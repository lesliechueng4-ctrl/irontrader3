import threading
import time
from datetime import datetime

import pandas as pd
import pytest

import sina_spot_client as ssc
from market_clock import TZ


@pytest.fixture(autouse=True)
def _clean_shared():
    ssc.clear_shared_spot_frame()
    yield
    ssc.clear_shared_spot_frame()


def _frame():
    return pd.DataFrame({"代码": ["600276"], "名称": ["恒瑞医药"], "最新价": [47.5], "涨跌幅": [0.1], "换手率": [0.5]})


class _CountingClient:
    calls = 0
    delay = 0.0

    def __init__(self, source_client=None):
        pass

    def fetch_spot_frame(self, node="hs_a"):
        type(self).calls += 1
        time.sleep(type(self).delay)
        return _frame()


def _trading(day):
    return day.weekday() < 5


def test_concurrent_callers_share_one_fetch():
    _CountingClient.calls, _CountingClient.delay = 0, 0.3
    now = datetime(2026, 10, 21, 10, 0, tzinfo=TZ)  # 盘中
    results = []

    def call():
        results.append(ssc.get_shared_spot_frame(max_age=60, now_fn=lambda: now, trading_day=_trading,
                                                 client_factory=_CountingClient))

    threads = [threading.Thread(target=call) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _CountingClient.calls == 1
    assert all(r is results[0] for r in results)
    assert results[0].attrs["fetched_at"] == now.isoformat()


def test_live_session_refetches_after_max_age_but_after_close_does_not():
    _CountingClient.calls, _CountingClient.delay = 0, 0.0
    clock = {"now": datetime(2026, 10, 21, 14, 50, tzinfo=TZ)}
    get = lambda: ssc.get_shared_spot_frame(max_age=60, now_fn=lambda: clock["now"], trading_day=_trading,  # noqa: E731
                                           client_factory=_CountingClient)
    get()
    clock["now"] = datetime(2026, 10, 21, 14, 52, tzinfo=TZ)   # 盘中过了 60 秒：重拉
    get()
    assert _CountingClient.calls == 2
    clock["now"] = datetime(2026, 10, 21, 15, 5, tzinfo=TZ)    # 收盘了，但手里是收盘前的快照：再拉一次
    get()
    assert _CountingClient.calls == 3
    clock["now"] = datetime(2026, 10, 21, 20, 0, tzinfo=TZ)    # 之后整晚都不再拉
    get()
    clock["now"] = datetime(2026, 10, 22, 8, 30, tzinfo=TZ)    # 第二天开盘前也不拉
    get()
    assert _CountingClient.calls == 3


def test_empty_frame_raises_so_callers_can_fall_back():
    class Empty(_CountingClient):
        def fetch_spot_frame(self, node="hs_a"):
            return pd.DataFrame()

    with pytest.raises(RuntimeError):
        ssc.get_shared_spot_frame(client_factory=Empty, now_fn=lambda: datetime(2026, 10, 21, 10, 0, tzinfo=TZ),
                                  trading_day=_trading)
