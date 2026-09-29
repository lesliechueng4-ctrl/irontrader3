"""
IronTrader Low-Buy Analysis Routes & Background Tasks
"""

import time
from threading import Lock, Thread
from flask import Blueprint, jsonify, request

from api_response import fail, ok
from single_flight_cache import SwrCache
from config import APIConfig
from exceptions import raise_if_invalid_stock_code
from logger_config import get_logger
from scanner_routes import (
    _create_scan_job,
    _get_active_scan_job,
    _get_scan_job,
    _scan_cancel_requested,
    _update_scan_job,
)

logger = get_logger(__name__)

lowbuy_bp = Blueprint("lowbuy_routes", __name__)

_low_buy_engine = None
_LOWBUY_CANDIDATES_LOCK = Lock()
_data_fetcher_getter = None


def init_lowbuy_routes(data_fetcher_getter):
    global _data_fetcher_getter
    _data_fetcher_getter = data_fetcher_getter


def _safe_error_text(value):
    return str(value).encode('gbk', errors='replace').decode('gbk')


def _get_low_buy_engine():
    global _low_buy_engine
    if _low_buy_engine is None:
        from low_buy_engine import LowBuyEngine
        df = _data_fetcher_getter() if _data_fetcher_getter else None
        _low_buy_engine = LowBuyEngine(df)
    return _low_buy_engine


@lowbuy_bp.route('/api/lowbuy/analyze', methods=['POST'])
def lowbuy_analyze():
    """单只股票低吸分析"""
    data = request.get_json() or {}
    code = data.get('code', '').strip()
    if not code:
        code = request.args.get('code', '').strip()
    raise_if_invalid_stock_code(code)

    engine = _get_low_buy_engine()
    result = engine.analyze(code)
    return jsonify({'success': True, 'data': result})


@lowbuy_bp.route('/api/lowbuy/batch', methods=['POST'])
def lowbuy_batch():
    """批量低吸分析"""
    data = request.get_json() or {}
    codes = data.get('codes', [])
    if not codes:
        return jsonify({'success': False, 'error': '请提供股票代码列表'}), 400
    codes = [str(c).strip() for c in codes]
    for c in codes:
        raise_if_invalid_stock_code(c)

    engine = _get_low_buy_engine()
    results = engine.batch_analyze(codes)
    return jsonify({'success': True, 'data': results, 'count': len(results)})


# 首页轮询的数据多人共享：60 秒内算一次，过期先给旧值、后台刷新
_SHARED = SwrCache(fresh_ttl=60, stale_ttl=900)


@lowbuy_bp.route('/api/lowbuy/sentiment')
def lowbuy_sentiment():
    """当前市场情绪周期"""
    result = _SHARED.get('sentiment', lambda: _get_low_buy_engine().sentiment_analyzer.analyze())[0]
    return jsonify({'success': True, 'data': result})


@lowbuy_bp.route('/api/lowbuy/sectors')
def lowbuy_sectors():
    """所有板块资金流向"""
    results = _SHARED.get('sectors', lambda: _get_low_buy_engine().sector_scorer.score_all_sectors())[0]
    return jsonify({'success': True, 'data': results, 'count': len(results)})


@lowbuy_bp.route('/api/lowbuy/data-source-health')
def lowbuy_data_source_health():
    """当前外部数据源健康状态"""
    engine = _get_low_buy_engine()
    return jsonify({
        'success': True,
        'data': engine.fetcher.get_data_source_health()
    })


@lowbuy_bp.route('/api/lowbuy/candidates')
def lowbuy_candidates():
    """全A扫描低吸候选"""
    if not _LOWBUY_CANDIDATES_LOCK.acquire(blocking=False):
        return jsonify({'success': False, 'error': '全A低吸扫描正在运行，请稍后再试'}), 409
    try:
        min_score = float(request.args.get('min_score', APIConfig.LOWBUY_DEFAULT_MIN_SCORE))
        engine = _get_low_buy_engine()
        results = engine.scan_candidates(min_score=min_score)
        return jsonify({'success': True, 'data': results, 'count': len(results)})
    finally:
        _LOWBUY_CANDIDATES_LOCK.release()


def _run_lowbuy_candidates_job(job_id, min_score):
    def progress_callback(**updates):
        if _scan_cancel_requested(job_id):
            raise RuntimeError('用户已取消扫描')
        _update_scan_job(job_id, status='running', **updates)

    try:
        _update_scan_job(
            job_id,
            status='running',
            phase='启动中',
            message='正在启动全A低吸扫描...',
            done=0,
            total=0,
            percent=0,
            matched=0,
            errors=0,
        )
        engine = _get_low_buy_engine()
        started = time.time()
        results = engine.scan_candidates(
            min_score=min_score,
            progress_callback=progress_callback,
            cancel_check=lambda: _scan_cancel_requested(job_id),
        )
        if _scan_cancel_requested(job_id):
            raise RuntimeError('用户已取消扫描')
        payload = {
            'success': True,
            'data': results,
            'count': len(results),
            'elapsed_sec': round(time.time() - started, 1),
            'meta': {
                'min_score': min_score,
                'scanned': int((_get_scan_job(job_id) or {}).get('total') or 0),
                **(getattr(engine, '_last_scan_meta', {}) or {}),
            },
        }
        current = _get_scan_job(job_id) or {}
        _update_scan_job(
            job_id,
            status='completed',
            phase='已完成',
            message=f"全A低吸扫描完成，发现 {len(results)} 只候选",
            done=int(current.get('done') or current.get('total') or 0),
            total=int(current.get('total') or current.get('done') or 0),
            matched=len(results),
            errors=int(current.get('errors') or 0),
            result=payload,
            finished_at=time.time(),
        )
    except Exception as e:
        if _scan_cancel_requested(job_id):
            _update_scan_job(
                job_id,
                status='cancelled',
                phase='已取消',
                message='扫描已取消',
                error=_safe_error_text(e),
                finished_at=time.time(),
            )
            return
        logger.error("全A低吸扫描任务失败", exc_info=True)
        error_text = _safe_error_text(e)
        _update_scan_job(
            job_id,
            status='failed',
            phase='失败',
            message='全A低吸扫描失败',
            error=error_text,
            finished_at=time.time(),
        )
    finally:
        _LOWBUY_CANDIDATES_LOCK.release()


@lowbuy_bp.route('/api/lowbuy/candidates/start', methods=['POST'])
def lowbuy_candidates_start():
    """后台启动全A低吸候选扫描"""
    if not _LOWBUY_CANDIDATES_LOCK.acquire(blocking=False):
        active_job = _get_active_scan_job('lowbuy_candidates')
        return fail('全A低吸扫描正在运行，请稍后再试', status=409, code="SCAN_BUSY", job_id=active_job.get('id') if active_job else '', job=active_job)

    try:
        min_score = float(request.args.get('min_score', APIConfig.LOWBUY_DEFAULT_MIN_SCORE))
        job = _create_scan_job(
            'lowbuy_candidates',
            params={'min_score': min_score},
            cancel_supported=True,
        )
        thread = Thread(
            target=_run_lowbuy_candidates_job,
            args=(job['id'], min_score),
            daemon=True,
        )
        thread.start()
        return ok(job)
    except Exception:
        _LOWBUY_CANDIDATES_LOCK.release()
        raise
