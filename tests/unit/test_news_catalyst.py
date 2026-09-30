from datetime import date, datetime

import pytest
from flask import Flask
from werkzeug.datastructures import MultiDict

import news_routes
from news_catalyst import (
    NewsCatalystService,
    aggregate,
    classify,
    parse_em_announcement,
    reaction_date,
    score_event,
    sessions_elapsed,
    TZ,
)
from rate_limit import classify as classify_request, owner_only

# 2026 国庆：10-01 ~ 10-08 休市
HOLIDAYS = {date(2026, 10, d) for d in range(1, 9)}


def checker(day):
    return day not in HOLIDAYS


@pytest.mark.parametrize("title, expected", [
    ("关于公司收到中国证券监督管理委员会立案告知书的公告", ("investigation", -1, "major")),
    ("关于诉讼事项被法院立案受理的公告", ("lawsuit", -1, "minor")),
    ("关于公司股票可能被终止上市的风险提示公告", ("delisting", -1, "major")),
    ("关于申请撤销其他风险警示的公告", ("st_removed", 1, "major")),
    ("关于控股股东筹划控制权变更暨停牌的公告", ("control_change", 1, "major")),
    ("发行股份及支付现金购买资产并募集配套资金预案", ("restructure", 1, "major")),
    ("关于本次交易符合《上市公司重大资产重组管理办法》第十一条规定的说明", ("other", 0, "noise")),
    ("关于终止筹划重大资产重组的公告", ("restructure_stopped", -1, "notable")),
    ("2026年前三季度业绩预增公告", ("earnings_up", 1, "notable")),
    ("2026年前三季度业绩预亏公告", ("earnings_down", -1, "notable")),
    ("2026年前三季度业绩预告", ("earnings_preview", 0, "notable")),
    ("关于持股5%以上股东减持股份计划的预披露公告", ("reduce_plan", -1, "notable")),
    ("关于持股5%以上股东减持计划期限届满暨减持结果的公告", ("reduce_progress", -1, "minor")),
    ("关于控股股东提前终止减持计划的公告", ("reduce_stopped", 1, "minor")),
    ("关于签订募集资金三方监管协议的公告", ("other", 0, "noise")),
    ("关于全资子公司签订重大销售合同的公告", ("big_contract", 1, "notable")),
    ("关于获得药品注册证书的公告", ("approval", 1, "notable")),
    ("关于最近五年不存在被证券监管部门处罚的公告", ("other", 0, "noise")),
    ("关于控股股东部分股份解除质押的公告", ("other", 0, "noise")),
    ("股东大会决议公告", ("other", 0, "noise")),
])
def test_classify_titles(title, expected):
    c = classify(title)
    assert (c["type"], c["direction"], c["level"]) == expected


def test_follow_up_announcements_are_downgraded():
    c = classify("关于公司股票被实施其他风险警示相关事项的进展公告")
    assert c["type"] == "st" and c["level"] == "minor" and "后续进展" in c["type_label"]
    c = classify("关于公司股票可能因股价低于面值被终止上市的第八次风险提示公告")
    assert c["level"] == "minor"


def test_price_only_news_is_not_a_catalyst():
    c = classify("贵州茅台股价拉升翻红")
    assert c["level"] == "noise" and c["type_label"] == "价格异动报道"


def test_reaction_date_after_close_moves_to_next_day():
    assert reaction_date(datetime(2026, 9, 29, 14, 59, tzinfo=TZ)) == date(2026, 9, 29)
    assert reaction_date(datetime(2026, 9, 29, 21, 27, tzinfo=TZ)) == date(2026, 9, 30)


def test_holiday_news_waits_for_first_session():
    effective = reaction_date(datetime(2026, 9, 30, 17, 0, tzinfo=TZ))  # 节前最后一天盘后
    assert sessions_elapsed(effective, date(2026, 10, 3), checker) == -1   # 长假中：待反应
    assert sessions_elapsed(effective, date(2026, 10, 9), checker) == 0    # 节后首日
    assert sessions_elapsed(effective, date(2026, 10, 12), checker) == 1   # 跳过周末


def _event(title, day, source="announcement", **kw):
    return {"source": source, "title": title, "effective_date": day, "id": title + source, **classify(title), **kw}


def test_major_negative_dominates_and_decays():
    today = date(2026, 9, 30)
    fresh = score_event(_event("关于收到中国证监会立案告知书的公告", date(2026, 9, 30)), today, checker)
    assert fresh["decay"] == 1 and fresh["contribution"] == -40 and fresh["active"]
    old = score_event(_event("关于收到中国证监会立案告知书的公告", date(2026, 9, 16)), today, checker)
    assert 0 < old["decay"] < 1 and old["contribution"] > -40

    agg = aggregate([fresh])
    assert agg["score"] == -66 and agg["label"] == "利空明显"
    assert agg["alerts"][0]["type"] == "investigation"
    assert "重大利空" in agg["summary"]


def test_reposts_of_same_event_do_not_stack():
    today = date(2026, 9, 30)
    ann = score_event(_event("关于全资子公司签订重大销售合同的公告", today), today, checker)
    news = score_event(_event("行云科技：签订重大销售合同", today, source="news"), today, checker)
    assert news["contribution"] == ann["contribution"] / 2  # 媒体报道权重减半
    single = aggregate([ann])["raw"]
    both = aggregate([ann, news])["raw"]
    assert both == pytest.approx(single + 0.25 * news["contribution"])


