"""信号复盘日志：记录合并、后续表现计算、统计、回补、自动记录节奏。"""
from datetime import date, datetime, timedelta

import pytest
from flask import Flask

import journal_routes
import signal_journal as sj
from rate_limit import owner_only
from werkzeug.datastructures import MultiDict

TZ = sj.TZ


def _ladder(stocks, as_of="2026-10-13 10:00:00", cycle="中", stale=False):
    return {"data_as_of": as_of, "data_stale": stale, "spirit": {"cycle": cycle},
            "sectors": [{"sector": "电池", "count": len(stocks), "stocks": stocks}]}


def _stock(code, name="甲", role="龙头", buy_hint=False, cross="", limit_count=2, first="10:15:00", turnover=8.0):
    return {"code": code, "name": name, "role": role, "limit_count": limit_count, "seal_amount": 1e8,
            "first_limit_time": first, "turnover_rate": turnover, "break_count": 0,
            "divergence": "分歧", "buy_hint": buy_hint, "cross": cross, "sell_alert": ""}


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def service(tmp_path):
    clock = Clock(datetime(2026, 10, 13, 10, 0, tzinfo=TZ))
    return sj.JournalService(sj.JournalStore(tmp_path / "j.db"), clock=clock), clock


# ---------------- 记录合并 ----------------

def test_intraday_records_merge_first_seen_and_buy_hint_any(service):
    svc, clock = service
    svc.record(_ladder([_stock("600001"), _stock("600002", name="乙", role="龙二")]),
               {"watch": [{"code": "600002"}]})
    clock.t = datetime(2026, 10, 13, 10, 30, tzinfo=TZ)
    svc.record(_ladder([_stock("600001", buy_hint=True), _stock("600002", name="乙", role="龙二")]),
               {"primary": [{"code": "600002"}]})
    clock.t = datetime(2026, 10, 13, 11, 0, tzinfo=TZ)
    svc.record(_ladder([_stock("600001", buy_hint=False)]), None)  # 买点消失、乙炸板出池

    rows = {r["code"]: r for r in svc.store.query("2026-10-13", "2026-10-13")}
    a, b = rows["600001"], rows["600002"]
    assert a["first_seen_at"] == "2026-10-13 10:00:00" and a["last_seen_at"] == "2026-10-13 11:00:00"
    assert a["buy_hint_any"] and not a["buy_hint"] and a["buy_hint_first_at"] == "2026-10-13 10:30:00"
    assert b["candidate_tier"] == "primary" and b["candidate_first_at"] == "2026-10-13 10:00:00"

    clock.t = datetime(2026, 10, 13, 15, 6, tzinfo=TZ)
    svc.record(_ladder([_stock("600001")], as_of="2026-10-13 15:06:00"), None, final=True)
    rows = {r["code"]: r for r in svc.store.query("2026-10-13", "2026-10-13")}
    assert rows["600001"]["closed_limit_up"] is True and rows["600002"]["closed_limit_up"] is False
    assert svc.finalized("2026-10-13")


def test_stale_ladder_from_yesterday_is_not_recorded(service):
    svc, _ = service
    assert svc.record(_ladder([_stock("600001")], as_of="2026-10-12 15:00:00")) == 0
    assert svc.record(_ladder([_stock("600001")], stale=True)) == 0
    assert svc.store.query("2026-10-01", "2026-10-31") == []


# ---------------- 后续表现 ----------------

def _bars(closes, opens=None, highs=None, lows=None, start=date(2026, 10, 9)):
    out, d = [], start
    for i, c in enumerate(closes):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"date": d.isoformat(), "open": (opens or closes)[i], "high": (highs or closes)[i],
                    "low": (lows or closes)[i], "close": c})
        d += timedelta(days=1)
    return out


