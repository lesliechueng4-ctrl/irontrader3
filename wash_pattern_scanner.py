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
import os
import re
import sys
import threading
import time
import warnings
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

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
    data_source: str = "yahoo"
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
    return (cfg.scan_mode,)


def mode_label(mode: str) -> str:
    if mode == "low_reversal":
        return LOW_REVERSAL_MODE
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
        & shrink_mask(data, 0, 1, cfg)
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
        & shrink_mask(data, 0, 1, cfg)
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
        & shrink_mask(data, 0, 1, cfg)
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
        & shrink_mask(data, 0, 1, cfg)
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


def read_stock_pool_cache(source: str, pool_name: str, max_age_days: int = 30) -> list[StockInfo]:
    for path in stock_pool_cache_files(source, pool_name):
        if not path.exists():
            continue
        age_seconds = time.time() - path.stat().st_mtime
        if age_seconds > max_age_days * 86400:
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
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False, encoding="utf-8-sig")
        except Exception:
            continue


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


def normalize_daily_columns(df: pd.DataFrame) -> pd.DataFrame:
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


# 同一 as_of 日期下，缓存在该 TTL 内视为有效（秒）。
# 4 小时意味着早盘扫一次、午后再扫一次会各自刷新，但同一时段的重复扫描走缓存。
WASH_OHLCV_TTL_SEC = 4 * 60 * 60


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
        if payload.get("as_of") != as_of:
            return None
        if payload.get("adjust") != cfg.adjust:
            return None
        if time.time() - float(payload.get("saved_at", 0)) > WASH_OHLCV_TTL_SEC:
            return None

        df = payload.get("data")
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None
        return df
    except Exception:
        return None


def save_wash_ohlcv_cache(code: str, cfg: ScanConfig, df: pd.DataFrame) -> None:
    """将网络获取的 OHLCV 写回持久缓存，供当天后续扫描复用。"""
    try:
        path = wash_ohlcv_cache_dir() / f"{code}.pkl"
        payload = {
            "code": code,
            "as_of": parse_as_of_date(cfg).strftime("%Y-%m-%d"),
            "adjust": cfg.adjust,
            "saved_at": time.time(),
            "data": df,
        }
        pd.to_pickle(payload, path)
    except Exception:
        # 缓存写入失败不应影响扫描主流程
        pass


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
            return add_ma(daily)
        except Exception:
            continue
    return None


def value_at(container: dict[str, list[float]], key: str, index: int) -> float | None:
    values = container.get(key) or []
    if index >= len(values):
        return None
    value = values[index]
    return None if value is None else float(value)


def fetch_daily(code: str, cfg: ScanConfig) -> pd.DataFrame | None:
    # 优先读取本项目持久化的当日缓存：同一 as_of 日期、且在 TTL 内的缓存直接复用，
    # 使当天的重复扫描（如调参重跑、Web 端多次触发）几乎不产生网络请求。
    cached_df = load_wash_ohlcv_cache(code, cfg)
    if cached_df is not None and not cached_df.empty:
        return cached_df

    errors: list[str] = []
    sources = ("akshare", "yahoo") if cfg.data_source == "auto" else (cfg.data_source,)
    sources = tuple(dict.fromkeys((*sources, "cache")))

    for source in sources:
        try:
            if source == "akshare":
                df = fetch_daily_akshare(code, cfg)
            elif source == "yahoo":
                df = fetch_daily_yahoo(code, cfg)
            elif source == "cache":
                df = fetch_daily_cache(code, cfg)
            else:
                raise ValueError(f"Unknown data source: {source}")

            if df is not None and not df.empty:
                # 网络源成功后写回持久缓存（cache 源命中无需重复写）
                if source != "cache":
                    save_wash_ohlcv_cache(code, cfg, df)
                return df
            errors.append(f"{source}=empty")
        except Exception as exc:
            errors.append(f"{source}={brief_error(exc)}")

    if cfg.show_errors:
        progress_write(f"Skip {code}: {'; '.join(errors)}")
    return None


def parse_as_of_date(cfg: ScanConfig) -> datetime:
    if not cfg.as_of_date:
        return datetime.today()
    return datetime.strptime(cfg.as_of_date, "%Y-%m-%d")


def scan_stock(
    stock: StockInfo, cfg: ScanConfig, today: datetime
) -> list[dict[str, object]]:
    try:
        df = fetch_daily(stock.code, cfg)
        min_rows = max(70, cfg.trend_rise_days + 10)
        if df is None or len(df) < min_rows:
            return []

        return build_result_rows(stock, df, cfg, today)
    except Exception as exc:
        if cfg.show_errors:
            progress_write(f"Skip {stock.code}: {exc}")
        return []


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
    iterator: Iterable[StockInfo]
    if show_progress:
        iterator = tqdm(stocks, desc="扫描中", unit="只")
    else:
        iterator = stocks

    for stock in iterator:
        found.extend(scan_stock(stock, cfg, today))
    return found


def scan_parallel(
    stocks: list[StockInfo], cfg: ScanConfig, today: datetime, show_progress: bool
) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
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
                found.extend(future.result())
                progress.update(1)
    finally:
        progress.close()
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
    """解析本次扫描的股票池，对全A扫描启用快速预筛选。

    抽取自 scan()，使 Web 路由（带进度回调的自定义扫描循环）也能复用
    同一套预筛选逻辑，避免网页端始终走全量 5000 只。
    """
    if cfg.stock_pool == 'all_a' and cfg.max_stocks == 0:
        print("🚀 [洗盘扫描优化] 检测到全A股扫描，启用快速预筛选...")
        try:
            from wash_pattern_optimizer import pre_screen_wash_candidates
            pre_filtered_codes = pre_screen_wash_candidates(cfg.stock_pool)

            if pre_filtered_codes:
                stocks = [StockInfo(code=c) for c in pre_filtered_codes]
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

    优化说明：
    - 增加快速预筛选层，使用实时行情过滤
    - 减少扫描范围：5000只 → 800-1500只
    - 时间节省：60%+（8分钟 → 3分钟）
    """
    stocks = resolve_scan_stocks(cfg)

    if cfg.max_stocks > 0:
        stocks = stocks[: cfg.max_stocks]

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
        choices=("strong", "low_reversal", "both"),
        default=ScanConfig.scan_mode,
        help="扫描模式：strong=强趋势洗盘, low_reversal=低位反转洗盘, both=两种都扫",
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
        choices=("auto", "akshare", "yahoo"),
        default=ScanConfig.data_source,
        help="日线数据源：auto=AKShare 优先，失败后使用 Yahoo",
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
