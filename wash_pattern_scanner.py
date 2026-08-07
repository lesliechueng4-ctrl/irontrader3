"""A-share wash pattern scanner — 上涨途中强洗盘形态.

形态说明（圈主洗盘）：
    A（两阴一阳两阴）: 缩量阴 + 缩量阴 + 放量阳（反弹） + 缩量阴 + 缩量阴
    B（两阴两阳两阴）: 缩量阴 + 缩量阴 + 放量阳 + 缩量阳 + 缩量阴 + 缩量阴

关键约束：
    * 洗盘阴线须为小实体（yin_max_body_pct），非暴跌形态
    * 中间阳线必须明显放量（yang_vol_ratio），确认主力护盘
    * Pattern B 第二根阳线须缩量，排除二次拉升假信号
    * 全程须在均线多头排列环境（MA5>MA10>MA20>MA60）
    * 洗盘阴线低点不破 MA20 支撑（require_ma_support）
    * 洗盘前须有大阳/涨停先行（require_impulse），确认主升段
    * 反弹阳线不创近期新高（require_no_new_high），纯反弹性质
    * 末尾阴线量能接近近期地量（require_near_low_vol），浮筹已净
    * 洗盘结束价不低于起始价97%（require_no_step_down），横盘非下跌

Data source:
    AKShare daily A-share data.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import threading
import time
import warnings
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

warnings.filterwarnings("ignore")


def ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


ensure_utf8_stdio()

import akshare as ak
import pandas as pd
import requests
import numpy as np
from tqdm import tqdm


def progress_write(message: str) -> None:
    writer = getattr(tqdm, "write", None)
    if callable(writer):
        writer(message)
    else:
        print(message)


def brief_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ")
    if len(message) > 180:
        message = message[:177] + "..."
    return f"{exc.__class__.__name__}: {message}"


class DailyDataSourceError(RuntimeError):
    """No trustworthy daily history was available for one stock.

    A normal strategy miss continues to return an empty result.  This typed
    exception is reserved for data coverage failures so Web/CLI callers can
    count them separately instead of reporting a misleading zero-match scan.
    """

    def __init__(self, code: str, errors: Iterable[str]):
        self.code = normalize_stock_code(code)
        self.source_errors = tuple(str(item) for item in errors if item)
        detail = "; ".join(self.source_errors) or "all sources returned no usable history"
        super().__init__(f"{self.code} daily history unavailable: {detail}")


DEFAULT_OUTPUT = str(Path(__file__).resolve().with_name("wash_pattern_results.csv"))
DEFAULT_WORKERS = 12
_THREAD_LOCAL = threading.local()
PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
STRONG_MODE = "强趋势洗盘"
LOW_REVERSAL_MODE = "低位反转洗盘"
BREAKOUT_BASE_MODE = "突破前蓄势"


@dataclass(frozen=True)
class ScanConfig:
    scan_mode: str = "strong"
    trend_rise_days: int = 20
    trend_min_rise_pct: float = 15.0
    require_ma_bullish: bool = True
    # 缩量阴线：允许首阴不缩量，从第二阴起要求当日量 ≤ 前日量 * shrink_ratio
    shrink_ratio: float = 0.95
    # 反弹阳线：量 ≥ 紧邻前阴量 * yang_vol_ratio（提高至1.50，要求明显放量）
    yang_vol_ratio: float = 1.50
    # 洗盘阴线实体占收盘价的最大比例（百分比），超过则视为暴跌非洗盘
    yin_max_body_pct: float = 5.0
    max_drawdown_pct: float = 8.0
    # C 试盘回落洗盘：阴阴 + 放量突破阳 + 高开回落换手阴 + 缩量阴阴
    c_front_vol_ratio: float = 1.20
    c_yang_vol_ratio: float = 1.35
    c_shakeout_body_pct: float = 6.0
    c_shakeout_min_vol_ratio: float = 0.90
    c_tail_vol_ratio: float = 0.75
    c_tail_flat_ratio: float = 1.05
    confirm_yang: int = 0
    stock_pool: str = "all_a"
    pool_source: str = "auto"
    max_stocks: int = 0
    fetch_days: int = 120
    recent_days: int = 30
    adjust: str = "qfq"
    data_source: str = "auto"
    # 在线行情不可用时，只允许使用最近若干天内的完整历史缓存。
    # 10 天可覆盖周末和 A 股长假，同时避免数周前的数据冒充实时扫描。
    cache_max_stale_days: int = 10
    output: str = DEFAULT_OUTPUT
    workers: int = DEFAULT_WORKERS
    show_errors: bool = False
    as_of_date: str = ""
    # ── 新增过滤条件 ──────────────────────────────────────
    # 洗盘阴线低点不破 MA20（0.5% 容忍）
    require_ma_support: bool = True
    # 末尾收盘 ≥ 首根阴线开盘 × 97%（横盘而非下台阶）
    require_no_step_down: bool = True
    # 反弹阳不创近期新高（纯反弹性质）
    require_no_new_high: bool = True
    no_new_high_lookback: int = 15
    # 末尾阴量 ≤ 近期最低量 × ratio（浮筹换手干净）
    require_near_low_vol: bool = True
    near_low_vol_ratio: float = 1.3
    near_low_vol_lookback: int = 20
    # 洗盘前 N 日内须有单日涨幅 ≥ min_impulse_pct% 的大阳
    require_impulse: bool = True
    min_impulse_pct: float = 7.0
    impulse_lookback: int = 10
    # 输出最新K线上的半完成形态：A=阴阴阳阴，B=阴阴阳阳阴
    include_candidate_warnings: bool = True
    # The legacy Eastmoney spot prefilter is intentionally lossy (price,
    # turnover, amount and board exclusions).  It must be an explicit opt-in;
    # a full-A scan is complete by default.
    enable_lossy_prescreen: bool = False
    # 低位反转洗盘：独立于强趋势过滤，默认只要求近期涨幅未进入强趋势区间
    low_reversal_max_rise_pct: float = 15.0
    low_reversal_require_no_step_down: bool = False
    # ── low_reversal 增强过滤（避免把阴跌出货误判为低位反转）──
    # 位置条件：现价须处于 lookback 区间的下沿（low-high 区间分位 ≤ 阈值）
    low_reversal_require_low_position: bool = True
    low_reversal_position_lookback: int = 120
    low_reversal_position_max_pct: float = 0.35
    # 企稳条件：MA5 走平或上拐（ma5[i] ≥ ma5[i-1]）
    low_reversal_require_stabilize: bool = True
    # ── 突破前蓄势（launch base）模式 ─────────────────────
    # 捕捉启动初期的"两阴一阳夹两阴"蓄势 base：不要求前置 impulse / 均线多头，
    # 允许末尾阴线放量（蓄势震荡而非缩量洗盘），但要求处于上涨初段且临近突破。
    breakout_base_min_rise_pct: float = 5.0       # 蓄势前已有的最小涨幅（确认有启动迹象）
    breakout_base_max_rise_pct: float = 80.0      # 排除已严重过热的高位
    breakout_base_position_lookback: int = 60
    breakout_base_position_min_pct: float = 0.5   # 收盘处于区间中上沿（临近突破）
    breakout_base_require_stabilize: bool = True  # MA5 走平或上拐
    breakout_base_trailing_shrink_ratio: float = 1.6  # 末尾阴线量上限（允许温和放量震荡）
    # 末尾缩量阴线的量比上限；None 时回退 shrink_ratio，
    # 保持 strong / low_reversal 模式行为完全不变。
    last_yin_shrink_ratio: Optional[float] = None


@dataclass(frozen=True)
class StockInfo:
    code: str
    name: str = ""


@dataclass(frozen=True)
class PatternHit:
    end_index: int
    start_index: int
    pattern_type: str
    drawdown_pct: float
    status: str = "已确认"
    note: str = ""
    scan_mode: str = STRONG_MODE


RESULT_COLUMNS = [
    "代码",
    "名称",
    "状态",
    "扫描模式",
    "洗盘开始日",
    "洗盘结束日",
    "距今(天)",
    "模式",
    "备注",
    "结束收盘",
    "当前价",
    "最新行情日",
    "后续涨幅%",
    "趋势涨幅%",
    "洗盘回撤%",
    "距MA20%",
]


def is_yin(row: pd.Series) -> bool:
    """Bearish candle: close is lower than open."""
    return float(row["close"]) < float(row["open"])


def is_yang(row: pd.Series) -> bool:
    """Bullish candle: close is greater than or equal to open."""
    return float(row["close"]) >= float(row["open"])


def add_ma(df: pd.DataFrame) -> pd.DataFrame:
    for days in (5, 10, 20, 60):
        df[f"ma{days}"] = df["close"].rolling(days).mean()
    return df


def ma_bullish(row: pd.Series) -> bool:
    values = [row.get("ma5"), row.get("ma10"), row.get("ma20"), row.get("ma60")]
    if any(pd.isna(value) for value in values):
        return False
    return bool(values[0] > values[1] > values[2] > values[3])


def shrink_vol(vol_now: float, vol_prev: float, ratio: float = 0.95) -> bool:
    if vol_prev <= 0:
        return False
    return vol_now <= vol_prev * ratio


def expand_vol(vol_now: float, vol_prev: float, ratio: float = 1.50) -> bool:
    if vol_prev <= 0:
        return False
    return vol_now >= vol_prev * ratio


def is_small_body_yin(row: pd.Series, max_body_pct: float) -> bool:
    """阴线小实体过滤：跌幅须在 max_body_pct 以内，排除暴跌 K 线."""
    close = float(row["close"])
    open_ = float(row["open"])
    if open_ <= 0:
        return False
    body_pct = (open_ - close) / open_ * 100
    return body_pct <= max_body_pct


def check_ma_support(yin_rows: list[pd.Series]) -> bool:
    """所有洗盘阴线最低价不破 MA20（留 0.5% 容忍），排除均线支撑破位."""
    for row in yin_rows:
        ma20 = row.get("ma20")
        if ma20 is None or pd.isna(ma20):
            continue
        if float(row["low"]) < float(ma20) * 0.995:
            return False
    return True


def check_no_step_down(first_yin: pd.Series, last_yin: pd.Series) -> bool:
    """末尾阴线收盘 ≥ 首根阴线开盘 × 97%，确认横盘而非单边下台阶."""
    open_ref = float(first_yin["open"])
    if open_ref <= 0:
        return False
    return float(last_yin["close"]) >= open_ref * 0.97


def check_no_new_high(
    df: pd.DataFrame, yang_row: pd.Series, start_index: int, lookback: int
) -> bool:
    """反弹阳最高价低于洗盘前 lookback 日内最高价，确认纯反弹而非有效突破."""
    lo = max(0, start_index - lookback)
    if lo >= start_index:
        return True
    recent_high = float(df.iloc[lo:start_index]["high"].max())
    return float(yang_row["high"]) < recent_high


def check_near_low_vol(
    df: pd.DataFrame, end_index: int, last_vol: float, lookback: int, ratio: float
) -> bool:
    """末尾阴线量 ≤ 近 lookback 日最低量 × ratio，浮筹换手干净信号."""
    lo = max(0, end_index - lookback)
    recent_min = float(df.iloc[lo:end_index]["volume"].min())
    if recent_min <= 0:
        return True
    return last_vol <= recent_min * ratio


def check_impulse_before(
    df: pd.DataFrame, start_index: int, min_pct: float, lookback: int
) -> bool:
    """洗盘前 lookback 日内有单日涨幅 ≥ min_pct% 的大阳/涨停（主升段佐证）."""
    lo = max(0, start_index - lookback)
    if lo >= start_index:
        return False
    window = df.iloc[lo:start_index]
    if "pct_chg" not in window.columns:
        return True
    return bool((window["pct_chg"] >= min_pct).any())


def calc_drawdown(window: pd.DataFrame) -> float:
    # 用第一根K线的开盘价作为基准，更准确反映洗盘起点的实际回撤
    start_ref = float(window.iloc[0]["open"])
    if start_ref <= 0:
        return float("inf")
    lowest_low = float(window["low"].min())
    return (start_ref - lowest_low) / start_ref * 100


def has_confirmation(df: pd.DataFrame, end_index: int, confirm_yang: int) -> bool:
    if confirm_yang <= 0:
        return True
    if end_index + confirm_yang >= len(df):
        return False
    rows = df.iloc[end_index + 1 : end_index + 1 + confirm_yang]
    return all(is_yang(row) for _, row in rows.iterrows())


def trend_rise_pct(df: pd.DataFrame, end_index: int, cfg: ScanConfig) -> float:
    trend_start = max(0, end_index - cfg.trend_rise_days)
    ref_close = float(df.iloc[trend_start]["close"])
    if ref_close <= 0:
        return float("-inf")
    close = float(df.iloc[end_index]["close"])
    return (close - ref_close) / ref_close * 100


def enabled_scan_modes(cfg: ScanConfig) -> tuple[str, ...]:
    if cfg.scan_mode == "both":
        return ("strong", "low_reversal")
    if cfg.scan_mode == "all":
        return ("strong", "low_reversal", "breakout_base")
    return (cfg.scan_mode,)


def mode_label(mode: str) -> str:
    if mode == "low_reversal":
        return LOW_REVERSAL_MODE
    if mode == "breakout_base":
        return BREAKOUT_BASE_MODE
    return STRONG_MODE


def with_mode(hit: PatternHit, mode: str) -> PatternHit:
    return replace(
        hit,
        scan_mode=mode_label(mode),
    )


def strong_trend_context_ok(df: pd.DataFrame, end_index: int, cfg: ScanConfig) -> bool:
    row = df.iloc[end_index]
    if cfg.require_ma_bullish and not ma_bullish(row):
        return False
    return trend_rise_pct(df, end_index, cfg) >= cfg.trend_min_rise_pct


def low_reversal_context_ok(df: pd.DataFrame, end_index: int, cfg: ScanConfig) -> bool:
    if trend_rise_pct(df, end_index, cfg) >= cfg.low_reversal_max_rise_pct:
        return False
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    if cfg.low_reversal_require_low_position:
        start = max(0, end_index - cfg.low_reversal_position_lookback + 1)
        window_low = low[start : end_index + 1].min()
        window_high = high[start : end_index + 1].max()
        rng = window_high - window_low
        pos = (close[end_index] - window_low) / rng if rng > 0 else 0.5
        if pos > cfg.low_reversal_position_max_pct:
            return False
    if cfg.low_reversal_require_stabilize and end_index >= 1:
        ma5 = pd.Series(close).rolling(5, min_periods=1).mean().to_numpy()
        if ma5[end_index] < ma5[end_index - 1]:
            return False
    return True


def low_reversal_config(cfg: ScanConfig) -> ScanConfig:
    return replace(
        cfg,
        require_ma_bullish=False,
        require_ma_support=False,
        require_no_step_down=cfg.low_reversal_require_no_step_down,
        require_no_new_high=False,
        require_near_low_vol=False,
        require_impulse=False,
    )


def breakout_base_config(cfg: ScanConfig) -> ScanConfig:
    """突破前蓄势模式的形态过滤配置。

    放开"强趋势洗盘"中针对中段洗盘设计的过滤（前置 impulse、均线多头、
    MA20 支撑、缩量见地量、反弹不创新高），并允许末尾阴线温和放量
    （启动初期的蓄势震荡常见放量），其余形态约束（小实体、回撤上限、
    不下台阶）保持不变。
    """
    return replace(
        cfg,
        require_ma_bullish=False,
        require_ma_support=False,
        require_no_new_high=False,
        require_near_low_vol=False,
        require_impulse=False,
        last_yin_shrink_ratio=cfg.breakout_base_trailing_shrink_ratio,
    )


@dataclass(frozen=True)
class VectorScanData:
    index: np.ndarray
    open_: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    small_yin: np.ndarray
    yang: np.ndarray
    ma_support: np.ndarray
    ma_bullish: np.ndarray
    trend_rise: np.ndarray
    confirm_yang: np.ndarray
    recent_high_before: np.ndarray
    recent_min_volume_before: np.ndarray
    impulse_before: np.ndarray

    @property
    def length(self) -> int:
        return len(self.close)


def numeric_array(df: pd.DataFrame, column: str, default: float = np.nan) -> np.ndarray:
    if column not in df.columns:
        return np.full(len(df), default, dtype=float)
    return pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)


def lag_float(values: np.ndarray, periods: int) -> np.ndarray:
    if periods <= 0:
        return values.astype(float, copy=True)
    result = np.full(len(values), np.nan, dtype=float)
    if periods < len(values):
        result[periods:] = values[:-periods]
    return result


def lag_bool(values: np.ndarray, periods: int) -> np.ndarray:
    if periods <= 0:
        return values.astype(bool, copy=True)
    result = np.zeros(len(values), dtype=bool)
    if periods < len(values):
        result[periods:] = values[:-periods]
    return result


def lead_bool(values: np.ndarray, periods: int) -> np.ndarray:
    if periods <= 0:
        return values.astype(bool, copy=True)
    result = np.zeros(len(values), dtype=bool)
    if periods < len(values):
        result[:-periods] = values[periods:]
    return result


def rolling_min(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 0:
        return np.full(len(values), np.nan, dtype=float)
    return pd.Series(values).rolling(window).min().to_numpy(dtype=float)


def rolling_max_before(values: np.ndarray, lookback: int) -> np.ndarray:
    if lookback <= 0:
        return np.full(len(values), np.nan, dtype=float)
    return (
        pd.Series(values)
        .rolling(lookback, min_periods=1)
        .max()
        .shift(1)
        .to_numpy(dtype=float)
    )


def rolling_min_before(values: np.ndarray, lookback: int) -> np.ndarray:
    if lookback <= 0:
        return np.full(len(values), np.nan, dtype=float)
    return (
        pd.Series(values)
        .rolling(lookback, min_periods=1)
        .min()
        .shift(1)
        .to_numpy(dtype=float)
    )


def trend_rise_array(close: np.ndarray, cfg: ScanConfig) -> np.ndarray:
    index = np.arange(len(close))
    ref_index = np.maximum(0, index - cfg.trend_rise_days)
    ref_close = close[ref_index]
    with np.errstate(divide="ignore", invalid="ignore"):
        rise = (close - ref_close) / ref_close * 100
    return np.where(ref_close > 0, rise, float("-inf"))


def low_position_array(
    close: np.ndarray, high: np.ndarray, low: np.ndarray, lookback: int
) -> np.ndarray:
    """每根 K 线收盘价在过去 lookback 根 [最低,最高] 区间内的分位（0=最低,1=最高）。

    用于判定"现价是否处于低位"。数据不足 lookback 时用已有窗口计算。
    """
    n = len(close)
    pos = np.ones(n, dtype=float)  # 默认 1（高位），不满足低位条件
    for i in range(n):
        start = max(0, i - lookback + 1)
        window_low = low[start : i + 1].min()
        window_high = high[start : i + 1].max()
        rng = window_high - window_low
        if rng > 0:
            pos[i] = (close[i] - window_low) / rng
        else:
            pos[i] = 0.5
    return pos


def ma5_stabilize_array(close: np.ndarray) -> np.ndarray:
    """MA5 是否走平或上拐：ma5[i] >= ma5[i-1]。"""
    n = len(close)
    if n == 0:
        return np.zeros(0, dtype=bool)
    ma5 = pd.Series(close).rolling(5, min_periods=1).mean().to_numpy()
    prev = np.concatenate(([ma5[0]], ma5[:-1]))
    return ma5 >= prev


def confirmation_array(yang: np.ndarray, confirm_yang: int) -> np.ndarray:
    if confirm_yang <= 0:
        return np.ones(len(yang), dtype=bool)
    confirmed = np.ones(len(yang), dtype=bool)
    for offset in range(1, confirm_yang + 1):
        confirmed &= lead_bool(yang, offset)
    return confirmed


def impulse_before_array(df: pd.DataFrame, cfg: ScanConfig) -> np.ndarray:
    if cfg.impulse_lookback <= 0:
        return np.zeros(len(df), dtype=bool)
    if "pct_chg" not in df.columns:
        return np.arange(len(df)) > 0

    pct_chg = numeric_array(df, "pct_chg")
    recent_max = rolling_max_before(pct_chg, cfg.impulse_lookback)
    return recent_max >= cfg.min_impulse_pct


def build_vector_scan_data(df: pd.DataFrame, cfg: ScanConfig) -> VectorScanData:
    open_ = numeric_array(df, "open")
    high = numeric_array(df, "high")
    low = numeric_array(df, "low")
    close = numeric_array(df, "close")
    volume = numeric_array(df, "volume")
    ma5 = numeric_array(df, "ma5")
    ma10 = numeric_array(df, "ma10")
    ma20 = numeric_array(df, "ma20")
    ma60 = numeric_array(df, "ma60")

    with np.errstate(divide="ignore", invalid="ignore"):
        body_pct = (open_ - close) / open_ * 100

    small_yin = (close < open_) & (open_ > 0) & (body_pct <= cfg.yin_max_body_pct)
    yang = close >= open_
    ma_support = np.isnan(ma20) | (low >= ma20 * 0.995)
    ma_bullish_values = (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)

    return VectorScanData(
        index=np.arange(len(df)),
        open_=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        small_yin=small_yin,
        yang=yang,
        ma_support=ma_support,
        ma_bullish=ma_bullish_values,
        trend_rise=trend_rise_array(close, cfg),
        confirm_yang=confirmation_array(yang, cfg.confirm_yang),
        recent_high_before=rolling_max_before(high, cfg.no_new_high_lookback),
        recent_min_volume_before=rolling_min_before(volume, cfg.near_low_vol_lookback),
        impulse_before=impulse_before_array(df, cfg),
    )


def drawdown_array(data: VectorScanData, pattern_length: int) -> np.ndarray:
    start_open = lag_float(data.open_, pattern_length - 1)
    lowest_low = rolling_min(data.low, pattern_length)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown = (start_open - lowest_low) / start_open * 100
    return np.where(start_open > 0, drawdown, float("inf"))


def shrink_mask(data: VectorScanData, now_lag: int, prev_lag: int, cfg: ScanConfig) -> np.ndarray:
    vol_now = lag_float(data.volume, now_lag)
    vol_prev = lag_float(data.volume, prev_lag)
    return (vol_prev > 0) & (vol_now <= vol_prev * cfg.shrink_ratio)


def last_yin_ratio(cfg: ScanConfig) -> float:
    """末尾阴线缩量比率：未显式配置时回退 shrink_ratio（保持原行为）。"""
    return cfg.shrink_ratio if cfg.last_yin_shrink_ratio is None else cfg.last_yin_shrink_ratio


def last_yin_shrink_mask(data: VectorScanData, cfg: ScanConfig) -> np.ndarray:
    """末根阴线相对前一根阴线的量约束，使用可配置的 last_yin_ratio。"""
    return volume_le_mask(data, 0, 1, last_yin_ratio(cfg))


def volume_le_mask(
    data: VectorScanData, now_lag: int, prev_lag: int, ratio: float
) -> np.ndarray:
    vol_now = lag_float(data.volume, now_lag)
    vol_prev = lag_float(data.volume, prev_lag)
    return (vol_prev > 0) & (vol_now <= vol_prev * ratio)


def volume_ge_mask(
    data: VectorScanData, now_lag: int, prev_lag: int, ratio: float
) -> np.ndarray:
    vol_now = lag_float(data.volume, now_lag)
    vol_prev = lag_float(data.volume, prev_lag)
    return (vol_prev > 0) & (vol_now >= vol_prev * ratio)


def expand_from_base_mask(
    data: VectorScanData,
    now_lag: int,
    base_lag: int,
    ref_lag: int,
    cfg: ScanConfig,
) -> np.ndarray:
    vol_now = lag_float(data.volume, now_lag)
    base = np.maximum(lag_float(data.volume, base_lag), lag_float(data.volume, ref_lag) * 0.6)
    return (base > 0) & (vol_now >= base * cfg.yang_vol_ratio)


def expand_from_base_ratio_mask(
    data: VectorScanData,
    now_lag: int,
    base_lag: int,
    ref_lag: int,
    ratio: float,
) -> np.ndarray:
    vol_now = lag_float(data.volume, now_lag)
    base = np.maximum(lag_float(data.volume, base_lag), lag_float(data.volume, ref_lag) * 0.6)
    return (base > 0) & (vol_now >= base * ratio)


def no_step_down_mask(data: VectorScanData, start_lag: int) -> np.ndarray:
    start_open = lag_float(data.open_, start_lag)
    return (start_open > 0) & (data.close >= start_open * 0.97)


def no_new_high_mask(data: VectorScanData, start_lag: int, yang_lag: int, cfg: ScanConfig) -> np.ndarray:
    if not cfg.require_no_new_high or cfg.no_new_high_lookback <= 0:
        return np.ones(data.length, dtype=bool)

    start_index = data.index - start_lag
    recent_high = lag_float(data.recent_high_before, start_lag)
    yang_high = lag_float(data.high, yang_lag)
    return (start_index <= 0) | (yang_high < recent_high)


def ma_support_mask(data: VectorScanData, lags: tuple[int, ...], cfg: ScanConfig) -> np.ndarray:
    if not cfg.require_ma_support:
        return np.ones(data.length, dtype=bool)

    supported = np.ones(data.length, dtype=bool)
    for lag in lags:
        supported &= lag_bool(data.ma_support, lag)
    return supported


def near_low_volume_mask(data: VectorScanData, cfg: ScanConfig) -> np.ndarray:
    if not cfg.require_near_low_vol:
        return np.ones(data.length, dtype=bool)

    recent_min = data.recent_min_volume_before
    return (recent_min <= 0) | (data.volume <= recent_min * cfg.near_low_vol_ratio)


def impulse_mask(data: VectorScanData, start_lag: int, cfg: ScanConfig) -> np.ndarray:
    if not cfg.require_impulse:
        return np.ones(data.length, dtype=bool)
    return lag_bool(data.impulse_before, start_lag)


def common_pattern_filters(
    data: VectorScanData,
    cfg: ScanConfig,
    start_lag: int,
    yang_lag: int,
    support_lags: tuple[int, ...],
    require_near_low_vol: bool,
) -> np.ndarray:
    filters = ma_support_mask(data, support_lags, cfg)
    if cfg.require_no_step_down:
        filters &= no_step_down_mask(data, start_lag)
    filters &= no_new_high_mask(data, start_lag, yang_lag, cfg)
    if require_near_low_vol:
        filters &= near_low_volume_mask(data, cfg)
    filters &= impulse_mask(data, start_lag, cfg)
    return filters


def match_pattern_a_vectorized(
    data: VectorScanData, cfg: ScanConfig
) -> tuple[np.ndarray, np.ndarray]:
    drawdown = drawdown_array(data, 5)
    mask = (
        lag_bool(data.small_yin, 4)
        & lag_bool(data.small_yin, 3)
        & shrink_mask(data, 3, 4, cfg)
        & lag_bool(data.yang, 2)
        & expand_from_base_mask(data, 2, 3, 5, cfg)
        & lag_bool(data.small_yin, 1)
        & shrink_mask(data, 1, 2, cfg)
        & data.small_yin
        & last_yin_shrink_mask(data, cfg)
        & (drawdown <= cfg.max_drawdown_pct)
    )
    mask &= common_pattern_filters(
        data,
        cfg,
        start_lag=4,
        yang_lag=2,
        support_lags=(4, 3, 1, 0),
        require_near_low_vol=True,
    )
    return mask, drawdown


def match_pattern_b_vectorized(
    data: VectorScanData, cfg: ScanConfig
) -> tuple[np.ndarray, np.ndarray]:
    drawdown = drawdown_array(data, 6)
    mask = (
        lag_bool(data.small_yin, 5)
        & lag_bool(data.small_yin, 4)
        & shrink_mask(data, 4, 5, cfg)
        & lag_bool(data.yang, 3)
        & expand_from_base_mask(data, 3, 4, 6, cfg)
        & lag_bool(data.yang, 2)
        & shrink_mask(data, 2, 3, cfg)
        & lag_bool(data.small_yin, 1)
        & shrink_mask(data, 1, 2, cfg)
        & data.small_yin
        & last_yin_shrink_mask(data, cfg)
        & (drawdown <= cfg.max_drawdown_pct)
    )
    mask &= common_pattern_filters(
        data,
        cfg,
        start_lag=5,
        yang_lag=3,
        support_lags=(5, 4, 1, 0),
        require_near_low_vol=True,
    )
    return mask, drawdown


def match_pattern_c_vectorized(
    data: VectorScanData, cfg: ScanConfig
) -> tuple[np.ndarray, np.ndarray]:
    """C: 阴阴 + 放量试盘阳 + 高开回落换手阴 + 缩量阴阴."""
    drawdown = drawdown_array(data, 6)
    shakeout_open = lag_float(data.open_, 2)
    shakeout_close = lag_float(data.close, 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        shakeout_body_pct = (shakeout_open - shakeout_close) / shakeout_open * 100

    shakeout_yin = (
        (shakeout_close < shakeout_open)
        & (shakeout_open > 0)
        & (shakeout_body_pct <= cfg.c_shakeout_body_pct)
        & (shakeout_open > lag_float(data.close, 3))
        & (lag_float(data.high, 2) >= lag_float(data.high, 3))
    )

    mask = (
        lag_bool(data.small_yin, 5)
        & lag_bool(data.small_yin, 4)
        & volume_le_mask(data, 4, 5, cfg.c_front_vol_ratio)
        & lag_bool(data.yang, 3)
        & expand_from_base_ratio_mask(data, 3, 4, 6, cfg.c_yang_vol_ratio)
        & shakeout_yin
        & volume_ge_mask(data, 2, 3, cfg.c_shakeout_min_vol_ratio)
        & lag_bool(data.small_yin, 1)
        & volume_le_mask(data, 1, 2, cfg.c_tail_vol_ratio)
        & data.small_yin
        & volume_le_mask(data, 0, 1, cfg.c_tail_flat_ratio)
        & (drawdown <= cfg.max_drawdown_pct)
    )
    mask &= ma_support_mask(data, (5, 4, 2, 1, 0), cfg)
    if cfg.require_no_step_down:
        mask &= no_step_down_mask(data, 5)
    mask &= impulse_mask(data, 5, cfg)
    return mask, drawdown


def match_candidate_pattern_a_vectorized(
    data: VectorScanData, cfg: ScanConfig
) -> tuple[np.ndarray, np.ndarray]:
    drawdown = drawdown_array(data, 4)
    if not cfg.include_candidate_warnings:
        return np.zeros(data.length, dtype=bool), drawdown

    mask = (
        lag_bool(data.small_yin, 3)
        & lag_bool(data.small_yin, 2)
        & shrink_mask(data, 2, 3, cfg)
        & lag_bool(data.yang, 1)
        & expand_from_base_mask(data, 1, 2, 4, cfg)
        & data.small_yin
        & last_yin_shrink_mask(data, cfg)
        & (drawdown <= cfg.max_drawdown_pct)
    )
    mask &= common_pattern_filters(
        data,
        cfg,
        start_lag=3,
        yang_lag=1,
        support_lags=(3, 2, 0),
        require_near_low_vol=False,
    )
    return mask, drawdown


def match_candidate_pattern_b_vectorized(
    data: VectorScanData, cfg: ScanConfig
) -> tuple[np.ndarray, np.ndarray]:
    drawdown = drawdown_array(data, 5)
    if not cfg.include_candidate_warnings:
        return np.zeros(data.length, dtype=bool), drawdown

    mask = (
        lag_bool(data.small_yin, 4)
        & lag_bool(data.small_yin, 3)
        & shrink_mask(data, 3, 4, cfg)
        & lag_bool(data.yang, 2)
        & expand_from_base_mask(data, 2, 3, 5, cfg)
        & lag_bool(data.yang, 1)
        & shrink_mask(data, 1, 2, cfg)
        & data.small_yin
        & last_yin_shrink_mask(data, cfg)
        & (drawdown <= cfg.max_drawdown_pct)
    )
    mask &= common_pattern_filters(
        data,
        cfg,
        start_lag=4,
        yang_lag=2,
        support_lags=(4, 3, 0),
        require_near_low_vol=False,
    )
    return mask, drawdown


def strong_context_mask(data: VectorScanData, cfg: ScanConfig) -> np.ndarray:
    context = data.trend_rise >= cfg.trend_min_rise_pct
    if cfg.require_ma_bullish:
        context &= data.ma_bullish
    return context


def low_reversal_context_mask(data: VectorScanData, cfg: ScanConfig) -> np.ndarray:
    context = data.trend_rise < cfg.low_reversal_max_rise_pct
    # 位置条件：现价处于区间下沿，排除高位/半山腰的"洗盘"（多为出货）
    if cfg.low_reversal_require_low_position:
        pos = low_position_array(
            data.close, data.high, data.low, cfg.low_reversal_position_lookback
        )
        context &= pos <= cfg.low_reversal_position_max_pct
    # 企稳条件：MA5 走平或上拐，排除单边阴跌中继
    if cfg.low_reversal_require_stabilize:
        context &= ma5_stabilize_array(data.close)
    return context


def breakout_base_context_mask(data: VectorScanData, cfg: ScanConfig) -> np.ndarray:
    """突破前蓄势上下文：上涨初段（涨幅在区间内）+ 临近突破（区间中上沿）+ MA5 企稳。"""
    context = (
        (data.trend_rise >= cfg.breakout_base_min_rise_pct)
        & (data.trend_rise <= cfg.breakout_base_max_rise_pct)
    )
    # 位置条件：收盘处于近 lookback 区间的中上沿，排除半山腰/高位的假蓄势
    if cfg.breakout_base_position_lookback > 0:
        pos = low_position_array(
            data.close, data.high, data.low, cfg.breakout_base_position_lookback
        )
        context &= pos >= cfg.breakout_base_position_min_pct
    # 企稳条件：MA5 走平或上拐
    if cfg.breakout_base_require_stabilize:
        context &= ma5_stabilize_array(data.close)
    return context


def vectorized_mode_hits(
    data: VectorScanData,
    cfg: ScanConfig,
    mode: str,
    valid_end: np.ndarray,
) -> tuple[object, ...]:
    if mode == "strong":
        mode_cfg = cfg
        context = strong_context_mask(data, cfg)
    elif mode == "low_reversal":
        mode_cfg = low_reversal_config(cfg)
        context = low_reversal_context_mask(data, cfg)
    elif mode == "breakout_base":
        mode_cfg = breakout_base_config(cfg)
        context = breakout_base_context_mask(data, cfg)
    else:
        raise ValueError(f"Unknown scan mode: {mode}")

    pattern_a, drawdown_a = match_pattern_a_vectorized(data, mode_cfg)
    pattern_b, drawdown_b = match_pattern_b_vectorized(data, mode_cfg)
    pattern_c, drawdown_c = match_pattern_c_vectorized(data, mode_cfg)
    candidate_a, candidate_drawdown_a = match_candidate_pattern_a_vectorized(data, mode_cfg)
    candidate_b, candidate_drawdown_b = match_candidate_pattern_b_vectorized(data, mode_cfg)

    base = valid_end & context
    confirmed_a = base & pattern_a & data.confirm_yang
    confirmed_b = base & ~pattern_a & pattern_b & data.confirm_yang
    confirmed_c = base & ~pattern_a & ~pattern_b & pattern_c & data.confirm_yang
    confirmed = confirmed_a | confirmed_b | confirmed_c
    warning_a = base & ~confirmed & candidate_a
    warning_b = base & ~confirmed & ~candidate_a & candidate_b

    return (
        mode,
        confirmed_a,
        drawdown_a,
        confirmed_b,
        drawdown_b,
        confirmed_c,
        drawdown_c,
        warning_a,
        candidate_drawdown_a,
        warning_b,
        candidate_drawdown_b,
    )


def match_confirmed_patterns(
    df: pd.DataFrame, end_index: int, cfg: ScanConfig
) -> PatternHit | None:
    hit = match_pattern_a(df, end_index, cfg)
    if hit is None:
        hit = match_pattern_b(df, end_index, cfg)
    if hit is None:
        hit = match_pattern_c(df, end_index, cfg)
    if hit is not None and has_confirmation(df, end_index, cfg.confirm_yang):
        return hit
    return None


def match_candidate_patterns(
    df: pd.DataFrame, end_index: int, cfg: ScanConfig
) -> PatternHit | None:
    if not cfg.include_candidate_warnings:
        return None
    hit = match_candidate_pattern_a(df, end_index, cfg)
    if hit is None:
        hit = match_candidate_pattern_b(df, end_index, cfg)
    return hit


def detect_strong_trend_wash(
    df: pd.DataFrame, end_index: int, cfg: ScanConfig
) -> PatternHit | None:
    if not strong_trend_context_ok(df, end_index, cfg):
        return None
    hit = match_confirmed_patterns(df, end_index, cfg)
    if hit is None:
        hit = match_candidate_patterns(df, end_index, cfg)
    return with_mode(hit, "strong") if hit is not None else None


def detect_low_reversal_wash(
    df: pd.DataFrame, end_index: int, cfg: ScanConfig
) -> PatternHit | None:
    if not low_reversal_context_ok(df, end_index, cfg):
        return None
    mode_cfg = low_reversal_config(cfg)
    hit = match_confirmed_patterns(df, end_index, mode_cfg)
    if hit is None:
        hit = match_candidate_patterns(df, end_index, mode_cfg)
    return with_mode(hit, "low_reversal") if hit is not None else None


def detect_wash_pattern(df: pd.DataFrame, cfg: ScanConfig) -> list[PatternHit]:
    """Return all matching wash-pattern positions in a normalized daily dataframe."""
    results: list[PatternHit] = []
    min_end = max(10, cfg.trend_rise_days)
    if len(df) <= min_end:
        return results

    data = build_vector_scan_data(df, cfg)
    valid_end = (data.index >= min_end) & (data.index < len(df) - cfg.confirm_yang)
    mode_hits = [
        vectorized_mode_hits(data, cfg, mode, valid_end)
        for mode in enabled_scan_modes(cfg)
    ]

    hit_indices = np.zeros(data.length, dtype=bool)
    for (
        _mode,
        confirmed_a,
        _drawdown_a,
        confirmed_b,
        _drawdown_b,
        confirmed_c,
        _drawdown_c,
        warning_a,
        _candidate_drawdown_a,
        warning_b,
        _candidate_drawdown_b,
    ) in mode_hits:
        hit_indices |= confirmed_a | confirmed_b | confirmed_c | warning_a | warning_b

    for end_index in np.flatnonzero(hit_indices):
        for (
            mode,
            confirmed_a,
            drawdown_a,
            confirmed_b,
            drawdown_b,
            confirmed_c,
            drawdown_c,
            warning_a,
            candidate_drawdown_a,
            warning_b,
            candidate_drawdown_b,
        ) in mode_hits:
            if confirmed_a[end_index]:
                results.append(
                    PatternHit(
                        end_index=int(end_index),
                        start_index=int(end_index - 4),
                        pattern_type="A:阴阴阳阴阴",
                        drawdown_pct=round(float(drawdown_a[end_index]), 2),
                        scan_mode=mode_label(mode),
                    )
                )
            elif confirmed_b[end_index]:
                results.append(
                    PatternHit(
                        end_index=int(end_index),
                        start_index=int(end_index - 5),
                        pattern_type="B:阴阴阳阳阴阴",
                        drawdown_pct=round(float(drawdown_b[end_index]), 2),
                        scan_mode=mode_label(mode),
                    )
                )
            elif confirmed_c[end_index]:
                results.append(
                    PatternHit(
                        end_index=int(end_index),
                        start_index=int(end_index - 5),
                        pattern_type="C:试盘回落洗盘",
                        drawdown_pct=round(float(drawdown_c[end_index]), 2),
                        scan_mode=mode_label(mode),
                    )
                )
            elif warning_a[end_index]:
                results.append(
                    PatternHit(
                        end_index=int(end_index),
                        start_index=int(end_index - 3),
                        pattern_type="A预警:阴阴阳阴",
                        drawdown_pct=round(float(candidate_drawdown_a[end_index]), 2),
                        status="候选预警",
                        note="缺最后一根缩量阴确认",
                        scan_mode=mode_label(mode),
                    )
                )
            elif warning_b[end_index]:
                results.append(
                    PatternHit(
                        end_index=int(end_index),
                        start_index=int(end_index - 4),
                        pattern_type="B预警:阴阴阳阳阴",
                        drawdown_pct=round(float(candidate_drawdown_b[end_index]), 2),
                        status="候选预警",
                        note="缺最后一根缩量阴确认",
                        scan_mode=mode_label(mode),
                    )
                )

    return results


def match_pattern_a(
    df: pd.DataFrame, end_index: int, cfg: ScanConfig
) -> PatternHit | None:
    """A: 缩量阴 + 缩量阴 + 放量阳（反弹） + 缩量阴 + 缩量阴."""
    if end_index < 5:
        return None

    chunk = df.iloc[end_index - 5 : end_index + 1]
    # ref_vol: 洗盘前一根K线的量，作为初始缩量基准
    ref_vol = float(chunk.iloc[0]["volume"])
    r1, r2, r3, r4, r5 = (chunk.iloc[pos] for pos in range(1, 6))

    # 阳线放量基准取「紧邻前阴量」与「洗盘前参考量」中的较大值
    # 确保反弹阳线相对整个洗盘区间也是明显放量
    yang_vol_base = max(float(r2["volume"]), ref_vol * 0.6)

    matched = (
        # 前两根阴线：首阴允许放量分歧，第二阴必须缩量
        is_yin(r1)
        and is_small_body_yin(r1, cfg.yin_max_body_pct)
        and is_yin(r2)
        and is_small_body_yin(r2, cfg.yin_max_body_pct)
        and shrink_vol(float(r2["volume"]), float(r1["volume"]), cfg.shrink_ratio)
        # 中间放量阳线：明显放量，主力护盘反弹
        and is_yang(r3)
        and expand_vol(float(r3["volume"]), yang_vol_base, cfg.yang_vol_ratio)
        # 后两根阴线：小实体 + 再次缩量
        and is_yin(r4)
        and is_small_body_yin(r4, cfg.yin_max_body_pct)
        and shrink_vol(float(r4["volume"]), float(r3["volume"]), cfg.shrink_ratio)
        and is_yin(r5)
        and is_small_body_yin(r5, cfg.yin_max_body_pct)
        and shrink_vol(float(r5["volume"]), float(r4["volume"]), cfg.shrink_ratio)
    )
    if not matched:
        return None

    pattern_window = chunk.iloc[1:]
    drawdown = calc_drawdown(pattern_window)
    if drawdown > cfg.max_drawdown_pct:
        return None

    pat_start = end_index - 4
    if cfg.require_ma_support and not check_ma_support([r1, r2, r4, r5]):
        return None
    if cfg.require_no_step_down and not check_no_step_down(r1, r5):
        return None
    if cfg.require_no_new_high and not check_no_new_high(
        df, r3, pat_start, cfg.no_new_high_lookback
    ):
        return None
    if cfg.require_near_low_vol and not check_near_low_vol(
        df, end_index, float(r5["volume"]),
        cfg.near_low_vol_lookback, cfg.near_low_vol_ratio
    ):
        return None
    if cfg.require_impulse and not check_impulse_before(
        df, pat_start, cfg.min_impulse_pct, cfg.impulse_lookback
    ):
        return None

    return PatternHit(
        end_index=end_index,
        start_index=pat_start,
        pattern_type="A:阴阴阳阴阴",
        drawdown_pct=round(drawdown, 2),
    )


def match_pattern_b(
    df: pd.DataFrame, end_index: int, cfg: ScanConfig
) -> PatternHit | None:
    """B: 缩量阴 + 缩量阴 + 放量阳 + 缩量阳（主力温和再拉） + 缩量阴 + 缩量阴."""
    if end_index < 6:
        return None

    chunk = df.iloc[end_index - 6 : end_index + 1]
    ref_vol = float(chunk.iloc[0]["volume"])
    r1, r2, r3, r4, r5, r6 = (chunk.iloc[pos] for pos in range(1, 7))

    # 阳线放量基准：同 Pattern A
    yang_vol_base = max(float(r2["volume"]), ref_vol * 0.6)

    matched = (
        # 前两根阴线：首阴允许放量分歧，第二阴必须缩量
        is_yin(r1)
        and is_small_body_yin(r1, cfg.yin_max_body_pct)
        and is_yin(r2)
        and is_small_body_yin(r2, cfg.yin_max_body_pct)
        and shrink_vol(float(r2["volume"]), float(r1["volume"]), cfg.shrink_ratio)
        # 第一根阳线：明显放量（主力拉高）
        and is_yang(r3)
        and expand_vol(float(r3["volume"]), yang_vol_base, cfg.yang_vol_ratio)
        # 第二根阳线：须缩量（排除连续放量拉升，与二次拉升混淆）
        and is_yang(r4)
        and shrink_vol(float(r4["volume"]), float(r3["volume"]), cfg.shrink_ratio)
        # 后两根阴线：小实体 + 再次缩量
        and is_yin(r5)
        and is_small_body_yin(r5, cfg.yin_max_body_pct)
        and shrink_vol(float(r5["volume"]), float(r4["volume"]), cfg.shrink_ratio)
        and is_yin(r6)
        and is_small_body_yin(r6, cfg.yin_max_body_pct)
        and shrink_vol(float(r6["volume"]), float(r5["volume"]), cfg.shrink_ratio)
    )
    if not matched:
        return None

    pattern_window = chunk.iloc[1:]
    drawdown = calc_drawdown(pattern_window)
    if drawdown > cfg.max_drawdown_pct:
        return None

    pat_start = end_index - 5
    if cfg.require_ma_support and not check_ma_support([r1, r2, r5, r6]):
        return None
    if cfg.require_no_step_down and not check_no_step_down(r1, r6):
        return None
    if cfg.require_no_new_high and not check_no_new_high(
        df, r3, pat_start, cfg.no_new_high_lookback
    ):
        return None
    if cfg.require_near_low_vol and not check_near_low_vol(
        df, end_index, float(r6["volume"]),
        cfg.near_low_vol_lookback, cfg.near_low_vol_ratio
    ):
        return None
    if cfg.require_impulse and not check_impulse_before(
        df, pat_start, cfg.min_impulse_pct, cfg.impulse_lookback
    ):
        return None

    return PatternHit(
        end_index=end_index,
        start_index=pat_start,
        pattern_type="B:阴阴阳阳阴阴",
        drawdown_pct=round(drawdown, 2),
    )


def match_pattern_c(
    df: pd.DataFrame, end_index: int, cfg: ScanConfig
) -> PatternHit | None:
    """C: 阴阴 + 放量试盘阳 + 高开回落换手阴 + 缩量阴阴."""
    if end_index < 6:
        return None

    chunk = df.iloc[end_index - 6 : end_index + 1]
    ref_vol = float(chunk.iloc[0]["volume"])
    r1, r2, r3, r4, r5, r6 = (chunk.iloc[pos] for pos in range(1, 7))
    yang_vol_base = max(float(r2["volume"]), ref_vol * 0.6)

    r4_open = float(r4["open"])
    r4_close = float(r4["close"])
    if r4_open <= 0:
        return None
    shakeout_body_pct = (r4_open - r4_close) / r4_open * 100

    matched = (
        is_yin(r1)
        and is_small_body_yin(r1, cfg.yin_max_body_pct)
        and is_yin(r2)
        and is_small_body_yin(r2, cfg.yin_max_body_pct)
        and float(r2["volume"]) <= float(r1["volume"]) * cfg.c_front_vol_ratio
        and is_yang(r3)
        and expand_vol(float(r3["volume"]), yang_vol_base, cfg.c_yang_vol_ratio)
        and is_yin(r4)
        and r4_open > float(r3["close"])
        and float(r4["high"]) >= float(r3["high"])
        and shakeout_body_pct <= cfg.c_shakeout_body_pct
        and float(r4["volume"]) >= float(r3["volume"]) * cfg.c_shakeout_min_vol_ratio
        and is_yin(r5)
        and is_small_body_yin(r5, cfg.yin_max_body_pct)
        and float(r5["volume"]) <= float(r4["volume"]) * cfg.c_tail_vol_ratio
        and is_yin(r6)
        and is_small_body_yin(r6, cfg.yin_max_body_pct)
        and float(r6["volume"]) <= float(r5["volume"]) * cfg.c_tail_flat_ratio
    )
    if not matched:
        return None

    pattern_window = chunk.iloc[1:]
    drawdown = calc_drawdown(pattern_window)
    if drawdown > cfg.max_drawdown_pct:
        return None

    pat_start = end_index - 5
    if cfg.require_ma_support and not check_ma_support([r1, r2, r4, r5, r6]):
        return None
    if cfg.require_no_step_down and not check_no_step_down(r1, r6):
        return None
    if cfg.require_impulse and not check_impulse_before(
        df, pat_start, cfg.min_impulse_pct, cfg.impulse_lookback
    ):
        return None

    return PatternHit(
        end_index=end_index,
        start_index=pat_start,
        pattern_type="C:试盘回落洗盘",
        drawdown_pct=round(drawdown, 2),
    )


def match_candidate_pattern_a(
    df: pd.DataFrame, end_index: int, cfg: ScanConfig
) -> PatternHit | None:
    """A预警: 缩量阴 + 缩量阴 + 放量阳 + 缩量阴，缺最后一根确认阴线."""
    if end_index < 4:
        return None

    chunk = df.iloc[end_index - 4 : end_index + 1]
    ref_vol = float(chunk.iloc[0]["volume"])
    r1, r2, r3, r4 = (chunk.iloc[pos] for pos in range(1, 5))
    yang_vol_base = max(float(r2["volume"]), ref_vol * 0.6)

    matched = (
        is_yin(r1)
        and is_small_body_yin(r1, cfg.yin_max_body_pct)
        and is_yin(r2)
        and is_small_body_yin(r2, cfg.yin_max_body_pct)
        and shrink_vol(float(r2["volume"]), float(r1["volume"]), cfg.shrink_ratio)
        and is_yang(r3)
        and expand_vol(float(r3["volume"]), yang_vol_base, cfg.yang_vol_ratio)
        and is_yin(r4)
        and is_small_body_yin(r4, cfg.yin_max_body_pct)
        and shrink_vol(float(r4["volume"]), float(r3["volume"]), cfg.shrink_ratio)
    )
    if not matched:
        return None

    pattern_window = chunk.iloc[1:]
    drawdown = calc_drawdown(pattern_window)
    if drawdown > cfg.max_drawdown_pct:
        return None

    pat_start = end_index - 3
    if cfg.require_ma_support and not check_ma_support([r1, r2, r4]):
        return None
    if cfg.require_no_step_down and not check_no_step_down(r1, r4):
        return None
    if cfg.require_no_new_high and not check_no_new_high(
        df, r3, pat_start, cfg.no_new_high_lookback
    ):
        return None
    if cfg.require_impulse and not check_impulse_before(
        df, pat_start, cfg.min_impulse_pct, cfg.impulse_lookback
    ):
        return None

    return PatternHit(
        end_index=end_index,
        start_index=pat_start,
        pattern_type="A预警:阴阴阳阴",
        drawdown_pct=round(drawdown, 2),
        status="候选预警",
        note="缺最后一根缩量阴确认",
    )


def match_candidate_pattern_b(
    df: pd.DataFrame, end_index: int, cfg: ScanConfig
) -> PatternHit | None:
    """B预警: 缩量阴 + 缩量阴 + 放量阳 + 缩量阳 + 缩量阴，缺最后一根确认阴线."""
    if end_index < 5:
        return None

    chunk = df.iloc[end_index - 5 : end_index + 1]
    ref_vol = float(chunk.iloc[0]["volume"])
    r1, r2, r3, r4, r5 = (chunk.iloc[pos] for pos in range(1, 6))
    yang_vol_base = max(float(r2["volume"]), ref_vol * 0.6)

    matched = (
        is_yin(r1)
        and is_small_body_yin(r1, cfg.yin_max_body_pct)
        and is_yin(r2)
        and is_small_body_yin(r2, cfg.yin_max_body_pct)
        and shrink_vol(float(r2["volume"]), float(r1["volume"]), cfg.shrink_ratio)
        and is_yang(r3)
        and expand_vol(float(r3["volume"]), yang_vol_base, cfg.yang_vol_ratio)
        and is_yang(r4)
        and shrink_vol(float(r4["volume"]), float(r3["volume"]), cfg.shrink_ratio)
        and is_yin(r5)
        and is_small_body_yin(r5, cfg.yin_max_body_pct)
        and shrink_vol(float(r5["volume"]), float(r4["volume"]), cfg.shrink_ratio)
    )
    if not matched:
        return None

    pattern_window = chunk.iloc[1:]
    drawdown = calc_drawdown(pattern_window)
    if drawdown > cfg.max_drawdown_pct:
        return None

    pat_start = end_index - 4
    if cfg.require_ma_support and not check_ma_support([r1, r2, r5]):
        return None
    if cfg.require_no_step_down and not check_no_step_down(r1, r5):
        return None
    if cfg.require_no_new_high and not check_no_new_high(
        df, r3, pat_start, cfg.no_new_high_lookback
    ):
        return None
    if cfg.require_impulse and not check_impulse_before(
        df, pat_start, cfg.min_impulse_pct, cfg.impulse_lookback
    ):
        return None

    return PatternHit(
        end_index=end_index,
        start_index=pat_start,
        pattern_type="B预警:阴阴阳阳阴",
        drawdown_pct=round(drawdown, 2),
        status="候选预警",
        note="缺最后一根缩量阴确认",
    )


def normalize_stock_code(code: object) -> str:
    return str(code).strip().split(".")[0].zfill(6)


def candidate_cache_dirs() -> list[Path]:
    candidates = [
        Path.cwd() / "cache",
        Path(__file__).resolve().with_name("cache"),
        Path.home() / "Desktop" / "code" / "code" / "irontrader3" / "cache",
    ]
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


@contextmanager
def without_proxy_env():
    saved = {key: os.environ.get(key) for key in PROXY_ENV_KEYS}
    for key in PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def load_stock_pool_raw(pool_name: str) -> tuple[pd.DataFrame, str, str]:
    if pool_name == "hs300":
        return ak.index_stock_cons_weight_csindex(symbol="000300"), "成分券代码", "成分券名称"
    if pool_name == "zz500":
        return ak.index_stock_cons_weight_csindex(symbol="000905"), "成分券代码", "成分券名称"
    if pool_name == "all_a":
        try:
            return ak.stock_info_a_code_name(), "code", "name"
        except Exception:
            return ak.stock_zh_a_spot_em(), "代码", "名称"
    raise ValueError(f"Unknown stock pool: {pool_name}")


def stock_pool_from_cache() -> list[StockInfo]:
    codes: set[str] = set()
    for cache_dir in candidate_cache_dirs():
        if not cache_dir.exists():
            continue
        for path in cache_dir.glob("*_stock_*_*.pkl"):
            parts = path.stem.split("_")
            if len(parts) < 4:
                continue
            code = normalize_stock_code(parts[-2])
            if code.isdigit() and len(code) == 6:
                codes.add(code)

    return [StockInfo(code=code) for code in sorted(codes)]


def stock_pool_cache_files(source: str, pool_name: str) -> list[Path]:
    return [
        cache_dir / f"{source}_{pool_name}_stock_pool.csv"
        for cache_dir in candidate_cache_dirs()
    ]


def read_stock_pool_cache(
    source: str,
    pool_name: str,
    max_age_days: int = 30,
    require_today: bool = True,
) -> list[StockInfo]:
    for path in stock_pool_cache_files(source, pool_name):
        if not path.exists():
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime)
        age_seconds = time.time() - modified_at.timestamp()
        if age_seconds > max_age_days * 86400:
            continue
        if require_today and modified_at.date() != current_local_datetime().date():
            continue
        df = pd.read_csv(path, dtype={"code": str, "name": str})
        if "code" not in df.columns:
            continue
        names = df["name"] if "name" in df.columns else pd.Series("", index=df.index)
        stocks = [
            StockInfo(code=normalize_stock_code(code), name="" if pd.isna(name) else str(name))
            for code, name in zip(df["code"], names)
        ]
        result = [
            stock
            for stock in stocks
            if stock.code.isdigit() and len(stock.code) == 6
        ]
        if result:
            return result
    return []


def write_stock_pool_cache(source: str, pool_name: str, stocks: list[StockInfo]) -> None:
    if not stocks:
        return
    frame = pd.DataFrame(
        [{"code": stock.code, "name": stock.name} for stock in stocks]
    )
    for path in stock_pool_cache_files(source, pool_name):
        temp_path = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(temp_path, index=False, encoding="utf-8-sig")
            os.replace(temp_path, path)
        except Exception:
            continue
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def sina_symbol_batches() -> Iterable[list[str]]:
    ranges = [
        ("sh", 600000, 605999),
        ("sh", 688000, 689999),
        ("sz", 0, 3999),
        ("sz", 300000, 301999),
        ("bj", 830000, 839999),
        ("bj", 870000, 879999),
        ("bj", 920000, 929999),
    ]
    batch_size = 500
    for prefix, start, end in ranges:
        batch: list[str] = []
        for code in range(start, end + 1):
            batch.append(f"{prefix}{code:06d}")
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch


def is_active_sina_quote(symbol: str, parts: list[str], as_of: datetime) -> bool:
    if not parts or not parts[0]:
        return False
    if len(parts) < 33 or parts[32] == "-3":
        return False
    if symbol.startswith(("sh", "sz")) and parts[32] != "00":
        return False
    if symbol.startswith("bj") and len(parts) > 38 and parts[38] != "T":
        return False
    try:
        quote_date = datetime.strptime(parts[30], "%Y-%m-%d")
    except Exception:
        return False
    return (as_of - quote_date).days <= 14


def stock_pool_from_sina_quote(pool_name: str) -> list[StockInfo]:
    if pool_name != "all_a":
        raise ValueError("新浪批量行情股票池接口仅支持 all_a")

    cached = read_stock_pool_cache("sina_quote", pool_name)
    if cached:
        return cached
    stale_cache = read_stock_pool_cache(
        "sina_quote", pool_name, max_age_days=30, require_today=False
    )

    session = get_http_session()
    headers = {"Referer": "http://finance.sina.com.cn"}
    as_of = datetime.today()
    stocks: list[StockInfo] = []
    for batch in sina_symbol_batches():
        url = "http://hq.sinajs.cn/list=" + ",".join(batch)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = session.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                response.encoding = "gbk"
                break
            except Exception as exc:
                last_error = exc
                time.sleep(0.5 + attempt)
        else:
            if stale_cache:
                progress_write(
                    "新浪股票池刷新失败，已回退最近一次本地股票池："
                    f"{len(stale_cache)} 只。错误：{brief_error(last_error)}"
                )
                return stale_cache
            raise last_error or RuntimeError("新浪批量行情接口拉取失败")

        for symbol, data in re.findall(r'var hq_str_([^=]+)="([^"]*)";', response.text):
            parts = data.split(",")
            if not is_active_sina_quote(symbol, parts, as_of):
                continue
            code = normalize_stock_code(symbol[2:])
            if code.isdigit() and len(code) == 6:
                stocks.append(StockInfo(code=code, name=parts[0].strip()))
        time.sleep(0.05)

    deduped: dict[str, StockInfo] = {}
    for stock in stocks:
        deduped.setdefault(stock.code, stock)
    result = list(deduped.values())
    if not result and stale_cache:
        progress_write(
            f"新浪股票池返回空列表，已回退最近一次本地股票池：{len(stale_cache)} 只"
        )
        return stale_cache
    write_stock_pool_cache("sina_quote", pool_name, result)
    return result


def stock_pool_from_sina(pool_name: str) -> list[StockInfo]:
    return stock_pool_from_sina_quote(pool_name)


def stock_pool_from_yahoo(pool_name: str) -> list[StockInfo]:
    raise ValueError("Yahoo 没有稳定免登录的 A 股全市场股票池接口，请使用 sina")


def stock_infos_from_raw(raw: pd.DataFrame, code_col: str, name_col: str) -> list[StockInfo]:
    if code_col not in raw.columns:
        raise ValueError(f"AKShare response does not include code column: {code_col}")

    codes = (
        raw[code_col]
        .astype(str)
        .str.strip()
        .str.partition(".")[0]
        .str.zfill(6)
    )
    if name_col in raw.columns:
        names = raw[name_col].astype(str).str.strip()
    else:
        names = pd.Series("", index=raw.index)

    pool = pd.DataFrame({"code": codes, "name": names})
    pool = pool[pool["code"].astype(bool)]
    return [
        StockInfo(code=code, name=name)
        for code, name in pool[["code", "name"]].itertuples(index=False, name=None)
    ]


def get_stock_pool(pool_name: str, pool_source: str = "auto") -> list[StockInfo]:
    errors: list[str] = []
    sources: tuple[str, ...]
    if pool_source == "auto":
        sources = ("sina", "akshare", "cache")
    else:
        sources = (pool_source,)

    for source in sources:
        try:
            if source == "sina":
                return stock_pool_from_sina(pool_name)
            if source == "yahoo":
                return stock_pool_from_yahoo(pool_name)
            if source == "akshare":
                for use_proxy in (True, False):
                    try:
                        if use_proxy:
                            raw, code_col, name_col = load_stock_pool_raw(pool_name)
                        else:
                            with without_proxy_env():
                                raw, code_col, name_col = load_stock_pool_raw(pool_name)
                        return stock_infos_from_raw(raw, code_col, name_col)
                    except Exception as exc:
                        label = "akshare/proxy" if use_proxy else "akshare/direct"
                        errors.append(f"{label}: {brief_error(exc)}")
                continue
            if source == "cache":
                stocks = stock_pool_from_cache()
                if stocks:
                    progress_write(
                        "在线股票池拉取失败，已改用本地 cache 中的股票代码："
                        f"{len(stocks)} 只。错误：{'; '.join(errors)}"
                    )
                    return stocks
                raise ValueError("cache 中没有可用股票代码")
            raise ValueError(f"Unknown pool source: {source}")
        except Exception as exc:
            errors.append(f"{source}: {brief_error(exc)}")

    raise RuntimeError(f"获取股票池失败：{'; '.join(errors)}")


def normalize_daily_columns(
    df: pd.DataFrame,
    volume_multiplier: float = 1.0,
) -> pd.DataFrame:
    columns = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "涨跌幅": "pct_chg",
    }
    normalized = df.rename(columns=columns).copy()
    required = ["date", "open", "close", "high", "low", "volume"]
    missing = [column for column in required if column not in normalized.columns]
    if missing:
        raise ValueError(f"Daily data missing required columns: {missing}")

    normalized["date"] = pd.to_datetime(normalized["date"])
    for column in ("open", "close", "high", "low", "volume"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized["volume"] = normalized["volume"] * float(volume_multiplier)

    normalized = normalized.dropna(subset=required)
    normalized = normalized.sort_values("date").reset_index(drop=True)
    return add_ma(normalized)


def fetch_daily_akshare(code: str, cfg: ScanConfig) -> pd.DataFrame | None:
    as_of = parse_as_of_date(cfg)
    end_date = as_of.strftime("%Y%m%d")
    start_date = (as_of - timedelta(days=cfg.fetch_days + 80)).strftime(
        "%Y%m%d"
    )
    raw = ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=cfg.adjust,
    )
    if raw is None or raw.empty:
        return None
    # Eastmoney reports 成交量 in lots (手); the shared cache contract is shares.
    return normalize_daily_columns(raw, volume_multiplier=100.0)


def sina_daily_symbol(code: str) -> str:
    """Format an A-share code for AKShare's Sina history endpoint."""
    code = normalize_stock_code(code)
    if code.startswith(("4", "8", "9")):
        return f"bj{code}"
    if code.startswith(("5", "6")):
        return f"sh{code}"
    return f"sz{code}"


