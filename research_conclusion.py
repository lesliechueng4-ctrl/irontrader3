"""Pure aggregation rules for the unified stock-research conclusion.

This module deliberately has no dependency on Flask or either decision engine.
It combines their already-structured outputs without parsing human-readable
``reason`` text, so wording changes cannot silently change the conclusion.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


EXECUTABLE = "EXECUTABLE"
CONFIRM = "CONFIRM"
OBSERVE = "OBSERVE"
NOT_APPLICABLE = "NOT_APPLICABLE"

_LABELS = {
    EXECUTABLE: "可执行",
    CONFIRM: "等确认",
    OBSERVE: "仅观察",
    NOT_APPLICABLE: "不适用",
}

_DRAGON_STATES = {"BUY", "WATCH", "IGNORE"}
_LOWBUY_STATES = {"低吸", "观察", "等待", "回避"}
_STALE_FRESHNESS = {"delayed", "stale", "off_session"}
_SESSION_ONLY_BLOCKERS = {
    "非A股交易时段",
    "非A股工作日",
    "非A股交易日",
    "交易日待确认",
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _dragon_strategy(dragon: Mapping[str, Any], errors: Mapping[str, Any]) -> Dict[str, Any]:
    raw_status = dragon.get("decision")
    stock_info = _mapping(dragon.get("stock_info"))
    structured_error = stock_info.get("error")
    available = raw_status in _DRAGON_STATES and not structured_error
    is_limit_up = stock_info.get("is_limit_up")

    if structured_error:
        reason_code = "DATA_ERROR"
        applicable = False
    elif not available:
        reason_code = "DATA_ERROR" if errors.get("dragon") else "NOT_PROVIDED"
        applicable = False
    elif is_limit_up is not True:
        reason_code = "NOT_LIMIT_UP"
        applicable = False
    elif raw_status == "BUY":
        reason_code = "BUY_SETUP"
        applicable = True
    elif raw_status == "WATCH":
        reason_code = "WAIT_TRIGGER"
        applicable = True
    else:
        reason_code = "NO_SETUP"
        applicable = True

    return {
        "raw_status": raw_status,
        "available": available,
        "applicable": applicable,
        "reason_code": reason_code,
    }


def _lowbuy_strategy(lowbuy: Mapping[str, Any], errors: Mapping[str, Any]) -> Dict[str, Any]:
    raw_status = lowbuy.get("decision")
    structured_error = lowbuy.get("data_error") is True or bool(lowbuy.get("error"))
    available = raw_status in _LOWBUY_STATES and not structured_error

    if structured_error:
        reason_code = "DATA_ERROR"
        applicable = False
    elif not available:
        reason_code = "DATA_ERROR" if errors.get("lowbuy") else "NOT_PROVIDED"
        applicable = False
    elif lowbuy.get("veto_triggered") is True:
        reason_code = "GLOBAL_VETO"
        applicable = True
    elif raw_status == "低吸":
        reason_code = "BUY_SETUP"
        applicable = True
    elif raw_status == "观察":
        reason_code = "WAIT_TRIGGER"
        applicable = True
    else:
        reason_code = "NO_SETUP"
        applicable = True

    return {
        "raw_status": raw_status,
        "available": available,
        "applicable": applicable,
        "reason_code": reason_code,
    }


def _execution_data(execution: Mapping[str, Any], lowbuy: Mapping[str, Any]) -> Dict[str, Any]:
    nested = _mapping(execution.get("data"))
    status = execution.get("data_status", nested.get("status"))
    status = status if status in {"complete", "partial", "unavailable"} else "complete"

    freshness_value = execution.get("freshness", nested.get("freshness", "unknown"))
    if isinstance(freshness_value, Mapping):
        if execution.get("mode") == "review":
            freshness = "off_session"
        elif freshness_value.get("emotion_stale") or freshness_value.get("emotion_degraded"):
            freshness = "stale"
        elif freshness_value.get("emotion_cached"):
            freshness = "cached"
        else:
            freshness = "live"
    else:
        freshness = freshness_value
    if execution.get("off_session") is True or execution.get("mode") == "review":
        freshness = "off_session"
    elif execution.get("cached") is True and freshness not in {"off_session", "stale"}:
        freshness = "cached"

    return {
        "status": status,
        "freshness": freshness,
        "as_of": execution.get("as_of", nested.get("as_of", lowbuy.get("timestamp"))),
    }


def _position(
    execution: Mapping[str, Any],
    dragon: Mapping[str, Any],
    lowbuy: Mapping[str, Any],
    can_open: bool,
) -> Dict[str, Any]:
    configured = _mapping(execution.get("position"))
    lowbuy_gate = _mapping(lowbuy.get("emotion_gate"))
    dragon_gate = _mapping(dragon.get("emotion_gate"))

    max_total = _number(configured.get("max_total_position", execution.get("max_total_position")))
    max_single = _number(configured.get("max_single_position", execution.get("max_single_position")))
    if max_single is None:
        max_single = _number(lowbuy_gate.get("max_single_position"))
    if max_single is None:
        max_single = _number(dragon_gate.get("max_single_position"))

    return {
        "can_open": can_open,
        "max_total_position": max_total,
        "max_single_position": max_single,
    }


def _message_for(status: str, reason_code: str) -> tuple[str, str]:
    if reason_code == "DATA_UNAVAILABLE":
        return "关键数据不可用，当前无法形成可靠结论。", "修复或刷新数据后重新研究。"
    if reason_code == "GLOBAL_VETO":
        return "存在全局风险否决，本次不适用。", "停止开仓计划，等待否决条件解除后重评。"
    if reason_code == "DATA_ERROR":
        return "部分策略出现数据错误，当前结论不可直接执行。", "刷新数据并重新研究，确认错误解除后再执行。"
    if reason_code in {"MARKET_BLOCKED", "EMOTION_BLOCKED", "EXECUTION_BLOCKED"}:
        return "当前环境禁止执行，仅保留观察。", "等待市场或情绪重新允许开仓后再评估。"
    if reason_code == "STRATEGY_MISMATCH":
        return "当前标的不适用于可用策略。", "更换研究策略或等待形态发生变化。"
    if status == EXECUTABLE:
        return "主策略条件已满足，可在仓位上限内执行。", "执行前复核价格与风险边界，并分批验证。"
    if status == CONFIRM:
        return "策略信号存在，但仍需等待盘中或数据确认。", "确认触发条件、数据时效和市场许可后再执行。"
    return "当前尚未形成可执行机会，仅保留观察。", "记录关键变化，满足触发条件后重新研究。"


def build_final_conclusion(
    dragon: Optional[Mapping[str, Any]],
    lowbuy: Optional[Mapping[str, Any]],
    errors: Optional[Mapping[str, Any]] = None,
    execution: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one conservative conclusion from dragon and low-buy results.

    Strategy choice is deterministic: a structurally valid limit-up stock uses
    the dragon strategy; otherwise a valid low-buy result is primary.  A
    secondary strategy can add blockers, but can never upgrade the primary
    strategy's action state.
    """

    dragon_data = _mapping(dragon)
    lowbuy_data = _mapping(lowbuy)
    error_data = _mapping(errors)
    execution_data = _mapping(execution)

    dragon_view = _dragon_strategy(dragon_data, error_data)
    lowbuy_view = _lowbuy_strategy(lowbuy_data, error_data)
    structured_data_error = (
        dragon_view["reason_code"] == "DATA_ERROR" and not error_data.get("dragon")
    ) or (
        lowbuy_view["reason_code"] == "DATA_ERROR" and not error_data.get("lowbuy")
    )
    strategies = {"dragon": dragon_view, "lowbuy": lowbuy_view}
    data = _execution_data(execution_data, lowbuy_data)
    blockers = []

    def add_blocker(code: str, scope: str, message: str) -> None:
        if not any(item["code"] == code for item in blockers):
            blockers.append({"code": code, "scope": scope, "message": message})

    if error_data.get("dragon"):
        add_blocker("DRAGON_DATA_UNAVAILABLE", "strategy", "龙头策略数据不可用")
    if error_data.get("lowbuy"):
        add_blocker("LOWBUY_DATA_UNAVAILABLE", "strategy", "低吸策略数据不可用")
    if dragon_view["reason_code"] == "DATA_ERROR" and not error_data.get("dragon"):
        add_blocker("DRAGON_DATA_ERROR", "strategy", "龙头策略返回数据错误")
    if lowbuy_view["reason_code"] == "DATA_ERROR" and not error_data.get("lowbuy"):
        add_blocker("LOWBUY_DATA_ERROR", "strategy", "低吸策略返回数据错误")

    explicitly_unavailable = data["status"] == "unavailable"
    no_structured_result = not dragon_view["available"] and not lowbuy_view["available"]
    if explicitly_unavailable or (no_structured_result and not structured_data_error):
        data["status"] = "unavailable"
        add_blocker("DATA_UNAVAILABLE", "global", "关键数据不可用")
        status, primary_strategy, reason_code = NOT_APPLICABLE, "none", "DATA_UNAVAILABLE"
    elif no_structured_result and structured_data_error:
        data["status"] = "unavailable"
        add_blocker("DATA_ERROR", "global", "策略输入包含明确数据错误")
        status, primary_strategy, reason_code = NOT_APPLICABLE, "none", "DATA_ERROR"
    elif lowbuy_view["reason_code"] == "GLOBAL_VETO":
        message = str(lowbuy_data.get("veto_reason") or "低吸引擎触发全局风险否决")
        add_blocker("GLOBAL_VETO", "global", message)
        status, primary_strategy, reason_code = NOT_APPLICABLE, "none", "GLOBAL_VETO"
    else:
        if dragon_view["applicable"]:
            primary_strategy = "dragon"
            raw_status = dragon_view["raw_status"]
            if raw_status == "BUY":
                status, reason_code = EXECUTABLE, "BUY_SETUP"
            elif raw_status == "WATCH":
                status, reason_code = CONFIRM, "WAIT_TRIGGER"
                add_blocker("DRAGON_CONFIRMATION_REQUIRED", "strategy", "龙头策略仍需确认")
            else:
                status, reason_code = OBSERVE, "NO_SETUP"
                dragon_reason = _plain(dragon_data.get("reason"))
                add_blocker(
                    "DRAGON_NO_SETUP", "strategy",
                    f"龙头策略未通过：{dragon_reason}" if dragon_reason else "龙头策略未通过",
                )
        elif lowbuy_view["applicable"]:
            primary_strategy = "lowbuy"
            raw_status = lowbuy_view["raw_status"]
            if raw_status == "低吸":
                status, reason_code = EXECUTABLE, "BUY_SETUP"
            elif raw_status == "观察":
                status, reason_code = CONFIRM, "WAIT_TRIGGER"
                position_reason = _mapping(lowbuy_data.get("position_check")).get("reason")
                add_blocker(
                    "LOWBUY_CONFIRMATION_REQUIRED", "strategy",
                    f"低吸评分达标，但{position_reason}" if position_reason else "低吸信号仍需确认",
                )
            else:
                status, reason_code = OBSERVE, "NO_SETUP"
                add_blocker("LOWBUY_NO_SETUP", "strategy", "低吸策略尚无开仓信号")
        else:
            status, primary_strategy = NOT_APPLICABLE, "none"
            reason_code = "DATA_UNAVAILABLE" if error_data else "STRATEGY_MISMATCH"
            code = "DATA_UNAVAILABLE" if error_data else "STRATEGY_MISMATCH"
            message = "适用策略的数据不可用" if error_data else "当前标的不适用于可用策略"
            add_blocker(code, "global" if error_data else "strategy", message)
            if error_data:
                data["status"] = "unavailable"

        if status != NOT_APPLICABLE:
            market_state = _mapping(execution_data.get("market_state")) or _mapping(dragon_data.get("market_state"))
            market_blocked = market_state.get("can_trade") is False

            configured_position = _mapping(execution_data.get("position"))
            explicit_can_open = execution_data.get("can_open", configured_position.get("can_open"))
            lowbuy_can_open = _mapping(lowbuy_data.get("emotion_gate")).get("can_open")
            dragon_can_open = _mapping(dragon_data.get("emotion_gate")).get("can_open")
            emotion_blocked = explicit_can_open is False or lowbuy_can_open is False or dragon_can_open is False
            # 复盘模式只忽略纯粹的交易时段限制。若 can_execute=False 还包含
            # 数据、市场或权限 blocker，仍必须阻断；缺少 blocker 明细时也
            # fail closed，不能假定失败原因只有“非交易时段”。
            execution_blockers = execution_data.get("blockers")
            execution_blockers = (
                list(execution_blockers)
                if isinstance(execution_blockers, (list, tuple, set))
                else []
            )
            review_has_only_session_blockers = bool(execution_blockers) and all(
                str(item) in _SESSION_ONLY_BLOCKERS for item in execution_blockers
            )
            if execution_data.get("mode") == "review" and review_has_only_session_blockers:
                add_blocker(
                    "SESSION_REVIEW",
                    "execution",
                    "；".join(str(item) for item in execution_blockers),
                )
            execution_blocked = execution_data.get("can_execute") is False and not (
                execution_data.get("mode") == "review" and review_has_only_session_blockers
            )

            previous_status = status
            if market_blocked:
                market_label = market_state.get("state_type") or market_state.get("state") or ""
                market_reason = market_state.get("reason") or ""
                add_blocker(
                    "MARKET_BLOCKED", "global",
                    f"指数{market_label}：{market_reason}，今日不开新仓" if market_label else "市场状态禁止交易",
                )
                status = OBSERVE
                if previous_status in {EXECUTABLE, CONFIRM}:
                    reason_code = "MARKET_BLOCKED"
            if emotion_blocked:
                add_blocker("EMOTION_BLOCKED", "global", "情绪仓位闸禁止开仓")
                was_actionable = status in {EXECUTABLE, CONFIRM}
                status = OBSERVE
                if was_actionable and reason_code not in {"MARKET_BLOCKED"}:
                    reason_code = "EMOTION_BLOCKED"
            if execution_blocked:
                add_blocker("EXECUTION_BLOCKED", "global", "当前执行模式禁止开仓")
                was_actionable = status in {EXECUTABLE, CONFIRM}
                status = OBSERVE
                if was_actionable and reason_code not in {"MARKET_BLOCKED", "EMOTION_BLOCKED"}:
                    reason_code = "EXECUTION_BLOCKED"

            if data["freshness"] in _STALE_FRESHNESS:
                freshness_code = str(data["freshness"]).upper()
                add_blocker(freshness_code, "execution", "数据时效不足，执行前需要刷新确认")
                if status == EXECUTABLE:
                    status = CONFIRM
                    reason_code = freshness_code

            if structured_data_error:
                data["status"] = "partial"
                add_blocker("DATA_ERROR", "data", "部分策略输入包含明确数据错误")
                if status == EXECUTABLE:
                    status = CONFIRM
                reason_code = "DATA_ERROR"

            if error_data or data["status"] == "partial":
                data["status"] = "partial"
                add_blocker("PARTIAL_DATA", "data", "部分策略或数据不可用")
                if status == EXECUTABLE:
                    status = CONFIRM
                    reason_code = "PARTIAL_DATA"

    summary, next_action = _message_for(status, reason_code)
    # 最具体的一条原因放在结论第一句（策略层原因优先于全局闸门，
    # 例如"一字板买不进"比"市场禁止交易"更能说明这只票本身的问题）
    def _specific(item: Mapping[str, Any]) -> bool:
        message = str(item.get("message") or "")
        return "：" in message or "但" in message

    key_reason = (
        next((b["message"] for b in blockers if b.get("scope") == "strategy" and _specific(b)), None)
        or next((b["message"] for b in blockers if b.get("scope") == "global" and _specific(b)), None)
    )
    position = _position(execution_data, dragon_data, lowbuy_data, status == EXECUTABLE)

    return {
        "status": status,
        "label": _LABELS[status],
        "primary_strategy": primary_strategy,
        "reason_code": reason_code,
        "summary": summary,
        "key_reason": key_reason,
        "next_action": next_action,
        "blockers": blockers,
        "position": position,
        "data": data,
        "strategies": strategies,
    }



def _plain(text: Any) -> str:
    """去掉引擎文案里的表情前缀与换行，只保留第一句。"""
    value = str(text or "").strip()
    for mark in ("⚠️", "❌", "✅", "ℹ️", "👀", "➖"):
        value = value.replace(mark, "")
    return value.strip().splitlines()[0].strip() if value.strip() else ""


__all__ = ["build_final_conclusion"]
