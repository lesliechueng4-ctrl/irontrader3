"""
回测分析台：在"信号复盘"的逐笔记录上，按任意条件组合回答"这类票买进去到底怎么样"。

数据只有一份：signal_journal.db（实盘记录 + 历史回补 + 导入的旧回测样本），回测实验室和信号复盘口径完全一致。

一笔交易的收益 = 该买入口径下第 H 日收盘收益 - 往返成本；买不进的（一字 / 秒板 / 次日开盘即涨停）不计入，单独计数。

注意：
- 资金曲线：资金分成 N 份（N = 持有天数）轮动，每个信号日用一份等权买入当天所有符合条件的票，
  所以每天累加"当日平均收益 ÷ N"。用来看策略在哪段时间失效，不是真实账户净值（没算仓位上限、空仓日资金闲置等）。
- 自动发现只列样本 ≥ MIN_FINDING_N 的组合；拆分越细越容易"挖出"偶然规律，样本数一定要一起看。
"""

from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, Tuple

import signal_journal as sj

MIN_BUCKET_N = 10        # 维度拆解里样本少于这个数的分组置灰
MIN_FINDING_N = 20       # 自动发现的最小样本
FINDINGS_PER_SIDE = 6

# ---------------------------------------------------------------------------
# 分桶
# ---------------------------------------------------------------------------

def minutes_of(t: Any) -> Optional[int]:
    s = str(t or "").strip()
    if not s or s in ("nan", "None"):
        return None
    try:
        if ":" in s:
            h, m = s.split(":")[:2]
            return int(h) * 60 + int(m)
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 4:
            return int(digits[:2]) * 60 + int(digits[2:4])
    except ValueError:
        return None
    return None


TIME_BUCKETS = [  # (key, 标签, 上限分钟含)
    ("auction", "开盘即封（≤9:30）", 9 * 60 + 30),
    ("open", "9:30–10:00", 10 * 60),
    ("morning", "10:00–11:30", 11 * 60 + 30),
    ("afternoon", "13:00–14:30", 14 * 60 + 30),
    ("late", "14:30 后", 24 * 60),
]


def time_bucket(row: Dict[str, Any]) -> Optional[str]:
    m = minutes_of(row.get("first_limit_time"))
    if m is None:
        return None
    for key, _label, upper in TIME_BUCKETS:
        if m <= upper:
            return key
    return "late"


TURNOVER_BUCKETS = [("t0", "<3%", 3), ("t1", "3–8%", 8), ("t2", "8–15%", 15), ("t3", "15–25%", 25), ("t4", "≥25%", 1e9)]


def turnover_bucket(row: Dict[str, Any]) -> Optional[str]:
    v = row.get("turnover_rate")
    if v is None:
        return None
    for key, _label, upper in TURNOVER_BUCKETS:
        if float(v) < upper:
            return key
    return "t4"


def limit_bucket(row: Dict[str, Any]) -> str:
    n = int(row.get("limit_count") or 1)
    return f"b{min(n, 5)}"


def sector_bucket(row: Dict[str, Any]) -> str:
    n = int(row.get("sector_count") or 0)
    return "s0" if n <= 0 else "s1" if n == 1 else "s2" if n == 2 else "s3" if n <= 4 else "s5"


def signal_bucket(row: Dict[str, Any]) -> str:
    if row.get("buy_hint_any"):
        return "buy_hint"
    if row.get("wts_any"):
        return "wts"
    return "plain"


DIMENSIONS: Dict[str, Dict[str, Any]] = {
    "signal": {"label": "信号", "fn": signal_bucket,
               "buckets": [("buy_hint", "★买点"), ("wts", "昨弱今强（无★）"), ("plain", "无买点信号")]},
    "cycle": {"label": "接力周期", "fn": lambda r: r.get("cycle") if r.get("cycle") in ("强", "中", "弱") else None,
              "buckets": [("强", "强"), ("中", "中"), ("弱", "弱")]},
    "limit": {"label": "板数", "fn": limit_bucket,
              "buckets": [("b1", "首板"), ("b2", "2板"), ("b3", "3板"), ("b4", "4板"), ("b5", "5板+")]},
    "time": {"label": "首封时间", "fn": time_bucket, "buckets": [(k, label) for k, label, _ in TIME_BUCKETS]},
    "turnover": {"label": "换手", "fn": turnover_bucket, "buckets": [(k, label) for k, label, _ in TURNOVER_BUCKETS]},
    "divergence": {"label": "分歧 / 一致", "fn": lambda r: r.get("divergence") or None,
                   "buckets": [("分歧", "分歧"), ("中性", "中性"), ("一致", "一致")]},
    "role": {"label": "题材地位", "fn": lambda r: r.get("role") or None,
             "buckets": [("龙头", "龙头"), ("龙二", "龙二"), ("龙三", "龙三"), ("梯队", "梯队")]},
    "sector": {"label": "题材涨停家数", "fn": sector_bucket,
               "buckets": [("s1", "1 家"), ("s2", "2 家"), ("s3", "3–4 家"), ("s5", "5 家+"), ("s0", "未知（旧样本）")]},
    "breaks": {"label": "盘中炸板", "fn": lambda r: "b0" if not int(r.get("break_count") or 0) else "b1",
               "buckets": [("b0", "没炸过"), ("b1", "炸过回封")]},
}

