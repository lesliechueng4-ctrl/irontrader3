"""
次日预案接口。

GET /api/plan              最新一份预案（收盘后生成，给下一个交易日用）+ 9:25 后的竞价确认
GET /api/plan/validation   滚动验证（只用当时已知数据生成历史预案，再和真实结果比）
GET /api/plan/archive      历史预案存档，自动对答案

预案在收盘记录（15:05 后）完成、后续表现更新之后由记录线程生成；没生成过时打开页面也会补生成。
竞价确认只用当时已经兑现的历史样本给建议，并服从统一执行闸（闸关闭时只能"仅观察"）。
"""

import json
import time
from datetime import date, datetime, timedelta
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

from flask import Blueprint, request

from api_response import fail, ok
from logger_config import get_logger
import next_day_plan as ndp
import signal_journal as sj

logger = get_logger(__name__)

plan_bp = Blueprint("plan_routes", __name__)


# ---------------------------------------------------------------------------
# 依赖（集中在这里，测试时整体替换）
# ---------------------------------------------------------------------------

def _service():
    import journal_routes

    return journal_routes.get_service()


def _is_trading_day(d: date) -> bool:
    from news_catalyst import is_trading_day

    return is_trading_day(d)


def _quote(code: str) -> Optional[Dict[str, Any]]:
    """新浪单票行情；9:25–9:30 之间 open 可能还是 0，用当前价（即竞价成交价）代替。"""
    import market_routes

    q = market_routes.data_fetcher.get_stock_realtime(code)
    if not q or q.get("error"):
        return None
    prev = float(q.get("prev_close") or 0)
    px = float(q.get("open") or 0) or float(q.get("current") or 0)
    if prev <= 0 or px <= 0:
        return None
    return {"open": px, "prev_close": prev, "name": q.get("name") or ""}


def _gate() -> Dict[str, Any]:
    """统一执行闸（情绪闸 + 指数闸取严）。竞价时还没进连续交易时段，所以看"是否允许开新仓"。"""
    import market_routes
    from workbench_service import build_execution_context

    ctx = build_execution_context(market_routes._get_emotion_result(), market_state=market_routes._get_market_state())
    pos = ctx.get("position") or {}
    return {"can_open": bool(pos.get("can_open")), "action": ctx.get("action"), "reason": ctx.get("reason"),
            "level": pos.get("level"), "decided_by": ctx.get("decided_by")}


DEPS: Dict[str, Callable] = {
    "service": _service, "is_trading_day": _is_trading_day, "quote": _quote, "gate": _gate, "now": sj.now_sh,
}


# ---------------------------------------------------------------------------
# 预案生成 / 读取
# ---------------------------------------------------------------------------

def next_trading_day(d: date, is_trading_day: Callable[[date], bool]) -> date:
    x = d + timedelta(days=1)
    for _ in range(30):
        if is_trading_day(x):
            return x
        x += timedelta(days=1)
    return x


def latest_plan_date(service, now: datetime) -> Optional[str]:
    """最近一个"收盘数据完整"的交易日：今天之前的，或今天已记完收盘版的。"""
    today = now.date().isoformat()
    for d in service.store.dates():  # 新 → 旧
        td = d["trade_date"]
        if td < today or (td == today and service.finalized(today)):
            return td
    return None


def ensure_plan(service, plan_date: str, *, is_trading_day, now: datetime, force: bool = False) -> List[Dict[str, Any]]:
    """读取 plan_date 的预案；没有（或 force）就用当时的全部记录生成并存档。"""
    stored = [] if force else service.store.load_plan(plan_date)
    if stored:
        return stored
    rows = service.store.query("2000-01-01", plan_date)
    plan = ndp.build_plan(rows, plan_date)
    for_date = next_trading_day(date.fromisoformat(plan_date), is_trading_day).isoformat()
    service.store.save_plan(plan_date, for_date, plan["items"], now.strftime("%Y-%m-%d %H:%M:%S"))
    service.store.set_meta(f"plan_model:{plan_date}", json.dumps(plan["model"], ensure_ascii=False))
    logger.info(f"[plan] 已生成 {plan_date} 的次日预案（{sum(1 for i in plan['items'] if i.get('tier'))} 只入选）")
    return service.store.load_plan(plan_date)


def generate_after_close(service, now: datetime, is_trading_day=None) -> int:
    """记录线程在收盘版记录 + 后续表现更新后调用：生成今天的次日预案（重算，覆盖盘中可能生成的版本）。"""
    today = now.date().isoformat()
    if not service.finalized(today):
        return 0
    items = ensure_plan(service, today, is_trading_day=is_trading_day or DEPS["is_trading_day"], now=now, force=True)
    return sum(1 for i in items if i.get("tier"))


# ---------------------------------------------------------------------------
# 滚动验证（缓存：数据不变就不重算）
# ---------------------------------------------------------------------------

_WF_CACHE: Dict[str, Any] = {"key": None, "value": None}
_WF_LOCK = Lock()


