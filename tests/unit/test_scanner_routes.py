import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from flask import Flask

import scanner_routes


class ScannerRoutesTest(unittest.TestCase):
    def setUp(self):
        with scanner_routes._SCAN_JOBS_LOCK:
            scanner_routes._SCAN_JOBS.clear()
        app = Flask(__name__)
        app.register_blueprint(scanner_routes.scanner_bp)
        self.client = app.test_client()

    def test_scanner_output_path_defaults_to_outputs_scanners(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(scanner_routes, "BASE_DIR", Path(tmpdir)):
                with patch.dict("os.environ", {}, clear=True):
                    output = scanner_routes._scanner_output_path("wash_pattern_results")

        self.assertEqual(output.parent, Path(tmpdir) / "outputs" / "scanners")
        self.assertTrue(output.name.startswith("wash_pattern_results_"))
        self.assertEqual(output.suffix, ".csv")

    def test_scanner_output_path_can_be_overridden_by_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "custom_scanner_results"
            with patch.dict("os.environ", {"SCANNER_OUTPUT_DIR": str(output_dir)}):
                output = scanner_routes._scanner_output_path("wash_pattern_results")

        self.assertEqual(output.parent, output_dir)

    def test_wash_pattern_route_returns_table_json(self):
        class FakeWashScanner:
            class ScanConfig:
                def __init__(self, **kwargs):
                    self.__dict__.update(kwargs)

            @staticmethod
            def scan(cfg, show_progress=False):
                self.assertFalse(show_progress)
                self.assertEqual(cfg.scan_mode, "both")
                return pd.DataFrame([
                    {
                        "代码": "600000",
                        "名称": "浦发银行",
                        "状态": "候选预警",
                    }
                ])

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(scanner_routes, "BASE_DIR", Path(tmpdir)):
                with patch.object(scanner_routes, "_load_external_module", return_value=FakeWashScanner):
                    response = self.client.get("/api/scanners/wash-pattern?max_stocks=1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["data"][0]["代码"], "600000")
        self.assertEqual(payload["meta"]["mode"], "both")

    def test_wash_pattern_route_bulk_prepares_cache_before_scanning(self):
        prepared = []

        class FakeWashScanner:
            pd = pd
            RESULT_COLUMNS = ["代码", "名称"]

            class ScanConfig:
                def __init__(self, **kwargs):
                    self.__dict__.update(kwargs)

            @staticmethod
            def get_stock_pool(pool, source):
                raise AssertionError("resolve_scan_stocks should be preferred")

            @staticmethod
            def resolve_scan_stocks(cfg):
                return [type("Stock", (), {"code": "600000", "name": "浦发银行"})()]

            @staticmethod
            def parse_as_of_date(cfg):
                return None

            @staticmethod
            def prepare_scan_cache(stocks, cfg):
                prepared.extend(stock.code for stock in stocks)
                return {
                    "enabled": True,
                    "quotes": 1,
                    "prepared": 1,
                    "needs_full_fetch": 0,
                    "elapsed_sec": 0.1,
                }

            @staticmethod
            def scan_stock(stock, cfg, today):
                return [{"代码": stock.code, "名称": stock.name}]

            @staticmethod
            def sort_wash_results(frame):
                return frame

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(scanner_routes, "BASE_DIR", Path(tmpdir)), \
                    patch.object(scanner_routes, "_load_external_module", return_value=FakeWashScanner):
                response = self.client.get("/api/scanners/wash-pattern?max_stocks=1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(prepared, ["600000"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["meta"]["data_prepare"]["prepared"], 1)

    def test_local_stock_screener_route_returns_normalized_json(self):
        class FakeLocalScreener:
            CONFIG = {"recent_days": 20, "top_n": 10, "output_file": ""}

            @staticmethod
            def run_screener():
                return pd.DataFrame([
                    {
                        "代码": "600000",
                        "名称": "浦发银行",
                        "现价": 10.5,
                        "今日涨幅%": 1.2,
                        "近20日涨幅%": 3.4,
                        "量比": 1.1,
                        "MA5": 10.1,
                        "MA10": 10.0,
                        "MA20": 9.8,
                        "MA30": 9.6,
                        "DIF": 0.2,
                        "DEA": 0.1,
                        "MACD": 0.2,
                        "近期金叉": "是",
                        "综合评分": 88,
                    }
                ])

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(scanner_routes, "BASE_DIR", Path(tmpdir)):
                with patch.object(scanner_routes, "_load_external_module", return_value=FakeLocalScreener):
                    response = self.client.get("/api/scanners/limit-down-rebound?max_stocks=0")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["meta"]["schema"], "local_stock_screener")
        self.assertEqual(payload["data"][0]["代码"], "600000")
        self.assertEqual(payload["data"][0]["股票代码"], "600000")
        self.assertEqual(payload["data"][0]["策略组"], "A股条件筛选")

    def test_local_stock_screener_parallel_updates_progress(self):
        prepared = []

        class FakeLocalScreener:
            CONFIG = {"recent_days": 20, "top_n": 10, "output_file": ""}

            @staticmethod
            def run_screener():
                raise AssertionError("parallel path should not call run_screener")

            @staticmethod
            def get_all_stocks():
                return pd.DataFrame([
                    {"code": "600000", "name": "浦发银行"},
                    {"code": "000001", "name": "平安银行"},
                ])

            @staticmethod
            def prepare_history_cache(stocks, workers=1):
                prepared.extend(stocks["code"].tolist())
                return {
                    "enabled": True,
                    "prepared": len(stocks),
                    "needs_full_fetch": 0,
                }

            @staticmethod
            def get_stock_history(code):
                frame = pd.DataFrame([
                    {"date": "2026-08-06", "close": 10.0},
                    {"date": "2026-08-07", "close": 10.8},
                ])
                frame.attrs["data_source"] = "新浪批量行情"
                return frame

            @staticmethod
            def check_price_change(df):
                return True, 1.2

            @staticmethod
            def check_recent_gain(df):
                return True, 3.4

            @staticmethod
            def check_ma_alignment(df):
                return True, {"MA5": 10.6, "MA10": 10.4, "MA20": 10.2, "MA30": 10.0}

            @staticmethod
            def check_macd_golden_cross(df):
                return True, {"DIF": 0.2, "DEA": 0.1, "MACD": 0.2, "金叉": True}

            @staticmethod
            def check_volume_ratio(df):
                return True, 1.3

            @staticmethod
            def score_stock(ma_data, macd_data, vol_ratio, pct_change, recent_gain):
                return 88

        progress_updates = []
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "parallel.csv"
            records, meta = scanner_routes._run_local_stock_screener(
                FakeLocalScreener,
                max_stocks=0,
                output_path=output_path,
                threads=2,
                progress_callback=lambda **updates: progress_updates.append(updates),
            )
            # The helper no longer publishes a CSV before the outer coverage
            # gate has validated the scan.
            self.assertFalse(output_path.exists())

        self.assertEqual(len(records), 2)
        self.assertEqual(meta["scanned"], 2)
        self.assertEqual(meta["errors"], 0)
        self.assertEqual(meta["total_matches"], 2)
        self.assertEqual(meta["returned_count"], 2)
        self.assertEqual(meta["result_limit"], 0)
        self.assertEqual(meta["legacy_top_n"], 10)
        self.assertEqual(meta["latest_data_date"], "2026-08-07")
        self.assertEqual(meta["data_prepare"]["prepared"], 2)
        self.assertEqual(prepared, ["600000", "000001"])
        self.assertEqual(records[0]["策略组"], "A股条件筛选")
        self.assertEqual(records[0]["数据日期"], "2026-08-07")
        self.assertEqual(records[0]["数据源"], "新浪批量行情")
        self.assertEqual(progress_updates[-1]["done"], 2)
        self.assertEqual(progress_updates[-1]["total"], 2)
        self.assertEqual(progress_updates[-1]["matched"], 2)

    def test_local_stock_screener_counts_history_source_errors(self):
        class FakeLocalScreener:
            CONFIG = {"recent_days": 20, "top_n": 10, "output_file": ""}

            class HistoryDataSourceError(RuntimeError):
                pass

            @staticmethod
            def run_screener():
                raise AssertionError("parallel path should not call run_screener")

            @staticmethod
            def get_all_stocks():
                return pd.DataFrame([{"code": "600000", "name": "浦发银行"}])

            @staticmethod
            def get_stock_history(code):
                raise FakeLocalScreener.HistoryDataSourceError(
                    "all history sources are down"
                )

            @staticmethod
            def check_price_change(df):
                raise AssertionError

            check_recent_gain = check_price_change
            check_ma_alignment = check_price_change
            check_macd_golden_cross = check_price_change
            check_volume_ratio = check_price_change
            score_stock = check_price_change

        progress_updates = []
        with tempfile.TemporaryDirectory() as tmpdir:
            records, meta = scanner_routes._run_local_stock_screener(
                FakeLocalScreener,
                max_stocks=0,
                output_path=Path(tmpdir) / "outage.csv",
                threads=1,
                progress_callback=lambda **updates: progress_updates.append(updates),
            )

        self.assertEqual(records, [])
        self.assertEqual(meta["scanned"], 1)
        self.assertEqual(meta["errors"], 1)
        self.assertEqual(meta["data_errors"], 1)
        self.assertEqual(meta["logic_errors"], 0)
        self.assertEqual(progress_updates[-1]["errors"], 1)

    def test_limit_down_rebound_rejects_mass_history_outage(self):
        class FakeLocalScreener:
            CONFIG = {"recent_days": 20}

            @staticmethod
            def run_screener():
                return None

        with tempfile.TemporaryDirectory() as tmpdir, \
                patch.object(scanner_routes, "BASE_DIR", Path(tmpdir)), \
                patch.object(scanner_routes, "_load_external_module", return_value=FakeLocalScreener), \
                patch.object(
                    scanner_routes,
                    "_run_local_stock_screener",
                    return_value=([], {"scanned": 5, "errors": 4}),
                ):
            with self.assertRaisesRegex(RuntimeError, "历史行情有效覆盖率过低"):
                scanner_routes._run_limit_down_rebound_scan(
                    threads=2,
                    max_stocks=0,
                )

    def test_explicit_zero_valid_data_is_not_treated_as_full_coverage(self):
        class FakeLocalScreener:
            CONFIG = {"recent_days": 20}

            @staticmethod
            def run_screener():
                return None

        with tempfile.TemporaryDirectory() as tmpdir, \
                patch.object(scanner_routes, "BASE_DIR", Path(tmpdir)), \
                patch.object(scanner_routes, "_load_external_module", return_value=FakeLocalScreener), \
                patch.object(
                    scanner_routes,
                    "_run_local_stock_screener",
                    return_value=(
                        [{"代码": "600000"}],
                        {"scanned": 5, "errors": 0, "valid_data": 0, "no_data": 5},
                    ),
                ):
            with self.assertRaisesRegex(RuntimeError, "有效覆盖率过低"):
                scanner_routes._run_limit_down_rebound_scan(
                    threads=2,
                    max_stocks=5,
                )
            self.assertEqual(list(Path(tmpdir).rglob("*.csv")), [])

    def test_valid_scan_publishes_csv_only_after_coverage_gate(self):
        class FakeLocalScreener:
            CONFIG = {"recent_days": 20}

            @staticmethod
            def run_screener():
                return None

        records = [{"代码": "600000", "名称": "浦发银行"}]
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch.object(scanner_routes, "BASE_DIR", Path(tmpdir)), \
                patch.object(scanner_routes, "_load_external_module", return_value=FakeLocalScreener), \
                patch.object(
                    scanner_routes,
                    "_run_local_stock_screener",
                    return_value=(records, {"scanned": 5, "errors": 0, "valid_data": 5}),
                ):
            result = scanner_routes._run_limit_down_rebound_scan(
                threads=2,
                max_stocks=5,
            )
            written = Path(result["output"])
            self.assertTrue(written.exists())
            self.assertEqual(
                pd.read_csv(written, dtype=str)["代码"].iloc[0], "600000"
            )

    def test_local_stock_screener_rejects_empty_pool(self):
        class FakeLocalScreener:
            CONFIG = {"recent_days": 20, "output_file": ""}

            @staticmethod
            def run_screener():
                raise AssertionError

            @staticmethod
            def get_all_stocks():
                return pd.DataFrame(columns=["code", "name"])

            get_stock_history = check_price_change = check_recent_gain = staticmethod(lambda *_: None)
            check_ma_alignment = check_macd_golden_cross = check_volume_ratio = check_price_change
            score_stock = check_price_change

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(RuntimeError, "股票池为空"):
                scanner_routes._run_local_stock_screener(
                    FakeLocalScreener,
                    max_stocks=0,
                    output_path=Path(tmpdir) / "empty.csv",
                )

    def test_cancel_requested_at_completion_boundary_wins_race(self):
        job = scanner_routes._create_scan_job(
            "wash_pattern", cancel_supported=True
        )
        lock = scanner_routes._EXTERNAL_SCAN_LOCKS["wash_pattern"]
        self.assertTrue(lock.acquire(blocking=False))

        def finish_after_cancel(*_args, **_kwargs):
            scanner_routes._request_scan_cancel(job["id"])
            return {"success": True, "count": 1, "meta": {"scanned": 1}}

        with patch.object(
            scanner_routes, "_run_wash_pattern_scan", side_effect=finish_after_cancel
        ):
            scanner_routes._run_wash_pattern_job(job["id"], {"mode": "both"})

        final = scanner_routes._get_scan_job(job["id"])
        self.assertEqual(final["status"], "cancelled")
        self.assertTrue(final["cancel_requested"])

    def test_breakout_does_not_adopt_different_wash_mode_job(self):
        active = scanner_routes._create_scan_job(
            "wash_pattern",
            params={"mode": "both"},
            cancel_supported=True,
        )
        lock = scanner_routes._EXTERNAL_SCAN_LOCKS["wash_pattern"]
        self.assertTrue(lock.acquire(blocking=False))
        try:
            response = self.client.post(
                "/api/scanners/wash-pattern/start?mode=breakout_base"
            )
        finally:
            lock.release()
            scanner_routes._update_scan_job(
                active["id"], status="failed", finished_at=time.time()
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(payload["job_id"])
        self.assertIsNone(payload["job"])

    def test_limit_down_rebound_background_job_reports_completion(self):
        def fake_scan(**kwargs):
            kwargs["progress_callback"](
                phase="筛选中",
                message="已处理 1/1 只，命中 1 条",
                done=1,
                total=1,
                matched=1,
                errors=0,
            )
            return {
                "success": True,
                "data": [{"代码": "600000", "名称": "浦发银行"}],
                "count": 1,
                "elapsed_sec": 0.1,
                "output": "",
                "meta": {
                    "schema": "local_stock_screener",
                    "scanned": 1,
                    "errors": 0,
                    "threads": kwargs["threads"],
                },
            }

        with patch.object(scanner_routes, "_run_limit_down_rebound_scan", side_effect=fake_scan):
            response = self.client.post("/api/scanners/limit-down-rebound/start?threads=2&max_stocks=1")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["success"])
            job_id = payload["job_id"]

            job = None
            for _ in range(20):
                status_response = self.client.get(f"/api/scanners/jobs/{job_id}")
                self.assertEqual(status_response.status_code, 200)
                job = status_response.get_json()["job"]
                if job["status"] == "completed":
                    break
                time.sleep(0.05)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["percent"], 100)
        self.assertEqual(job["matched"], 1)
        self.assertEqual(job["result"]["count"], 1)

    def test_wash_pattern_background_job_reports_completion(self):
        def fake_scan(params, progress_callback=None, cancel_check=None):
            self.assertEqual(params["mode"], "both")
            self.assertEqual(params["workers"], 2)
            progress_callback(
                phase="扫描中",
                message="已处理 1/1 只，命中 1 条",
                done=1,
                total=1,
                matched=1,
                errors=0,
            )
            return {
                "success": True,
                "data": [{"代码": "600000", "名称": "浦发银行"}],
                "count": 1,
                "elapsed_sec": 0.1,
                "output": "",
                "meta": {
                    "mode": "both",
                    "pool": "all_a",
                    "pool_source": "auto",
                    "recent_days": 30,
                    "workers": params["workers"],
                    "scanned": 1,
                    "errors": 0,
                },
            }

        with patch.object(scanner_routes, "_run_wash_pattern_scan", side_effect=fake_scan):
            response = self.client.post("/api/scanners/wash-pattern/start?mode=both&workers=2&max_stocks=1")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["success"])
            job_id = payload["job_id"]

            job = None
            for _ in range(20):
                status_response = self.client.get(f"/api/scanners/jobs/{job_id}")
                self.assertEqual(status_response.status_code, 200)
                job = status_response.get_json()["job"]
                if job["status"] == "completed":
                    break
                time.sleep(0.05)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["percent"], 100)
        self.assertEqual(job["matched"], 1)
        self.assertEqual(job["result"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
