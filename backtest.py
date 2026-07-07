"""
信号回测框架 (SignalBacktest)
================================================

目的：把"分歧/一致、买点、龙头"这些**拍脑袋的标签**用历史数据验证——
回放历史每个交易日的涨停池，用 DragonLadder 做**点位时间(point-in-time)**分类，
再测量每个信号的**前向收益**（次日开盘买入 → 第 H 日收盘卖出），
统计 胜率 / 平均收益 / 中位数 / 分布，按 信号类型 × 持有天数 汇总。

关键正确性：
  * 信号只用当日快照字段（换手/连板/封单/首封），不含未来信息；
  * 前向收益用 D+1…D+H 的真实价格（这是被测的“结果/标签”，非穿越）；
  * 默认剔除"次日一字/接近涨停开盘买不进"的不可成交样本，使结果更诚实。

定位：研究/CLI 工具（较重，逐日拉涨停池 + 逐股拉历史），不挂 Web 请求。
    python backtest.py --days 20 --signal buy_hint --horizons 1,3,5
"""

from __future__ import annotations

import argparse
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from logger_config import get_logger

logger = get_logger(__name__)

try:
    import akshare as ak
except Exception as exc:  # pragma: no cover
    ak = None
    logger.warning(f"akshare 导入失败，回测不可用: {exc}")


# 历史涨停池(ak.stock_zt_pool_em) 列名 → DragonLadder 所需字段
_ZT_COLMAP = {
    "code": ("代码",),
    "name": ("名称",),
    "sector": ("所属行业", "行业"),
    "limit_count": ("连板数",),
    "seal_amount": ("封板资金", "封单资金"),
    "first_limit_time": ("首次封板时间", "首次涨停时间"),
    "turnover_rate": ("换手率",),
    "break_count": ("炸板次数",),
}


def _pick(row, names, default=None):
    for n in names:
        if n in row and pd.notna(row[n]):
            return row[n]
    return default


