"""消息催化扫描（方案 D）。"""
import time

import news_catalyst
import news_routes
import news_scanner
from werkzeug.datastructures import MultiDict
from rate_limit import classify


def _ev(code, name, type_="restructure", direction=1, level="major", pending=False, elapsed=0, t="2026-09-29 19:00"):
    return {"code": code, "name": name, "type": type_, "type_label": type_, "direction": direction, "level": level,
            "level_label": "重大" if level == "major" else "显著", "title": f"{name}公告", "url": "u",
            "published_at": t, "pending": pending, "sessions_elapsed": -1 if pending else elapsed, "related": 0}


QUOTES = {
    "600001": {"name": "甲", "current": 10.5, "change_pct": 2.0},                     # 普通：关注
    "600002": {"name": "乙", "current": 11.0, "change_pct": 10.0, "is_limit_up": True,
               "open": 11.0, "high": 11.0, "low": 11.0},                             # 一字：买不进
    "600003": {"name": "丙", "current": 10.8, "change_pct": 8.0},                     # 已兑现
    "600009": {"name": "壬", "current": 9.0, "change_pct": -9.0},                     # 利好后大跌：市场不认
    "600004": {"name": "丁", "current": 0, "change_pct": 0},                          # 停牌
    "600005": {"name": "戊", "current": 10.2, "change_pct": 1.0},                     # 同时有利空
    "600006": {"name": "己", "current": 11.0, "change_pct": 10.0, "is_limit_up": True},  # 换手板：可排板
}


def _radar():
    return {"as_of": "x", "window": {"reaction_day": "2026-09-30"}, "events": [
        _ev("600001", "甲", level="notable", type_="big_contract"),
        _ev("600002", "乙"),
        _ev("600003", "丙"),
        _ev("600004", "丁", type_="major_plan_halt"),
        _ev("600005", "戊"),
        _ev("600005", "戊", type_="reduce_plan", direction=-1, level="notable"),
        _ev("600006", "己", level="notable", type_="approval"),
        _ev("600007", "庚", pending=True),
        _ev("600008", "辛", type_="delisting", direction=-1),  # 纯利空不进扫描
        _ev("600009", "壬", type_="control_change"),
    ]}


ZT = [
    {"code": "600006", "sector": "医药", "first_limit_time": "10:15:00", "turnover_rate": 6.3, "limit_count": 1},
    {"code": "600100", "sector": "医药"}, {"code": "600101", "sector": "医药"},
]
OPEN = {"position": {"can_open": True}, "blockers": []}


def _run(execution=OPEN):
    return news_scanner.evaluate(
        _radar(), quote=lambda c: QUOTES.get(c, {"error": "无行情"}), zt_pool=ZT, execution=execution,
        sector_of=lambda c: "医药生物-化学制药-医药" if c == "600001" else "计算机-软件开发",
    )


def test_each_status_is_decided_for_the_right_reason():
    rows = {r["code"]: r for r in _run()["data"]}
    assert "600008" not in rows
    assert rows["600001"]["status"] == "focus" and rows["600001"]["mainline"]
    assert rows["600002"]["status"] == "blocked" and "一字" in rows["600002"]["blockers"][0]
    assert rows["600003"]["status"] == "priced_in"
    assert rows["600004"]["status"] == "wait" and "停牌" in rows["600004"]["reasons"][0]
    assert rows["600005"]["status"] == "wait" and "同时有利空" in rows["600005"]["blockers"][0]
    assert rows["600006"]["status"] == "focus" and "排板" in rows["600006"]["reasons"][0]
    assert rows["600007"]["status"] == "wait" and rows["600007"]["timing"] == "待首次交易"
    assert rows["600009"]["status"] == "rejected" and "市场不认" in rows["600009"]["blockers"][0]
    assert rows["600001"]["sector"] == "医药" and rows["600001"]["sector_limit_ups"] == 3  # 行业分级近似匹配


def test_rows_are_ranked_focus_first_then_major_then_mainline():
    data = _run()
    order = [r["code"] for r in data["data"]]
    assert order[:2] == ["600001", "600006"]  # 两个关注：都在主线，同为显著，按时间
    assert data["meta"]["status_counts"] == {"focus": 2, "wait": 3, "priced_in": 1, "rejected": 1, "blocked": 1}


def test_closed_execution_gate_turns_focus_into_observe_only():
    closed = {"position": {"can_open": False}, "blockers": ["指数空仓态：今日不开新仓"]}
    rows = {r["code"]: r for r in _run(closed)["data"]}
    assert rows["600001"]["status_label"] == "关注（执行闸暂停开仓）"
    assert not rows["600001"]["blockers"]
    assert "指数空仓态" in _run(closed)["meta"]["gate_reason"]


def test_after_close_only_says_wait_for_open():
    review = {"mode": "review", "position": {"can_open": False}, "blockers": ["非A股交易时段"]}
    rows = {r["code"]: r for r in _run(review)["data"]}
    assert rows["600001"]["status_label"] == "关注（待开盘验证）" and not rows["600001"]["blockers"]


def test_catalyst_job_runs_in_background_and_counts_as_scan(monkeypatch):
    monkeypatch.setattr(news_catalyst, "get_radar", lambda refresh=False: (_radar(), "fresh"))
    monkeypatch.setattr(news_routes, "_catalyst_inputs", lambda: {
        "quote": lambda c: QUOTES.get(c, {"error": "无行情"}), "zt_pool": ZT, "execution": OPEN,
        "sector_of": lambda c: "",
    })
    from flask import Flask
    import scanner_routes

    app = Flask(__name__)
    app.register_blueprint(news_routes.news_bp)
    app.register_blueprint(scanner_routes.scanner_bp)
    client = app.test_client()
    job = client.post("/api/news/catalyst/start").get_json()["data"]
    for _ in range(50):
        state = client.get(f"/api/scanners/jobs/{job['id']}").get_json()["data"]
        if state["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert state["status"] == "completed", state
    assert state["result"]["meta"]["status_counts"]["focus"] == 2 and state["matched"] == 2
    assert classify("POST", "/api/news/catalyst/start", MultiDict()) == "scan"
