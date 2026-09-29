"""
A股选股筛选器
条件：均线多头排列 + MACD金叉 + 涨幅过滤 + 量比条件
每天收盘后运行，自动输出候选池

依赖：pip install akshare pandas ta tqdm
"""

import os
import sys
import threading
import time
import urllib.request

# ── 代理修复 ──────────────────────────────────────────────────
# 清除环境变量代理
for _proxy_key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                   "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"):
    os.environ.pop(_proxy_key, None)
# Windows注册表代理无法被env清理，直接monkey-patch让requests看不到任何代理
urllib.request.getproxies = lambda: {}
try:
    import urllib.request as _ur
    _ur.getproxies_environment = lambda: {}
    _ur.getproxies_registry = lambda: {}
except Exception:
    pass

# Windows GBK终端兼容：强制UTF-8输出，避免emoji编码错误
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import akshare as ak
import pandas as pd
import ta
from tqdm import tqdm
from datetime import datetime, timedelta
import warnings

from sina_spot_client import SinaSpotClient
warnings.filterwarnings("ignore")


class HistoryDataSourceError(RuntimeError):
    """历史行情源全部不可用，不能把它误判为股票未通过筛选。"""


def _history_backend():
    """延迟加载共用行情缓存，避免本脚本启动时产生额外网络操作。"""
    import wash_pattern_scanner
    return wash_pattern_scanner


HISTORY_SOURCE_ATTR = "data_source"
HISTORY_DATE_ATTR = "latest_data_date"
HISTORY_SCHEMA_ATTR = "history_schema_version"
HISTORY_TRUSTED_ATTR = "trusted_normalized_history"
HISTORY_SCHEMA_VERSION = 1

A_SHARE_PREFIXES = (
    "000", "001", "002", "003", "30",
    "600", "601", "603", "605", "688", "689",
    "4", "8", "92",
)
STAR_MARKET_PREFIXES = ("688", "689")

_STOCK_POOL_CACHE = {}
_STOCK_POOL_CACHE_LOCK = threading.Lock()
_HISTORY_CONFIG_CACHE = {}
_HISTORY_CONFIG_CACHE_LOCK = threading.Lock()
_SHARED_CACHE_DIRS = {}
_SHARED_CACHE_DIR_LOCK = threading.Lock()

# ============================================================
# 参数配置（可自由调整）
# ============================================================
CONFIG = {
    # 均线参数
    "ma_periods": [5, 10, 20, 30],         # 均线周期

    # 涨幅过滤（当日）
    "min_pct_change": -3.0,                 # 最小涨幅%（排除暴跌）
    "max_pct_change": 9.5,                  # 最大涨幅%（排除涨停追高）

    # 历史涨幅过滤（近N日总涨幅，防止追高）
    "recent_days": 20,                      # 近N日
    "max_recent_gain": 50.0,                # 近N日涨幅不超过X%

    # 量比条件
    "min_volume_ratio": 0.8,                # 最小量比（排除极度缩量）
    "max_volume_ratio": 5.0,                # 最大量比（排除异常炒作）

    # MACD参数
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,

    # 数据获取
    "history_days": 90,                     # 获取多少天历史数据用于计算
    "min_full_pool_size": 4000,             # 全市场列表低于该数量视为数据源残缺
    "require_beijing_pool": True,           # A股口径包含北交所
    "exclude_st": True,                     # 排除ST股票
    "exclude_kechuang": False,              # 是否排除科创板（688/689开头）
    "exclude_chuangye": False,              # 是否排除创业板（30开头，含300/301）

    # 输出
    "output_file": "候选股票池.csv",
    "top_n": 50,                            # 最多输出N只
}

# ============================================================
# 工具函数
# ============================================================

def _stock_pool_cache_key():
    """模块内股票池缓存键；过滤配置变化时不会误用旧列表。"""
    return (
        datetime.now().date().isoformat(),
        bool(CONFIG["exclude_st"]),
        bool(CONFIG["exclude_kechuang"]),
        bool(CONFIG["exclude_chuangye"]),
        bool(CONFIG.get("require_beijing_pool", True)),
    )