def fetch_daily_sina(code: str, cfg: ScanConfig) -> pd.DataFrame | None:
    """Fetch daily history from Sina, independently of Eastmoney/Yahoo."""
    as_of = parse_as_of_date(cfg)
    end_date = as_of.strftime("%Y%m%d")
    start_date = (as_of - timedelta(days=cfg.fetch_days + 80)).strftime(
        "%Y%m%d"
    )
    raw = ak.stock_zh_a_daily(
        symbol=sina_daily_symbol(code),
        start_date=start_date,
        end_date=end_date,
        adjust=cfg.adjust,
    )
    if raw is None or raw.empty:
        return None
    return normalize_daily_columns(raw)


def yahoo_symbol(code: str) -> str:
    if code.startswith(("4", "8", "9")):
        return f"{code}.BJ"
    if code.startswith(("5", "6")):
        return f"{code}.SS"
    return f"{code}.SZ"


def get_http_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.trust_env = False
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        _THREAD_LOCAL.session = session
    return session


def fetch_daily_yahoo(code: str, cfg: ScanConfig) -> pd.DataFrame | None:
    as_of = parse_as_of_date(cfg)
    end_dt = as_of + timedelta(days=1)
    start_dt = as_of - timedelta(days=cfg.fetch_days + 80)
    params = {
        "period1": int(start_dt.timestamp()),
        "period2": int(end_dt.timestamp()),
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol(code)}"
    response = get_http_session().get(
        url,
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    result = payload.get("chart", {}).get("result") or []
    if not result:
        return None

    chart = result[0]
    timestamps = chart.get("timestamp") or []
    indicators = chart.get("indicators", {})
    quote = (indicators.get("quote") or [{}])[0]
    adjclose = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []

    rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(timestamps):
        close = value_at(quote, "close", index)
        if close is None:
            continue

        open_price = value_at(quote, "open", index)
        high = value_at(quote, "high", index)
        low = value_at(quote, "low", index)
        volume = value_at(quote, "volume", index) or 0
        if open_price is None or high is None or low is None:
            continue

        adjusted_close = adjclose[index] if index < len(adjclose) else None
        if cfg.adjust and adjusted_close and close:
            factor = adjusted_close / close
            open_price *= factor
            high *= factor
            low *= factor
            close = adjusted_close

        rows.append(
            {
                "date": datetime.fromtimestamp(timestamp).date(),
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
            }
        )

    if not rows:
        return None

    daily = pd.DataFrame(rows)
    daily["date"] = pd.to_datetime(daily["date"])
    daily["pct_chg"] = daily["close"].pct_change() * 100
    daily = daily.sort_values("date").reset_index(drop=True)
    return add_ma(daily)


def wash_ohlcv_cache_dir() -> Path:
    """洗盘扫描专用的 OHLCV 持久缓存目录。"""
    d = Path(__file__).resolve().with_name("cache") / "wash_ohlcv"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Same-session history is stable after the close, but an intraday daily bar is
# still moving.  Keep the old four-hour reuse window only outside market hours
# and refresh a live bar every five minutes while the market is open.
WASH_OHLCV_TTL_SEC = 4 * 60 * 60
WASH_OHLCV_INTRADAY_TTL_SEC = 5 * 60
MARKET_DATA_OPEN_MINUTE = 9 * 60 + 15
MARKET_CLOSE_MINUTE = 15 * 60
SINA_QUOTE_BATCH_SIZE = 500
SINA_QUOTE_BATCH_WORKERS = 4
_VALIDATED_WASH_CACHE: dict[tuple[str, str, str], float] = {}
_VALIDATED_WASH_CACHE_LOCK = threading.Lock()
_TRADE_CALENDAR_DATES: list[date] = []
_TRADE_CALENDAR_LOCK = threading.Lock()


def _minute_of_day(value: datetime) -> int:
    return value.hour * 60 + value.minute


def current_local_datetime() -> datetime:
    """Single clock hook used by cache freshness checks and deterministic tests."""
    return datetime.now()


def is_a_share_intraday(value: datetime) -> bool:
    """Whether a current-date cache contains a still-changing daily bar."""
    minute = _minute_of_day(value)
    return (
        value.weekday() < 5
        and MARKET_DATA_OPEN_MINUTE <= minute < MARKET_CLOSE_MINUTE
    )


def wash_cache_ttl_seconds(cfg: ScanConfig, now: datetime | None = None) -> int:
    """Return a dynamic cache TTL for historical, intraday and closed bars."""
    current = now or current_local_datetime()
    if not cfg.as_of_date and is_a_share_intraday(current):
        return WASH_OHLCV_INTRADAY_TTL_SEC
    return WASH_OHLCV_TTL_SEC


def wash_cache_payload_is_fresh(
    payload: dict[str, object],
    cfg: ScanConfig,
    now: datetime | None = None,
    code: str | None = None,
) -> bool:
    """Validate wall-clock freshness without reusing a pre-close bar at close."""
    current = now or current_local_datetime()
    saved_candidates = [payload.get("saved_at", 0)]
    if code:
        key = (
            normalize_stock_code(code),
            cfg.adjust,
            parse_as_of_date(cfg).strftime("%Y-%m-%d"),
        )
        with _VALIDATED_WASH_CACHE_LOCK:
            validated_at = _VALIDATED_WASH_CACHE.get(key)
        if validated_at:
            saved_candidates.insert(0, validated_at)

    for raw_saved_at in saved_candidates:
        try:
            saved_at = float(raw_saved_at)
            saved = datetime.fromtimestamp(saved_at)
        except (TypeError, ValueError, OSError):
            continue

        age_seconds = current.timestamp() - saved_at
        if age_seconds < -60 or age_seconds > wash_cache_ttl_seconds(cfg, current):
            continue

        # A bar cached/validated before 15:00 is provisional.  Once the market
        # has closed it must be refreshed even inside the after-close TTL.
        if (
            not cfg.as_of_date
            and current.weekday() < 5
            and current.date() == saved.date()
            and _minute_of_day(current) >= MARKET_CLOSE_MINUTE
            and _minute_of_day(saved) < MARKET_CLOSE_MINUTE
        ):
            continue
        return True
    return False


def mark_wash_cache_validated(
    code: str,
    cfg: ScanConfig,
    now: datetime | None = None,
) -> None:
    """Remember that a live quote just confirmed an unchanged cached bar."""
    current = now or current_local_datetime()
    key = (
        normalize_stock_code(code),
        cfg.adjust,
        parse_as_of_date(cfg).strftime("%Y-%m-%d"),
    )
    with _VALIDATED_WASH_CACHE_LOCK:
        _VALIDATED_WASH_CACHE[key] = current.timestamp()
        if len(_VALIDATED_WASH_CACHE) > 12000:
            cutoff = current.timestamp() - WASH_OHLCV_TTL_SEC * 2
            stale_keys = [
                item
                for item, timestamp in _VALIDATED_WASH_CACHE.items()
                if timestamp < cutoff
            ]
            for item in stale_keys:
                _VALIDATED_WASH_CACHE.pop(item, None)


def wash_cache_validation_is_fresh(
    code: str,
    cfg: ScanConfig,
    now: datetime | None = None,
) -> bool:
    """Whether a current live quote has validated this code without a rewrite."""
    current = now or current_local_datetime()
    key = (
        normalize_stock_code(code),
        cfg.adjust,
        parse_as_of_date(cfg).strftime("%Y-%m-%d"),
    )
    with _VALIDATED_WASH_CACHE_LOCK:
        validated_at = _VALIDATED_WASH_CACHE.get(key)
    if not validated_at:
        return False
    return wash_cache_payload_is_fresh(
        {
            "saved_at": validated_at,
            "as_of": parse_as_of_date(cfg).strftime("%Y-%m-%d"),
        },
        cfg,
        now=current,
    )


def minimum_history_rows(cfg: ScanConfig) -> int:
    return max(70, cfg.trend_rise_days + 10)


def history_data_issue(df: pd.DataFrame | None, cfg: ScanConfig) -> str:
    """Return why a history frame is unsafe for scanning, or an empty string."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return "empty"
    min_rows = minimum_history_rows(cfg)
    if len(df) < min_rows:
        return f"only {len(df)} rows (need {min_rows})"
    if "date" not in df.columns:
        return "missing date column"
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dates.empty:
        return "invalid date column"
    age_days = (parse_as_of_date(cfg).date() - dates.max().date()).days
    if age_days < 0:
        return f"latest row is {abs(age_days)} days after as-of date"
    if age_days > cfg.cache_max_stale_days:
        return (
            f"latest row is {age_days} days old "
            f"(max {cfg.cache_max_stale_days})"
        )
    return ""


def wash_cache_frame_in_shares(payload: dict[str, object]) -> pd.DataFrame | None:
    """Return a cached frame under the canonical volume=shares contract."""
    df = payload.get("data")
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None

    unit = str(payload.get("volume_unit") or "").lower()
    source = str(payload.get("source") or "").lower()
    if unit == "shares":
        return df
    eastmoney_marker_columns = [
        column
        for column in ("成交额", "换手率", "振幅", "涨跌额")
        if column in df.columns
    ]
    if eastmoney_marker_columns:
        # Old mixed payloads can contain Eastmoney rows in lots followed by a
        # Sina batch row in shares.  Marker columns are populated only on the
        # Eastmoney rows, so convert those rows rather than the entire frame.
        lots_mask = df[eastmoney_marker_columns].notna().any(axis=1)
        if lots_mask.any():
            converted = df.copy()
            converted.loc[lots_mask, "volume"] = pd.to_numeric(
                converted.loc[lots_mask, "volume"], errors="coerce"
            ) * 100.0
            return converted
    if unit in {"lots", "hands"} or source in {"akshare", "eastmoney"}:
        converted = df.copy()
        converted["volume"] = pd.to_numeric(
            converted.get("volume"), errors="coerce"
        ) * 100.0
        return converted
    if source in {"sina", "sina_batch", "yahoo"}:
        # Compatibility for caches created before volume_unit was persisted.
        # These providers already report shares.
        return df
    # Unknown legacy payloads are intentionally rejected instead of silently
    # mixing lots and shares in volume-ratio pattern rules.
    return None


def persist_volume_unit_migration(
    path: Path,
    payload: dict[str, object],
    df: pd.DataFrame,
) -> None:
    """Atomically upgrade a safely identifiable legacy payload in place."""
    if payload.get("volume_unit") or not isinstance(df, pd.DataFrame):
        return
    source = str(payload.get("source") or "").lower()
    has_eastmoney_markers = any(
        column in df.columns
        for column in ("成交额", "换手率", "振幅", "涨跌额")
    )
    if source not in {"sina", "sina_batch", "yahoo", "akshare", "eastmoney"} \
            and not has_eastmoney_markers:
        return
    temp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.volume.tmp"
    )
    try:
        migrated = dict(payload)
        migrated["data"] = df
        migrated["volume_unit"] = "shares"
        pd.to_pickle(migrated, temp_path)
        os.replace(temp_path, path)
    except Exception:
        pass
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def completed_history_view(
    df: pd.DataFrame,
    cfg: ScanConfig,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Exclude today's still-changing daily bar from end-of-day strategies."""
    if cfg.as_of_date or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    current = now or current_local_datetime()
    if not is_a_share_intraday(current) or "date" not in df.columns:
        return df
    dates = pd.to_datetime(df["date"], errors="coerce")
    if dates.dropna().empty or dates.max().date() != current.date():
        return df
    completed = df.loc[dates.dt.date < current.date()].copy()
    completed.attrs.update(df.attrs)
    completed.attrs["provisional_bar_excluded"] = True
    return completed.reset_index(drop=True)


def tag_wash_history(
    df: pd.DataFrame,
    source: str,
    stale_fallback: bool = False,
    cache_saved_at: float | None = None,
) -> pd.DataFrame:
    tagged = df.copy(deep=False)
    tagged.attrs["data_source"] = str(source or "unknown")
    tagged.attrs["stale_fallback"] = bool(stale_fallback)
    dates = pd.to_datetime(tagged.get("date"), errors="coerce").dropna()
    tagged.attrs["latest_data_date"] = (
        dates.max().date().isoformat() if not dates.empty else ""
    )
    tagged.attrs["volume_unit"] = "shares"
    if cache_saved_at is not None:
        tagged.attrs["cache_saved_at"] = float(cache_saved_at)
    return tagged


def load_wash_ohlcv_cache(code: str, cfg: ScanConfig) -> pd.DataFrame | None:
    """读取本项目持久化的洗盘 OHLCV 缓存。

    仅当缓存的 as_of 日期与本次扫描一致、且写入时间在 TTL 内时复用，
    保证当天重复扫描免网络、跨日/跨时段自动失效刷新。
    """
    try:
        path = wash_ohlcv_cache_dir() / f"{code}.pkl"
        if not path.exists():
            return None
        payload = pd.read_pickle(path)
        if not isinstance(payload, dict):
            return None

        as_of = parse_as_of_date(cfg).strftime("%Y-%m-%d")
        validated_now = wash_cache_validation_is_fresh(code, cfg)
        if payload.get("as_of") != as_of and not validated_now:
            return None
        if payload.get("adjust") != cfg.adjust:
            return None
        if not wash_cache_payload_is_fresh(payload, cfg, code=code):
            return None

        df = wash_cache_frame_in_shares(payload)
        if df is not None:
            persist_volume_unit_migration(path, payload, df)
        df = completed_history_view(df, cfg) if df is not None else None
        if history_data_issue(df, cfg):
            return None
        return tag_wash_history(
            df,
            str(payload.get("source") or "shared_cache"),
            cache_saved_at=float(payload.get("saved_at") or 0),
        )
    except Exception:
        return None


def load_recent_wash_ohlcv_cache(code: str, cfg: ScanConfig) -> pd.DataFrame | None:
    """Use a recent complete persistent cache only after live sources fail."""
    try:
        path = wash_ohlcv_cache_dir() / f"{code}.pkl"
        if not path.exists():
            return None
        payload = pd.read_pickle(path)
        if not isinstance(payload, dict) or payload.get("adjust") != cfg.adjust:
            return None
        df = wash_cache_frame_in_shares(payload)
        if df is not None:
            persist_volume_unit_migration(path, payload, df)
        df = completed_history_view(df, cfg) if df is not None else None
        if history_data_issue(df, cfg):
            return None
        return tag_wash_history(
            df,
            str(payload.get("source") or "shared_cache"),
            stale_fallback=True,
            cache_saved_at=float(payload.get("saved_at") or 0),
        )
    except Exception:
        return None


def save_wash_ohlcv_cache(
    code: str,
    cfg: ScanConfig,
    df: pd.DataFrame,
    source: str = "",
) -> None:
    """Atomically persist OHLCV so concurrent scans never read a half-write."""
    temp_path: Path | None = None
    try:
        path = wash_ohlcv_cache_dir() / f"{code}.pkl"
        dates = pd.to_datetime(df.get("date"), errors="coerce").dropna()
        latest_bar_date = dates.max().date().isoformat() if not dates.empty else ""
        payload = {
            "code": code,
            "as_of": parse_as_of_date(cfg).strftime("%Y-%m-%d"),
            "adjust": cfg.adjust,
            "saved_at": time.time(),
            "source": source,
            "volume_unit": "shares",
            "latest_bar_date": latest_bar_date,
            "data": df,
        }
        temp_path = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        pd.to_pickle(payload, temp_path)
        os.replace(temp_path, path)
    except Exception:
        # 缓存写入失败不应影响扫描主流程
        pass
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


def _fetch_sina_quote_batch(
    stocks: list[StockInfo],
    cfg: ScanConfig,
) -> dict[str, dict[str, object]]:
    symbols = [sina_daily_symbol(stock.code) for stock in stocks]
    url = "http://hq.sinajs.cn/list=" + ",".join(symbols)
    headers = {"Referer": "http://finance.sina.com.cn"}
    response = get_http_session().get(url, headers=headers, timeout=30)
    response.raise_for_status()
    response.encoding = "gbk"
    as_of = parse_as_of_date(cfg).date()
    quotes: dict[str, dict[str, object]] = {}

    for symbol, payload in re.findall(
        r'var hq_str_([^=]+)="([^"]*)";', response.text
    ):
        parts = payload.split(",")
        if len(parts) < 33 or not parts[0] or parts[32] == "-3":
            continue
        try:
            quote_date = datetime.strptime(parts[30], "%Y-%m-%d").date()
            open_price = float(parts[1])
            previous_close = float(parts[2])
            close = float(parts[3])
            high = float(parts[4])
            low = float(parts[5])
            volume = float(parts[8])
        except (TypeError, ValueError):
            continue
        if quote_date > as_of:
            continue
        if min(open_price, previous_close, close, high, low) <= 0 or volume <= 0:
            continue
        code = normalize_stock_code(symbol[2:])
        quotes[code] = {
            "date": quote_date,
            "open": open_price,
            "close": close,
            "high": high,
            "low": low,
            "volume": volume,
            "previous_close": previous_close,
        }
    return quotes


def fetch_sina_quote_snapshot(
    stocks: list[StockInfo],
    cfg: ScanConfig,
    diagnostics: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    """Fetch the whole scan universe in a handful of Sina batch requests."""
    batches = [
        stocks[index:index + SINA_QUOTE_BATCH_SIZE]
        for index in range(0, len(stocks), SINA_QUOTE_BATCH_SIZE)
    ]
    if not batches:
        if diagnostics is not None:
            diagnostics.update({"quote_batches": 0, "quote_batch_errors": 0})
        return {}

    quotes: dict[str, dict[str, object]] = {}
    batch_errors: list[str] = []
    max_workers = min(SINA_QUOTE_BATCH_WORKERS, len(batches))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_fetch_sina_quote_batch, batch, cfg)
            for batch in batches
        ]
        for future in as_completed(futures):
            try:
                quotes.update(future.result())
            except Exception as exc:
                batch_errors.append(brief_error(exc))
    if diagnostics is not None:
        diagnostics.update({
            "quote_batches": len(batches),
            "quote_batch_errors": len(batch_errors),
            "quote_batch_error_samples": batch_errors[:3],
        })
    return quotes


