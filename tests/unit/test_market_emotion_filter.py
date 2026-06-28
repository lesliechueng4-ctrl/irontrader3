"""MarketEmotionFilter 单元测试（全程 mock，不依赖网络）。"""

import unittest
from unittest.mock import patch

import pandas as pd

import market_emotion_filter as mef
from market_emotion_filter import (
    EmotionConfig,
    MarketEmotionFilter,
    PositionManager,
    _linear_map,
)


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


if __name__ == "__main__":
    unittest.main()
