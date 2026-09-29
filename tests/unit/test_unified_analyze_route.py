from unittest.mock import patch

import app as app_module
import market_routes as routes


def _emotion(*, data_as_of, as_of="2026-08-12 10:00:00"):
    return {
        "score": 80,
        "level": "高潮",
        "confidence": 0.9,
        "as_of": as_of,
        "data_as_of": data_as_of,
        "cached": False,
        "stale": False,
        "degraded": False,
        "position": {
            "can_open": True,
            "action": "允许开仓",
            "max_total_position": 0.5,
            "max_single_position": 0.1,
        },
    }


def _dragon():
    return {
        "decision": "IGNORE",
        "confidence": 0,
        "stock_info": {"code": "600000", "name": "测试", "is_limit_up": False},
        "market_state": {"can_trade": True},
    }


def _lowbuy():
    return {
        "decision": "低吸",
        "total_score": 80,
        "stock_code": "600000",
        "stock_name": "测试",
        "timestamp": "2026-08-12 10:00:00",
        "emotion_gate": {"can_open": True, "max_single_position": 0.1},
    }


def test_unified_analyze_marks_non_today_market_data_partial_and_stale():
    emotion = _emotion(data_as_of="2026-08-11 15:00:00")
    execution = {
        "mode": "live",
        "can_execute": False,
        "blockers": ["情绪数据非当日"],
        "position": {"can_open": True, "max_total_position": 0.5, "max_single_position": 0.1},
        "freshness": {
            "emotion_data_is_today": False,
            "emotion_stale": False,
            "emotion_degraded": False,
            "emotion_cached": False,
        },
    }

    with patch.object(routes, "_get_emotion_filter") as get_filter, \
            patch.object(routes.decision_maker, "make_decision", return_value=_dragon()), \
            patch.object(routes, "_get_low_buy_engine_fn") as get_lowbuy, \
            patch.object(routes, "build_execution_context", return_value=execution):
        get_filter.return_value.calculate_emotion_score.return_value = emotion
        get_lowbuy.return_value.analyze.return_value = _lowbuy()
        response = app_module.app.test_client().get("/api/analyze/600000")

    assert response.status_code == 200
    conclusion = response.get_json()["data"]["final_conclusion"]
    assert conclusion["data"] == {
        "status": "partial",
        "freshness": "stale",
        "as_of": "2026-08-11 15:00:00",
    }
    assert conclusion["status"] != "EXECUTABLE"


def test_unified_analyze_uses_data_timestamp_when_data_is_current():
    emotion = _emotion(data_as_of="2026-08-12 09:59:00")
    execution = {
        "mode": "live",
        "can_execute": True,
        "blockers": [],
        "position": {"can_open": True, "max_total_position": 0.5, "max_single_position": 0.1},
        "freshness": {
            "emotion_data_is_today": True,
            "emotion_stale": False,
            "emotion_degraded": False,
            "emotion_cached": False,
        },
    }

    with patch.object(routes, "_get_emotion_filter") as get_filter, \
            patch.object(routes.decision_maker, "make_decision", return_value=_dragon()), \
            patch.object(routes, "_get_low_buy_engine_fn") as get_lowbuy, \
            patch.object(routes, "build_execution_context", return_value=execution):
        get_filter.return_value.calculate_emotion_score.return_value = emotion
        get_lowbuy.return_value.analyze.return_value = _lowbuy()
        response = app_module.app.test_client().get("/api/analyze/600000")

    conclusion = response.get_json()["data"]["final_conclusion"]
    assert conclusion["data"] == {
        "status": "complete",
        "freshness": "live",
        "as_of": "2026-08-12 09:59:00",
    }
