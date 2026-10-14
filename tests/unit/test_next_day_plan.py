"""次日预案：样本标签、收缩预测、无穿越的滚动验证、分档、竞价确认、存档与接口。"""
from datetime import date, datetime, timedelta

import pytest
from flask import Flask

import next_day_plan as ndp
import plan_routes
import signal_journal as sj

TZ = sj.now_sh().tzinfo


def _trading_days(n, start=date(2026, 9, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _row(d, code, *, cont=False, nxt=None, lc=1, t="10:30:00", entry=10.0, buyable=True, close2=10.0,
         open_pct=1.0, buy_hint=False, origin="backfill", seal=1e8, days=5):
    follow = [{"date": nxt, "close": 10.5}, {"date": "x", "close": close2}] if nxt else []
    return {
        "trade_date": d, "code": code, "name": code, "sector": "电池", "sector_count": 3, "role": "龙头",
        "limit_count": lc, "first_limit_time": t, "turnover_rate": 8.0, "break_count": 0, "seal_amount": seal,
        "divergence": "分歧", "buy_hint_any": buy_hint, "wts_any": False, "cycle": "中", "origin": origin,
        "outcome": None if not nxt else {
            "days": days, "next_limit_up": cont, "next_open_pct": open_pct, "follow": follow,
            "next_open": {"entry": entry, "buyable": buyable, "ret_1": 1.0, "ret_3": 2.0},
        },
    }


# ---------------- 样本标签 ----------------

def test_samples_label_cont_hint_and_t_plus_one_return():
    d1, d2 = "2026-10-12", "2026-10-13"
    rows = [
        _row(d1, "A", cont=True, nxt=d2, close2=11.0),
        _row(d1, "B", nxt=d2, buyable=False),
        _row(d2, "A", buy_hint=True),           # A 次日出★买点
    ]
    s = {(x["date"], x["code"]): x for x in ndp.build_samples(rows, cost=0.3)}
    a, b = s[(d1, "A")], s[(d1, "B")]
    assert a["cont"] is True and a["hint"] is True and b["hint"] is False
    assert a["ret2"] == pytest.approx(9.7)       # 次日开盘 10 买、隔日收盘 11 卖，扣 0.3
    assert b["ret2"] is None and b["buyable"] is False   # 买不进的不算收益
    assert s[(d2, "A")]["cont"] is None          # 结果还没出来


def test_hint_unknown_when_next_day_is_legacy_snapshot():
    d1, d2 = "2026-10-12", "2026-10-13"
    rows = [_row(d1, "A", nxt=d2), _row(d2, "Z", origin="legacy")]
    assert ndp.build_samples(rows)[0]["hint"] is None  # 旧样本每天只有约 20 只，不能当"没出买点"


# ---------------- 模型 ----------------

def _sample(cont, lc, idx=0):
    return {"idx": idx, "cont": cont, "hint": False, "features": {"limit": ndp.lab.limit_bucket({"limit_count": lc})}}


def test_shrinkage_pulls_small_groups_toward_base():
    train = [_sample(i % 5 == 0, 1) for i in range(100)] + [_sample(True, 3)] * 2
    m = ndp.PlanModel(train)
    big = m.predict({"limit": ndp.lab.limit_bucket({"limit_count": 1})})
    small = m.predict({"limit": ndp.lab.limit_bucket({"limit_count": 3})})
    # 只有 2 笔、命中率 100% 的分组：收缩后远低于 100%，但高于基准
    assert m.base["cont"] < small["cont"] < 0.4
    assert big["cont"] < m.base["cont"] + 0.01
    assert small["reasons"][0]["n"] == 2 and small["reasons"][0]["rate"] == 1.0


def test_train_for_uses_only_known_outcomes():
    samples = [_sample(True, 1, idx=i) for i in range(5)]
    m = ndp.train_for(samples, 3)
    assert m.n["cont"] == 3  # idx 0..2；站在第 3 天收盘，第 3 天的次日结果还不知道


def test_tiers():
    m = ndp.PlanModel([_sample(i % 10 == 0, 1) for i in range(50)])  # 基准 10%
    assert ndp.tier_of({"cont": 0.30, "hint": 0.0}, m) == "focus"
    assert ndp.tier_of({"cont": 0.20, "hint": 0.0}, m) is None    # 2 倍但低于 25% 的下限
    m.base["hint"] = 0.1
    assert ndp.tier_of({"cont": 0.1, "hint": 0.2}, m) == "watch"


def test_walk_forward_does_not_peek_at_future():
    days = _trading_days(14)
    rows = []
    for i, d in enumerate(days):
        nxt = days[i + 1] if i + 1 < len(days) else None
        for k in range(6):
            # 前半段 2 板必涨停，后半段反过来：如果偷看未来，早期预测就会知道"反转"
            strong = (k < 2) == (i < 9)
            rows.append(_row(d, f"{k:06d}", cont=strong and nxt is not None, nxt=nxt, lc=2 if k < 2 else 1))
    wf = ndp.walk_forward(rows)
    first = wf["series"][0]
    assert first["date"] == days[ndp.MIN_TRAIN_DAYS]
    assert first["plan_cont"] == 1.0  # 第 8 天只学到"2 板强"，且当天确实如此
    assert wf["series"][-1]["plan_cont"] in (0.0, None)  # 规律反转后，模型只能事后慢慢学到
    assert "plan_samples" in wf


# ---------------- 竞价确认 ----------------

RULES = [{"key": "low3", "n": 30, "avg_2": 1.2, "avg_3": 0.5}, {"key": "high3", "n": 30, "avg_2": -2.0, "avg_3": -3.0},
         {"key": "high6", "n": 5, "avg_2": 3.0, "avg_3": 3.0}]


def test_auction_advice_codes():
    assert ndp.auction_advice(None, False, [], RULES, True)["code"] == "unknown"
    assert ndp.auction_advice(10.0, True, [], RULES, True)["code"] == "unbuyable"
    ok = ndp.auction_advice(-4.0, False, [], RULES, True)
    assert ok["code"] == "ok" and "全部前日涨停" in ok["text"]
    assert ndp.auction_advice(1.0, False, [], RULES, True)["code"] == "skip"
    assert ndp.auction_advice(4.0, False, [], RULES, True)["code"] == "thin"
    assert ndp.auction_advice(-10.0, False, [], RULES, True, at_limit_down=True)["code"] == "limit_down"
    gated = ndp.auction_advice(-4.0, False, [], RULES, False)
    assert gated["code"] == "gated" and gated["text"].startswith("执行闸暂停开仓")


def test_plan_rules_preferred_when_enough_samples():
    plan = [{"key": "low3", "n": 25, "avg_2": -1.0, "avg_3": -1.0}]
    adv = ndp.auction_advice(-4.0, False, plan, RULES, True)
    assert adv["code"] == "skip" and "预案票" in adv["text"]


# ---------------- 存档与接口 ----------------

@pytest.fixture
def env(tmp_path):
    svc = sj.JournalService(sj.JournalStore(tmp_path / "j.db"))
    days = _trading_days(12, start=date(2026, 9, 28))
    rows = []
    for i, d in enumerate(days):
        nxt = days[i + 1] if i + 1 < len(days) else None
        for k in range(5):
            rows.append(_row(d, f"60000{k}", cont=(k == 0 and nxt is not None), nxt=nxt, lc=3 if k == 0 else 1,
                             open_pct=-4.0))
    for r in rows:
        svc.store.upsert(r["trade_date"], [{k: v for k, v in r.items() if k != "outcome"}], f"{r['trade_date']} 15:00:00",
                         "backfill", final=True)
        if r["outcome"]:
            svc.store.save_outcome(r["trade_date"], r["code"], r["outcome"], "t")
    state = {"now": datetime(2026, 10, 14, 9, 0, tzinfo=TZ), "quotes": 0}

    def quote(code):
        state["quotes"] += 1
        return {"open": 9.6, "prev_close": 10.0, "name": code}

    old = dict(plan_routes.DEPS)
    plan_routes.DEPS.update(service=lambda: svc, now=lambda: state["now"], is_trading_day=lambda d: d.weekday() < 5,
                            quote=quote, gate=lambda: {"can_open": True})
    plan_routes.clear_cache()
    app = Flask(__name__)
    app.register_blueprint(plan_routes.plan_bp)
    yield svc, app.test_client(), state, days
    plan_routes.DEPS.update(old)
    plan_routes.clear_cache()


def test_plan_endpoint_generates_once_and_confirms_auction(env):
    svc, client, state, days = env
    body = client.get("/api/plan").get_json()
    assert body["success"]
    d = body["data"]
    assert d["plan_date"] == days[-1] and d["for_date"] == "2026-10-14" and d["auction"]["phase"] == "before"
    top = d["items"][0]
    assert top["code"] == "600000" and top["tier"] == "focus" and top["auction_advice"] is None
    assert "plan_samples" not in str(d.keys())
    assert d["verdict"]["level"] in ("ok", "warn", "crit", "none")

    state["now"] = datetime(2026, 10, 14, 9, 26, tzinfo=TZ)
    d = client.get("/api/plan").get_json()["data"]
    top = d["items"][0]
    assert d["auction"]["phase"] == "live" and top["auction_open_pct"] == -4.0
    assert top["auction_advice"]["code"] in ("ok", "thin", "skip")
    calls = state["quotes"]
    # 竞价结果第一次取到就存档，之后不再请求行情
    state["now"] = datetime(2026, 10, 14, 10, 0, tzinfo=TZ)
    d2 = client.get("/api/plan").get_json()["data"]
    assert state["quotes"] == calls and d2["items"][0]["auction_at"] == "2026-10-14 09:26:00"
    assert len(svc.store.plan_dates()) == 1


def test_auction_respects_execution_gate(env):
    svc, client, state, _ = env
    plan_routes.DEPS["gate"] = lambda: {"can_open": False}
    state["now"] = datetime(2026, 10, 14, 9, 26, tzinfo=TZ)
    items = client.get("/api/plan").get_json()["data"]["items"]
    advice = [i["auction_advice"] for i in items if i.get("tier")]
    assert advice and all(a["code"] != "ok" for a in advice)


def test_archive_scores_past_plans_and_history_is_read_only(env):
    svc, client, state, days = env
    now = datetime(2026, 10, 9, 15, 30, tzinfo=TZ)
    plan_routes.ensure_plan(svc, days[-3], is_trading_day=lambda d: d.weekday() < 5, now=now)
    plans = client.get("/api/plan/archive").get_json()["data"]["plans"]
    p = next(x for x in plans if x["plan_date"] == days[-3])
    assert p["settled"] >= 1 and p["cont"] is not None
    assert client.get("/api/plan?date=2020-01-01").status_code == 404
    assert client.get("/api/plan?date=bad").status_code == 400
    v = client.get("/api/plan/validation").get_json()["data"]
    assert "plan_samples" not in v and set(v["rules"]) == {"plan", "all"}


def test_generate_after_close_requires_final_record(env):
    svc, _, _, days = env
    late = datetime(2026, 10, 14, 15, 10, tzinfo=TZ)
    assert plan_routes.generate_after_close(svc, late, lambda d: True) == 0  # 今天还没记收盘版
    svc.store.set_meta(f"final:{days[-1]}", "x")
    n = plan_routes.generate_after_close(svc, datetime.fromisoformat(days[-1] + "T15:10:00+08:00"), lambda d: True)
    assert n >= 1 and svc.store.load_plan(days[-1])
