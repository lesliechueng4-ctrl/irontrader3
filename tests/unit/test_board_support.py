import unittest
from unittest.mock import patch

import pandas as pd

from data_fetcher import DataFetcher
from stock_selector import StockSelector
from strategy_enhancements import StockClassifier


class DataFetcherBoardSupportTest(unittest.TestCase):
    def setUp(self):
        self.fetcher = DataFetcher()

    def test_limit_up_thresholds_are_board_aware(self):
        self.assertEqual(self.fetcher._get_limit_up_threshold("600519"), 9.5)
        self.assertEqual(self.fetcher._get_limit_up_threshold("300750"), 19.5)
        self.assertEqual(self.fetcher._get_limit_up_threshold("301183"), 19.5)
        self.assertEqual(self.fetcher._get_limit_up_threshold("688041"), 19.5)
        self.assertEqual(self.fetcher._get_limit_up_threshold("920001"), 29.5)

    def test_check_limit_up_uses_board_thresholds(self):
        self.assertTrue(self.fetcher._check_limit_up("600519", 10.0))
        self.assertFalse(self.fetcher._check_limit_up("300750", 10.0))
        self.assertTrue(self.fetcher._check_limit_up("300750", 20.0))
        self.assertFalse(self.fetcher._check_limit_up("920001", 20.0))
        self.assertTrue(self.fetcher._check_limit_up("920001", 30.0))

    @patch.object(DataFetcher, "_get_cache", return_value=None)
    @patch.object(DataFetcher, "_set_cache")
    @patch("data_fetcher.ak.stock_zh_a_hist", side_effect=RuntimeError("hist unavailable"))
    @patch("data_fetcher.ak.stock_zh_a_daily")
    def test_history_uses_daily_endpoint_first(self, daily_mock, hist_mock, _set_cache, _get_cache):
        daily_mock.return_value = pd.DataFrame(
            {
                "date": ["2026-04-10", "2026-04-11", "2026-04-12"],
                "open": [10, 11, 12],
                "high": [11, 12, 13],
                "low": [9, 10, 11],
                "close": [10.5, 11.5, 12.5],
                "volume": [100, 110, 120],
                "amount": [1000, 1100, 1200],
                "turnover": [0.1, 0.2, 0.3],
            }
        )

        df = self.fetcher.get_stock_history("301183", days=2)

        daily_mock.assert_called_once()
        self.assertEqual(daily_mock.call_args.kwargs["symbol"], "sz301183")
        self.assertEqual(daily_mock.call_args.kwargs["adjust"], "qfq")
        hist_mock.assert_not_called()
        self.assertEqual(list(df.columns), ["date", "open", "high", "low", "close", "volume", "amount", "turnover"])
        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[-1]["close"], 12.5)

    @patch.object(DataFetcher, "_get_cache", return_value=None)
    @patch.object(DataFetcher, "_set_cache")
    @patch("data_fetcher.ak.stock_zh_a_hist")
    @patch("data_fetcher.ak.stock_zh_a_daily", side_effect=RuntimeError("daily unavailable"))
    def test_history_falls_back_to_hist_with_chinese_columns(self, _daily_mock, hist_mock, _set_cache, _get_cache):
        hist_mock.return_value = pd.DataFrame(
            {
                "\u65e5\u671f": ["2026-04-10", "2026-04-11"],
                "\u5f00\u76d8": [10, 11],
                "\u6700\u9ad8": [11, 12],
                "\u6700\u4f4e": [9, 10],
                "\u6536\u76d8": [10.5, 11.5],
                "\u6210\u4ea4\u91cf": [100, 120],
                "\u6210\u4ea4\u989d": [1000, 1200],
                "\u6362\u624b\u7387": [0.1, 0.2],
            }
        )

        df = self.fetcher.get_stock_history("600519", days=1)

        hist_mock.assert_called_once()
        self.assertEqual(hist_mock.call_args.kwargs["symbol"], "600519")
        self.assertEqual(hist_mock.call_args.kwargs["period"], "daily")
        self.assertEqual(hist_mock.call_args.kwargs["adjust"], "qfq")
        self.assertEqual(list(df.columns), ["date", "open", "high", "low", "close", "volume", "amount", "turnover"])
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["close"], 11.5)


class StockSelectorBoardSupportTest(unittest.TestCase):
    def test_trade_time_is_normalized_before_buyability_check(self):
        selector = StockSelector(object())
        is_buyable, _ = selector._check_buyability(
            {"first_limit_time": "093303", "turnover_rate": 2.0}
        )
        self.assertTrue(is_buyable)

    def test_301_stocks_are_included_in_20cm_arbitrage_candidates(self):
        class FakeFetcher:
            @staticmethod
            def get_limit_up_pool():
                return [
                    {
                        "code": "301219",
                        "name": "Test GEM",
                        "sector": "Test Sector",
                        "limit_count": 1,
                        "first_limit_time": "09:33:03",
                        "turnover_rate": 5.0,
                        "seal_amount": 20000000,
                    },
                    {
                        "code": "688813",
                        "name": "Test STAR",
                        "sector": "Test Sector",
                        "limit_count": 1,
                        "first_limit_time": "09:40:00",
                        "turnover_rate": 6.0,
                        "seal_amount": 10000000,
                    },
                ]

        selector = StockSelector(FakeFetcher())
        selector.analyze_stock = lambda code: {"is_buyable": False, "sector": "Test Sector"}

        candidates = selector.get_20cm_arbitrage("002000")

        self.assertIn("301219", [item["code"] for item in candidates])


class StrategyEnhancementBoardSupportTest(unittest.TestCase):
    def test_classifier_marks_301_and_688_as_tech(self):
        df = pd.DataFrame(
            {
                "Close": [10, 10.2, 10.5, 10.7, 11.0],
                "Volume": [100, 100, 100, 100, 100],
            }
        )
        self.assertEqual(StockClassifier.classify_stock(df, "301183"), "tech")
        self.assertEqual(StockClassifier.classify_stock(df, "688041"), "tech")


if __name__ == "__main__":
    unittest.main()
