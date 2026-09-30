"""
消息面接口。

GET /api/news/<code>?name=贵州茅台   个股消息面：公告 + 新闻、逐条定性、衰减加权后的分数
GET /api/news/radar                  全市场重大消息雷达（多人共享缓存，首次构建约 20–40 秒）
POST /api/news/catalyst/start        消息催化扫描（后台任务，结果见 /api/scanners/jobs/<id>）
"""

import time
import traceback
from threading import Lock, Thread

from flask import Blueprint, request

import news_catalyst
import news_scanner
from api_response import fail, ok
from exceptions import raise_if_invalid_stock_code
from logger_config import get_logger

logger = get_logger(__name__)

news_bp = Blueprint("news_routes", __name__)

# 兼容旧引用（测试 conftest 清缓存用）
STOCK_CACHE = news_catalyst.STOCK_CACHE
RADAR_CACHE = news_catalyst.RADAR_CACHE
set_service = news_catalyst.set_service


def _meta(data, state):
    return {"as_of": data.get("as_of"), "cached": state != "built", "stale": state == "stale"}


@news_bp.route("/api/news/radar")
def news_radar():
    try:
        data, state = news_catalyst.get_radar(refresh=request.args.get("refresh") == "1")
    except Exception as exc:
        logger.warning(f"[news] 重大消息雷达构建失败: {exc}")
        return fail(f"公告数据暂时取不到：{exc}", status=503, code="NEWS_UNAVAILABLE")
    return ok(data, meta=_meta(data, state))


@news_bp.route("/api/news/<code>")
def stock_news(code):
    raise_if_invalid_stock_code(code)
    name = (request.args.get("name") or "").strip()[:12]
    try:
        data, state = news_catalyst.get_stock_news(code, name, refresh=request.args.get("refresh") == "1")
    except Exception as exc:
        logger.warning(f"[news] 个股消息面失败 {code}: {exc}")
        return fail(f"消息面数据暂时取不到：{exc}", status=503, code="NEWS_UNAVAILABLE")
    return ok(data, meta=_meta(data, state))


# ---------------------------------------------------------------------------
# 消息催化扫描（后台任务，复用选股雷达的任务存储与进度轮询）
# ---------------------------------------------------------------------------

_CATALYST_LOCK = Lock()


def _catalyst_inputs():
    """扫描要用的行情 / 涨停池 / 执行闸；集中在这里，测试时整体替换。"""
    import market_routes
    from workbench_service import build_execution_context

    fetcher = market_routes.data_fetcher
    try:
        zt_pool = fetcher.get_limit_up_pool() or []
    except Exception as exc:
        logger.warning(f"[news] 涨停池获取失败，主线判断按无数据处理: {exc}")
        zt_pool = []
    try:
        execution = build_execution_context(
            market_routes._get_emotion_result() or {}, market_state=market_routes._get_market_state()
        )
    except Exception as exc:
        logger.warning(f"[news] 执行闸计算失败，按未知处理: {exc}")
        execution = None
    return {
        "quote": fetcher.get_stock_realtime,
        "zt_pool": zt_pool,
        "execution": execution,
        "sector_of": lambda code: _industry_path(fetcher, code),
    }


_INDUSTRY_CACHE = {}


def _industry_path(fetcher, code):
    """东财 F10 的行业分级（如"化石能源-煤炭-煤炭开采洗选"），行业几乎不变，进程内永久缓存。"""
    if code in _INDUSTRY_CACHE:
        return _INDUSTRY_CACHE[code]
    market = "SH" if code.startswith(("6", "9")) else "BJ" if code.startswith(("4", "8")) else "SZ"
    try:
        res = fetcher.source_client.get(
            "eastmoney", "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax",
            params={"code": f"{market}{code}"}, headers={"User-Agent": "Mozilla/5.0"},
        )
        info = (res.response.json().get("jbzl") or [{}])[0] if res.ok else {}
        path = info.get("EM2016") or info.get("INDUSTRYCSRC1") or ""
    except Exception as exc:
        logger.info(f"[news] 行业获取失败 {code}: {exc}")
        path = ""
    if path:
        _INDUSTRY_CACHE[code] = path
    return path


def _run_catalyst_job(job_id):
    from scanner_routes import _scan_cancel_requested, _update_scan_job

    started = time.time()

    def progress(**updates):
        if _scan_cancel_requested(job_id):
            raise RuntimeError("用户已取消扫描")
        _update_scan_job(job_id, status="running", **updates)

    try:
        progress(phase="获取重大消息", message="正在读取全市场重大消息（首次约 20–40 秒）...", done=0, total=0)
        radar, _ = news_catalyst.get_radar()
        progress(phase="准备行情", message="正在读取涨停池与统一执行闸...", done=0, total=0)
        inputs = _catalyst_inputs()
        result = news_scanner.evaluate(radar, progress=progress, cancelled=lambda: _scan_cancel_requested(job_id),
                                       **inputs)
        result["elapsed_sec"] = round(time.time() - started, 1)
        counts = result["meta"]["status_counts"]
        _update_scan_job(
            job_id, status="completed", phase="已完成",
            message=f"利好消息 {result['meta']['scanned']} 条：关注 {counts['focus']}、等待 {counts['wait']}、"
                    f"已兑现 {counts['priced_in']}、买不进 {counts['blocked']}",
            done=result["meta"]["scanned"], total=result["meta"]["scanned"], matched=counts["focus"],
            errors=result["meta"]["errors"], result=result, finished_at=time.time(),
        )
    except Exception as exc:
        cancelled = "取消" in str(exc)
        if not cancelled:
            traceback.print_exc()
        _update_scan_job(
            job_id, status="cancelled" if cancelled else "failed", phase="已取消" if cancelled else "失败",
            message="扫描已取消" if cancelled else "消息催化扫描失败", error=str(exc), finished_at=time.time(),
        )
    finally:
        _CATALYST_LOCK.release()


@news_bp.route("/api/news/catalyst/start", methods=["POST"])
def catalyst_scan_start():
    from scanner_routes import _create_scan_job, _get_active_scan_job

    if not _CATALYST_LOCK.acquire(blocking=False):
        active = _get_active_scan_job("news_catalyst")
        return fail("消息催化扫描正在运行，请稍后再试", status=409, code="SCAN_BUSY",
                    job_id=active.get("id") if active else "", job=active)
    try:
        job = _create_scan_job("news_catalyst", params={}, cancel_supported=True)
        Thread(target=_run_catalyst_job, args=(job["id"],), daemon=True).start()
        return ok(job)
    except Exception:
        _CATALYST_LOCK.release()
        raise
