"""MarketEmotionFilter 单元测试（全程 mock，不依赖网络）。"""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import market_emotion_filter as mef
from market_emotion_filter import (
    EmotionConfig,
    MarketEmotionFilter,
    PositionManager,
    _linear_map,
)

# 测试期间龙头池落盘重定向到临时目录，避免污染真实 cache/leader_pool.json
_TMP = tempfile.TemporaryDirectory()
_ORIG_POOL_FILE = MarketEmotionFilter._leader_pool_file


def setUpModule():
    MarketEmotionFilter._leader_pool_file = (
        lambda self: Path(_TMP.name) / "leader_pool.json")


def tearDownModule():
    MarketEmotionFilter._leader_pool_file = _ORIG_POOL_FILE
    _TMP.cleanup()


class _FakeFetcher:
    """注入用假数据源：按代码返回构造好的历史，使近期涨幅可预测。"""

    def __init__(self, returns_by_code=None):
        # returns_by_code: {code: 近期涨幅%}，用于反推一段单调 close 序列
        self.returns_by_code = returns_by_code or {}

    def get_stock_history(self, code, days=30):
        pct = self.returns_by_code.get(code, 0.0)
        base = 10.0
        last = base * (1 + pct / 100.0)
        closes = [base] * 5 + [base] + [last]  # 保证 len >= lookback+1
        # 用线性过渡填满 days 根
        n = max(days, 20)
        closes = [base] * (n - 1) + [last]
        return pd.DataFrame({"close": closes})


def _spot_df():
    """构造全A快照：含龙头候选、ST、科创板、低换手等，用于验证过滤逻辑。"""
    return pd.DataFrame(
        {
            "代码": ["600001", "600002", "600003", "688111", "600004", "600005"],
            "名称": ["龙头A", "龙头B", "ST垃圾", "科创板", "低换手", "龙头C"],
            "涨跌幅": [-8.0, 2.0, -9.0, -10.0, 1.0, -7.5],
            "换手率": [12.0, 8.0, 15.0, 20.0, 0.5, 10.0],
            "最新价": [20.0, 15.0, 3.0, 30.0, 8.0, 12.0],
        }
    )


class LinearMapTest(unittest.TestCase):
    def test_ascending_and_clamp(self):
        self.assertEqual(_linear_map(3.0, -5.0, 3.0), 100.0)
        self.assertEqual(_linear_map(-5.0, -5.0, 3.0), 0.0)
        self.assertEqual(_linear_map(-1.0, -5.0, 3.0), 50.0)
        self.assertEqual(_linear_map(99.0, -5.0, 3.0), 100.0)  # 上夹紧

    def test_descending(self):
        # 跌停家数 0 → 100 分，60 → 0 分
        self.assertEqual(_linear_map(0.0, 60.0, 0.0), 100.0)
        self.assertEqual(_linear_map(60.0, 60.0, 0.0), 0.0)
        self.assertEqual(_linear_map(30.0, 60.0, 0.0), 50.0)


