"""回测分析台：筛选、指标、分布、资金曲线、维度拆解、自动发现、结论翻转、旧样本导入、接口。"""
from datetime import date, datetime

import pytest
from flask import Flask

import backtest_lab as lab
import journal_routes
import signal_journal as sj


def _row(d, code, ret3, *, buyable=True, buy_hint=False, wts=False, role="龙头", lc=2, t="10:15:00", turnover=8.0,
         div="分歧", cycle="中", sector_count=3, breaks=0, origin="backfill", closed=True, ret1=None, days=5):
    mode = {"entry": 10.0, "buyable": buyable, "reason": "" if buyable else "次日开盘即涨停，买不进",
            "ret_1": ret1 if ret1 is not None else ret3, "ret_3": ret3, "ret_5": ret3, "max_gain": 5.0, "max_drawdown": -4.0}
    return {"trade_date": d, "code": code, "name": code, "sector": "电池", "sector_count": sector_count, "role": role,
            "limit_count": lc, "first_limit_time": t, "turnover_rate": turnover, "break_count": breaks,
            "divergence": div, "buy_hint_any": buy_hint, "wts_any": wts, "candidate_tier": None, "cycle": cycle,
            "origin": origin, "closed_limit_up": closed,
            "outcome": {"days": days, "next_limit_up": ret3 > 5, "next_open_pct": 1.0, "streak": 0,
                        "next_open": mode, "same_day": mode}}


ROWS = [
    _row("2026-10-08", "000001", 6.0, buy_hint=True, lc=2, t="09:45:00"),
    _row("2026-10-08", "000002", -4.0, buy_hint=True, lc=3, t="14:40:00", cycle="弱"),
    _row("2026-10-09", "000003", 2.0, lc=1, t="09:25:00", div="一致", turnover=1.0),
    _row("2026-10-09", "000004", 0.0, buyable=False, buy_hint=True),
    _row("2026-10-09", "000005", -2.0, role="龙二", lc=1),
    _row("2026-10-12", "000006", 8.0, wts=True, lc=2, breaks=1),
]


def test_filters_combine_and_count_unbuyable_separately():
    r = lab.run(ROWS, {"signals": ["buy_hint"], "cost": 0})
    m = r["metrics"]
    assert m["signals"] == 3 and m["n"] == 2 and m["unbuyable"] == 1
    assert m["win"] == 0.5 and m["avg"] == 1.0 and m["payoff"] == 1.5
    # 基准 = 区间内全部（买得进 5 笔）
    assert r["baseline"]["n"] == 5 and r["baseline"]["avg"] == 2.0 and r["excess"]["avg"] == -1.0

    assert lab.run(ROWS, {"signals": ["buy_hint", "wts"], "signal_logic": "any"})["metrics"]["signals"] == 4
    assert lab.run(ROWS, {"signals": ["buy_hint", "wts"], "signal_logic": "all"})["metrics"]["signals"] == 0
    assert [t["code"] for t in lab.run(ROWS, {"limit_min": 2, "limit_max": 2})["trades"]] == ["000001", "000004", "000006"]
    assert [t["code"] for t in lab.run(ROWS, {"times": ["auction"]})["trades"]] == ["000003"]
    assert [t["code"] for t in lab.run(ROWS, {"turnover_max": 3})["trades"]] == ["000003"]
    assert [t["code"] for t in lab.run(ROWS, {"breaks": "some"})["trades"]] == ["000006"]
    assert [t["code"] for t in lab.run(ROWS, {"cycles": ["弱"]})["trades"]] == ["000002"]
    assert [t["code"] for t in lab.run(ROWS, {"roles": ["龙二"]})["trades"]] == ["000005"]


def test_cost_and_horizon_and_mode_are_applied():
    r = lab.run(ROWS, {"signals": ["buy_hint"], "cost": 0.5, "horizon": 1, "mode": "same_day"})
    assert r["metrics"]["avg"] == 0.5 and r["spec"]["mode"] == "same_day"
    assert lab.normalize_spec({"horizon": 7, "mode": "x", "cost": "abc"})["horizon"] == 3


def test_histogram_and_equity_curve():
    r = lab.run(ROWS, {"cost": 0, "horizon": 1})
    hist = {b["label"]: b["count"] for b in r["histogram"]}
    assert hist["6~10%"] == 2 and hist["-6~-3%"] == 1 and hist["1~3%"] == 1 and sum(hist.values()) == 5
    eq = r["equity"]
    # 10-08 均 1.0；10-09 均 0.0（-2 与 2）；10-12 均 8.0
    assert [p["cum"] for p in eq["series"]] == [1.0, 1.0, 9.0] and eq["total"] == 9.0
    assert eq["days"] == 3 and eq["win_days"] == 2 and eq["max_drawdown"] == 0.0


def test_equity_drawdown():
    rows = [_row("2026-10-08", "a", 5.0), _row("2026-10-09", "b", -8.0), _row("2026-10-12", "c", 2.0)]
    eq = lab.run(rows, {"cost": 0, "horizon": 1})["equity"]
    assert eq["max_drawdown"] == -8.0 and eq["total"] == -1.0
    # 持有 3 日：资金分 3 份轮动，每天只累加 1/3
    eq3 = lab.run(rows, {"cost": 0, "horizon": 3})["equity"]
    assert eq3["total"] == round(-1.0 / 3, 2) and eq3["slots"] == 3


def test_breakdown_marks_small_groups_unreliable():
    r = lab.run(ROWS, {"cost": 0})
    limit = next(d for d in r["breakdown"] if d["key"] == "limit")
    b2 = next(b for b in limit["buckets"] if b["key"] == "b2")
    assert b2["n"] == 2 and b2["avg"] == 7.0 and b2["excess"] == 5.0 and b2["reliable"] is False


