"""本次新增的运维清理与路由行为测试（离线）。"""
import os
import time

import app as app_module
from cache_manager import CacheManager
from logger_config import cleanup_legacy_logs


def test_home_serves_frontend_and_legacy_redirects(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>v2</html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(app_module, "_WEB_DIST", tmp_path)
    client = app_module.app.test_client()

    for path in ("/", "/scanners", "/research", "/backtest"):
        resp = client.get(path)
        assert resp.status_code == 200 and b"v2" in resp.data, path
        assert "no-cache" in resp.headers.get("Cache-Control", "")
    assert client.get("/assets/app.js").status_code == 200

    legacy = client.get("/legacy")
    assert legacy.status_code == 301 and legacy.headers["Location"].endswith("/")
    # 旧版静态资源已下线，不再提供 /static
    assert client.get("/static/app.js").status_code == 404


def test_old_v2_links_redirect_to_home_with_query():
    client = app_module.app.test_client()
    resp = client.get("/v2?stock=002713&name=x")
    assert resp.status_code == 301
    assert resp.headers["Location"].endswith("/?stock=002713&name=x")
    assert client.get("/v2/").headers["Location"].endswith("/")
    assert client.get("/v2/scanners").headers["Location"].endswith("/scanners")


def test_api_routes_are_not_shadowed_by_frontend():
    resp = app_module.app.test_client().get("/api/definitely-not-a-route")
    assert resp.status_code == 404 and resp.is_json


def test_json_errors_keep_chinese_readable():
    client = app_module.app.test_client()
    resp = client.get("/api/definitely-not-a-route")
    assert resp.status_code == 404
    assert "\\u" not in resp.get_data(as_text=True)


def test_cleanup_legacy_logs_only_removes_old_dated_files(tmp_path):
    old = tmp_path / "irontrader_20260601.log"
    fresh = tmp_path / "irontrader_20260927.log"
    rolling = tmp_path / "irontrader.log.3"
    for f in (old, fresh, rolling):
        f.write_text("x" * 10, encoding="utf-8")
    past = time.time() - 30 * 86400
    os.utime(old, (past, past))
    os.utime(rolling, (past, past))

    removed, freed = cleanup_legacy_logs(retention_days=14, log_dir=tmp_path)

    assert removed == 1 and freed == 10
    assert not old.exists()
    assert fresh.exists() and rolling.exists()


def test_cleanup_legacy_logs_disabled_with_zero(tmp_path):
    old = tmp_path / "irontrader_20260601.log"
    old.write_text("x", encoding="utf-8")
    past = time.time() - 30 * 86400
    os.utime(old, (past, past))
    assert cleanup_legacy_logs(retention_days=0, log_dir=tmp_path) == (0, 0)
    assert old.exists()


def test_clear_stale_temp_files(tmp_path):
    cm = CacheManager(cache_dir=str(tmp_path), cleanup_legacy=False, secret_key=b"k" * 32)
    stale = tmp_path / "stock_realtime_600519.tmp.8096_1790254913689"
    recent = tmp_path / "stock_realtime_600519.tmp.8096_1790999999999"
    keep = tmp_path / "stock_realtime_600519.pkl"
    for f in (stale, recent, keep):
        f.write_bytes(b"x")
    past = time.time() - 2 * 3600
    os.utime(stale, (past, past))

    assert cm.clear_stale_temp_files(max_age_sec=3600) == 1
    assert not stale.exists()
    assert recent.exists() and keep.exists()
