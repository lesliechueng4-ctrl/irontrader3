"""
题材龙头梯队 (DragonLadder)
================================================

围绕"选最强龙头 / 买在分歧 / 卖在一致"的趋势打法，把平铺的涨停池整理成**结构**：

  ① 题材梯队榜：按题材分组，组内按 连板高度 → 封单 → 首封时间 排出龙头/龙二/龙三…，
     标注空间高度与"断层"（龙头与龙二的高度差≥2），题材按强度排序。
  ② 分歧 / 一致 标签：用 换手率 + 首封时间 + 连板数 给每只涨停打标签——
     一致(一字/秒板缩量，不追) / 分歧(高换手/盘中弱转强，关注接力买点) / 中性，
     并对"连板分歧且封单仍强"的票给出"弱转强买点"提示。
  ③ 晋级率 & 空间高度：用昨日涨停股今日表现算连板晋级率（赚钱效应命脉），叠加全场最高连板。
  ④ 卖在一致预警：盘面整体偏一致 + 高度高 + 晋级率高 ⇒ 周期亢奋、临近卖点。

设计：仅依赖现成数据（涨停池快照字段 + 昨日涨停今日表现），不做逐股拉历史；
所有外部取数包 try/except，失败降级而非中断。阈值集中在 LadderConfig 便于调参/回测。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from logger_config import get_logger

logger = get_logger(__name__)

try:
    import akshare as ak
except Exception as exc:  # pragma: no cover
    ak = None
    logger.warning(f"akshare 导入失败，DragonLadder 晋级率将不可用: {exc}")


@dataclass(frozen=True)
class LadderConfig:
    """题材梯队参数。"""

    # ---- 分歧/一致判定 ----
    low_turnover: float = 7.0       # 换手率低于此视为缩量(%)
    high_turnover: float = 12.0     # 换手率高于此视为高换手分歧(%)
    early_seal_min: int = 9 * 60 + 35   # 首封早于此(分钟)视为秒板/早盘抢筹
    late_seal_min: int = 13 * 60        # 首封晚于此(分钟)视为盘中/尾盘弱势

    # ---- 弱转强买点 ----
    buy_hint_min_seal: float = 5e7  # 连板分歧且封单≥此(元)给买点提示

    # ---- 梯队 ----
    gap_height: int = 2             # 龙头与龙二高度差≥此视为"断层"

    # ---- 晋级率 / 卖点 ----
    promotion_limit_pct: float = 9.5    # 今日涨跌幅≥此视为仍涨停(晋级)
    sell_warn_consensus_ratio: float = 0.5  # 一致占比≥此 + 高度高 → 卖点预警
    sell_warn_min_height: int = 4


def _to_minutes(t: object) -> Optional[int]:
    """把首封时间('09:33:03'/'0933'/'093303'/datetime) 解析为当日分钟数。失败返回 None。"""
    if t is None:
        return None
    s = str(t).strip()
    if not s or s in ("nan", "None", "NaT"):
        return None
    try:
        if ":" in s:
            parts = s.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 4:
            return int(digits[:2]) * 60 + int(digits[2:4])
    except Exception:
        return None
    return None


class DragonLadder:
    """题材龙头梯队引擎。"""

    def __init__(self, data_fetcher=None, config: Optional[LadderConfig] = None):
        self.config = config or LadderConfig()
        if data_fetcher is None:
            from data_fetcher import DataFetcher
            data_fetcher = DataFetcher()
        self.fetcher = data_fetcher
        self._cache: Optional[Dict[str, object]] = None
        self._cached_at: float = 0.0
        self.cache_ttl = 120  # 秒

    # ------------------------------------------------------------------
    # ② 分歧 / 一致
    # ------------------------------------------------------------------
    def classify_divergence(self, stock: Dict) -> Dict[str, object]:
        """返回 {'tag': 一致/分歧/中性, 'buy_hint': bool, 'reason': str}。"""
        cfg = self.config
        turnover = float(stock.get("turnover_rate", 0) or 0)
        limit_count = int(stock.get("limit_count", 1) or 1)
        seal = float(stock.get("seal_amount", 0) or 0)
        t = _to_minutes(stock.get("first_limit_time"))

        early = t is not None and t <= cfg.early_seal_min
        late = t is not None and t >= cfg.late_seal_min

        tag, reason = "中性", ""
        if early and turnover < cfg.low_turnover:
            tag = "一致"
            reason = "早盘秒封 + 缩量，情绪一致（接力性价比低）"
        elif turnover >= cfg.high_turnover or late:
            tag = "分歧"
            reason = ("高换手分歧" if turnover >= cfg.high_turnover else "盘中/尾盘弱势封板")
        else:
            reason = "换手适中"

        # 弱转强买点：连板 + 分歧 + 封单仍强
        buy_hint = bool(tag == "分歧" and limit_count >= 2 and seal >= cfg.buy_hint_min_seal)
        return {"tag": tag, "buy_hint": buy_hint, "reason": reason}

    # ------------------------------------------------------------------
    # ① 题材梯队
    # ------------------------------------------------------------------
    @staticmethod
    def _sort_key(s: Dict):
        # 连板高 → 封单大 → 首封早
        t = _to_minutes(s.get("first_limit_time"))
        return (
            -int(s.get("limit_count", 1) or 1),
            -float(s.get("seal_amount", 0) or 0),
            t if t is not None else 9999,
        )

    def _build_sectors(self, pool: List[Dict]) -> List[Dict]:
        groups: Dict[str, List[Dict]] = {}
        for s in pool:
            sector = (s.get("sector") or "其他").strip() or "其他"
            groups.setdefault(sector, []).append(s)

        roles = ["龙头", "龙二", "龙三"]
        sectors = []
        for sector, stocks in groups.items():
            ranked = sorted(stocks, key=self._sort_key)
            heights = [int(s.get("limit_count", 1) or 1) for s in ranked]
            max_height = max(heights) if heights else 1
            # 断层：龙头与龙二的高度差
            has_gap = len(ranked) >= 2 and (heights[0] - heights[1]) >= self.config.gap_height

            items = []
            for i, s in enumerate(ranked):
                div = self.classify_divergence(s)
                items.append({
                    "code": str(s.get("code", "")),
                    "name": s.get("name", ""),
                    "limit_count": int(s.get("limit_count", 1) or 1),
                    "seal_amount": float(s.get("seal_amount", 0) or 0),
                    "first_limit_time": str(s.get("first_limit_time", "") or ""),
                    "turnover_rate": round(float(s.get("turnover_rate", 0) or 0), 2),
                    "role": roles[i] if i < len(roles) else "梯队",
                    "divergence": div["tag"],
                    "buy_hint": div["buy_hint"],
                    "div_reason": div["reason"],
                })
            seal_sum = sum(it["seal_amount"] for it in items)
            sectors.append({
                "sector": sector,
                "count": len(items),
                "max_height": max_height,
                "has_gap": has_gap,
                "seal_sum": seal_sum,
                # 题材强度：空间高度为主，家数与封单为辅
                "strength": max_height * 100 + len(items) * 5 + seal_sum / 1e8,
                "stocks": items,
            })

        sectors.sort(key=lambda x: x["strength"], reverse=True)
        return sectors

    # ------------------------------------------------------------------
    # ③ 晋级率 & 空间高度
    # ------------------------------------------------------------------
    def _promotion(self) -> Dict[str, object]:
        """连板晋级率：昨日涨停股今日仍涨停的比例（赚钱效应）。"""
        result = {"rate": None, "promoted": 0, "total": 0}
        if ak is None:
            return result
        try:
            today = datetime.now().strftime("%Y%m%d")
            df = ak.stock_zt_pool_previous_em(date=today)
            if df is None or df.empty:
                return result
            import pandas as pd
            col = next((c for c in df.columns if "涨跌幅" in str(c) or "涨幅" in str(c)), None)
            if not col:
                return result
            chg = pd.to_numeric(df[col], errors="coerce").dropna()
            total = len(chg)
            promoted = int((chg >= self.config.promotion_limit_pct).sum())
            result.update(total=total, promoted=promoted,
                          rate=(promoted / total) if total > 0 else None)
        except Exception as exc:
            logger.warning(f"计算晋级率失败: {exc}")
        return result

    # ------------------------------------------------------------------
    # ④ 卖在一致预警
    # ------------------------------------------------------------------
    def _sell_warning(self, sectors: List[Dict], max_height: int) -> Optional[str]:
        cfg = self.config
        total = sum(s["count"] for s in sectors)
        if total == 0:
            return None
        consensus = sum(
            1 for s in sectors for it in s["stocks"] if it["divergence"] == "一致"
        )
        ratio = consensus / total if total else 0
        if ratio >= cfg.sell_warn_consensus_ratio and max_height >= cfg.sell_warn_min_height:
            return (f"盘面偏一致（{consensus}/{total} 缩量一致）且空间已达 {max_height} 板，"
                    f"情绪趋于亢奋——警惕一致见顶，持仓宜卖在一致、不追高。")
        return None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def build(self, force: bool = False) -> Dict[str, object]:
        now = time.time()
        if not force and self._cache is not None and (now - self._cached_at) < self.cache_ttl:
            return {**self._cache, "cached": True}

        try:
            pool = self.fetcher.get_limit_up_pool() or []
        except Exception as exc:
            logger.warning(f"获取涨停池失败: {exc}")
            pool = []
        if isinstance(pool, list):
            stocks = pool
        else:  # DataFrame
            try:
                stocks = pool.to_dict("records")
            except Exception:
                stocks = []

        sectors = self._build_sectors(stocks)
        max_height = max((s["max_height"] for s in sectors), default=0)
        promotion = self._promotion()
        sell_warning = self._sell_warning(sectors, max_height)

        # 周期定位（晋级率）：强/中/弱。阈值与回测分桶一致。
        pr = promotion["rate"]
        if pr is None:
            cycle = "未知"
        elif pr >= 0.4:
            cycle = "强"
        elif pr >= 0.2:
            cycle = "中"
        else:
            cycle = "弱"
        # 回测结论接回实盘：近20日(退潮样本)显示，弱周期里"分歧买点★"平均跑输
        # (-4.8%/胜率38%，各换手阈值均亏)，强势一致股反而占优。强周期样本不足，暂不背书。
        if cycle == "弱":
            signal_note = ("退潮/弱周期：回测显示『分歧买点★』平均跑输（近20日 -4.8%、胜率38%，"
                           "且各换手阈值均亏），强势一致股反而占优——买点★仅供参考，勿追分歧、宁做强转强。")
        elif cycle in ("中", "强"):
            signal_note = "周期回暖：可逐步启用分歧买点，但仍以题材龙头 + 强转强为先。"
        else:
            signal_note = ""

        # 全场分歧/一致汇总
        total = sum(s["count"] for s in sectors)
        consensus = sum(1 for s in sectors for it in s["stocks"] if it["divergence"] == "一致")
        divergent = sum(1 for s in sectors for it in s["stocks"] if it["divergence"] == "分歧")
        buy_hints = sum(1 for s in sectors for it in s["stocks"] if it["buy_hint"])

        result = {
            "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cached": False,
            "spirit": {
                "limit_up_total": total,
                "max_height": max_height,
                "sector_count": len(sectors),
                "cycle": cycle,
                "promotion_rate": promotion["rate"],
                "promotion_promoted": promotion["promoted"],
                "promotion_total": promotion["total"],
                "consensus_count": consensus,
                "divergent_count": divergent,
                "buy_hint_count": buy_hints,
                "buy_hint_reliable": cycle not in ("弱",),  # 弱周期买点不可靠（回测）
            },
            "signal_note": signal_note,
            "sell_warning": sell_warning,
            "sectors": sectors,
        }
        self._cache = result
        self._cached_at = now
        return result


if __name__ == "__main__":
    dl = DragonLadder()
    data = dl.build()
    sp = data["spirit"]
    print(f"=== 龙头梯队 @ {data['as_of']} ===")
    pr = sp["promotion_rate"]
    print(f"涨停 {sp['limit_up_total']} · 题材 {sp['sector_count']} · 空间高度 {sp['max_height']}板 · "
          f"晋级率 {f'{pr*100:.0f}%' if pr is not None else 'N/A'} "
          f"({sp['promotion_promoted']}/{sp['promotion_total']})")
    print(f"一致 {sp['consensus_count']} / 分歧 {sp['divergent_count']} / 买点 {sp['buy_hint_count']}")
    if data["sell_warning"]:
        print(f"⚠ 卖点预警：{data['sell_warning']}")
    for s in data["sectors"][:6]:
        gap = " [断层]" if s["has_gap"] else ""
        print(f"\n【{s['sector']}】{s['count']}只 最高{s['max_height']}板{gap}")
        for it in s["stocks"][:5]:
            bh = " ★买点" if it["buy_hint"] else ""
            print(f"  {it['role']:>3} {it['name']}({it['code']}) {it['limit_count']}板 "
                  f"换手{it['turnover_rate']}% [{it['divergence']}]{bh}")
