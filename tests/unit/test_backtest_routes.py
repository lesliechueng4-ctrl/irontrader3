import time
from unittest.mock import patch

from flask import Flask

import backtest_routes


def _client():
    app = Flask(__name__)
    app.register_blueprint(backtest_routes.backtest_bp)
    return app.test_client()


def test_rerun_is_single_flight_and_status_comes_from_task_store(isolated_task_store):
    client = _client()
    with patch.object(backtest_routes, "Thread") as thread:
        first = client.post("/api/backtest/rerun", json={"days": 5}).get_json()["data"]
        second = client.post("/api/backtest/rerun", json={"days": 5}).get_json()["data"]

    assert thread.call_count == 1  # 已有进行中的回测时不再启动第二个
    assert first["running"] is True and second["task_id"] == first["task_id"]

    isolated_task_store.update_task(
        first["task_id"], status="completed", result={"n": 1}, finished_at=time.time()
    )
    status = client.get("/api/backtest/status").get_json()["data"]
    assert status["running"] is False
    assert status["result"] == {"n": 1}
    assert status["finished"]


def test_status_without_any_backtest():
    data = _client().get("/api/backtest/status").get_json()["data"]
    assert data["running"] is False and data["result"] is None
