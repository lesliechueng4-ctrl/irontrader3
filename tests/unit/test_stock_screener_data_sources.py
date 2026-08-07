import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

import stock_screener_2 as screener


def _sina_history(rows=40):
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    close = [10.0 + index for index in range(rows)]
    frame = pd.DataFrame({
        "date": dates,
        "open": [str(value - 0.2) for value in close],
        "high": [str(value + 0.4) for value in close],
        "low": [str(value - 0.5) for value in close],
        "close": [str(value) for value in close],
        "volume": [str(1000 + index) for index in range(rows)],
        "amount": [10000 + index for index in range(rows)],
    })
    return frame.iloc[::-1].reset_index(drop=True)


class StockScreenerDataSourceTest(unittest.TestCase):
    def setUp(self):
        screener.clear_stock_pool_cache()

    def tearDown(self):
        screener.clear_stock_pool_cache()

    def test_history_uses_sina_and_normalizes_for_screening(self):
        raw = _sina_history()
        with patch.object(screener, "_load_shared_history_cache", return_value=None), \
                patch.object(screener.ak, "stock_zh_a_daily", return_value=raw) as sina, \
                patch.object(screener.ak, "stock_zh_a_hist") as eastmoney:
            result = screener.get_stock_history("600519")

        self.assertEqual(len(result), 40)
        self.assertTrue(result["date"].is_monotonic_increasing)
        self.assertTrue(pd.api.types.is_numeric_dtype(result["close"]))
        self.assertIn("pct_change", result.columns)
        expected = (49.0 / 48.0 - 1) * 100
        self.assertAlmostEqual(result.iloc[-1]["pct_change"], expected, places=6)
        self.assertEqual(result.attrs[screener.HISTORY_SOURCE_ATTR], "新浪")
        self.assertEqual(result.attrs[screener.HISTORY_DATE_ATTR], "2026-02-09")
        sina.assert_called_once()
        self.assertEqual(sina.call_args.kwargs["symbol"], "sh600519")
        self.assertEqual(sina.call_args.kwargs["adjust"], "qfq")
        eastmoney.assert_not_called()

    def test_eastmoney_fallback_converts_volume_to_shares(self):
        raw = _sina_history()
        with patch.object(screener, "_load_shared_history_cache", return_value=None), \
                patch.object(screener.ak, "stock_zh_a_daily", side_effect=RuntimeError("down")), \
                patch.object(screener.ak, "stock_zh_a_hist", return_value=raw):
            result = screener.get_stock_history("600519")

        self.assertEqual(
            result.iloc[-1]["volume"], float(raw.iloc[0]["volume"]) * 100
        )
        self.assertEqual(result.attrs["data_source"], "东方财富")

    def test_fresh_batch_cache_avoids_per_stock_network_calls(self):
        cached = _sina_history().rename(columns={"date": "date"})
        cached["pct_chg"] = 1.0
        with patch.object(
            screener,
            "_load_shared_history_cache",
            return_value=cached,
        ), patch.object(
            screener.ak,
            "stock_zh_a_daily",
            side_effect=AssertionError("live Sina should not be called"),
        ), patch.object(
            screener.ak,
            "stock_zh_a_hist",
            side_effect=AssertionError("Eastmoney should not be called"),
        ):
            result = screener.get_stock_history("000001")

        self.assertEqual(len(result), 40)
        self.assertTrue((result["pct_change"] == 1.0).all())

    def test_total_source_outage_raises_instead_of_becoming_no_match(self):
        with patch.object(screener, "_load_shared_history_cache", return_value=None), \
                patch.object(screener.ak, "stock_zh_a_daily", side_effect=RuntimeError("sina down")), \
                patch.object(screener.ak, "stock_zh_a_hist", side_effect=RuntimeError("eastmoney down")):
            with self.assertRaises(screener.HistoryDataSourceError):
                screener.get_stock_history("600519")

    def test_short_history_is_a_normal_skip(self):
        raw = _sina_history(rows=20)
        with patch.object(screener, "_load_shared_history_cache", return_value=None), \
                patch.object(screener.ak, "stock_zh_a_daily", return_value=raw), \
                patch.object(screener.ak, "stock_zh_a_hist", side_effect=RuntimeError("down")):
            self.assertIsNone(screener.get_stock_history("301999"))

    def test_trusted_normalized_cache_uses_fast_path_and_keeps_metadata(self):
        frame = _sina_history().sort_values("date").reset_index(drop=True)
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column])
        frame["pct_chg"] = frame["close"].pct_change() * 100

        with patch.object(
            screener.pd,
            "to_numeric",
            side_effect=AssertionError("trusted cache must not repeat numeric cleaning"),
        ):
            result = screener._normalize_history_frame(
                frame,
                source="sina_batch",
                trusted=True,
            )

        self.assertIn("pct_change", result.columns)
        self.assertEqual(result.attrs[screener.HISTORY_SOURCE_ATTR], "新浪批量行情")
        self.assertEqual(result.attrs[screener.HISTORY_DATE_ATTR], "2026-02-09")
        self.assertTrue(result.attrs[screener.HISTORY_TRUSTED_ATTR])
        self.assertNotIn("pct_change", frame.columns)

    def test_ma_alignment_matches_legacy_result_without_mutating_dataframe(self):
        close = pd.Series(
            [10 + index * 0.05 for index in range(60)],
            dtype=float,
        )
        frame = pd.DataFrame({"close": close})
        legacy = frame.copy()
        for period in screener.CONFIG["ma_periods"]:
            legacy[f"MA{period}"] = legacy["close"].rolling(period).mean()
        last = legacy.iloc[-1]
        expected = {
            f"MA{period}": round(last[f"MA{period}"], 3)
            for period in screener.CONFIG["ma_periods"]
        }

        passed, actual = screener.check_ma_alignment(frame)

        self.assertTrue(passed)
        self.assertEqual(actual, expected)
        self.assertEqual(list(frame.columns), ["close"])

    def test_evaluate_stock_history_runs_volume_before_ma_and_carries_lineage(self):
        frame = _sina_history()
        frame = screener._normalize_history_frame(frame, source="新浪")
        calls = []

        def result(name, value):
            def inner(*_args, **_kwargs):
                calls.append(name)
                return value
            return inner

        with patch.object(screener, "check_price_change", result("price", (True, 1.2))), \
                patch.object(screener, "check_recent_gain", result("recent", (True, 5.0))), \
                patch.object(screener, "check_volume_ratio", result("volume", (True, 1.3))), \
                patch.object(screener, "check_ma_alignment", result("ma", (True, {
                    "MA5": 12.0, "MA10": 11.0, "MA20": 10.0, "MA30": 9.0,
                }))), \
                patch.object(screener, "check_macd_golden_cross", result("macd", (True, {
                    "DIF": 0.3, "DEA": 0.2, "MACD": 0.2, "金叉": True,
                }))), \
                patch.object(screener, "score_stock", result("score", 90)):
            candidate = screener.evaluate_stock_history("689001", "测试股", frame)

        self.assertEqual(calls, ["price", "recent", "volume", "ma", "macd", "score"])
        self.assertEqual(candidate["代码"], "689001")
        self.assertEqual(candidate["数据日期"], "2026-02-09")
        self.assertEqual(candidate["数据源"], "新浪")

    def test_stock_pool_includes_689_and_reuses_same_day_module_cache(self):
        calls = []

        def get_stock_pool(pool, source):
            calls.append((pool, source))
            return [
                SimpleNamespace(code="600000", name="浦发银行"),
                SimpleNamespace(code="689001", name="科创样本"),
                SimpleNamespace(code="900901", name="B股"),
                SimpleNamespace(code="301001", name="创业样本"),
                SimpleNamespace(code="000001", name="平安银行"),
                SimpleNamespace(code="920001", name="北交样本"),
            ]

        fake_backend = SimpleNamespace(get_stock_pool=get_stock_pool)
        with patch.object(screener, "_history_backend", return_value=fake_backend):
            first = screener.get_all_stocks()
            first.loc[0, "name"] = "调用方修改"
            second = screener.get_all_stocks()

        self.assertEqual(calls, [("all_a", "auto")])
        self.assertIn("689001", set(second["code"]))
        self.assertIn("301001", set(second["code"]))
        self.assertNotIn("900901", set(second["code"]))
        self.assertIn("920001", set(second["code"]))
        self.assertNotIn("调用方修改", set(second["name"]))

    def test_prepare_history_cache_reports_single_thread_hint_when_fully_warm(self):
        fake_backend = SimpleNamespace(
            StockInfo=lambda code, name: SimpleNamespace(code=code, name=name),
            ScanConfig=lambda **kwargs: SimpleNamespace(**kwargs),
            prepare_scan_cache=lambda stocks, cfg: {
                "prepared": len(stocks),
                "needs_full_fetch": 0,
            },
        )
        stocks = pd.DataFrame([{"code": "600000", "name": "浦发银行"}])
        with patch.object(screener, "_history_backend", return_value=fake_backend):
            meta = screener.prepare_history_cache(stocks, workers=12)

        self.assertTrue(meta["cache_warm"])
        self.assertEqual(meta["recommended_scan_workers"], 1)

    def test_config_does_not_claim_unsupported_market_cap_filter(self):
        self.assertNotIn("min_market_cap", screener.CONFIG)
        self.assertNotIn("max_market_cap", screener.CONFIG)


if __name__ == "__main__":
    unittest.main()