def test_outcome_counts_streak_and_both_entry_modes():
    # D-1=10, D0 涨停 11, D1 一字 12.1, D2 涨停 13.31（开 12.5），D3 12.5, D4 12, D5 12.6
    bars = _bars(
        [10, 11, 12.1, 13.31, 12.5, 12.0, 12.6],
        opens=[10, 10.5, 12.1, 12.5, 13.0, 12.4, 12.0],
        highs=[10, 11, 12.1, 13.31, 13.5, 12.6, 12.8],
        lows=[10, 10.4, 12.1, 12.3, 12.4, 11.8, 11.9],
    )
    rec = {"trade_date": "2026-10-12", "code": "600001", "name": "甲", "limit_count": 2,
           "first_limit_time": "10:15:00", "turnover_rate": 8.0}
    o = sj.compute_outcome(rec, bars)
    assert o["closed_at_limit"] and o["streak"] == 2 and o["height_after"] == 4
    assert o["next_limit_up"] and o["follow"][0]["one_word"] and o["next_open_pct"] == 10.0
    assert o["complete"]
    # 次日开盘即涨停：买不进
    assert o["next_open"]["buyable"] is False and "买不进" in o["next_open"]["reason"]
    # 当日排板：11 元买入，T+1 收 12.1 → +10%，T+5 收 12.6
    sd = o["same_day"]
    assert sd["buyable"] and sd["entry"] == 11 and sd["ret_1"] == 10.0 and sd["ret_5"] == 14.55
    assert sd["max_gain"] == 22.73 and sd["max_drawdown"] == 7.27


def test_same_day_entry_is_unbuyable_for_one_word_board_and_records_blowup_loss():
    bars = _bars([10, 10.6, 10.2], opens=[10, 10.3, 10.5])
    rec = {"trade_date": "2026-10-12", "code": "600001", "first_limit_time": "09:25:00", "turnover_rate": 0.5}
    o = sj.compute_outcome(rec, bars)
    assert o["same_day"]["buyable"] is False and "一字" in o["same_day"]["reason"]
    assert o["same_day"]["day0_ret"] == -3.64  # 排板 11 元，收盘 10.6（炸板）
    assert not o["complete"] and o["days"] == 1


def test_limit_pct_by_board():
    assert sj.limit_pct("300001") == 20 and sj.limit_pct("688001") == 20
    assert sj.limit_pct("830001") == 30 and sj.limit_pct("600001", "*ST甲") == 5
    assert sj.limit_pct("002001") == 10


def test_update_outcomes_fetches_each_code_once_and_skips_today_before_close(service):
    svc, clock = service
    svc.store.upsert("2026-10-12", [{**_stock("600001"), "cycle": "中"}], "2026-10-12 15:00:00", "backfill", True)
    svc.store.upsert("2026-10-13", [{**_stock("600001"), "cycle": "中"}], "2026-10-13 15:00:00", "backfill", True)
    calls = []
    bars = _bars([10, 11, 12.1, 12.5])  # 10-09, 10-12, 10-13, 10-14

    def bars_of(code):
        calls.append(code)
        return bars

    clock.t = datetime(2026, 10, 14, 11, 0, tzinfo=TZ)  # 14 日盘中：只能用到 13 日
    res = svc.update_outcomes(bars_of)
    assert calls == ["600001"] and res["updated"] == 2
    rows = {r["trade_date"]: r for r in svc.store.query("2026-10-12", "2026-10-13")}
    assert rows["2026-10-12"]["outcome"]["days"] == 1
    assert rows["2026-10-13"]["outcome"]["days"] == 0  # 次日还没收盘


# ---------------- 统计 ----------------

def test_summary_counts_only_buyable_trades():
    def row(ret1, buyable, buy_hint=True, limit=False):
        mode = {"buyable": buyable, "entry": 10, "ret_1": ret1, "ret_3": None, "ret_5": None,
                "max_gain": 5.0, "max_drawdown": -3.0}
        return {"buy_hint_any": buy_hint, "role": "龙头", "outcome": {
            "next_open": mode, "same_day": mode, "days": 1, "next_limit_up": limit, "next_open_pct": 2.0,
            "streak": 1 if limit else 0}}

    rows = [row(5.0, True), row(-2.0, True), row(10.0, False, limit=True), row(1.0, True, buy_hint=False)]
    s = sj.summarize(rows, "next_open")
    assert s["buy_hint"]["n"] == 3 and s["buy_hint"]["unbuyable"] == 1 and s["buy_hint"]["n_1"] == 2
    assert s["buy_hint"]["win_1"] == 0.5 and s["buy_hint"]["avg_1"] == 1.5
    assert s["buy_hint"]["next_limit_rate"] == round(1 / 3, 3)
    assert s["all"]["n"] == 4


# ---------------- 回补 ----------------

