import unittest
import time
from unittest.mock import patch

import pandas as pd

from counter_trend_hero import CounterTrendHeroScanner
from low_buy_engine import LowBuyEngine


class ScanCancellationTest(unittest.TestCase):
    def test_lowbuy_honors_cancellation_before_external_requests(self):
        engine = object.__new__(LowBuyEngine)
        with self.assertRaisesRegex(RuntimeError, "已取消"):
            engine.scan_candidates(cancel_check=lambda: True)

    def test_hero_honors_cancellation_before_external_requests(self):
        scanner = object.__new__(CounterTrendHeroScanner)
        with self.assertRaisesRegex(RuntimeError, "已取消"):
            scanner.scan(cancel_check=lambda: True)

    def test_lowbuy_records_near_misses_when_threshold_filters_all(self):
        engine = object.__new__(LowBuyEngine)
        engine.sentiment_analyzer = type("Sentiment", (), {
            "analyze": lambda self: {"phase": "中性", "score": 50}
        })()
        engine._sentiment_cached_at = 0
        engine._cached_sentiment = None
        engine._cached_emotion = None
        engine._emotion_cached_at = 0
        engine.EMOTION_CACHE_TTL = 300

        scored = {
            "600001": {"stock_code": "600001", "stock_name": "甲", "total_score": 54.5, "stock_score": 54.5, "decision": "等待"},
            "600002": {"stock_code": "600002", "stock_name": "乙", "total_score": 49.0, "stock_score": 49.0, "decision": "等待"},
        }
        with patch.object(engine, "_pre_screen", return_value=list(scored)):
            with patch.object(engine, "_preload_shared_data", return_value=None):
                with patch.object(engine, "analyze", side_effect=lambda code: scored[code]):
                    result = engine.scan_candidates(min_score=55)

        self.assertEqual(result, [])
        self.assertEqual(engine._last_scan_meta["reviewed"], 2)
        self.assertEqual(engine._last_scan_meta["top_score"], 54.5)
        self.assertEqual(engine._last_scan_meta["near_misses"][0]["stock_code"], "600001")

    def test_lowbuy_preload_reuses_prescreen_spot_frame(self):
        cached = {}
        engine = object.__new__(LowBuyEngine)
        engine._last_spot_frame = pd.DataFrame({
            "代码": ["600001"],
            "名称": ["甲"],
            "最新价": [10.0],
            "昨收": [10.2],
            "涨跌幅": [-1.0],
            "成交量": [1000],
            "成交额": [30_000_000],
            "最高": [10.5],
            "最低": [9.8],
            "今开": [10.1],
            "换手率": [2.5],
        })
        engine._last_spot_frame_at = time.time()
        engine.fetcher = type("Fetcher", (), {
            "_set_cache": lambda self, key, value: cached.setdefault(key, value),
            "_get_board_type": lambda self, code: "main",
            "_get_limit_up_threshold": lambda self, code: 9.5,
            "_check_limit_up": lambda self, code, change_pct: False,
            "get_stock_history": lambda self, code, days=120: [],
        })()

        engine._preload_shared_data(["600001"])

        self.assertIn("stock_realtime_600001", cached)
        self.assertEqual(cached["stock_realtime_600001"]["name"], "甲")


if __name__ == "__main__":
    unittest.main()