class PositionManagerTest(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(PositionManager.decide(95)["level"], "高潮")
        self.assertEqual(PositionManager.decide(72)["level"], "分歧")
        self.assertEqual(PositionManager.decide(50)["level"], "退潮")
        self.assertEqual(PositionManager.decide(10)["level"], "冰点")

    def test_ice_forbids_opening(self):
        d = PositionManager.decide(5)
        self.assertFalse(d["can_open"])
        self.assertEqual(d["max_total_position"], 0.0)

    def test_cap_position(self):
        # 高潮期单票上限 0.30，意图 0.5 被裁剪到 0.30
        self.assertEqual(PositionManager.cap_position(90, 0.5), 0.30)
        # 冰点期任何意图都归零
        self.assertEqual(PositionManager.cap_position(10, 0.5), 0.0)


class DimensionScoringTest(unittest.TestCase):
    def setUp(self):
        self.flt = MarketEmotionFilter(data_fetcher=_FakeFetcher())

    def test_prev_return_missing_is_neutral(self):
        ds = self.flt._score_prev_return(None)
        self.assertFalse(ds.available)
        self.assertEqual(ds.score, 50.0)

    def test_blowup_scoring(self):
        ds = self.flt._score_blowup({"rate": 0.0, "total": 30, "blown": 0})
        self.assertEqual(ds.score, 100.0)
        ds2 = self.flt._score_blowup({"rate": 0.30, "total": 30, "blown": 9})
        self.assertEqual(ds2.score, 0.0)


class LeaderPoolTest(unittest.TestCase):
    def test_pool_filters_and_ranks(self):
        # 近期涨幅：龙头B 最强，龙头A 次之，龙头C 第三
        fetcher = _FakeFetcher({"600001": 20.0, "600002": 50.0, "600005": 35.0})
        flt = MarketEmotionFilter(
            data_fetcher=fetcher,
            config=EmotionConfig(leader_pool_size=3, leader_workers=2),
        )
        with patch.object(mef.ak, "stock_zh_a_spot_em", return_value=_spot_df()):
            pool = flt._build_leader_pool(force=True)
        # ST(600003)、科创(688111)、低换手(600004) 应被剔除
        self.assertNotIn("600003", pool)
        self.assertNotIn("688111", pool)
        self.assertNotIn("600004", pool)
        # 按近期涨幅排序：600002 最前
        self.assertEqual(pool[0], "600002")

    def test_blowup_rate_uses_live_change(self):
        fetcher = _FakeFetcher({"600001": 20.0, "600002": 50.0, "600005": 35.0})
        flt = MarketEmotionFilter(
            data_fetcher=fetcher,
            config=EmotionConfig(leader_pool_size=3, leader_workers=2, big_loss_pct=-7.0),
        )
        with patch.object(mef.ak, "stock_zh_a_spot_em", return_value=_spot_df()):
            blowup = flt.get_leader_blowup_rate()
        # 龙头池 = {600001(-8%), 600002(+2%), 600005(-7.5%)}；跌超7%的有 600001、600005
        self.assertEqual(blowup["total"], 3)
        self.assertEqual(blowup["blown"], 2)
        self.assertAlmostEqual(blowup["rate"], 2 / 3, places=3)


class DegradedPathTest(unittest.TestCase):
    """数据源故障时的三层降级：旧快照 → 落盘龙头池 → 逐票实时。"""

    def test_spot_stale_fallback(self):
        # 快照源挂了，但 5 分钟前的旧快照(<30min)应被降级复用，而不是返回 None
        flt = MarketEmotionFilter(data_fetcher=_FakeFetcher())
        df = _spot_df()
        flt._spot_cache = df
        flt._spot_cached_at = time.time() - 300  # 已超 spot_cache_ttl(120s)
        with patch.object(mef.ak, "stock_zh_a_spot_em", side_effect=Exception("network down")):
            got = flt._get_spot_snapshot()
        self.assertIs(got, df)

    def test_blowup_realtime_fallback_when_spot_dead(self):
        # 快照彻底不可用 → 逐票实时行情兜底，大面率不再 N/A
        live = {"600001": -8.0, "600002": 2.0, "600005": -7.5}
        fetcher = _FakeFetcher()
        fetcher.get_stock_realtime = lambda code: {
            "code": code, "name": "X", "current": 10.0, "change_pct": live[code]}
        flt = MarketEmotionFilter(
            data_fetcher=fetcher,
            config=EmotionConfig(leader_pool_size=3, leader_workers=2, big_loss_pct=-7.0),
        )
        flt._leader_pool_cache = list(live)
        flt._leader_pool_cached_at = time.time()
        with patch.object(flt, "_get_spot_snapshot", return_value=None):
            blowup = flt.get_leader_blowup_rate()
        self.assertEqual(blowup["total"], 3)
        self.assertEqual(blowup["blown"], 2)
        self.assertAlmostEqual(blowup["rate"], 2 / 3, places=3)

    def test_leader_pool_persist_and_restore(self):
        # 构建成功后落盘；"重启"(新实例)且快照挂掉时，从落盘文件恢复同一池子
        fetcher = _FakeFetcher({"600001": 20.0, "600002": 50.0, "600005": 35.0})
        cfg = EmotionConfig(leader_pool_size=3, leader_workers=2)
        flt = MarketEmotionFilter(data_fetcher=fetcher, config=cfg)
        with patch.object(mef.ak, "stock_zh_a_spot_em", return_value=_spot_df()):
            pool = flt._build_leader_pool(force=True)
        self.assertTrue(pool)

        flt2 = MarketEmotionFilter(data_fetcher=fetcher, config=cfg)
        with patch.object(mef.ak, "stock_zh_a_spot_em", side_effect=Exception("down")):
            pool2 = flt2._build_leader_pool()
        self.assertEqual(pool2, pool)
        # 指标(近期涨幅/昨日走势)也一并恢复
        self.assertIn(pool[0], flt2._leader_metrics)


class PrevLimitupDetailTest(unittest.TestCase):
    def test_detail_items_and_counts(self):
        flt = MarketEmotionFilter(data_fetcher=_FakeFetcher())
        prev_df = pd.DataFrame({
            "代码": ["600001", "600002", "600003"],
            "名称": ["甲", "乙", "丙"],
            "涨跌幅": [5.0, -3.0, 1.0],
        })
        with patch.object(mef.ak, "stock_zt_pool_previous_em", return_value=prev_df):
            detail = flt.get_prev_limitup_detail()
        self.assertEqual(detail["count"], 3)
        self.assertEqual(detail["up_count"], 2)
        self.assertEqual(detail["down_count"], 1)
        # 按今日涨跌幅降序：甲(5) 在最前，乙(-3) 在最后
        self.assertEqual(detail["items"][0]["code"], "600001")
        self.assertEqual(detail["items"][-1]["code"], "600002")
        self.assertAlmostEqual(detail["avg"], 1.0, places=3)


class ResultCacheTest(unittest.TestCase):
    def test_result_cached_then_force_recomputes(self):
        flt = MarketEmotionFilter(data_fetcher=_FakeFetcher())
        prev_df = pd.DataFrame({"代码": ["1"], "名称": ["x"], "涨跌幅": [1.0]})
        dt_df = pd.DataFrame({"代码": ["1"] * 3})
        with patch.object(mef.ak, "stock_zh_a_spot_em", side_effect=RuntimeError("net")), \
             patch.object(mef.ak, "stock_zt_pool_previous_em", return_value=prev_df) as prev_mock, \
             patch.object(mef.ak, "stock_zt_pool_dtgc_em", return_value=dt_df):
            r1 = flt.calculate_emotion_score()
            self.assertFalse(r1["cached"])
            r2 = flt.calculate_emotion_score()
            self.assertTrue(r2["cached"])               # 第二次命中缓存
            self.assertEqual(r1["score"], r2["score"])
            calls_after_cache = prev_mock.call_count
            flt.calculate_emotion_score(force=True)      # 强制重算
            self.assertGreater(prev_mock.call_count, calls_after_cache)

    def test_result_exposes_underlying_market_data_time_when_available(self):
        fetcher = _FakeFetcher()
        fetcher.limit_up_pool_meta = {"as_of": "2026-08-11 15:00:00"}
        flt = MarketEmotionFilter(data_fetcher=fetcher)
        prev_df = pd.DataFrame({"代码": ["1"], "名称": ["x"], "涨跌幅": [1.0]})
        dt_df = pd.DataFrame({"代码": ["1"]})
        with patch.object(mef.ak, "stock_zh_a_spot_em", side_effect=RuntimeError("net")), \
             patch.object(mef.ak, "stock_zt_pool_previous_em", return_value=prev_df), \
             patch.object(mef.ak, "stock_zt_pool_dtgc_em", return_value=dt_df):
            result = flt.calculate_emotion_score()

        self.assertEqual(result["data_as_of"], "2026-08-11 15:00:00")


class IntegrationScoreTest(unittest.TestCase):
    def test_full_score_all_sources_ok(self):
        fetcher = _FakeFetcher({"600001": 20.0, "600002": 50.0, "600005": 35.0})
        flt = MarketEmotionFilter(
            data_fetcher=fetcher,
            config=EmotionConfig(leader_pool_size=3, leader_workers=2),
        )
        prev_df = pd.DataFrame({"涨跌幅": [1.0, 2.0, 3.0]})       # 昨日涨停今日均涨 2%
        dt_df = pd.DataFrame({"代码": ["1"] * 12})                 # 跌停 12 家
        with patch.object(mef.ak, "stock_zh_a_spot_em", return_value=_spot_df()), \
             patch.object(mef.ak, "stock_zt_pool_previous_em", return_value=prev_df), \
             patch.object(mef.ak, "stock_zt_pool_dtgc_em", return_value=dt_df):
            result = flt.calculate_emotion_score()
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertEqual(result["confidence"], 1.0)
        self.assertIn(result["level"], ("高潮", "分歧", "退潮", "冰点"))
        self.assertIn("position", result)

    def test_full_score_degrades_when_sources_fail(self):
        flt = MarketEmotionFilter(data_fetcher=_FakeFetcher())
        # 所有 ak 接口抛错 → 全维度降级为中性，得分应为 50、可信度 0
        with patch.object(mef.ak, "stock_zh_a_spot_em", side_effect=RuntimeError("net")), \
             patch.object(mef.ak, "stock_zt_pool_previous_em", side_effect=RuntimeError("net")), \
             patch.object(mef.ak, "stock_zt_pool_dtgc_em", side_effect=RuntimeError("net")):
            result = flt.calculate_emotion_score()
        self.assertEqual(result["score"], 50)
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["level"], "退潮")