class SignalBacktest:
    """涨停池信号前向收益回测。"""

    __test__ = False  # 防止 pytest 因 *Test 命名规则误把本类当测试类收集

    def __init__(self, data_fetcher=None, ladder=None):
        if data_fetcher is None:
            from data_fetcher import DataFetcher
            data_fetcher = DataFetcher()
        self.fetcher = data_fetcher
        if ladder is None:
            from dragon_ladder import DragonLadder
            ladder = DragonLadder(data_fetcher)
        self.ladder = ladder
        self._price_cache: Dict[str, Optional[pd.DataFrame]] = {}

    # ------------------------------------------------------------------
    # 数据：历史涨停池 / 交易日 / 个股价格
    # ------------------------------------------------------------------
    def historical_zt_pool(self, date_str: str) -> List[Dict]:
        """取某交易日(YYYYMMDD)的涨停池，映射为 DragonLadder 字段。失败/休市返回 []。"""
        if ak is None:
            return []
        try:
            df = ak.stock_zt_pool_em(date=date_str)
            if df is None or df.empty:
                return []
            out = []
            for _, row in df.iterrows():
                out.append({
                    "code": str(_pick(row, _ZT_COLMAP["code"], "")).zfill(6),
                    "name": str(_pick(row, _ZT_COLMAP["name"], "")),
                    "sector": str(_pick(row, _ZT_COLMAP["sector"], "其他")),
                    "limit_count": int(_pick(row, _ZT_COLMAP["limit_count"], 1) or 1),
                    "seal_amount": float(_pick(row, _ZT_COLMAP["seal_amount"], 0) or 0),
                    "first_limit_time": str(_pick(row, _ZT_COLMAP["first_limit_time"], "")),
                    "turnover_rate": float(_pick(row, _ZT_COLMAP["turnover_rate"], 0) or 0),
                    "break_count": int(_pick(row, _ZT_COLMAP["break_count"], 0) or 0),
                })
            return out
        except Exception as exc:
            logger.warning(f"取 {date_str} 涨停池失败: {exc}")
            return []

    def trading_days(self, start: str, end: str) -> List[str]:
        """[start,end] 间的交易日列表(YYYYMMDD)。优先用交易日历，失败则回退按周一~周五。"""
        if ak is not None:
            try:
                cal = ak.tool_trade_date_hist_sina()
                d = pd.to_datetime(cal["trade_date"])
                s, e = pd.to_datetime(start), pd.to_datetime(end)
                days = d[(d >= s) & (d <= e)]
                return [x.strftime("%Y%m%d") for x in days]
            except Exception as exc:
                logger.warning(f"取交易日历失败，回退工作日: {exc}")
        out, cur, e = [], pd.to_datetime(start), pd.to_datetime(end)
        while cur <= e:
            if cur.weekday() < 5:
                out.append(cur.strftime("%Y%m%d"))
            cur += timedelta(days=1)
        return out

    def price_map(self, code: str, min_days: int) -> Optional[Dict[str, Dict[str, float]]]:
        """返回 {‘YYYY-MM-DD’: {open, close}} 及有序日期，用于按日期查前向收益。"""
        if code in self._price_cache:
            df = self._price_cache[code]
        else:
            try:
                df = self.fetcher.get_stock_history(code, days=max(min_days, 60))
            except Exception:
                df = None
            self._price_cache[code] = df
        if df is None or df.empty or "close" not in df.columns or "date" not in df.columns:
            return None
        m = {}
        for _, r in df.iterrows():
            try:
                key = pd.to_datetime(r["date"]).strftime("%Y-%m-%d")
                m[key] = {"open": float(r.get("open", r["close"])), "close": float(r["close"])}
            except Exception:
                continue
        return m

    # ------------------------------------------------------------------
    # 信号选择
    # ------------------------------------------------------------------
    def select_signals(self, pool: List[Dict], signal: str) -> List[Dict]:
        """按信号类型从当日涨停池里挑出标的（用 DragonLadder 做点位时间分类）。"""
        sectors = self.ladder._build_sectors(pool)
        picked = []
        for sec in sectors:
            for it in sec["stocks"]:
                if signal == "all_zt":
                    ok = True
                elif signal == "buy_hint":
                    ok = it["buy_hint"]
                elif signal == "divergent":
                    ok = it["divergence"] == "分歧"
                elif signal == "consensus":
                    ok = it["divergence"] == "一致"
                elif signal == "leader":
                    ok = it["role"] == "龙头"
                else:
                    ok = False
                if ok:
                    picked.append({**it, "sector": sec["sector"]})
        return picked

    # ------------------------------------------------------------------
    # 前向收益
    # ------------------------------------------------------------------
    @staticmethod
    def _forward_return(pm: Dict[str, Dict[str, float]], dates: List[str],
                        signal_date: str, horizon: int,
                        exclude_unbuyable: bool) -> Optional[float]:
        """次日开盘买入 → 第 horizon 日收盘卖出 的收益率(%)。不可成交/数据不足返回 None。"""
        if signal_date not in pm:
            return None
        i = dates.index(signal_date)
        entry_i, exit_i = i + 1, i + horizon
        if exit_i >= len(dates):
            return None
        entry = pm[dates[entry_i]]["open"]
        sig_close = pm[signal_date]["close"]
        if entry <= 0 or sig_close <= 0:
            return None
        # 次日近涨停开盘视为买不进，剔除（更诚实）
        if exclude_unbuyable and (entry / sig_close - 1.0) >= 0.097:
            return None
        exit_close = pm[dates[exit_i]]["close"]
        return (exit_close - entry) / entry * 100.0

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, days: int = 20, signal: str = "buy_hint",
            horizons: Optional[List[int]] = None, max_per_day: int = 40,
            exclude_unbuyable: bool = True, end: Optional[str] = None) -> Dict[str, object]:
        horizons = horizons or [1, 3, 5]
        end_dt = pd.to_datetime(end) if end else datetime.now()
        # 多取一些日历天，保证覆盖到 days 个交易日 + 前向窗口
        start_dt = end_dt - timedelta(days=days * 2 + max(horizons) + 20)
        tdays = self.trading_days(start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d"))
        # 末尾要留出 max(horizons) 个交易日做卖出，信号日只取倒数 horizon 之前
        signal_days = tdays[-(days + max(horizons)): -max(horizons)] if len(tdays) > days + max(horizons) else tdays[:-max(horizons)]

        trades: List[Dict] = []
        for d in signal_days:
            pool = self.historical_zt_pool(d)
            if not pool:
                continue
            picks = self.select_signals(pool, signal)[:max_per_day]
            d_iso = pd.to_datetime(d).strftime("%Y-%m-%d")
            for st in picks:
                pm = self.price_map(st["code"], min_days=days * 2 + 40)
                if not pm:
                    continue
                dates = sorted(pm.keys())
                rets = {h: self._forward_return(pm, dates, d_iso, h, exclude_unbuyable) for h in horizons}
                if all(v is None for v in rets.values()):
                    continue
                trades.append({
                    "date": d_iso, "code": st["code"], "name": st["name"],
                    "sector": st.get("sector", ""), "limit_count": st["limit_count"],
                    "turnover_rate": st["turnover_rate"], "divergence": st["divergence"],
                    **{f"ret_{h}": (round(rets[h], 2) if rets[h] is not None else None) for h in horizons},
                })

        return {
            "params": {"days": days, "signal": signal, "horizons": horizons,
                       "max_per_day": max_per_day, "exclude_unbuyable": exclude_unbuyable,
                       "signal_days": len(signal_days)},
            "horizons": {str(h): self._aggregate([t.get(f"ret_{h}") for t in trades]) for h in horizons},
            "trades": trades,
        }

    @staticmethod
    def _aggregate(vals: List[Optional[float]]) -> Dict[str, object]:
        xs = [v for v in vals if v is not None]
        if not xs:
            return {"n": 0, "win_rate": None, "avg": None, "median": None, "best": None, "worst": None}
        wins = sum(1 for v in xs if v > 0)
        return {
            "n": len(xs),
            "win_rate": round(wins / len(xs), 3),
            "avg": round(statistics.mean(xs), 2),
            "median": round(statistics.median(xs), 2),
            "best": round(max(xs), 2),
            "worst": round(min(xs), 2),
        }


def main(argv=None):
    p = argparse.ArgumentParser(description="涨停池信号前向收益回测")
    p.add_argument("--days", type=int, default=20, help="回测的信号交易日数")
    p.add_argument("--signal", default="buy_hint",
                   choices=["buy_hint", "divergent", "consensus", "leader", "all_zt"])
    p.add_argument("--horizons", default="1,3,5", help="持有天数，逗号分隔")
    p.add_argument("--max-per-day", type=int, default=40)
    p.add_argument("--include-unbuyable", action="store_true", help="不剔除次日一字买不进的样本")
    p.add_argument("--output", default="", help="可选：把逐笔记录保存为 CSV")
    args = p.parse_args(argv)

    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    bt = SignalBacktest()
    res = bt.run(days=args.days, signal=args.signal, horizons=horizons,
                 max_per_day=args.max_per_day, exclude_unbuyable=not args.include_unbuyable)

    pa = res["params"]
    print(f"=== 回测 [{args.signal}] 近 {pa['days']} 个交易日 · 次日开盘买入 ===")
    print(f"{'持有':>4} {'样本':>5} {'胜率':>7} {'平均%':>8} {'中位%':>8} {'最好%':>8} {'最差%':>8}")
    for h in horizons:
        a = res["horizons"][str(h)]
        if a["n"] == 0:
            print(f"{h:>3}日 {'0':>5}  (无样本)")
            continue
        print(f"{h:>3}日 {a['n']:>5} {a['win_rate']*100:>6.1f}% {a['avg']:>8} {a['median']:>8} {a['best']:>8} {a['worst']:>8}")

    if args.output and res["trades"]:
        pd.DataFrame(res["trades"]).to_csv(args.output, index=False, encoding="utf-8-sig")
        print(f"\n逐笔记录已保存：{args.output}（{len(res['trades'])} 笔）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
