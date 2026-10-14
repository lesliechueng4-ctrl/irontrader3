"""
次日预案：收盘后从当天涨停股里，提前挑出"明天可能走出买点、并且值得开盘买"的票；
第二天 9:25 竞价后按实际开盘幅度给出确认；每份预案存档，事后自动对答案，并做滚动验证。

为什么能提前：★买点要求"连板分歧"或"昨弱今强"，都以前一天涨停为前提，
所以明天的买点 100% 出自今天的涨停池。问题变成：今天五六十只涨停里，哪几只明天更可能走出来？

模型（刻意保持透明，每个数字都能追溯到样本）：
- 只预测"明天会不会继续涨停 / 出★买点"；"买不买"交给 9:25 竞价确认（见 PlanModel 的说明）。
- 特征全部是"今天收盘就知道"的：板数、首封时间、换手、炸板、题材涨停家数、题材地位、封单、接力周期、分歧/一致、今天的信号。
- 每个特征的每个分组，统计历史上"次日继续涨停率 / 次日出★买点率"；
  样本少的分组向整体平均收缩（相当于先给每组加 SHRINK_N 个"平均样本"），避免被几笔样本带偏。
- 预测 = 基准 + α × Σ 各特征相对基准的偏离（概率在 logit 空间相加）。α<1 是因为特征彼此相关
  （例如开盘即封和缩量一致），直接相加会重复计算。
- 滚动验证只用"当时已经知道结果"的样本训练，然后去预测下一天，再和真实结果比。

两件事要分开看：能继续涨（概率高）不等于开盘买进去能赚钱（强势往往已经体现在高开里）。
A 股 T+1：次日开盘买最早第二天才能卖，所以收益口径用"隔日收盘卖"（以及持有 3 日）。
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence

import backtest_lab as lab

SHRINK_N = 20          # 收缩强度：每个分组先加 20 个"平均样本"
ALPHA = 0.7            # 特征合成的阻尼系数（滚动验证里 0.7 的概率校准最好：预测 35% 的组实际约 34%）
COST = 0.3             # 收益扣往返成本（%）
MIN_TRAIN_DAYS = 8     # 滚动验证：至少有这么多天历史才开始预测
FOCUS_LIFT = 1.5       # 次日涨停概率达到基准的 1.5 倍以上才进预案
MIN_AUCTION_N = 20     # 竞价规律：同档样本少于这个数不给建议

# ---------------------------------------------------------------------------
# 特征（全部是信号日收盘时已知的）
# ---------------------------------------------------------------------------

def seal_bucket(row: Dict[str, Any]) -> Optional[str]:
    v = row.get("seal_amount")
    if v is None:
        return None
    v = float(v)
    return "a" if v < 5e7 else "b" if v < 2e8 else "c"


def today_signal(row: Dict[str, Any]) -> str:
    return "buy_hint" if row.get("buy_hint_any") else "wts" if row.get("wts_any") else "plain"


FEATURES: Dict[str, Dict[str, Any]] = {
    "limit": {"label": "板数", "fn": lab.limit_bucket, "names": dict(lab.DIMENSIONS["limit"]["buckets"])},
    "time": {"label": "首封", "fn": lab.time_bucket, "names": dict(lab.DIMENSIONS["time"]["buckets"])},
    "turnover": {"label": "换手", "fn": lab.turnover_bucket, "names": dict(lab.DIMENSIONS["turnover"]["buckets"])},
    "breaks": {"label": "炸板", "fn": lab.DIMENSIONS["breaks"]["fn"], "names": dict(lab.DIMENSIONS["breaks"]["buckets"])},
    "sector": {"label": "题材家数", "fn": lambda r: None if not r.get("sector_count") else lab.sector_bucket(r),
               "names": dict(lab.DIMENSIONS["sector"]["buckets"])},
    "role": {"label": "地位", "fn": lambda r: r.get("role") or None, "names": {}},
    "seal": {"label": "封单", "fn": seal_bucket, "names": {"a": "<0.5亿", "b": "0.5–2亿", "c": "≥2亿"}},
    "cycle": {"label": "接力周期", "fn": lambda r: r.get("cycle") if r.get("cycle") in ("强", "中", "弱") else None,
              "names": {"强": "强周期", "中": "中周期", "弱": "弱周期"}},
    "divergence": {"label": "形态", "fn": lambda r: r.get("divergence") or None, "names": {}},
    "signal": {"label": "今日信号", "fn": today_signal,
               "names": {"buy_hint": "今天已出★买点", "wts": "今天昨弱今强", "plain": "今天无买点"}},
}


def features_of(row: Dict[str, Any]) -> Dict[str, Optional[str]]:
    return {k: f["fn"](row) for k, f in FEATURES.items()}


def feature_text(key: str, bucket: str) -> str:
    f = FEATURES[key]
    name = f["names"].get(bucket, bucket)
    return name if key in ("limit", "signal", "cycle") else f"{f['label']}{name}"


# ---------------------------------------------------------------------------
# 样本：每条信号记录 → 特征 + 次日结果
# ---------------------------------------------------------------------------

def build_samples(rows: Sequence[Dict[str, Any]], cost: float = COST) -> List[Dict[str, Any]]:
    by_date: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    legacy_dates = set()
    for r in rows:
        by_date[r["trade_date"]][r["code"]] = r
        if r.get("origin") == "legacy":
            legacy_dates.add(r["trade_date"])
    dates = sorted(by_date)
    out = []
    for i, d in enumerate(dates):
        nxt_date = dates[i + 1] if i + 1 < len(dates) else None
        for code, r in by_date[d].items():
            o = r.get("outcome") or {}
            follow = o.get("follow") or []
            cont = bool(o.get("next_limit_up")) if o.get("days") else None
            # 次日是否出★买点：要求次日确实是下一个交易日、且次日的涨停池是完整记录（旧样本每天只有约 20 只）
            hint = None
            if follow and nxt_date and follow[0]["date"] == nxt_date and nxt_date not in legacy_dates:
                nxt = by_date[nxt_date].get(code)
                hint = bool(nxt and nxt.get("buy_hint_any"))
            m = o.get("next_open") or {}
            buyable = bool(m.get("buyable")) if m.get("entry") is not None else None
            ret3 = (m["ret_3"] - cost) if buyable and m.get("ret_3") is not None else None
            ret1 = (m["ret_1"] - cost) if buyable and m.get("ret_1") is not None else None
            # A 股 T+1：次日开盘买，最早第二天才能卖 → "隔日收盘卖"是最短的可兑现收益
            ret2 = ((follow[1]["close"] / m["entry"] - 1) * 100 - cost) if buyable and len(follow) >= 2 and m.get("entry") else None
            out.append({
                "date": d, "idx": i, "code": code, "name": r.get("name") or "", "row": r,
                "features": features_of(r), "cont": cont, "hint": hint, "ret3": ret3, "ret1": ret1, "ret2": ret2,
                "buyable": buyable, "open_pct": o.get("next_open_pct"),
            })
    return out


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------

def _logit(p: float) -> float:
    p = min(max(p, 0.005), 0.995)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


class PlanModel:
    """
    两个目标：cont（次日继续涨停）、hint（次日出★买点）。

    曾经也预测过"次日开盘买的收益"，滚动验证发现它反向（预测越高、实际越差：历史上表现好的组合，
    后来被市场提前抢筹、高开吃掉了），所以不再预测收益；"买不买"交给竞价确认，用竞价幅度的历史规律判断。
    """

    TARGETS = ("cont", "hint")

    def __init__(self, train: Sequence[Dict[str, Any]], *, label_filter: Optional[Callable[[str, Dict], bool]] = None):
        self.base: Dict[str, Optional[float]] = {}
        self.n: Dict[str, int] = {}
        self.stats: Dict[str, Dict[str, Dict[str, Dict[str, float]]]] = {}
        for t in self.TARGETS:
            rows = [s for s in train if s[t] is not None and (label_filter is None or label_filter(t, s))]
            vals = [float(s[t]) for s in rows]
            self.n[t] = len(vals)
            self.base[t] = statistics.mean(vals) if vals else None
            per: Dict[str, Dict[str, Dict[str, float]]] = {}
            for s in rows:
                for k, b in s["features"].items():
                    if b is None:
                        continue
                    cell = per.setdefault(k, {}).setdefault(b, {"n": 0, "sum": 0.0})
                    cell["n"] += 1
                    cell["sum"] += float(s[t])
            self.stats[t] = per

    def _cell(self, t: str, k: str, b: Optional[str]):
        if b is None or self.base[t] is None:
            return None
        c = self.stats[t].get(k, {}).get(b)
        if not c:
            return None
        shrunk = (c["sum"] + SHRINK_N * self.base[t]) / (c["n"] + SHRINK_N)
        return c["n"], c["sum"] / c["n"], shrunk

    def predict(self, feats: Dict[str, Optional[str]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        contrib: List[Dict[str, Any]] = []
        for t in self.TARGETS:
            base = self.base[t]
            if base is None:
                out[t] = None
                continue
            prob = t in ("cont", "hint")
            acc = 0.0
            for k, b in feats.items():
                cell = self._cell(t, k, b)
                if not cell:
                    continue
                n, raw, shrunk = cell
                delta = (_logit(shrunk) - _logit(base)) if prob else (shrunk - base)
                acc += delta
                if t == "cont":
                    contrib.append({"feature": k, "bucket": b, "text": feature_text(k, b), "n": n,
                                    "rate": round(raw, 3), "delta": delta})
            out[t] = _sigmoid(_logit(base) + ALPHA * acc) if prob else base + ALPHA * acc
        contrib.sort(key=lambda c: c["delta"], reverse=True)
        out["reasons"] = [c for c in contrib if c["delta"] > 0][:3]
        out["drags"] = [c for c in reversed(contrib) if c["delta"] < 0][:2]
        return out

    def summary(self) -> Dict[str, Any]:
        return {"n": self.n, "base": {k: (round(v, 4) if v is not None else None) for k, v in self.base.items()}}


def tier_of(pred: Dict[str, Any], model: PlanModel) -> Optional[str]:
    base_cont, base_hint = model.base.get("cont"), model.base.get("hint")
    if pred.get("cont") is not None and base_cont is not None and pred["cont"] >= max(FOCUS_LIFT * base_cont, 0.25):
        return "focus"       # 重点：明天继续涨停的概率明显高于平均
    if base_hint and pred.get("hint") is not None and pred["hint"] >= FOCUS_LIFT * base_hint:
        return "watch"       # 观察：明天更可能出★买点（多为分歧换手的票）
    return None


TIER_LABEL = {"focus": "重点", "watch": "观察"}
TIER_ORDER = {"focus": 0, "watch": 1, None: 2}


def _round(v, nd=3):
    return None if v is None else round(v, nd)


def score_day(model: PlanModel, day_samples: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for s in day_samples:
        p = model.predict(s["features"])
        tier = tier_of(p, model)
        r = s["row"]
        out.append({
            "code": s["code"], "name": s["name"], "sector": r.get("sector"), "sector_count": r.get("sector_count"),
            "role": r.get("role"), "limit_count": r.get("limit_count"), "first_limit_time": r.get("first_limit_time"),
            "turnover_rate": r.get("turnover_rate"), "seal_amount": r.get("seal_amount"),
            "divergence": r.get("divergence"), "buy_hint_today": bool(r.get("buy_hint_any")),
            "cycle": r.get("cycle"),
            "p_cont": _round(p.get("cont")), "p_hint": _round(p.get("hint")),
            "tier": tier, "tier_label": TIER_LABEL.get(tier),
            "reasons": [{k: c[k] for k in ("text", "n", "rate")} for c in p["reasons"]],
            "drags": [{k: c[k] for k in ("text", "n", "rate")} for c in p["drags"]],
            # 实际结果（预测当天未知，仅用于事后对答案 / 验证）
            "actual": {"cont": s["cont"], "hint": s["hint"], "ret2": _round(s["ret2"], 2), "ret3": _round(s["ret3"], 2),
                       "buyable": s["buyable"], "open_pct": s["open_pct"]},
        })
    out.sort(key=lambda x: (TIER_ORDER[x["tier"]], -(x["p_cont"] or 0)))
    for i, x in enumerate(out, 1):
        x["rank"] = i
    return out


def train_for(samples: Sequence[Dict[str, Any]], idx: int) -> PlanModel:
    """站在第 idx 天收盘：次日结果（是否涨停 / 是否出★买点）只知道到 idx-1 的样本。"""
    return PlanModel([s for s in samples if s["idx"] <= idx - 1])


# ---------------------------------------------------------------------------
# 今日预案
# ---------------------------------------------------------------------------

def build_plan(rows: Sequence[Dict[str, Any]], plan_date: str) -> Dict[str, Any]:
    """用 plan_date（含）之前的全部记录训练，给 plan_date 当天的涨停股打分。实盘时结果只到已收盘的日 K，自然不会穿越。"""
    samples = build_samples([r for r in rows if r["trade_date"] <= plan_date])
    day = [s for s in samples if s["date"] == plan_date]
    if not day:
        return {"plan_date": plan_date, "items": [], "model": None}
    idx = day[0]["idx"]
    # 实盘：日 K 结果只会出现到今天收盘，所以 ≤ idx-1 的次日结果、≤ idx-3 的 3 日收益都已经是"当时已知"
    model = train_for(samples, idx)
    items = score_day(model, day)
    for it in items:
        it.pop("actual", None)
    return {"plan_date": plan_date, "items": items, "model": model.summary()}


# ---------------------------------------------------------------------------
# 竞价规律 & 竞价确认
# ---------------------------------------------------------------------------

AUCTION_BUCKETS = [("low3", "低开 3% 以上", -1e9, -3), ("low", "低开 0–3%", -3, 0), ("high3", "高开 0–3%", 0, 3),
                   ("high6", "高开 3–6%", 3, 6), ("high", "高开 6% 以上", 6, 1e9)]


def auction_bucket(open_pct: Optional[float]) -> Optional[str]:
    if open_pct is None:
        return None
    for key, _label, lo, hi in AUCTION_BUCKETS:
        if lo <= open_pct < hi:
            return key
    return None


def auction_rules(samples: Sequence[Dict[str, Any]], subset: Optional[Callable[[Dict], bool]] = None) -> List[Dict[str, Any]]:
    """历史上"前一天涨停、今天竞价开在某个幅度"时，开盘买入的当日收益和 3 日收益（扣成本）。"""
    out = []
    for key, label, _lo, _hi in AUCTION_BUCKETS:
        g = [s for s in samples if auction_bucket(s["open_pct"]) == key and (subset is None or subset(s))]
        r1 = [s["ret1"] for s in g if s["ret1"] is not None]
        r2 = [s["ret2"] for s in g if s["ret2"] is not None]
        r3 = [s["ret3"] for s in g if s["ret3"] is not None]
        out.append({
            "key": key, "label": label, "n": len(r2), "unbuyable": sum(1 for s in g if s["buyable"] is False),
            "avg_1": _round(statistics.mean(r1), 2) if r1 else None,   # 当日浮动（T+1 卖不了，仅参考）
            "avg_2": _round(statistics.mean(r2), 2) if r2 else None,   # 隔日收盘卖（最短可兑现）
            "win_2": _round(sum(1 for x in r2 if x > 0) / len(r2)) if r2 else None,
            "avg_3": _round(statistics.mean(r3), 2) if r3 else None,
            "win_3": _round(sum(1 for x in r3 if x > 0) / len(r3)) if r3 else None,
            "next_limit": _round(sum(1 for s in g if s["cont"]) / len(g)) if g else None,
        })
    return out


def pick_rule(key: Optional[str], plan_rules: Sequence[Dict[str, Any]], all_rules: Sequence[Dict[str, Any]]):
    """优先用"历史上进过预案的票"的同档规律（这才是你要买的那类票），样本不足时退回全部前日涨停。"""
    p = next((r for r in plan_rules if r["key"] == key), None)
    if p and p["n"] >= MIN_AUCTION_N:
        return {**p, "source": "预案票"}
    a = next((r for r in all_rules if r["key"] == key), None)
    return {**a, "source": "全部前日涨停"} if a else None


def auction_advice(open_pct: Optional[float], at_limit: bool, plan_rules: Sequence[Dict[str, Any]],
                   all_rules: Sequence[Dict[str, Any]], gate_open: Optional[bool], at_limit_down: bool = False) -> Dict[str, Any]:
    if open_pct is None:
        return {"code": "unknown", "text": "还没有竞价数据", "tone": "none"}
    if at_limit:
        return {"code": "unbuyable", "text": "开盘涨停，买不进", "tone": "none"}
    if at_limit_down:
        # "低开 3% 以上"的历史样本绝大多数是 -3%~-7%，跌停开盘（多半有突发利空）不能套用
        return {"code": "limit_down", "text": "开盘跌停，历史规律不适用，不给建议（先查消息面）", "tone": "warn"}
    key = auction_bucket(open_pct)
    rule = pick_rule(key, plan_rules, all_rules)
    prefix = "" if gate_open is not False else "执行闸暂停开仓，仅观察；"
    if not rule or rule["n"] < MIN_AUCTION_N:
        return {"code": "thin", "text": prefix + "同档历史样本不足，自行判断", "tone": "none", "bucket": key}
    stat = (f"{rule['source']}同档历史 {rule['n']} 笔：隔日收盘卖均 {(rule['avg_2'] or 0):+.2f}%、"
            f"持有 3 日均 {(rule['avg_3'] or 0):+.2f}%")
    if (rule["avg_2"] or 0) > 0:
        return {"code": "ok" if gate_open is not False else "gated", "text": f"{prefix}可考虑（{stat}）",
                "tone": "ok" if gate_open is not False else "warn", "bucket": key}
    return {"code": "skip", "text": f"{prefix}不追，等分歧（{stat}）", "tone": "warn", "bucket": key}


# ---------------------------------------------------------------------------
# 滚动验证
# ---------------------------------------------------------------------------

def walk_forward(rows: Sequence[Dict[str, Any]], top_n: int = 5) -> Dict[str, Any]:
    """
    滚动验证：对历史上每一天，只用当时已知的数据生成预案，再和真实结果比。

    预测层：预案里的票，次日涨停率 / 次日出★买点率是否高于全部涨停。
    执行层（次日开盘买、隔日收盘卖，扣成本）：
      - 无条件开盘买：预案里的票全部开盘买；
      - 竞价确认后买：只在竞价规律给出"可考虑"时买。规律只用决策前已兑现的样本
        （隔日收盘卖的结果要到 j+2 收盘才知道，所以只用 idx ≤ i-2 的样本）。
    """
    samples = build_samples(rows)
    dates = sorted({s["date"] for s in samples})
    by_idx: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        by_idx[s["idx"]].append(s)

    days = []
    plan_all, base_all, confirmed_all = [], [], []
    plan_hist: List[Dict[str, Any]] = []  # 历史上进过预案的样本（竞价规律优先用它）
    calib: Dict[str, List] = defaultdict(list)
    for i in range(MIN_TRAIN_DAYS, len(dates)):
        day = by_idx[i]
        if not any(s["cont"] is not None for s in day):
            continue  # 次日结果还没出来
        model = train_for(samples, i)
        if model.base["cont"] is None:
            continue
        scored = score_day(model, day)
        plan = [x for x in scored if x["tier"]]
        known = i - 2  # 隔日收盘卖的结果，决策时只知道到 i-2
        all_rules = auction_rules([s for s in samples if s["idx"] <= known])
        plan_rules = auction_rules([s for s in plan_hist if s["idx"] <= known])
        confirmed = []
        for x in plan:
            a = x["actual"]
            adv = auction_advice(a["open_pct"], a["buyable"] is False, plan_rules, all_rules, None)
            if adv["code"] == "ok":
                confirmed.append(x)
        plan_codes = {x["code"] for x in plan}
        plan_hist += [s for s in day if s["code"] in plan_codes]
        plan_all += plan
        base_all += scored
        confirmed_all += confirmed
        for x in scored:
            if x["actual"]["cont"] is not None and x["p_cont"] is not None:
                b = "<15%" if x["p_cont"] < 0.15 else "15–30%" if x["p_cont"] < 0.3 else "30–45%" if x["p_cont"] < 0.45 else "≥45%"
                calib[b].append((x["p_cont"], x["actual"]["cont"]))
        days.append({
            "date": dates[i], "n": len(scored), "plan": len(plan), "confirmed": len(confirmed),
            "plan_ret": _mean([x["actual"]["ret2"] for x in plan]),
            "confirmed_ret": _mean([x["actual"]["ret2"] for x in confirmed]),
            "base_ret": _mean([x["actual"]["ret2"] for x in scored]),
            "plan_cont": _rate([x["actual"]["cont"] for x in plan]),
            "base_cont": _rate([x["actual"]["cont"] for x in scored]),
        })

    # 资金曲线：隔日收盘卖（持有 2 个交易日）→ 资金分 2 份轮动
    cum = {"plan": 0.0, "confirmed": 0.0, "base": 0.0}
    for d in days:
        for k in cum:
            v = d[f"{k}_ret"]
            if v is not None:
                cum[k] += v / 2
        d.update({f"cum_{k}": round(v, 2) for k, v in cum.items()})

    def agg(xs):
        return {
            "n": len(xs),
            "cont": _rate([x["actual"]["cont"] for x in xs]),
            "hint": _rate([x["actual"]["hint"] for x in xs]),
            "ret2": _mean([x["actual"]["ret2"] for x in xs]),
            "win2": _rate([(x["actual"]["ret2"] > 0) if x["actual"]["ret2"] is not None else None for x in xs]),
            "ret3": _mean([x["actual"]["ret3"] for x in xs]),
            "unbuyable": sum(1 for x in xs if x["actual"]["buyable"] is False),
        }

    return {
        "plan_samples": plan_hist,  # 内部用：竞价规律（接口返回前去掉）
        "days": len(days),
        "first": days[0]["date"] if days else None,
        "last": days[-1]["date"] if days else None,
        "plan": agg(plan_all),
        "confirmed": agg(confirmed_all),
        "base": agg(base_all),
        "calibration": [
            {"bucket": b, "n": len(v), "predicted": _round(statistics.mean(p for p, _ in v)),
             "actual": _round(sum(1 for _, a in v if a) / len(v))}
            for b in ("<15%", "15–30%", "30–45%", "≥45%") if (v := calib.get(b))
        ],
        "series": days,
    }


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 2) if xs else None


def _rate(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(1 for x in xs if x) / len(xs), 3) if xs else None


__all__ = ["PlanModel", "auction_advice", "auction_rules", "build_plan", "build_samples", "walk_forward"]
