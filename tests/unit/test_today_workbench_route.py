from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
import time
from unittest.mock import patch

import app as app_module
import market_routes as routes


def _candidate(code="000001"):
    return {
        "code": code,
        "name": code,
        "sector": "测试",
        "sector_rank": 1,
        "role": "龙头",
        "limit_count": 2,
        "divergence": "分歧",
        "cross": "昨弱今强",
        "buy_hint": True,
        "buy_hint_reliable": True,
        "precheck_score": 100,
        "reasons": ["昨弱今强"],
        "blockers": [],
        "tier": "primary",
        "rank": 1,
        "next_action": "analyze_stock",
    }


def _workbench():
    return {
        "status": "ready",
        "quality": "high",
        "executable": True,
        "warnings": [],
        "primary": [_candidate()],
        "watch": [],
        "source_summary": {"eligible_precheck_count": 1},
    }


def _clear_cache():
    routes._TODAY_WORKBENCH.clear()


def test_session_key_isolated_across_shanghai_trading_boundaries():
    values = [
        datetime(2026, 8, 12, 9, 29),
        datetime(2026, 8, 12, 9, 30),
        datetime(2026, 8, 12, 11, 31),
        datetime(2026, 8, 12, 13, 0),
        datetime(2026, 8, 12, 15, 1),
    ]

    keys = [routes._today_workbench_session_key(value) for value in values]

    assert keys == [
        "2026-08-12:review_preopen",
        "2026-08-12:live_am",
        "2026-08-12:review_lunch",
        "2026-08-12:live_pm",
        "2026-08-12:review_closed",
    ]
    # 01:30 UTC is 09:30 in Shanghai.
    assert routes._today_workbench_session_key(
        datetime(2026, 8, 12, 1, 30, tzinfo=timezone.utc)
    ).endswith(":live_am")


def test_cache_ttl_is_at_least_three_minutes_and_entries_are_phase_scoped():
    assert routes._TODAY_WORKBENCH_CACHE_TTL >= 180
    _clear_cache()
    routes._set_today_workbench_cache("day:live_am", {"value": 1}, now=100)

    assert routes._get_today_workbench_cache("day:live_am", now=279) == {"value": 1}
    assert routes._get_today_workbench_cache("day:review_lunch", now=279) is None
    assert routes._get_today_workbench_cache("day:live_am", now=280) is None


def test_concurrent_normal_cache_miss_builds_only_once():
    _clear_cache()
    calls = 0
    calls_lock = Lock()

    def fake_build(refresh=False):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return {"build": calls}

    with patch.object(routes, "_today_workbench_session_key", return_value="2026-08-12:live_am"):
        with patch.object(routes, "_build_today_workbench_result", side_effect=fake_build):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: routes._get_or_build_today_workbench(False), range(2)))

    assert calls == 1
    assert [hit for _, hit in results].count(False) == 1
    assert [hit for _, hit in results].count(True) == 1
    assert results[0][0] == results[1][0]


def test_slow_build_crossing_session_discards_old_result_and_rebuilds():
    _clear_cache()
    live_key = "2026-08-12:live_am"
    review_key = "2026-08-12:review_lunch"
    # 阶段 key 的读取时机：开始时一次，每次构建完成后一次。
    # 第一次构建期间跨入午休 → 丢弃 live 结果，按 review 阶段重建。
    keys = iter([live_key, review_key, review_key])
    builds = iter([
        {"phase": "live-result"},
        {"phase": "review-result"},
    ])

    with patch.object(routes, "_today_workbench_session_key", side_effect=lambda: next(keys)):
        with patch.object(
            routes,
            "_build_today_workbench_result",
            side_effect=lambda refresh=False: next(builds),
        ) as build:
            result, cache_hit = routes._get_or_build_today_workbench(False)

    assert build.call_count == 2
    assert cache_hit is False
    assert result == {"phase": "review-result"}
    assert routes._get_today_workbench_cache(live_key) is None
    assert routes._get_today_workbench_cache(review_key) == result


def test_busy_risk_lock_returns_pending_watch_without_running_engine():
    base = _workbench()
    routes._TODAY_WORKBENCH_RISK_LOCK.acquire()
    try:
        with patch.object(routes, "_get_low_buy_engine_fn") as get_engine:
            result = routes._risk_precheck_workbench_candidates(base)
    finally:
        routes._TODAY_WORKBENCH_RISK_LOCK.release()

    get_engine.assert_not_called()
    assert result["primary"] == []
    assert result["watch"][0]["risk_precheck"]["status"] == "pending"
    assert result["deep_precheck"]["pending"] is True
    assert result["executable"] is False
    assert result["quality"] == "medium"


def test_partial_deep_errors_downgrade_to_medium_and_disable_execution():
    result = {
        **_workbench(),
        "deep_precheck": {"reviewed": 2, "passed": 1, "excluded": 0, "errors": 1},
    }

    checked = routes._apply_today_workbench_deep_quality(result)

    assert checked["quality"] == "medium"
    assert checked["executable"] is False
    assert checked["primary"]
    assert any("1 只异常" in warning for warning in checked["warnings"])


def test_all_deep_checks_failed_are_low_degraded_and_clear_primary():
    result = {
        **_workbench(),
        "deep_precheck": {"reviewed": 0, "passed": 0, "excluded": 0, "errors": 3},
    }

    checked = routes._apply_today_workbench_deep_quality(result)

    assert checked["status"] == "degraded"
    assert checked["quality"] == "low"
    assert checked["executable"] is False
    assert checked["primary"] == []
    assert any("全部失败" in warning for warning in checked["warnings"])
