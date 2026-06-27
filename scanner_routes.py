from concurrent.futures import ThreadPoolExecutor, as_completed
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

from flask import Blueprint, jsonify, request


scanner_bp = Blueprint("scanners", __name__)

BASE_DIR = Path(__file__).resolve().parent


def _scanner_output_dir():
    output_dir = os.environ.get("SCANNER_OUTPUT_DIR")
    if output_dir:
        return Path(output_dir).expanduser()
    return BASE_DIR / "outputs" / "scanners"


def _scanner_output_path(prefix):
    return _scanner_output_dir() / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.csv"


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
_EXTERNAL_SCAN_LOCKS = {
    "wash_pattern": Lock(),
    "limit_down_rebound": Lock(),
}
_SCAN_JOBS = {}
_SCAN_JOBS_LOCK = Lock()
_SCAN_JOB_RETENTION_SEC = 60 * 60
_MAX_SCAN_JOBS = 30


class _ScanBusyError(RuntimeError):
    pass


def _cleanup_scan_jobs_locked():
    now = time.time()
    expired_ids = [
        job_id
        for job_id, job in _SCAN_JOBS.items()
        if job.get("status") in {"completed", "failed"}
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
            if job.get("status") in {"completed", "failed"}
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


def _create_scan_job(kind):
    now = time.time()
    job_id = uuid4().hex
    job = {
        "id": job_id,
        "kind": kind,
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
    }
    normalized.update({
        "股票代码": code,
        "股票名称": name,
        "策略组": "A股条件筛选",
        "跌停日期": "",
        "跌停日涨跌幅(%)": "",
        "次日日期": "",
        "次日涨跌幅(%)": "",
        "最新日期": date.today().isoformat(),
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
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    return True


def _run_single_local_stock(screener, row, recent_days):
    raw_code = _stock_row_value(row, "code", "")
    if raw_code is None or str(raw_code).strip() == "":
        return None
    code = str(raw_code).strip().split(".", 1)[0].zfill(6)
    name = str(_stock_row_value(row, "name", ""))

    df = screener.get_stock_history(code)
    if df is None:
        return None

    pct_ok, pct_change = screener.check_price_change(df)
    if not pct_ok:
        return None

    recent_ok, recent_gain = screener.check_recent_gain(df)
    if not recent_ok:
        return None

    ma_ok, ma_data = screener.check_ma_alignment(df)
    if not ma_ok:
        return None

    macd_ok, macd_data = screener.check_macd_golden_cross(df)
    if not macd_ok:
        return None

    vol_ok, vol_ratio = screener.check_volume_ratio(df)
    if not vol_ok:
        return None

    score = screener.score_stock(ma_data, macd_data, vol_ratio, pct_change, recent_gain)
    last = df.iloc[-1]

    return {
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
    }


def _run_local_stock_screener(
    screener,
    max_stocks,
    output_path,
    threads=1,
    config_overrides=None,
    progress_callback=None,
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
            rows = list(_stock_rows(stocks))
            total = len(rows)

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
            done = 0
            if rows:
                max_workers = max(1, min(int(threads or 1), total))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [
                        executor.submit(_run_single_local_stock, screener, row, recent_days)
                        for row in rows
                    ]
                    for future in as_completed(futures):
                        done += 1
                        try:
                            record = future.result()
                            if record:
                                candidates.append(record)
                        except Exception:
                            errors += 1
                        _progress(
                            progress_callback,
                            phase="筛选中",
                            message=f"已处理 {done}/{total} 只，命中 {len(candidates)} 只",
                            done=done,
                            total=total,
                            matched=len(candidates),
                            errors=errors,
                        )

            candidates.sort(key=lambda item: item.get("综合评分") or 0, reverse=True)
            top_n = int(config.get("top_n") or len(candidates) or 0)
            selected = candidates[:top_n] if top_n > 0 else candidates
            raw_records = _json_safe_records(selected)
            records = [
                _normalize_stock_screener_record(record, recent_days)
                for record in raw_records
            ]
            _write_records_csv(records, output_path)
            return records, {
                "scanned": total,
                "recent_days": recent_days,
                "source": Path(getattr(screener, "__file__", "stock_screener_2.py")).name,
                "errors": errors,
                "candidates": len(candidates),
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
    _write_records_csv(records, output_path)

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
        )
        meta.update({
            "schema": "local_stock_screener",
            "threads": threads,
        })
    else:
        raise AttributeError(
            "Unsupported screener interface: expected legacy limit-down API or run_screener()/CONFIG"
        )

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
        "data_source": _str_param("data_source", "auto", ("auto", "akshare", "yahoo", "cache")),
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
        output=str(output_path),
    )


def _run_wash_pattern_scan(params, progress_callback=None):
    started = time.time()
    scanner = _load_external_module("wash_pattern", WASH_PATTERN_SCANNER_PATH)
    output_path = _scanner_output_path("wash_pattern_results")
    cfg = _build_wash_pattern_config(scanner, params, output_path)

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
        # 复用扫描器内置的预筛选逻辑（全A扫描时 5000 → 800-1500 只）；
        # 旧版直接 get_stock_pool 会让 Web 端始终走全量。
        if callable(getattr(scanner, "resolve_scan_stocks", None)):
            stocks = scanner.resolve_scan_stocks(cfg)
        else:
            stocks = scanner.get_stock_pool(cfg.stock_pool, cfg.pool_source)
        if cfg.max_stocks > 0:
            stocks = stocks[: cfg.max_stocks]
        total = len(stocks)
        today = scanner.parse_as_of_date(cfg)

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
        done = 0
        if stocks:
            max_workers = max(1, min(int(cfg.workers or 1), total))
            if max_workers <= 1:
                for stock in stocks:
                    done += 1
                    try:
                        found.extend(scanner.scan_stock(stock, cfg, today))
                    except Exception:
                        errors += 1
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
                        executor.submit(scanner.scan_stock, stock, cfg, today)
                        for stock in stocks
                    ]
                    for future in as_completed(futures):
                        done += 1
                        try:
                            found.extend(future.result())
                        except Exception:
                            errors += 1
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    records = _json_safe_records(result_df)
    return {
        "success": True,
        "data": records,
        "count": len(records),
        "elapsed_sec": round(time.time() - started, 1),
        "output": str(output_path),
        "meta": {
            "mode": cfg.scan_mode,
            "pool": cfg.stock_pool,
            "pool_source": cfg.pool_source,
            "recent_days": cfg.recent_days,
            "workers": cfg.workers,
            "scanned": total,
            "errors": errors,
        },
    }


@scanner_bp.route("/api/scanners/wash-pattern", methods=["GET", "POST"])
def wash_pattern_scan():
    """Run the external wash pattern scanner and return table-ready JSON."""
    lock = _EXTERNAL_SCAN_LOCKS["wash_pattern"]
    if not lock.acquire(blocking=False):
        return jsonify({
            "success": False,
            "error": "洗盘形态扫描正在运行，请稍后再试",
        }), 409

    try:
        return jsonify(_run_wash_pattern_scan(_wash_pattern_params_from_request()))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        lock.release()


def _run_wash_pattern_job(job_id, params):
    lock = _EXTERNAL_SCAN_LOCKS["wash_pattern"]

    def progress_callback(**updates):
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
        result = _run_wash_pattern_scan(params, progress_callback=progress_callback)
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
    lock = _EXTERNAL_SCAN_LOCKS["wash_pattern"]
    if not lock.acquire(blocking=False):
        return jsonify({
            "success": False,
            "error": "洗盘形态扫描正在运行，请稍后再试",
        }), 409

    try:
        params = _wash_pattern_params_from_request()
        job = _create_scan_job("wash_pattern")
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
        )
        meta = result.get("meta") or {}
        scanned = int(meta.get("scanned") or 0)
        _update_scan_job(
            job_id,
            status="completed",
            phase="已完成",
            message=f"筛选完成，发现 {result.get('count', 0)} 条结果",
            done=scanned or int(_get_scan_job(job_id).get("done") or 0),
            total=scanned or int(_get_scan_job(job_id).get("total") or 0),
            matched=result.get("count", 0),
            errors=meta.get("errors", 0),
            result=result,
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
        return jsonify({
            "success": False,
            "error": "A股条件筛选正在运行，请稍后再试",
        }), 409

    try:
        params = {
            "threads": _int_param("threads", 10, 1, 32),
            "max_stocks": _int_param("max_stocks", 0, 0, 6000),
            "recent_days": _optional_int_param("recent_days", 1, 240),
            "limit_down": _optional_float_param("limit_down"),
            "recovery": _optional_float_param("recovery"),
        }
        job = _create_scan_job("limit_down_rebound")
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


@scanner_bp.route("/api/scanners/jobs/<job_id>", methods=["GET"])
def scanner_job_status(job_id):
    job = _get_scan_job(job_id)
    if not job:
        return jsonify({"success": False, "error": "扫描任务不存在或已过期"}), 404
    return jsonify({"success": True, "job": job})
