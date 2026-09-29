"""
涨停股"能不能买进"的统一判定（龙头决策、今日作战台共用，避免两处口径不一）。
"""

from typing import Any, Tuple


def normalize_trade_time(value: Any) -> str:
    """把 92500 / 0925 / 09:25 / 09:25:00 统一成 HH:MM:SS。"""
    digits = ''.join(ch for ch in str(value or '').strip() if ch.isdigit())
    if len(digits) == 6:
        return f"{digits[0:2]}:{digits[2:4]}:{digits[4:6]}"
    if len(digits) == 4:
        return f"{digits[0:2]}:{digits[2:4]}:00"
    text = str(value or '').strip()
    if len(text) == 5 and text.count(':') == 1:
        return f"{text}:00"
    return text


def check_limit_buyability(first_limit_time: Any, turnover_rate: Any) -> Tuple[bool, str]:
    """
    已涨停的股票还能不能买进。
    一字板（09:30 前封板）/ 秒板（09:31 前封板）/ 封死且换手 < 1% 视为买不进。
    """
    t = normalize_trade_time(first_limit_time)
    if t and t <= '09:30:00':
        return False, '一字板，无法买入'
    if t and t <= '09:31:00':
        return False, '秒板，买入困难'
    try:
        turnover = float(turnover_rate or 0)
    except (TypeError, ValueError):
        turnover = 0.0
    if turnover < 1:
        return False, '封板牢固，买入困难'
    return True, '可尝试排板买入'
