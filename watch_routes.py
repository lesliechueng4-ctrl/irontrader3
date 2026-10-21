"""
长线观察接口。

GET /api/watch          研究数据：方向判断、风停信号、龙头标的、同花顺分组（来自 data/longterm_watch.json）
GET /api/watch/quotes   A 股龙头的实时行情 + 年内涨幅（腾讯行情 + 腾讯日 K）

两个接口分开：研究数据是静态文件，页面先秒开；行情慢一点、可能失败，失败时只影响行情列（显示"暂无"）。
行情走 SwrCache：多人同时打开页面只向腾讯发一次请求；日 K 只用来找去年收盘价，6 小时刷新一次。
"""

from __future__ import annotations

import os
from datetime import datetime
from threading import Lock
from typing import Any, Callable, Dict, List, Tuple

from flask import Blueprint

import longterm_watch as lw
from api_response import fail, ok
from logger_config import get_logger
from single_flight_cache import SwrCache

logger = get_logger(__name__)

watch_bp = Blueprint("watch_routes", __name__)

QUOTE_CACHE = SwrCache(fresh_ttl=60, stale_ttl=1800)
BARS_CACHE = SwrCache(fresh_ttl=6 * 3600, stale_ttl=48 * 3600)


# ---------------------------------------------------------------------------
# 依赖（集中在这里，测试时整体替换）
# ---------------------------------------------------------------------------

def _client():
    import market_routes

    if market_routes.data_fetcher is None:
        raise RuntimeError("行情模块还没初始化")
    return market_routes.data_fetcher.source_client


def _quotes(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    return lw.fetch_tencent_quotes(_client(), codes)


def _bars(codes: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    from signal_journal import tencent_bars

    client = _client()
    return lw.fetch_year_bars(lambda code: tencent_bars(client, code, count=260), codes)


def _now() -> datetime:
    from signal_journal import now_sh

    return now_sh()


DEPS: Dict[str, Callable] = {
    "path": lw.data_path, "quotes": _quotes, "bars": _bars, "now": _now,
}


# ---------------------------------------------------------------------------
# 研究数据（按文件修改时间缓存，月度更新后 git pull 即生效，不用重启）
# ---------------------------------------------------------------------------

_doc_lock = Lock()
_doc_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def load_doc() -> Dict[str, Any]:
    path = DEPS["path"]()
    mtime = os.path.getmtime(path)
    key = str(path)
    with _doc_lock:
        hit = _doc_cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    doc = lw.load(path)
    with _doc_lock:
        _doc_cache[key] = (mtime, doc)
    return doc


def clear_caches() -> None:
    QUOTE_CACHE.clear()
    BARS_CACHE.clear()
    with _doc_lock:
        _doc_cache.clear()


@watch_bp.get("/api/watch")
def watch_overview():
    try:
        doc = load_doc()
    except FileNotFoundError:
        return fail("长线观察数据文件不存在（data/longterm_watch.json）", status=404, code="WATCH_DATA_MISSING")
    except (lw.WatchDataError, ValueError) as exc:
        logger.warning(f"长线观察数据文件有误: {exc}")
        return fail(f"长线观察数据文件有误：{exc}", status=500, code="WATCH_DATA_INVALID")
    data = {**doc, "groups": lw.build_groups(doc)}
    return ok(data, meta={"as_of": doc["as_of"], "count": len(doc["leaders"])})


@watch_bp.get("/api/watch/quotes")
def watch_quotes():
    try:
        doc = load_doc()
    except (OSError, ValueError) as exc:
        return fail(f"长线观察数据读取失败：{exc}", status=500, code="WATCH_DATA_INVALID")

    codes = lw.a_share_codes(doc)
    if not codes:
        return ok({}, meta={"as_of": None, "available": 0})

    def build_quotes():
        quotes = DEPS["quotes"](codes)
        if not quotes:
            raise RuntimeError("腾讯行情没有返回数据")
        return {"quotes": quotes, "fetched_at": DEPS["now"]().strftime("%Y-%m-%d %H:%M:%S")}

    stale = False
    cached = False
    try:
        quote_pack, state = QUOTE_CACHE.get(("quotes", tuple(codes)), build_quotes)
        stale = state == "stale"
        cached = state != "built"
    except Exception as exc:
        logger.warning(f"长线观察行情获取失败: {exc}")
        quote_pack = {"quotes": {}, "fetched_at": None}

    try:
        bars, _ = BARS_CACHE.get(("bars", tuple(codes)), lambda: DEPS["bars"](codes))
    except Exception as exc:
        logger.warning(f"长线观察日K获取失败: {exc}")
        bars = {}

    today = DEPS["now"]().date()
    rows = lw.merge_quotes(codes, quote_pack["quotes"], bars, today)
    available = sum(1 for r in rows.values() if r["available"])
    meta: Dict[str, Any] = {"as_of": quote_pack["fetched_at"], "available": available, "count": len(codes)}
    if stale:
        meta["stale"] = True
    if cached:
        meta["cached"] = True
    return ok(rows, meta=meta)


__all__ = ["BARS_CACHE", "DEPS", "QUOTE_CACHE", "clear_caches", "load_doc", "watch_bp"]
