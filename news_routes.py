"""
消息面接口（观察模式，不影响任何买卖结论）。

GET /api/news/<code>?name=贵州茅台   个股消息面：公告 + 新闻、逐条定性、衰减加权后的分数
GET /api/news/radar                  全市场重大消息雷达（多人共享缓存，首次构建约 20–40 秒）
"""

from threading import Lock

from flask import Blueprint, request

from api_response import fail, ok
from exceptions import raise_if_invalid_stock_code
from logger_config import get_logger
from news_catalyst import NewsCatalystService
from single_flight_cache import SwrCache

logger = get_logger(__name__)

news_bp = Blueprint("news_routes", __name__)

# 个股：10 分钟内直接用缓存，1 小时内先给旧值再后台刷新
STOCK_CACHE = SwrCache(600, 3600)
# 雷达：翻几十页全市场公告，10 分钟刷新一次，2 小时内都先给旧值
RADAR_CACHE = SwrCache(600, 7200)

_service = None
_service_lock = Lock()


def get_service() -> NewsCatalystService:
    global _service
    with _service_lock:
        if _service is None:
            _service = NewsCatalystService()
        return _service


def set_service(service) -> None:
    """测试用：注入假的数据源。"""
    global _service
    with _service_lock:
        _service = service


@news_bp.route("/api/news/radar")
def news_radar():
    builder = lambda: get_service().radar()  # noqa: E731
    try:
        if request.args.get("refresh") == "1":
            data = builder()
            RADAR_CACHE.put("radar", data)
            state = "built"
        else:
            data, state = RADAR_CACHE.get("radar", builder)
    except Exception as exc:
        logger.warning(f"[news] 重大消息雷达构建失败: {exc}")
        return fail(f"公告数据暂时取不到：{exc}", status=503, code="NEWS_UNAVAILABLE")
    return ok(data, meta={"as_of": data.get("as_of"), "cached": state != "built", "stale": state == "stale"})


@news_bp.route("/api/news/<code>")
def stock_news(code):
    raise_if_invalid_stock_code(code)
    name = (request.args.get("name") or "").strip()[:12]
    builder = lambda: get_service().stock(code, name)  # noqa: E731
    try:
        if request.args.get("refresh") == "1":
            data = builder()
            STOCK_CACHE.put(code, data)
            state = "built"
        else:
            data, state = STOCK_CACHE.get(code, builder)
    except Exception as exc:
        logger.warning(f"[news] 个股消息面失败 {code}: {exc}")
        return fail(f"消息面数据暂时取不到：{exc}", status=503, code="NEWS_UNAVAILABLE")
    return ok(data, meta={"as_of": data.get("as_of"), "cached": state != "built", "stale": state == "stale"})
