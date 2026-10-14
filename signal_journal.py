"""
信号复盘日志：把每天的龙头梯队 / ★买点 / 昨弱今强 / 作战台候选记下来，再跟踪之后 5 个交易日的真实走势。

为什么要单独记：龙头梯队和候选池都是实时计算的，收盘后就没了；回测实验室是用历史涨停池"重算"信号，
和当天界面上实际看到的不完全一样（盘中出现过、后来炸板消失的买点，回测里就没有）。

记录口径
--------
- 盘中每 2 分钟记一次（服务开着时），同一天同一只票只保留一行：
  首次出现时间、★买点首次出现时间、作战台候选首次出现时间保留"第一次"，其他字段取最新；
  "当天出现过★买点 / 昨弱今强"记为 *_any（你当时在界面上能看到它）。
- 收盘后（15:05 起）再记一次收盘版，并标记哪些票收盘仍封住涨停（closed_limit_up），没封住的就是盘中炸板。
- 历史回补：东财历史涨停池约能回溯 1 个月，用当时的涨停池按同一套梯队规则重算（origin=backfill）。
  回补的记录只有收盘口径，没有盘中时间，也没有作战台候选（候选池无法事后重建）。

后续表现（两种买入口径）
------------------------
- 当日排板：信号日按涨停价买入。一字 / 秒板 / 封死（换手 < 1%）视为买不进（与龙头决策同一口径）。
  盘中出现、收盘没封住的票，排板买入价仍是涨停价，所以当日就会体现炸板的亏损。
- 次日开盘：第二天开盘价买入。次日开盘即涨停（一字 / 秒开涨停）视为买不进。
- 收益 = 第 1 / 3 / 5 个交易日收盘价 ÷ 买入价 - 1；另算 5 日内最大涨幅 / 最大回撤、后续连板数、次日开盘溢价。
- 统计只算"买得进"的样本，买不进的单独计数（不然一字连板会把收益吹得很好看）。
- K 线用前复权；当天收盘前不使用当天的 K 线。
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

from buyability import check_limit_buyability
from logger_config import get_logger

logger = get_logger(__name__)

TZ = ZoneInfo("Asia/Shanghai")
HORIZONS = (1, 3, 5)
FOLLOW_DAYS = max(HORIZONS)
LEADER_MIN_SECTOR = 3  # 单只涨停的题材里"龙头"没有意义，不计入题材龙头

# 筛选 / 分组口径（前端的"信号类型"）
SIGNAL_TYPES: Dict[str, str] = {
    "buy_hint": "★买点",
    "leader": "题材龙头",      # 所在题材当天 ≥3 只涨停的龙头（与龙头战法"板块效应"同一门槛）
    "wts": "昨弱今强",
    "candidate": "作战台候选",
    "divergent": "分歧",
    "consensus": "一致",
    "all": "全部涨停",
}

_COLUMNS = (
    "trade_date", "code", "name", "sector", "sector_count", "sector_rank", "role", "limit_count",
    "seal_amount", "first_limit_time", "turnover_rate", "break_count", "divergence", "buy_hint",
    "buy_hint_any", "buy_hint_first_at", "cross", "wts_any", "sell_alert", "cycle", "candidate_tier",
    "candidate_first_at", "first_seen_at", "last_seen_at", "closed_limit_up", "origin",
    "outcome", "outcome_complete", "outcome_at",
)


def matches(row: Dict[str, Any], signal: str) -> bool:
    if signal == "buy_hint":
        return bool(row.get("buy_hint_any"))
    if signal == "leader":
        return row.get("role") == "龙头" and int(row.get("sector_count") or 0) >= LEADER_MIN_SECTOR
    if signal == "wts":
        return bool(row.get("wts_any"))
    if signal == "candidate":
        return bool(row.get("candidate_tier"))
    if signal == "divergent":
        return row.get("divergence") == "分歧"
    if signal == "consensus":
        return row.get("divergence") == "一致"
    return True


def cycle_of(rate: Optional[float]) -> str:
    """与 DragonLadder.build 相同的接力周期阈值。"""
    if rate is None:
        return "未知"
    return "强" if rate >= 0.4 else "中" if rate >= 0.2 else "弱"


# ---------------------------------------------------------------------------
# 从梯队 / 候选池提取当天信号（纯函数）
# ---------------------------------------------------------------------------

def extract_signals(ladder: Dict[str, Any], workbench: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    cycle = ((ladder or {}).get("spirit") or {}).get("cycle") or "未知"
    tiers: Dict[str, str] = {}
    for tier in ("primary", "watch"):
        for c in (workbench or {}).get(tier) or []:
            code = str(c.get("code") or "")
            if code and code not in tiers:
                tiers[code] = tier
    out = []
    for rank, sec in enumerate((ladder or {}).get("sectors") or [], 1):
        for it in sec.get("stocks") or []:
            code = str(it.get("code") or "")
            if not code:
                continue
            out.append({
                "code": code,
                "name": it.get("name") or "",
                "sector": sec.get("sector") or "",
                "sector_count": int(sec.get("count") or 0),
                "sector_rank": rank,
                "role": it.get("role") or "",
                "limit_count": int(it.get("limit_count") or 1),
                "seal_amount": float(it.get("seal_amount") or 0),
                "first_limit_time": str(it.get("first_limit_time") or ""),
                "turnover_rate": float(it.get("turnover_rate") or 0),
                "break_count": int(it.get("break_count") or 0),
                "divergence": it.get("divergence") or "",
                "buy_hint": bool(it.get("buy_hint")),
                "cross": it.get("cross") or "",
                "sell_alert": bool(it.get("sell_alert")),
                "cycle": cycle,
                "candidate_tier": tiers.get(code),
            })
    return out


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------

class JournalStore:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            from runtime_paths import application_data_dir

            out = application_data_dir() / "outputs"
            out.mkdir(parents=True, exist_ok=True)
            db_path = out / "signal_journal.db"
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    trade_date TEXT NOT NULL, code TEXT NOT NULL, name TEXT, sector TEXT,
                    sector_count INTEGER, sector_rank INTEGER, role TEXT, limit_count INTEGER,
                    seal_amount REAL, first_limit_time TEXT, turnover_rate REAL, break_count INTEGER,
                    divergence TEXT, buy_hint INTEGER, buy_hint_any INTEGER, buy_hint_first_at TEXT,
                    cross TEXT, wts_any INTEGER, sell_alert INTEGER, cycle TEXT, candidate_tier TEXT,
                    candidate_first_at TEXT, first_seen_at TEXT, last_seen_at TEXT, closed_limit_up INTEGER,
                    origin TEXT, outcome TEXT, outcome_complete INTEGER DEFAULT 0, outcome_at TEXT,
                    PRIMARY KEY (trade_date, code)
                )""")
            c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            c.execute("""
                CREATE TABLE IF NOT EXISTS lab_presets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, spec TEXT NOT NULL,
                    created_by TEXT, created_at TEXT
                )""")

    @contextmanager
    def _conn(self):
        """提交并关闭（sqlite3 自带的 with 只提交不关闭，长期运行会泄漏文件句柄）。"""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 元信息（例如某天的收盘版是否已记录）----
    def get_meta(self, key: str) -> Optional[str]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return r["value"] if r else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    # ---- 回测实验室保存的策略（条件组合）----
    def list_presets(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM lab_presets ORDER BY id DESC")]
        for r in rows:
            r["spec"] = json.loads(r["spec"])
        return rows

    def add_preset(self, name: str, spec: Dict[str, Any], created_by: str, at: str) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO lab_presets(name, spec, created_by, created_at) VALUES (?, ?, ?, ?)",
                            (name, json.dumps(spec, ensure_ascii=False), created_by, at))
            return int(cur.lastrowid)

    def get_preset(self, pid: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM lab_presets WHERE id=?", (pid,)).fetchone()
            return dict(r) if r else None

    def delete_preset(self, pid: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM lab_presets WHERE id=?", (pid,))

    # ---- 写入 ----
    def upsert(self, trade_date: str, items: Sequence[Dict[str, Any]], seen_at: str,
               origin: str = "live", final: bool = False) -> int:
        """
        合并写入一天的信号。final=True 表示这是收盘版：池子里的票 closed_limit_up=1，
        当天之前出现过、收盘不在池子里的票 closed_limit_up=0（盘中炸板）。
        """
        with self._lock, self._conn() as c:
            existing = {
                r["code"]: dict(r)
                for r in c.execute("SELECT * FROM signals WHERE trade_date=?", (trade_date,))
            }
            seen_codes = set()
            for it in items:
                code = it["code"]
                seen_codes.add(code)
                old = existing.get(code)
                if old and old.get("origin") == "live" and origin == "backfill":
                    continue  # 实盘记录更全，回补不覆盖
                row = dict(old or {})
                row.update({k: it.get(k) for k in (
                    "name", "sector", "sector_count", "sector_rank", "role", "limit_count", "seal_amount",
                    "first_limit_time", "turnover_rate", "break_count", "divergence", "cross", "cycle",
                )})
                row["trade_date"], row["code"] = trade_date, code
                row["buy_hint"] = int(bool(it.get("buy_hint")))
                row["sell_alert"] = int(bool(it.get("sell_alert")))
                if it.get("buy_hint"):
                    row["buy_hint_any"] = 1
                    row["buy_hint_first_at"] = row.get("buy_hint_first_at") or seen_at
                row["buy_hint_any"] = int(bool(row.get("buy_hint_any")))
                row["wts_any"] = int(bool(row.get("wts_any")) or it.get("cross") == "昨弱今强")
                tier = it.get("candidate_tier")
                if tier:
                    if row.get("candidate_tier") != "primary":  # 当天进过优先关注就一直记为优先
                        row["candidate_tier"] = tier
                    row["candidate_first_at"] = row.get("candidate_first_at") or seen_at
                row["first_seen_at"] = row.get("first_seen_at") or seen_at
                row["last_seen_at"] = seen_at
                row["origin"] = row.get("origin") or origin
                if final:
                    row["closed_limit_up"] = 1
                self._write(c, row)
            if final:
                for code, old in existing.items():
                    if code not in seen_codes and old.get("origin") == "live":
                        c.execute("UPDATE signals SET closed_limit_up=0 WHERE trade_date=? AND code=?",
                                  (trade_date, code))
            return len(seen_codes)

    @staticmethod
    def _write(c, row: Dict[str, Any]) -> None:
        cols = [k for k in _COLUMNS if k in row]
        c.execute(
            f"INSERT OR REPLACE INTO signals ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [row[k] for k in cols],
        )

    def save_outcome(self, trade_date: str, code: str, outcome: Optional[Dict[str, Any]], at: str) -> None:
        complete = int(bool(outcome and outcome.get("complete")))
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE signals SET outcome=?, outcome_complete=?, outcome_at=? WHERE trade_date=? AND code=?",
                (json.dumps(outcome, ensure_ascii=False) if outcome else None, complete, at, trade_date, code),
            )

    # ---- 读取 ----
    def query(self, start: str, end: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM signals WHERE trade_date BETWEEN ? AND ? "
                "ORDER BY trade_date DESC, sector_rank ASC, limit_count DESC", (start, end))]
        for r in rows:
            r["outcome"] = json.loads(r["outcome"]) if r.get("outcome") else None
            for k in ("buy_hint", "buy_hint_any", "wts_any", "sell_alert", "outcome_complete"):
                r[k] = bool(r.get(k))
            if r.get("closed_limit_up") is not None:
                r["closed_limit_up"] = bool(r["closed_limit_up"])
        return rows

    def pending_outcomes(self, since: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT trade_date, code, name, limit_count, first_limit_time, turnover_rate, closed_limit_up FROM signals "
                "WHERE outcome_complete=0 AND trade_date >= ? ORDER BY code", (since,))]

    def dates(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT trade_date, COUNT(*) AS n, MIN(origin) AS origin FROM signals "
                "GROUP BY trade_date ORDER BY trade_date DESC")]


