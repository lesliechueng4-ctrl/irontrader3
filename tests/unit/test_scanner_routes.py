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
            def get_stock_history(code):
                return pd.DataFrame([{"close": 10.0}, {"close": 10.8}])

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
            self.assertTrue(output_path.exists())

        self.assertEqual(len(records), 2)
        self.assertEqual(meta["scanned"], 2)
        self.assertEqual(meta["errors"], 0)
        self.assertEqual(records[0]["策略组"], "A股条件筛选")
        self.assertEqual(progress_updates[-1]["done"], 2)
        self.assertEqual(progress_updates[-1]["total"], 2)
        self.assertEqual(progress_updates[-1]["matched"], 2)

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
        def fake_scan(params, progress_callback=None):
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
