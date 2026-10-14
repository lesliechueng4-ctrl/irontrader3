"""
信号复盘接口 + 自动记录线程。

GET  /api/journal?start=2026-09-16&end=2026-10-14   区间内的信号记录、后续表现与分组统计
POST /api/journal/backfill/start?days=20            回补历史信号（管理员，后台任务）
POST /api/journal/outcomes/start                    立即更新后续表现（管理员，后台任务）

自动记录（app.py 启动 start_recorder）：
- 交易日 09:30–15:00 每 2 分钟记一次（梯队读首页共享缓存；作战台候选每个交易阶段只构建一次）；
- 15:05 之后记一次收盘版，并更新所有未满 5 个交易日的后续表现；服务晚上才开也会补做。
"""

import time
import traceback
from datetime import date, datetime, timedelta
from threading import Lock, Thread

from flask import Blueprint, request

from api_response import fail, ok
from logger_config import get_logger
import backtest_lab as lab
import signal_journal as sj

logger = get_logger(__name__)

journal_bp = Blueprint("journal_routes", __name__)

_service = None
_service_lock = Lock()
_JOB_LOCK = Lock()


def get_service() -> sj.JournalService:
    global _service
    with _service_lock:
        if _service is None:
            _service = sj.JournalService()
        return _service


def set_service(service) -> None:
    """测试用。"""
    global _service
    with _service_lock:
        _service = service


# ---------------------------------------------------------------------------
# 数据来源（集中在这里，测试时整体替换）
# ---------------------------------------------------------------------------

def _fetcher():
    import market_routes

    return market_routes.data_fetcher


def bars_of(code: str):
    """日 K：腾讯优先，失败退回 DataFetcher 的新浪 / 东财链路。"""
    fetcher = _fetcher()
    try:
        return sj.tencent_bars(fetcher.source_client, code)
    except Exception as exc:
        logger.info(f"[journal] 腾讯日K失败 {code}，改用默认链路: {exc}")
    df = fetcher.get_stock_history(code, days=260)
    if df is None or df.empty:
        raise RuntimeError("日K为空")
    out = []
    for _, r in df.iterrows():
        d = r.get("date")
        out.append({
            "date": d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10],
            "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"]),
        })
    return out


def _backfill_sources():
    from backtest import SignalBacktest
    from dragon_ladder import DragonLadder

    fetcher = _fetcher()
    bt = SignalBacktest(fetcher, DragonLadder(fetcher))

    def trading_days(start: date, end: date):
        return [datetime.strptime(d, "%Y%m%d").date()
                for d in bt.trading_days(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))]

    return {
        "trading_days": trading_days,
        "zt_pool_of": lambda d: bt.historical_zt_pool(d.strftime("%Y%m%d")),
        "build_sectors": bt.ladder._build_sectors,
    }


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

@journal_bp.route("/api/journal")
def journal_query():
    today = sj.now_sh().date()
    try:
        end = date.fromisoformat(request.args.get("end") or today.isoformat())
        start = date.fromisoformat(request.args.get("start") or (end - timedelta(days=30)).isoformat())
    except ValueError:
        return fail("日期格式应为 YYYY-MM-DD", status=400, code="BAD_DATE")
    if start > end:
        start, end = end, start
    if (end - start).days > 400:
        return fail("一次最多查询 400 天", status=400, code="RANGE_TOO_LARGE")
    store = get_service().store
    rows = store.query(start.isoformat(), end.isoformat())
    dates = store.dates()
    return ok({
        "rows": rows,
        "summary": {mode: sj.summarize(rows, mode) for mode in ("next_open", "same_day")},
        "signal_types": sj.SIGNAL_TYPES,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "recorded_dates": dates,
        "pending_outcomes": sum(1 for r in rows if not r.get("outcome_complete")),
    }, meta={"as_of": sj.now_sh().strftime("%Y-%m-%d %H:%M:%S")})


def _legacy_path():
    from runtime_paths import application_data_dir

    return application_data_dir() / "outputs" / "backtest_samples.csv"