# ---------------------------------------------------------------------------
# 后续表现（纯函数）
# ---------------------------------------------------------------------------

def limit_pct(code: str, name: str = "") -> float:
    if "ST" in (name or "").upper():
        return 5.0
    if code.startswith(("30", "68")):
        return 20.0
    if code.startswith(("4", "8", "92")):
        return 30.0
    return 10.0


def limit_price(prev_close: float, pct: float) -> float:
    return round(prev_close * (1 + pct / 100) + 1e-9, 2)


def _at_limit(price: float, prev_close: float, pct: float) -> bool:
    return prev_close > 0 and price >= limit_price(prev_close, pct) - 0.011


def _pct(a: float, b: float) -> Optional[float]:
    return round((a / b - 1) * 100, 2) if a and b else None


def compute_outcome(rec: Dict[str, Any], bars: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    rec：一条信号记录（trade_date / code / name / first_limit_time / turnover_rate / closed_limit_up）。
    bars：按日期升序的日 K（date / open / high / low / close），只含已收盘的交易日。
    """
    dates = [b["date"] for b in bars]
    if rec["trade_date"] not in dates:
        return None
    i = dates.index(rec["trade_date"])
    d0 = bars[i]
    prev0 = bars[i - 1]["close"] if i > 0 else None
    pct = limit_pct(rec["code"], rec.get("name") or "")
    after = list(bars[i + 1:i + 1 + FOLLOW_DAYS])

    follow, prev, streak, counting = [], d0["close"], 0, True
    for b in after:
        at_limit = _at_limit(b["close"], prev, pct)
        one_word = at_limit and b["low"] >= limit_price(prev, pct) - 0.011
        follow.append({
            "date": b["date"], "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
            "pct": _pct(b["close"], prev), "limit": at_limit, "one_word": one_word,
        })
        if counting and at_limit:
            streak += 1
        else:
            counting = False
        prev = b["close"]

    def mode(entry: Optional[float], buyable: bool, reason: str, window: List[Dict[str, Any]]):
        res = {"entry": round(entry, 2) if entry else None, "buyable": buyable, "reason": reason}
        for h in HORIZONS:
            res[f"ret_{h}"] = _pct(after[h - 1]["close"], entry) if entry and len(after) >= h else None
        if entry and window:
            res["max_gain"] = _pct(max(b["high"] for b in window), entry)
            res["max_drawdown"] = _pct(min(b["low"] for b in window), entry)
        else:
            res["max_gain"] = res["max_drawdown"] = None
        return res

    # 当日排板：涨停价买入（盘中炸板的票同样按涨停价算，体现炸板亏损）
    lp0 = limit_price(prev0, pct) if prev0 else None
    can_buy, why = check_limit_buyability(rec.get("first_limit_time"), rec.get("turnover_rate"))
    same_entry = lp0 or d0["close"]
    same_day = mode(same_entry, can_buy, "" if can_buy else why, after)
    same_day["day0_ret"] = _pct(d0["close"], same_entry)  # 当天收盘相对排板价（炸板会是负数）

    # 次日开盘
    if after:
        d1 = after[0]
        opened_limit = _at_limit(d1["open"], d0["close"], pct)
        next_open = mode(d1["open"], not opened_limit,
                         "次日开盘即涨停，买不进" if opened_limit else "", after)
    else:
        next_open = mode(None, False, "还没有次日行情", [])

    return {
        "limit_pct": pct,
        "day0_close": d0["close"],
        "closed_at_limit": _at_limit(d0["close"], prev0, pct) if prev0 else None,
        "next_open_pct": _pct(after[0]["open"], d0["close"]) if after else None,
        "next_close_pct": _pct(after[0]["close"], d0["close"]) if after else None,
        "next_limit_up": bool(after and follow[0]["limit"]),
        "streak": streak,                      # 信号日之后连续涨停的天数
        "height_after": int(rec.get("limit_count") or 1) + streak,
        "follow": follow,
        "days": len(after),
        "complete": len(after) >= FOLLOW_DAYS,
        "same_day": same_day,
        "next_open": next_open,
    }


# ---------------------------------------------------------------------------
# 统计（纯函数）
# ---------------------------------------------------------------------------

def _avg(xs: List[float]) -> Optional[float]:
    return round(statistics.mean(xs), 2) if xs else None


def summarize(rows: Iterable[Dict[str, Any]], mode: str) -> Dict[str, Dict[str, Any]]:
    rows = list(rows)
    out = {}
    for key, label in SIGNAL_TYPES.items():
        group = [r for r in rows if matches(r, key)]
        witho = [r for r in group if r.get("outcome")]
        res = [r["outcome"][mode] for r in witho]
        buyable = [m for m in res if m.get("buyable")]
        stats: Dict[str, Any] = {
            "label": label,
            "n": len(group),
            "with_outcome": len(witho),
            "unbuyable": sum(1 for m in res if not m.get("buyable") and m.get("entry")),
            "buyable": len(buyable),
        }
        for h in HORIZONS:
            xs = [m[f"ret_{h}"] for m in buyable if m.get(f"ret_{h}") is not None]
            stats[f"n_{h}"] = len(xs)
            stats[f"win_{h}"] = round(sum(1 for x in xs if x > 0) / len(xs), 3) if xs else None
            stats[f"avg_{h}"] = _avg(xs)
            stats[f"median_{h}"] = round(statistics.median(xs), 2) if xs else None
        nxt = [r["outcome"] for r in witho if r["outcome"].get("days")]
        stats["next_limit_rate"] = round(sum(1 for o in nxt if o["next_limit_up"]) / len(nxt), 3) if nxt else None
        stats["avg_next_open"] = _avg([o["next_open_pct"] for o in nxt if o.get("next_open_pct") is not None])
        stats["avg_streak"] = _avg([float(o["streak"]) for o in nxt])
        stats["avg_max_gain"] = _avg([m["max_gain"] for m in buyable if m.get("max_gain") is not None])
        stats["avg_max_drawdown"] = _avg([m["max_drawdown"] for m in buyable if m.get("max_drawdown") is not None])
        out[key] = stats
    return out


# ---------------------------------------------------------------------------
# 记录 / 更新 / 回补（外部数据都从参数注入，便于测试）
# ---------------------------------------------------------------------------

def now_sh() -> datetime:
    return datetime.now(TZ)


def bars_complete_until(now: datetime) -> date:
    """可以使用到哪一天的日 K：15:10 之后含当天，否则只到昨天。"""
    local = now.astimezone(TZ) if now.tzinfo else now.replace(tzinfo=TZ)
    return local.date() if (local.hour, local.minute) >= (15, 10) else local.date() - timedelta(days=1)


class JournalService:
    def __init__(self, store: Optional[JournalStore] = None, clock: Callable[[], datetime] = now_sh):
        self.store = store or JournalStore()
        self.clock = clock

    # ---- 实盘记录 ----
    def record(self, ladder: Dict[str, Any], workbench: Optional[Dict[str, Any]] = None,
               final: bool = False) -> int:
        """记一次。ladder 的数据日期必须是今天（降级到昨日快照时不记，避免把昨天的票记成今天）。"""
        now = self.clock()
        today = now.date().isoformat()
        data_as_of = str((ladder or {}).get("data_as_of") or "")[:10]
        if (ladder or {}).get("data_stale") or (data_as_of and data_as_of != today):
            logger.info(f"[journal] 涨停池不是今天的数据（{data_as_of or '未知'}），跳过记录")
            return 0
        items = extract_signals(ladder, workbench)
        if not items:
            return 0
        n = self.store.upsert(today, items, now.strftime("%Y-%m-%d %H:%M:%S"), "live", final=final)
        if final:
            self.store.set_meta(f"final:{today}", now.strftime("%Y-%m-%d %H:%M:%S"))
        return n

    def finalized(self, day: str) -> bool:
        return self.store.get_meta(f"final:{day}") is not None

    # ---- 后续表现 ----
    def update_outcomes(self, bars_of: Callable[[str], List[Dict[str, Any]]], lookback_days: int = 60,
                        progress: Optional[Callable[..., None]] = None,
                        cancelled: Optional[Callable[[], bool]] = None) -> Dict[str, int]:
        now = self.clock()
        until = bars_complete_until(now).isoformat()
        since = (now.date() - timedelta(days=lookback_days)).isoformat()
        pending = [p for p in self.store.pending_outcomes(since) if p["trade_date"] <= until]
        by_code: Dict[str, List[Dict[str, Any]]] = {}
        for p in pending:
            by_code.setdefault(p["code"], []).append(p)
        done = errors = 0
        total = len(by_code)
        for idx, (code, recs) in enumerate(by_code.items(), 1):
            if cancelled and cancelled():
                raise RuntimeError("用户已取消")
            if progress and (idx == 1 or idx % 5 == 0 or idx == total):
                progress(phase="更新后续表现", message=f"读取日K {idx}/{total}", done=idx - 1, total=total)
            try:
                bars = [b for b in (bars_of(code) or []) if b["date"] <= until]
            except Exception as exc:
                logger.info(f"[journal] {code} 日K获取失败: {exc}")
                errors += 1
                continue
            for rec in recs:
                outcome = compute_outcome(rec, bars)
                if outcome is not None:
                    self.store.save_outcome(rec["trade_date"], code, outcome, now.strftime("%Y-%m-%d %H:%M:%S"))
                    done += 1
        return {"codes": total, "records": len(pending), "updated": done, "errors": errors}

    # ---- 历史回补 ----
    def backfill(self, days: int, *, trading_days: Callable[[date, date], List[date]],
                 zt_pool_of: Callable[[date], List[Dict[str, Any]]], build_sectors: Callable[..., List[Dict]],
                 progress: Optional[Callable[..., None]] = None,
                 cancelled: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
        now = self.clock()
        last = bars_complete_until(now)
        tdays = [d for d in trading_days(last - timedelta(days=days * 2 + 20), last) if d <= last][-(days + 1):]
        filled, skipped, empty = 0, 0, []
        prev_pool: Optional[List[Dict[str, Any]]] = None
        for idx, d in enumerate(tdays):
            if cancelled and cancelled():
                raise RuntimeError("用户已取消")
            if progress:
                progress(phase="回补历史信号", message=f"{d.isoformat()} 涨停池（{idx + 1}/{len(tdays)}）",
                         done=idx, total=len(tdays))
            pool = zt_pool_of(d) or []
            if idx == 0:  # 第一天只用来提供"昨日"对比
                prev_pool = pool
                continue
            if not pool:
                empty.append(d.isoformat())
                prev_pool = pool
                continue
            prev_map = {str(p.get("code")): p for p in (prev_pool or [])}
            rate = None
            if prev_pool:
                today_codes = {str(p.get("code")) for p in pool}
                rate = sum(1 for c in prev_map if c in today_codes) / len(prev_map)
            ladder = {"spirit": {"cycle": cycle_of(rate)}, "sectors": build_sectors(pool, prev_map)}
            n = self.store.upsert(d.isoformat(), extract_signals(ladder), f"{d.isoformat()} 15:00:00",
                                  "backfill", final=True)
            filled += n
            if n == 0:
                skipped += 1
            prev_pool = pool
        return {"days": len(tdays) - 1, "records": filled, "empty_days": empty}


def tencent_bars(client, code: str, count: int = 260) -> List[Dict[str, Any]]:
    """腾讯日 K（前复权）：单次请求、国内源，比 AKShare 新浪接口快。返回升序 [{date, open, high, low, close}]。"""
    market = "sh" if code.startswith(("6", "9")) else "bj" if code.startswith(("4", "8")) else "sz"
    symbol = f"{market}{code}"
    res = client.get("tencent", "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                     params={"param": f"{symbol},day,,,{count},qfq"})
    if not res.ok:
        raise RuntimeError(res.error)
    data = ((res.response.json() or {}).get("data") or {}).get(symbol) or {}
    rows = data.get("qfqday") or data.get("day") or []
    out = []
    for r in rows:
        try:  # [日期, 开, 收, 高, 低, 量]
            out.append({"date": r[0], "open": float(r[1]), "close": float(r[2]),
                        "high": float(r[3]), "low": float(r[4])})
        except (IndexError, TypeError, ValueError):
            continue
    if not out:
        raise RuntimeError("腾讯日K为空")
    return out


__all__ = [
    "HORIZONS", "SIGNAL_TYPES", "JournalService", "JournalStore", "compute_outcome", "cycle_of",
    "extract_signals", "limit_pct", "matches", "summarize", "tencent_bars",
]