# 自动发现参与组合的维度（题材家数旧样本缺失、炸板与分歧高度相关，不参与组合，避免重复发现）
FINDING_DIMS = ("signal", "cycle", "limit", "time", "turnover", "divergence", "role")


# ---------------------------------------------------------------------------
# 条件筛选
# ---------------------------------------------------------------------------

DEFAULT_SPEC: Dict[str, Any] = {
    "signals": [], "signal_logic": "any", "roles": [], "divergence": [], "limit_min": None, "limit_max": None,
    "times": [], "turnover_min": None, "turnover_max": None, "breaks": "any", "sector_min": None, "cycles": [],
    "closed_only": False, "include_legacy": True,
    "mode": "next_open", "horizon": 3, "cost": 0.3,
}


def normalize_spec(spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = {**DEFAULT_SPEC, **{k: v for k, v in (spec or {}).items() if k in DEFAULT_SPEC or k in ("start", "end")}}
    if out["mode"] not in ("next_open", "same_day"):
        out["mode"] = "next_open"
    if out["horizon"] not in (1, 3, 5):
        out["horizon"] = 3
    try:
        out["cost"] = max(0.0, min(5.0, float(out["cost"] or 0)))
    except (TypeError, ValueError):
        out["cost"] = 0.0
    return out


def _signal_ok(row: Dict[str, Any], key: str) -> bool:
    return sj.matches(row, key)


def passes(row: Dict[str, Any], spec: Dict[str, Any]) -> bool:
    if not spec["include_legacy"] and row.get("origin") == "legacy":
        return False
    sigs = spec["signals"]
    if sigs:
        hits = [_signal_ok(row, s) for s in sigs]
        if not (all(hits) if spec["signal_logic"] == "all" else any(hits)):
            return False
    if spec["roles"] and row.get("role") not in spec["roles"]:
        return False
    if spec["divergence"] and row.get("divergence") not in spec["divergence"]:
        return False
    lc = int(row.get("limit_count") or 1)
    if spec["limit_min"] is not None and lc < int(spec["limit_min"]):
        return False
    if spec["limit_max"] is not None and lc > int(spec["limit_max"]):
        return False
    if spec["times"] and time_bucket(row) not in spec["times"]:
        return False
    tr = row.get("turnover_rate")
    if spec["turnover_min"] is not None and (tr is None or float(tr) < float(spec["turnover_min"])):
        return False
    if spec["turnover_max"] is not None and (tr is None or float(tr) > float(spec["turnover_max"])):
        return False
    breaks = int(row.get("break_count") or 0)
    if spec["breaks"] == "none" and breaks:
        return False
    if spec["breaks"] == "some" and not breaks:
        return False
    if spec["sector_min"] is not None and int(row.get("sector_count") or 0) < int(spec["sector_min"]):
        return False
    if spec["cycles"] and row.get("cycle") not in spec["cycles"]:
        return False
    if spec["closed_only"] and row.get("closed_limit_up") is False:
        return False
    return True


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------

def trade_return(row: Dict[str, Any], mode: str, horizon: int, cost: float) -> Tuple[str, Optional[float]]:
    """返回 (状态, 扣成本后的收益%)。状态：trade / unbuyable / pending。"""
    o = row.get("outcome") or {}
    m = o.get(mode) or {}
    if not m or m.get("entry") is None:
        return "pending", None
    if not m.get("buyable"):
        return "unbuyable", None
    r = m.get(f"ret_{horizon}")
    if r is None:
        return "pending", None
    return "trade", round(float(r) - cost, 3)


def _r(x: Optional[float], nd: int = 2) -> Optional[float]:
    return None if x is None else round(x, nd)


def metrics(rows: Sequence[Dict[str, Any]], spec: Dict[str, Any]) -> Dict[str, Any]:
    mode, h, cost = spec["mode"], spec["horizon"], spec["cost"]
    rs, unbuyable, pending = [], 0, 0
    max_gain, max_dd = [], []
    next_limit = []
    for row in rows:
        state, r = trade_return(row, mode, h, cost)
        if state == "unbuyable":
            unbuyable += 1
        elif state == "pending":
            pending += 1
        else:
            rs.append(r)
            m = row["outcome"][mode]
            if m.get("max_gain") is not None:
                max_gain.append(m["max_gain"])
            if m.get("max_drawdown") is not None:
                max_dd.append(m["max_drawdown"])
        o = row.get("outcome") or {}
        if o.get("days"):
            next_limit.append(bool(o.get("next_limit_up")))
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x <= 0]
    avg_win = statistics.mean(wins) if wins else None
    avg_loss = statistics.mean(losses) if losses else None
    return {
        "signals": len(rows),
        "n": len(rs),
        "unbuyable": unbuyable,
        "pending": pending,
        "unbuyable_rate": _r(unbuyable / (unbuyable + len(rs)), 3) if (unbuyable + len(rs)) else None,
        "win": _r(len(wins) / len(rs), 3) if rs else None,
        "avg": _r(statistics.mean(rs)) if rs else None,
        "median": _r(statistics.median(rs)) if rs else None,
        "std": _r(statistics.pstdev(rs)) if len(rs) > 1 else None,
        "best": _r(max(rs)) if rs else None,
        "worst": _r(min(rs)) if rs else None,
        "avg_win": _r(avg_win),
        "avg_loss": _r(avg_loss),
        "payoff": _r(avg_win / abs(avg_loss)) if avg_win is not None and avg_loss else None,
        "profit_factor": _r(sum(wins) / abs(sum(losses))) if wins and losses and sum(losses) else None,
        "avg_max_gain": _r(statistics.mean(max_gain)) if max_gain else None,
        "avg_max_drawdown": _r(statistics.mean(max_dd)) if max_dd else None,
        "next_limit_rate": _r(sum(next_limit) / len(next_limit), 3) if next_limit else None,
    }


