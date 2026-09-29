from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
import time

import pytest

from single_flight_cache import SingleFlightCache


def _together(fn, n=3):
    barrier = Barrier(n)

    def worker(_):
        barrier.wait()
        return fn()

    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(worker, range(n)))


def test_ttl_expiry_and_max_entries():
    cache = SingleFlightCache(10, max_entries=2)
    cache.set("a", 1, now=0)
    cache.set("b", 2, now=1)
    cache.set("c", 3, now=2)  # 挤掉最旧的 a
    assert cache.get("a", now=3) is None
    assert cache.get("b", now=3) == 2
    assert cache.get("c", now=11.9) == 3
    assert cache.get("c", now=12) is None


def test_keys_build_independently():
    cache = SingleFlightCache(60)
    assert cache.get_or_build("x", lambda: "X") == ("X", False)
    assert cache.get_or_build("y", lambda: "Y") == ("Y", False)
    assert cache.get_or_build("x", lambda: "other") == ("X", True)


def test_uncacheable_result_is_shared_but_not_stored():
    calls = []
    lock = Lock()
    cache = SingleFlightCache(60, should_cache=lambda key, v: v["ok"])

    def build():
        with lock:
            calls.append(1)
        time.sleep(0.05)
        return {"ok": False}

    results = _together(lambda: cache.get_or_build("k", build))
    assert len(calls) == 1
    assert all(value == {"ok": False} and hit is False for value, hit in results)
    assert cache.get("k") is None


def test_error_does_not_poison_later_calls():
    cache = SingleFlightCache(60)
    with pytest.raises(RuntimeError):
        cache.get_or_build("k", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cache.get_or_build("k", lambda: "ok") == ("ok", False)


def test_swr_returns_stale_immediately_and_refreshes_in_background():
    import threading
    import time as _time

    from single_flight_cache import SwrCache

    now = [0.0]
    cache = SwrCache(fresh_ttl=10, stale_ttl=100, clock=lambda: now[0])
    calls = []
    release = threading.Event()

    def builder():
        calls.append(1)
        if len(calls) > 1:
            release.wait(2)
        return len(calls)

    assert cache.get("k", builder) == (1, "built")
    assert cache.get("k", builder) == (1, "fresh")
    now[0] = 50  # 过期但仍可用：马上拿到旧值，不等构建
    started = _time.monotonic()
    assert cache.get("k", builder) == (1, "stale")
    assert _time.monotonic() - started < 0.5
    release.set()
    for _ in range(50):
        if cache.get("k", builder)[0] == 2:
            break
        _time.sleep(0.02)
    assert cache.get("k", builder)[0] == 2


def test_swr_keeps_old_value_when_rebuild_fails():
    from single_flight_cache import SwrCache

    now = [0.0]
    cache = SwrCache(fresh_ttl=10, stale_ttl=100, clock=lambda: now[0])
    cache.get("k", lambda: "ok")
    now[0] = 500  # 太老，需要当场重建；重建失败时退回旧值

    def boom():
        raise RuntimeError("upstream down")

    assert cache.get("k", boom) == ("ok", "stale")
