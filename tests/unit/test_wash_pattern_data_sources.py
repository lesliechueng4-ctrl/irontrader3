import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import wash_pattern_scanner as scanner
import wash_pattern_optimizer as optimizer


def history_frame(rows=90, end="2026-08-05"):
    dates = pd.bdate_range(end=end, periods=rows)
    values = pd.Series(range(rows), dtype=float)
    return pd.DataFrame({
        "date": dates,
        "open": 10.0 + values * 0.01,
        "high": 10.3 + values * 0.01,
        "low": 9.8 + values * 0.01,
        "close": 10.1 + values * 0.01,
        "volume": 1_000_000 + values * 1_000,
    })


class WashPatternDataSourceTest(unittest.TestCase):
    def test_full_a_scan_does_not_use_lossy_prescreen_by_default(self):
        cfg = scanner.ScanConfig(stock_pool="all_a")
        expected = [scanner.StockInfo("002021", "中捷资源")]

        with patch.object(scanner, "get_stock_pool", return_value=expected) as pool, \
                patch.object(
                    optimizer,
                    "pre_screen_wash_candidates",
                    side_effect=AssertionError("lossy prefilter must stay disabled"),
                ):
            result = scanner.resolve_scan_stocks(cfg)

        self.assertEqual(result, expected)
        pool.assert_called_once_with("all_a", "auto")

    def test_lossy_optimizer_requires_explicit_opt_in(self):
        with patch("builtins.print"):
            self.assertEqual(optimizer.pre_screen_wash_candidates(), [])

    def test_sina_symbol_supports_all_a_share_boards(self):
        self.assertEqual(scanner.sina_daily_symbol("000001"), "sz000001")
        self.assertEqual(scanner.sina_daily_symbol("600519"), "sh600519")
        self.assertEqual(scanner.sina_daily_symbol("688306"), "sh688306")
        self.assertEqual(scanner.sina_daily_symbol("920017"), "bj920017")

    def test_fetch_daily_sina_normalizes_history(self):
        raw = history_frame()
        cfg = scanner.ScanConfig(as_of_date="2026-08-06")

        with patch.object(scanner.ak, "stock_zh_a_daily", return_value=raw) as fetch:
            result = scanner.fetch_daily_sina("600519", cfg)

        self.assertEqual(len(result), 90)
        self.assertIn("ma20", result.columns)
        self.assertEqual(result.iloc[-1]["volume"], raw.iloc[-1]["volume"])
        fetch.assert_called_once_with(
            symbol="sh600519",
            start_date="20260118",
            end_date="20260806",
            adjust="qfq",
        )

    def test_eastmoney_history_volume_is_converted_from_lots_to_shares(self):
        raw = history_frame()
        cfg = scanner.ScanConfig(as_of_date="2026-08-06")

        with patch.object(scanner.ak, "stock_zh_a_hist", return_value=raw):
            result = scanner.fetch_daily_akshare("600519", cfg)

        self.assertEqual(
            result.iloc[-1]["volume"], raw.iloc[-1]["volume"] * 100
        )

    def test_mixed_legacy_cache_converts_only_eastmoney_rows(self):
        frame = scanner.add_ma(history_frame(rows=70, end="2026-08-06"))
        frame["成交额"] = 1_000_000.0
        quote_row = frame.iloc[-1].copy()
        quote_row["date"] = pd.Timestamp("2026-08-07")
        quote_row["volume"] = 25_000_000.0
        quote_row["成交额"] = float("nan")
        mixed = pd.concat(
            [frame, pd.DataFrame([quote_row])], ignore_index=True
        )

        normalized = scanner.wash_cache_frame_in_shares({
            "source": "sina_batch",
            "data": mixed,
        })

        self.assertEqual(
            normalized.iloc[-2]["volume"], frame.iloc[-1]["volume"] * 100
        )
        self.assertEqual(normalized.iloc[-1]["volume"], 25_000_000.0)

    def test_intraday_completed_view_excludes_partial_current_bar(self):
        frame = scanner.add_ma(history_frame(rows=90, end="2026-08-07"))
        cfg = scanner.ScanConfig()

        result = scanner.completed_history_view(
            frame, cfg, now=datetime(2026, 8, 7, 10, 5)
        )

        self.assertEqual(result.iloc[-1]["date"].strftime("%Y-%m-%d"), "2026-08-06")
        self.assertTrue(result.attrs["provisional_bar_excluded"])

    def test_auto_source_prefers_sina_and_records_source(self):
        frame = scanner.add_ma(history_frame())
        cfg = scanner.ScanConfig(as_of_date="2026-08-06", data_source="auto")

        with patch.object(scanner, "load_wash_ohlcv_cache", return_value=None), \
                patch.object(scanner, "fetch_daily_sina", return_value=frame), \
                patch.object(scanner, "fetch_daily_akshare", side_effect=AssertionError), \
                patch.object(scanner, "fetch_daily_yahoo", side_effect=AssertionError), \
                patch.object(scanner, "save_wash_ohlcv_cache") as save:
            result = scanner.fetch_daily("600519", cfg)

        pd.testing.assert_frame_equal(result, frame)
        self.assertEqual(result.attrs["data_source"], "sina")
        save.assert_called_once()
        args, kwargs = save.call_args
        self.assertEqual(args[:2], ("600519", cfg))
        pd.testing.assert_frame_equal(args[2], result)
        self.assertEqual(kwargs, {"source": "sina"})

    def test_live_failure_uses_recent_complete_wash_cache(self):
        frame = scanner.add_ma(history_frame())
        cfg = scanner.ScanConfig(as_of_date="2026-08-06", data_source="auto")

        with patch.object(scanner, "load_wash_ohlcv_cache", return_value=None), \
                patch.object(scanner, "fetch_daily_sina", side_effect=RuntimeError("down")), \
                patch.object(scanner, "fetch_daily_akshare", side_effect=RuntimeError("down")), \
                patch.object(scanner, "fetch_daily_yahoo", side_effect=RuntimeError("down")), \
                patch.object(scanner, "load_recent_wash_ohlcv_cache", return_value=frame), \
                patch.object(scanner, "fetch_daily_cache", side_effect=AssertionError):
            result = scanner.fetch_daily("600519", cfg)

        self.assertIs(result, frame)

    def test_all_sources_failure_raises_typed_data_error(self):
        cfg = scanner.ScanConfig(as_of_date="2026-08-06", data_source="auto")

        with patch.object(scanner, "load_wash_ohlcv_cache", return_value=None), \
                patch.object(scanner, "fetch_daily_sina", side_effect=RuntimeError("down")), \
                patch.object(scanner, "fetch_daily_akshare", side_effect=RuntimeError("down")), \
                patch.object(scanner, "fetch_daily_yahoo", side_effect=RuntimeError("down")), \
                patch.object(scanner, "load_recent_wash_ohlcv_cache", return_value=None), \
                patch.object(scanner, "fetch_daily_cache", return_value=None):
            with self.assertRaises(scanner.DailyDataSourceError) as raised:
                scanner.scan_stock(
                    scanner.StockInfo("600519", "贵州茅台"),
                    cfg,
                    datetime(2026, 8, 6),
                )

        self.assertEqual(raised.exception.code, "600519")
        self.assertIn("sina=", str(raised.exception))

    def test_short_live_history_is_normal_non_match(self):
        short = scanner.add_ma(history_frame(rows=30))
        cfg = scanner.ScanConfig(as_of_date="2026-08-06", data_source="auto")

        with patch.object(scanner, "load_wash_ohlcv_cache", return_value=None), \
                patch.object(scanner, "fetch_daily_sina", return_value=short), \
                patch.object(scanner, "fetch_daily_akshare", return_value=None), \
                patch.object(scanner, "fetch_daily_yahoo", return_value=None), \
                patch.object(scanner, "load_recent_wash_ohlcv_cache", return_value=None), \
                patch.object(scanner, "fetch_daily_cache", return_value=None):
            result = scanner.scan_stock(
                scanner.StockInfo("001234", "新股"),
                cfg,
                datetime(2026, 8, 6),
            )

        self.assertEqual(result, [])

    def test_cache_freshness_is_intraday_aware(self):
        cfg = scanner.ScanConfig()
        intraday_payload = {
            "as_of": "2026-08-07",
            "saved_at": datetime(2026, 8, 7, 12, 58).timestamp(),
        }
        preclose_payload = {
            "as_of": "2026-08-07",
            "saved_at": datetime(2026, 8, 7, 14, 59).timestamp(),
        }
        closed_payload = {
            "as_of": "2026-08-07",
            "saved_at": datetime(2026, 8, 7, 15, 1).timestamp(),
        }

        self.assertTrue(scanner.wash_cache_payload_is_fresh(
            intraday_payload, cfg, datetime(2026, 8, 7, 13, 1)
        ))
        self.assertFalse(scanner.wash_cache_payload_is_fresh(
            intraday_payload, cfg, datetime(2026, 8, 7, 13, 10)
        ))
        self.assertFalse(scanner.wash_cache_payload_is_fresh(
            preclose_payload, cfg, datetime(2026, 8, 7, 15, 2)
        ))
        self.assertTrue(scanner.wash_cache_payload_is_fresh(
            closed_payload, cfg, datetime(2026, 8, 7, 15, 2)
        ))

    def test_cache_save_is_atomic_and_records_latest_bar_date(self):
        cfg = scanner.ScanConfig(as_of_date="2026-08-06")
        frame = scanner.add_ma(history_frame(end="2026-08-05"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            with patch.object(scanner, "wash_ohlcv_cache_dir", return_value=cache_dir):
                scanner.save_wash_ohlcv_cache("600519", cfg, frame, source="sina")
            payload = pd.read_pickle(cache_dir / "600519.pkl")
            leftovers = list(cache_dir.glob("*.tmp"))

        self.assertEqual(payload["latest_bar_date"], "2026-08-05")
        self.assertEqual(payload["source"], "sina")
        self.assertEqual(leftovers, [])

    def test_results_include_real_latest_bar_date(self):
        frame = scanner.add_ma(history_frame(end="2026-08-05"))
        hit = scanner.PatternHit(
            end_index=len(frame) - 1,
            start_index=len(frame) - 5,
            pattern_type="A",
            drawdown_pct=2.0,
        )
        cfg = scanner.ScanConfig(recent_days=30)

        with patch.object(scanner, "detect_wash_pattern", return_value=[hit]):
            rows = scanner.build_result_rows(
                scanner.StockInfo("600519", "贵州茅台"),
                frame,
                cfg,
                datetime(2026, 8, 6),
            )

        self.assertEqual(rows[0]["最新行情日"], "2026-08-05")

    def test_recent_cache_rejects_stale_or_short_history(self):
        cfg = scanner.ScanConfig(as_of_date="2026-08-06", cache_max_stale_days=10)
        cases = (
            history_frame(rows=90, end="2026-06-30"),
            history_frame(rows=30, end="2026-08-05"),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            with patch.object(scanner, "wash_ohlcv_cache_dir", return_value=cache_dir):
                for frame in cases:
                    pd.to_pickle({
                        "adjust": "qfq",
                        "as_of": "2026-08-05",
                        "saved_at": time.time(),
                        "data": scanner.add_ma(frame),
                    }, cache_dir / "600519.pkl")
                    self.assertIsNone(
                        scanner.load_recent_wash_ohlcv_cache("600519", cfg)
                    )

    def test_legacy_cache_skips_stale_long_file_for_recent_complete_file(self):
        cfg = scanner.ScanConfig(as_of_date="2026-08-06", cache_max_stale_days=10)
        stale = history_frame(rows=120, end="2026-06-30")
        recent = history_frame(rows=90, end="2026-08-05")

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            pd.to_pickle(stale, cache_dir / "20260630_stock_history_600519_120.pkl")
            pd.to_pickle(recent, cache_dir / "20260805_stock_history_600519_90.pkl")
            with patch.object(scanner, "candidate_cache_dirs", return_value=[cache_dir]):
                result = scanner.fetch_daily_cache("600519", cfg)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 90)
        self.assertEqual(result.iloc[-1]["date"].strftime("%Y-%m-%d"), "2026-08-05")

    def test_merge_sina_quote_appends_only_without_trading_day_gap(self):
        cfg = scanner.ScanConfig(cache_max_stale_days=90)
        frame = scanner.add_ma(history_frame(rows=90, end="2026-08-06"))
        previous_close = float(frame.iloc[-1]["close"])
        quote = {
            "date": pd.Timestamp("2026-08-07").date(),
            "open": previous_close + 0.01,
            "close": previous_close + 0.05,
            "high": previous_close + 0.10,
            "low": previous_close - 0.05,
            "volume": 2_000_000,
            "previous_close": previous_close,
        }

        merged = scanner.merge_sina_quote_history(
            frame, quote, cfg, pd.Timestamp("2026-08-06").date()
        )
        rejected = scanner.merge_sina_quote_history(
            frame, quote, cfg, pd.Timestamp("2026-08-05").date()
        )

        self.assertIsNotNone(merged)
        self.assertEqual(len(merged), 91)
        self.assertEqual(merged.iloc[-1]["date"].strftime("%Y-%m-%d"), "2026-08-07")
        self.assertIsNone(rejected)

    def test_prepare_scan_cache_bulk_updates_only_contiguous_histories(self):
        cfg = scanner.ScanConfig(workers=2, cache_max_stale_days=90)
        stocks = [
            scanner.StockInfo("600519", "贵州茅台"),
            scanner.StockInfo("000001", "平安银行"),
        ]
        current = scanner.add_ma(history_frame(rows=90, end="2026-08-06"))
        gapped = scanner.add_ma(history_frame(rows=90, end="2026-08-05"))

        def quote_for(frame):
            previous_close = float(frame.iloc[-1]["close"])
            return {
                "date": pd.Timestamp("2026-08-07").date(),
                "open": previous_close,
                "close": previous_close + 0.03,
                "high": previous_close + 0.06,
                "low": previous_close - 0.02,
                "volume": 2_000_000,
                "previous_close": previous_close,
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            for code, frame in (("600519", current), ("000001", gapped)):
                pd.to_pickle({
                    "adjust": "qfq",
                    "as_of": "2026-08-06",
                    "saved_at": time.time(),
                    "source": "sina",
                    "data": frame,
                }, cache_dir / f"{code}.pkl")

            quotes = {
                "600519": quote_for(current),
                "000001": quote_for(gapped),
            }
            with patch.object(scanner, "wash_ohlcv_cache_dir", return_value=cache_dir), \
                    patch.object(scanner, "fetch_sina_quote_snapshot", return_value=quotes), \
                    patch.object(scanner, "trade_dates_through", return_value=[
                        pd.Timestamp("2026-08-05").date(),
                        pd.Timestamp("2026-08-06").date(),
                        pd.Timestamp("2026-08-07").date(),
                    ]):
                meta = scanner.prepare_scan_cache(stocks, cfg)
                payload = pd.read_pickle(cache_dir / "600519.pkl")

        self.assertTrue(meta["enabled"])
        self.assertEqual(meta["prepared"], 1)
        self.assertEqual(meta["needs_full_fetch"], 1)
        self.assertEqual(payload["source"], "sina_batch")
        self.assertEqual(
            payload["data"].iloc[-1]["date"].strftime("%Y-%m-%d"),
            "2026-08-07",
        )

    def test_prepare_scan_cache_refuses_merge_without_trade_calendar(self):
        cfg = scanner.ScanConfig(workers=1)
        stock = scanner.StockInfo("600519", "贵州茅台")
        with patch.object(
            scanner,
            "fetch_sina_quote_snapshot",
            return_value={"600519": {"date": pd.Timestamp("2026-08-07").date()}},
        ), patch.object(scanner, "trade_dates_through", return_value=[]), \
                patch.object(scanner, "save_wash_ohlcv_cache") as save:
            meta = scanner.prepare_scan_cache([stock], cfg)

        self.assertEqual(meta["needs_full_fetch"], 1)
        self.assertIn("calendar_error", meta)
        save.assert_not_called()

    def test_unchanged_quote_validates_previous_day_payload_for_current_scan(self):
        cfg = scanner.ScanConfig(workers=1)
        fixed_now = datetime(2026, 8, 8, 10, 0)
        frame = scanner.add_ma(history_frame(end="2026-08-07"))
        last = frame.iloc[-1]
        quote_date = pd.Timestamp("2026-08-07").date()
        quote = {
            "date": quote_date,
            "open": float(last["open"]),
            "close": float(last["close"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "volume": float(last["volume"]),
            "previous_close": float(frame.iloc[-2]["close"]),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            pd.to_pickle({
                "code": "600518",
                "as_of": "2026-08-07",
                "adjust": "qfq",
                "saved_at": time.time() - 6 * 60 * 60,
                "source": "sina_batch",
                "latest_bar_date": "2026-08-07",
                "data": frame,
            }, cache_dir / "600518.pkl")

            with patch.object(scanner, "wash_ohlcv_cache_dir", return_value=cache_dir), \
                    patch.object(scanner, "current_local_datetime", return_value=fixed_now), \
                    patch.object(scanner, "parse_as_of_date", return_value=fixed_now), \
                    patch.object(scanner, "trade_dates_through", return_value=[
                        pd.Timestamp("2026-08-06").date(), quote_date,
                    ]), \
                    patch.object(scanner, "expected_latest_quote_date", return_value=quote_date), \
                    patch.object(
                        scanner,
                        "fetch_sina_quote_snapshot",
                        return_value={"600518": quote},
                    ):
                meta = scanner.prepare_scan_cache(
                    [scanner.StockInfo("600518", "康美药业")], cfg
                )
                loaded = scanner.load_wash_ohlcv_cache("600518", cfg)

        self.assertEqual(meta["reused"], 1)
        self.assertEqual(meta["needs_full_fetch"], 0)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded), len(frame))


if __name__ == "__main__":
    unittest.main()
