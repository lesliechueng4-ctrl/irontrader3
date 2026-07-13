"""SignalBacktest 单元测试（全程 mock，不依赖网络）。"""

import unittest
from unittest.mock import patch

import pandas as pd

from backtest import SignalBacktest
from dragon_ladder import DragonLadder


def _price_df(dates, opens, closes):
    return pd.DataFrame({"date": dates, "open": opens, "close": closes})


class _FakeFetcher:
    """get_stock_history 按代码返回构造好的 OHLC，用于精确验证前向收益。"""

    def __init__(self, hist):
        self.hist = hist  # {code: DataFrame}

    def get_stock_history(self, code, days=30):
        return self.hist.get(code)


class ForwardReturnTest(unittest.TestCase):
    def setUp(self):
        self.bt = SignalBacktest(data_fetcher=_FakeFetcher({}), ladder=DragonLadder(_FakeFetcher({})))

    def test_entry_nextopen_exit_close(self):
        # D=06-02 收10; D+1=06-03 开10 收11; D+3=06-05 收12
        pm = {
            "2026-06-02": {"open": 9.8, "close": 10.0},
            "2026-06-03": {"open": 10.0, "close": 11.0},
            "2026-06-04": {"open": 11.0, "close": 11.5},
            "2026-06-05": {"open": 11.5, "close": 12.0},
        }
        dates = sorted(pm)
        # 持有1日：买10开、卖06-03收11 → +10%
        self.assertAlmostEqual(self.bt._forward_return(pm, dates, "2026-06-02", 1, True), 10.0, places=2)
        # 持有3日：买10开、卖06-05收12 → +20%
        self.assertAlmostEqual(self.bt._forward_return(pm, dates, "2026-06-02", 3, True), 20.0, places=2)

    def test_exclude_unbuyable_gap(self):
        # 次日开盘 10.99 相对昨收10 = +9.9% ≥9.7% → 视为买不进，返回 None
        pm = {
            "2026-06-02": {"open": 9.8, "close": 10.0},
            "2026-06-03": {"open": 10.99, "close": 11.0},
            "2026-06-04": {"open": 11.0, "close": 11.2},
        }
        dates = sorted(pm)
        self.assertIsNone(self.bt._forward_return(pm, dates, "2026-06-02", 1, True))
        # 关闭剔除则可计算
        self.assertIsNotNone(self.bt._forward_return(pm, dates, "2026-06-02", 1, False))

    def test_insufficient_future_returns_none(self):
        pm = {"2026-06-02": {"open": 9.8, "close": 10.0}, "2026-06-03": {"open": 10.0, "close": 11.0}}
        dates = sorted(pm)
        self.assertIsNone(self.bt._forward_return(pm, dates, "2026-06-02", 3, True))


class AggregateTest(unittest.TestCase):
    def test_winrate_and_stats(self):
        a = SignalBacktest._aggregate([10.0, -5.0, 20.0, None, 0.0])
        self.assertEqual(a["n"], 4)               # None 被剔除
        self.assertEqual(a["win_rate"], 0.5)      # 10,20 >0 ; -5,0 不算
        self.assertEqual(a["best"], 20.0)
        self.assertEqual(a["worst"], -5.0)

    def test_empty(self):
        a = SignalBacktest._aggregate([None, None])
        self.assertEqual(a["n"], 0)
        self.assertIsNone(a["win_rate"])


class RunIntegrationTest(unittest.TestCase):
    def test_run_end_to_end_mocked(self):
        # 两只票，足够历史；一个买点信号
        dates = [f"2026-05-{d:02d}" for d in range(20, 30)]  # 05-20..05-29
        rising = _price_df(dates, [10 + i for i in range(10)], [10.5 + i for i in range(10)])
        fetcher = _FakeFetcher({"600001": rising})
        bt = SignalBacktest(data_fetcher=fetcher, ladder=DragonLadder(fetcher))

        pool = [{
            "code": "600001", "name": "测试", "sector": "芯片",
            "limit_count": 2, "seal_amount": 8e7, "first_limit_time": "10:30:00",
            "turnover_rate": 18.0,   # 连板+高换手分歧+封单 → buy_hint
        }]

        with patch.object(bt, "trading_days", return_value=[d.replace("-", "") for d in dates]), \
             patch.object(bt, "historical_zt_pool", side_effect=lambda d: pool):
            res = bt.run(days=3, signal="buy_hint", horizons=[1, 2], max_per_day=10)

        self.assertGreater(res["horizons"]["1"]["n"], 0)
        self.assertIn("trades", res)
        self.assertTrue(all("ret_1" in t for t in res["trades"]))


class SummarizeCostTest(unittest.TestCase):
    def test_cost_sensitivity_rows(self):
        from backtest_study import summarize
        df = pd.DataFrame({
            "date": ["2026-06-02", "2026-06-03"],
            "code": ["600001", "600002"],
            "cycle": ["弱", "弱"],
            "role": ["龙头", "龙二"],
            "divergence": ["分歧", "分歧"],
            "buy_hint": [True, True],
            "ret_3": [5.0, -4.0],
        })
        out = summarize(df, [3])
        cs = {c["cost"]: c for c in out["cost_sensitivity"]}
        self.assertEqual(cs[0.0]["n"], 2)
        self.assertAlmostEqual(cs[0.3]["avg"], 0.2, places=2)   # (4.7 - 4.3) / 2
        self.assertEqual(cs[0.5]["win"], 0.5)                    # 4.5 赢 / -4.5 输


class MergeSamplesTest(unittest.TestCase):
    def test_dedup_keeps_latest_and_sorts(self):
        from backtest_study import merge_samples
        old = pd.DataFrame({"date": ["2026-06-02", "2026-06-03"], "code": ["600001", "600002"], "ret_3": [5.0, 1.0]})
        new = pd.DataFrame({"date": ["2026-06-03", "2026-06-04"], "code": ["600002", "600003"], "ret_3": [9.9, 2.0]})
        m = merge_samples(old, new)
        self.assertEqual(len(m), 3)  # 600002@06-03 去重
        row = m[(m["date"] == "2026-06-03") & (m["code"] == "600002")].iloc[0]
        self.assertEqual(row["ret_3"], 9.9)  # 保留最新
        self.assertEqual(list(m["date"]), ["2026-06-02", "2026-06-03", "2026-06-04"])  # 已排序

    def test_merge_handles_empty(self):
        from backtest_study import merge_samples
        new = pd.DataFrame({"date": ["2026-06-02"], "code": ["1"], "ret_3": [1.0]})
        self.assertEqual(len(merge_samples(None, new)), 1)
        self.assertEqual(len(merge_samples(new, None)), 1)
        self.assertTrue(merge_samples(None, None).empty)


if __name__ == "__main__":
    unittest.main()