def _walk_forward(service) -> Dict[str, Any]:
    key = service.store.fingerprint()
    with _WF_LOCK:
        if _WF_CACHE["key"] == key and _WF_CACHE["value"] is not None:
            return _WF_CACHE["value"]
        rows = service.store.query("2000-01-01", "2999-12-31")
        wf = ndp.walk_forward(rows)
        samples = ndp.build_samples(rows)
        wf["rules"] = {
            "plan": ndp.auction_rules(wf.pop("plan_samples")),
            "all": ndp.auction_rules(samples),
        }
        _WF_CACHE.update(key=key, value=wf)
        return wf


def clear_cache() -> None:
    with _WF_LOCK:
        _WF_CACHE.update(key=None, value=None)
    _QUOTES.clear()


# ---------------------------------------------------------------------------
# 竞价确认
# ---------------------------------------------------------------------------

_QUOTES: Dict[str, Any] = {}
QUOTE_TTL = 30


def _cached_quote(code: str) -> Optional[Dict[str, Any]]:
    hit = _QUOTES.get(code)
    if hit and time.time() - hit[0] < QUOTE_TTL:
        return hit[1]
    try:
        q = DEPS["quote"](code)
    except Exception as exc:
        logger.info(f"[plan] 竞价行情失败 {code}: {exc}")
        q = None
    _QUOTES[code] = (time.time(), q)
    return q


def auction_phase(now: datetime, for_date: str) -> str:
    d = now.date().isoformat()
    if d < for_date:
        return "before"
    if d > for_date:
        return "done"
    hm = now.hour * 60 + now.minute
    return "before" if hm < 9 * 60 + 25 else "live"


