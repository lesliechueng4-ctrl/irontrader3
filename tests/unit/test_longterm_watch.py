import json
from datetime import date, datetime

import pytest
from flask import Flask

import longterm_watch as lw
import watch_routes


def _tencent_line(market: str, code: str, name: str, price: str, prev: str, pct: str, pe: str, mv: str) -> str:
    parts = [""] * 50
    parts[0] = "1"
    parts[1] = name
    parts[2] = code
    parts[3] = price
    parts[4] = prev
    parts[30] = "20261021143000"
    parts[32] = pct
    parts[39] = pe
    parts[45] = mv
    return f'v_{market}{code}="{"~".join(parts)}";\n'


def _doc():
    return {
        "schema": 1,
        "as_of": "2026-10-21",
        "takeaway": "一句话结论",
        "disclaimer": "不构成投资建议",
        "directions": [
            {"id": "space", "name": "商业航天", "short": "商业航天"},
            {"id": "aihw", "name": "AI 硬件瓶颈", "short": "AI 硬件"},
        ],
        "groups": [
            {"id": "space", "name": "长线·商业航天", "dir": "space"},
            {"id": "turbine", "name": "长线·燃机", "dir": "aihw"},
        ],
        "leaders": [
            {"id": "L1", "dir": "space", "name": "应流股份", "market": "sh", "code": "603308",
             "groups": ["space", "turbine"], "sources": ["https://a"]},
            {"id": "L2", "dir": "aihw", "name": "GE Vernova", "market": "us", "code": "GEV",
             "groups": ["turbine"], "sources": ["https://b"]},
            {"id": "L3", "dir": "aihw", "name": "杰瑞股份", "market": "sz", "code": "002353",
             "groups": ["turbine"], "sources": ["https://c"]},
            {"id": "L4", "dir": "space", "name": "蓝箭航天", "market": "unlisted", "code": None,
             "groups": [], "sources": ["https://d"]},
        ],
        "signals": [
            {"id": "S1", "dir": "space", "name": "发射次数", "lamp": "green", "sources": ["https://e"]},
        ],
    }


# ---------------------------------------------------------------------------
# 仓库里的数据文件（每月定时任务会改它，CI 在这里兜底）
# ---------------------------------------------------------------------------

def test_repo_data_file_is_valid():
    doc = json.loads(lw.data_path().read_text(encoding="utf-8"))
    assert lw.validate(doc) == []
    groups = lw.build_groups(doc)
    assert groups and all(g["codes"] for g in groups)  # 每个同花顺分组至少有一只能导入的 A 股


def test_validate_reports_broken_records():
    doc = _doc()
    doc["signals"][0]["lamp"] = "绿"
    doc["leaders"][0]["code"] = "60330"
    doc["leaders"][2]["groups"] = ["nope"]
    problems = lw.validate(doc)
    assert any("灯只能是" in p for p in problems)
    assert any("不是 6 位数字" in p for p in problems)
    assert any("分组 nope 不存在" in p for p in problems)


# ---------------------------------------------------------------------------
# 同花顺分组与导入文本
# ---------------------------------------------------------------------------

def test_groups_split_importable_a_shares_from_manual_listings():
    groups = {g["id"]: g for g in lw.build_groups(_doc())}
    assert groups["space"]["codes"] == ["603308"]
    assert groups["turbine"]["codes"] == ["603308", "002353"]  # 一只票可以进多个分组
    assert groups["turbine"]["manual"] == [{"code": "GEV", "name": "GE Vernova", "market": "us"}]


def test_ths_import_text_is_one_code_per_line_with_crlf():
    assert lw.ths_import_text(["603308", "002353", "603308"]) == "603308\r\n002353\r\n"


def test_a_share_codes_skip_unlisted_and_overseas():
    assert lw.a_share_codes(_doc()) == ["603308", "002353"]


# ---------------------------------------------------------------------------
# 行情解析与年内涨幅
# ---------------------------------------------------------------------------

def test_parse_tencent_quotes_reads_fields_and_blanks_suspended():
    text = (_tencent_line("sh", "603308", "应流股份", "38.50", "37.00", "4.05", "61.2", "261.3")
            + _tencent_line("sz", "002353", "杰瑞股份", "0.00", "52.10", "0.00", "0", "533.1"))
    quotes = lw.parse_tencent_quotes(text)
    assert quotes["603308"]["price"] == 38.5
    assert quotes["603308"]["change_pct"] == 4.05
    assert quotes["603308"]["pe_ttm"] == 61.2
    assert quotes["603308"]["total_mv_yi"] == 261.3
    # 停牌：现价为 0 时不给现价和涨跌幅，市盈率 0 视为取不到
    assert quotes["002353"]["price"] is None and quotes["002353"]["change_pct"] is None
    assert quotes["002353"]["pe_ttm"] is None and quotes["002353"]["prev_close"] == 52.1


