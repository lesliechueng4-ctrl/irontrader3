"""
IronTrader Backtest Routes & Task Management
"""

import os
import time
from threading import Lock, Thread
from flask import Blueprint, request

from api_response import fail, ok
from logger_config import get_logger

from task_manager import ACTIVE_STATUSES, default_task_manager

logger = get_logger(__name__)

backtest_bp = Blueprint("backtest_routes", __name__)

_BT_SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outputs', 'backtest_samples.csv')
_BT_SUMMARY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outputs', 'backtest_summary.json')
# 回测任务状态只存在 TaskManager 里（kind='backtest'），进程重启后仍能看到最近一次结果；
# _BT_START_LOCK 只用于"检查是否已有进行中的回测 + 创建新任务"这一步的原子性。
_BT_START_LOCK = Lock()
_tasks = default_task_manager


def _fmt_ts(ts):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts)) if ts else None


def _run_backtest_job(days, horizons, task_id):
    import pandas as pd
    from backtest_study import collect, json_sane, merge_samples, summarize, update_summary_file
    try:
        def _cb(i, total, got):
            _tasks.update_task(
                task_id, status='running', phase='回测采样中', done=i, total=total,
                message=f"{i}/{total}（已收集 {got} 笔）",
            )

        _tasks.update_task(task_id, status='running', phase='启动中', message='启动中…')
        old = None
        if os.path.exists(_BT_SAMPLES):
            try:
                old = pd.read_csv(_BT_SAMPLES)
            except Exception as e:
                logger.debug(f"读取旧回测样本失败: {e}")
                old = None
        new = collect(days, horizons, progress_cb=_cb)
        df = merge_samples(old, new)
        os.makedirs(os.path.dirname(_BT_SAMPLES), exist_ok=True)
        df.to_csv(_BT_SAMPLES, index=False, encoding='utf-8-sig')
        added = len(df) - (0 if old is None else len(old))
        result = summarize(df, horizons)
        result['added'] = max(added, 0)
        result['as_of'] = time.strftime('%Y-%m-%d %H:%M')
        # 周报自检：写 summary JSON 并检测结论翻转，翻转随结果返回给前端
        result['flips'] = update_summary_file(df, horizons, path=_BT_SUMMARY)
        # 消毒兜底：NaN 序列化出去是非法 JSON，前端 response.json() 会直接抛错
        _tasks.update_task(
            task_id, status='completed', phase='已完成', message='回测完成',
            result=json_sane(result), finished_at=time.time(),
        )
    except Exception as e:
        logger.error(f"手动回测失败: {e}")
        _tasks.update_task(task_id, status='failed', phase='失败', error=str(e), finished_at=time.time())


def _status_payload(task):
    """保持原 /api/backtest/status 的返回结构，数据来自任务记录。"""
    if not task:
        return {'running': False, 'progress': '', 'started': None, 'finished': None,
                'error': None, 'result': None, 'task_id': None}
    running = task['status'] in ACTIVE_STATUSES
    return {
        'running': running,
        'progress': task.get('message') or '',
        'started': _fmt_ts(task.get('started_at')),
        'finished': _fmt_ts(task.get('finished_at')),
        'error': task.get('error'),
        'result': task.get('result'),
        'status': task['status'],
        'task_id': task['id'],
    }


@backtest_bp.route('/api/backtest/rerun', methods=['POST'])
def backtest_rerun():
    """手动触发一次回测（后台线程），累积到样本库；前端轮询 /api/backtest/status。"""
    days = int((request.get_json(silent=True) or {}).get('days', 10))
    days = max(3, min(days, 30))
    horizons = [1, 3, 5]
    with _BT_START_LOCK:
        active = _tasks.get_active_task('backtest')
        if active:
            return ok(_status_payload(active))
        task = _tasks.create_task('backtest', params={'days': days, 'horizons': horizons},
                                  status='queued', phase='排队中', message='启动中…')
    Thread(target=_run_backtest_job, args=(days, horizons, task['id']), daemon=True).start()
    return ok(_status_payload(task))


@backtest_bp.route('/api/backtest/status')
def backtest_status():
    """回测进度/结果轮询：返回进行中的任务，否则返回最近一次任务。"""
    task = _tasks.get_active_task('backtest') or _tasks.get_latest_task('backtest')
    return ok(_status_payload(task))


@backtest_bp.route('/api/backtest/summary')
def backtest_summary():
    """最近一次回测周报（含结论翻转），由每周任务/手动回测更新。"""
    if not os.path.exists(_BT_SUMMARY):
        return ok(None)
    try:
        import json as _json
        from backtest_study import json_sane
        with open(_BT_SUMMARY, encoding='utf-8') as f:
            # 历史文件可能残留 NaN 字面量（json.load 读得进、浏览器读不了），消毒后再返回
            return ok(json_sane(_json.load(f)))
    except Exception as e:
        logger.warning(f"读取回测周报失败: {e}")
        return fail(f'读取回测周报失败：{e}', status=500, code='BACKTEST_SUMMARY_ERROR')


@backtest_bp.route('/api/backtest/history')
def backtest_history():
    """获取历史回测任务记录列表。"""
    tasks = default_task_manager.list_tasks(kind="backtest", limit=10)
    return ok(tasks)
