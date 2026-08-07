from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from threading import Lock, Thread
from uuid import uuid4
import csv
import importlib.util
import math
import os
import sys
import time
import traceback

import pandas as pd
from flask import Blueprint, jsonify, request


scanner_bp = Blueprint("scanners", __name__)

BASE_DIR = Path(__file__).resolve().parent


def _scanner_output_dir():
    output_dir = os.environ.get("SCANNER_OUTPUT_DIR")
    if output_dir:
        return Path(output_dir).expanduser()
    return BASE_DIR / "outputs" / "scanners"


def _scanner_output_path(prefix):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return _scanner_output_dir() / f"{prefix}_{stamp}_{uuid4().hex[:8]}.csv"


def _resolve_external_script(env_var, local_candidates):
    """Prefer env override, then files placed in this project."""
    candidates = []
    env_value = os.environ.get(env_var)
    if env_value:
        candidates.append(Path(env_value).expanduser())
    candidates.extend(BASE_DIR / name for name in local_candidates)

    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            return path

    return candidates[0]


WASH_PATTERN_SCANNER_PATH = _resolve_external_script(
    "WASH_PATTERN_SCANNER_PATH",
    (
        "wash_pattern_scanner.py",
    ),
)
A_STOCK_SCREENER_PATH = _resolve_external_script(
    "A_STOCK_SCREENER_PATH",
    (
        "stock_screener_2.py",
        "a_stock_screener.py",
        "stock_screener.py",
    ),
)

_EXTERNAL_MODULES = {}
_HEAVY_SCANNER_LOCK = Lock()
_EXTERNAL_SCAN_LOCKS = {
    # 两条全市场扫描会读写同一批 OHLCV 缓存，必须共享重型任务锁。
    "wash_pattern": _HEAVY_SCANNER_LOCK,
    "limit_down_rebound": _HEAVY_SCANNER_LOCK,
}
_SCAN_JOBS = {}
_SCAN_JOBS_LOCK = Lock()
_SCAN_JOB_RETENTION_SEC = 60 * 60
_MAX_SCAN_JOBS = 30


class _ScanBusyError(RuntimeError):
    pass


class _ScanCancelledError(RuntimeError):
    pass


def _cleanup_scan_jobs_locked():
    now = time.time()
    expired_ids = [
        job_id
        for job_id, job in _SCAN_JOBS.items()
        if job.get("status") in {"completed", "failed", "cancelled", "canceled"}
        and now - float(job.get("finished_at") or now) > _SCAN_JOB_RETENTION_SEC
    ]
    for job_id in expired_ids:
        _SCAN_JOBS.pop(job_id, None)

    if len(_SCAN_JOBS) <= _MAX_SCAN_JOBS:
        return

    finished_jobs = sorted(
        (
            (float(job.get("finished_at") or job.get("started_at") or 0), job_id)
            for job_id, job in _SCAN_JOBS.items()
            if job.get("status") in {"completed", "failed", "cancelled", "canceled"}
        )
    )
    for _, job_id in finished_jobs[: max(0, len(_SCAN_JOBS) - _MAX_SCAN_JOBS)]:
        _SCAN_JOBS.pop(job_id, None)


def _job_snapshot(job):
    snapshot = dict(job)
    started_at = float(snapshot.get("started_at") or 0)
    finished_at = snapshot.get("finished_at")
    end_time = float(finished_at) if finished_at else time.time()
    snapshot["elapsed_sec"] = round(max(0, end_time - started_at), 1) if started_at else 0

    total = int(snapshot.get("total") or 0)
    done = int(snapshot.get("done") or 0)
    if total > 0:
        snapshot["percent"] = round(min(100, max(0, done / total * 100)), 1)
    elif snapshot.get("status") == "completed":
        snapshot["percent"] = 100
    else:
        snapshot["percent"] = float(snapshot.get("percent") or 0)
    return snapshot


def _create_scan_job(kind, params=None, cancel_supported=False):
    now = time.time()
    job_id = uuid4().hex
    job = {
        "id": job_id,
        "kind": kind,
        "params": dict(params or {}),
        "cancel_supported": bool(cancel_supported),
        "status": "queued",
        "phase": "排队中",
        "message": "等待启动筛选任务...",
        "done": 0,
        "total": 0,
        "percent": 0,
        "matched": 0,
        "errors": 0,
        "started_at": now,
        "started_at_text": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
        "elapsed_sec": 0,
        "result": None,
        "error": "",
        "cancel_requested": False,
    }
    with _SCAN_JOBS_LOCK:
        _cleanup_scan_jobs_locked()
        _SCAN_JOBS[job_id] = job
    return _job_snapshot(job)


def _update_scan_job(job_id, **updates):
    if not job_id:
        return None
    with _SCAN_JOBS_LOCK:
        job = _SCAN_JOBS.get(job_id)
        if not job:
            return None
        job.update(updates)
        return _job_snapshot(job)


def _get_scan_job(job_id):
    with _SCAN_JOBS_LOCK:
        job = _SCAN_JOBS.get(job_id)
        if not job:
            return None
        return _job_snapshot(job)


def _get_active_scan_job(kind=None):
    with _SCAN_JOBS_LOCK:
        active = [
            job
            for job in _SCAN_JOBS.values()
            if job.get("status") in {"queued", "running", "cancelling"}
            and (kind is None or job.get("kind") == kind)
        ]
        if not active:
            return None
        return _job_snapshot(max(active, key=lambda item: item.get("started_at") or 0))


def _scan_cancel_requested(job_id):
    with _SCAN_JOBS_LOCK:
        job = _SCAN_JOBS.get(job_id)
        return bool(job and job.get("cancel_requested"))