def test_unknown_direction_is_flagged_for_review_not_scored():
    today = date(2026, 9, 30)
    e = score_event(_event("2026年前三季度业绩预告", today), today, checker)
    agg = aggregate([e])
    assert agg["score"] == 0 and agg["review"] and "看正文" in agg["summary"]


def test_parse_eastmoney_market_item_prefers_a_share_code():
    item = {
        "art_code": "AN1",
        "codes": [{"stock_code": "113049", "short_name": "长汽转债"}, {"stock_code": "000625", "short_name": "长安汽车"}],
        "columns": [{"column_name": "董事会决议公告"}],
        "display_time": "2026-09-29 21:27:00:123",
        "notice_date": "2026-09-30 00:00:00",
        "title": "长安汽车:关于控股股东筹划控制权变更的公告",
    }
    ev = parse_em_announcement(item)
    assert ev["code"] == "000625" and ev["title"].startswith("关于")
    assert ev["effective_date"] == date(2026, 9, 30) and ev["type"] == "control_change"
    assert ev["url"].endswith("/000625/AN1.html")


class FakeFetcher:
    def __init__(self, anns=None, news=None, market=None, fail_ann=False, fail_news=False):
        self._anns, self._news, self._market = anns or [], news or [], market or []
        self.fail_ann, self.fail_news = fail_ann, fail_news
        self.news_name = None

    def announcements(self, code, since):
        if self.fail_ann:
            raise RuntimeError("东财超时")
        return [a for a in self._anns if a["effective_date"] >= since], "测试股份"

    def news(self, code, name, since):
        self.news_name = name
        if self.fail_news:
            raise RuntimeError("资讯超时")
        return self._news

    def market_announcements(self, begin, end):
        self.window = (begin, end)
        return self._market, True


def _service(fetcher, today=datetime(2026, 9, 30, 20, 0, tzinfo=TZ)):
    return NewsCatalystService(fetcher=fetcher, checker=checker, clock=lambda: today)


def test_stock_uses_announcement_name_for_news_and_survives_one_source_failing():
    anns = [{**_event("关于收到中国证监会立案告知书的公告", date(2026, 9, 30)), "code": "600001",
             "published_at": "2026-09-29 21:00"}]
    fetcher = FakeFetcher(anns=anns, fail_news=True)
    data = _service(fetcher).stock("600001")
    assert fetcher.news_name == "测试股份" and data["name"] == "测试股份"
    assert data["sources"]["announcement"]["ok"] and not data["sources"]["news"]["ok"]
    assert data["score"] < 0 and data["alerts"][0]["title"].startswith("关于收到")
    assert data["mode"] == "observe"
    assert "columns" not in data["events"][0]  # 只返回公开字段


def test_stock_raises_when_all_sources_fail():
    with pytest.raises(RuntimeError):
        _service(FakeFetcher(fail_ann=True, fail_news=True)).stock("600001", "测试股份")


def test_radar_groups_same_company_event_and_sorts_major_first():
    today = date(2026, 9, 30)
    market = [
        {**_event("关于获得药品注册证书的公告", today), "code": "600002", "name": "乙", "published_at": "2026-09-29 18:00"},
        {**_event("发行股份购买资产预案", today), "code": "600001", "name": "甲", "published_at": "2026-09-29 19:00"},
        {**_event("发行股份购买资产报告书(草案)", today), "code": "600001", "name": "甲", "published_at": "2026-09-29 19:01"},
        {**_event("股东大会决议公告", today), "code": "600003", "name": "丙", "published_at": "2026-09-29 19:02"},
    ]
    fetcher = FakeFetcher(market=market)
    data = _service(fetcher).radar()
    assert [e["code"] for e in data["events"]] == ["600001", "600002"]
    assert data["events"][0]["related"] == 1
    assert data["counts"] == {"major_up": 1, "major_down": 0, "notable": 1, "scanned": 4}


def test_radar_window_covers_long_holiday():
    fetcher = FakeFetcher()
    data = _service(fetcher, today=datetime(2026, 10, 3, 10, 0, tzinfo=TZ)).radar()
    assert data["window"]["reaction_day"] == "2026-10-09"
    assert fetcher.window[0] == date(2026, 10, 3) and fetcher.window[1] >= date(2026, 10, 9)


def _client(service):
    news_routes.set_service(service)
    app = Flask(__name__)
    app.register_blueprint(news_routes.news_bp)
    return app.test_client()


def test_routes_use_envelope_and_report_unavailable():
    anns = [{**_event("关于获得药品注册证书的公告", date(2026, 9, 30)), "code": "600001", "published_at": "x"}]
    try:
        client = _client(_service(FakeFetcher(anns=anns)))
        body = client.get("/api/news/600001?name=测试股份").get_json()
        assert body["success"] and body["data"]["score"] > 0 and body["meta"]["cached"] is False
        assert client.get("/api/news/600001").get_json()["meta"]["cached"] is True

        client = _client(_service(FakeFetcher(fail_ann=True, fail_news=True)))
        resp = client.get("/api/news/600009?name=x")
        assert resp.status_code == 503 and resp.get_json()["error_code"] == "NEWS_UNAVAILABLE"
    finally:
        news_routes.set_service(None)


def test_rate_limit_rules_for_news():
    assert classify_request("GET", "/api/news/600519", MultiDict()) == "news"
    assert classify_request("GET", "/api/news/radar", MultiDict()) == "api"
    assert owner_only("GET", "/api/news/radar", MultiDict({"refresh": "1"}))
    assert owner_only("GET", "/api/news/radar", MultiDict()) is None
