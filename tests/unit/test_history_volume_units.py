import unittest

import pandas as pd

from data_fetcher import DataFetcher


class HistoryVolumeUnitTest(unittest.TestCase):
    def test_data_fetcher_normalizes_eastmoney_lots_to_shares(self):
        raw = pd.DataFrame([{
            "日期": "2026-08-07",
            "开盘": 10.0,
            "最高": 10.5,
            "最低": 9.8,
            "收盘": 10.2,
            "成交量": 12345,
        }])

        result = DataFetcher._normalize_history_frame(
            raw,
            volume_multiplier=100.0,
            source_name="stock_zh_a_hist",
        )

        self.assertEqual(result.iloc[0]["volume"], 1_234_500)
        self.assertEqual(result.attrs["volume_unit"], "shares")
        self.assertEqual(result.attrs["data_source"], "stock_zh_a_hist")


if __name__ == "__main__":
    unittest.main()