def trade_dates_through(as_of: date) -> list[date]:
    """Return known A-share trading dates up to ``as_of``."""
    with _TRADE_CALENDAR_LOCK:
        cached_dates = list(_TRADE_CALENDAR_DATES)
    if cached_dates and cached_dates[-1] >= as_of:
        return [value for value in cached_dates if value <= as_of]
    try:
        frame = ak.tool_trade_date_hist_sina()
        dates = pd.to_datetime(frame["trade_date"], errors="coerce").dropna()
        all_dates = sorted(set(value.date() for value in dates))
        if not all_dates:
            return []
        with _TRADE_CALENDAR_LOCK:
            _TRADE_CALENDAR_DATES[:] = all_dates
        return [value for value in all_dates if value <= as_of]
    except Exception:
        if cached_dates and cached_dates[-1] >= as_of:
            return [value for value in cached_dates if value <= as_of]
        return []


def expected_latest_quote_date(
    calendar: list[date],
    cfg: ScanConfig,
    now: datetime | None = None,
) -> date | None:
    """Latest trading date a current quote is expected to represent."""
    if not calendar:
        return None
    expected = calendar[-1]
    current = now or current_local_datetime()
    as_of = parse_as_of_date(cfg).date()
    if (
        not cfg.as_of_date
        and expected == as_of == current.date()
        and _minute_of_day(current) < MARKET_DATA_OPEN_MINUTE
        and len(calendar) > 1
    ):
        return calendar[-2]
    return expected


