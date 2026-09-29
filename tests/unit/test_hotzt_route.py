from unittest.mock import patch

import app as app_module
import market_routes as routes


def _stocks():
    return [
        {
            "code": "000001",
            "name": "测试一",
            "seal_amount": 100,
            "limit_count": 2,
            "first_limit_time": "09:31:00",
            "sector": "测试",
        },
        {
            "code": "000002",
            "name": "测试二",
            "seal_amount": 200,
            "limit_count": 1,
            "first_limit_time": "09:32:00",
            "sector": "测试",
        },
    ]


def test_hotzt_is_lightweight_and_sorted_without_decision_engine():
    routes.data_fetcher.limit_up_pool_meta = {
        "as_of": "2026-08-12 10:00:00",
        "stale": False,
    }
    with patch.object(routes.data_fetcher, "get_limit_up_pool", return_value=_stocks()) as pool, \
            patch.object(routes.decision_maker, "batch_make_decision") as batch:
        response = app_module.app.test_client().get("/api/hotzt")

    payload = response.get_json()
    pool.assert_called_once_with(force_refresh=False)
    batch.assert_not_called()
    assert [item["code"] for item in payload["data"]] == ["000002", "000001"]
    assert payload["meta"]["as_of"] == "2026-08-12 10:00:00"
    assert payload["meta"]["stale"] is False


def test_hotzt_refresh_only_forces_source_refresh():
    routes.data_fetcher.limit_up_pool_meta = {}
    with patch.object(routes.data_fetcher, "get_limit_up_pool", return_value=_stocks()) as pool, \
            patch.object(routes.decision_maker, "make_decision") as decision:
        response = app_module.app.test_client().get("/api/hotzt?refresh=1")

    assert response.status_code == 200
    pool.assert_called_once_with(force_refresh=True)
    decision.assert_not_called()
