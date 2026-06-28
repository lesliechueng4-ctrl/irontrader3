"""DragonLadder 单元测试（全程 mock，不依赖网络）。"""

import unittest
from unittest.mock import patch

import dragon_ladder as dl_mod
from dragon_ladder import DragonLadder, LadderConfig, _to_minutes


class _FakePool:
    def __init__(self, pool):
        self._pool = pool

    def get_limit_up_pool(self):
        return self._pool


def _stock(code, name, sector, lc, seal, t, turn):
    return {
        "code": code, "name": name, "sector": sector,
        "limit_count": lc, "seal_amount": seal,
        "first_limit_time": t, "turnover_rate": turn,
    }


class TimeParseTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(_to_minutes("09:33:03"), 573)
        self.assertEqual(_to_minutes("0933"), 573)
        self.assertEqual(_to_minutes("093303"), 573)
        self.assertIsNone(_to_minutes(""))
        self.assertIsNone(_to_minutes(None))


class DivergenceTest(unittest.TestCase):
    def setUp(self):
        self.dl = DragonLadder(data_fetcher=_FakePool([]))

    def test_consensus_early_low_turnover(self):
        d = self.dl.classify_divergence(_stock("1", "甲", "A", 1, 1e8, "09:25:30", 3.0))
        self.assertEqual(d["tag"], "一致")

    def test_divergence_high_turnover(self):
        d = self.dl.classify_divergence(_stock("2", "乙", "A", 2, 8e7, "10:30:00", 18.0))
        self.assertEqual(d["tag"], "分歧")

    def test_buy_hint_needs_lianban_diverg_and_seal(self):
        # 2板 + 高换手分歧 + 封单8千万(≥5千万) → 买点
        d = self.dl.classify_divergence(_stock("2", "乙", "A", 2, 8e7, "10:30:00", 18.0))
        self.assertTrue(d["buy_hint"])
        # 首板分歧但非连板 → 不给买点
        d2 = self.dl.classify_divergence(_stock("3", "丙", "A", 1, 8e7, "10:30:00", 18.0))
        self.assertFalse(d2["buy_hint"])


class LadderTest(unittest.TestCase):
    def setUp(self):
        pool = [
            _stock("600001", "甲龙", "芯片", 5, 5e8, "09:25:00", 4.0),    # 龙头 一致
            _stock("600002", "甲二", "芯片", 2, 8e7, "10:30:00", 20.0),   # 龙二 分歧+买点
            _stock("600003", "甲三", "芯片", 1, 3e7, "11:00:00", 15.0),   # 龙三 分歧
            _stock("600010", "乙首", "光伏", 1, 1e8, "14:30:00", 25.0),   # 分歧(尾盘)
        ]
        self.dl = DragonLadder(data_fetcher=_FakePool(pool))

    def test_sector_grouping_and_roles(self):
        sectors = self.dl._build_sectors(self.dl.fetcher.get_limit_up_pool())
        chip = next(s for s in sectors if s["sector"] == "芯片")
        self.assertEqual(chip["count"], 3)
        self.assertEqual(chip["max_height"], 5)
        self.assertEqual(chip["stocks"][0]["role"], "龙头")
        self.assertEqual(chip["stocks"][0]["name"], "甲龙")
        self.assertEqual(chip["stocks"][1]["role"], "龙二")

    def test_gap_detected(self):
        sectors = self.dl._build_sectors(self.dl.fetcher.get_limit_up_pool())
        chip = next(s for s in sectors if s["sector"] == "芯片")
        self.assertTrue(chip["has_gap"])  # 5板 vs 2板 差3 ≥2

    def test_sectors_sorted_by_strength(self):
        sectors = self.dl._build_sectors(self.dl.fetcher.get_limit_up_pool())
        self.assertEqual(sectors[0]["sector"], "芯片")  # 5板 > 光伏1板

    def test_build_with_promotion_and_cache(self):
        import pandas as pd
        prev = pd.DataFrame({"涨跌幅": [10.0, 10.0, 3.0, -2.0]})  # 4只昨涨停，2只今仍涨停
        with patch.object(dl_mod.ak, "stock_zt_pool_previous_em", return_value=prev):
            data = self.dl.build(force=True)
        self.assertAlmostEqual(data["spirit"]["promotion_rate"], 0.5, places=3)
        self.assertEqual(data["spirit"]["max_height"], 5)
        self.assertGreaterEqual(data["spirit"]["buy_hint_count"], 1)
        # 第二次命中缓存
        data2 = self.dl.build()
        self.assertTrue(data2["cached"])


if __name__ == "__main__":
    unittest.main()