def test_findings_need_enough_samples_and_give_appliable_filters(monkeypatch):
    monkeypatch.setattr(lab, "MIN_FINDING_N", 3)
    rows = [_row("2026-10-08", f"{i:06d}", 6.0, buy_hint=True, cycle="强") for i in range(4)]
    rows += [_row("2026-10-09", f"1{i:05d}", -3.0, cycle="弱") for i in range(6)]
    f = lab.run(rows, {"cost": 0})["findings"]
    labels = [x["label"] for x in f["best"]]
    assert "信号：★买点" in labels and "接力周期：强" in labels
    best = next(x for x in f["best"] if x["label"] == "信号：★买点")
    assert best["n"] == 4 and best["patch"] == {"signals": ["buy_hint"]}
    assert any(x["label"] == "接力周期：弱" for x in f["worst"])
    # "★买点 · 强周期"与单独"★买点"样本完全相同，不应重复出现
    assert not any(x["label"] == "信号：★买点 · 接力周期：强" for x in f["best"])
    # 应用发现给出的条件，结果应一致
    applied = lab.run(rows, {"cost": 0, **best["patch"]})["metrics"]
    assert applied["n"] == 4 and applied["avg"] == 6.0


def test_legacy_rows_can_be_excluded():
    rows = ROWS + [_row("2026-06-16", "600001", 9.0, origin="legacy", sector_count=0)]
    assert lab.run(rows, {})["metrics"]["signals"] == 7
    assert lab.run(rows, {"include_legacy": False})["metrics"]["signals"] == 6


@pytest.fixture
def store(tmp_path):
    return sj.JournalStore(tmp_path / "j.db")


def test_verdict_flips_compare_with_a_week_ago(store):
    good = [_row(f"2026-09-{d:02d}", f"{d:06d}", 3.0, buy_hint=True) for d in range(1, 13)]
    assert lab.update_verdicts(store, good, date(2026, 9, 20)) == []
    bad = [_row(f"2026-09-{d:02d}", f"{d:06d}", -3.0, buy_hint=True) for d in range(14, 28)]
    flips = lab.update_verdicts(store, bad, date(2026, 9, 28))
    assert flips and flips[0]["signal"] == "buy_hint" and flips[0]["from"] == "有效" and flips[0]["to"] == "无效"
    assert lab.latest_flips(store, date(2026, 10, 1))["flips"]
    assert lab.latest_flips(store, date(2026, 10, 20))["flips"] == []  # 两周后不再显示


def test_import_legacy_only_fills_missing_dates(store, tmp_path):
    store.upsert("2026-09-16", [{"code": "600001", "name": "甲", "cycle": "中"}], "2026-09-16 15:00:00", "backfill", True)
    csv = tmp_path / "s.csv"
    csv.write_text(
        "date,code,name,cycle,promo,role,divergence,buy_hint,turnover,limit_count,seal,t_min,ret_1,ret_3,ret_5,promo_real,cycle_real,break_count\n"
        "2026-06-16,1257,盛龙股份,中,0.2,龙头,分歧,True,16.13,4,143740634.0,572,-6.5,-3.4,-15.3,,,\n"
        "2026-09-16,2585,双星新材,中,0.2,龙头,一致,False,6.95,2,210888901.0,570,9.5,7.6,3.2,0.3,中,0\n",
        encoding="utf-8",
    )
    res = lab.import_legacy_samples(store, csv)
    assert res == {"imported": 1, "days": 1, "skipped_days": 1}
    row = store.query("2026-06-16", "2026-06-16")[0]
    assert row["code"] == "001257" and row["origin"] == "legacy" and row["first_limit_time"] == "09:32:00"
    assert row["buy_hint_any"] and row["cycle"] == "中" and row["outcome"] is None
    assert lab.import_legacy_samples(store, tmp_path / "missing.csv")["imported"] == 0


def test_lab_endpoints_and_presets(store):
    svc = sj.JournalService(store, clock=lambda: datetime(2026, 10, 14, 12, 0, tzinfo=sj.TZ))
    store.upsert("2026-10-08", [{"code": "600001", "name": "甲", "cycle": "中", "buy_hint": True, "role": "龙头",
                                 "limit_count": 2}], "2026-10-08 15:00:00", "backfill", True)
    journal_routes.set_service(svc)
    try:
        app = Flask(__name__)
        app.register_blueprint(journal_routes.journal_bp)
        c = app.test_client()
        body = c.post("/api/lab/run", json={"signals": ["buy_hint"], "start": "2026-10-01"}).get_json()
        assert body["success"] and body["data"]["metrics"]["signals"] == 1 and body["data"]["metrics"]["pending"] == 1
        assert "flips" in body["data"] and body["data"]["dimension_buckets"]["time"]

        assert c.post("/api/lab/presets", json={"name": ""}).status_code == 400
        saved = c.post("/api/lab/presets", json={"name": "二板买点", "spec": {"signals": ["buy_hint"], "limit_min": 2,
                                                                          "start": "2026-01-01"}}).get_json()["data"]
        assert "start" not in saved["spec"] and saved["spec"]["limit_min"] == 2
        listed = c.get("/api/lab/presets").get_json()["data"]
        assert listed[0]["name"] == "二板买点"
        assert c.delete(f"/api/lab/presets/{saved['id']}").get_json()["success"]
        assert c.get("/api/lab/presets").get_json()["data"] == []
    finally:
        journal_routes.set_service(None)
