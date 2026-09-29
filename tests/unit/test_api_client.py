"""
Unit tests for Flask API endpoints using test_client (CI ready, no live 127.0.0.1:5002 needed)
"""

from unittest.mock import MagicMock, patch
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_root_page(client, tmp_path, monkeypatch):
    # web/dist 是构建产物（不进 Git），这里用临时的入口页代替，只验证首页路由可用
    import app as app_module

    (tmp_path / "index.html").write_text("<!DOCTYPE html><title>IronTrader</title>", encoding="utf-8")
    monkeypatch.setattr(app_module, "_WEB_DIST", tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    text = response.data.decode("utf-8")
    assert "IronTrader" in text or "DOCTYPE html" in text


def test_market_state_endpoint(client):
    with patch("app.decision_maker.risk_engine.get_market_state", return_value={
        "state": "震荡",
        "can_trade": True,
        "suggestion": "轻仓操作"
    }):
        response = client.get("/api/market-state")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["data"]["state"] == "震荡"


def test_hot_sectors_endpoint(client):
    fake_pool = [
        {"code": "000001", "name": "平安银行", "sector": "银行"},
        {"code": "600036", "name": "招商银行", "sector": "银行"},
        {"code": "600519", "name": "贵州茅台", "sector": "白酒"},
    ]
    with patch("app.data_fetcher.get_limit_up_pool", return_value=fake_pool):
        response = client.get("/api/hot-sectors")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert len(data["data"]) == 2
        assert data["data"][0]["name"] == "银行"
        assert data["data"][0]["count"] == 2


def test_backtest_status_endpoint(client):
    response = client.get("/api/backtest/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert "running" in data["data"]


def test_lowbuy_sentiment_endpoint(client):
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = {"cycle": "上升期", "score": 80}
    with patch("lowbuy_routes._get_low_buy_engine") as mock_engine_getter:
        mock_engine = MagicMock()
        mock_engine.sentiment_analyzer = mock_analyzer
        mock_engine_getter.return_value = mock_engine

        response = client.get("/api/lowbuy/sentiment")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["data"]["cycle"] == "上升期"
