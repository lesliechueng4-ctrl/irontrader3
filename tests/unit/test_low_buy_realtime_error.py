"""Low-buy analysis must fail closed when realtime stock data is unavailable."""

import unittest

from low_buy_engine import LowBuyEngine


class _FailingRealtimeFetcher:
    def _normalize_code(self, code):
        return str(code).zfill(6)

    def get_stock_realtime(self, code):
        return {"code": code, "name": "未知", "error": "所有数据源均不可用"}

    def get_data_source_health(self):
        return {"sina": {"status": "degraded"}}


class _HealthyRealtimeFetcher(_FailingRealtimeFetcher):
    def get_stock_realtime(self, code):
        return {"code": code, "name": "测试股票", "price": 10.0}


class _MustNotRun:
    def __getattr__(self, name):
        raise AssertionError(f"downstream analyzer must not run: {name}")


class LowBuyRealtimeErrorTest(unittest.TestCase):
    def test_realtime_error_returns_structured_data_error_immediately(self):
        engine = object.__new__(LowBuyEngine)
        engine.fetcher = _FailingRealtimeFetcher()
        sentinel = _MustNotRun()
        engine.sentiment_analyzer = sentinel
        engine.sector_scorer = sentinel
        engine.fund_analyzer = sentinel
        engine.technical_scorer = sentinel
        engine.fundamental_scorer = sentinel

        result = engine.analyze("1")

        self.assertEqual(result["stock_code"], "000001")
        self.assertEqual(result["decision"], "回避")
        self.assertTrue(result["data_error"])
        self.assertEqual(result["error_code"], "REALTIME_DATA_ERROR")
        self.assertIn("所有数据源均不可用", result["error"])
        self.assertEqual(result["dimensions"], {})
        self.assertIsNone(result["emotion_gate"])

    def test_explicit_emotion_snapshot_is_used_without_engine_cache(self):
        engine = object.__new__(LowBuyEngine)
        engine.fetcher = _HealthyRealtimeFetcher()
        engine._get_sentiment = lambda: {"score": 80, "phase": "高潮", "details": {}}
        engine.sector_scorer = type("Sector", (), {"score_sector": lambda *_: {"score": 80}})()
        engine.fund_analyzer = type("Fund", (), {"analyze": lambda *_: {"score": 80}})()
        engine.technical_scorer = type("Technical", (), {"score": lambda *_: {"score": 80}})()
        engine.fundamental_scorer = type("Fundamental", (), {"score": lambda *_: {"score": 80}})()
        engine.INTENDED_SINGLE = {"低吸": 0.20, "观察": 0.10}
        engine._get_emotion = lambda: self.fail("engine emotion cache must not be read")

        result = engine.analyze("1", emotion_snapshot={"score": 20})

        self.assertEqual(result["emotion_gate"]["emotion_score"], 20)
        self.assertFalse(result["emotion_gate"]["can_open"])
        self.assertEqual(result["decision"], "回避")


if __name__ == "__main__":
    unittest.main()


def test_position_check_blocks_limit_up_and_far_from_support():
    from low_buy_engine import LowBuyEngine

    check = LowBuyEngine._position_check
    assert check({'current': 20.45, 'change_pct': 10.0, 'is_limit_up': True}, {'support_level': 14.75})['ok'] is False
    far = check({'current': 16.0, 'change_pct': 1.0}, {'support_level': 14.75})
    assert far['ok'] is False and far['dist_support_pct'] > 5 and '支撑' in far['reason']
    assert check({'current': 15.0, 'change_pct': -1.2}, {'support_level': 14.75})['ok'] is True
    # 没有支撑数据时不因位置否决
    assert check({'current': 15.0, 'change_pct': 0.5}, {})['ok'] is True
