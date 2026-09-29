from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
import time
from unittest.mock import patch

import app as app_module
import market_routes as routes


def _reset_zt_pool_state():
    assert not routes._ZT_POOL.is_building(routes._ZT_POOL_KEY)
    routes._ZT_POOL.clear()


def _run_together(callable_):
    barrier = Barrier(3)

    def worker():
        barrier.wait()
        return callable_()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        barrier.wait()
        return [future.result(timeout=2) for future in futures]


def test_zt_pool_cache_ttl_is_three_minutes():
    _reset_zt_pool_state()
    assert routes._ZT_POOL_CACHE_TTL >= 180

    payload = {'success': True, 'data': [], 'count': 0}
    routes._set_zt_pool_cache(payload, now=100)

    assert routes._get_zt_pool_cache(now=279) is payload
    assert routes._get_zt_pool_cache(now=280) is None


def test_concurrent_cold_miss_builds_zt_pool_once():
    _reset_zt_pool_state()
    calls = 0
    calls_lock = Lock()

    def fake_build(refresh=False):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return {'success': True, 'data': [{'code': '000001'}], 'count': 1}

    with patch.object(routes, '_build_zt_pool_payload', side_effect=fake_build):
        results = _run_together(lambda: routes._get_or_build_zt_pool(False))

    assert calls == 1
    assert [cache_hit for _, cache_hit in results].count(False) == 1
    assert [cache_hit for _, cache_hit in results].count(True) == 1
    assert results[0][0] == results[1][0]


def test_concurrent_refresh_requests_share_one_forced_build():
    _reset_zt_pool_state()
    calls = []
    calls_lock = Lock()

    def fake_build(refresh=False):
        with calls_lock:
            calls.append(refresh)
        time.sleep(0.05)
        return {'success': True, 'data': [{'code': '000002'}], 'count': 1}

    with patch.object(routes, '_build_zt_pool_payload', side_effect=fake_build):
        results = _run_together(lambda: routes._get_or_build_zt_pool(True))

    assert calls == [True]
    assert all(cache_hit is False for _, cache_hit in results)
    assert results[0][0] == results[1][0]


def test_sequential_refresh_requests_still_force_separate_builds():
    _reset_zt_pool_state()
    calls = []

    def fake_build(refresh=False):
        calls.append(refresh)
        return {'success': True, 'data': [{'build': len(calls)}], 'count': 1}

    with patch.object(routes, '_build_zt_pool_payload', side_effect=fake_build):
        first = routes._get_or_build_zt_pool(True)
        second = routes._get_or_build_zt_pool(True)

    assert calls == [True, True]
    assert first[0] != second[0]
    assert first[1] is False
    assert second[1] is False


def test_concurrent_build_error_is_shared_without_duplicate_retry():
    _reset_zt_pool_state()
    calls = 0
    calls_lock = Lock()

    def fake_build(refresh=False):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        raise RuntimeError('upstream unavailable')

    def invoke():
        try:
            routes._get_or_build_zt_pool(False)
        except RuntimeError as exc:
            return str(exc)
        raise AssertionError('expected the shared build error')

    with patch.object(routes, '_build_zt_pool_payload', side_effect=fake_build):
        results = _run_together(invoke)

    assert calls == 1
    assert results == ['upstream unavailable', 'upstream unavailable']


def test_zt_pool_builder_preserves_response_shape_and_seal_order():
    _reset_zt_pool_state()
    stocks = [
        {
            'code': '000001', 'name': '低封单', 'seal_amount': 10,
            'limit_count': 1, 'first_limit_time': '10:00:00',
        },
        {
            'code': '000002', 'name': '高封单', 'seal_amount': 20,
            'limit_count': 2, 'first_limit_time': '09:40:00',
        },
    ]
    decision = {
        'decision': 'WATCH', 'confidence': 0.5, 'reason': '测试',
        'market_state': {}, 'stock_info': {}, 'sector_effect': {},
        'sector_money': {}, 'chip_quality': {}, 'arbitrage': [],
    }

    with patch.object(routes.data_fetcher, 'get_limit_up_pool', return_value=stocks) as fetch:
        with patch.object(
            routes.decision_maker,
            'batch_make_decision',
            return_value={stock['code']: decision for stock in stocks},
        ):
            payload = routes._build_zt_pool_payload(refresh=True)

    fetch.assert_called_once_with(force_refresh=True)
    assert set(payload) == {'success', 'data', 'count'}
    assert payload['success'] is True
    assert payload['count'] == 2
    assert [item['code'] for item in payload['data']] == ['000002', '000001']
