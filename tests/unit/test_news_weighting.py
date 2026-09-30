"""消息面计入低吸与龙头（方案 C）。"""
from unittest.mock import patch

import app as app_module  # noqa: F401  导入即完成 market_routes 的初始化
import market_routes as routes
from low_buy_engine import LowBuyEngine
from news_weighting import apply_dragon_news, dragon_news_effect, lowbuy_news_dimension


def _news(score, events=(), label=None):
    return {"score": score, "label": label or ("偏利空" if score < 0 else "偏利好"), "summary": "",
            "alerts": [], "events": list(events), "sources": {"announcement": {"ok": True}, "news": {"ok": True}}}


def _ev(type_, direction, level, elapsed=0, active=True, label="事件"):
    return {"type": type_, "type_label": label, "direction": direction, "level": level,
            "sessions_elapsed": elapsed, "active": active, "title": label}


# ---------------- 低吸第六维 ----------------

def test_negative_news_is_heavily_penalised_and_capped():
    assert lowbuy_news_dimension(_news(-66), {})["adjustment"] == -16.5
    assert lowbuy_news_dimension(_news(-100), {})["adjustment"] == -25


def test_positive_news_adds_little_and_is_capped():
    assert lowbuy_news_dimension(_news(38), {"change_pct": 1})["adjustment"] == 3.0
    assert lowbuy_news_dimension(_news(100), {"change_pct": 1})["adjustment"] == 8


def test_positive_news_already_priced_in_adds_nothing():
    dim = lowbuy_news_dimension(_news(66), {"change_pct": 6.2})
    assert dim["priced_in"] and dim["adjustment"] == 0 and "已兑现" in dim["note"]
    dim = lowbuy_news_dimension(_news(66), {"change_pct": 3, "is_limit_up": True})
    assert dim["priced_in"] and "涨停" in dim["note"]
    # 利空不存在"兑现"：当天涨了也照样扣分
    assert lowbuy_news_dimension(_news(-40), {"change_pct": 6})["adjustment"] < 0


def test_missing_news_does_not_move_score():
    dim = lowbuy_news_dimension(None, {})
    assert not dim["available"] and dim["adjustment"] == 0 and "暂无" in dim["note"]


class _Fetcher:
    def _normalize_code(self, code):
        return str(code).zfill(6)

    def get_stock_realtime(self, code):
        return {"code": code, "name": "测试股票", "current": 10.0, "change_pct": 1.0}

    def get_data_source_health(self):
        return {}


def _engine(news_provider=None):
    engine = object.__new__(LowBuyEngine)
    engine.fetcher = _Fetcher()
    engine._get_sentiment = lambda: {"score": 50, "phase": "分歧", "details": {}}
    engine.sector_scorer = type("S", (), {"score_sector": lambda *_: {"score": 80}})()
    engine.fund_analyzer = type("F", (), {"analyze": lambda *_: {"score": 80}})()
    engine.technical_scorer = type("T", (), {"score": lambda *_: {"score": 80, "support_level": 9.9}})()
    engine.fundamental_scorer = type("Fu", (), {"score": lambda *_: {"score": 80}})()
    engine.INTENDED_SINGLE = {"低吸": 0.20, "观察": 0.10}
    engine.news_provider = news_provider
    return engine


def test_engine_applies_news_adjustment_before_sentiment_coefficient():
    base = _engine().analyze("1", emotion_snapshot={})
    assert base["total_score"] == 80 and base["decision"] == "低吸"
    assert base["dimensions"]["news"]["available"] is False

    hit = _engine(lambda code, name: _news(-66, label="利空明显")).analyze("1", emotion_snapshot={})
    assert hit["news_adjustment"] == -16.5
    assert hit["stock_score"] == 80  # 四维分本身不变
    assert hit["total_score"] == 63.5 and hit["decision"] == "观察"
    assert "扣 16.5 分" in hit["dimensions"]["news"]["note"]


def test_explicit_news_argument_wins_over_provider():
    engine = _engine(lambda *_: (_ for _ in ()).throw(AssertionError("provider must not run")))
    result = engine.analyze("1", emotion_snapshot={}, news=_news(0, label="中性"))
    assert result["news_adjustment"] == 0 and result["dimensions"]["news"]["available"]


def test_scan_uses_prefetched_bulk_news():
    engine = _engine(lambda *_: (_ for _ in ()).throw(AssertionError("single lookup during scan")))
    engine._scan_news = {"000001": _news(-40)}
    assert engine.analyze("1", emotion_snapshot={})["news_adjustment"] == -10
    engine._scan_news = {}
    assert engine.analyze("1", emotion_snapshot={})["dimensions"]["news"]["available"] is False


# ---------------- 龙头信心 ----------------

def test_fresh_catalyst_raises_dragon_confidence():
    news = _news(40, [_ev("control_change", 1, "major", elapsed=0, label="控制权变更")])
    out = apply_dragon_news({"decision": "BUY", "confidence": 3}, news)
    assert out["confidence"] == 4 and "新催化" in out["news_effect"]["note"]


def test_old_catalyst_does_not_count():
    news = _news(20, [_ev("big_contract", 1, "notable", elapsed=3)])
    assert dragon_news_effect(news)["delta"] == 0


def test_risk_signals_lower_confidence_but_never_change_decision():
    news = _news(-70, [
        _ev("reduce_plan", -1, "notable", label="股东减持计划"),
        _ev("reduce_plan", -1, "notable", label="股东减持计划"),  # 同类只算一次
        _ev("inquiry", -1, "minor", label="问询函"),
    ])
    effect = dragon_news_effect(news)
    assert effect["delta"] == -2 and len(effect["risks"]) == 2
    out = apply_dragon_news({"decision": "BUY", "confidence": 2}, news)
    assert out["decision"] == "BUY" and out["confidence"] == 1  # 下限 1 星

    ignored = apply_dragon_news({"decision": "IGNORE", "confidence": 3}, news)
    assert ignored["confidence"] == 3 and ignored["news_effect"]["delta"] == -2


def test_unified_analyze_passes_same_news_to_both_engines():
    calls = []

    def lookup(code, name):
        calls.append(code)
        return _news(-66, [_ev("investigation", -1, "major", label="立案调查")])

    dragon = {"decision": "BUY", "confidence": 4, "stock_info": {"code": "600000", "name": "测试"},
              "market_state": {"can_trade": True}}
    with patch.object(routes, "_news_lookup", lookup), \
            patch.object(routes, "_get_emotion_result", return_value={}), \
            patch.object(routes.decision_maker, "make_decision", return_value=dragon), \
            patch.object(routes, "_get_low_buy_engine_fn") as get_lowbuy:
        get_lowbuy.return_value.analyze.return_value = {"decision": "观察", "total_score": 60}
        body = app_module.app.test_client().get("/api/analyze/600000").get_json()

    assert calls == ["600000"]  # 只抓一次
    passed = get_lowbuy.return_value.analyze.call_args.kwargs["news"]
    assert passed["score"] == -66
    assert body["data"]["dragon"]["confidence"] == 2
    assert body["data"]["dragon"]["news_effect"]["risks"][0]["type"] == "investigation"