LEGACY_SAMPLES = None  # 运行时取（测试可替换）


def _refresh_verdicts(service):
    try:
        rows = service.store.query("2000-01-01", "2999-12-31")
        lab.update_verdicts(service.store, rows, sj.now_sh().date())
    except Exception as exc:
        logger.warning(f"[lab] 结论快照更新失败: {exc}")


# ---------------------------------------------------------------------------
# 回测实验室（分析台）
# ---------------------------------------------------------------------------

@journal_bp.route("/api/lab/run", methods=["POST"])
def lab_run():
    spec = request.get_json(silent=True) or {}
    today = sj.now_sh().date()
    try:
        end = date.fromisoformat(spec.get("end") or today.isoformat())
        start = date.fromisoformat(spec.get("start") or "2000-01-01")
    except (TypeError, ValueError):
        return fail("日期格式应为 YYYY-MM-DD", status=400, code="BAD_DATE")
    if start > end:
        start, end = end, start
    store = get_service().store
    rows = store.query(start.isoformat(), end.isoformat())
    report = lab.run(rows, spec)
    report["flips"] = lab.latest_flips(store, today)
    return ok(report, meta={"as_of": sj.now_sh().strftime("%Y-%m-%d %H:%M:%S")})


@journal_bp.route("/api/lab/presets", methods=["GET", "POST"])
def lab_presets():
    store = get_service().store
    if request.method == "GET":
        return ok(store.list_presets())
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()[:30]
    if not name:
        return fail("请给策略起个名字", status=400, code="NAME_REQUIRED")
    spec = lab.normalize_spec(body.get("spec") or {})
    spec.pop("start", None)
    spec.pop("end", None)
    pid = store.add_preset(name, spec, _who(), sj.now_sh().strftime("%Y-%m-%d %H:%M"))
    return ok({"id": pid, "name": name, "spec": spec})


@journal_bp.route("/api/lab/presets/<int:pid>", methods=["DELETE"])
def lab_preset_delete(pid):
    store = get_service().store
    preset = store.get_preset(pid)
    if not preset:
        return fail("策略不存在", status=404, code="NOT_FOUND")
    try:
        from auth import is_owner
        owner = is_owner()
    except Exception:
        owner = True
    if not owner and preset.get("created_by") and preset["created_by"] != _who():
        return fail(f"这个策略是 {preset['created_by']} 保存的，只有他本人或管理员可以删除", status=403, code="NOT_YOURS")
    store.delete_preset(pid)
    return ok(None)


def _who():
    try:
        from auth import current_user
        return (current_user() or {}).get("name") or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 后台任务：回补 / 更新后续表现（复用选股雷达的任务存储）
# ---------------------------------------------------------------------------

def _run_job(job_id, kind, days):
    from scanner_routes import _scan_cancel_requested, _update_scan_job

    def progress(**updates):
        if _scan_cancel_requested(job_id):
            raise RuntimeError("用户已取消")
        _update_scan_job(job_id, status="running", **updates)

    try:
        service = get_service()
        result = {}
        if kind == "journal_backfill":
            progress(phase="准备", message="读取交易日历...", done=0, total=0)
            result["backfill"] = service.backfill(days, progress=progress,
                                                  cancelled=lambda: _scan_cancel_requested(job_id),
                                                  **_backfill_sources())
            # 旧回测样本里东财已经取不到的更早日期，一并导入（只导一次，已有的日期跳过）
            result["legacy"] = lab.import_legacy_samples(service.store, LEGACY_SAMPLES or _legacy_path())
        progress(phase="更新后续表现", message="读取日K...", done=0, total=0)
        result["outcomes"] = service.update_outcomes(bars_of, lookback_days=400, progress=progress,
                                                     cancelled=lambda: _scan_cancel_requested(job_id))
        _refresh_verdicts(service)
        parts = []
        if "backfill" in result:
            b = result["backfill"]
            parts.append(f"回补 {b['days']} 个交易日、{b['records']} 条信号")
            if result["legacy"]["days"]:
                parts.append(f"导入旧回测样本 {result['legacy']['days']} 天、{result['legacy']['imported']} 条")
        o = result["outcomes"]
        parts.append(f"更新后续表现 {o['updated']} 条（日K失败 {o['errors']} 只）")
        _update_scan_job(job_id, status="completed", phase="已完成", message="，".join(parts),
                         result=result, errors=o["errors"], finished_at=time.time())
    except Exception as exc:
        cancelled = "取消" in str(exc)
        if not cancelled:
            traceback.print_exc()
        _update_scan_job(job_id, status="cancelled" if cancelled else "failed",
                         phase="已取消" if cancelled else "失败",
                         message="已取消" if cancelled else "任务失败", error=str(exc), finished_at=time.time())
    finally:
        _JOB_LOCK.release()


