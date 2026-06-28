"""
回测综合研究 (一次取数，四个角度切片)
================================================

一次回放历史涨停池 + 拉价格，落成"逐笔特征表"，再在内存里多维切片：
  ① 分周期：按当日"晋级率"把交易日分 强/中/弱，看买点信号在不同情绪周期的胜率差异。
  ② 横向比信号：buy_hint / 分歧 / 一致 / 龙头 / 全部涨停 的前向收益对比。
  ③ 调参：扫换手分歧阈值(high_turnover)，看 buy_hint 胜率随阈值变化（不重新取数，纯重算标签）。
输出供决定 ④（把结论接回实盘，如退潮期压制买点）。

用法：python backtest_study.py --days 45 --horizons 1,3,5 [--output trades.csv]
"""

from __future__ import annotations

import argparse
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from logger_config import get_logger
from backtest import SignalBacktest
from dragon_ladder import DragonLadder, _to_minutes

logger = get_logger(__name__)


def _div_tag(turnover, limit_count, seal, t_min, low_turn, high_turn,
             early=9 * 60 + 35, late=13 * 60):
    """按给定阈值重算 分歧/一致 标签 + buy_hint（用于参数扫描，不需重新取数）。"""
    is_early = t_min is not None and t_min <= early
    is_late = t_min is not None and t_min >= late
    if is_early and turnover < low_turn:
        tag = "一致"
    elif turnover >= high_turn or is_late:
        tag = "分歧"
    else:
        tag = "中性"
    buy = tag == "分歧" and limit_count >= 2 and seal >= 5e7
    return tag, buy


def _agg(xs: List[float]) -> Dict[str, object]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0, "win": None, "avg": None, "med": None}
    return {"n": len(xs), "win": round(sum(1 for v in xs if v > 0) / len(xs), 3),
            "avg": round(statistics.mean(xs), 2), "med": round(statistics.median(xs), 2)}