def merge_sina_quote_history(
    df: pd.DataFrame,
    quote: dict[str, object],
    cfg: ScanConfig,
    previous_trade_date: date | None,
) -> pd.DataFrame | None:
    """Append/replace one quote bar without creating a gap in daily history."""
    if history_data_issue(df, cfg):
        return None
    required_fast_columns = {
        "date", "open", "close", "high", "low", "volume", "pct_chg",
        "ma5", "ma10", "ma20", "ma60",
    }
    fast_contract = bool(
        required_fast_columns.issubset(df.columns)
        and pd.api.types.is_datetime64_any_dtype(df["date"])
        and df["date"].is_monotonic_increasing
        and not df["date"].duplicated().any()
    )
    if fast_contract:
        daily = df.copy()
    else:
        daily = df.copy()
        daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
        daily = daily.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if daily.empty:
        return None

    quote_date = pd.Timestamp(quote["date"])
    last_date = daily.iloc[-1]["date"].date()
    if last_date != quote_date.date() and last_date != previous_trade_date:
        return None

    previous_close = float(quote["previous_close"])
    if last_date == previous_trade_date and previous_close > 0:
        cached_close = float(daily.iloc[-1]["close"])
        # A large mismatch usually means a corporate-action adjustment changed;
        # force a full history refresh instead of mixing incompatible prices.
        if abs(cached_close / previous_close - 1) > 0.02:
            return None

    row = {
        "date": quote_date,
        "open": float(quote["open"]),
        "close": float(quote["close"]),
        "high": float(quote["high"]),
        "low": float(quote["low"]),
        "volume": float(quote["volume"]),
        "pct_chg": (
            (float(quote["close"]) / previous_close - 1) * 100
            if previous_close > 0 else float("nan")
        ),
    }
    if fast_contract:
        if last_date == quote_date.date():
            last_index = daily.index[-1]
            for column in ("股票代码", "成交额", "振幅", "涨跌额", "换手率"):
                if column in daily.columns:
                    daily.at[last_index, column] = np.nan
            for column, value in row.items():
                daily.at[last_index, column] = value
        else:
            append_row = {column: np.nan for column in daily.columns}
            append_row.update(row)
            daily = pd.concat(
                [daily, pd.DataFrame([append_row])],
                ignore_index=True,
                sort=False,
            )
        last_index = daily.index[-1]
        for window in (5, 10, 20, 60):
            daily.at[last_index, f"ma{window}"] = (
                daily["close"].iloc[-window:].mean()
                if len(daily) >= window
                else np.nan
            )
        daily.attrs.update(df.attrs)
        return daily

    daily = daily[daily["date"] != quote_date]
    daily = pd.concat([daily, pd.DataFrame([row])], ignore_index=True, sort=False)
    daily = daily.sort_values("date").reset_index(drop=True)
    return add_ma(daily)