def _start(kind, days=0):
    from scanner_routes import _create_scan_job, _get_active_scan_job

    if not _JOB_LOCK.acquire(blocking=False):
        active = _get_active_scan_job(kind) or _get_active_scan_job()
        return fail("复盘数据任务正在运行，请稍后再试", status=409, code="SCAN_BUSY",
                    job_id=active.get("id") if active else "", job=active)
    try:
        job = _create_scan_job(kind, params={"days": days}, cancel_supported=True)
        Thread(target=_run_job, args=(job["id"], kind, days), daemon=True).start()
        return ok(job)
    except Exception:
        _JOB_LOCK.release()
        raise


@journal_bp.route("/api/journal/backfill/start", methods=["POST"])
def journal_backfill_start():
    try:
        days = max(1, min(40, int(request.args.get("days", 20))))
    except ValueError:
        days = 20
    return _start("journal_backfill", days)


@journal_bp.route("/api/journal/outcomes/start", methods=["POST"])
def journal_outcomes_start():
    return _start("journal_outcomes")


# ---------------------------------------------------------------------------
# 自动记录线程
# ---------------------------------------------------------------------------

def recorder_tick(now: datetime, *, is_trading_day, ladder_live, ladder_fresh, workbench, service=None) -> str:
    """单次检查，返回做了什么（便于测试）。now 为上海时间。"""
    service = service or get_service()
    if not is_trading_day(now.date()):
        return "closed"
    hm = now.hour * 60 + now.minute
    today = now.date().isoformat()
    if 9 * 60 + 30 <= hm <= 15 * 60:
        n = service.record(ladder_live(), workbench(), final=False)
        return f"live:{n}"
    if hm >= 15 * 60 + 5 and not service.finalized(today):
        n = service.record(ladder_fresh(), workbench(), final=True)
        if n:
            service.update_outcomes(bars_of)
            _refresh_verdicts(service)
        return f"final:{n}"
    return "idle"


def _safe_workbench(mr):
    try:
        return mr._get_or_build_today_workbench(False)[0]
    except Exception as exc:
        logger.info(f"[journal] 作战台候选暂不可用，本次只记梯队: {exc}")
        return None


def start_recorder(interval: int = 120):
    def _loop():
        import market_routes as mr
        from news_catalyst import is_trading_day

        time.sleep(20)  # 等首页预热先跑
        while True:
            try:
                result = recorder_tick(
                    sj.now_sh(),
                    is_trading_day=is_trading_day,
                    ladder_live=lambda: mr.DASHBOARD_CACHE.get(
                        "dragon-ladder", lambda: mr._get_dragon_ladder().build())[0],
                    ladder_fresh=lambda: mr._get_dragon_ladder().build(force=True),
                    # 候选池每个交易阶段（上午 / 下午）只构建一次，之后都命中缓存
                    workbench=lambda: _safe_workbench(mr),
                )
                if result.startswith("final"):
                    logger.info(f"[journal] 收盘版信号已记录：{result}")
            except Exception as exc:
                logger.warning(f"[journal] 自动记录失败: {exc}")
            time.sleep(interval)

    Thread(target=_loop, daemon=True, name="signal-journal").start()