def test_backfill_rebuilds_signals_with_previous_day_and_promotion_cycle(service):
    svc, clock = service
    clock.t = datetime(2026, 10, 14, 20, 0, tzinfo=TZ)
    days = [date(2026, 10, 9), date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)]
    pools = {
        date(2026, 10, 9): [{"code": "600001"}, {"code": "600002"}],
        date(2026, 10, 12): [{"code": "600001"}],
        date(2026, 10, 13): [],                       # 取不到
        date(2026, 10, 14): [{"code": "600003"}],
    }
    seen_prev = []

    def build_sectors(pool, prev_map):
        seen_prev.append(sorted(prev_map))
        return [{"sector": "电池", "count": len(pool), "stocks": [_stock(p["code"]) for p in pool]}]

    res = svc.backfill(3, trading_days=lambda a, b: days, zt_pool_of=lambda d: pools[d],
                       build_sectors=build_sectors)
    assert res["days"] == 3 and res["empty_days"] == ["2026-10-13"]
    rows = {(r["trade_date"], r["code"]): r for r in svc.store.query("2026-10-01", "2026-10-31")}
    assert rows[("2026-10-12", "600001")]["cycle"] == "强"  # 晋级率 1/2 = 50% ≥ 40%
    assert seen_prev[0] == ["600001", "600002"]
    assert rows[("2026-10-12", "600001")]["origin"] == "backfill"


def test_backfill_never_overwrites_live_records(service):
    svc, clock = service
    svc.record(_ladder([_stock("600001", buy_hint=True)]))
    clock.t = datetime(2026, 10, 14, 20, 0, tzinfo=TZ)
    svc.backfill(1, trading_days=lambda a, b: [date(2026, 10, 12), date(2026, 10, 13)],
                 zt_pool_of=lambda d: [{"code": "600001"}],
                 build_sectors=lambda pool, prev: [{"sector": "x", "count": 1, "stocks": [_stock("600001")]}])
    row = svc.store.query("2026-10-13", "2026-10-13")[0]
    assert row["origin"] == "live" and row["buy_hint_any"]


# ---------------- 自动记录节奏 ----------------

def test_recorder_tick_schedule(service, monkeypatch):
    svc, clock = service
    monkeypatch.setattr(journal_routes, "bars_of", lambda code: [])
    kw = dict(is_trading_day=lambda d: d.weekday() < 5, workbench=lambda: None, service=svc,
              ladder_live=lambda: _ladder([_stock("600001")], as_of=f"{clock.t.date()} 10:00:00"),
              ladder_fresh=lambda: _ladder([_stock("600001")], as_of=f"{clock.t.date()} 15:06:00"))

    def tick(t):
        clock.t = t
        return journal_routes.recorder_tick(t, **kw)

    assert tick(datetime(2026, 10, 13, 9, 20, tzinfo=TZ)) == "idle"
    assert tick(datetime(2026, 10, 13, 10, 0, tzinfo=TZ)) == "live:1"
    assert tick(datetime(2026, 10, 13, 15, 6, tzinfo=TZ)) == "final:1"
    assert tick(datetime(2026, 10, 13, 15, 8, tzinfo=TZ)) == "idle"  # 收盘版只记一次
    assert tick(datetime(2026, 10, 17, 10, 0, tzinfo=TZ)) == "closed"  # 周六


# ---------------- 接口 ----------------

def test_query_endpoint_returns_rows_and_both_summaries(service):
    svc, _ = service
    svc.record(_ladder([_stock("600001", buy_hint=True)]))
    journal_routes.set_service(svc)
    try:
        app = Flask(__name__)
        app.register_blueprint(journal_routes.journal_bp)
        body = app.test_client().get("/api/journal?start=2026-10-01&end=2026-10-14").get_json()
        assert body["success"] and body["data"]["rows"][0]["code"] == "600001"
        assert set(body["data"]["summary"]) == {"next_open", "same_day"}
        assert body["data"]["summary"]["next_open"]["buy_hint"]["n"] == 1
        bad = app.test_client().get("/api/journal?start=2026-13-01")
        assert bad.status_code == 400
    finally:
        journal_routes.set_service(None)


def test_backfill_and_refresh_are_owner_only():
    assert owner_only("POST", "/api/journal/backfill/start", MultiDict())
    assert owner_only("POST", "/api/journal/outcomes/start", MultiDict())
    assert owner_only("GET", "/api/journal", MultiDict()) is None