def prepare_scan_cache(stocks: list[StockInfo], cfg: ScanConfig) -> dict[str, object]:
    """Bulk-update recent caches so the main scan becomes local CPU work."""
    started = time.time()
    meta: dict[str, object] = {
        "enabled": False,
        "quotes": 0,
        "prepared": 0,
        "reused": 0,
        "needs_full_fetch": len(stocks),
        "elapsed_sec": 0.0,
    }
    if cfg.as_of_date or cfg.data_source not in {"auto", "sina"} or cfg.adjust == "hfq":
        return meta

    quote_diagnostics: dict[str, object] = {}
    quotes = fetch_sina_quote_snapshot(stocks, cfg, diagnostics=quote_diagnostics)
    meta["enabled"] = True
    meta["quotes"] = len(quotes)
    meta.update(quote_diagnostics)
    calendar = trade_dates_through(parse_as_of_date(cfg).date())
    if not calendar:
        meta["calendar_error"] = "交易日历不可用，已禁用批量行情合并"
        meta["elapsed_sec"] = round(time.time() - started, 1)
        return meta
    expected_quote_date = expected_latest_quote_date(calendar, cfg)
    current = current_local_datetime()
    completed_bars_only = bool(
        not cfg.as_of_date and is_a_share_intraday(current)
    )
    meta["intraday_completed_bars_only"] = completed_bars_only
    meta["latest_quote_date"] = (
        expected_quote_date.isoformat() if expected_quote_date else ""
    )
    previous_by_date: dict[date, date | None] = {}
    for quote in quotes.values():
        quote_date = quote["date"]
        if quote_date in previous_by_date:
            continue
        previous = [item for item in calendar if item < quote_date]
        previous_by_date[quote_date] = previous[-1] if previous else None

    def prepare_one(stock: StockInfo) -> str:
        cached = load_recent_wash_ohlcv_cache(stock.code, cfg)
        if cached is None:
            return "needs_full_fetch"
        quote = quotes.get(stock.code)
        if quote is None:
            return "needs_full_fetch"
        if expected_quote_date is not None and quote["date"] != expected_quote_date:
            return "needs_full_fetch"
        try:
            last = cached.iloc[-1]
            last_date = pd.Timestamp(last["date"]).date()
            if completed_bars_only and quote["date"] == current.date():
                previous_trade_date = previous_by_date.get(quote["date"])
                saved_at = float(cached.attrs.get("cache_saved_at") or 0)
                saved = datetime.fromtimestamp(saved_at) if saved_at else None
                prior_bar_was_provisional = bool(
                    saved
                    and saved.date() == last_date
                    and _minute_of_day(saved) < MARKET_CLOSE_MINUTE
                )
                if (
                    last_date != previous_trade_date
                    or prior_bar_was_provisional
                    or not math.isclose(
                        float(last["close"]),
                        float(quote["previous_close"]),
                        rel_tol=1e-8,
                        abs_tol=1e-4,
                    )
                ):
                    return "needs_full_fetch"
                mark_wash_cache_validated(stock.code, cfg)
                return "reused"
            unchanged = (
                last_date == quote["date"]
                and all(
                    math.isclose(
                        float(last[column]),
                        float(quote[column]),
                        rel_tol=1e-10,
                        abs_tol=1e-8,
                    )
                    for column in ("open", "close", "high", "low", "volume")
                )
            )
            if unchanged:
                mark_wash_cache_validated(stock.code, cfg)
                return "reused"
        except (KeyError, TypeError, ValueError, IndexError):
            pass
        merged = merge_sina_quote_history(
            cached,
            quote,
            cfg,
            previous_by_date.get(quote["date"]),
        )
        if merged is None:
            return "needs_full_fetch"
        save_wash_ohlcv_cache(stock.code, cfg, merged, source="sina_batch")
        return "prepared"

    counts = {"prepared": 0, "reused": 0, "needs_full_fetch": 0}
    max_workers = max(1, min(int(cfg.workers or 1), 24, len(stocks) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(prepare_one, stock) for stock in stocks]
        for future in as_completed(futures):
            try:
                counts[future.result()] += 1
            except Exception:
                counts["needs_full_fetch"] += 1

    meta.update(counts)
    meta["elapsed_sec"] = round(time.time() - started, 1)
    return meta


def fetch_daily_cache(code: str, cfg: ScanConfig) -> pd.DataFrame | None:
    files: list[Path] = []
    for cache_dir in candidate_cache_dirs():
        if cache_dir.exists():
            files.extend(cache_dir.glob(f"*_stock_history_{code}_*.pkl"))

    def _days_in_name(path: Path) -> int:
        # 文件名形如 {date}_stock_history_{code}_{days}.pkl
        # 取末段数字作为天数；越大代表历史越长，应优先选用
        m = re.search(r"_(\d+)\.pkl$", path.name)
        return int(m.group(1)) if m else 0

    # 按 (天数, 修改时间) 倒序：优先最长历史，再优先最新文件
    # 避免字符串排序把 "_30" 排在 "_120" 前面导致只读到 30 行短缓存
    files = sorted(
        set(files),
        key=lambda p: (_days_in_name(p), p.stat().st_mtime if p.exists() else 0),
        reverse=True,
    )
    for path in files:
        try:
            cached = pd.read_pickle(path)
            if isinstance(cached, dict):
                raw = cached.get("data")
            else:
                raw = cached
            if not isinstance(raw, pd.DataFrame) or raw.empty:
                continue

            daily = raw.copy()
            daily["date"] = pd.to_datetime(daily["date"])
            as_of = parse_as_of_date(cfg)
            daily = daily[daily["date"] <= as_of]
            if daily.empty:
                continue
            for column in ("open", "close", "high", "low", "volume"):
                daily[column] = pd.to_numeric(daily[column], errors="coerce")
            daily = daily.dropna(subset=["date", "open", "close", "high", "low", "volume"])
            daily = daily.sort_values("date").reset_index(drop=True)
            if "pct_chg" not in daily.columns:
                daily["pct_chg"] = daily["close"].pct_change() * 100
            else:
                daily["pct_chg"] = pd.to_numeric(daily["pct_chg"], errors="coerce")
                daily["pct_chg"] = daily["pct_chg"].fillna(daily["close"].pct_change() * 100)
            daily = completed_history_view(daily, cfg)
            if history_data_issue(daily, cfg):
                continue
            return tag_wash_history(
                add_ma(daily), "legacy_cache", stale_fallback=True
            )
        except Exception:
            continue
    return None


def value_at(container: dict[str, list[float]], key: str, index: int) -> float | None:
    values = container.get(key) or []
    if index >= len(values):
        return None
    value = values[index]
    return None if value is None else float(value)


def fetch_daily(code: str, cfg: ScanConfig) -> pd.DataFrame:
    # 优先读取本项目持久化的当日缓存：同一 as_of 日期、且在 TTL 内的缓存直接复用，
    # 使当天的重复扫描（如调参重跑、Web 端多次触发）几乎不产生网络请求。
    cached_df = load_wash_ohlcv_cache(code, cfg)
    if cached_df is not None and not cached_df.empty:
        return cached_df

    errors: list[str] = []
    short_history: pd.DataFrame | None = None
    sources = (
        ("sina", "akshare", "yahoo")
        if cfg.data_source == "auto"
        else (cfg.data_source,)
    )
    live_sources = tuple(source for source in sources if source != "cache")

    for source in live_sources:
        try:
            if source == "sina":
                df = fetch_daily_sina(code, cfg)
            elif source == "akshare":
                df = fetch_daily_akshare(code, cfg)
            elif source == "yahoo":
                df = fetch_daily_yahoo(code, cfg)
            else:
                raise ValueError(f"Unknown data source: {source}")

            if isinstance(df, pd.DataFrame):
                df = completed_history_view(df, cfg)
            issue = history_data_issue(df, cfg)
            if not issue:
                df = tag_wash_history(df, source)
                save_wash_ohlcv_cache(code, cfg, df, source=source)
                return df
            if issue.startswith("only ") and isinstance(df, pd.DataFrame) and not df.empty:
                df = tag_wash_history(df, source)
                if short_history is None or len(df) > len(short_history):
                    short_history = df
            errors.append(f"{source}={issue}")
        except Exception as exc:
            errors.append(f"{source}={brief_error(exc)}")

    # 实时源全部失败后，优先使用洗盘扫描自己的近期完整缓存；再尝试
    # 项目里的通用历史缓存。两者都必须通过行数和新鲜度校验。
    cached_df = load_recent_wash_ohlcv_cache(code, cfg)
    if cached_df is not None:
        return cached_df
    cached_df = fetch_daily_cache(code, cfg)
    if cached_df is not None:
        return cached_df
    errors.append("cache=no recent complete history")

    # A newly listed stock with genuine but insufficient history is a normal
    # non-match, not a data-source outage.  Return its best short frame so
    # scan_stock can apply the ordinary minimum-history check.
    if short_history is not None:
        return short_history

    error = DailyDataSourceError(code, errors)
    if cfg.show_errors:
        progress_write(f"Skip {code}: {error}")
    raise error


def parse_as_of_date(cfg: ScanConfig) -> datetime:
    if not cfg.as_of_date:
        return datetime.today()
    return datetime.strptime(cfg.as_of_date, "%Y-%m-%d")


def scan_stock(
    stock: StockInfo, cfg: ScanConfig, today: datetime
) -> list[dict[str, object]]:
    rows, _ = scan_stock_with_diagnostics(stock, cfg, today)
    return rows


def scan_stock_with_diagnostics(
    stock: StockInfo,
    cfg: ScanConfig,
    today: datetime,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    df = fetch_daily(stock.code, cfg)
    diagnostics = {
        "data_date": str(df.attrs.get("latest_data_date") or ""),
        "data_source": str(df.attrs.get("data_source") or "unknown"),
        "stale_fallback": bool(df.attrs.get("stale_fallback")),
    }
    if not diagnostics["data_date"] and len(df):
        dates = pd.to_datetime(df.get("date"), errors="coerce").dropna()
        if not dates.empty:
            diagnostics["data_date"] = dates.max().date().isoformat()
    min_rows = minimum_history_rows(cfg)
    if len(df) < min_rows:
        diagnostics["short_history"] = True
        return [], diagnostics

    return build_result_rows(stock, df, cfg, today), diagnostics


def build_result_rows(
    stock: StockInfo, df: pd.DataFrame, cfg: ScanConfig, today: datetime
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    hits = detect_wash_pattern(df, cfg)
    for hit in hits:
        row = df.iloc[hit.end_index]
        days_ago = (today - row["date"].to_pydatetime()).days
        if days_ago > cfg.recent_days:
            continue

        current_close = float(df.iloc[-1]["close"])
        latest_bar_date = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        end_close = float(row["close"])
        future_rise = (
            (current_close - end_close) / end_close * 100
            if end_close > 0
            else float("nan")
        )
        ma20_val = row.get("ma20")
        dist_ma20 = (
            round((end_close - float(ma20_val)) / float(ma20_val) * 100, 2)
            if ma20_val is not None and not pd.isna(ma20_val) and float(ma20_val) > 0
            else float("nan")
        )
        rows.append(
            {
                "代码": stock.code,
                "名称": stock.name,
                "状态": hit.status,
                "扫描模式": hit.scan_mode,
                "洗盘开始日": df.iloc[hit.start_index]["date"].strftime("%Y-%m-%d"),
                "洗盘结束日": row["date"].strftime("%Y-%m-%d"),
                "距今(天)": days_ago,
                "模式": hit.pattern_type,
                "备注": hit.note,
                "结束收盘": round(end_close, 2),
                "当前价": round(current_close, 2),
                "最新行情日": latest_bar_date,
                "后续涨幅%": round(future_rise, 2),
                "趋势涨幅%": round(trend_rise_pct(df, hit.end_index, cfg), 2),
                "洗盘回撤%": hit.drawdown_pct,
                "距MA20%": dist_ma20,
            }
        )
    return rows


def scan_sequential(
    stocks: list[StockInfo], cfg: ScanConfig, today: datetime, show_progress: bool
) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    errors = 0
    iterator: Iterable[StockInfo]
    if show_progress:
        iterator = tqdm(stocks, desc="扫描中", unit="只")
    else:
        iterator = stocks

    for stock in iterator:
        try:
            found.extend(scan_stock(stock, cfg, today))
        except Exception as exc:
            errors += 1
            if cfg.show_errors:
                progress_write(f"Skip {stock.code}: {exc}")
    if stocks and (len(stocks) - errors) * 5 < len(stocks) * 4:
        raise RuntimeError(
            f"扫描有效覆盖率过低（{len(stocks) - errors}/{len(stocks)}），"
            "结果已作废"
        )
    if errors and show_progress:
        progress_write(f"行情/规则错误：{errors} 只")
    return found


def scan_parallel(
    stocks: list[StockInfo], cfg: ScanConfig, today: datetime, show_progress: bool
) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    errors = 0
    progress = tqdm(
        total=len(stocks),
        desc="扫描中",
        unit="只",
        disable=not show_progress,
    )
    try:
        with ThreadPoolExecutor(max_workers=max(1, cfg.workers)) as executor:
            futures = [
                executor.submit(scan_stock, stock, cfg, today) for stock in stocks
            ]
            for future in as_completed(futures):
                try:
                    found.extend(future.result())
                except Exception as exc:
                    errors += 1
                    if cfg.show_errors:
                        progress_write(f"Skip stock: {exc}")
                finally:
                    progress.update(1)
    finally:
        progress.close()
    if stocks and (len(stocks) - errors) * 5 < len(stocks) * 4:
        raise RuntimeError(
            f"扫描有效覆盖率过低（{len(stocks) - errors}/{len(stocks)}），"
            "结果已作废"
        )
    if errors and show_progress:
        progress_write(f"行情/规则错误：{errors} 只")
    return found


def sort_wash_results(result: pd.DataFrame) -> pd.DataFrame:
    """对洗盘结果排序：实盘可操作性优先，而非按回测涨幅。

    旧逻辑按"后续涨幅%"降序，会把今天刚出现(后续涨幅=0)的新信号排到最底部，
    而把29天前已涨完的旧信号排到最前——榜首全是错过买点的历史信号。
    这里改为：已确认优先于候选预警，再按距今天数升序（越新越靠前）。
    "后续涨幅%"退化为验证列，不再作为排序键。
    """
    if result.empty:
        return result
    df = result.copy()
    # 已确认 = 0 排在候选预警 = 1 前面
    df["_status_rank"] = (df["状态"] != "已确认").astype(int)
    df["_days"] = pd.to_numeric(df["距今(天)"], errors="coerce").fillna(9999)
    df = df.sort_values(
        ["_status_rank", "_days"], ascending=[True, True]
    ).reset_index(drop=True)
    return df.drop(columns=["_status_rank", "_days"])


def resolve_scan_stocks(cfg: ScanConfig) -> list[StockInfo]:
    """Resolve the requested universe without silently dropping valid shapes.

    The old spot prefilter is lossy: it imposes price/liquidity/board rules that
    are absent from the pattern definition.  Full-A therefore stays complete
    by default; the legacy speed/recall tradeoff requires an explicit opt-in.
    """
    if (
        cfg.enable_lossy_prescreen
        and cfg.stock_pool == "all_a"
        and cfg.max_stocks == 0
    ):
        print("⚠️ [洗盘扫描] 已显式启用有损实时预筛选，结果可能漏票...")
        try:
            from wash_pattern_optimizer import pre_screen_wash_candidates
            pre_filtered = pre_screen_wash_candidates(
                cfg.stock_pool,
                allow_lossy=True,
            )

            if pre_filtered:
                # 预筛选返回 (代码, 名称) 列表；保留名称以填充结果文件“名称”列。
                # 兼容旧返回（仅代码字符串）：缺名称时回退为空串。
                stocks = []
                for item in pre_filtered:
                    if isinstance(item, (tuple, list)):
                        code = str(item[0])
                        name = str(item[1]) if len(item) > 1 else ""
                    else:
                        code, name = str(item), ""
                    stocks.append(StockInfo(code=code, name=name))
                print(f"✅ 使用预筛选结果：{len(stocks)} 只股票")
                return stocks
            stocks = get_stock_pool(cfg.stock_pool, cfg.pool_source)
            print(f"⚠️ 预筛选失败，使用原有逻辑：{len(stocks)} 只股票")
            return stocks
        except Exception as e:
            print(f"⚠️ 预筛选模块导入失败: {e}，使用原有逻辑")
            return get_stock_pool(cfg.stock_pool, cfg.pool_source)

    return get_stock_pool(cfg.stock_pool, cfg.pool_source)


def scan(cfg: ScanConfig, show_progress: bool = True) -> pd.DataFrame:
    """
    洗盘扫描（优化版）

    Full-A scans are complete by default.  Fast bulk quote/cache preparation
    provides the speedup without a lossy stock-universe prefilter.
    """
    stocks = resolve_scan_stocks(cfg)

    if cfg.max_stocks > 0:
        stocks = stocks[: cfg.max_stocks]

    # Web 路由有自己的进度循环，会显式调用同一预热函数；命令行直接运行时
    # 也先批量更新缓存，避免退回逐股下载日线。
    prepare_scan_cache(stocks, cfg)

    today = parse_as_of_date(cfg)
    if cfg.workers <= 1 or len(stocks) <= 1:
        found = scan_sequential(stocks, cfg, today, show_progress)
    else:
        found = scan_parallel(stocks, cfg, today, show_progress)

    result = pd.DataFrame(found, columns=RESULT_COLUMNS)
    if not result.empty:
        result = sort_wash_results(result)
    return result


def save_and_print_results(result: pd.DataFrame, output: str) -> None:
    if result.empty:
        print("\n未找到符合条件的洗盘模式")
        result.to_csv(output, index=False, encoding="utf-8-sig")
        print(f"空结果已保存至：{output}")
        return

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)
    pd.set_option("display.float_format", lambda value: f"{value:.2f}")
    print(f"\n共找到 {len(result)} 个洗盘模式：\n")
    print(result.to_string(index=False))
    result.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存至：{output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="洗盘模式扫描器（强趋势洗盘 / 低位反转洗盘）"
    )
    parser.add_argument(
        "--mode",
        choices=("strong", "low_reversal", "breakout_base", "both", "all"),
        default=ScanConfig.scan_mode,
        help=(
            "扫描模式：strong=强趋势洗盘, low_reversal=低位反转洗盘, "
            "breakout_base=突破前蓄势, both=strong+low_reversal, all=三种都扫"
        ),
    )
    parser.add_argument(
        "--pool",
        choices=("hs300", "zz500", "all_a"),
        default=ScanConfig.stock_pool,
        help="股票池：hs300=沪深300, zz500=中证500, all_a=全部A股",
    )
    parser.add_argument(
        "--pool-source",
        choices=("auto", "sina", "akshare", "cache"),
        default=ScanConfig.pool_source,
        help="股票池来源：auto=新浪优先，失败后AKShare/cache；sina=新浪财经；akshare=AKShare；cache=本地缓存",
    )
    parser.add_argument("--max-stocks", type=int, default=ScanConfig.max_stocks)
    parser.add_argument("--fetch-days", type=int, default=ScanConfig.fetch_days)
    parser.add_argument("--recent-days", type=int, default=ScanConfig.recent_days)
    parser.add_argument(
        "--workers",
        type=int,
        default=ScanConfig.workers,
        help="并发线程数，1 表示单线程",
    )
    parser.add_argument("--trend-days", type=int, default=ScanConfig.trend_rise_days)
    parser.add_argument(
        "--trend-min-rise",
        type=float,
        default=ScanConfig.trend_min_rise_pct,
        help="过去趋势窗口的最低涨幅百分比",
    )
    parser.add_argument(
        "--shrink-ratio",
        type=float,
        default=ScanConfig.shrink_ratio,
        help="缩量阴线：当日量 ≤ 前日量 * shrink-ratio（默认0.95，首阴允许不缩量）",
    )
    parser.add_argument(
        "--yang-vol-ratio",
        type=float,
        default=ScanConfig.yang_vol_ratio,
        help="反弹阳线放量倍数（默认1.50，即须放量50%%以上）",
    )
    parser.add_argument(
        "--yin-max-body-pct",
        type=float,
        default=ScanConfig.yin_max_body_pct,
        help="洗盘阴线最大实体幅度%%（超过则视为暴跌，默认5.0）",
    )
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=ScanConfig.max_drawdown_pct,
        help="洗盘区间最大回撤百分比",
    )
    parser.add_argument(
        "--c-front-vol-ratio",
        type=float,
        default=ScanConfig.c_front_vol_ratio,
        help="C模式前两阴允许的最大量比（默认1.20）",
    )
    parser.add_argument(
        "--c-yang-vol-ratio",
        type=float,
        default=ScanConfig.c_yang_vol_ratio,
        help="C模式试盘阳放量倍数（默认1.35）",
    )
    parser.add_argument(
        "--c-shakeout-body-pct",
        type=float,
        default=ScanConfig.c_shakeout_body_pct,
        help="C模式高开回落阴最大实体幅度%%（默认6.0）",
    )
    parser.add_argument(
        "--c-shakeout-min-vol-ratio",
        type=float,
        default=ScanConfig.c_shakeout_min_vol_ratio,
        help="C模式高开回落阴相对试盘阳的最低量比（默认0.90）",
    )
    parser.add_argument(
        "--c-tail-vol-ratio",
        type=float,
        default=ScanConfig.c_tail_vol_ratio,
        help="C模式第一根缩量阴相对换手阴的最大量比（默认0.75）",
    )
    parser.add_argument(
        "--c-tail-flat-ratio",
        type=float,
        default=ScanConfig.c_tail_flat_ratio,
        help="C模式第二根缩量阴相对前阴的最大量比（默认1.05）",
    )
    parser.add_argument("--confirm-yang", type=int, default=ScanConfig.confirm_yang)
    parser.add_argument(
        "--no-candidate-warnings",
        action="store_true",
        help="关闭最新K线半完成形态预警（阴阴阳阴 / 阴阴阳阳阴）",
    )
    parser.add_argument(
        "--enable-lossy-prescreen",
        action="store_true",
        help="显式启用有损实时预筛选（更快，但可能漏掉有效形态）",
    )
    parser.add_argument(
        "--no-ma-bullish",
        action="store_true",
        help="关闭 MA5>MA10>MA20>MA60 多头排列过滤",
    )
    parser.add_argument(
        "--adjust",
        choices=("", "qfq", "hfq"),
        default=ScanConfig.adjust,
        help="复权方式：空字符串=不复权, qfq=前复权, hfq=后复权",
    )
    parser.add_argument(
        "--data-source",
        choices=("auto", "sina", "akshare", "yahoo", "cache"),
        default=ScanConfig.data_source,
        help="日线数据源：auto=新浪优先，失败后使用东方财富/Yahoo/近期缓存",
    )
    parser.add_argument("--output", default=ScanConfig.output)
    parser.add_argument(
        "--as-of-date",
        default=ScanConfig.as_of_date,
        help="回测截止日期，格式 YYYY-MM-DD；数据源只拉到该日期",
    )
    parser.add_argument("--quiet", action="store_true", help="不显示进度条")
    parser.add_argument("--show-errors", action="store_true", help="显示单票请求失败详情")
    # ── 新增过滤开关 ────────────────────────────────────────
    parser.add_argument(
        "--no-ma-support", action="store_true",
        help="关闭洗盘阴线不破MA20过滤",
    )
    parser.add_argument(
        "--allow-step-down", action="store_true",
        help="允许末尾收盘低于起始开盘97%%（默认开启）",
    )
    parser.add_argument(
        "--allow-new-high", action="store_true",
        help="允许反弹阳创近期新高（默认开启过滤）",
    )
    parser.add_argument(
        "--no-new-high-lookback", type=int, default=ScanConfig.no_new_high_lookback,
        help="反弹阳不创新高回溯天数（默认15）",
    )
    parser.add_argument(
        "--no-near-low-vol", action="store_true",
        help="关闭末尾接近地量过滤",
    )
    parser.add_argument(
        "--near-low-vol-ratio", type=float, default=ScanConfig.near_low_vol_ratio,
        help="末尾阴量 ≤ 近期最低量 × ratio（默认1.3）",
    )
    parser.add_argument(
        "--near-low-vol-lookback", type=int, default=ScanConfig.near_low_vol_lookback,
        help="地量回溯天数（默认20）",
    )
    parser.add_argument(
        "--no-impulse", action="store_true",
        help="关闭洗盘前大阳/涨停过滤",
    )
    parser.add_argument(
        "--min-impulse-pct", type=float, default=ScanConfig.min_impulse_pct,
        help="洗盘前大阳门槛涨幅％（默认7.0）",
    )
    parser.add_argument(
        "--impulse-lookback", type=int, default=ScanConfig.impulse_lookback,
        help="洗盘前大阳回溯天数（默认10）",
    )
    parser.add_argument(
        "--low-reversal-max-rise",
        type=float,
        default=ScanConfig.low_reversal_max_rise_pct,
        help="低位反转模式：过去趋势窗口最大涨幅%%（默认15.0，低于强趋势门槛）",
    )
    parser.add_argument(
        "--low-reversal-require-no-step-down",
        action="store_true",
        help="低位反转模式也要求末尾收盘不低于起始开盘97%%",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> ScanConfig:
    return ScanConfig(
        scan_mode=args.mode,
        trend_rise_days=args.trend_days,
        trend_min_rise_pct=args.trend_min_rise,
        require_ma_bullish=not args.no_ma_bullish,
        shrink_ratio=args.shrink_ratio,
        yang_vol_ratio=args.yang_vol_ratio,
        yin_max_body_pct=args.yin_max_body_pct,
        max_drawdown_pct=args.max_drawdown,
        c_front_vol_ratio=args.c_front_vol_ratio,
        c_yang_vol_ratio=args.c_yang_vol_ratio,
        c_shakeout_body_pct=args.c_shakeout_body_pct,
        c_shakeout_min_vol_ratio=args.c_shakeout_min_vol_ratio,
        c_tail_vol_ratio=args.c_tail_vol_ratio,
        c_tail_flat_ratio=args.c_tail_flat_ratio,
        confirm_yang=args.confirm_yang,
        stock_pool=args.pool,
        pool_source=args.pool_source,
        max_stocks=args.max_stocks,
        fetch_days=args.fetch_days,
        recent_days=args.recent_days,
        adjust=args.adjust,
        data_source=args.data_source,
        output=args.output,
        workers=max(1, args.workers),
        show_errors=args.show_errors,
        as_of_date=args.as_of_date,
        require_ma_support=not args.no_ma_support,
        require_no_step_down=not args.allow_step_down,
        require_no_new_high=not args.allow_new_high,
        no_new_high_lookback=args.no_new_high_lookback,
        require_near_low_vol=not args.no_near_low_vol,
        near_low_vol_ratio=args.near_low_vol_ratio,
        near_low_vol_lookback=args.near_low_vol_lookback,
        require_impulse=not args.no_impulse,
        min_impulse_pct=args.min_impulse_pct,
        impulse_lookback=args.impulse_lookback,
        include_candidate_warnings=not args.no_candidate_warnings,
        enable_lossy_prescreen=args.enable_lossy_prescreen,
        low_reversal_max_rise_pct=args.low_reversal_max_rise,
        low_reversal_require_no_step_down=args.low_reversal_require_no_step_down,
    )


def print_banner(cfg: ScanConfig) -> None:
    on = "✓"
    off = "✕"
    mode_names = {
        "strong": STRONG_MODE,
        "low_reversal": LOW_REVERSAL_MODE,
        "both": f"{STRONG_MODE} + {LOW_REVERSAL_MODE}",
    }
    print("=" * 60)
    print("  洗盘模式扫描器（两阴一阳两阴 / 两阴两阳两阴 / 试盘回落洗盘）")
    print("=" * 60)
    print(f"  扫描模式：{mode_names.get(cfg.scan_mode, cfg.scan_mode)}")
    print(f"  股票池：{cfg.stock_pool}  来源：{cfg.pool_source}")
    if cfg.as_of_date:
        print(f"  回测截止：{cfg.as_of_date}")
    print(f"  趋势要求：过去{cfg.trend_rise_days}日涨幅≥{cfg.trend_min_rise_pct}%")
    print(f"  缩量比例：≤{cfg.shrink_ratio * 100:.0f}%  阳线放量：≥{cfg.yang_vol_ratio * 100:.0f}%")
    print(f"  阴线最大实体：≤{cfg.yin_max_body_pct}%  最大回撤：≤{cfg.max_drawdown_pct}%")
    print(f"  C试盘回落：试盘阳≥{cfg.c_yang_vol_ratio * 100:.0f}%  "
          f"换手阴≤{cfg.c_shakeout_body_pct}%  "
          f"尾阴≤{cfg.c_tail_vol_ratio * 100:.0f}%/{cfg.c_tail_flat_ratio * 100:.0f}%")
    print(f"  MA20支撑：{on if cfg.require_ma_support else off}  "
          f"横盘不下台阶：{on if cfg.require_no_step_down else off}  "
          f"反弹不创新高：{on if cfg.require_no_new_high else off}")
    print(f"  末尾地量：{on if cfg.require_near_low_vol else off}(≤{cfg.near_low_vol_ratio}倍)  "
          f"前大阳作证：{on if cfg.require_impulse else off}(≥{cfg.min_impulse_pct}%,{cfg.impulse_lookback}日)")
    print(f"  低位反转：趋势涨幅<{cfg.low_reversal_max_rise_pct}%  "
          f"横盘不下台阶：{on if cfg.low_reversal_require_no_step_down else off}")
    print(f"  候选预警：{on if cfg.include_candidate_warnings else off}  "
          f"确认阳线：{cfg.confirm_yang} 根  日线数据源：{cfg.data_source}  并发线程：{cfg.workers}")
    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = config_from_args(args)
    print_banner(cfg)
    try:
        result = scan(cfg, show_progress=not args.quiet)
    except KeyboardInterrupt:
        print("\n用户中断扫描")
        return 130
    except Exception as exc:
        print(f"\n扫描失败：{exc}", file=sys.stderr)
        return 1

    save_and_print_results(result, cfg.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