HIST_EDGES = [-10, -6, -3, -1, 1, 3, 6, 10]


def histogram(rows: Sequence[Dict[str, Any]], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels = (["≤-10%"] + [f"{a}~{b}%" for a, b in zip(HIST_EDGES, HIST_EDGES[1:])] + ["≥10%"])
    counts = [0] * (len(HIST_EDGES) + 1)
    for row in rows:
        state, r = trade_return(row, spec["mode"], spec["horizon"], spec["cost"])
        if state != "trade":
            continue
        i = 0
        while i < len(HIST_EDGES) and r >= HIST_EDGES[i]:
            i += 1
        counts[i] += 1
    total = sum(counts)
    return [{"label": label, "count": c, "share": _r(c / total, 3) if total else 0,
             "side": "loss" if i < 4 else "flat" if i == 4 else "gain"}
            for i, (label, c) in enumerate(zip(labels, counts))]


def equity(rows: Sequence[Dict[str, Any]], base_rows: Sequence[Dict[str, Any]], spec: Dict[str, Any]) -> Dict[str, Any]:
    def daily(rs):
        by: Dict[str, List[float]] = {}
        for row in rs:
            state, r = trade_return(row, spec["mode"], spec["horizon"], spec["cost"])
            if state == "trade":
                by.setdefault(row["trade_date"], []).append(r)
        return {d: statistics.mean(v) for d, v in by.items()}, {d: len(v) for d, v in by.items()}

    slots = max(1, int(spec["horizon"]))  # 持有 N 天 → 资金分 N 份轮动，避免重叠持仓被重复累加
    mine, counts = daily(rows)
    base, _ = daily(base_rows)
    dates = sorted(set(mine) | set(base))
    cum = bcum = peak = 0.0
    max_dd = 0.0
    series = []
    for d in dates:
        if d in mine:
            cum += mine[d] / slots
        bcum += base.get(d, 0.0) / slots
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)
        series.append({"date": d, "n": counts.get(d, 0), "avg": _r(mine.get(d)), "cum": _r(cum),
                       "base_avg": _r(base.get(d)), "base_cum": _r(bcum)})
    active = [v for v in mine.values()]
    return {
        "series": series,
        "total": _r(cum),
        "base_total": _r(bcum),
        "max_drawdown": _r(max_dd),
        "days": len(active),
        "slots": slots,
        "win_days": sum(1 for v in active if v > 0),
    }


