import unittest

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


if __name__ == "__main__":
    unittest.main()
