import threading
import time
from datetime import datetime, timedelta

import pandas as pd

import data_fetcher
from market_clock import TZ
from single_flight_cache import MarketSwr


def _trading(day):
    return day.weekday() < 5


class _Loader:
    def __init__(self, values=None, delay=0.0):
        self.calls = 0
        self.values = list(values or [])
        self.delay = delay
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            self.calls += 1
            n = self.calls
        time.sleep(self.delay)
        if self.values:
            value = self.values.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        return {"板块": n}


def _wait_refresh(swr, timeout=2.0):
    deadline = time.time() + timeout
    while swr.is_refreshing() and time.time() < deadline:
        time.sleep(0.01)
    assert not swr.is_refreshing()


def _swr(loader, wall, **kw):
    return MarketSwr(loader, 60, 900, now_fn=lambda: wall["now"], trading_day=_trading, **kw)


def test_lunch_break_and_after_close_do_not_refetch():
    loader = _Loader()
    clock = {"now": datetime(2026, 10, 21, 11, 40, tzinfo=TZ)}  # 午休
    swr = _swr(loader, clock)
    assert swr.get() == {"板块": 1}
    clock["now"] = datetime(2026, 10, 21, 12, 55, tzinfo=TZ)
    assert swr.get() == {"板块": 1}
    assert loader.calls == 1
    clock["now"] = datetime(2026, 10, 21, 13, 5, tzinfo=TZ)    # 下午开盘：午休时取的已经过时（超过 15 分钟），当场重拉
    assert swr.get() == {"板块": 2}
    clock["now"] = datetime(2026, 10, 21, 14, 58, tzinfo=TZ)
    assert swr.get() == {"板块": 3}
    clock["now"] = datetime(2026, 10, 21, 15, 3, tzinfo=TZ)    # 刚收盘：先给 14:58 的旧值，后台再拉一次收盘后的
    assert swr.get() == {"板块": 3}
    _wait_refresh(swr)
    clock["now"] = datetime(2026, 10, 21, 21, 0, tzinfo=TZ)    # 晚上一直用收盘后那一份
    assert swr.get() == {"板块": 4}
    clock["now"] = datetime(2026, 10, 22, 9, 0, tzinfo=TZ)     # 第二天开盘前也不拉
    assert swr.get() == {"板块": 4}
    assert loader.calls == 4


def test_live_session_serves_stale_value_while_one_background_refresh_runs():
    loader = _Loader(delay=0.2)
    clock = {"now": datetime(2026, 10, 21, 10, 0, tzinfo=TZ)}
    swr = _swr(loader, clock)
    assert swr.get() == {"板块": 1}
    clock["now"] += timedelta(seconds=30)
    assert swr.get() == {"板块": 1}            # 新鲜期内不拉
    assert loader.calls == 1
    clock["now"] += timedelta(seconds=60)      # 过期但在可用期内：立刻给旧值
    started = time.time()
    results = [swr.get() for _ in range(5)]
    assert time.time() - started < 0.15        # 没人等那 0.2 秒
    assert results == [{"板块": 1}] * 5
    _wait_refresh(swr)
    assert loader.calls == 2                   # 5 个请求只触发一次后台刷新
    assert swr.get() == {"板块": 2}


