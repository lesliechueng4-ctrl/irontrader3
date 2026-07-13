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
import json
import os
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


def _cycle_bucket(rate: Optional[float]) -> Optional[str]:
    """晋级率 → 强/中/弱 分档（与 dragon_ladder 实盘阈值一致）。"""
    if rate is None:
        return None
    return "强" if rate >= 0.4 else ("中" if rate >= 0.2 else "弱")


def _real_promotion(date_str: str, limit_pct: float = 9.5) -> Optional[float]:
    """实盘口径晋级率：昨日涨停股今日仍涨停比例（与 dragon_ladder._promotion 同源同算法）。

    回测样本同时保存代理口径(promo)与实盘口径(promo_real)，用于校准两套周期分档。
    """
    try:
        import akshare as ak
        df = ak.stock_zt_pool_previous_em(date=date_str)
        if df is None or df.empty:
            return None
        col = next((c for c in df.columns if "涨跌幅" in str(c) or "涨幅" in str(c)), None)
        if not col:
            return None
        chg = pd.to_numeric(df[col], errors="coerce").dropna()
        if not len(chg):
            return None
        return round(float((chg >= limit_pct).mean()), 3)
    except Exception as exc:
        logger.debug(f"取 {date_str} 实盘晋级率失败: {exc}")
        return None


def _agg(xs: List[float]) -> Dict[str, object]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0, "win": None, "avg": None, "med": None}
    return {"n": len(xs), "win": round(sum(1 for v in xs if v > 0) / len(xs), 3),
            "avg": round(statistics.mean(xs), 2), "med": round(statistics.median(xs), 2)}


def collect(days: int, horizons: List[int], max_per_day: int = 20, progress_cb=None) -> pd.DataFrame:
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
        if progress_cb:
            try:
                progress_cb(di, len(signal_days), len(rows))
            except Exception:
                pass
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
        promo_real = _real_promotion(d)   # 实盘口径，用于两套周期分档的对照校准

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
                    "promo_real": promo_real,
                    "cycle_real": _cycle_bucket(promo_real),
                    "role": it["role"], "divergence": it["divergence"], "buy_hint": it["buy_hint"],
                    "turnover": it["turnover_rate"], "limit_count": it["limit_count"],
                    "seal": it.get("seal_amount", 0),
                    "break_count": int(it.get("break_count", 0) or 0),
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

    if "promo_real" in df.columns:
        sub = df.dropna(subset=["promo", "promo_real"]).drop_duplicates("date")
        if len(sub):
            agree = float((sub["promo"].map(_cycle_bucket) == sub["promo_real"].map(_cycle_bucket)).mean())
            print("\n=== ①b 周期口径校准 ===")
            print(f"覆盖 {len(sub)} 日：代理口径(今连板/昨涨停) vs 实盘口径(昨涨停今仍板) "
                  f"强/中/弱同档率 {agree * 100:.0f}%")

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

    # 连板股次日开盘滑点不小：扣掉往返冲击+费用后结论是否翻转，决定实盘能否吃到回测收益
    print(f"\n=== ④ 成本敏感性 · buy_hint（持有{h}日，扣往返冲击+费用）===")
    print(f"{'成本%':>6}{'样本':>6}{'胜率':>8}{'平均%':>8}")
    bh_rets = bh[f"ret_{h}"].dropna().tolist()
    for cost in (0.0, 0.3, 0.5):
        a = _agg([r - cost for r in bh_rets])
        wr = f"{a['win']*100:.1f}%" if a["win"] is not None else "--"
        print(f"{cost:>6}{a['n']:>6}{wr:>8}{str(a['avg']):>8}")


def _pct(w) -> str:
    return f"{w * 100:.0f}%" if w is not None else "--"


