"""DragonLadder 单元测试（全程 mock，不依赖网络）。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dragon_ladder as dl_mod
from dragon_ladder import DragonLadder, LadderConfig, _to_minutes

# 周期历史落盘重定向到临时目录，避免测试污染真实 cache/cycle_history.json
_TMP = tempfile.TemporaryDirectory()
_ORIG_CYCLE_PATH = DragonLadder._cycle_history_path


def setUpModule():
    DragonLadder._cycle_history_path = (
        lambda self: Path(_TMP.name) / "cycle_history.json")


def tearDownModule():
    DragonLadder._cycle_history_path = _ORIG_CYCLE_PATH
    _TMP.cleanup()


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

    def test_break_count_forces_divergence(self):
        # 早盘秒封+缩量本应"一致"，但盘中炸板2次回封 → 分歧
        s = _stock("4", "丁", "A", 2, 8e7, "09:25:00", 3.0)
        s["break_count"] = 2
        d = self.dl.classify_divergence(s)
        self.assertEqual(d["tag"], "分歧")
        self.assertIn("炸板2次", d["reason"])
        self.assertTrue(d["buy_hint"])  # 连板 + 分歧 + 封单强

    def test_cross_weak_to_strong(self):
        # 昨日炸板尾封 → 今日早盘回封且有承接换手 = 昨弱今强，给买点
        today = _stock("5", "戊", "A", 2, 1e8, "09:26:00", 9.0)
        prev = {"first_limit_time": "14:40:00", "break_count": 3, "turnover_rate": 20.0}
        d = self.dl.classify_divergence(today, prev)
        self.assertEqual(d["cross"], "昨弱今强")
        self.assertTrue(d["buy_hint"])

    def test_acceleration_beats_wts(self):
        # 3板+昨弱今封但缩量一字(买不进、主升末端)：一致加速优先，压掉买点
        today = _stock("5b", "戊二", "A", 3, 1e8, "09:26:00", 4.0)
        prev = {"first_limit_time": "14:40:00", "break_count": 3, "turnover_rate": 20.0}
        d = self.dl.classify_divergence(today, prev)
        self.assertEqual(d["cross"], "昨弱今强")
        self.assertTrue(d["sell_alert"])
        self.assertFalse(d["buy_hint"])

    def test_stock_level_consensus_acceleration_sell(self):
        # 4板 + 首封较昨提前2小时+ + 换手 22%→6% 骤降 → 个股"一致加速"兑现提示，且不给买点
        today = _stock("6", "己", "A", 4, 2e8, "09:30:00", 6.0)
        prev = {"first_limit_time": "13:40:00", "break_count": 0, "turnover_rate": 22.0}
        d = self.dl.classify_divergence(today, prev)
        self.assertTrue(d["sell_alert"])
        self.assertFalse(d["buy_hint"])

    def test_no_prev_snapshot_no_cross_signals(self):
        d = self.dl.classify_divergence(_stock("7", "庚", "A", 3, 1e8, "09:26:00", 4.0), None)
        self.assertEqual(d["cross"], "")
        self.assertEqual(d["sell_alert"], "")


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


class CycleTransitionTest(unittest.TestCase):
    def setUp(self):
        self.dl = DragonLadder(data_fetcher=_FakePool([]))
        self.path = self.dl._cycle_history_path()
        if self.path.exists():
            self.path.unlink()

    def _seed_prev(self, cycle, rate=0.1):
        self.path.write_text(
            json.dumps({"2020-01-01": {"cycle": cycle, "rate": rate}}), encoding="utf-8")

    def test_first_record_no_transition(self):
        self.assertIsNone(self.dl._cycle_transition("弱", 0.1))
        hist = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(hist), 1)  # 今天已记录

    def test_up_transition(self):
        self._seed_prev("弱", 0.12)
        cc = self.dl._cycle_transition("强", 0.45)
        self.assertEqual((cc["from"], cc["to"], cc["direction"]), ("弱", "强", "up"))

    def test_down_transition(self):
        self._seed_prev("强", 0.5)
        cc = self.dl._cycle_transition("弱", 0.1)
        self.assertEqual(cc["direction"], "down")

    def test_same_cycle_no_transition(self):
        self._seed_prev("中", 0.3)
        self.assertIsNone(self.dl._cycle_transition("中", 0.25))

    def test_unknown_cycle_not_recorded(self):
        self.assertIsNone(self.dl._cycle_transition("未知", None))
        self.assertFalse(self.path.exists())  # 未知档不落盘

    def test_intraday_overwrite_same_day(self):
        self._seed_prev("弱")
        self.dl._cycle_transition("中", 0.25)
        self.dl._cycle_transition("强", 0.45)   # 盘中再变，覆盖当天记录
        hist = json.loads(self.path.read_text(encoding="utf-8"))
        today_entries = [v for k, v in hist.items() if k != "2020-01-01"]
        self.assertEqual(len(today_entries), 1)
        self.assertEqual(today_entries[0]["cycle"], "强")


if __name__ == "__main__":
    unittest.main()