def collect(days: int, horizons: List[int], max_per_day: int = 20) -> pd.DataFrame:
    bt = SignalBacktest()
    ladder = bt.ladder
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days * 2 + max(horizons) + 25)
    tdays = bt.trading_days(start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d"))
    signal_days = tdays[-(days + max(horizons)): -max(horizons)]

    rows: List[Dict] = []
    prev_zt_count = None
    for di, d in enumerate(signal_days, 1):
        print(f"  进度 {di}/{len(signal_days)} {d} (已收集 {len(rows)} 笔)", flush=True)
        pool = bt.historical_zt_pool(d)
        if not pool:
            prev_zt_count = prev_zt_count  # 不更新
            continue
        # 当日"晋级率"代理：今日连板(>=2)数 / 昨日涨停总数（赚钱效应/周期强弱）
        cont = sum(1 for s in pool if int(s.get("limit_count", 1) or 1) >= 2)
        promo = (cont / prev_zt_count) if prev_zt_count else None
        prev_zt_count = len(pool)
        if promo is None:
            continue
        cycle = "强" if promo >= 0.4 else ("中" if promo >= 0.2 else "弱")

        sectors = ladder._build_sectors(pool)
        d_iso = pd.to_datetime(d).strftime("%Y-%m-%d")
        # 控成本：每日只取最强的 max_per_day 只（按连板高度→封单），避免逐股拉历史拖垮
        flat = [(it, sec["sector"]) for sec in sectors for it in sec["stocks"]]
        flat.sort(key=lambda x: (-x[0]["limit_count"], -x[0].get("seal_amount", 0)))
        for it, sec_name in flat[:max_per_day]:
            if True:
                pm = bt.price_map(it["code"], min_days=days * 2 + 40)
                if not pm:
                    continue
                dates = sorted(pm.keys())
                rets = {h: bt._forward_return(pm, dates, d_iso, h, True) for h in horizons}
                if all(v is None for v in rets.values()):
                    continue
                rows.append({
                    "date": d_iso, "code": it["code"], "name": it["name"],
                    "cycle": cycle, "promo": round(promo, 3),
                    "role": it["role"], "divergence": it["divergence"], "buy_hint": it["buy_hint"],
                    "turnover": it["turnover_rate"], "limit_count": it["limit_count"],
                    "seal": it.get("seal_amount", 0),
                    "t_min": _to_minutes(it["first_limit_time"]),
                    **{f"ret_{h}": rets[h] for h in horizons},
                })
    return pd.DataFrame(rows)


def report(df: pd.DataFrame, horizons: List[int]):
    if df.empty:
        print("无样本（可能取数失败或休市区间）")
        return

    print(f"\n总样本 {len(df)} 笔，覆盖 {df['date'].nunique()} 个交易日\n")

    print("=== ② 横向比信号（次日开盘买入）===")
    print(f"{'信号':<8}{'持有':>4}{'样本':>6}{'胜率':>8}{'平均%':>8}{'中位%':>8}")
    sig_masks = {
        "buy_hint": df["buy_hint"] == True,
        "分歧": df["divergence"] == "分歧",
        "一致": df["divergence"] == "一致",
        "龙头": df["role"] == "龙头",
        "全部涨停": df["code"].notna(),
    }
    for name, mask in sig_masks.items():
        for h in horizons:
            a = _agg(df.loc[mask, f"ret_{h}"].tolist())
            wr = f"{a['win']*100:.1f}%" if a["win"] is not None else "--"
            print(f"{name:<8}{h:>3}日{a['n']:>6}{wr:>8}{str(a['avg']):>8}{str(a['med']):>8}")
        print()

    print("=== ① 分周期 · buy_hint（持有3日）===")
    print(f"{'周期':<6}{'样本':>6}{'胜率':>8}{'平均%':>8}{'中位%':>8}")
    h = 3 if 3 in horizons else horizons[-1]
    bh = df[df["buy_hint"] == True]
    for cyc in ["强", "中", "弱"]:
        a = _agg(bh.loc[bh["cycle"] == cyc, f"ret_{h}"].tolist())
        wr = f"{a['win']*100:.1f}%" if a["win"] is not None else "--"
        print(f"{cyc:<6}{a['n']:>6}{wr:>8}{str(a['avg']):>8}{str(a['med']):>8}")
    print("（也看全部分歧的分周期）")
    dv = df[df["divergence"] == "分歧"]
    for cyc in ["强", "中", "弱"]:
        a = _agg(dv.loc[dv["cycle"] == cyc, f"ret_{h}"].tolist())
        wr = f"{a['win']*100:.1f}%" if a["win"] is not None else "--"
        print(f"分歧·{cyc:<3}{a['n']:>6}{wr:>8}{str(a['avg']):>8}{str(a['med']):>8}")

    print(f"\n=== ③ 调参 · 换手分歧阈值 high_turnover 扫描（buy_hint 持有{h}日）===")
    print(f"{'阈值%':>6}{'样本':>6}{'胜率':>8}{'平均%':>8}")
    for ht in [8, 10, 12, 15, 18, 22]:
        rets = []
        for _, r in df.iterrows():
            _, buy = _div_tag(r["turnover"], r["limit_count"], (r["seal"] or 0),
                              r["t_min"], low_turn=7.0, high_turn=ht)
            if buy and r.get(f"ret_{h}") is not None:
                rets.append(r[f"ret_{h}"])
        a = _agg(rets)
        wr = f"{a['win']*100:.1f}%" if a["win"] is not None else "--"
        print(f"{ht:>6}{a['n']:>6}{wr:>8}{str(a['avg']):>8}")


def main(argv=None):
    p = argparse.ArgumentParser(description="回测综合研究")
    p.add_argument("--days", type=int, default=45)
    p.add_argument("--horizons", default="1,3,5")
    p.add_argument("--output", default="")
    args = p.parse_args(argv)
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]

    print(f"采集数据中（近 {args.days} 个交易日，约需数分钟）...")
    df = collect(args.days, horizons)
    report(df, horizons)
    if args.output and not df.empty:
        df.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(f"\n逐笔记录已保存：{args.output}（{len(df)} 笔）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
