"""
全局市场情绪过滤器 (MarketEmotionFilter)
================================================

目的
----
在原有"技术指标买卖逻辑"之上叠加一层 **全局市场情绪闸门**，把主观盘面情绪
量化为 0~100 分，用于控制 IronTrader 的：
  1. 整体开仓权限（冰点/退潮期收紧甚至禁止开仓）；
  2. 单票/总仓位上限（高潮期放开、分歧期减半）。

情绪三维度
----------
  D1. 昨日涨停股今日平均收益率  —— 反映"连板接力/赚钱效应"
  D2. 趋势龙头池今日大面率      —— 近期涨幅前 N 且换手活跃的核心资产，
                                   今日跌幅 > 阈值(默认 7%) 的占比，反映"核心资产亏钱效应"
  D3. 市场总体跌停家数          —— 反映"系统性恐慌"

设计要点
--------
  * 所有外部数据访问均包裹 try-except，任一维度取数失败时降级为"中性分"，
    并在结果中标记 available=False、降低 confidence，绝不让单点故障阻断主流程。
  * 龙头池构建较重（需逐票拉历史算近期涨幅），故带 TTL 缓存；
    "今日大面率"则用实时快照即时计算，保证盘中时效性。
  * 评分阈值与权重全部集中在 EmotionConfig，便于回测调参，杜绝散落魔数。

依赖
----
  * akshare：涨停/跌停/全A快照数据源（与项目内 market_sentiment 复用同一批接口）。
  * 项目内 DataFetcher：复用其历史行情获取与缓存能力。
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from logger_config import get_logger
from market_clock import TZ as _MARKET_TZ
from market_clock import snapshot_is_final

logger = get_logger(__name__)

# akshare 为可选硬依赖：导入失败时整个过滤器走降级路径（返回中性分），而非崩溃。
try:
    import akshare as ak
except Exception as exc:  # pragma: no cover - 环境缺失时才触发
    ak = None
    logger.warning(f"akshare 导入失败，MarketEmotionFilter 将以降级模式运行: {exc}")


# ==========================================================================
# 配置：所有阈值/权重集中管理，便于回测与调参
# ==========================================================================
@dataclass(frozen=True)
class EmotionConfig:
    """市场情绪过滤器参数配置。"""

    # ---- 维度权重（三项之和应为 1.0）----
    weight_prev_zt: float = 0.40      # 连板接力情绪
    weight_blowup: float = 0.35       # 核心资产亏钱效应
    weight_limit_down: float = 0.25   # 系统性恐慌

    # ---- D1：昨日涨停今日平均收益率 → 子分 的线性映射区间(%) ----
    # 均收益 >= good 记 100 分；<= bad 记 0 分；其间线性。
    prev_zt_good_pct: float = 3.0
    prev_zt_bad_pct: float = -5.0

    # ---- D2：龙头池构建与大面率 ----
    leader_pool_size: int = 30          # 趋势龙头池容量（近期涨幅前 N）
    leader_lookback_days: int = 10       # "近期涨幅"回看交易日数
    leader_min_turnover: float = 3.0     # 换手活跃下限(%)
    leader_candidate_cap: int = 120      # 拉历史前先用当日涨幅截断的候选上限（控成本）
    leader_workers: int = 12             # 历史并发拉取线程数
    big_loss_pct: float = -7.0           # "大面"定义：今日涨跌幅 <= 此值
    blowup_bad_rate: float = 0.30        # 大面率 >= 此值记 0 分（满盘皆墨）

    # ---- D3：跌停家数 → 子分 的线性映射 ----
    limit_down_panic: int = 60           # 跌停家数 >= 此值记 0 分

    # ---- 缓存 TTL（秒）----
    spot_cache_ttl: int = 120            # 全A快照
    leader_pool_cache_ttl: int = 1800    # 龙头池成员（近期涨幅前N，盘中基本稳定）
    result_cache_ttl: int = 180          # 综合情绪结果整体缓存（避免每次请求都重新取数）

    # ---- 情绪等级阈值 ----
    level_high: int = 80     # >= 高潮
    level_diverge: int = 60  # >= 分歧
    level_ebb: int = 40      # >= 退潮，否则 冰点

    def validate(self) -> None:
        total = self.weight_prev_zt + self.weight_blowup + self.weight_limit_down
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"情绪维度权重之和必须为 1.0，当前为 {total:.3f}")


# ==========================================================================
# 维度评分结果（用于结构化输出与可解释性）
# ==========================================================================
@dataclass
class DimensionScore:
    """单个情绪维度的评分明细。"""

    name: str
    raw: Optional[float]      # 原始观测值（取数失败为 None）
    score: float              # 归一化后的 0~100 子分
    weight: float             # 该维度权重
    available: bool           # 数据是否成功获取
    desc: str = ""            # 人类可读说明

    @property
    def weighted(self) -> float:
        return round(self.score * self.weight, 2)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """将数值夹紧到 [low, high]。"""
    return max(low, min(high, value))


def _linear_map(value: float, v0: float, v100: float) -> float:
    """把 value 从区间 [v0->0分, v100->100分] 线性映射到 0~100（自动处理升/降序）。"""
    if v100 == v0:
        return 50.0
    return _clamp((value - v0) / (v100 - v0) * 100.0)


# ==========================================================================
# 主体：市场情绪过滤器
# ==========================================================================
class MarketEmotionFilter:
    """全局市场情绪过滤器。

    用法::

        flt = MarketEmotionFilter(data_fetcher)
        result = flt.calculate_emotion_score()
        print(result['score'], result['level'])
        print(result['position']['action'])
    """

    def __init__(self, data_fetcher=None, config: Optional[EmotionConfig] = None):
        self.config = config or EmotionConfig()
        self.config.validate()

        # 延迟导入，避免循环依赖；调用方也可注入已有实例以复用缓存。
        if data_fetcher is None:
            from data_fetcher import DataFetcher
            data_fetcher = DataFetcher()
        self.fetcher = data_fetcher

        # 内部缓存
        self._spot_cache: Optional[pd.DataFrame] = None
        self._spot_cached_at: float = 0.0          # 快照的取数时间（epoch 秒）
        self._spot_source: str = ""                # 新浪 / 东方财富 / 落盘快照（…）
        self._spot_stale: bool = False             # 重启后先顶上的落盘快照，还没刷新成当前数据
        self._spot_lock = threading.Lock()         # 单飞：同一时间只取一次快照
        self._spot_flag_lock = threading.Lock()
        self._spot_refreshing: bool = False
        self._trading_day = None                   # 可注入交易日判断（测试用），默认见 market_clock
        self._clock = time.time                    # 可注入时钟（测试用）
        self._leader_pool_cache: Optional[List[str]] = None
        self._leader_pool_cached_at: float = 0.0
        self._leader_metrics: Dict[str, Dict[str, Optional[float]]] = {}  # 龙头近期涨幅/昨日涨跌
        self._result_cache: Optional[Dict[str, object]] = None
        self._result_cached_at: float = 0.0

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------
    @staticmethod
    def _today_str() -> str:
        return datetime.now().strftime("%Y%m%d")

    def _data_as_of(self) -> str:
        """Best available market-data timestamp, separate from calculation time."""
        meta = getattr(self.fetcher, "limit_up_pool_meta", None) or {}
        value = str(meta.get("as_of") or "").strip()
        if value:
            return value
        snapshot_loader = getattr(self.fetcher, "load_zt_snapshot", None)
        if callable(snapshot_loader):
            try:
                snapshot = snapshot_loader()
                if snapshot:
                    return str(snapshot.get("as_of") or snapshot.get("date") or "").strip()
            except Exception:
                pass
        return ""

    SPOT_STALE_MAX = 1800  # 秒：快照源失败时，最多接受多旧的过期快照（大面率分钟级误差可接受）
    SPOT_COLUMNS = ("代码", "名称", "最新价", "涨跌幅", "换手率")  # 落盘只保留用得到的列

    def _get_spot_snapshot(self, force: bool = False) -> Optional[pd.DataFrame]:
        """获取全 A 快照（含 代码/名称/最新价/涨跌幅/换手率）。

        - 数据源：新浪全市场快照（直连、进程内共享）优先，失败退回东方财富；
        - 盘中按 spot_cache_ttl 刷新；午休、收盘后、节假日只要快照取于最近一次收盘之后就不再重拉；
        - 刚重启时先用落盘快照：收盘后取的直接当当前数据用；盘中 30 分钟内的先顶上
          （标"陈旧"，执行闸会暂停开仓）并在后台立刻刷新，请求不用等；
        - 取数失败退回 30 分钟内的旧快照（降级），彻底没有才返回 None。
        """
        now = self._clock()
        if not force and not self._spot_stale and self._spot_current(now):
            return self._spot_cache

        if not force and self._spot_cache is None:
            self._restore_spot_file()
            if self._spot_cache is not None:
                if self._spot_current(now):
                    logger.info(f"全A快照从落盘文件恢复（{self._spot_as_of()}，收盘后数据，直接使用）")
                    return self._spot_cache
                if (now - self._spot_cached_at) < self.SPOT_STALE_MAX:
                    logger.info(f"全A快照先用落盘文件（{self._spot_as_of()}），后台刷新")
                    self._spot_stale = True
                    self._refresh_spot_async()
                    return self._spot_cache

        if not force and self._spot_stale and self._spot_refreshing \
                and (now - self._spot_cached_at) < self.SPOT_STALE_MAX:
            return self._spot_cache  # 后台正在刷新：不让请求等

        df = self._fetch_spot_locked(force=force)
        if df is not None:
            return df

        # 降级：手里的过期快照好过没有
        if self._spot_cache is not None and (now - self._spot_cached_at) < self.SPOT_STALE_MAX:
            logger.info(f"全A快照降级：使用 {(now - self._spot_cached_at) / 60:.0f} 分钟前的旧快照")
            return self._spot_cache
        return None

    def _spot_current(self, now: float) -> bool:
        """手里的快照能否直接用：收盘后取的最终快照，或盘中 TTL 内。"""
        if self._spot_cache is None or self._spot_cached_at <= 0:
            return False
        fetched = datetime.fromtimestamp(self._spot_cached_at, _MARKET_TZ)
        if snapshot_is_final(fetched, datetime.fromtimestamp(now, _MARKET_TZ), self._trading_day):
            return True
        return (now - self._spot_cached_at) < self.config.spot_cache_ttl

    def _spot_as_of(self) -> str:
        if self._spot_cache is None or self._spot_cached_at <= 0:
            return ""
        return datetime.fromtimestamp(self._spot_cached_at, _MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S")

    def _fetch_spot_from_sources(self) -> Tuple[Optional[pd.DataFrame], str, Optional[float]]:
        """依次试新浪（经 DataFetcher 共享快照）、东方财富。返回 (快照, 来源, 取数时间)。"""
        getter = getattr(self.fetcher, "get_market_spot_frame", None)
        if callable(getter):
            try:
                df = getter(max_age=self.config.spot_cache_ttl)
                if df is not None and not df.empty:
                    fetched_at = None
                    raw = df.attrs.get("fetched_at") if hasattr(df, "attrs") else None
                    if raw:
                        try:
                            fetched_at = datetime.fromisoformat(str(raw)).timestamp()
                        except ValueError:
                            fetched_at = None
                    return df, "新浪", fetched_at
                logger.warning("新浪全市场快照为空")
            except Exception as exc:
                logger.warning(f"新浪全市场快照失败，改用东方财富: {exc}")
        if ak is not None:
            try:
                df = ak.stock_zh_a_spot_em()
                if df is not None and not df.empty:
                    return df, "东方财富", None
                logger.warning("全A快照为空")
            except Exception as exc:
                logger.warning(f"获取全A快照失败: {exc}")
        return None, "", None

    def _fetch_spot_locked(self, force: bool = False) -> Optional[pd.DataFrame]:
        """单飞取快照：别的线程正在取就等它的结果。成功时更新内存与落盘，失败返回 None。"""
        with self._spot_lock:
            now = self._clock()
            if not force and not self._spot_stale and self._spot_current(now):
                return self._spot_cache  # 等锁期间别的线程已取完
            started = self._clock()
            df, source, fetched_at = self._fetch_spot_from_sources()
            if df is None:
                return None
            self._spot_cache = df
            self._spot_cached_at = fetched_at or started
            self._spot_source = source
            self._spot_stale = False
            self._save_spot_file()
            return df

    def _refresh_spot_async(self) -> None:
        with self._spot_flag_lock:
            if self._spot_refreshing:
                return
            self._spot_refreshing = True

        def run():
            try:
                self._fetch_spot_locked(force=True)
            except Exception as exc:  # 后台刷新失败：保留落盘快照，下一次请求再试
                logger.warning(f"后台刷新全A快照失败: {exc}")
            finally:
                with self._spot_flag_lock:
                    self._spot_refreshing = False

        threading.Thread(target=run, daemon=True, name="emotion-spot-refresh").start()

    # ---- 快照落盘：重启后不用先等一遍全市场行情 ----

    def _spot_file(self) -> Optional[Path]:
        """只有真实 DataFetcher（带缓存目录）才落盘；测试里的假数据源不写文件。"""
        cache_dir = getattr(getattr(self.fetcher, "cache_manager", None), "cache_dir", None)
        return Path(cache_dir) / "emotion_spot.json" if cache_dir else None

    def _save_spot_file(self) -> None:
        path = self._spot_file()
        if path is None or self._spot_cache is None:
            return
        try:
            cols = {}
            for key in self.SPOT_COLUMNS:
                col = self._find_col(self._spot_cache, key)
                if col is not None:
                    cols[key] = col
            if "代码" not in cols or "涨跌幅" not in cols:
                return
            frame = self._spot_cache[list(cols.values())].copy()
            frame.columns = list(cols.keys())
            frame["代码"] = frame["代码"].astype(str).str.zfill(6)
            payload = {
                "ts": self._spot_cached_at,
                "source": self._spot_source,
                "columns": list(frame.columns),
                "rows": frame.astype(object).where(frame.notna(), None).values.tolist(),
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            logger.debug(f"全A快照落盘失败: {exc}")

    def _restore_spot_file(self) -> None:
        path = self._spot_file()
        if path is None or not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            frame = pd.DataFrame(payload["rows"], columns=payload["columns"])
            if frame.empty or "代码" not in frame.columns:
                return
            frame["代码"] = frame["代码"].astype(str).str.zfill(6)
            self._spot_cache = frame
            self._spot_cached_at = float(payload.get("ts") or 0)
            self._spot_source = f"落盘快照（{payload.get('source') or '未知来源'}）"
        except Exception as exc:
            logger.debug(f"读取全A快照落盘文件失败: {exc}")

    @staticmethod
    def _find_col(df: pd.DataFrame, *keywords: str) -> Optional[str]:
        """在 DataFrame 列名中模糊匹配第一个包含任一关键字的列名。"""
        for col in df.columns:
            text = str(col)
            if any(kw in text for kw in keywords):
                return col
        return None

    # ------------------------------------------------------------------
    # D1：昨日涨停股今日平均收益率（连板接力情绪）
    # ------------------------------------------------------------------
    def get_prev_limitup_detail(self) -> Dict[str, object]:
        """昨日涨停股今日表现明细。

        Returns: {
            'avg': float|None,     # 今日平均涨跌幅(%)
            'count': int,          # 昨日涨停股数
            'up_count': int,       # 今日上涨家数
            'down_count': int,     # 今日下跌家数
            'items': [             # 逐票明细（按今日涨跌幅降序）
                {'code', 'name', 'change', 'prev_limit'(可选连板数)}, ...
            ],
        }
        取数失败时 avg=None、items=[]。
        """
        empty = {'avg': None, 'count': 0, 'up_count': 0, 'down_count': 0, 'items': []}
        if ak is None:
            return empty
        try:
            df = ak.stock_zt_pool_previous_em(date=self._today_str())
            if df is None or df.empty:
                logger.info("昨日涨停池为空（可能为休市或数据延迟）")
                return empty
            change_col = self._find_col(df, "涨跌幅", "涨幅")
            if not change_col:
                logger.warning("昨日涨停池未找到涨跌幅列")
                return empty
            code_col = self._find_col(df, "代码")
            name_col = self._find_col(df, "名称")
            limit_col = self._find_col(df, "连板", "涨停统计")

            work = df.copy()
            work["_chg"] = pd.to_numeric(work[change_col], errors="coerce")
            work = work.dropna(subset=["_chg"])
            avg = float(work["_chg"].mean()) if not work.empty else None

            items = []
            for _, r in work.sort_values("_chg", ascending=False).iterrows():
                item = {
                    "code": str(r[code_col]).zfill(6) if code_col else "",
                    "name": str(r[name_col]) if name_col else "",
                    "change": round(float(r["_chg"]), 2),
                }
                if limit_col:
                    item["prev_limit"] = str(r[limit_col])
                items.append(item)

            return {
                "avg": avg,
                "count": len(work),
                "up_count": int((work["_chg"] > 0).sum()),
                "down_count": int((work["_chg"] < 0).sum()),
                "items": items,
            }
        except Exception as exc:
            logger.warning(f"获取昨日涨停今日表现失败: {exc}")
            return empty

    def get_prev_limitup_avg_return(self) -> Optional[float]:
        """昨日涨停股今日平均涨跌幅(%)。取数失败返回 None。（明细见 get_prev_limitup_detail）"""
        return self.get_prev_limitup_detail()["avg"]

    # ------------------------------------------------------------------
    # D2：趋势龙头池今日大面率（核心资产亏钱效应）
    # ------------------------------------------------------------------
    def _compute_leader_metrics(self, code: str) -> Optional[Dict[str, Optional[float]]]:
        """计算单只股票的趋势指标：
            recent_return —— 近 lookback 个交易日累计涨幅(%)，即入选龙头池的依据；
            prev_change   —— 最近一个已收盘交易日的单日涨跌幅(%)，即“昨日走势”。
        失败返回 None。
        """
        try:
            lookback = self.config.leader_lookback_days
            series = self._recent_closes(code, days=lookback + 12)
            if series is None:
                return None
            closes = pd.Series(series, dtype="float64").dropna().reset_index(drop=True)
            if len(closes) < lookback + 1:
                return None

            recent_return = None
            base = float(closes.iloc[-1 - lookback])
            last = float(closes.iloc[-1])
            if base > 0:
                recent_return = (last - base) / base * 100.0

            # “昨日”=最新交易日的前一交易日的单日涨跌。
            # 实时快照的“今日涨跌幅”在盘后/休市时等于历史最后一根K线(最新交易日)，
            # 因此“昨日”取倒数第2根相对第3根的涨跌（= 最新交易日的前一日），避免今/昨重复。
            prev_change = None
            if len(closes) >= 3:
                a = float(closes.iloc[-3])
                b = float(closes.iloc[-2])
                if a > 0:
                    prev_change = (b - a) / a * 100.0

            # 近 lookback+1 根收盘价序列，供前端画迷你走势(sparkline)
            spark = [round(float(x), 2) for x in closes.iloc[-(lookback + 1):].tolist()]

            return {"recent_return": recent_return, "prev_change": prev_change, "spark": spark}
        except Exception:
            return None

    def _recent_closes(self, code: str, days: int) -> Optional[List[float]]:
        """最近若干个已收盘交易日的收盘价（升序）。

        优先腾讯前复权日 K（直连、可并发，龙头池 100 多只票几秒拉完）；
        只取到"已收盘"的那一天（15:10 前不含当天），与原来新浪日 K 的口径一致。
        腾讯失败时退回 DataFetcher.get_stock_history（AKShare，较慢）。
        """
        client = getattr(self.fetcher, "source_client", None)
        if client is not None:
            try:
                from signal_journal import bars_complete_until, now_sh, tencent_bars

                until = bars_complete_until(now_sh()).isoformat()
                bars = tencent_bars(client, code, count=days + 2)
                closes = [float(b["close"]) for b in bars if str(b["date"]) <= until]
                if closes:
                    return closes[-days:]
            except Exception as exc:
                logger.debug(f"腾讯日K失败 {code}，改用 AKShare: {exc}")
        df = self.fetcher.get_stock_history(code, days=days)
        if df is None or "close" not in df.columns:
            return None
        return pd.to_numeric(df["close"], errors="coerce").dropna().tolist()

    def _build_leader_pool(self, force: bool = False) -> List[str]:
        """构建趋势龙头池：换手活跃 + 近期涨幅前 N。返回股票代码列表，带 TTL 缓存。

        步骤：
          1. 全A快照过滤（换手活跃、剔除 ST / 科创 / 北交 / 新股、价格有效）；
          2. 按当日涨幅降序截断候选（控制后续拉历史的成本）；
          3. 并发拉历史计算"近期涨幅"，取前 N 作为龙头池。
        任一步失败均返回当前能得到的结果（可能为空列表）。
        """
        now = time.time()
        if (
            not force
            and self._leader_pool_cache is not None
            and (now - self._leader_pool_cached_at) < self.config.leader_pool_cache_ttl
        ):
            return self._leader_pool_cache

        # 内存里没有（如刚重启）→ 先从落盘文件恢复：TTL 内直接用；
        # 过期也先装进内存，作为后续重建失败时的降级底座。
        if self._leader_pool_cache is None:
            saved = self._load_leader_pool_file()
            if saved and saved.get("leaders"):
                self._leader_pool_cache = [str(c) for c in saved["leaders"]]
                self._leader_metrics = saved.get("metrics") or {}
                self._leader_pool_cached_at = float(saved.get("ts", 0))
                if not force and (now - self._leader_pool_cached_at) < self.config.leader_pool_cache_ttl:
                    logger.info(f"龙头池从落盘文件恢复（{len(self._leader_pool_cache)} 只）")
                    return self._leader_pool_cache

        spot = self._get_spot_snapshot()
        if spot is None:
            return self._leader_pool_cache or []
        if self._spot_stale and self._leader_pool_cache:
            # 手里只有重启前的落盘快照：先沿用旧池子，等当前快照到了再重建，别用旧数据选新池子
            return self._leader_pool_cache

        try:
            code_col = self._find_col(spot, "代码")
            name_col = self._find_col(spot, "名称")
            change_col = self._find_col(spot, "涨跌幅")
            turnover_col = self._find_col(spot, "换手率")
            price_col = self._find_col(spot, "最新价")
            if not all([code_col, change_col, turnover_col]):
                logger.warning("快照缺少必要列，无法构建龙头池")
                return self._leader_pool_cache or []

            df = spot.copy()
            df["_code"] = df[code_col].astype(str).str.zfill(6)
            df["_chg"] = pd.to_numeric(df[change_col], errors="coerce")
            df["_turn"] = pd.to_numeric(df[turnover_col], errors="coerce")
            if name_col:
                df["_name"] = df[name_col].astype(str)
            else:
                df["_name"] = ""
            if price_col:
                df["_price"] = pd.to_numeric(df[price_col], errors="coerce")
            else:
                df["_price"] = 1.0

            cfg = self.config
            mask = (
                (df["_turn"] >= cfg.leader_min_turnover)
                & (df["_price"] > 0)
                & (~df["_name"].str.contains("ST", case=False, na=False))
                & (~df["_code"].str.startswith(("68", "8", "4", "9")))  # 剔除科创/北交
            )
            cand = df[mask].dropna(subset=["_chg", "_turn"])
            # 当日涨幅降序截断候选，降低拉历史成本
            cand = cand.sort_values("_chg", ascending=False).head(cfg.leader_candidate_cap)
            codes = cand["_code"].tolist()
            if not codes:
                return self._leader_pool_cache or []

            # 并发计算每只候选的趋势指标（近期涨幅 + 昨日涨跌）
            metrics: Dict[str, Dict[str, Optional[float]]] = {}
            workers = max(1, min(cfg.leader_workers, len(codes)))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(self._compute_leader_metrics, c): c for c in codes}
                for fut in as_completed(futures):
                    code = futures[fut]
                    try:
                        m = fut.result()
                    except Exception:
                        m = None
                    if m is not None and m.get("recent_return") is not None:
                        metrics[code] = m

            if not metrics:
                logger.warning("龙头池近期涨幅全部计算失败")
                return self._leader_pool_cache or []

            leaders = sorted(metrics, key=lambda c: metrics[c]["recent_return"], reverse=True)[: cfg.leader_pool_size]
            self._leader_pool_cache = leaders
            self._leader_metrics = {c: metrics[c] for c in leaders}  # 仅保留入选龙头的指标
            self._leader_pool_cached_at = now
            self._save_leader_pool_file()
            logger.info(f"龙头池构建完成，共 {len(leaders)} 只")
            return leaders
        except Exception as exc:
            logger.warning(f"构建龙头池失败: {exc}")
            return self._leader_pool_cache or []

    # ---- 龙头池落盘：重启/数据源故障时不丢池子（构建一次成本很高）----

    def _leader_pool_file(self) -> Path:
        cache_dir = getattr(getattr(self.fetcher, "cache_manager", None), "cache_dir", "cache")
        return Path(cache_dir) / "leader_pool.json"

    def _save_leader_pool_file(self):
        try:
            payload = {
                "date": self._today_str(), "ts": self._leader_pool_cached_at,
                "leaders": self._leader_pool_cache, "metrics": self._leader_metrics,
            }
            self._leader_pool_file().write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.debug(f"龙头池落盘失败: {exc}")

    def _load_leader_pool_file(self) -> Optional[Dict]:
        try:
            path = self._leader_pool_file()
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug(f"读取龙头池落盘文件失败: {exc}")
            return None

    def get_leader_blowup_rate(self) -> Dict[str, object]:
        """趋势龙头池今日"大面率"。

        Returns: {
            'rate': float|None,   # 大面率(0~1)，无龙头池时为 None
            'total': int,         # 龙头池股票数
            'blown': int,         # 今日跌幅 <= big_loss_pct 的数量
            'threshold_pct': float,
        }
        """
        cfg = self.config
        result = {"rate": None, "total": 0, "blown": 0, "threshold_pct": cfg.big_loss_pct, "items": []}

        leaders = self._build_leader_pool()
        if not leaders:
            return result

        # 今日涨跌来源：全A快照（含过期降级）→ 逐票实时行情兜底（新浪，走熔断器）。
        # 龙头池只有十余只，逐票成本可控——这条兜底专治东财快照单点故障。
        changes = self._leader_changes_from_spot(leaders)
        if changes is None:
            changes = self._leader_changes_realtime(leaders)
        if not changes:
            result["total"] = len(leaders)
            return result

        def _round(v):
            return round(float(v), 2) if v is not None else None

        changes.sort(key=lambda x: x[2])  # 按今日涨跌幅升序，最惨的在前
        items = []
        for code, name, chg in changes:
            m = self._leader_metrics.get(code, {})
            items.append({
                "code": code,
                "name": name,
                "change": round(chg, 2),                        # 今日
                "prev_change": _round(m.get("prev_change")),    # 昨日
                "recent_return": _round(m.get("recent_return")),# 近N日累计
                "spark": m.get("spark") or [],                  # 近N日收盘序列(迷你走势)
                "blown": bool(chg <= cfg.big_loss_pct),
            })
        total = len(changes)
        blown = sum(1 for _, _, chg in changes if chg <= cfg.big_loss_pct)
        result.update(total=total, blown=blown,
                      rate=(blown / total) if total > 0 else None, items=items)
        return result

    def _leader_changes_from_spot(self, leaders: List[str]) -> Optional[List[Tuple[str, str, float]]]:
        """从全A快照取龙头今日涨跌 [(code, name, chg)]。快照不可用返回 None（走兜底）。"""
        spot = self._get_spot_snapshot()
        if spot is None:
            return None
        try:
            code_col = self._find_col(spot, "代码")
            change_col = self._find_col(spot, "涨跌幅")
            name_col = self._find_col(spot, "名称")
            if not code_col or not change_col:
                return None
            snap = spot.copy()
            snap["_code"] = snap[code_col].astype(str).str.zfill(6)
            snap["_chg"] = pd.to_numeric(snap[change_col], errors="coerce")
            snap["_name"] = snap[name_col].astype(str) if name_col else ""
            sub = snap[snap["_code"].isin(set(leaders))].dropna(subset=["_chg"])
            return [(r["_code"], r["_name"], float(r["_chg"])) for _, r in sub.iterrows()]
        except Exception as exc:
            logger.warning(f"快照解析龙头涨跌失败: {exc}")
            return None

    def _leader_changes_realtime(self, leaders: List[str]) -> List[Tuple[str, str, float]]:
        """兜底：逐票实时行情取今日涨跌幅（多源+熔断，绕开东财快照单点）。"""
        out: List[Tuple[str, str, float]] = []
        fetch = getattr(self.fetcher, "get_stock_realtime", None)
        if not callable(fetch):
            return out
        for code in leaders:
            try:
                rt = fetch(code)
                if rt and not rt.get("error") and rt.get("current"):
                    out.append((str(code), str(rt.get("name", "")), float(rt.get("change_pct", 0))))
            except Exception:
                continue
        if out:
            logger.info(f"大面率降级：逐票实时兜底命中 {len(out)}/{len(leaders)}")
        return out

    # ------------------------------------------------------------------
    # D3：市场总体跌停家数（系统性恐慌）
    # ------------------------------------------------------------------
    def get_limit_down_count(self) -> Optional[int]:
        """全市场跌停家数。取数失败返回 None。"""
        if ak is None:
            return None
        try:
            df = ak.stock_zt_pool_dtgc_em(date=self._today_str())
            if df is not None:
                return int(len(df))
            return None
        except Exception as exc:
            logger.warning(f"获取跌停家数失败: {exc}")
            return None

    # ------------------------------------------------------------------
    # 子分计算
    # ------------------------------------------------------------------
    def _score_prev_return(self, raw: Optional[float]) -> DimensionScore:
        cfg = self.config
        if raw is None:
            return DimensionScore("prev_limitup_return", None, 50.0,
                                  cfg.weight_prev_zt, False, "昨日涨停今日表现取数失败，按中性处理")
        score = _linear_map(raw, cfg.prev_zt_bad_pct, cfg.prev_zt_good_pct)
        desc = f"昨日涨停股今日平均 {raw:+.2f}%（接力{'赚钱' if raw >= 0 else '亏钱'}）"
        return DimensionScore("prev_limitup_return", round(raw, 2), round(score, 1),
                              cfg.weight_prev_zt, True, desc)

    def _score_blowup(self, blowup: Dict[str, object]) -> DimensionScore:
        cfg = self.config
        rate = blowup.get("rate")
        if rate is None:
            return DimensionScore("leader_blowup_rate", None, 50.0,
                                  cfg.weight_blowup, False, "龙头池/大面率不可用，按中性处理")
        # 大面率越高分越低：0 → 100 分，blowup_bad_rate → 0 分
        score = _linear_map(float(rate), cfg.blowup_bad_rate, 0.0)
        desc = (f"龙头池 {blowup.get('total', 0)} 只，今日跌超 "
                f"{abs(cfg.big_loss_pct):.0f}% 共 {blowup.get('blown', 0)} 只，大面率 {rate*100:.1f}%")
        return DimensionScore("leader_blowup_rate", round(float(rate), 4), round(score, 1),
                              cfg.weight_blowup, True, desc)

    def _score_limit_down(self, raw: Optional[int]) -> DimensionScore:
        cfg = self.config
        if raw is None:
            return DimensionScore("limit_down_count", None, 50.0,
                                  cfg.weight_limit_down, False, "跌停家数取数失败，按中性处理")
        # 跌停越多分越低：0 → 100 分，panic → 0 分
        score = _linear_map(float(raw), float(cfg.limit_down_panic), 0.0)
        desc = f"全市场跌停 {raw} 家"
        return DimensionScore("limit_down_count", int(raw), round(score, 1),
                              cfg.weight_limit_down, True, desc)

    # ------------------------------------------------------------------
    # 综合情绪得分
    # ------------------------------------------------------------------
    def _level_of(self, score: float) -> str:
        cfg = self.config
        if score >= cfg.level_high:
            return "高潮"
        if score >= cfg.level_diverge:
            return "分歧"
        if score >= cfg.level_ebb:
            return "退潮"
        return "冰点"

    def calculate_emotion_score(self, force: bool = False) -> Dict[str, object]:
        """计算 0~100 综合市场情绪得分（带 TTL 缓存，避免每次请求都重新取数）。

        Args:
            force: True 时忽略缓存强制重算。

        Returns: {
            'score': int,          # 0~100 综合分
            'level': str,          # 高潮/分歧/退潮/冰点
            'confidence': float,   # 可用维度占比(0~1)，反映结果可信度
            'as_of': str,          # 计算时间
            'cached': bool,        # 本次是否命中缓存
            'dimensions': {name: {...}},   # 各维度明细（含逐票对比 items）
            'position': {...},     # 据综合分给出的仓位指令（便捷字段）
        }
        即使全部数据源失败，也会返回中性分 50，绝不抛出异常中断主流程。
        """
        now = time.time()
        if (
            not force
            and self._result_cache is not None
            and (now - self._result_cached_at) < self.config.result_cache_ttl
        ):
            return {**self._result_cache, "cached": True}

        # 取数（每个都已内部容错）
        prev = self.get_prev_limitup_detail()
        blowup = self.get_leader_blowup_rate()
        limit_down = self.get_limit_down_count()

        dims = [
            self._score_prev_return(prev["avg"]),
            self._score_blowup(blowup),
            self._score_limit_down(limit_down),
        ]

        # 加权汇总（权重和恒为 1.0，缺失维度以中性分 50 参与，不改变权重结构）
        total = int(_clamp(round(sum(d.weighted for d in dims))))
        available = sum(1 for d in dims if d.available)
        confidence = round(available / len(dims), 2)
        level = self._level_of(total)

        dimensions = {
            d.name: {
                "raw": d.raw,
                "score": d.score,
                "weight": round(d.weight, 3),
                "weighted": d.weighted,
                "available": d.available,
                "desc": d.desc,
            }
            for d in dims
        }
        # 附加逐票对比明细：完整列出昨日涨停股今日的全部上涨/下跌票，让用户看到全貌
        items = prev["items"]                          # 已按今日涨跌幅降序
        gainers = [it for it in items if it["change"] > 0]
        losers = [it for it in items if it["change"] < 0][::-1]   # 反转→跌幅最深在前
        dimensions["prev_limitup_return"].update({
            "count": prev["count"],
            "up_count": prev["up_count"],
            "down_count": prev["down_count"],
            "top_gainers": gainers,            # 今日全部上涨票（接力成功）
            "top_losers": losers,              # 今日全部下跌票（高位杀跌）
        })
        dimensions["leader_blowup_rate"].update({
            "total": blowup.get("total", 0),
            "blown": blowup.get("blown", 0),
            "items": blowup.get("items", []),  # 龙头池全部成员今日表现（按跌幅升序，最惨在前）
        })

        # 全维度失效（断网等）：不能拿中性50分照常发仓位指令——
        # 优先退回上一次成功结果（标 stale），实在没有则明确"数据不足"降级。
        if available == 0:
            if self._result_cache is not None and self._result_cache.get("confidence", 0) > 0:
                logger.warning("情绪数据源全部失效，退回上次结果（stale）")
                return {**self._result_cache, "cached": True, "stale": True}
            degraded = {
                "score": total,
                "level": level,
                "confidence": 0.0,
                "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data_as_of": self._data_as_of(),
                "cached": False,
                "degraded": True,
                "dimensions": dimensions,
                "position": {
                    "level": "未知", "action": "数据不足，维持现有仓位，勿按指令开新仓",
                    "max_total_position": 0.0, "max_single_position": 0.0,
                    "note": "全部数据源不可用，本指令为降级保护",
                },
            }
            # 不写入 result_cache，避免把降级结果当正常结果缓存 3 分钟
            return degraded

        result = {
            "score": total,
            "level": level,
            "confidence": confidence,
            "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_as_of": self._data_as_of(),
            "cached": False,
            "dimensions": dimensions,
            "position": PositionManager.decide(total),
            "spot_as_of": self._spot_as_of(),
            "spot_source": self._spot_source,
        }
        if self._spot_stale:
            # 重启后先顶上的落盘快照：如实标"陈旧"（执行闸会暂停开仓），也不进结果缓存，
            # 后台快照刷新完，下一次计算就是当前数据
            result["stale"] = True
            result["stale_reason"] = f"刚重启，先用 {self._spot_as_of()} 的落盘快照，正在刷新"
            return result
        self._result_cache = result
        self._result_cached_at = now
        return result


# ==========================================================================
# 仓位管理：得分区间 → 交易动作指令
# ==========================================================================
@dataclass(frozen=True)
class PositionBand:
    """一个情绪区间对应的仓位策略。"""

    level: str            # 区间名（高潮/分歧/退潮/冰点）
    min_score: int        # 区间下界（含）
    action: str           # 交易动作指令
    max_total_position: float   # 总仓位上限（0~1）
    max_single_position: float  # 单票仓位上限（0~1）
    note: str             # 说明


class PositionManager:
    """简单仓位映射：根据综合情绪得分返回开仓权限与仓位上限。

    示例::

        decision = PositionManager.decide(72)
        # {'level':'分歧','action':'半仓标准', 'max_total_position':0.5, ...}
    """

    # 区间按 min_score 降序定义，decide() 自上而下匹配第一个满足的区间。
    BANDS: List[PositionBand] = [
        PositionBand("高潮", 80, "满仓进攻", 1.0, 0.30,
                     "赚钱效应强、核心资产稳、恐慌低 —— 可放开仓位追主线"),
        PositionBand("分歧", 60, "半仓标准", 0.50, 0.20,
                     "多空分歧、接力一般 —— 半仓参与，控制单票暴露"),
        PositionBand("退潮", 40, "轻仓防守", 0.30, 0.10,
                     "核心资产杀跌、赚钱效应转差 —— 轻仓只做强势确认"),
        PositionBand("冰点", 0, "空仓观望", 0.0, 0.0,
                     "系统性恐慌、普跌 —— 禁止开仓，保留现金等待右侧"),
    ]

    @classmethod
    def get_band(cls, score: float) -> PositionBand:
        """返回得分所属的仓位区间。"""
        s = _clamp(float(score))
        for band in cls.BANDS:
            if s >= band.min_score:
                return band
        return cls.BANDS[-1]  # 理论不可达（冰点 min_score=0 兜底）

    @classmethod
    def decide(cls, score: float) -> Dict[str, object]:
        """根据综合情绪得分返回仓位指令字典。"""
        band = cls.get_band(score)
        return {
            "level": band.level,
            "action": band.action,
            "max_total_position": band.max_total_position,
            "max_single_position": band.max_single_position,
            "can_open": band.max_total_position > 0,
            "note": band.note,
        }

    @classmethod
    def cap_position(cls, score: float, intended_fraction: float) -> float:
        """将"意图仓位"按当前情绪的单票上限裁剪，返回实际允许的仓位比例。

        便于在下单前做一行式风控：actual = PositionManager.cap_position(score, 0.25)
        """
        band = cls.get_band(score)
        return round(max(0.0, min(intended_fraction, band.max_single_position)), 4)

    @classmethod
    def gate(cls, score: float, intended_single: float, is_open_signal: bool,
             downgrade_to: str) -> Dict[str, object]:
        """情绪闸：对一个"开仓信号"按当前市场情绪做实际约束。

        Args:
            score: 综合情绪得分(0~100)
            intended_single: 该信号原本意图的单票仓位比例(0~1)
            is_open_signal: 原决策是否为"开仓/买入"类信号
            downgrade_to: 冰点(禁止开仓)时，开仓信号应被下调到的目标决策值
                          （各引擎决策词不同，由调用方传入，如 '回避' / 'IGNORE'）

        Returns: {
            'emotion_score', 'emotion_level',
            'max_single_position',          # 当前情绪允许的单票上限
            'capped_single_position',       # intended 经上限裁剪后的实际值
            'can_open',                     # 当前情绪是否允许开仓
            'gated',                        # 信号是否因情绪被强制下调
            'final_signal',                 # 被下调后的目标决策（未下调则为 None）
            'note',
        }
        """
        band = cls.get_band(score)
        capped = cls.cap_position(score, intended_single)
        gated = bool(is_open_signal and band.max_total_position <= 0)
        return {
            'emotion_score': int(_clamp(float(score))),
            'emotion_level': band.level,
            'max_single_position': band.max_single_position,
            'capped_single_position': capped,
            'can_open': band.max_total_position > 0,
            'gated': gated,
            'final_signal': downgrade_to if gated else None,
            'note': band.note,
        }


# ==========================================================================
# 命令行自检 / 演示
# ==========================================================================
if __name__ == "__main__":
    print("=== MarketEmotionFilter 实盘自检 ===")
    flt = MarketEmotionFilter()
    result = flt.calculate_emotion_score()
    print(f"综合情绪得分: {result['score']}  等级: {result['level']}  可信度: {result['confidence']}")
    for name, d in result["dimensions"].items():
        flag = "" if d["available"] else "(降级)"
        print(f"  - {name}: 子分 {d['score']} 权重 {d['weight']} {flag}  {d['desc']}")
    pos = result["position"]
    print(f"仓位指令: 【{pos['level']}】{pos['action']} | 总仓位≤{pos['max_total_position']:.0%} "
          f"单票≤{pos['max_single_position']:.0%} | 可开仓: {pos['can_open']}")

    print("\n=== 仓位映射演示（得分 → 动作）===")
    for demo in (95, 72, 50, 20):
        d = PositionManager.decide(demo)
        print(f"  得分 {demo:>3} → 【{d['level']}】{d['action']}  "
              f"总仓位≤{d['max_total_position']:.0%} 单票≤{d['max_single_position']:.0%}")