def breakdown(rows: Sequence[Dict[str, Any]], spec: Dict[str, Any], base_avg: Optional[float]) -> List[Dict[str, Any]]:
    out = []
    for key, dim in DIMENSIONS.items():
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            b = dim["fn"](row)
            if b is not None:
                groups.setdefault(b, []).append(row)
        buckets = []
        for bkey, label in dim["buckets"]:
            g = groups.get(bkey, [])
            if not g:
                continue
            m = metrics(g, spec)
            buckets.append({
                "key": bkey, "label": label, "signals": m["signals"], "n": m["n"], "win": m["win"], "avg": m["avg"],
                "median": m["median"], "unbuyable": m["unbuyable"],
                "excess": _r(m["avg"] - base_avg) if m["avg"] is not None and base_avg is not None else None,
                "reliable": m["n"] >= MIN_BUCKET_N,
                "patch": _spec_patch(key, bkey),
            })
        if len(buckets) >= 2:
            out.append({"key": key, "label": dim["label"], "buckets": buckets})
    return out


def _spec_patch(dim: str, bucket: str) -> Dict[str, Any]:
    """把一个"维度=分组"翻译成条件，前端点"套用"时用。"""
    if dim == "signal":
        return {"signals": [bucket]} if bucket != "plain" else {}
    if dim == "cycle":
        return {"cycles": [bucket]}
    if dim == "limit":
        n = int(bucket[1:])
        return {"limit_min": n, "limit_max": None if n >= 5 else n}
    if dim == "time":
        return {"times": [bucket]}
    if dim == "turnover":
        bounds = {"t0": (None, 3), "t1": (3, 8), "t2": (8, 15), "t3": (15, 25), "t4": (25, None)}[bucket]
        return {"turnover_min": bounds[0], "turnover_max": bounds[1]}
    if dim == "divergence":
        return {"divergence": [bucket]}
    if dim == "role":
        return {"roles": [bucket]}
    if dim == "sector":
        return {"sector_min": {"s1": 1, "s2": 2, "s3": 3, "s5": 5}.get(bucket)} if bucket != "s0" else {}
    if dim == "breaks":
        return {"breaks": "none" if bucket == "b0" else "some"}
    return {}


def findings(rows: Sequence[Dict[str, Any]], spec: Dict[str, Any], base_avg: Optional[float]) -> Dict[str, List]:
    """在全部样本里找跑赢 / 跑输基准最明显的单维度和两两组合。"""
    if base_avg is None:
        return {"best": [], "worst": []}
    labels = {k: dict(DIMENSIONS[k]["buckets"]) for k in FINDING_DIMS}
    keyed = []
    for row in rows:
        state, r = trade_return(row, spec["mode"], spec["horizon"], spec["cost"])
        if state != "trade":
            continue
        keyed.append(({k: DIMENSIONS[k]["fn"](row) for k in FINDING_DIMS}, r))
    groups: Dict[Tuple, List[float]] = {}
    for buckets, r in keyed:
        for k in FINDING_DIMS:
            if buckets[k] is not None:
                groups.setdefault(((k, buckets[k]),), []).append(r)
        for a, b in combinations(FINDING_DIMS, 2):
            if buckets[a] is not None and buckets[b] is not None:
                groups.setdefault(((a, buckets[a]), (b, buckets[b])), []).append(r)
    items = []
    for key, rs in groups.items():
        if len(rs) < MIN_FINDING_N:
            continue
        # 两两组合里，若加上第二个条件样本数不变（例如"5板+"本来就全是龙头），就是重复发现，跳过
        if len(key) == 2 and any(len(groups.get((part,), [])) == len(rs) for part in key):
            continue
        # "无买点信号"这一组不单独当发现（它基本就是基准）
        if any(d == "signal" and b == "plain" for d, b in key):
            continue
        avg = statistics.mean(rs)
        patch: Dict[str, Any] = {}
        for d, b in key:
            patch.update(_spec_patch(d, b))
        items.append({
            "label": " · ".join(f"{DIMENSIONS[d]['label']}：{labels[d].get(b, b)}" for d, b in key),
            "n": len(rs), "avg": _r(avg), "win": _r(sum(1 for x in rs if x > 0) / len(rs), 3),
            "excess": _r(avg - base_avg), "patch": patch,
        })
    items.sort(key=lambda x: x["excess"], reverse=True)
    best = [i for i in items if i["excess"] > 0][:FINDINGS_PER_SIDE]
    worst = [i for i in reversed(items) if i["excess"] < 0][:FINDINGS_PER_SIDE]
    return {"best": best, "worst": worst}


