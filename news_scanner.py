"""
消息催化扫描（作者选择的方案 D）：把"重大消息雷达"里的利好，逐只过一遍能不能做的筛子。

流程：
1. 雷达里方向为利好、等级为重大 / 显著的公告（同一公司同一件事已合并）；
2. 逐只核对行情，并判断能不能做：
   - 停牌 / 无行情 → 等复牌；
   - 消息还没被交易过（盘后 / 长假发布）→ 等首个交易日开盘验证；
   - 涨停：一字板 / 秒板 / 封死 → 买不进（与龙头决策共用 buyability 口径）；
   - 已涨 ≥ 7% 未封板 → 利好可能已兑现，等分歧；
   - 利好后反而跌 ≥ 5% → 市场不认，回避（也可能是规则把"出售资产"之类误判成了利好）；
   - 同一只票同时有利空公告 → 降为等待，先看正文；
3. 看主线：所属行业今天涨停 ≥ 3 只（与龙头战法"板块效应"同一门槛）。行业用东财行业分级
   （如"化石能源-煤炭-煤炭开采洗选"），与涨停池的"所属行业"按层级名称匹配，是近似判断；
4. 看统一执行闸：闸门关闭时，所有候选都只能观察（不能出现"这里可做、首页禁止开仓"的矛盾）。

输出分五档：关注 / 等待 / 已兑现 / 市场不认 / 买不进。它是研究线索，不是买入信号，最终仍要进单票研报看完整结论。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional

from buyability import check_limit_buyability
from logger_config import get_logger

logger = get_logger(__name__)

PRICED_IN_GAIN_PCT = 7.0      # 未封板但已涨这么多，视为利好已部分兑现
REJECTED_DROP_PCT = -5.0      # 利好后反而跌这么多，视为市场不认
MAINLINE_MIN_LIMIT_UPS = 3    # 与龙头战法"板块效应 ≥3 只涨停"一致

STATUS_ORDER = {"focus": 0, "wait": 1, "priced_in": 2, "rejected": 3, "blocked": 4}
STATUS_LABEL = {"focus": "关注", "wait": "等待", "priced_in": "已兑现", "rejected": "市场不认", "blocked": "买不进"}
LEVEL_ORDER = {"major": 0, "notable": 1}


def _timing(e: Dict[str, Any]) -> str:
    if e.get("pending"):
        return "待首次交易"
    if e.get("sessions_elapsed") == 0:
        return "今日首日"
    return f"第 {int(e.get('sessions_elapsed') or 0) + 1} 个交易日"


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def evaluate(
    radar: Dict[str, Any],
    *,
    quote: Callable[[str], Dict[str, Any]],
    zt_pool: Iterable[Dict[str, Any]],
    execution: Optional[Dict[str, Any]],
    sector_of: Optional[Callable[[str], str]] = None,
    progress: Optional[Callable[..., None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    events = radar.get("events") or []
    positives = [e for e in events if e.get("direction", 0) > 0 and e.get("level") in LEVEL_ORDER]
    negatives: Dict[str, List[str]] = {}
    for e in events:
        if e.get("direction", 0) < 0:
            negatives.setdefault(e["code"], []).append(e.get("type_label") or "利空")

    # 同一只票可能有多条利好（如重组 + 停牌），保留等级最高、最新的一条，其余作为补充说明
    by_code: Dict[str, Dict[str, Any]] = {}
    extra: Dict[str, List[str]] = {}
    for e in sorted(positives, key=lambda x: (LEVEL_ORDER[x["level"]], x.get("published_at") or "")):
        if e["code"] in by_code:
            extra.setdefault(e["code"], []).append(e.get("type_label") or "")
        else:
            by_code[e["code"]] = e

    pool = {str(z.get("code")): z for z in zt_pool or []}
    sector_counts = Counter(str(z.get("sector") or "") for z in pool.values() if z.get("sector"))
    position = (execution or {}).get("position") or {}
    can_open = position.get("can_open") is True
    off_session = (execution or {}).get("mode") == "review"
    gate_reason = ""
    if execution is not None and not can_open:
        blockers = [b for b in (execution.get("blockers") or []) if b != "非A股交易时段"]
        gate_reason = blockers[0] if blockers else ("" if off_session else "统一执行闸：暂停新增开仓")

    rows = []
    total = len(by_code)
    for i, (code, e) in enumerate(by_code.items(), 1):
        if cancelled and cancelled():
            raise RuntimeError("用户已取消扫描")
        if progress:
            progress(phase="核对行情", message=f"核对 {e.get('name') or code}（{i}/{total}）", done=i - 1, total=total)
        rows.append(_evaluate_one(code, e, quote, pool, sector_counts, sector_of,
                                  negatives.get(code, []), extra.get(code, []), can_open, gate_reason,
                                  gate_known=execution is not None, off_session=off_session))

    rows.sort(key=lambda r: r["published_at"] or "", reverse=True)  # 新的在前
    rows.sort(key=lambda r: (STATUS_ORDER[r["status"]], LEVEL_ORDER.get(r["level"], 9), not r["mainline"]))
    counts = Counter(r["status"] for r in rows)
    return {
        "success": True,
        "data": rows,
        "meta": {
            "radar_as_of": radar.get("as_of"),
            "reaction_day": (radar.get("window") or {}).get("reaction_day"),
            "scanned": total,
            "total_matches": total,
            "returned_count": total,
            "status_counts": {k: counts.get(k, 0) for k in STATUS_ORDER},
            "can_open": can_open if execution is not None else None,
            "gate_reason": gate_reason,
            "off_session": off_session,
            "errors": sum(1 for r in rows if r.get("quote_error")),
        },
    }


def match_sector(path: str, sector_counts: Counter) -> tuple:
    """
    东财行业分级（"电力设备-电池-锂电池"）与涨停池"所属行业"（"电池"）做近似匹配。
    返回 (显示名, 该行业今日涨停数)；匹配不到时显示最末一级、涨停数 0。
    """
    if not path:
        return "", 0
    parts = [p for p in str(path).replace("—", "-").split("-") if p]
    best = ("", 0)
    for name, n in sector_counts.items():
        if not name:
            continue
        if any(name == p or name in p or p in name for p in parts) and n > best[1]:
            best = (name, n)
    return best if best[1] else (parts[-1] if parts else "", 0)


def _evaluate_one(code, e, quote, pool, sector_counts, sector_of, negatives, extra, can_open, gate_reason,
                  gate_known, off_session=False) -> Dict[str, Any]:
    reasons: List[str] = []
    blockers: List[str] = []
    q: Dict[str, Any] = {}
    quote_error = None
    try:
        q = quote(code) or {}
        if q.get("error"):
            quote_error = str(q["error"])
    except Exception as exc:  # 单只失败不影响整批
        quote_error = str(exc)

    price = _num(q.get("current"))
    change = _num(q.get("change_pct"))
    z = pool.get(code)
    sector = (z or {}).get("sector") or ""
    if sector:
        sector_zt = sector_counts.get(sector, 0)
    else:
        path = ""
        if sector_of:
            try:
                path = sector_of(code) or ""
            except Exception:
                path = ""
        sector, sector_zt = match_sector("" if path == "未知" else path, sector_counts)
    mainline = sector_zt >= MAINLINE_MIN_LIMIT_UPS

    if e.get("pending"):
        status = "wait"
        reasons.append("消息还没被交易过，等首个交易日开盘：高开一字买不进，高开分歧才有机会")
    elif quote_error or price <= 0:
        status = "wait"
        reasons.append("停牌或暂无行情，复牌后看开盘是否一字" if not quote_error else f"行情暂不可用：{quote_error[:40]}")
    elif q.get("is_limit_up") or z is not None:
        if z is not None:
            buyable, why = check_limit_buyability(z.get("first_limit_time"), z.get("turnover_rate"))
        else:
            one_price = _num(q.get("open")) == _num(q.get("high")) == _num(q.get("low")) == price
            buyable, why = (False, "一字板，无法买入") if one_price else (True, "涨停，可尝试排板")
        if buyable:
            status = "focus"
            reasons.append(f"已涨停（{why}），属于消息首板 / 接力思路")
        else:
            status = "blocked"
            blockers.append(why)
    elif change >= PRICED_IN_GAIN_PCT:
        status = "priced_in"
        reasons.append(f"已涨 {change:.1f}% 未封板，利好可能已部分兑现，等分歧回落再看")
    elif change <= REJECTED_DROP_PCT and e.get("sessions_elapsed", 0) >= 0:
        status = "rejected"
        blockers.append(f"利好后反而跌 {change:.1f}%，市场不认（或属于误判，先看公告原文）")
    else:
        status = "focus"
        reasons.append(f"今日 {change:+.1f}%，利好还没被充分反应")

    if mainline:
        reasons.append(f"所属{sector}今天 {sector_zt} 只涨停，处在主线")
    elif sector:
        reasons.append(f"所属{sector}今天涨停 {sector_zt} 只，不是主线，属于独立消息")
    if extra:
        reasons.append("另有：" + "、".join(x for x in extra if x))
    if negatives:
        blockers.append("同时有利空：" + "、".join(negatives[:2]) + "，先看正文")
        if status == "focus":
            status = "wait"

    status_label = STATUS_LABEL[status]
    if status == "focus" and gate_known and not can_open:
        if gate_reason:  # 原因在结果顶部统一说明一次，不在每行重复
            status_label = "关注（执行闸暂停开仓）"
        elif off_session:
            status_label = "关注（待开盘验证）"

    return {
        "code": code,
        "name": e.get("name") or q.get("name") or "",
        "event_type": e.get("type"),
        "event_label": e.get("type_label"),
        "level": e.get("level"),
        "level_label": e.get("level_label"),
        "title": e.get("title"),
        "url": e.get("url"),
        "published_at": e.get("published_at"),
        "timing": _timing(e),
        "pending": bool(e.get("pending")),
        "related": e.get("related") or 0,
        "price": round(price, 2) if price > 0 else None,
        "change_pct": round(change, 2) if price > 0 else None,
        "limit_count": (z or {}).get("limit_count"),
        "sector": sector or None,
        "sector_limit_ups": sector_zt,
        "mainline": mainline,
        "status": status,
        "status_label": status_label,
        "reasons": reasons,
        "blockers": [b for b in blockers if b],
        "quote_error": quote_error,
    }


__all__ = ["evaluate", "PRICED_IN_GAIN_PCT", "MAINLINE_MIN_LIMIT_UPS"]
