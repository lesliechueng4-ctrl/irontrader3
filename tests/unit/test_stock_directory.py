import json
import threading
import time

from flask import Flask

import market_routes
import stock_directory as sd


def test_builds_from_primary_merges_supplement_and_persists(tmp_path):
    path = tmp_path / "stock_directory.json"
    directory = sd.StockDirectory(
        path,
        primary=[("新浪", lambda: [{"code": "600276", "name": "恒瑞医药"}, {"code": "2080", "name": "中材科技"}])],
        supplements=[("北交所", lambda: [{"code": "920001", "name": "北交甲"}])],
    )
    assert directory.items(wait=5) is not None
    results, ready = directory.search("中材", limit=10)
    assert ready and results == [{"code": "002080", "name": "中材科技", "market": "SZ"}]
    assert directory.search("92", limit=10)[0][0]["market"] == "BJ"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved["items"]) == 3 and saved["source"] == "新浪 + 北交所"

    # 重启（新实例）直接读落盘文件，不再调用任何数据源
    def boom():
        raise AssertionError("不应再去下载名单")

    restored = sd.StockDirectory(path, primary=[("新浪", boom)])
    assert restored.search("恒瑞", limit=10)[0][0]["code"] == "600276"


def test_falls_back_to_next_primary_when_first_fails(tmp_path):
    def sina_down():
        raise RuntimeError("新浪挂了")

    directory = sd.StockDirectory(
        tmp_path / "d.json",
        primary=[("新浪", sina_down), ("交易所名单", lambda: [{"code": "600000", "name": "浦发银行"}])],
    )
    results, ready = directory.search("浦发", limit=10)
    assert ready and results[0]["code"] == "600000"


def test_search_never_blocks_longer_than_wait_and_builds_once(tmp_path):
    started = []
    release = threading.Event()

    def slow():
        started.append(1)
        release.wait(5)
        return [{"code": "600276", "name": "恒瑞医药"}]

    directory = sd.StockDirectory(tmp_path / "d.json", primary=[("新浪", slow)])
    t0 = time.monotonic()
    assert directory.items(wait=0.2) is None          # 名单没好：等一小会儿就先返回
    assert time.monotonic() - t0 < 1.0
    assert directory.items(wait=0.1) is None          # 第二次请求不会再起一个构建
    release.set()
    for _ in range(50):
        if directory.items(wait=0.1):
            break
        time.sleep(0.05)
    assert directory.items(wait=0)[0]["code"] == "600276"
    assert len(started) == 1


def test_expired_list_is_served_while_rebuilding(tmp_path):
    path = tmp_path / "d.json"
    old = time.time() - sd.MAX_AGE - 10
    path.write_text(json.dumps({"ts": old, "source": "新浪", "items": [{"code": "600276", "name": "恒瑞医药"}]}),
                    encoding="utf-8")
    rebuilt = threading.Event()

    def fresh():
        rebuilt.set()
        return [{"code": "600276", "name": "恒瑞医药"}, {"code": "688825", "name": "长鑫科技"}]

    directory = sd.StockDirectory(path, primary=[("新浪", fresh)])
    assert directory.items(wait=0)[0]["code"] == "600276"   # 先给旧名单
    assert rebuilt.wait(5)                                   # 后台重建
    for _ in range(50):
        if len(directory.items(wait=0)) == 2:
            break
        time.sleep(0.05)
    assert len(directory.items(wait=0)) == 2


def test_search_route_returns_empty_with_ready_flag_instead_of_hanging(monkeypatch, tmp_path):
    def never():
        time.sleep(5)
        return []

    monkeypatch.setattr(market_routes, "_DIRECTORY", sd.StockDirectory(tmp_path / "d.json", primary=[("新浪", never)]))
    monkeypatch.setattr(sd, "WAIT_SECONDS", 0.2)
    app = Flask(__name__)
    app.register_blueprint(market_routes.market_bp)
    t0 = time.monotonic()
    body = app.test_client().get("/api/search?q=600").get_json()
    assert time.monotonic() - t0 < 1.5
    assert body["success"] is True and body["data"] == [] and body["meta"] == {"ready": False}


def test_search_route_requires_query():
    app = Flask(__name__)
    app.register_blueprint(market_routes.market_bp)
    resp = app.test_client().get("/api/search?q=")
    assert resp.status_code == 400 and resp.get_json()["success"] is False