def trade_rows(rows: Sequence[Dict[str, Any]], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        state, r = trade_return(row, spec["mode"], spec["horizon"], spec["cost"])
        o = row.get("outcome") or {}
        m = o.get(spec["mode"]) or {}
        out.append({
            "trade_date": row["trade_date"], "code": row["code"], "name": row.get("name"), "sector": row.get("sector"),
            "sector_count": row.get("sector_count"), "role": row.get("role"), "limit_count": row.get("limit_count"),
            "first_limit_time": row.get("first_limit_time"), "turnover_rate": row.get("turnover_rate"),
            "divergence": row.get("divergence"), "buy_hint_any": row.get("buy_hint_any"), "wts_any": row.get("wts_any"),
            "candidate_tier": row.get("candidate_tier"), "cycle": row.get("cycle"), "origin": row.get("origin"),
            "closed_limit_up": row.get("closed_limit_up"),
            "state": state, "ret": r, "reason": m.get("reason") or "",
            "entry": m.get("entry"), "next_open_pct": o.get("next_open_pct"), "streak": o.get("streak") if o.get("days") else None,
            "max_gain": m.get("max_gain"), "max_drawdown": m.get("max_drawdown"),
        })
    return out


def run(all_rows: Sequence[Dict[str, Any]], spec: Dict[str, Any]) -> Dict[str, Any]:
    spec = normalize_spec(spec)
    base_rows = [r for r in all_rows if spec["include_legacy"] or r.get("origin") != "legacy"]
    rows = [r for r in base_rows if passes(r, spec)]
    m = metrics(rows, spec)
    base = metrics(base_rows, spec)
    base_avg = base["avg"]
    return {
        "spec": spec,
        "metrics": m,
        "baseline": base,
        "excess": {
            "avg": _r(m["avg"] - base_avg) if m["avg"] is not None and base_avg is not None else None,
            "win": _r(m["win"] - base["win"], 3) if m["win"] is not None and base["win"] is not None else None,
        },
        "histogram": histogram(rows, spec),
        "equity": equity(rows, base_rows, spec),
        "breakdown": breakdown(rows, spec, base_avg),
        "findings": findings(base_rows, spec, base_avg),
        "trades": trade_rows(rows, spec),
        "dates": {"first": min((r["trade_date"] for r in base_rows), default=None),
                  "last": max((r["trade_date"] for r in base_rows), default=None),
                  "days": len({r["trade_date"] for r in base_rows})},
        "dimension_buckets": {k: [{"key": b, "label": label} for b, label in d["buckets"]] for k, d in DIMENSIONS.items()},
    }


# ---------------------------------------------------------------------------
# 结论翻转：每天保存一次主要信号的结论，与 7 天前的对比
# ---------------------------------------------------------------------------

VERDICT_SIGNALS = ("buy_hint", "leader", "wts", "divergent", "consensus")
VERDICT_SPEC = {"mode": "next_open", "horizon": 3, "cost": 0.3}


def _verdict(m: Dict[str, Any]) -> Optional[str]:
    if m["n"] < 10 or m["avg"] is None:
        return None
    if m["avg"] > 0 and m["win"] >= 0.5:
        return "有效"
    if m["avg"] < 0 and m["win"] < 0.5:
        return "无效"
    return "分化"


def verdicts(rows: Sequence[Dict[str, Any]], today: date, window_days: int = 30) -> Dict[str, Any]:
    since = (today - timedelta(days=window_days)).isoformat()
    recent = [r for r in rows if r["trade_date"] >= since]
    spec = normalize_spec(VERDICT_SPEC)
    out = {}
    for s in VERDICT_SIGNALS:
        m = metrics([r for r in recent if sj.matches(r, s)], spec)
        out[s] = {"label": sj.SIGNAL_TYPES[s], "n": m["n"], "win": m["win"], "avg": m["avg"], "verdict": _verdict(m)}
    return out


def update_verdicts(store: sj.JournalStore, rows: Sequence[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """保存今天的结论快照，返回相对 ≥7 天前快照的翻转（并存档，页面两周内显示）。"""
    history = json.loads(store.get_meta("lab:verdict_history") or "{}")
    now = verdicts(rows, today)
    history[today.isoformat()] = now
    # 只保留最近 60 天
    cutoff = (today - timedelta(days=60)).isoformat()
    history = {d: v for d, v in history.items() if d >= cutoff}
    store.set_meta("lab:verdict_history", json.dumps(history, ensure_ascii=False))

    older = sorted(d for d in history if d <= (today - timedelta(days=7)).isoformat())
    if not older:
        return []
    prev_day = older[-1]
    prev = history[prev_day]
    flips = []
    for s, cur in now.items():
        p = prev.get(s) or {}
        if cur["verdict"] and p.get("verdict") and cur["verdict"] != p["verdict"] and "分化" not in (cur["verdict"], p["verdict"]):
            flips.append({
                "signal": s, "label": cur["label"], "from": p["verdict"], "to": cur["verdict"], "since": prev_day,
                "note": (f"{cur['label']}（次日开盘买、持有 3 日、扣 0.3% 成本）：近 30 天由「{p['verdict']}」变为"
                         f"「{cur['verdict']}」——胜率 {round((p.get('win') or 0) * 100)}% → {round(cur['win'] * 100)}%，"
                         f"均值 {p.get('avg')}% → {cur['avg']}%（{cur['n']} 笔）"),
            })
    if flips:
        store.set_meta("lab:flips", json.dumps({"as_of": today.isoformat(), "flips": flips}, ensure_ascii=False))
    return flips


def latest_flips(store: sj.JournalStore, today: date) -> Dict[str, Any]:
    data = json.loads(store.get_meta("lab:flips") or "{}")
    if not data or data.get("as_of", "") < (today - timedelta(days=14)).isoformat():
        return {"as_of": None, "flips": []}
    return data


# ---------------------------------------------------------------------------
# 导入旧回测样本（outputs/backtest_samples.csv）
# ---------------------------------------------------------------------------

def import_legacy_samples(store: sj.JournalStore, csv_path) -> Dict[str, Any]:
    """
    只导入信号复盘里完全没有记录的日期（那些日期东财已经取不到历史涨停池）。
    旧样本没有题材信息、每天只有最高板的约 20 只，标记 origin=legacy，后续表现按日 K 重新计算。
    周期优先用实盘口径（cycle_real），没有时用旧的代理口径。
    """
    import pandas as pd

    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        return {"imported": 0, "days": 0, "skipped_days": 0}
    have = {d["trade_date"] for d in store.dates()}
    imported, days, skipped = 0, 0, 0
    for d, g in df.groupby("date"):
        d = str(d)[:10]
        if d in have:
            skipped += 1
            continue
        items = []
        for _, r in g.iterrows():
            def val(k, default=None):
                v = r.get(k, default)
                return default if v is None or (isinstance(v, float) and v != v) else v
            t = val("t_min")
            cyc = val("cycle_real") or val("cycle") or "未知"
            items.append({
                "code": str(val("code", "")).split(".")[0].zfill(6), "name": val("name", ""), "sector": "",
                "sector_count": 0, "sector_rank": 0, "role": val("role", ""), "limit_count": int(val("limit_count", 1)),
                "seal_amount": float(val("seal", 0)), "turnover_rate": float(val("turnover", 0)),
                "first_limit_time": f"{int(t) // 60:02d}:{int(t) % 60:02d}:00" if t is not None else "",
                "break_count": int(val("break_count", 0)), "divergence": val("divergence", ""),
                "buy_hint": str(val("buy_hint", "")).lower() in ("true", "1", "1.0"), "cross": "",
                "sell_alert": False, "cycle": cyc, "candidate_tier": None,
            })
        imported += store.upsert(d, items, f"{d} 15:00:00", "legacy", final=True)
        days += 1
    return {"imported": imported, "days": days, "skipped_days": skipped}


__all__ = ["DEFAULT_SPEC", "DIMENSIONS", "import_legacy_samples", "latest_flips", "normalize_spec", "run",
           "update_verdicts", "verdicts"]
