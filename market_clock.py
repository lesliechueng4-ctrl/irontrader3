"""
行情时钟：现在是不是"行情还在变"的时段，以及最近一次收盘（含午间休市）是什么时候。

用途：全市场快照这类重数据，盘中按 TTL 刷新；午休、收盘后、周末节假日行情不再变化，
只要手里的快照是在最近一次收盘之后取的，就代表当前状态，不用每 2 分钟重拉一次。

时段（北京时间，交易日）：
- 09:15–11:32、13:00–15:02 视为"行情在变"（含集合竞价；收盘后留 2 分钟等数据落定）
- 其余时间看最近一次收盘：当天 11:32（午休）/ 15:02（收盘），或上一个交易日 15:02
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

LIVE_WINDOWS = ((time(9, 15), time(11, 32)), (time(13, 0), time(15, 2)))
LUNCH_CLOSE = time(11, 32)
DAY_CLOSE = time(15, 2)

TradingDayFn = Callable[[date], bool]


def _default_trading_day(day: date) -> bool:
    """周末休市；工作日看已加载的交易日历（执行闸启动时会加载），没加载时按开市算。

    这里刻意不主动联网拉日历：这个判断在取快照的热路径上，不能因为日历接口慢而卡住。
    """
    if day.weekday() >= 5:
        return False
    try:
        import workbench_service as ws

        dates = getattr(ws, "_TRADING_CALENDAR_DATES", None)
        span = getattr(ws, "_TRADING_CALENDAR_RANGE", None)
        if dates is not None and span is not None and span[0] <= day <= span[1]:
            return day in dates
    except Exception:
        pass
    return True


def _local(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(TZ)
    return now.astimezone(TZ) if now.tzinfo else now.replace(tzinfo=TZ)


def is_live(now: Optional[datetime] = None, trading_day: Optional[TradingDayFn] = None) -> bool:
    """行情是否还在变化（交易日的竞价与连续交易时段）。"""
    local = _local(now)
    if not (trading_day or _default_trading_day)(local.date()):
        return False
    current = local.time().replace(tzinfo=None)
    return any(start <= current < end for start, end in LIVE_WINDOWS)


def last_close(now: Optional[datetime] = None, trading_day: Optional[TradingDayFn] = None) -> Optional[datetime]:
    """最近一次收盘（午间休市也算）的时间点；行情还在变时返回 None。"""
    check = trading_day or _default_trading_day
    local = _local(now)
    if is_live(local, check):
        return None
    current = local.time().replace(tzinfo=None)
    if check(local.date()):
        if current >= DAY_CLOSE:
            return datetime.combine(local.date(), DAY_CLOSE, TZ)
        if current >= LUNCH_CLOSE:
            return datetime.combine(local.date(), LUNCH_CLOSE, TZ)
    day = local.date() - timedelta(days=1)
    for _ in range(30):  # 长假也够用
        if check(day):
            return datetime.combine(day, DAY_CLOSE, TZ)
        day -= timedelta(days=1)
    return None


def snapshot_is_final(fetched_at: Optional[datetime], now: Optional[datetime] = None,
                      trading_day: Optional[TradingDayFn] = None) -> bool:
    """快照取于最近一次收盘之后（且现在行情不再变化）：它就是当前状态，不用重拉。"""
    if fetched_at is None:
        return False
    boundary = last_close(now, trading_day)
    return boundary is not None and _local(fetched_at) >= boundary


__all__ = ["LIVE_WINDOWS", "TZ", "is_live", "last_close", "snapshot_is_final"]