def clear_stock_pool_cache():
    """清空进程内股票池缓存，主要供手动强制刷新和测试使用。"""
    with _STOCK_POOL_CACHE_LOCK:
        _STOCK_POOL_CACHE.clear()


def _filter_stock_pool(df):
    """统一股票池范围；返回独立 DataFrame，避免调用方污染缓存。"""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(columns=["code", "name"])

    result = df.loc[:, ["code", "name"]].copy()
    result["code"] = (
        result["code"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    result["name"] = result["name"].fillna("").astype(str)

    if CONFIG["exclude_st"]:
        result = result[~result["name"].str.contains("ST|退", na=False, case=False)]
    if CONFIG["exclude_kechuang"]:
        result = result[~result["code"].str.startswith(STAR_MARKET_PREFIXES)]
    if CONFIG["exclude_chuangye"]:
        result = result[~result["code"].str.startswith("30")]

    result = result[result["code"].str.startswith(A_SHARE_PREFIXES)]
    return result.drop_duplicates("code").reset_index(drop=True)


def get_all_stocks(force_refresh=False):
    """获取A股股票列表；同一进程、同一天复用新浪列表。"""
    print("📋 获取股票列表...")

    cache_key = _stock_pool_cache_key()
    if not force_refresh:
        with _STOCK_POOL_CACHE_LOCK:
            cached = _STOCK_POOL_CACHE.get(cache_key)
            if cached is not None:
                result = cached.copy(deep=True)
                print(f"✅ 共 {len(result)} 只股票待筛选（股票池缓存）")
                return result

    def fetch_sina_market(node):
        """分页拉取新浪财经某市场的全部股票（统一走 SinaSpotClient）"""
        return SinaSpotClient().fetch_name_list(node)

    try:
        backend = _history_backend()
        shared_pool = backend.get_stock_pool("all_a", "auto")
        df = pd.DataFrame([
            {"code": stock.code, "name": stock.name}
            for stock in shared_pool
        ])
        if df.empty:
            raise RuntimeError("共用全A股票池为空")
    except Exception as shared_error:
        if CONFIG.get("require_beijing_pool", True):
            raise RuntimeError(
                f"无法获取包含北交所的全A股票池：{shared_error}"
            ) from shared_error
        try:
            sh_stocks = fetch_sina_market("sh_a")
            sz_stocks = fetch_sina_market("sz_a")
            all_records = sh_stocks + sz_stocks
            if not all_records:
                raise RuntimeError("新浪沪深股票列表为空")
            df = pd.DataFrame(all_records)
        except Exception as fallback_error:
            raise RuntimeError(
                "无法获取股票列表："
                f"共用股票池={shared_error}；新浪沪深={fallback_error}"
            ) from fallback_error

    df = _filter_stock_pool(df)
    with _STOCK_POOL_CACHE_LOCK:
        _STOCK_POOL_CACHE[cache_key] = df.copy(deep=True)
    print(f"✅ 共 {len(df)} 只股票待筛选")
    return df.copy(deep=True)


def _history_scan_config(workers=10):
    backend = _history_backend()
    key = (
        id(backend.ScanConfig),
        int(CONFIG["history_days"]),
        max(1, int(workers or 1)),
    )
    with _HISTORY_CONFIG_CACHE_LOCK:
        cached = _HISTORY_CONFIG_CACHE.get(key)
        if cached is None:
            cached = backend.ScanConfig(
                fetch_days=key[1],
                adjust="qfq",
                data_source="auto",
                workers=key[2],
            )
            _HISTORY_CONFIG_CACHE[key] = cached
        return cached


def _completed_history_frame(df, cfg):
    """Apply the shared end-of-day policy before any volume-based rule."""
    if not isinstance(df, pd.DataFrame):
        return df
    backend = _history_backend()
    completed_view = getattr(backend, "completed_history_view", None)
    if not callable(completed_view):
        return df
    completed = completed_view(df, cfg)
    completed.attrs.pop(HISTORY_DATE_ATTR, None)
    return _tag_history_frame(completed)


def _source_label(source):
    """把缓存中的机器标识转换为页面可读的数据源名称。"""
    labels = {
        "sina": "新浪",
        "sina_batch": "新浪批量行情",
        "akshare": "东方财富",
        "eastmoney": "东方财富",
        "cache": "本地历史缓存",
        "shared_cache": "共用行情缓存",
        "legacy_cache": "旧版历史缓存",
    }
    source = str(source or "").strip()
    return labels.get(source.lower(), source or "未知")


def _tag_history_frame(
    df,
    source=None,
    schema_version=None,
    trusted=None,
    stale_fallback=None,
):
    """在 DataFrame.attrs 中携带真实数据日期、来源和缓存契约。"""
    if not isinstance(df, pd.DataFrame):
        return df

    existing_source = df.attrs.get(HISTORY_SOURCE_ATTR)
    df.attrs[HISTORY_SOURCE_ATTR] = _source_label(source or existing_source)
    if "date" in df.columns and not df.empty and not df.attrs.get(HISTORY_DATE_ATTR):
        dates = df["date"]
        if pd.api.types.is_datetime64_any_dtype(dates) and dates.is_monotonic_increasing:
            latest = dates.iloc[-1]
        else:
            latest = pd.to_datetime(dates, errors="coerce").max()
        if not pd.isna(latest):
            df.attrs[HISTORY_DATE_ATTR] = pd.Timestamp(latest).date().isoformat()
    if schema_version is not None:
        df.attrs[HISTORY_SCHEMA_ATTR] = schema_version
    if trusted is not None:
        df.attrs[HISTORY_TRUSTED_ATTR] = bool(trusted)
    if stale_fallback is not None:
        df.attrs["stale_fallback"] = bool(stale_fallback)
    return df


def history_metadata(df):
    """返回候选记录可直接使用的真实行情元数据。"""
    if not isinstance(df, pd.DataFrame):
        return {"data_date": "", "data_source": "未知"}
    _tag_history_frame(df)
    return {
        "data_date": str(df.attrs.get(HISTORY_DATE_ATTR) or ""),
        "data_source": str(df.attrs.get(HISTORY_SOURCE_ATTR) or "未知"),
        "stale_fallback": bool(df.attrs.get("stale_fallback")),
    }


def _read_shared_cache_payload(code, cfg, fresh):
    """直接读取共用缓存及其 source 元数据，避免加载后再读第二遍。"""
    backend = _history_backend()
    cache_dir_loader = getattr(backend, "wash_ohlcv_cache_dir", None)
    if not callable(cache_dir_loader):
        return None

    try:
        cache_key = (id(backend), id(cache_dir_loader))
        cache_dir = _SHARED_CACHE_DIRS.get(cache_key)
        if cache_dir is None:
            with _SHARED_CACHE_DIR_LOCK:
                cache_dir = _SHARED_CACHE_DIRS.get(cache_key)
                if cache_dir is None:
                    cache_dir = cache_dir_loader()
                    _SHARED_CACHE_DIRS[cache_key] = cache_dir
        path = cache_dir / f"{code}.pkl"
        if not path.exists():
            return None
        payload = pd.read_pickle(path)
        if not isinstance(payload, dict):
            return None
        if payload.get("adjust") != cfg.adjust:
            return None

        if fresh:
            parse_as_of = getattr(backend, "parse_as_of_date")
            expected_as_of = parse_as_of(cfg).strftime("%Y-%m-%d")
            if payload.get("as_of") != expected_as_of:
                validation_check = getattr(
                    backend, "wash_cache_validation_is_fresh", None
                )
                if not callable(validation_check) or not validation_check(code, cfg):
                    return None
            fresh_validator = getattr(backend, "wash_cache_payload_is_fresh", None)
            if callable(fresh_validator):
                try:
                    payload_is_fresh = fresh_validator(payload, cfg, code=code)
                except TypeError:
                    payload_is_fresh = fresh_validator(payload, cfg)
                if not payload_is_fresh:
                    return None
            else:
                ttl = float(getattr(backend, "WASH_OHLCV_TTL_SEC", 4 * 60 * 60))
                if time.time() - float(payload.get("saved_at", 0)) > ttl:
                    return None

        frame_loader = getattr(backend, "wash_cache_frame_in_shares", None)
        frame = (
            frame_loader(payload)
            if callable(frame_loader)
            else payload.get("data")
        )
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        frame = _completed_history_frame(frame, cfg)
        if frame.empty:
            return None

        required = {"date", "open", "close", "high", "low", "volume"}
        quick_contract = (
            required.issubset(frame.columns)
            and ("pct_change" in frame.columns or "pct_chg" in frame.columns)
            and pd.api.types.is_datetime64_any_dtype(frame["date"])
            and frame["date"].is_monotonic_increasing
            and all(
                pd.api.types.is_numeric_dtype(frame[column])
                for column in required - {"date"}
            )
        )
        if quick_contract:
            minimum_rows = getattr(backend, "minimum_history_rows", lambda _cfg: 70)
            if len(frame) < int(minimum_rows(cfg)):
                return None
            latest = pd.Timestamp(frame["date"].iloc[-1]).date()
            as_of_date = getattr(backend, "parse_as_of_date")(cfg).date()
            age_days = (as_of_date - latest).days
            if age_days < 0 or age_days > int(getattr(cfg, "cache_max_stale_days", 10)):
                return None
        else:
            issue = getattr(backend, "history_data_issue", None)
            if callable(issue) and issue(frame, cfg):
                return None

        schema_version = (
            payload.get("history_schema_version")
            or payload.get("schema_version")
            or (HISTORY_SCHEMA_VERSION if quick_contract else None)
        )
        return _tag_history_frame(
            frame,
            source=payload.get("source") or "shared_cache",
            schema_version=schema_version,
            trusted=quick_contract,
            stale_fallback=not fresh,
        )
    except Exception:
        return None


def _load_shared_history_cache(code, cfg, fresh):
    """读取洗盘扫描器维护的批量行情缓存。"""
    backend = _history_backend()
    direct = _read_shared_cache_payload(code, cfg, fresh)
    if direct is not None:
        if not fresh:
            direct.attrs["stale_fallback"] = True
        return direct

    if fresh:
        cached = backend.load_wash_ohlcv_cache(code, cfg)
        if cached is not None:
            return _tag_history_frame(
                cached,
                source="shared_cache",
                schema_version=HISTORY_SCHEMA_VERSION,
                trusted=True,
                stale_fallback=False,
            )
        return None

    cached = backend.load_recent_wash_ohlcv_cache(code, cfg)
    if cached is not None:
        return _tag_history_frame(
            cached,
            source="shared_cache",
            schema_version=HISTORY_SCHEMA_VERSION,
            trusted=True,
            stale_fallback=True,
        )
    cached = backend.fetch_daily_cache(code, cfg)
    if cached is not None:
        return _tag_history_frame(
            cached,
            source="legacy_cache",
            trusted=False,
            stale_fallback=True,
        )
    return None


def _is_normalized_history_frame(raw):
    """检查共用缓存是否满足可跳过全量清洗的最小契约。"""
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return False
    required = ["date", "open", "close", "high", "low", "volume"]
    if any(column not in raw.columns for column in required):
        return False
    if "pct_change" not in raw.columns and "pct_chg" not in raw.columns:
        return False
    if not pd.api.types.is_datetime64_any_dtype(raw["date"]):
        return False
    if not raw["date"].is_monotonic_increasing or raw["date"].duplicated().any():
        return False
    if raw[required].isna().any().any():
        return False
    return all(pd.api.types.is_numeric_dtype(raw[column]) for column in required[1:])


def _normalize_history_frame(
    raw,
    source=None,
    trusted=False,
    volume_multiplier=1.0,
):
    """统一新浪/东方财富/共用缓存的字段，供筛选规则直接使用。"""
    if raw is None:
        return None
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return pd.DataFrame()

    source = source or raw.attrs.get(HISTORY_SOURCE_ATTR)
    schema_version = raw.attrs.get(HISTORY_SCHEMA_ATTR)
    trusted = bool(trusted or raw.attrs.get(HISTORY_TRUSTED_ATTR))

    has_trusted_contract = bool(
        raw.attrs.get(HISTORY_TRUSTED_ATTR)
        and raw.attrs.get(HISTORY_SCHEMA_ATTR) == HISTORY_SCHEMA_VERSION
    )
    if trusted and (has_trusted_contract or _is_normalized_history_frame(raw)):
        # 浅拷贝只复制 DataFrame 管理结构，不复制行情数组；同时避免修改调用方对象。
        df = raw.copy(deep=False)
        if "pct_change" not in df.columns:
            # 在轻量副本上增加别名，比 rename 整个 DataFrame 更轻。
            df["pct_change"] = df["pct_chg"]
        return _tag_history_frame(
            df,
            source=source or "shared_cache",
            schema_version=schema_version or HISTORY_SCHEMA_VERSION,
            trusted=True,
        )

    rename_columns = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
        "换手率": "turnover",
    }
    if "pct_change" not in raw.columns:
        rename_columns["pct_chg"] = "pct_change"
    df = raw.copy().rename(columns=rename_columns)
    if "pct_change" in df.columns and "pct_chg" in df.columns:
        df = df.drop(columns=["pct_chg"])
    required = ["date", "open", "close", "high", "low", "volume"]
    if any(column not in df.columns for column in required):
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in ("open", "close", "high", "low", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["volume"] = df["volume"] * float(volume_multiplier)
    df = (
        df.dropna(subset=required)
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    if "pct_change" in df.columns:
        df["pct_change"] = pd.to_numeric(df["pct_change"], errors="coerce")
        calculated = df["close"].pct_change() * 100
        df["pct_change"] = df["pct_change"].fillna(calculated)
    else:
        # 新浪日线没有涨跌幅字段，必须在日期排序后由收盘价计算。
        df["pct_change"] = df["close"].pct_change() * 100
    return _tag_history_frame(
        df,
        source=source,
        schema_version=HISTORY_SCHEMA_VERSION,
        trusted=True,
        stale_fallback=False,
    )


def _sina_symbol(code):
    if code.startswith(("4", "8", "9")):
        return f"bj{code}"
    return f"sh{code}" if code.startswith(("5", "6")) else f"sz{code}"


def get_stock_history(code):
    """获取单只股票历史数据：批量缓存 → 新浪 → 东方财富 → 近期缓存。"""
    end_date = datetime.today().strftime("%Y%m%d")
    start_date = (datetime.today() - timedelta(days=CONFIG["history_days"] + 60)).strftime("%Y%m%d")
    cfg = _history_scan_config()
    saw_short_history = False

    try:
        cached_raw = _load_shared_history_cache(code, cfg, fresh=True)
        cached = _normalize_history_frame(cached_raw, trusted=True)
        if cached is not None and len(cached) >= 35:
            return cached
        saw_short_history = cached is not None and not cached.empty
    except Exception:
        # 单个缓存损坏不应阻断在线数据源回退。
        pass

    errors = []
    live_sources = (
        (
            "新浪",
            lambda: ak.stock_zh_a_daily(
                symbol=_sina_symbol(code),
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            ),
            1.0,
        ),
        (
            "东方财富",
            lambda: ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            ),
            100.0,
        ),
    )
    for source_name, loader, volume_multiplier in live_sources:
        try:
            df = _normalize_history_frame(
                loader(),
                source=source_name,
                volume_multiplier=volume_multiplier,
            )
            df = _completed_history_frame(df, cfg)
            if df is not None and len(df) >= 35:
                return df
            if df is not None and not df.empty:
                saw_short_history = True
        except Exception as exc:
            message = str(exc).replace("\n", " ")
            errors.append(f"{source_name}: {message[:160]}")

    try:
        cached_raw = _load_shared_history_cache(code, cfg, fresh=False)
        cached = _normalize_history_frame(cached_raw, trusted=True)
        if cached is not None and len(cached) >= 35:
            return cached
        if cached is not None and not cached.empty:
            saw_short_history = True
    except Exception:
        pass

    # 新股确实可能少于 35 根日线，这是正常跳过；源全部报错则必须上抛，
    # 让扫描进度把它计为数据错误，而不是伪装成“不符合条件”。
    if saw_short_history:
        return None
    detail = "; ".join(errors) if errors else "所有数据源均未返回有效数据"
    raise HistoryDataSourceError(f"{code} 历史行情获取失败：{detail}")


def prepare_history_cache(stocks, workers=10):
    """用少量新浪批量报价更新共用日线缓存，主扫描随后只做本地计算。"""
    backend = _history_backend()
    stock_infos = []
    rows = stocks.iterrows() if hasattr(stocks, "iterrows") else enumerate(stocks)
    for _, row in rows:
        if isinstance(row, dict):
            code = row.get("code", "")
            name = row.get("name", "")
        else:
            code = row.get("code", "") if hasattr(row, "get") else ""
            name = row.get("name", "") if hasattr(row, "get") else ""
        raw_code = str(code).strip()
        if not raw_code:
            continue
        code = raw_code.split(".", 1)[0].zfill(6)
        stock_infos.append(backend.StockInfo(code=code, name=str(name or "")))

    cfg = _history_scan_config(workers=workers)
    prepared = backend.prepare_scan_cache(stock_infos, cfg)
    if not isinstance(prepared, dict):
        return prepared

    meta = dict(prepared)
    needs_full_fetch = int(meta.get("needs_full_fetch") or 0)
    covered = int(meta.get("prepared") or 0) + int(meta.get("reused") or 0)
    meta["cache_warm"] = (
        bool(stock_infos)
        and needs_full_fetch == 0
        and covered >= len(stock_infos)
    )
    # 本地 pickle + pandas 计算受 GIL 约束；全命中时单线程通常更快。
    meta["recommended_scan_workers"] = 1 if meta["cache_warm"] else max(1, int(workers or 1))
    return meta


def check_ma_alignment(df):
    """
    检查均线多头排列
    条件：MA5 > MA10 > MA20 > MA30，且股价位于 MA5 上方。

    这里不额外判断均线斜率；“多头排列”与“均线向上”不是同一条件。
    只计算每条均线的最后一个值，避免给每只股票写入四个完整临时列。
    """
    periods = CONFIG["ma_periods"]
    if not periods or not isinstance(df, pd.DataFrame) or "close" not in df.columns:
        return False, {}
    if len(df) < max(periods):
        return False, {}

    close = df["close"]
    ma_values = {
        period: close.rolling(period).mean().iloc[-1]
        for period in periods
    }
    if any(pd.isna(value) for value in ma_values.values()):
        return False, {}
    
    # 检查多头排列：MA5 > MA10 > MA20 > MA30
    for i in range(len(periods) - 1):
        if ma_values[periods[i]] <= ma_values[periods[i + 1]]:
            return False, {}
    
    # 股价在MA5上方
    first_period = periods[0]
    if close.iloc[-1] < ma_values[first_period]:
        return False, {}
    
    ma_data = {f"MA{p}": round(ma_values[p], 3) for p in periods}
    return True, ma_data


def check_macd_golden_cross(df):
    """
    检查MACD金叉
    条件：DIF上穿DEA（近3日内发生金叉），且MACD > 0 or 刚过零轴
    """
    macd = ta.trend.MACD(
        df["close"],
        window_fast=CONFIG["macd_fast"],
        window_slow=CONFIG["macd_slow"],
        window_sign=CONFIG["macd_signal"]
    )
    
    df["DIF"] = macd.macd()
    df["DEA"] = macd.macd_signal()
    df["MACD"] = macd.macd_diff() * 2  # 柱状图
    
    # 检查近3日是否发生金叉（DIF从下方穿越DEA）
    golden_cross = False
    for i in range(-3, 0):
        if (df["DIF"].iloc[i-1] < df["DEA"].iloc[i-1] and 
            df["DIF"].iloc[i] >= df["DEA"].iloc[i]):
            golden_cross = True
            break
    
    # 也接受DIF > DEA且两者都在上升（持续金叉状态）
    last = df.iloc[-1]
    dif_above_dea = last["DIF"] > last["DEA"]
    dif_positive = last["DIF"] > 0  # 零轴以上更强
    
    macd_data = {
        "DIF": round(last["DIF"], 3),
        "DEA": round(last["DEA"], 3),
        "MACD": round(last["MACD"], 3),
        "金叉": golden_cross
    }
    
    # 通过条件：近期金叉 OR (DIF>DEA且DIF>0)
    passed = golden_cross or (dif_above_dea and dif_positive)
    return passed, macd_data


def check_volume_ratio(df):
    """
    检查量比条件
    量比 = 当日成交量 / 近5日平均成交量
    """
    if len(df) < 6:
        return False, 0
    
    avg_vol_5 = df["volume"].iloc[-6:-1].mean()
    if avg_vol_5 == 0:
        return False, 0
    
    vol_ratio = df["volume"].iloc[-1] / avg_vol_5
    
    passed = CONFIG["min_volume_ratio"] <= vol_ratio <= CONFIG["max_volume_ratio"]
    return passed, round(vol_ratio, 2)


def check_price_change(df):
    """
    检查当日涨幅
    排除涨停追高、排除暴跌
    """
    last_pct = df["pct_change"].iloc[-1]
    passed = CONFIG["min_pct_change"] <= last_pct <= CONFIG["max_pct_change"]
    return passed, round(last_pct, 2)


def check_recent_gain(df):
    """
    检查近N日涨幅，防止追高
    """
    n = CONFIG["recent_days"]
    if len(df) < n:
        return True, 0  # 数据不足则放行
    
    price_n_days_ago = df["close"].iloc[-n]
    price_now = df["close"].iloc[-1]
    
    if price_n_days_ago == 0:
        return True, 0
    
    recent_gain = (price_now - price_n_days_ago) / price_n_days_ago * 100
    
    passed = recent_gain <= CONFIG["max_recent_gain"]
    return passed, round(recent_gain, 2)


def score_stock(ma_data, macd_data, vol_ratio, pct_change, recent_gain):
    """
    综合评分（0-100分）
    """
    score = 0
    
    # 均线发散程度（MA5和MA30差距越大越好，但不能过大）
    ma5 = ma_data.get("MA5", 0)
    ma30 = ma_data.get("MA30", 0)
    if ma30 > 0:
        spread = (ma5 - ma30) / ma30 * 100
        if 1 <= spread <= 15:
            score += 30
        elif spread < 1:
            score += 10  # 刚开始发散
        else:
            score += 20
    
    # MACD状态
    if macd_data.get("金叉"):
        score += 25  # 近期金叉加分
    if macd_data.get("DIF", 0) > 0:
        score += 15  # 零轴上方加分
    
    # 量比（1.2-2.5为最佳温和放量）
    if 1.2 <= vol_ratio <= 2.5:
        score += 20
    elif 0.8 <= vol_ratio < 1.2:
        score += 10
    else:
        score += 5
    
    # 当日涨幅（温和上涨最佳）
    if 1 <= pct_change <= 5:
        score += 10
    elif 0 <= pct_change < 1:
        score += 5
    
    return min(score, 100)


def evaluate_stock_history(code, name, df):
    """按低成本优先顺序筛选一只股票，并生成带数据血缘的候选记录。"""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None

    pct_ok, pct_change = check_price_change(df)
    if not pct_ok:
        return None

    recent_ok, recent_gain = check_recent_gain(df)
    if not recent_ok:
        return None

    # 量比只读取六个值，先于均线/MACD 可减少大量无效计算。
    vol_ok, vol_ratio = check_volume_ratio(df)
    if not vol_ok:
        return None

    ma_ok, ma_data = check_ma_alignment(df)
    if not ma_ok:
        return None

    macd_ok, macd_data = check_macd_golden_cross(df)
    if not macd_ok:
        return None

    score = score_stock(ma_data, macd_data, vol_ratio, pct_change, recent_gain)
    last = df.iloc[-1]
    metadata = history_metadata(df)
    return {
        "代码": str(code).zfill(6),
        "名称": str(name or ""),
        "现价": round(float(last["close"]), 2),
        "今日涨幅%": pct_change,
        f"近{CONFIG['recent_days']}日涨幅%": recent_gain,
        "量比": vol_ratio,
        "MA5": ma_data.get("MA5"),
        "MA10": ma_data.get("MA10"),
        "MA20": ma_data.get("MA20"),
        "MA30": ma_data.get("MA30"),
        "DIF": macd_data.get("DIF"),
        "DEA": macd_data.get("DEA"),
        "MACD": macd_data.get("MACD"),
        "近期金叉": "✅" if macd_data.get("金叉") else "—",
        "综合评分": score,
        "数据日期": metadata["data_date"],
        "数据源": metadata["data_source"],
    }


# ============================================================
# 主筛选逻辑
# ============================================================

def run_screener():
    print("\n" + "="*60)
    print(f"  A股选股筛选器  |  运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*60)
    
    stocks = get_all_stocks()
    print("\n⚡ 正在批量更新行情缓存...")
    try:
        prepare_meta = prepare_history_cache(stocks, workers=10)
        print(
            f"✅ 批量行情准备完成：更新 {prepare_meta.get('prepared', 0)} 只，"
            f"复用 {prepare_meta.get('reused', 0)} 只，"
            f"仍需逐股补取 {prepare_meta.get('needs_full_fetch', 0)} 只"
        )
    except Exception as exc:
        # 批量报价失败时仍可由 get_stock_history 逐股走新浪/东财回退。
        print(f"⚠️ 批量行情准备失败，改用逐股备用源：{exc}")
    candidates = []
    errors = 0
    no_data = 0
    
    print("\n🔍 开始逐股筛选...\n")
    
    for _, row in tqdm(stocks.iterrows(), total=len(stocks), desc="筛选进度"):
        code = row["code"]
        name = row["name"]
        
        try:
            df = get_stock_history(code)
            if df is None:
                no_data += 1
                continue
            candidate = evaluate_stock_history(code, name, df)
            if candidate is not None:
                candidates.append(candidate)
            
        except Exception as e:
            errors += 1
            continue
    
    # ============================================================
    # 输出结果
    # ============================================================
    
    valid_data = max(0, len(stocks) - errors - no_data)
    if len(stocks) and valid_data * 5 < len(stocks) * 4:
        raise RuntimeError(
            f"历史行情有效覆盖率过低（{valid_data}/{len(stocks)}，"
            f"错误 {errors}，无数据/历史不足 {no_data}），结果已作废"
        )

    if not candidates:
        print("\n❌ 今日没有符合条件的股票，市场可能整体偏弱。")
        return
    
    result_df = pd.DataFrame(candidates)
    result_df = result_df.sort_values("综合评分", ascending=False)
    result_df = result_df.reset_index(drop=True)
    result_df.index += 1
    display_df = result_df.head(CONFIG["top_n"])
    
    print(f"\n✅ 筛选完成！符合条件：{len(candidates)} 只，终端显示前 {len(display_df)} 只\n")
    print("=" * 60)
    
    # 终端输出
    display_cols = [
        "代码", "名称", "现价", "今日涨幅%",
        f"近{CONFIG['recent_days']}日涨幅%", "量比", "近期金叉",
        "综合评分", "数据日期", "数据源",
    ]
    print(display_df[display_cols].to_string())
    
    # 保存CSV
    output_path = CONFIG["output_file"]
    result_df.to_csv(output_path, index=True, encoding="utf-8-sig")
    print(f"\n💾 结果已保存至：{output_path}")
    print(f"⚠️  筛选出错股票数：{errors}（网络或数据问题，正常现象）")
    print("\n⚠️  本工具仅供技术分析参考，不构成投资建议。")
    
    return result_df


# ============================================================
# 筛选条件说明打印
# ============================================================

def print_config():
    print("\n📐 当前筛选条件：")
    print("  ✦ 均线多头排列：MA5 > MA10 > MA20 > MA30，股价在MA5上方（不额外判断斜率）")
    print(f"  ✦ MACD：近3日金叉 或 DIF>DEA且DIF>0（零轴上方）")
    print(f"  ✦ 今日涨幅：{CONFIG['min_pct_change']}% ~ {CONFIG['max_pct_change']}%（排除涨停追高）")
    print(f"  ✦ 近{CONFIG['recent_days']}日涨幅：不超过 {CONFIG['max_recent_gain']}%（防追高）")
    print(f"  ✦ 量比：{CONFIG['min_volume_ratio']} ~ {CONFIG['max_volume_ratio']}")
    print(f"  ✦ 排除ST：{'是' if CONFIG['exclude_st'] else '否'}")
    print(f"  ✦ 排除科创板：{'是' if CONFIG['exclude_kechuang'] else '否'}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    print_config()
    result = run_screener()
