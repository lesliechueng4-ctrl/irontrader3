import unittest

import pandas as pd

from chip_quality_strategy import ChipQualityStrategy
from data_fetcher import DataFetcher
from risk_engine import RiskEngine


class DataFetcherSentimentTest(unittest.TestCase):
    def setUp(self):
        self.fetcher = DataFetcher()

    def test_market_sentiment_detects_premium_smallcap_style(self):
        zt_pool = []
        for idx in range(12):
            zt_pool.append({
                "code": f"301{idx:03d}",
                "sector": "AI" if idx < 6 else "Robot",
                "board_type": "gem",
                "first_limit_time": "09:30:30",
                "seal_amount": 250_000_000,
                "limit_count": 2 if idx < 8 else 1,
            })
        for idx in range(8):
            zt_pool.append({
                "code": f"688{idx:03d}",
                "sector": "Chip",
                "board_type": "star",
                "first_limit_time": "09:35:00",
                "seal_amount": 180_000_000,
                "limit_count": 3 if idx < 2 else 1,
            })
        for idx in range(10):
            zt_pool.append({
                "code": f"600{idx:03d}",
                "sector": "Main",
                "board_type": "main",
                "first_limit_time": "10:05:00",
                "seal_amount": 80_000_000,
                "limit_count": 1,
            })

        sentiment = self.fetcher.get_market_sentiment(zt_pool)

        self.assertEqual(sentiment["style_bias"], "premium_smallcap")
        self.assertEqual(sentiment["dominant_board"], "gem")
        self.assertEqual(sentiment["temperature"], "hot")
        self.assertEqual(sentiment["total_limit_ups"], 30)


class RiskEngineSentimentIntegrationTest(unittest.TestCase):
    class FakeFetcher:
        @staticmethod
        def get_index_with_ma5():
            return {
                "current": 3200,
                "ma5": 3185,
                "distance_pct": 0.47,
                "above_ma5": True,
                "change_pct": 0.6,
            }

        @staticmethod
        def get_index_history(days=10):
            return pd.DataFrame({"close": [3180, 3182, 3182, 3184, 3184, 3185]})

        @staticmethod
        def get_limit_up_pool():
            return [
                {"code": "301001", "sector": "AI", "seal_amount": 1_0000_0000},
                {"code": "301002", "sector": "AI", "seal_amount": 1_1000_0000},
                {"code": "688001", "sector": "Chip", "seal_amount": 9000_0000},
                {"code": "688002", "sector": "Chip", "seal_amount": 8000_0000},
            ]

        @staticmethod
        def get_market_sentiment(zt_pool=None):
            return {
                "temperature": "warm",
                "style_bias": "premium_smallcap",
                "premium_count": 4,
                "total_limit_ups": 8,
                "max_limit_count": 2,
                "dominant_board": "gem",
                "hot_sector_count": 1,
            }

        @staticmethod
        def get_hot_sectors():
            return []

    def test_consecutive_move_helpers_count_full_streak(self):
        engine = RiskEngine(self.FakeFetcher())
        up_history = pd.DataFrame({"close": [1, 2, 3, 4, 5]})
        down_history = pd.DataFrame({"close": [5, 4, 3, 2, 1]})

        self.assertTrue(engine._check_consecutive_up(up_history))
        self.assertTrue(engine._check_consecutive_down(down_history))

    def test_market_state_uses_premium_style_when_theme_is_smallcap(self):
        fetcher = self.FakeFetcher()
        engine = RiskEngine(fetcher)

        state = engine.get_market_state(zt_pool=fetcher.get_limit_up_pool())

        self.assertTrue(state["can_trade"])
        self.assertEqual(state["state"], "有主线震荡")
        self.assertEqual(state["sentiment"]["style_bias"], "premium_smallcap")
        self.assertIn("创业板/科创板", state["suggestion"])


class ChipQualityStrategySentimentTest(unittest.TestCase):
    class FakeFetcher:
        @staticmethod
        def get_limit_up_pool():
            return []

        @staticmethod
        def get_market_sentiment(pool_data=None):
            return {
                "temperature": "hot",
                "style_bias": "premium_smallcap",
                "dominant_board": "gem",
                "premium_count": 6,
                "hot_sector_count": 2,
                "top_sector_count": 4,
                "max_limit_count": 3,
            }

    def setUp(self):
        self.strategy = ChipQualityStrategy(self.FakeFetcher())

    def test_market_sentiment_and_style_scores_reward_gem_leaders(self):
        pool_info = {
            "board_type": "gem",
            "market_sentiment": self.FakeFetcher.get_market_sentiment(),
        }

        sentiment_score, _ = self.strategy._score_market_sentiment(pool_info)
        style_score, _ = self.strategy._score_board_style_fit("301183", pool_info)

        self.assertGreaterEqual(sentiment_score, 6)
        self.assertGreaterEqual(style_score, 5)

    def test_batch_analyze_enriches_pool_info(self):
        captured = {}

        def fake_analyze_stock(code, days=30, pool_info=None):
            captured[code] = pool_info
            return {
                "code": code,
                "name": "",
                "pass_risk_filter": True,
                "total_score": 0,
                "filter_details": {"pass_all": True},
                "score_details": {"total": 0},
                "recommendation": "ok",
            }

        self.strategy.analyze_stock = fake_analyze_stock

        self.strategy.batch_analyze(
            ["301183"],
            pool_data=[
                {
                    "code": "301183",
                    "sector": "AI",
                    "board_type": "gem",
                    "limit_count": 1,
                    "seal_amount": 200_000_000,
                    "first_limit_time": "09:33:00",
                }
            ],
        )

        self.assertEqual(captured["301183"]["sector_zt_count"], 1)
        self.assertEqual(
            captured["301183"]["market_sentiment"]["style_bias"],
            "premium_smallcap",
        )


if __name__ == "__main__":
    unittest.main()