# ---------------------------------------------------------------------------
# 快照数据源 / 落盘 / 冷启动 / 非交易时段（2026-10 卡顿排查后的改造）
# ---------------------------------------------------------------------------
import threading  # noqa: E402
from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

import signal_journal  # noqa: E402
from market_clock import TZ  # noqa: E402


def _ts(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=TZ).timestamp()


class _SinaFetcher(_FakeFetcher):
    """带新浪共享快照与缓存目录的假数据源。"""

    def __init__(self, cache_dir=None, frame_fn=None, **kw):
        super().__init__(**kw)
        self.frame_fn = frame_fn or _spot_df
        self.calls = 0
        if cache_dir is not None:
            self.cache_manager = SimpleNamespace(cache_dir=str(cache_dir))

    def get_market_spot_frame(self, max_age=60.0):
        self.calls += 1
        return self.frame_fn()


def _weekday(day):
    return day.weekday() < 5


def _filter(fetcher, now_ts):
    flt = MarketEmotionFilter(data_fetcher=fetcher)
    flt._trading_day = _weekday
    flt._clock = lambda: now_ts
    return flt


def test_prefers_sina_frame_over_eastmoney():
    fetcher = _SinaFetcher()
    flt = _filter(fetcher, _ts(2026, 10, 21, 10, 0))
    with patch.object(mef.ak, "stock_zh_a_spot_em", side_effect=AssertionError("不应调用东财")):
        got = flt._get_spot_snapshot()
    assert list(got["代码"]) == list(_spot_df()["代码"])
    assert flt._spot_source == "新浪" and fetcher.calls == 1