def test_ytd_uses_last_close_of_previous_year():
    bars = [{"date": "2025-12-30", "close": 9.0}, {"date": "2025-12-31", "close": 10.0},
            {"date": "2026-01-02", "close": 11.0}, {"date": "2026-10-20", "close": 14.0}]
    assert lw.ytd_change(bars, 15.0, date(2026, 10, 21)) == {"ytd_pct": 50.0, "ytd_note": None}
    # 没有现价时用最后一根日 K
    assert lw.ytd_change(bars, None, date(2026, 10, 21))["ytd_pct"] == 40.0


def test_ytd_for_stock_listed_this_year_is_not_faked():
    bars = [{"date": "2026-07-27", "close": 30.0}, {"date": "2026-10-20", "close": 45.0}]
    assert lw.ytd_change(bars, 45.0, date(2026, 10, 21)) == {"ytd_pct": None, "ytd_note": "今年上市"}
    assert lw.ytd_change([], 45.0, date(2026, 10, 21)) == {"ytd_pct": None, "ytd_note": "暂无日K"}


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------

@pytest.fixture
def watch_client(tmp_path, monkeypatch):
    path = tmp_path / "longterm_watch.json"
    path.write_text(json.dumps(_doc(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(watch_routes.DEPS, "path", lambda: path)
    monkeypatch.setitem(watch_routes.DEPS, "now", lambda: datetime(2026, 10, 21, 14, 30))
    app = Flask(__name__)
    app.register_blueprint(watch_routes.watch_bp)
    return app.test_client(), path


def test_overview_returns_groups_in_standard_envelope(watch_client):
    client, _ = watch_client
    body = client.get("/api/watch").get_json()
    assert body["success"] is True
    assert body["meta"]["as_of"] == "2026-10-21"
    turbine = next(g for g in body["data"]["groups"] if g["id"] == "turbine")
    assert turbine["codes"] == ["603308", "002353"]


def test_overview_reports_broken_data_file(watch_client):
    client, path = watch_client
    doc = _doc()
    doc["signals"][0]["lamp"] = "purple"
    path.write_text(json.dumps(doc), encoding="utf-8")
    watch_routes.clear_caches()
    resp = client.get("/api/watch")
    assert resp.status_code == 500
    assert resp.get_json()["error_code"] == "WATCH_DATA_INVALID"


def test_quotes_merge_live_quote_and_ytd(watch_client, monkeypatch):
    client, _ = watch_client
    calls = []

    def fake_quotes(codes):
        calls.append(list(codes))
        return lw.parse_tencent_quotes(_tencent_line("sh", "603308", "应流股份", "38.50", "37.00", "4.05", "61.2", "261.3"))

    monkeypatch.setitem(watch_routes.DEPS, "quotes", fake_quotes)
    monkeypatch.setitem(watch_routes.DEPS, "bars", lambda codes: {
        "603308": [{"date": "2025-12-31", "close": 35.0}, {"date": "2026-10-20", "close": 37.0}],
        "002353": [],
    })
    body = client.get("/api/watch/quotes").get_json()
    assert calls == [["603308", "002353"]]  # 只给 A 股取行情
    row = body["data"]["603308"]
    assert row["price"] == 38.5 and row["available"] is True
    assert row["ytd_pct"] == 10.0
    missing = body["data"]["002353"]
    assert missing["available"] is False and missing["price"] is None  # 取不到就是"暂无"
    assert body["meta"]["available"] == 1 and body["meta"]["count"] == 2

    client.get("/api/watch/quotes")
    assert len(calls) == 1  # 60 秒内多人打开共享同一次请求


def test_quotes_failure_leaves_fields_empty(watch_client, monkeypatch):
    client, _ = watch_client

    def boom(codes):
        raise RuntimeError("tencent down")

    monkeypatch.setitem(watch_routes.DEPS, "quotes", boom)
    monkeypatch.setitem(watch_routes.DEPS, "bars", boom)
    body = client.get("/api/watch/quotes").get_json()
    assert body["success"] is True
    assert body["meta"]["available"] == 0
    assert all(r["price"] is None and r["ytd_pct"] is None for r in body["data"].values())