def test_cold_start_concurrent_callers_share_one_fetch():
    loader = _Loader(delay=0.2)
    clock = {"now": datetime(2026, 10, 21, 10, 0, tzinfo=TZ)}
    swr = _swr(loader, clock)
    results = []
    threads = [threading.Thread(target=lambda: results.append(swr.get())) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert loader.calls == 1
    assert results == [{"板块": 1}] * 5


def test_failures_keep_old_value_then_cool_down_when_nothing_is_left():
    mono = {"t": 0.0}
    loader = _Loader(values=[{"板块": "早"}, RuntimeError("东财超时"), RuntimeError("东财超时"),
                             RuntimeError("还是超时"), {"板块": "恢复"}])
    clock = {"now": datetime(2026, 10, 21, 10, 0, tzinfo=TZ)}
    swr = _swr(loader, clock, clock=lambda: mono["t"], fail_cooldown=30)
    assert swr.get() == {"板块": "早"}
    clock["now"] += timedelta(minutes=5)
    assert swr.get() == {"板块": "早"}         # 后台刷新失败，旧值照用
    _wait_refresh(swr)
    clock["now"] += timedelta(minutes=20)      # 旧值超过 15 分钟：不能再用，当场拉又失败
    assert swr.get() is None
    calls = loader.calls
    mono["t"] += 10
    assert swr.get() is None                   # 冷却期内不再打数据源
    assert loader.calls == calls
    mono["t"] += 30
    assert swr.get() is None                   # 冷却期过了再试一次（还是失败）
    assert loader.calls == calls + 1
    mono["t"] += 31
    assert swr.get() == {"板块": "恢复"}


def test_restore_uses_disk_copy_only_while_it_is_still_valid():
    clock = {"now": datetime(2026, 10, 21, 12, 30, tzinfo=TZ)}
    loader = _Loader()
    lunch_copy = ({"板块": "午休落盘"}, datetime(2026, 10, 21, 11, 45, tzinfo=TZ))
    swr = _swr(loader, clock, restore=lambda: lunch_copy)
    assert swr.get() == {"板块": "午休落盘"}
    assert loader.calls == 0

    clock["now"] = datetime(2026, 10, 21, 13, 40, tzinfo=TZ)  # 盘中重启，落盘的是 40 分钟前的：当场拉
    old_copy = ({"板块": "旧"}, datetime(2026, 10, 21, 13, 0, tzinfo=TZ))
    swr2 = _swr(loader, clock, restore=lambda: old_copy)
    assert swr2.get() == {"板块": 1}


def test_store_is_called_after_each_successful_fetch():
    stored = []
    clock = {"now": datetime(2026, 10, 21, 10, 0, tzinfo=TZ)}
    swr = _swr(_Loader(values=[{}, {"板块": "有"}]), clock, store=stored.append, fail_cooldown=0)
    assert swr.get() is None                   # 空结果不算成功，也不落盘
    assert swr.get() == {"板块": "有"}
    assert stored == [{"板块": "有"}]


def test_data_fetcher_sector_flow_is_shared_and_failures_return_empty(monkeypatch):
    calls = {"em": 0, "ths": 0}

    def em(**kwargs):
        calls["em"] += 1
        return pd.DataFrame({"名称": ["半导体"], "序号": [1], "今日主力净流入-净额": [8e8],
                             "今日主力净流入-净占比": [3.0]})

    def ths(**kwargs):
        calls["ths"] += 1
        raise RuntimeError("同花顺也挂了")

    monkeypatch.setattr(data_fetcher.ak, "stock_sector_fund_flow_rank", em)
    monkeypatch.setattr(data_fetcher.ak, "stock_fund_flow_industry", ths)
    first, second = data_fetcher.DataFetcher(), data_fetcher.DataFetcher()
    monkeypatch.setattr(first, "_restore_sector_money_flow", lambda: None)
    monkeypatch.setattr(first, "_set_cache", lambda key, value: None)

    flow = first.get_sector_money_flow_map()
    assert flow["半导体"]["net_inflow"] == 8e8
    assert second.get_sector_money_flow_map() is flow   # 龙头决策那个实例也用同一份
    assert calls == {"em": 1, "ths": 0}

    data_fetcher.clear_sector_flow_cache()
    monkeypatch.setattr(data_fetcher.ak, "stock_sector_fund_flow_rank",
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("东财超时")))
    assert first.get_sector_money_flow_map() == {}      # 两个源都失败、也没有旧值：返回空，调用方按"暂无"处理
    assert calls["ths"] == 1