def test_falls_back_to_eastmoney_when_sina_fails():
    def down():
        raise RuntimeError("新浪挂了")

    flt = _filter(_SinaFetcher(frame_fn=down), _ts(2026, 10, 21, 10, 0))
    with patch.object(mef.ak, "stock_zh_a_spot_em", return_value=_spot_df()):
        got = flt._get_spot_snapshot()
    assert got is not None and flt._spot_source == "东方财富"


def test_no_refetch_in_lunch_break_once_snapshot_is_after_lunch_close():
    fetcher = _SinaFetcher()
    flt = _filter(fetcher, _ts(2026, 10, 21, 12, 40))
    flt._spot_cache = _spot_df()
    flt._spot_cached_at = _ts(2026, 10, 21, 11, 33)    # 午间收盘后取的
    assert flt._get_spot_snapshot() is flt._spot_cache
    assert fetcher.calls == 0
    # 同样的快照到了下午开盘就过期了，要重拉
    flt._clock = lambda: _ts(2026, 10, 21, 13, 5)
    flt._get_spot_snapshot()
    assert fetcher.calls == 1


def test_snapshot_persisted_and_restored_after_close(tmp_path):
    frame = _spot_df()
    frame.attrs["fetched_at"] = datetime(2026, 10, 21, 15, 5, tzinfo=TZ).isoformat()
    first = _filter(_SinaFetcher(cache_dir=tmp_path, frame_fn=lambda: frame), _ts(2026, 10, 21, 15, 6))
    first._get_spot_snapshot()
    assert (tmp_path / "emotion_spot.json").exists()

    def boom():
        raise AssertionError("收盘后的落盘快照就是当前状态，不应重拉")

    restarted = _filter(_SinaFetcher(cache_dir=tmp_path, frame_fn=boom), _ts(2026, 10, 21, 20, 0))
    got = restarted._get_spot_snapshot()
    assert list(got["代码"]) == list(frame["代码"])
    assert list(got["换手率"]) == list(frame["换手率"])
    assert restarted._spot_stale is False and restarted._spot_source.startswith("落盘快照")


