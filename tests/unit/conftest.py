"""单元测试公共夹具。"""
import pytest

import backtest_routes
import lowbuy_routes
import market_routes
import scanner_routes
from task_manager import TaskManager


@pytest.fixture(autouse=True)
def isolated_task_store(tmp_path, monkeypatch):
    """每个测试使用独立的临时任务库，不写入项目 outputs/tasks.db。"""
    tm = TaskManager(db_path=tmp_path / "tasks.db")
    monkeypatch.setattr(scanner_routes, "_tasks", tm)
    monkeypatch.setattr(backtest_routes, "_tasks", tm)
    return tm


@pytest.fixture(autouse=True)
def fresh_dashboard_cache():
    """首页共享缓存跨测试会串数据：每个测试前后清空。"""
    market_routes.DASHBOARD_CACHE.clear()
    lowbuy_routes._SHARED.clear()
    yield
    market_routes.DASHBOARD_CACHE.clear()
    lowbuy_routes._SHARED.clear()