def summarize(df: Optional[pd.DataFrame], horizons: List[int]) -> Dict[str, object]:
    """把样本库压成一段可直接显示的结论（供前端"重新回测"按钮渲染）。"""
    if df is None or df.empty:
        return {"total": 0, "days": 0, "h": None, "cross": [], "cycles": {},
                "conclusion": "样本库为空（取数失败或休市区间）"}
    df = df.copy()
    if "buy_hint" in df.columns and df["buy_hint"].dtype == object:
        df["buy_hint"] = df["buy_hint"].astype(str).str.lower().isin(["true", "1", "1.0"])

    h = 3 if 3 in horizons else horizons[-1]
    col = f"ret_{h}"
    masks = {
        "买点★": df["buy_hint"] == True,
        "分歧": df["divergence"] == "分歧",
        "一致": df["divergence"] == "一致",
        "龙头": df["role"] == "龙头",
        "全部涨停": df["code"].notna(),
    }
    cross = []
    for name, mask in masks.items():
        a = _agg(df.loc[mask, col].tolist()) if col in df.columns else _agg([])
        cross.append({"signal": name, "n": a["n"], "win": a["win"], "avg": a["avg"], "med": a["med"]})

    cycles = {}
    bh = df[df["buy_hint"] == True]
    for cyc in ["强", "中", "弱"]:
        a = _agg(bh.loc[bh["cycle"] == cyc, col].tolist()) if col in bh.columns else _agg([])
        cycles[cyc] = {"n": a["n"], "win": a["win"], "avg": a["avg"]}

    # 成本敏感性：买点★扣往返成本后的胜率/均值（0.3%≈常规冲击，0.5%≈追高冲击）
    bh_rets = bh[col].dropna().tolist() if col in bh.columns else []
    cost_sensitivity = []
    for cost in (0.0, 0.3, 0.5):
        a = _agg([r - cost for r in bh_rets])
        cost_sensitivity.append({"cost": cost, "n": a["n"], "win": a["win"], "avg": a["avg"]})

    bh_row = next((c for c in cross if c["signal"] == "买点★"), None)
    con_row = next((c for c in cross if c["signal"] == "一致"), None)
    parts = []
    if bh_row and bh_row["n"]:
        parts.append(f"买点★ {bh_row['n']}样本 胜率{_pct(bh_row['win'])}、均{bh_row['avg']}%")
    if con_row and con_row["n"]:
        parts.append(f"强势一致 胜率{_pct(con_row['win'])}、均{con_row['avg']}%")
    conclusion = (f"持有{h}日：" + "；".join(parts)) if parts else "样本不足，暂无结论"
    return {"total": int(len(df)), "days": int(df["date"].nunique()), "h": h,
            "cross": cross, "cycles": cycles, "cost_sensitivity": cost_sensitivity,
            "conclusion": conclusion}


def update_summary_file(df: Optional[pd.DataFrame], horizons: List[int],
                        path: str = "outputs/backtest_summary.json") -> List[Dict]:
    """写最新回测周报 JSON，并与上一份对比检测【结论翻转】。

    翻转定义（样本 ≥10 才有资格参与判定，避免小样本噪音）：
      - 买点★整体 / 买点★分周期：平均收益符号翻转，或胜率跨过 50%。
    每周任务与手动回测都会调用——结论一旦翻转（例如弱周期买点由跑输转为跑赢），
    前端梯队卡会弹提示，提醒重新审视当前操作纪律。
    返回翻转列表 [{key, metric, from, to, note}]。
    """
    new_sum = summarize(df, horizons)

    def _verdicts(s: Dict) -> Dict[str, Dict]:
        out: Dict[str, Dict] = {}
        bh = next((c for c in (s.get("cross") or []) if c["signal"] == "买点★"), None)
        if bh and (bh.get("n") or 0) >= 10:
            out["买点★整体"] = {"win": bh.get("win"), "avg": bh.get("avg"), "n": bh.get("n")}
        for cyc, a in (s.get("cycles") or {}).items():
            if (a.get("n") or 0) >= 10:
                out[f"买点★·{cyc}周期"] = {"win": a.get("win"), "avg": a.get("avg"), "n": a.get("n")}
        return out

    old = None
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
    except Exception as exc:
        logger.warning(f"读上一份回测周报失败: {exc}")

    new_v = _verdicts(new_sum)
    flips: List[Dict] = []
    if old and old.get("verdicts"):
        for key, nv in new_v.items():
            ov = old["verdicts"].get(key)
            if not ov:
                continue
            if (ov.get("avg") is not None and nv.get("avg") is not None
                    and (ov["avg"] > 0) != (nv["avg"] > 0)):
                flips.append({"key": key, "metric": "avg", "from": ov["avg"], "to": nv["avg"],
                              "note": f"{key} 平均收益 {ov['avg']}% → {nv['avg']}%（符号翻转）"})
            if (ov.get("win") is not None and nv.get("win") is not None
                    and (ov["win"] >= 0.5) != (nv["win"] >= 0.5)):
                flips.append({"key": key, "metric": "win", "from": ov["win"], "to": nv["win"],
                              "note": f"{key} 胜率 {ov['win'] * 100:.0f}% → {nv['win'] * 100:.0f}%（跨过50%）"})

    payload = {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "prev_as_of": (old or {}).get("as_of"),
        "verdicts": new_v,
        "flips": flips,
        "summary": new_sum,
    }
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning(f"写回测周报失败: {exc}")
    for fl in flips:
        print(f"[结论翻转] {fl['note']}")
    return flips