def test_cold_start_in_session_serves_disk_snapshot_and_refreshes_in_background(tmp_path):
    now = _ts(2026, 10, 21, 10, 30)
    seed = _filter(_SinaFetcher(cache_dir=tmp_path), now - 300)
    seed._get_spot_snapshot()                      # 5 分钟前落过一次盘

    release = threading.Event()
    fresh = _spot_df().assign(涨跌幅=[1.0] * 6)

    def slow():
        release.wait(5)
        return fresh

    fetcher = _SinaFetcher(cache_dir=tmp_path, frame_fn=slow)
    flt = _filter(fetcher, now)
    started = time.monotonic()
    got = flt._get_spot_snapshot()
    assert time.monotonic() - started < 1.0        # 不等新快照
    assert list(got["涨跌幅"]) == list(_spot_df()["涨跌幅"])
    assert flt._spot_stale is True

    release.set()
    for _ in range(100):
        if not flt._spot_stale:
            break
        time.sleep(0.02)
    assert flt._spot_stale is False
    assert list(flt._get_spot_snapshot()["涨跌幅"]) == [1.0] * 6


def test_old_disk_snapshot_in_session_is_not_used(tmp_path):
    now = _ts(2026, 10, 21, 10, 30)
    seed = _filter(_SinaFetcher(cache_dir=tmp_path), now - 3 * 3600)   # 3 小时前
    seed._get_spot_snapshot()
    fetcher = _SinaFetcher(cache_dir=tmp_path)
    flt = _filter(fetcher, now)
    flt._get_spot_snapshot()
    assert fetcher.calls == 1 and flt._spot_stale is False             # 当场取新的


def test_stale_snapshot_marks_result_and_skips_result_cache():
    flt = MarketEmotionFilter(data_fetcher=_FakeFetcher())
    flt._spot_stale = True
    flt._spot_cache = _spot_df()
    flt._spot_cached_at = time.time() - 120
    with patch.object(flt, "get_prev_limitup_detail",
                      return_value={"avg": 1.0, "count": 1, "up_count": 1, "down_count": 0, "items": []}), \
         patch.object(flt, "get_leader_blowup_rate",
                      return_value={"rate": 0.0, "total": 3, "blown": 0, "threshold_pct": -7.0, "items": []}), \
         patch.object(flt, "get_limit_down_count", return_value=3):
        result = flt.calculate_emotion_score()
    assert result["stale"] is True and "落盘快照" in result["stale_reason"]
    assert flt._result_cache is None


def test_leader_pool_not_rebuilt_from_stale_snapshot():
    flt = MarketEmotionFilter(data_fetcher=_FakeFetcher())
    flt._leader_pool_cache = ["600009"]
    flt._leader_pool_cached_at = time.time() - 99999      # 过期
    flt._spot_stale = True
    with patch.object(flt, "_get_spot_snapshot", return_value=_spot_df()):
        assert flt._build_leader_pool() == ["600009"]


def test_recent_closes_use_tencent_and_skip_todays_partial_bar(monkeypatch):
    bars = [{"date": f"2026-10-{d:02d}", "open": 1, "close": float(d), "high": 1, "low": 1} for d in range(8, 22)]
    monkeypatch.setattr(signal_journal, "tencent_bars", lambda client, code, count=260: bars)
    monkeypatch.setattr(signal_journal, "now_sh", lambda: datetime(2026, 10, 21, 10, 0, tzinfo=TZ))
    fetcher = _FakeFetcher()
    fetcher.source_client = object()
    fetcher.get_stock_history = lambda *a, **k: pytest.fail("腾讯可用时不应走 AKShare")
    closes = MarketEmotionFilter(data_fetcher=fetcher)._recent_closes("002080", days=5)
    assert closes == [16.0, 17.0, 18.0, 19.0, 20.0]   # 盘中不含当天（21 日）的未完成 K 线


if __name__ == "__main__":
    unittest.main()
