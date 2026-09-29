"""今日作战台的纯聚合与候选预检逻辑。

本模块不获取行情、不调用逐股分析，也不启动全市场扫描。调用方只需传入
已经取得的 market emotion 与 dragon ladder 字典，便可生成稳定的作战台响应。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time
from threading import Lock
from time import monotonic
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from buyability import check_limit_buyability


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
MIN_EMOTION_CONFIDENCE = 0.67
PRIMARY_LIMIT = 3
WATCH_LIMIT = 10
PRIMARY_ROLES = {"龙头", "龙二", "龙三"}
TRADING_CALENDAR_RETRY_SECONDS = 300.0

TradingDayChecker = Callable[[date], Optional[bool]]

_TRADING_CALENDAR_LOCK = Lock()
_TRADING_CALENDAR_DATES: Optional[frozenset[date]] = None
_TRADING_CALENDAR_RANGE: Optional[Tuple[date, date]] = None
_TRADING_CALENDAR_RETRY_AFTER = 0.0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unique(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _coerce_datetime(value: Optional[Union[datetime, str]]) -> datetime:
    if value is None:
        return datetime.now(SHANGHAI_TZ)
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("datetime string must be ISO-8601 compatible") from exc
    else:
        raise TypeError("now/generated_at must be a datetime, ISO string, or None")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=SHANGHAI_TZ)
    return dt.astimezone(SHANGHAI_TZ)


def _display_datetime(value: Optional[Union[datetime, str]]) -> Tuple[datetime, str]:
    dt = _coerce_datetime(value)
    return dt, dt.strftime("%Y-%m-%d %H:%M:%S")


def _coerce_source_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is not None:
            dt = dt.astimezone(SHANGHAI_TZ)
        return dt.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(SHANGHAI_TZ)
        return dt.date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _emotion_data_date(emotion: Mapping[str, Any]) -> Tuple[str, Optional[date]]:
    # data_as_of 优先代表底层行情日期；缺失时才退回情绪计算时间 as_of。
    for key in ("data_as_of", "as_of"):
        parsed = _coerce_source_date(emotion.get(key))
        if parsed is not None:
            return key, parsed
    return "", None


def _load_akshare_trading_calendar() -> Optional[Tuple[frozenset[date], date, date]]:
    """懒加载并缓存 AKShare 的新浪交易日历；失败时短暂退避。"""

    global _TRADING_CALENDAR_DATES, _TRADING_CALENDAR_RANGE
    global _TRADING_CALENDAR_RETRY_AFTER

    with _TRADING_CALENDAR_LOCK:
        if _TRADING_CALENDAR_DATES is not None and _TRADING_CALENDAR_RANGE is not None:
            return (
                _TRADING_CALENDAR_DATES,
                _TRADING_CALENDAR_RANGE[0],
                _TRADING_CALENDAR_RANGE[1],
            )
        current = monotonic()
        if current < _TRADING_CALENDAR_RETRY_AFTER:
            return None
        try:
            import akshare as ak

            frame = ak.tool_trade_date_hist_sina()
            if "trade_date" not in getattr(frame, "columns", ()):
                raise ValueError("交易日历缺少 trade_date 列")
            dates = frozenset(
                parsed
                for value in frame["trade_date"]
                if (parsed := _coerce_source_date(value)) is not None
            )
            if not dates:
                raise ValueError("交易日历为空")
            first, last = min(dates), max(dates)
            _TRADING_CALENDAR_DATES = dates
            _TRADING_CALENDAR_RANGE = (first, last)
            _TRADING_CALENDAR_RETRY_AFTER = 0.0
            return dates, first, last
        except Exception:
            _TRADING_CALENDAR_RETRY_AFTER = current + TRADING_CALENDAR_RETRY_SECONDS
            return None


def _default_trading_day_checker(day: date) -> Optional[bool]:
    calendar = _load_akshare_trading_calendar()
    if calendar is None:
        return None
    dates, first, last = calendar
    # 超出日历覆盖范围不是休市证据，必须保持“待确认”。
    if day < first or day > last:
        return None
    return day in dates


def _trading_day_state(
    day: date, checker: Optional[TradingDayChecker]
) -> Tuple[Optional[bool], str]:
    if day.weekday() >= 5:
        return False, "weekday"
    active_checker = checker or _default_trading_day_checker
    try:
        result = active_checker(day)
    except Exception:
        result = None
    if result is None:
        return None, "injected" if checker is not None else "akshare"
    return bool(result), "injected" if checker is not None else "akshare"


def _in_a_share_session(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.time().replace(tzinfo=None)
    return (
        time(9, 30) <= current <= time(11, 30)
        or time(13, 0) <= current <= time(15, 0)
    )


def _market_gate(market_state: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """把风控引擎的指数状态压成一道闸；未提供时返回 None（不参与判断）。"""
    if market_state is None:
        return None
    market = _mapping(market_state)
    known = bool(market) and "can_trade" in market and not market.get("error")
    state_type = str(market.get("state_type") or "")
    state = str(market.get("state") or "")
    return {
        "known": known,
        "can_trade": known and market.get("can_trade") is True,
        "state": state,
        "state_type": state_type,
        "reason": str(market.get("reason") or market.get("error") or ""),
        "suggestion": str(market.get("suggestion") or ""),
    }


def build_execution_context(
    emotion: Optional[Mapping[str, Any]],
    now: Optional[Union[datetime, str]] = None,
    trading_day_checker: Optional[TradingDayChecker] = None,
    market_state: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """根据时间、市场情绪和指数状态生成唯一的"今日执行闸"。

    情绪闸（仓位上限）和指数闸（风控引擎的市场状态）取更严格者：任一不允许开仓，
    首页、候选池、个股研究都按"不开新仓"处理，并在 ``decided_by`` 里说明是哪一道闸拦下的。

    只有交易日历明确确认当天开市、处于 A 股连续交易时段内，且情绪数据为
    上海当天、新鲜、非降级、可信度不低于 0.67、仓位指令明确允许开仓时，
    ``can_execute`` 才为 True。交易日历不可用或超出覆盖范围时一律 fail-closed。
    """

    emotion_data = _mapping(emotion)
    position = _mapping(emotion_data.get("position"))
    checked_dt, checked_at = _display_datetime(now)
    is_workday = checked_dt.weekday() < 5
    in_clock_window = _in_a_share_session(checked_dt)
    is_trading_day, trading_day_source = _trading_day_state(
        checked_dt.date(), trading_day_checker
    )
    in_session = in_clock_window and is_trading_day is True
    mode = "live" if in_session else "review"
    data_date_key, data_date = _emotion_data_date(emotion_data)
    data_is_today = data_date == checked_dt.date() if data_date is not None else False

    stale = bool(emotion_data.get("stale"))
    degraded = bool(emotion_data.get("degraded"))
    confidence = max(0.0, min(1.0, _number(emotion_data.get("confidence"), 0.0)))
    can_open = position.get("can_open") is True

    blockers: List[str] = []
    if not in_clock_window:
        blockers.append("非A股交易时段" if is_workday else "非A股工作日")
    elif is_trading_day is False:
        blockers.append("非A股交易日")
    elif is_trading_day is None:
        blockers.append("交易日待确认")
    if in_clock_window and not data_is_today:
        blockers.append("情绪数据日期未知" if data_date is None else "情绪数据非当日")
    if stale:
        blockers.append("情绪数据陈旧")
    if degraded:
        blockers.append("情绪数据已降级")
    if confidence < MIN_EMOTION_CONFIDENCE:
        blockers.append(f"情绪可信度不足（{confidence:.0%}）")
    if not can_open:
        blockers.append("市场仓位指令不允许开仓")

    market_gate = _market_gate(market_state)
    market_blocks = False
    if market_gate is not None:
        if not market_gate["known"]:
            market_blocks = True
            blockers.append("指数状态未知")
        elif not market_gate["can_trade"]:
            market_blocks = True
            label = market_gate["state_type"] or market_gate["state"] or "禁止开仓"
            blockers.append(f"指数{label}：{market_gate['reason']}" if market_gate["reason"] else f"指数{label}")

    emotion_level = str(position.get("level") or "未知")
    emotion_action = str(position.get("action") or "")
    if can_open and market_blocks:
        decided_by = (
            f"情绪{emotion_level}允许开仓（{emotion_action or '有仓位'}），"
            f"但指数处于{(market_gate or {}).get('state_type') or '禁止开仓状态'}，以更严格的指数闸为准"
        )
    elif not can_open and market_gate is not None and market_gate["can_trade"]:
        decided_by = f"指数允许交易，但情绪{emotion_level}不允许开仓，以情绪闸为准"
    elif not can_open:
        decided_by = "情绪闸不允许开仓"
    elif market_blocks:
        decided_by = "指数闸不允许开仓"
    else:
        decided_by = ""
    can_open_final = can_open and not market_blocks

    can_execute = not blockers
    if mode == "review":
        status_label = "复盘模式"
        action = "仅制定计划"
    elif can_execute:
        status_label = "盘中可执行"
        action = emotion_action or "按计划验证后执行"
    else:
        status_label = "盘中观察"
        # 被任何一道闸拦下时不再显示情绪闸的"满仓进攻"之类进攻性指令
        action = "暂停新增开仓" if (market_blocks or not can_open) else (emotion_action or "暂停新增开仓")

    return {
        "mode": mode,
        "can_execute": can_execute,
        "action": action,
        "status_label": status_label,
        "reason": "；".join(blockers) if blockers else "交易时段与市场情绪闸均通过",
        "blockers": blockers,
        "checked_at": checked_at,
        "is_workday": is_workday,
        "is_trading_day": is_trading_day,
        "trading_day_status": (
            "confirmed" if is_trading_day is True
            else "closed" if is_trading_day is False
            else "unconfirmed"
        ),
        "trading_day_source": trading_day_source,
        "in_clock_window": in_clock_window,
        "in_trading_window": in_session,
        "decided_by": decided_by,
        "gates": {
            "emotion": {"level": emotion_level, "action": emotion_action, "can_open": can_open},
            "market": market_gate,
        },
        "position": {
            "level": emotion_level,
            "source_action": emotion_action,
            "can_open": can_open_final,
            "max_total_position": _number(position.get("max_total_position"), 0.0),
            "max_single_position": _number(position.get("max_single_position"), 0.0),
        },
        "freshness": {
            "emotion_as_of": str(emotion_data.get("as_of") or ""),
            "emotion_cached": bool(emotion_data.get("cached")),
            "emotion_stale": stale,
            "emotion_degraded": degraded,
            "emotion_confidence": confidence,
            "emotion_data_date_source": data_date_key,
            "emotion_data_date": data_date.isoformat() if data_date is not None else "",
            "emotion_data_is_today": data_is_today,
        },
    }


def _sector_bonus(sector_rank: int) -> int:
    return {1: 15, 2: 10, 3: 5}.get(sector_rank, 0)


def _candidate_from_stock(
    stock: Mapping[str, Any],
    sector: Mapping[str, Any],
    sector_rank: int,
    buy_hint_reliable: bool,
) -> Optional[Dict[str, Any]]:
    code = str(stock.get("code") or "").strip()
    if not code or stock.get("sell_alert"):
        return None

    role = str(stock.get("role") or "")
    cross = str(stock.get("cross") or "")
    buy_hint = bool(stock.get("buy_hint"))
    if role not in PRIMARY_ROLES and not buy_hint and cross != "昨弱今强":
        return None

    limit_count = max(0, _integer(stock.get("limit_count"), 0))
    divergence = str(stock.get("divergence") or "")
    score = 0
    reasons: List[str] = []

    if cross == "昨弱今强":
        score += 60
        reasons.append("昨弱今强")
    if buy_hint:
        if buy_hint_reliable:
            score += 45
            reasons.append("可靠买点信号")
        else:
            score += 5
            reasons.append("买点信号待验证")

    role_score = {"龙头": 20, "龙二": 10, "龙三": 5}.get(role, 0)
    score += role_score
    if role_score:
        reasons.append(role)

    score += min(limit_count, 5) * 4
    if limit_count:
        reasons.append(f"{limit_count}板")

    topic_bonus = _sector_bonus(sector_rank)
    score += topic_bonus
    if topic_bonus:
        reasons.append(f"题材Top{sector_rank}")

    # 今天已经一字 / 秒板 / 封死的票盘中买不进，不能排进"优先关注"
    # （缺少首封时间与换手数据时无法判断，按可买处理，由个股研究再确认）
    if stock.get("first_limit_time") or stock.get("turnover_rate") not in (None, ""):
        buyable, buyable_reason = check_limit_buyability(
            stock.get("first_limit_time"), stock.get("turnover_rate")
        )
    else:
        buyable, buyable_reason = True, ""

    if divergence == "分歧" and buy_hint and buy_hint_reliable:
        score += 8
        reasons.append("分歧信号经周期验证")

    return {
        "code": code,
        "name": str(stock.get("name") or code),
        "sector": str(sector.get("sector") or "其他"),
        "sector_rank": sector_rank,
        "role": role,
        "limit_count": limit_count,
        "divergence": divergence,
        "cross": cross,
        "buy_hint": buy_hint,
        "buy_hint_reliable": buy_hint_reliable,
        "precheck_score": score,
        "buyable": buyable,
        "buyable_reason": buyable_reason,
        "reasons": _unique(reasons),
        "blockers": [],
        "next_action": "analyze_stock",
    }


def _candidate_sort_key(candidate: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        -_integer(candidate.get("precheck_score"), 0),
        _integer(candidate.get("sector_rank"), 9999),
        -_integer(candidate.get("limit_count"), 0),
        str(candidate.get("code") or ""),
    )


def _flatten_candidates(
    ladder: Mapping[str, Any], buy_hint_reliable: bool
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    sectors_value = ladder.get("sectors")
    sectors = sectors_value if isinstance(sectors_value, list) else []
    raw_candidates: List[Dict[str, Any]] = []
    stock_count = 0
    hard_excluded = 0

    for sector_rank, sector_value in enumerate(sectors, start=1):
        sector = _mapping(sector_value)
        stocks_value = sector.get("stocks")
        stocks = stocks_value if isinstance(stocks_value, list) else []
        for stock_value in stocks:
            stock_count += 1
            candidate = _candidate_from_stock(
                _mapping(stock_value), sector, sector_rank, buy_hint_reliable
            )
            if candidate is None:
                hard_excluded += 1
            else:
                raw_candidates.append(candidate)

    # 同一代码只保留稳定排序下最优的一条，且不修改调用方传入的对象。
    deduped: Dict[str, Dict[str, Any]] = {}
    for candidate in sorted(raw_candidates, key=_candidate_sort_key):
        deduped.setdefault(candidate["code"], candidate)

    candidates = sorted(deduped.values(), key=_candidate_sort_key)
    return candidates, {
        "sector_count": len(sectors),
        "stock_count": stock_count,
        "eligible_precheck_count": len(candidates),
        "hard_excluded_count": hard_excluded,
        "duplicate_count": max(0, len(raw_candidates) - len(candidates)),
    }


def build_today_workbench(
    emotion: Optional[Mapping[str, Any]],
    ladder: Optional[Mapping[str, Any]],
    generated_at: Optional[Union[datetime, str]] = None,
    trading_day_checker: Optional[TradingDayChecker] = None,
    market_state: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """聚合情绪与梯队数据，生成今日预检候选及执行约束。"""

    emotion_data = _mapping(emotion)
    ladder_data = _mapping(ladder)
    generated_dt, generated_text = _display_datetime(generated_at)
    execution = build_execution_context(
        emotion_data,
        now=generated_dt,
        trading_day_checker=trading_day_checker,
        market_state=market_state,
    )
    spirit = _mapping(ladder_data.get("spirit"))
    cycle = str(spirit.get("cycle") or "未知")
    buy_hint_reliable = spirit.get("buy_hint_reliable") is not False
    ladder_stale = bool(ladder_data.get("data_stale"))

    # 非交易时段只禁止“执行”，不应阻止用户为下一交易时段建立研究优先级。
    # 候选分层仍受数据质量、情绪仓位和梯队状态约束。
    execution_blockers = list(execution["blockers"])
    session_blockers = {
        "非A股交易时段",
        "非A股工作日",
        "非A股交易日",
        "交易日待确认",
    }
    candidate_gate_blockers = [item for item in execution_blockers if item not in session_blockers]
    global_blockers = list(candidate_gate_blockers)
    if ladder_stale:
        global_blockers.append("梯队数据陈旧")
    if cycle == "未知":
        global_blockers.append("市场周期未知")
    global_blockers = _unique(global_blockers)
    executable = execution["can_execute"] and not global_blockers

    candidates, source_summary = _flatten_candidates(ladder_data, buy_hint_reliable)
    source_summary["buy_hint_reliable"] = buy_hint_reliable

    primary: List[Dict[str, Any]] = []
    watch: List[Dict[str, Any]] = []
    for candidate in candidates:
        blockers = list(global_blockers)
        has_primary_signal = (
            candidate["cross"] == "昨弱今强"
            or (candidate["buy_hint"] and buy_hint_reliable)
        )
        if candidate["limit_count"] < 2:
            blockers.append("连板高度不足二板")
        if execution["mode"] == "live" and not candidate.get("buyable", True):
            blockers.append(f"盘中{candidate.get('buyable_reason') or '买不进'}")
        if not has_primary_signal:
            blockers.append("缺少昨弱今强或可靠买点")
        if (
            candidate["buy_hint"]
            and not buy_hint_reliable
            and candidate["cross"] != "昨弱今强"
        ):
            blockers.append("当前周期下买点可靠性不足")
        if cycle == "弱" and candidate["buy_hint"] and candidate["cross"] != "昨弱今强":
            blockers.append("弱周期分歧买点不进入主选")
        # 个股自身的原因排在全局闸门前面：界面只显示第一条时，看到的是"这只票为什么不行"
        own = [b for b in blockers if b not in global_blockers]
        blockers = _unique([*own, *global_blockers])

        item = {**candidate, "blockers": blockers}
        if not blockers and len(primary) < PRIMARY_LIMIT:
            item.update(tier="primary", rank=len(primary) + 1)
            primary.append(item)
        else:
            if not blockers and len(primary) >= PRIMARY_LIMIT:
                item["blockers"] = ["主选名额已满"]
            if len(watch) < WATCH_LIMIT:
                item.update(tier="watch", rank=len(watch) + 1)
                watch.append(item)

    confidence = execution["freshness"]["emotion_confidence"]
    emotion_cached = execution["freshness"]["emotion_cached"]
    ladder_cached = bool(ladder_data.get("cached"))
    critical_quality_issue = bool(
        execution["freshness"]["emotion_stale"]
        or execution["freshness"]["emotion_degraded"]
        or confidence < MIN_EMOTION_CONFIDENCE
        or ladder_stale
        or cycle == "未知"
    )
    if critical_quality_issue:
        quality = "low"
    elif emotion_cached or ladder_cached or confidence < 1.0:
        quality = "medium"
    else:
        quality = "high"

    warnings = list(dict.fromkeys([*execution_blockers, *global_blockers]))
    if not candidates:
        warnings.append("暂无符合预检条件的梯队候选")

    position = execution["position"]
    return {
        "generated_at": generated_text,
        "status": "degraded" if quality == "low" else "ready",
        "quality": quality,
        "executable": executable,
        "blockers": global_blockers,
        "execution": execution,
        "market": {
            "emotion_score": _integer(emotion_data.get("score"), 0),
            "emotion_level": str(emotion_data.get("level") or "未知"),
            "emotion_confidence": confidence,
            "cycle": cycle,
            "can_open": position["can_open"],
            "max_total_position": position["max_total_position"],
            "max_single_position": position["max_single_position"],
            "action": execution["action"],
        },
        "freshness": {
            **execution["freshness"],
            "ladder_as_of": str(ladder_data.get("as_of") or ""),
            "ladder_data_as_of": str(ladder_data.get("data_as_of") or ""),
            "ladder_cached": ladder_cached,
            "ladder_stale": ladder_stale,
        },
        "source_summary": source_summary,
        "primary": primary,
        "watch": watch,
        "warnings": _unique(warnings),
    }


def _normalise_stock_code(value: Any) -> str:
    text = str(value or "").strip().split(".", 1)[0]
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else text


def _analysis_code(value: Any) -> str:
    record = _mapping(value)
    direct = record.get("stock_code") or record.get("code")
    if direct:
        return _normalise_stock_code(direct)
    data = _mapping(record.get("data"))
    lowbuy = _mapping(record.get("lowbuy")) or _mapping(data.get("lowbuy"))
    return _normalise_stock_code(
        lowbuy.get("stock_code")
        or lowbuy.get("code")
        or data.get("stock_code")
        or data.get("code")
    )


def _index_analyses(analyses: Any) -> Tuple[Dict[str, Any], set[str]]:
    """接受 code->result 映射、单条结果或结果列表，统一按代码索引。"""

    indexed: Dict[str, Any] = {}
    attempted: set[str] = set()
    if isinstance(analyses, Mapping):
        if _analysis_code(analyses):
            code = _analysis_code(analyses)
            indexed[code] = analyses
            attempted.add(code)
        else:
            for raw_code, result in analyses.items():
                code = _normalise_stock_code(raw_code)
                if code:
                    indexed[code] = result
                    attempted.add(code)
        return indexed, attempted

    if isinstance(analyses, (list, tuple)):
        for result in analyses:
            code = _analysis_code(result)
            if code:
                indexed[code] = result
                attempted.add(code)
    return indexed, attempted


def _unwrap_analysis(value: Any) -> Tuple[Optional[Mapping[str, Any]], str]:
    if isinstance(value, BaseException):
        return None, str(value) or value.__class__.__name__
    if not isinstance(value, Mapping):
        return None, "分析结果格式无效"
    if value.get("success") is False:
        return None, str(value.get("error") or "个股分析失败")

    data = _mapping(value.get("data"))
    analysis = _mapping(value.get("lowbuy"))
    if not analysis:
        analysis = _mapping(data.get("lowbuy"))
    if not analysis and ("decision" in data or "veto_triggered" in data):
        analysis = data
    if not analysis and ("decision" in value or "veto_triggered" in value):
        analysis = value
    if not analysis:
        return None, str(value.get("error") or data.get("error") or "缺少低吸分析结果")
    if "decision" not in analysis and analysis.get("veto_triggered") is not True:
        return None, "低吸分析结果缺少决策字段"
    return analysis, ""


def _risk_precheck_result(value: Any, attempted: bool) -> Dict[str, Any]:
    if value is None:
        if attempted:
            return {
                "status": "error",
                "reviewed": False,
                "passed": False,
                "decision": "",
                "veto_triggered": False,
                "veto_reason": "",
                "error": "已发起分析但未返回结果",
            }
        return {
            "status": "pending",
            "reviewed": False,
            "passed": False,
            "decision": "",
            "veto_triggered": False,
            "veto_reason": "",
            "error": "",
        }

    analysis, error = _unwrap_analysis(value)
    if analysis is None:
        return {
            "status": "error",
            "reviewed": False,
            "passed": False,
            "decision": "",
            "veto_triggered": False,
            "veto_reason": "",
            "error": error,
        }

    decision = str(analysis.get("decision") or "")
    veto = bool(analysis.get("veto_triggered"))
    veto_reason = str(analysis.get("veto_reason") or "")
    passed = not veto and decision in {"低吸", "观察"}
    status = "excluded" if veto else ("passed" if passed else "rejected")
    return {
        "status": status,
        "reviewed": True,
        "passed": passed,
        "decision": decision,
        "veto_triggered": veto,
        "veto_reason": veto_reason,
        "total_score": analysis.get("total_score"),
        "timestamp": str(analysis.get("timestamp") or ""),
        "error": "",
    }


def apply_candidate_risk_precheck(
    workbench: Optional[Mapping[str, Any]],
    analyses: Any,
    analyzed_codes: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """将已有逐股低吸分析作为第二道风控，重新分配 primary/watch。

    函数只处理传入数据，不会触发任何分析或行情调用，并通过深拷贝保证输入
    ``workbench`` 与 ``analyses`` 不被修改。
    """

    result = deepcopy(dict(_mapping(workbench)))
    indexed, inferred_attempted = _index_analyses(analyses)
    explicit_attempted = {
        _normalise_stock_code(code) for code in (analyzed_codes or [])
        if _normalise_stock_code(code)
    }
    attempted_codes = inferred_attempted | explicit_attempted

    primary_values = result.get("primary")
    watch_values = result.get("watch")
    source_candidates = [
        deepcopy(dict(_mapping(candidate)))
        for candidate in [
            *(primary_values if isinstance(primary_values, list) else []),
            *(watch_values if isinstance(watch_values, list) else []),
        ]
        if _mapping(candidate).get("code")
    ]

    # 防御性去重；正常情况下 build_today_workbench 已经保证候选代码唯一。
    candidates_by_code: Dict[str, Dict[str, Any]] = {}
    for candidate in sorted(source_candidates, key=_candidate_sort_key):
        code = _normalise_stock_code(candidate.get("code"))
        if code and code not in candidates_by_code:
            candidate["code"] = code
            candidates_by_code[code] = candidate

    primary: List[Dict[str, Any]] = []
    watch: List[Dict[str, Any]] = []
    risk_excluded: List[Dict[str, Any]] = []
    reviewed = passed = excluded = errors = 0

    prepared: List[Tuple[Dict[str, Any], Dict[str, Any], List[str]]] = []
    for candidate in sorted(candidates_by_code.values(), key=_candidate_sort_key):
        code = candidate["code"]
        analysis_value = indexed.get(code)
        risk = _risk_precheck_result(analysis_value, code in attempted_codes)
        if risk["reviewed"]:
            reviewed += 1
        if risk["passed"]:
            passed += 1
        if risk["status"] == "excluded":
            excluded += 1
        if risk["status"] == "error":
            errors += 1

        # “主选名额已满”只是上一轮容量结果，不是候选自身风险，重排前移除。
        base_blockers = [
            str(blocker) for blocker in candidate.get("blockers", [])
            if str(blocker) != "主选名额已满"
        ]
        item = {**candidate, "risk_precheck": risk}

        if risk["status"] == "excluded":
            reason = risk["veto_reason"] or "触发低吸一票否决"
            item["blockers"] = _unique([*base_blockers, f"个股一票否决：{reason}"])
            item.update(tier="risk_excluded", rank=len(risk_excluded) + 1)
            risk_excluded.append(item)
            continue
        if risk["status"] == "pending":
            base_blockers.append("个股风险预检未完成")
        elif risk["status"] == "error":
            base_blockers.append("个股风险预检异常")
        elif risk["status"] == "rejected":
            decision = risk["decision"] or "未知"
            if decision == "回避":
                base_blockers.append("个股风险预检结论为回避")
            else:
                base_blockers.append(f"个股风险预检未通过（{decision}）")
        prepared.append((item, risk, _unique(base_blockers)))

    # 原候选顺序即稳定的预检优先级。通过深检且无自身 blocker 的候选依次
    # 填满主选，因上一轮容量落入 watch 的第 4 名可自然回填。
    for item, risk, blockers in prepared:
        if risk["passed"] and not blockers and len(primary) < PRIMARY_LIMIT:
            item["blockers"] = []
            item.update(tier="primary", rank=len(primary) + 1)
            primary.append(item)
            continue

        if risk["passed"] and not blockers:
            blockers = ["主选名额已满"]
        if len(watch) < WATCH_LIMIT:
            item["blockers"] = blockers
            item.update(tier="watch", rank=len(watch) + 1)
            watch.append(item)

    result["primary"] = primary
    result["watch"] = watch
    result["risk_excluded"] = risk_excluded
    result["deep_precheck"] = {
        "reviewed": reviewed,
        "passed": passed,
        "excluded": excluded,
        "errors": errors,
    }
    return result