def merge_samples(old: Optional[pd.DataFrame], new: Optional[pd.DataFrame]) -> pd.DataFrame:
    """把新一轮逐笔结果并入历史样本库：按 (date, code) 去重(保留最新)，按日期排序。

    这样每周复跑时，重叠的交易日不会重复计数，只有新交易日的样本累积进来——
    随时间推移，强/中/弱各周期的样本会逐步攒够。
    """
    frames = [d for d in (old, new) if d is not None and not d.empty]
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "code"], keep="last")
    return combined.sort_values("date").reset_index(drop=True)


def main(argv=None):
    p = argparse.ArgumentParser(description="回测综合研究")
    p.add_argument("--days", type=int, default=45)
    p.add_argument("--horizons", default="1,3,5")
    p.add_argument("--output", default="")
    p.add_argument("--accumulate", default="",
                   help="样本库 CSV 路径：新结果并入(去重)后再出累计报告。供每周定时任务累积各周期样本。")
    p.add_argument("--report-only", action="store_true", help="只读样本库出报告，不重新取数")
    args = p.parse_args(argv)
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]

    if args.accumulate:
        old = None
        if os.path.exists(args.accumulate):
            try:
                old = pd.read_csv(args.accumulate)
            except Exception as exc:
                logger.warning(f"读取样本库失败: {exc}")
        if args.report_only:
            df = old if old is not None else pd.DataFrame()
        else:
            print(f"采集数据中（近 {args.days} 个交易日）...")
            new = collect(args.days, horizons)
            df = merge_samples(old, new)
            os.makedirs(os.path.dirname(os.path.abspath(args.accumulate)), exist_ok=True)
            df.to_csv(args.accumulate, index=False, encoding="utf-8-sig")
            added = len(df) - (0 if old is None else len(old))
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            print(f"\n[{stamp}] 样本库 {args.accumulate}：累计 {len(df)} 笔（本轮新增 {max(added,0)}）")
            try:
                with open(args.accumulate.replace('.csv', '.log'), 'a', encoding='utf-8') as f:
                    f.write(f"{stamp} total={len(df)} added={max(added,0)} days={args.days}\n")
            except Exception:
                pass
            # 周报自检：写 summary JSON 并检测与上一份的结论翻转
            update_summary_file(
                df, horizons,
                path=os.path.join(os.path.dirname(os.path.abspath(args.accumulate)),
                                  "backtest_summary.json"))
        report(df, horizons)
        return 0

    print(f"采集数据中（近 {args.days} 个交易日，约需数分钟）...")
    df = collect(args.days, horizons)
    report(df, horizons)
    if args.output and not df.empty:
        df.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(f"\n逐笔记录已保存：{args.output}（{len(df)} 笔）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