def _load_external_module(name, path):
    """Load an external scanner script once and keep dataclasses happy."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"External scanner not found: {path}")

    cache_key = (name, str(path.resolve()))
    if cache_key in _EXTERNAL_MODULES:
        return _EXTERNAL_MODULES[cache_key]

    module_name = f"irontrader_external_{name}"
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load scanner module: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _EXTERNAL_MODULES[cache_key] = module
    return module


def _request_value(name):
    raw = request.args.get(name)
    if raw is None:
        body = request.get_json(silent=True) or {}
        raw = body.get(name)
    return raw


def _int_param(name, default, minimum=None, maximum=None):
    raw = _request_value(name)
    value = default if raw in (None, "") else int(raw)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _float_param(name, default):
    raw = _request_value(name)
    return default if raw in (None, "") else float(raw)


def _optional_int_param(name, minimum=None, maximum=None):
    raw = _request_value(name)
    if raw in (None, ""):
        return None
    value = int(raw)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _optional_float_param(name):
    raw = _request_value(name)
    return None if raw in (None, "") else float(raw)


def _str_param(name, default, allowed=None):
    raw = _request_value(name)
    value = default if raw in (None, "") else str(raw)
    if allowed and value not in allowed:
        raise ValueError(f'{name} must be one of: {", ".join(allowed)}')
    return value


def _json_safe_value(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _json_safe_records(data):
    if data is None:
        return []
    if hasattr(data, "to_dict"):
        try:
            data = data.where(data.notna(), None)
        except Exception:
            pass
        records = data.to_dict("records")
    else:
        records = list(data)
    return [
        {str(key): _json_safe_value(value) for key, value in dict(row).items()}
        for row in records
    ]


def _normalize_stock_screener_record(record, recent_days):
    """Map stock_screener_2.py output into stable UI-facing keys."""
    values = list(record.values())
    if len(values) < 15:
        return {str(key): _json_safe_value(value) for key, value in record.items()}

    code = _json_safe_value(record.get("代码", values[0]))
    name = _json_safe_value(record.get("名称", values[1]))
    price = _json_safe_value(record.get("现价", values[2]))
    today_gain = _json_safe_value(record.get("今日涨幅%", values[3]))
    recent_gain = _json_safe_value(
        record.get(f"近{recent_days}日涨幅%", record.get("近20日涨幅%", values[4]))
    )
    volume_ratio = _json_safe_value(record.get("量比", values[5]))
    ma5 = _json_safe_value(record.get("MA5", values[6]))
    ma10 = _json_safe_value(record.get("MA10", values[7]))
    ma20 = _json_safe_value(record.get("MA20", values[8]))
    ma30 = _json_safe_value(record.get("MA30", values[9]))
    dif = _json_safe_value(record.get("DIF", values[10]))
    dea = _json_safe_value(record.get("DEA", values[11]))
    macd = _json_safe_value(record.get("MACD", values[12]))
    golden_cross = _json_safe_value(record.get("近期金叉", values[13]))
    score = _json_safe_value(record.get("综合评分", values[14]))
    latest_date = _json_safe_value(
        record.get("数据日期", record.get("最新日期", ""))
    )
    data_source = _json_safe_value(record.get("数据源", ""))

    normalized = {
        "代码": code,
        "名称": name,
        "现价": price,
        "今日涨幅%": today_gain,
        f"近{recent_days}日涨幅%": recent_gain,
        "近20日涨幅%": recent_gain,
        "量比": volume_ratio,
        "MA5": ma5,
        "MA10": ma10,
        "MA20": ma20,
        "MA30": ma30,
        "DIF": dif,
        "DEA": dea,
        "MACD": macd,
        "近期金叉": golden_cross,
        "综合评分": score,
        "数据日期": latest_date,
        "数据源": data_source,
    }
    normalized.update({
        "股票代码": code,
        "股票名称": name,
        "策略组": "A股条件筛选",
        "跌停日期": "",
        "跌停日涨跌幅(%)": "",
        "次日日期": "",
        "次日涨跌幅(%)": "",
        "最新日期": latest_date,
        "最新收盘价": price,
        "最新涨跌幅(%)": today_gain,
    })
    return normalized


def _progress(progress_callback, **updates):
    if not progress_callback:
        return
    try:
        progress_callback(**updates)
    except Exception:
        pass


def _stock_rows(stocks):
    if hasattr(stocks, "iterrows"):
        for _, row in stocks.iterrows():
            yield row
        return
    for row in stocks:
        yield row


def _stock_row_value(row, key, default=""):
    if hasattr(row, "get"):
        return row.get(key, default)
    return getattr(row, key, default)


def _limit_stock_pool(stocks, max_stocks):
    if max_stocks <= 0:
        return stocks
    if hasattr(stocks, "head"):
        return stocks.head(max_stocks)
    return stocks[:max_stocks]


def _write_records_csv(records, output_path):
    if not records:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        with temp_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
    return True


def _local_stock_outcome(status, df=None, record=None):
    data_date = ""
    data_source = ""
    if df is not None and len(df):
        try:
            data_date = pd.to_datetime(df.iloc[-1]["date"]).date().isoformat()
        except Exception:
            data_date = str(getattr(df, "attrs", {}).get("data_date") or "")
        data_source = str(getattr(df, "attrs", {}).get("data_source") or "")
    return {
        "status": status,
        "record": record,
        "data_date": data_date,
        "data_source": data_source,
        "stale_fallback": bool(
            getattr(df, "attrs", {}).get("stale_fallback")
        ) if df is not None else False,
    }


def _run_single_local_stock(screener, row, recent_days):
    raw_code = _stock_row_value(row, "code", "")
    if raw_code is None or str(raw_code).strip() == "":
        return _local_stock_outcome("no_data")
    code = str(raw_code).strip().split(".", 1)[0].zfill(6)
    name = str(_stock_row_value(row, "name", ""))

    df = screener.get_stock_history(code)
    if df is None:
        return _local_stock_outcome("no_data")

    pct_ok, pct_change = screener.check_price_change(df)
    if not pct_ok:
        return _local_stock_outcome("filtered", df=df)

    recent_ok, recent_gain = screener.check_recent_gain(df)
    if not recent_ok:
        return _local_stock_outcome("filtered", df=df)

    # 量比只需最后 6 根成交量，远比均线/MACD 便宜，提前短路可明显减少计算。
    vol_ok, vol_ratio = screener.check_volume_ratio(df)
    if not vol_ok:
        return _local_stock_outcome("filtered", df=df)

    ma_ok, ma_data = screener.check_ma_alignment(df)
    if not ma_ok:
        return _local_stock_outcome("filtered", df=df)

    macd_ok, macd_data = screener.check_macd_golden_cross(df)
    if not macd_ok:
        return _local_stock_outcome("filtered", df=df)

    score = screener.score_stock(ma_data, macd_data, vol_ratio, pct_change, recent_gain)
    last = df.iloc[-1]

    data_date = pd.to_datetime(last.get("date"), errors="coerce")
    record = {
        "代码": code,
        "名称": name,
        "现价": round(float(last["close"]), 2),
        "今日涨幅%": pct_change,
        f"近{recent_days}日涨幅%": recent_gain,
        "量比": vol_ratio,
        "MA5": ma_data.get("MA5"),
        "MA10": ma_data.get("MA10"),
        "MA20": ma_data.get("MA20"),
        "MA30": ma_data.get("MA30"),
        "DIF": macd_data.get("DIF"),
        "DEA": macd_data.get("DEA"),
        "MACD": macd_data.get("MACD"),
        "近期金叉": "是" if macd_data.get("金叉") else "否",
        "综合评分": score,
        "数据日期": data_date.date().isoformat() if pd.notna(data_date) else "",
        "数据源": str(getattr(df, "attrs", {}).get("data_source") or ""),
    }
    return _local_stock_outcome("matched", df=df, record=record)


def _run_local_stock_screener(
    screener,
    max_stocks,
    output_path,
    threads=1,
    config_overrides=None,
    progress_callback=None,
    cancel_check=None,
):
    """Support the bundled stock_screener_2.py style interface."""
    config = getattr(screener, "CONFIG", None)
    run_screener = getattr(screener, "run_screener", None)
    get_all_stocks = getattr(screener, "get_all_stocks", None)

    if not isinstance(config, dict) or not callable(run_screener):
        raise AttributeError("Unsupported stock screener interface")

    original_config = dict(config)
    original_get_all_stocks = get_all_stocks

    try:
        config["output_file"] = str(output_path)
        if config_overrides:
            config.update(config_overrides)

        required_functions = (
            "get_all_stocks",
            "get_stock_history",
            "check_price_change",
            "check_recent_gain",
            "check_ma_alignment",
            "check_macd_golden_cross",
            "check_volume_ratio",
            "score_stock",
        )
        can_run_parallel = all(callable(getattr(screener, name, None)) for name in required_functions)
        recent_days = int(config.get("recent_days", 20))

        if can_run_parallel:
            _progress(
                progress_callback,
                phase="获取股票列表",
                message="正在获取A股股票列表...",
                done=0,
                total=0,
                matched=0,
                errors=0,
            )
            stocks = _limit_stock_pool(screener.get_all_stocks(), max_stocks)
            if cancel_check and cancel_check():
                raise _ScanCancelledError("用户已取消扫描")
            data_prepare = {}
            prepare_history_cache = getattr(screener, "prepare_history_cache", None)
            if callable(prepare_history_cache):
                stock_count = len(stocks)
                _progress(
                    progress_callback,
                    phase="准备行情数据",
                    message=f"正在批量更新 {stock_count} 只股票的行情缓存...",
                    done=0,
                    total=0,
                    matched=0,
                    errors=0,
                )
                try:
                    prepared = prepare_history_cache(stocks, workers=threads)
                    if isinstance(prepared, dict):
                        data_prepare = prepared
                    if cancel_check and cancel_check():
                        raise _ScanCancelledError("用户已取消扫描")
                    _progress(
                        progress_callback,
                        phase="准备行情数据",
                        message=(
                            f"批量行情已就绪 {int(data_prepare.get('prepared') or 0)} 只，"
                            f"直接复用 {int(data_prepare.get('reused') or 0)} 只，"
                            f"逐股补取 {int(data_prepare.get('needs_full_fetch') or 0)} 只"
                        ),
                        done=0,
                        total=0,
                        matched=0,
                        errors=0,
                    )
                except _ScanCancelledError:
                    raise
                except Exception as exc:
                    message = str(exc).replace("\n", " ")
                    data_prepare = {
                        "enabled": False,
                        "error": message[:200],
                    }
            rows = list(_stock_rows(stocks))
            total = len(rows)
            if total == 0:
                raise RuntimeError("股票池为空，本次扫描已终止，请检查股票列表数据源")
            minimum_full_pool = int(config.get("min_full_pool_size") or 0)
            if (
                max_stocks <= 0
                and minimum_full_pool > 0
                and total < minimum_full_pool
            ):
                raise RuntimeError(
                    f"股票池明显不完整（仅 {total} 只，至少应有 "
                    f"{minimum_full_pool} 只），本次扫描已终止"
                )

            if max_stocks > 0:
                config["top_n"] = max_stocks

            _progress(
                progress_callback,
                phase="筛选中",
                message=f"开始筛选 {total} 只股票...",
                done=0,
                total=total,
                matched=0,
                errors=0,
            )

            candidates = []
            errors = 0
            data_errors = 0
            logic_errors = 0
            filtered = 0
            no_data = 0
            done = 0
            data_dates = Counter()
            data_sources = Counter()
            stale_fallback_count = 0
            error_types = Counter()
            error_samples = []
            if rows:
                needs_full_fetch = int(data_prepare.get("needs_full_fetch") or 0)
                requested_workers = max(1, min(int(threads or 1), total))
                # 纯本地 pickle + pandas 小任务使用多线程反而更慢；仅缺历史、
                # 需要联网补取时才保留请求并发。
                recommended_workers = int(
                    data_prepare.get("recommended_scan_workers") or 0
                )
                if recommended_workers > 0:
                    max_workers = max(1, min(requested_workers, recommended_workers))
                else:
                    max_workers = requested_workers if needs_full_fetch > 0 else 1
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [
                        executor.submit(_run_single_local_stock, screener, row, recent_days)
                        for row in rows
                    ]
                    last_progress_at = 0.0
                    for future in as_completed(futures):
                        if cancel_check and cancel_check():
                            for pending in futures:
                                pending.cancel()
                            raise _ScanCancelledError("用户已取消扫描")
                        done += 1
                        try:
                            outcome = future.result()
                            if isinstance(outcome, dict) and "status" in outcome:
                                status = outcome.get("status")
                                record = outcome.get("record")
                                if outcome.get("data_date"):
                                    data_dates[str(outcome["data_date"])] += 1
                                if outcome.get("data_source"):
                                    data_sources[str(outcome["data_source"])] += 1
                                if outcome.get("stale_fallback"):
                                    stale_fallback_count += 1
                                if status == "matched" and record:
                                    candidates.append(record)
                                elif status == "filtered":
                                    filtered += 1
                                else:
                                    no_data += 1
                            elif outcome:
                                # 兼容第三方旧版筛选器直接返回记录。
                                candidates.append(outcome)
                            else:
                                filtered += 1
                        except Exception as exc:
                            errors += 1
                            if isinstance(
                                exc,
                                getattr(screener, "HistoryDataSourceError", ()),
                            ):
                                data_errors += 1
                            else:
                                logic_errors += 1
                            error_types[exc.__class__.__name__] += 1
                            if len(error_samples) < 10:
                                error_samples.append(str(exc).replace("\n", " ")[:240])
                        now = time.monotonic()
                        if done == total or now - last_progress_at >= 0.4:
                            _progress(
                                progress_callback,
                                phase="筛选中",
                                message=f"已处理 {done}/{total} 只，命中 {len(candidates)} 只",
                                done=done,
                                total=total,
                                matched=len(candidates),
                                errors=errors,
                            )
                            last_progress_at = now

            candidates.sort(key=lambda item: item.get("综合评分") or 0, reverse=True)
            legacy_top_n = int(config.get("top_n") or 0)
            # 浏览器端数据量只有百级，返回并导出全部命中。旧脚本的 top_n
            # 只保留作诊断，不能再被页面误解成仍存在的输出截断上限。
            result_limit = 0
            raw_records = _json_safe_records(candidates)
            records = [
                _normalize_stock_screener_record(record, recent_days)
                for record in raw_records
            ]
            return records, {
                "scanned": total,
                "recent_days": recent_days,
                "source": Path(getattr(screener, "__file__", "stock_screener_2.py")).name,
                "errors": errors,
                "data_errors": data_errors,
                "logic_errors": logic_errors,
                "candidates": len(candidates),
                "total_matches": len(candidates),
                "returned_count": len(records),
                "result_limit": result_limit,
                "legacy_top_n": legacy_top_n,
                "valid_data": max(
                    0, filtered + len(candidates) - stale_fallback_count
                ),
                "filtered": filtered,
                "no_data": no_data,
                "stale_fallback_count": stale_fallback_count,
                "data_coverage_pct": round(
                    max(0, filtered + len(candidates) - stale_fallback_count)
                    / total * 100, 2
                ) if total else 0,
                "coverage_pct": round(
                    max(0, filtered + len(candidates) - stale_fallback_count)
                    / total * 100, 2
                ) if total else 0,
                "data_dates": dict(data_dates),
                "latest_data_date": max(data_dates) if data_dates else "",
                "data_sources": dict(data_sources),
                "error_types": dict(error_types),
                "error_samples": error_samples,
                "scan_workers": max_workers if rows else 0,
                "data_prepare": data_prepare,
            }

        if max_stocks > 0:
            config["top_n"] = max_stocks

            if callable(original_get_all_stocks):
                def _limited_get_all_stocks():
                    stocks = original_get_all_stocks()
                    return _limit_stock_pool(stocks, max_stocks)

                screener.get_all_stocks = _limited_get_all_stocks

        _progress(
            progress_callback,
            phase="运行脚本",
            message="正在运行本地筛选脚本...",
            done=0,
            total=0,
        )
        result_df = run_screener()
        if result_df is None or len(result_df) == 0:
            return [], {
                "scanned": max_stocks if max_stocks > 0 else 0,
                "recent_days": recent_days,
                "source": "stock_screener_2.py",
            }

        raw_records = _json_safe_records(result_df)
        records = [
            _normalize_stock_screener_record(record, recent_days)
            for record in raw_records
        ]
        _progress(
            progress_callback,
            phase="整理结果",
            message=f"筛选完成，命中 {len(records)} 条",
            done=len(records),
            total=len(records),
            matched=len(records),
        )
        return records, {
            "scanned": max_stocks if max_stocks > 0 else len(raw_records),
            "recent_days": recent_days,
            "source": Path(getattr(screener, "__file__", "stock_screener_2.py")).name,
        }
    finally:
        config.clear()
        config.update(original_config)
        if callable(original_get_all_stocks):
            screener.get_all_stocks = original_get_all_stocks


def _run_legacy_limit_down_rebound(
    screener,
    threads,
    max_stocks,
    output_path,
    limit_down=None,
    recovery=None,
    progress_callback=None,
):
    if limit_down is None:
        limit_down = getattr(screener, "LIMIT_DOWN_THRESHOLD", -9.8)
    if recovery is None:
        recovery = getattr(screener, "RECOVERY_THRESHOLD", -5.0)

    screener.DEBUG = False
    screener.LIMIT_DOWN_THRESHOLD = limit_down
    screener.RECOVERY_THRESHOLD = recovery
    screener.debug_limit_downs = []

    _progress(progress_callback, phase="获取股票列表", message="正在获取主板非ST股票列表...")
    stocks = screener.filter_main_board_non_st(screener.get_main_board_stocks())
    if max_stocks > 0:
        stocks = stocks[:max_stocks]
    if not stocks:
        raise RuntimeError("未获取到可筛选的主板非 ST 股票")

    screener.progress_counter["total"] = len(stocks)
    screener.progress_counter["done"] = 0
    screener.progress_counter["errors"] = 0

    _progress(
        progress_callback,
        phase="筛选中",
        message=f"开始筛选 {len(stocks)} 只股票...",
        done=0,
        total=len(stocks),
        matched=0,
        errors=0,
    )

    today_str = datetime.now().strftime("%Y-%m-%d")
    all_results = []
    done = 0
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {
            executor.submit(screener.process_single_stock, symbol, code, name, today_str): (code, name)
            for symbol, code, name in stocks
        }
        for future in as_completed(futures):
            done += 1
            try:
                items = future.result()
                if items:
                    all_results.extend(items)
            except Exception:
                screener.progress_counter["errors"] += 1
            _progress(
                progress_callback,
                phase="筛选中",
                message=f"已处理 {done}/{len(stocks)} 只，命中 {len(all_results)} 条",
                done=done,
                total=len(stocks),
                matched=len(all_results),
                errors=screener.progress_counter.get("errors", 0),
            )

    all_results.sort(key=lambda item: (
        str(item.get("策略组", "")),
        str(item.get("股票代码", "")),
    ))
    records = _json_safe_records(all_results)
    return records, {
        "schema": "legacy_limit_down_rebound",
        "source": Path(getattr(screener, "__file__", A_STOCK_SCREENER_PATH)).name,
        "scanned": len(stocks),
        "errors": screener.progress_counter.get("errors", 0),
        "threads": threads,
        "limit_down": limit_down,
        "recovery": recovery,
    }


def _run_limit_down_rebound_scan(
    threads,
    max_stocks,
    recent_days=None,
    limit_down=None,
    recovery=None,
    progress_callback=None,
    cancel_check=None,
):
    started = time.time()
    screener = _load_external_module("limit_down_rebound", A_STOCK_SCREENER_PATH)
    output_path = _scanner_output_path("limit_down_rebound_results")

    if all(callable(getattr(screener, name, None)) for name in (
        "filter_main_board_non_st",
        "get_main_board_stocks",
        "process_single_stock",
    )):
        records, meta = _run_legacy_limit_down_rebound(
            screener,
            threads=threads,
            max_stocks=max_stocks,
            output_path=output_path,
            limit_down=limit_down,
            recovery=recovery,
            progress_callback=progress_callback,
        )
    elif isinstance(getattr(screener, "CONFIG", None), dict) and callable(getattr(screener, "run_screener", None)):
        recent_days_default = int(screener.CONFIG.get("recent_days", 20))
        resolved_recent_days = recent_days if recent_days is not None else recent_days_default
        records, meta = _run_local_stock_screener(
            screener,
            max_stocks=max_stocks,
            output_path=output_path,
            threads=threads,
            config_overrides={"recent_days": resolved_recent_days},
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        meta.update({
            "schema": "local_stock_screener",
            "threads": threads,
        })
    else:
        raise AttributeError(
            "Unsupported screener interface: expected legacy limit-down API or run_screener()/CONFIG"
        )

    scanned = int(meta.get("scanned") or 0)
    all_errors = int(meta.get("errors") or 0)
    raw_valid_data = meta.get("valid_data")
    valid_data = (
        int(raw_valid_data)
        if raw_valid_data is not None
        else max(0, scanned - all_errors)
    )
    if scanned > 0 and valid_data * 5 < scanned * 4:
        raise RuntimeError(
            f"历史行情有效覆盖率过低（{valid_data}/{scanned}，"
            f"数据错误 {int(meta.get('data_errors') or 0)}，"
            f"规则错误 {int(meta.get('logic_errors') or 0)}，"
            f"无数据/历史不足 {int(meta.get('no_data') or 0)}，"
            f"陈旧缓存兜底 {int(meta.get('stale_fallback_count') or 0)}），"
            "本次结果已作废，请检查行情数据源后重试"
        )
    if cancel_check and cancel_check():
        raise _ScanCancelledError("用户已取消扫描")
    _write_records_csv(records, output_path)

    elapsed = round(time.time() - started, 1)
    return {
        "success": True,
        "data": records,
        "count": len(records),
        "elapsed_sec": elapsed,
        "output": str(output_path) if output_path.exists() else "",
        "meta": meta,
    }


def _wash_pattern_params_from_request():
    return {
        "mode": _str_param("mode", "both", ("strong", "low_reversal", "breakout_base", "both", "all")),
        "pool": _str_param("pool", "all_a", ("hs300", "zz500", "all_a")),
        "pool_source": _str_param("pool_source", "auto", ("auto", "sina", "akshare", "cache")),
        "max_stocks": _int_param("max_stocks", 0, 0, 6000),
        "fetch_days": _int_param("fetch_days", 120, 30, 360),
        "recent_days": _int_param("recent_days", 30, 1, 240),
        "workers": _int_param("workers", 12, 1, 32),
        "data_source": _str_param(
            "data_source",
            "auto",
            ("auto", "sina", "akshare", "yahoo", "cache"),
        ),
        "enable_lossy_prescreen": bool(
            _int_param("enable_lossy_prescreen", 0, 0, 1)
        ),
    }


def _build_wash_pattern_config(scanner, params, output_path):
    return scanner.ScanConfig(
        scan_mode=params["mode"],
        stock_pool=params["pool"],
        pool_source=params["pool_source"],
        max_stocks=params["max_stocks"],
        fetch_days=params["fetch_days"],
        recent_days=params["recent_days"],
        workers=params["workers"],
        data_source=params["data_source"],
        enable_lossy_prescreen=params.get("enable_lossy_prescreen", False),
        output=str(output_path),
    )


def _run_wash_pattern_scan(params, progress_callback=None, cancel_check=None):
    started = time.time()
    scanner = _load_external_module("wash_pattern", WASH_PATTERN_SCANNER_PATH)
    output_path = _scanner_output_path("wash_pattern_results")
    cfg = _build_wash_pattern_config(scanner, params, output_path)
    stocks = []
    max_workers = 0

    can_track_progress = all(callable(getattr(scanner, name, None)) for name in (
        "get_stock_pool",
        "parse_as_of_date",
        "scan_stock",
    )) and hasattr(scanner, "RESULT_COLUMNS") and hasattr(scanner, "pd")

    if can_track_progress:
        _progress(
            progress_callback,
            phase="获取股票池",
            message="正在获取洗盘扫描股票池...",
            done=0,
            total=0,
            matched=0,
            errors=0,
        )
        # resolve_scan_stocks 默认使用完整股票池；有损预筛必须由显式配置开启。
        if callable(getattr(scanner, "resolve_scan_stocks", None)):
            stocks = scanner.resolve_scan_stocks(cfg)
        else:
            stocks = scanner.get_stock_pool(cfg.stock_pool, cfg.pool_source)
        if cfg.max_stocks > 0:
            stocks = stocks[: cfg.max_stocks]
        total = len(stocks)
        if total == 0:
            raise RuntimeError("洗盘扫描股票池为空，请检查股票列表数据源")
        minimum_pool_sizes = {"all_a": 4000, "hs300": 200, "zz500": 400}
        minimum_pool = minimum_pool_sizes.get(cfg.stock_pool, 0)
        if cfg.max_stocks <= 0 and minimum_pool and total < minimum_pool:
            raise RuntimeError(
                f"洗盘股票池明显不完整（仅 {total} 只，至少应有 "
                f"{minimum_pool} 只），本次扫描已终止"
            )
        today = scanner.parse_as_of_date(cfg)
        prepare_meta = {}
        if cancel_check and cancel_check():
            raise _ScanCancelledError("用户已取消扫描")

        if callable(getattr(scanner, "prepare_scan_cache", None)) and stocks:
            _progress(
                progress_callback,
                phase="批量更新行情",
                message=f"正在批量更新 {total} 只股票的最新行情...",
                done=0,
                total=0,
                matched=0,
                errors=0,
            )
            prepare_meta = scanner.prepare_scan_cache(stocks, cfg)
            if cancel_check and cancel_check():
                raise _ScanCancelledError("用户已取消扫描")
            prepared = int(prepare_meta.get("prepared") or 0)
            reused = int(prepare_meta.get("reused") or 0)
            needs_fetch = int(prepare_meta.get("needs_full_fetch") or 0)
            _progress(
                progress_callback,
                phase="批量更新完成",
                message=(
                    f"已批量更新 {prepared} 只，直接复用 {reused} 只，"
                    f"需单独补历史 {needs_fetch} 只"
                ),
                done=0,
                total=0,
                matched=0,
                errors=0,
            )

        _progress(
            progress_callback,
            phase="扫描中",
            message=f"开始扫描 {total} 只股票的洗盘形态...",
            done=0,
            total=total,
            matched=0,
            errors=0,
        )

        found = []
        errors = 0
        data_errors = 0
        logic_errors = 0
        error_types = Counter()
        error_samples = []
        data_dates = Counter()
        data_sources = Counter()
        stale_fallback_count = 0
        short_history_count = 0
        done = 0

        diagnostic_scanner = getattr(scanner, "scan_stock_with_diagnostics", None)

        def scan_one(stock):
            if callable(diagnostic_scanner):
                return diagnostic_scanner(stock, cfg, today)
            return scanner.scan_stock(stock, cfg, today)

        def consume_scan_result(value):
            nonlocal stale_fallback_count, short_history_count
            diagnostics = {}
            rows = value
            if (
                isinstance(value, tuple)
                and len(value) == 2
                and isinstance(value[1], dict)
            ):
                rows, diagnostics = value
            found.extend(rows or [])
            if diagnostics.get("data_date"):
                data_dates[str(diagnostics["data_date"])] += 1
            if diagnostics.get("data_source"):
                data_sources[str(diagnostics["data_source"])] += 1
            if diagnostics.get("stale_fallback"):
                stale_fallback_count += 1
            if diagnostics.get("short_history"):
                short_history_count += 1

        if stocks:
            requested_workers = max(1, min(int(cfg.workers or 1), total))
            needs_full_fetch = int(prepare_meta.get("needs_full_fetch") or 0)
            max_workers = requested_workers if needs_full_fetch > 0 else 1
            if max_workers <= 1:
                last_emit = 0.0
                for stock in stocks:
                    if cancel_check and cancel_check():
                        raise _ScanCancelledError("用户已取消扫描")
                    done += 1
                    try:
                        consume_scan_result(scan_one(stock))
                    except Exception as exc:
                        errors += 1
                        if isinstance(exc, getattr(scanner, "DailyDataSourceError", ())):
                            data_errors += 1
                        else:
                            logic_errors += 1
                        error_types[exc.__class__.__name__] += 1
                        if len(error_samples) < 10:
                            error_samples.append(str(exc).replace("\n", " ")[:240])
                    now = time.monotonic()
                    if done == total or now - last_emit >= 0.4:
                        last_emit = now
                        _progress(
                            progress_callback,
                            phase="扫描中",
                            message=f"已处理 {done}/{total} 只，命中 {len(found)} 条",
                            done=done,
                            total=total,
                            matched=len(found),
                            errors=errors,
                        )
            else:
                last_emit = 0.0
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [
                        executor.submit(scan_one, stock)
                        for stock in stocks
                    ]
                    for future in as_completed(futures):
                        if cancel_check and cancel_check():
                            for pending in futures:
                                pending.cancel()
                            raise _ScanCancelledError("用户已取消扫描")
                        done += 1
                        try:
                            consume_scan_result(future.result())
                        except Exception as exc:
                            errors += 1
                            if isinstance(exc, getattr(scanner, "DailyDataSourceError", ())):
                                data_errors += 1
                            else:
                                logic_errors += 1
                            error_types[exc.__class__.__name__] += 1
                            if len(error_samples) < 10:
                                error_samples.append(str(exc).replace("\n", " ")[:240])
                        # 进度回调节流：每只都打锁更新会产生数千次 _update_scan_job，
                        # 改为最多每 0.5s 一次（最后一只必报）
                        now = time.time()
                        if now - last_emit >= 0.5 or done == total:
                            last_emit = now
                            _progress(
                                progress_callback,
                                phase="扫描中",
                                message=f"已处理 {done}/{total} 只，命中 {len(found)} 条",
                                done=done,
                                total=total,
                                matched=len(found),
                                errors=errors,
                            )

        result_df = scanner.pd.DataFrame(found, columns=scanner.RESULT_COLUMNS)
        if not result_df.empty:
            if callable(getattr(scanner, "sort_wash_results", None)):
                result_df = scanner.sort_wash_results(result_df)
            else:
                result_df = result_df.sort_values("后续涨幅%", ascending=False).reset_index(drop=True)
    else:
        _progress(
            progress_callback,
            phase="运行脚本",
            message="正在运行洗盘形态扫描脚本...",
            done=0,
            total=0,
        )
        result_df = scanner.scan(cfg, show_progress=False)
        total = int(cfg.max_stocks or 0)
        errors = 0
        data_errors = 0
        logic_errors = 0
        error_types = Counter()
        error_samples = []
        prepare_meta = {}
        data_dates = Counter()
        data_sources = Counter()
        stale_fallback_count = 0
        short_history_count = 0

    records = _json_safe_records(result_df)
    if not data_dates:
        data_dates.update(
            str(record.get("最新行情日"))
            for record in records
            if record.get("最新行情日")
        )
    valid_data = max(0, total - errors - stale_fallback_count)
    if total > 0 and valid_data * 5 < total * 4:
        raise RuntimeError(
            f"洗盘行情有效覆盖率过低（{valid_data}/{total}，"
            f"数据错误 {data_errors}，规则错误 {logic_errors}，"
            f"陈旧缓存兜底 {stale_fallback_count}），"
            "本次结果已作废，请检查行情数据源后重试"
        )
    _write_records_csv(records, output_path)
    return {
        "success": True,
        "data": records,
        "count": len(records),
        "elapsed_sec": round(time.time() - started, 1),
        "output": str(output_path) if output_path.exists() else "",
        "meta": {
            "mode": cfg.scan_mode,
            "pool": cfg.stock_pool,
            "pool_source": cfg.pool_source,
            "recent_days": cfg.recent_days,
            "workers": cfg.workers,
            "scanned": total,
            "errors": errors,
            "data_errors": data_errors,
            "logic_errors": logic_errors,
            "stale_fallback_count": stale_fallback_count,
            "short_history_count": short_history_count,
            "candidates": len(records),
            "total_matches": len(records),
            "returned_count": len(records),
            "result_limit": 0,
            "valid_data": valid_data,
            "data_coverage_pct": round(valid_data / total * 100, 2) if total else 0,
            "coverage_pct": round(valid_data / total * 100, 2) if total else 0,
            "latest_data_date": max(data_dates) if data_dates else "",
            "data_dates": dict(data_dates),
            "data_sources": dict(data_sources),
            "error_types": dict(error_types),
            "error_samples": error_samples,
            "scan_workers": max_workers if stocks else 0,
            "data_prepare": prepare_meta,
        },
    }


@scanner_bp.route("/api/scanners/wash-pattern", methods=["GET", "POST"])
def wash_pattern_scan():
    """Run the external wash pattern scanner and return table-ready JSON."""
    params = _wash_pattern_params_from_request()
    job_kind = (
        "breakout_base" if params.get("mode") == "breakout_base"
        else "wash_pattern"
    )
    lock = _EXTERNAL_SCAN_LOCKS["wash_pattern"]
    if not lock.acquire(blocking=False):
        active_job = _get_active_scan_job(job_kind)
        return jsonify({
            "success": False,
            "error": "洗盘形态扫描正在运行，请稍后再试",
            "job_id": active_job.get("id") if active_job else "",
            "job": active_job,
        }), 409

    try:
        return jsonify(_run_wash_pattern_scan(params))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        lock.release()


def _run_wash_pattern_job(job_id, params):
    lock = _EXTERNAL_SCAN_LOCKS["wash_pattern"]

    def progress_callback(**updates):
        if _scan_cancel_requested(job_id):
            raise _ScanCancelledError("用户已取消扫描")
        _update_scan_job(job_id, status="running", **updates)

    try:
        _update_scan_job(
            job_id,
            status="running",
            phase="启动中",
            message="正在启动洗盘形态扫描...",
            done=0,
            total=0,
            percent=0,
            matched=0,
            errors=0,
        )
        result = _run_wash_pattern_scan(
            params,
            progress_callback=progress_callback,
            cancel_check=lambda: _scan_cancel_requested(job_id),
        )
        if _scan_cancel_requested(job_id):
            raise _ScanCancelledError("用户已取消扫描")
        meta = result.get("meta") or {}
        scanned = int(meta.get("scanned") or 0)
        current = _get_scan_job(job_id) or {}
        _update_scan_job(
            job_id,
            status="completed",
            phase="已完成",
            message=f"洗盘扫描完成，发现 {result.get('count', 0)} 条结果",
            done=scanned or int(current.get("done") or 0),
            total=scanned or int(current.get("total") or 0),
            matched=result.get("count", 0),
            errors=meta.get("errors", 0),
            result=result,
            finished_at=time.time(),
        )
    except _ScanCancelledError as e:
        _update_scan_job(
            job_id,
            status="cancelled",
            phase="已取消",
            message="扫描已取消",
            error=str(e),
            finished_at=time.time(),
        )
    except Exception as e:
        traceback.print_exc()
        _update_scan_job(
            job_id,
            status="failed",
            phase="失败",
            message="洗盘扫描任务失败",
            error=str(e),
            finished_at=time.time(),
        )
    finally:
        lock.release()


@scanner_bp.route("/api/scanners/wash-pattern/start", methods=["POST"])
def wash_pattern_scan_start():
    """Start the wash pattern scanner in a background job."""
    params = _wash_pattern_params_from_request()
    job_kind = (
        "breakout_base" if params.get("mode") == "breakout_base"
        else "wash_pattern"
    )
    lock = _EXTERNAL_SCAN_LOCKS["wash_pattern"]
    if not lock.acquire(blocking=False):
        active_job = _get_active_scan_job(job_kind)
        return jsonify({
            "success": False,
            "error": "洗盘形态扫描正在运行，请稍后再试",
            "job_id": active_job.get("id") if active_job else "",
            "job": active_job,
        }), 409

    try:
        job = _create_scan_job(
            job_kind,
            params=params,
            cancel_supported=True,
        )
        thread = Thread(
            target=_run_wash_pattern_job,
            args=(job["id"], params),
            daemon=True,
        )
        thread.start()
        return jsonify({"success": True, "job_id": job["id"], "job": job})
    except Exception:
        lock.release()
        raise


@scanner_bp.route("/api/scanners/limit-down-rebound", methods=["GET", "POST"])
def limit_down_rebound_scan():
    """Run the configured external stock screener and return table-ready JSON."""
    lock = _EXTERNAL_SCAN_LOCKS["limit_down_rebound"]
    if not lock.acquire(blocking=False):
        return jsonify({
            "success": False,
            "error": "外部筛选正在运行，请稍后再试",
        }), 409

    try:
        threads = _int_param("threads", 10, 1, 32)
        max_stocks = _int_param("max_stocks", 0, 0, 6000)
        result = _run_limit_down_rebound_scan(
            threads=threads,
            max_stocks=max_stocks,
            recent_days=_optional_int_param("recent_days", 1, 240),
            limit_down=_optional_float_param("limit_down"),
            recovery=_optional_float_param("recovery"),
        )
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        lock.release()


def _run_limit_down_rebound_job(job_id, params):
    lock = _EXTERNAL_SCAN_LOCKS["limit_down_rebound"]

    def progress_callback(**updates):
        if _scan_cancel_requested(job_id):
            raise _ScanCancelledError("用户已取消扫描")
        _update_scan_job(job_id, status="running", **updates)

    try:
        _update_scan_job(
            job_id,
            status="running",
            phase="启动中",
            message="正在启动A股条件筛选...",
            done=0,
            total=0,
            percent=0,
            matched=0,
            errors=0,
        )
        result = _run_limit_down_rebound_scan(
            threads=params["threads"],
            max_stocks=params["max_stocks"],
            recent_days=params.get("recent_days"),
            limit_down=params.get("limit_down"),
            recovery=params.get("recovery"),
            progress_callback=progress_callback,
            cancel_check=lambda: _scan_cancel_requested(job_id),
        )
        if _scan_cancel_requested(job_id):
            raise _ScanCancelledError("用户已取消扫描")
        meta = result.get("meta") or {}
        scanned = int(meta.get("scanned") or 0)
        _update_scan_job(
            job_id,
            status="completed",
            phase="已完成",
            message=f"筛选完成，发现 {result.get('count', 0)} 条结果",
            done=scanned or int(_get_scan_job(job_id).get("done") or 0),
            total=scanned or int(_get_scan_job(job_id).get("total") or 0),
            matched=meta.get("total_matches", result.get("count", 0)),
            errors=meta.get("errors", 0),
            result=result,
            finished_at=time.time(),
        )
    except _ScanCancelledError as e:
        _update_scan_job(
            job_id,
            status="cancelled",
            phase="已取消",
            message="扫描已取消",
            error=str(e),
            finished_at=time.time(),
        )
    except Exception as e:
        traceback.print_exc()
        _update_scan_job(
            job_id,
            status="failed",
            phase="失败",
            message="筛选任务失败",
            error=str(e),
            finished_at=time.time(),
        )
    finally:
        lock.release()


@scanner_bp.route("/api/scanners/limit-down-rebound/start", methods=["POST"])
def limit_down_rebound_scan_start():
    """Start the stock screener in a background job."""
    lock = _EXTERNAL_SCAN_LOCKS["limit_down_rebound"]
    if not lock.acquire(blocking=False):
        active_job = _get_active_scan_job("limit_down_rebound")
        return jsonify({
            "success": False,
            "error": "A股条件筛选正在运行，请稍后再试",
            "job_id": active_job.get("id") if active_job else "",
            "job": active_job,
        }), 409

    try:
        params = {
            "threads": _int_param("threads", 10, 1, 32),
            "max_stocks": _int_param("max_stocks", 0, 0, 6000),
            "recent_days": _optional_int_param("recent_days", 1, 240),
            "limit_down": _optional_float_param("limit_down"),
            "recovery": _optional_float_param("recovery"),
        }
        job = _create_scan_job(
            "limit_down_rebound",
            params=params,
            cancel_supported=True,
        )
        thread = Thread(
            target=_run_limit_down_rebound_job,
            args=(job["id"], params),
            daemon=True,
        )
        thread.start()
        return jsonify({"success": True, "job_id": job["id"], "job": job})
    except Exception:
        lock.release()
        raise


def _request_scan_cancel(job_id):
    with _SCAN_JOBS_LOCK:
        job = _SCAN_JOBS.get(job_id)
        if not job:
            return None
        if job.get("status") not in {"completed", "failed", "cancelled", "canceled"}:
            job.update({
                "cancel_requested": True,
                "status": "cancelling",
                "phase": "取消中",
                "message": "正在停止尚未执行的扫描任务...",
            })
        return _job_snapshot(job)


@scanner_bp.route("/api/scanners/jobs/current", methods=["GET"])
def scanner_current_job():
    kind = request.args.get("kind") or None
    job = _get_active_scan_job(kind)
    return jsonify({"success": True, "job": job})


@scanner_bp.route("/api/scanners/jobs/<job_id>/cancel", methods=["POST"])
def scanner_job_cancel(job_id):
    job = _request_scan_cancel(job_id)
    if not job:
        return jsonify({"success": False, "error": "扫描任务不存在或已过期"}), 404
    return jsonify({"success": True, "job": job})


@scanner_bp.route("/api/scanners/jobs/<job_id>", methods=["GET", "DELETE"])
def scanner_job_status(job_id):
    if request.method == "DELETE":
        job = _request_scan_cancel(job_id)
        if not job:
            return jsonify({"success": False, "error": "扫描任务不存在或已过期"}), 404
        return jsonify({"success": True, "job": job})
    job = _get_scan_job(job_id)
    if not job:
        return jsonify({"success": False, "error": "扫描任务不存在或已过期"}), 404
    return jsonify({"success": True, "job": job})
