"""
IronTrader Counter-Trend Hero Routes & Background Tasks
"""

import time
from threading import Lock, Thread
from flask import Blueprint, jsonify, request

from api_response import fail, ok
from logger_config import get_logger
from scanner_routes import (
    _create_scan_job,
    _get_active_scan_job,
    _scan_cancel_requested,
    _update_scan_job,
)

logger = get_logger(__name__)

hero_bp = Blueprint("hero_routes", __name__)

_hero_scanner = None
_HERO_SCAN_LOCK = Lock()
_data_fetcher_getter = None


def init_hero_routes(data_fetcher_getter):
    global _data_fetcher_getter
    _data_fetcher_getter = data_fetcher_getter


def _get_hero_scanner():
    global _hero_scanner
    if _hero_scanner is None:
        from counter_trend_hero import CounterTrendHeroScanner
        df = _data_fetcher_getter() if _data_fetcher_getter else None
        _hero_scanner = CounterTrendHeroScanner(df)
    return _hero_scanner


def _run_hero_scan_job(job_id: str, min_gain: float, max_turnover: float, lookback: int):
    """后台执行逆势英雄扫描"""
    started = time.time()
    try:
        _update_scan_job(job_id, status='running', phase='扫描中', message='正在扫描逆势英雄...')
        scanner = _get_hero_scanner()
        result = scanner.scan(
            min_gain_pct=min_gain,
            max_turnover=max_turnover,
            lookback_days=lookback,
        )
        heroes = (result or {}).get('heroes') or []
        _update_scan_job(
            job_id,
            status='completed',
            phase='已完成',
            message=f"逆势英雄扫描完成，发现 {len(heroes) if isinstance(heroes, list) else 0} 只",
            matched=len(heroes) if isinstance(heroes, list) else 0,
            result=result,
            elapsed_sec=round(time.time() - started, 1),
            finished_at=time.time(),
        )
    except Exception as e:
        if _scan_cancel_requested(job_id):
            _update_scan_job(
                job_id,
                status='cancelled',
                phase='已取消',
                message='扫描已取消',
                error=str(e),
                finished_at=time.time(),
            )
            return
        logger.error("逆势英雄扫描任务失败", exc_info=True)
        _update_scan_job(
            job_id,
            status='failed',
            phase='失败',
            message='逆势英雄扫描失败',
            error=str(e),
            finished_at=time.time(),
        )
    finally:
        _HERO_SCAN_LOCK.release()


@hero_bp.route('/api/hero/scan', methods=['GET', 'POST'])
def hero_scan():
    """逆势英雄扫描：暴跌日找"该跌不跌"甚至逆势涨停的强势股（同步模式）"""
    if not _HERO_SCAN_LOCK.acquire(blocking=False):
        return jsonify({'success': False, 'error': '逆势英雄扫描正在运行，请稍后再试'}), 409
    try:
        min_gain = float(request.args.get('min_gain', 3.0))
        max_turnover = float(request.args.get('max_turnover', 25.0))
        lookback = int(request.args.get('lookback', 10))

        scanner = _get_hero_scanner()
        result = scanner.scan(
            min_gain_pct=min_gain,
            max_turnover=max_turnover,
            lookback_days=lookback,
        )
        return jsonify(result)
    finally:
        _HERO_SCAN_LOCK.release()


@hero_bp.route('/api/hero/scan/start', methods=['POST'])
def hero_scan_start():
    """后台启动逆势英雄扫描，返回 job_id，进度通过 /api/scanners/jobs/<job_id> 查询"""
    if not _HERO_SCAN_LOCK.acquire(blocking=False):
        active_job = _get_active_scan_job('hero_scan')
        return fail('逆势英雄扫描正在运行，请稍后再试', status=409, code="SCAN_BUSY", job_id=active_job.get('id') if active_job else '', job=active_job)
    try:
        min_gain = float(request.args.get('min_gain', 3.0))
        max_turnover = float(request.args.get('max_turnover', 25.0))
        lookback = int(request.args.get('lookback', 10))

        job = _create_scan_job(
            'hero_scan',
            params={
                'min_gain': min_gain,
                'max_turnover': max_turnover,
                'lookback': lookback,
            },
            cancel_supported=True,
        )
        thread = Thread(
            target=_run_hero_scan_job,
            args=(job['id'], min_gain, max_turnover, lookback),
            daemon=True,
        )
        thread.start()
        return ok(job)
    except Exception:
        _HERO_SCAN_LOCK.release()
        raise