def attach_auction(service, plan_date: str, items: List[Dict[str, Any]], *, phase: str, rules: Dict[str, Any],
                   gate: Optional[Dict[str, Any]], now: datetime) -> None:
    """竞价开始后给入选的票取开盘幅度并给建议；第一次取到就存档（之后不再改，开盘价不会变）。"""
    gate_open = gate.get("can_open") if gate else None
    for it in items:
        if not it.get("tier"):
            continue
        if it.get("auction_at"):
            continue  # 已存档
        if phase != "live":
            continue
        q = _cached_quote(it["code"])
        if not q:
            it["auction_advice"] = {"code": "unknown", "text": "暂无竞价行情", "tone": "none"}
            continue
        pct = round((q["open"] / q["prev_close"] - 1) * 100, 2)
        lim = sj.limit_pct(it["code"], it.get("name") or q.get("name") or "")
        at_limit = sj._at_limit(q["open"], q["prev_close"], lim)
        at_down = q["open"] <= round(q["prev_close"] * (1 - lim / 100) + 1e-9, 2) + 0.011
        adv = ndp.auction_advice(pct, at_limit, rules["plan"], rules["all"], gate_open, at_limit_down=at_down)
        it["auction_open_pct"], it["auction_advice"] = pct, adv
        it["auction_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
        service.store.save_auction(plan_date, it["code"], pct, adv, it["auction_at"])


def _flatten(stored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in stored:
        it = dict(r.get("item") or {})
        it.update({"code": r["code"], "rank": r["rank"], "tier": r["tier"],
                   "auction_open_pct": r.get("auction_open_pct"), "auction_advice": r.get("auction_advice"),
                   "auction_at": r.get("auction_at")})
        out.append(it)
    return out


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------

@plan_bp.route("/api/plan")
def plan_latest():
    service, now = DEPS["service"](), DEPS["now"]()
    plan_date = request.args.get("date") or latest_plan_date(service, now)
    if not plan_date:
        return ok({"plan_date": None, "items": []}, meta={"as_of": now.strftime("%Y-%m-%d %H:%M:%S")})
    try:
        date.fromisoformat(plan_date)
    except ValueError:
        return fail("日期格式应为 YYYY-MM-DD", status=400, code="BAD_DATE")
    is_td = DEPS["is_trading_day"]
    if request.args.get("date"):
        stored = service.store.load_plan(plan_date)  # 查看历史预案：只读，不补生成
        if not stored:
            return fail(f"{plan_date} 没有预案存档", status=404, code="PLAN_NOT_FOUND")
    else:
        stored = ensure_plan(service, plan_date, is_trading_day=is_td, now=now)
    for_date = (stored[0].get("for_date") if stored else None) or next_trading_day(
        date.fromisoformat(plan_date), is_td).isoformat()
    items = _flatten(stored)
    wf = _walk_forward(service)
    phase = auction_phase(now, for_date)
    gate = None
    if phase == "live":
        try:
            gate = DEPS["gate"]()
        except Exception as exc:
            logger.info(f"[plan] 执行闸暂不可用: {exc}")
    attach_auction(service, plan_date, items, phase=phase, rules=wf["rules"], gate=gate, now=now)
    model = service.store.get_meta(f"plan_model:{plan_date}")
    return ok({
        "plan_date": plan_date,
        "for_date": for_date,
        "generated_at": stored[0].get("created_at") if stored else None,
        "items": items,
        "model": json.loads(model) if model else None,
        "auction": {"phase": phase, "gate": gate, "min_n": ndp.MIN_AUCTION_N},
        "rules": wf["rules"],
        "verdict": verdict_of(wf),
        "history": [d["plan_date"] for d in service.store.plan_dates()[:60]],
    }, meta={"as_of": now.strftime("%Y-%m-%d %H:%M:%S")})


def verdict_of(wf: Dict[str, Any]) -> Dict[str, Any]:
    """把滚动验证浓缩成一句话结论（页面顶部显示，避免只看预案不看效果）。"""
    p, b, c = wf.get("plan") or {}, wf.get("base") or {}, wf.get("confirmed") or {}
    if not wf.get("days") or not p.get("n") or p.get("cont") is None or not b.get("cont"):
        return {"level": "none", "predict": None, "trade": None, "text": "历史数据还不够做滚动验证"}
    lift = p["cont"] / b["cont"] if b["cont"] else None
    predict_ok = lift is not None and lift >= 1.2
    best = max((x for x in (p.get("ret2"), c.get("ret2")) if x is not None), default=None)
    trade_ok = best is not None and best > 0
    parts = [f"近 {wf['days']} 个交易日滚动验证：预案票次日涨停率 {p['cont'] * 100:.0f}%，全部涨停股 {b['cont'] * 100:.0f}%"
             f"（{lift:.1f} 倍）" if lift else ""]
    if p.get("ret2") is not None:
        parts.append(f"开盘买、隔日收盘卖平均 {p['ret2']:+.2f}%")
    if c.get("n") and c.get("ret2") is not None:
        parts.append(f"竞价确认后买 {c['n']} 笔平均 {c['ret2']:+.2f}%")
    if predict_ok and not trade_ok:
        tail = "能预测谁更强，但强势多半已在开盘价里，按预案开盘买还没赚到钱——把它当观察名单，别当买入名单"
        level = "warn"
    elif predict_ok and trade_ok:
        tail = "预测和买入都为正，样本仍需继续积累"
        level = "ok"
    else:
        tail = "预测能力不明显，先只做观察"
        level = "crit"
    return {"level": level, "predict": predict_ok, "trade": trade_ok, "lift": round(lift, 2) if lift else None,
            "text": "；".join(x for x in parts if x) + "。" + tail + "。"}


@plan_bp.route("/api/plan/validation")
def plan_validation():
    service, now = DEPS["service"](), DEPS["now"]()
    wf = dict(_walk_forward(service))
    wf["verdict"] = verdict_of(wf)
    wf["params"] = {"shrink_n": ndp.SHRINK_N, "alpha": ndp.ALPHA, "cost": ndp.COST,
                    "focus_lift": ndp.FOCUS_LIFT, "min_train_days": ndp.MIN_TRAIN_DAYS}
    return ok(wf, meta={"as_of": now.strftime("%Y-%m-%d %H:%M:%S")})


def build_archive(service, limit: int = 30) -> List[Dict[str, Any]]:
    """历史预案 + 真实结果：次日是否涨停、是否出★买点、竞价开盘幅度、开盘买隔日收盘卖收益。"""
    heads = service.store.plan_dates()[:limit]
    if not heads:
        return []
    start = heads[-1]["plan_date"]
    rows = service.store.query(start, "2999-12-31")
    actual = {(s["date"], s["code"]): s for s in ndp.build_samples(rows)}
    out = []
    for h in heads:
        items = []
        for it in _flatten(service.store.load_plan(h["plan_date"])):
            if not it.get("tier"):
                continue
            s = actual.get((h["plan_date"], it["code"]))
            it["actual"] = None if not s else {
                "cont": s["cont"], "hint": s["hint"], "open_pct": s["open_pct"], "buyable": s["buyable"],
                "ret2": None if s["ret2"] is None else round(s["ret2"], 2),
                "ret3": None if s["ret3"] is None else round(s["ret3"], 2),
            }
            items.append(it)
        acts = [i["actual"] for i in items if i["actual"]]
        conf = [i["actual"] for i in items if i["actual"] and (i.get("auction_advice") or {}).get("code") == "ok"]
        out.append({
            "plan_date": h["plan_date"], "for_date": h["for_date"], "created_at": h["created_at"],
            "n": len(items),
            "settled": sum(1 for a in acts if a["cont"] is not None),
            "cont": ndp._rate([a["cont"] for a in acts]),
            "hint": ndp._rate([a["hint"] for a in acts]),
            "ret2": ndp._mean([a["ret2"] for a in acts]),
            "confirmed": len(conf),
            "confirmed_ret2": ndp._mean([a["ret2"] for a in conf]),
            "items": items,
        })
    return out


@plan_bp.route("/api/plan/archive")
def plan_archive():
    service, now = DEPS["service"](), DEPS["now"]()
    try:
        limit = max(1, min(int(request.args.get("limit", 30)), 120))
    except ValueError:
        limit = 30
    return ok({"plans": build_archive(service, limit)}, meta={"as_of": now.strftime("%Y-%m-%d %H:%M:%S")})
