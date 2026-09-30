"""
消息面如何计入原有策略（作者选择的方案 C）。纯函数，便于测试和调参。

1. 低吸：第六维"消息面"，以【非对称修正分】加到个股四维分上
   - 利空：消息面分 × 0.25，最多扣 25 分 —— 低吸最怕接飞刀，立案 / 退市 / 减持要明显压分；
   - 利好：消息面分 × 0.08，最多加 8 分 —— 低吸靠的是回调到位，利好只是锦上添花；
   - 利好兑现：有利好但当天已涨停或已涨 ≥ 5%，不加分，并提示"利好可能已兑现"。
   为什么不是"再加一个 10% 权重的维度"：按权重算，一条立案调查（消息面 -66）只会让综合分少 3 分左右，
   根本拦不住；非对称修正更符合"利空要躲、利好别追"的直觉，也更好解释。

2. 龙头：用消息判断"题材有没有新催化 / 有没有退潮信号"，只调整信心（1–5 星），不改变买 / 不买
   - 新催化：近 2 个交易日内出现的重大 / 显著利好 → 信心 +1；
   - 退潮信号：重大利空 → 信心 -2；减持计划、问询函、严重异常波动、停牌核查、处罚、冻结 → 信心 -1；
   - 合计限制在 -2 ~ +1。
   一票否决（方案 B）作者没有选，所以这里不会把 BUY 改成 IGNORE。

所有参数都在这里，改完跑 tests/unit/test_news_weighting.py。
"""

from typing import Any, Dict, List, Optional

# ---- 低吸 ----
LOWBUY_NEG_FACTOR = 0.25
LOWBUY_NEG_CAP = -25.0
LOWBUY_POS_FACTOR = 0.08
LOWBUY_POS_CAP = 8.0
PRICED_IN_DAY_GAIN_PCT = 5.0

# ---- 龙头 ----
DRAGON_CATALYST_MAX_AGE = 1      # 已过交易日 ≤ 1（今天首日或第 2 个交易日）才算"新"催化
DRAGON_RISK_TYPES = {"reduce_plan", "inquiry", "severe_abnormal", "trading_halt_check", "penalty", "frozen"}
DRAGON_DELTA_MIN, DRAGON_DELTA_MAX = -2, 1


def lowbuy_news_dimension(news: Optional[Dict[str, Any]], realtime: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """返回低吸第六维：{available, score, adjustment, priced_in, note, ...}。news 为 None 表示取不到。"""
    if not news:
        return {
            "available": False,
            "score": None,
            "adjustment": 0.0,
            "priced_in": False,
            "note": "消息面暂无（数据源不可用），未计入",
        }
    score = float(news.get("score") or 0)
    rt = realtime or {}
    try:
        change = float(rt.get("change_pct") or 0)
    except (TypeError, ValueError):
        change = 0.0
    priced_in = score > 0 and (bool(rt.get("is_limit_up")) or change >= PRICED_IN_DAY_GAIN_PCT)

    if score < 0:
        adj = max(LOWBUY_NEG_CAP, score * LOWBUY_NEG_FACTOR)
        note = f"消息面{news.get('label', '偏利空')}（{score:+.0f}），扣 {abs(adj):.1f} 分"
    elif priced_in:
        adj = 0.0
        note = f"有利好（{score:+.0f}），但当天已{'涨停' if rt.get('is_limit_up') else f'涨 {change:.1f}%'}，利好可能已兑现，不加分"
    elif score > 0:
        adj = min(LOWBUY_POS_CAP, score * LOWBUY_POS_FACTOR)
        note = f"消息面{news.get('label', '偏利好')}（{score:+.0f}），加 {adj:.1f} 分"
    else:
        adj = 0.0
        note = "消息面中性，不加减分"

    sources = news.get("sources") or {}
    return {
        "available": True,
        "score": score,
        "label": news.get("label"),
        "adjustment": round(adj, 1),
        "priced_in": priced_in,
        "note": note,
        "summary": news.get("summary"),
        "alerts": [_brief(e) for e in (news.get("alerts") or [])[:3]],
        "announcements_only": not (sources.get("news") or {}).get("ok", False),
    }


def dragon_news_effect(news: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """龙头的消息面影响：{available, delta, catalysts, risks, note}。"""
    if not news:
        return {"available": False, "delta": 0, "catalysts": [], "risks": [], "note": "消息面暂无，未计入信心"}
    catalysts: List[Dict[str, Any]] = []
    risks: List[Dict[str, Any]] = []
    delta = 0
    for e in news.get("events") or []:
        if not e.get("active"):
            continue
        direction, level = e.get("direction", 0), e.get("level")
        if direction > 0 and level in ("major", "notable") and e.get("sessions_elapsed", 99) <= DRAGON_CATALYST_MAX_AGE:
            catalysts.append(_brief(e))
        elif direction < 0 and level == "major":
            risks.append({**_brief(e), "weight": -2})
        elif direction < 0 and e.get("type") in DRAGON_RISK_TYPES:
            risks.append({**_brief(e), "weight": -1})
    # 同类只算一次，避免媒体转载叠加
    seen = set()
    catalysts = [c for c in catalysts if not (c["type"] in seen or seen.add(c["type"]))]
    seen = set()
    risks = [r for r in risks if not (r["type"] in seen or seen.add(r["type"]))]
    if catalysts:
        delta += 1
    delta += sum(r["weight"] for r in risks)
    delta = max(DRAGON_DELTA_MIN, min(DRAGON_DELTA_MAX, delta))

    parts = []
    if catalysts:
        parts.append("题材有新催化：" + "、".join(c["type_label"] for c in catalysts[:2]))
    if risks:
        parts.append("出现退潮信号：" + "、".join(r["type_label"] for r in risks[:2]))
    note = "；".join(parts) if parts else "近期没有新的催化或利空"
    return {"available": True, "delta": delta, "catalysts": catalysts, "risks": risks, "note": note}


def apply_dragon_news(dragon: Optional[Dict[str, Any]], news: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """把消息面影响写进龙头结果：只调整信心星级（1–5），不改变决策。返回新 dict。"""
    if not isinstance(dragon, dict):
        return dragon
    effect = dragon_news_effect(news)
    out = {**dragon, "news_effect": effect}
    conf = dragon.get("confidence")
    if effect["delta"] and isinstance(conf, (int, float)) and dragon.get("decision") in ("BUY", "WATCH"):
        new_conf = int(max(1, min(5, conf + effect["delta"])))
        out["confidence"] = new_conf
        effect["confidence_before"] = conf
        effect["confidence_after"] = new_conf
    return out


def _brief(e: Dict[str, Any]) -> Dict[str, Any]:
    return {k: e.get(k) for k in ("type", "type_label", "direction", "level", "title", "url", "sessions_elapsed",
                                  "pending", "published_at")}


__all__ = ["apply_dragon_news", "dragon_news_effect", "lowbuy_news_dimension"]
