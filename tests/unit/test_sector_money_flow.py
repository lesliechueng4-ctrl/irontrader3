import unittest

import pandas as pd

from data_fetcher import DataFetcher
from decision_maker_enhanced import DecisionMakerEnhanced
from sector_money_flow import SectorMoneyFlowAnalyzer


class SectorMoneyFlowAnalyzerTest(unittest.TestCase):
    def test_scores_hot_sector_with_rank_inflow_and_breadth(self):
        result = SectorMoneyFlowAnalyzer.score_sector_money(
            "Robot",
            {
                "rank": 3,
                "net_inflow": 1_200_000_000,
                "net_inflow_pct": 3.5,
                "amount": 20_000_000_000,
                "source": "test",
            },
            [{"sector": "Robot"} for _ in range(5)],
        )

        self.assertEqual(result["money_temperature"], "hot")
        self.assertGreaterEqual(result["money_score"], 6)
        self.assertFalse(SectorMoneyFlowAnalyzer.should_block_entry(result, 5))

    def test_blocks_thin_sector_with_outflow(self):
        result = SectorMoneyFlowAnalyzer.score_sector_money(
            "Robot",
            {
                "rank": 40,
                "net_inflow": -500_000_000,
                "net_inflow_pct": -2.5,
                "amount": 8_000_000_000,
                "source": "test",
            },
            [{"sector": "Robot"} for _ in range(3)],
        )

        self.assertEqual(result["money_temperature"], "cold")
        self.assertTrue(SectorMoneyFlowAnalyzer.should_block_entry(result, 3))


class DataFetcherSectorMoneyFlowTest(unittest.TestCase):
    def test_normalizes_common_provider_columns(self):
        fetcher = DataFetcher()
        frame = pd.DataFrame(
            {
                "名称": ["Robot"],
                "序号": [2],
                "今日主力净流入-净额": [350_000_000],
                "今日主力净流入-净占比": [1.8],
                "今日成交额": [5_000_000_000],
            }
        )

        result = fetcher._normalize_sector_money_flow_frame(frame, "test")

        self.assertEqual(result["Robot"]["rank"], 2)
        self.assertEqual(result["Robot"]["net_inflow"], 350_000_000)
        self.assertEqual(result["Robot"]["net_inflow_pct"], 1.8)


class DecisionMakerSectorMoneyTest(unittest.TestCase):
    def test_single_decision_blocks_cold_sector_money(self):
        maker = DecisionMakerEnhanced(enable_chip_quality=False)
        zt_pool = [
            {
                "code": "301001",
                "name": "Leader",
                "sector": "Robot",
                "seal_amount": 500_000_000,
                "limit_count": 2,
                "first_limit_time": "09:40:00",
                "turnover_rate": 8,
                "board_type": "gem",
            },
            {"code": "301002", "sector": "Robot", "seal_amount": 300_000_000, "limit_count": 1},
            {"code": "301003", "sector": "Robot", "seal_amount": 200_000_000, "limit_count": 1},
        ]
        market_state = {
            "can_trade": True,
            "state": "test",
            "suggestion": "test",
            "sentiment": {"temperature": "warm", "style_bias": "premium_smallcap"},
        }

        maker.stock_selector.analyze_stock = lambda code, zt_pool=None: {
            "code": code,
            "name": "Leader",
            "is_limit_up": True,
            "is_buyable": True,
            "sector": "Robot",
            "seal_amount": 500_000_000,
            "limit_count": 2,
            "first_limit_time": "09:40:00",
            "turnover_rate": 8,
            "board_type": "gem",
            "is_leader": True,
        }

        result = maker._single_decision(
            "301001",
            market_state,
            zt_pool,
            maker._build_sector_map(zt_pool),
            chip_quality=None,
            sector_money_map={
                "Robot": {
                    "rank": 50,
                    "net_inflow": -600_000_000,
                    "net_inflow_pct": -3.0,
                    "source": "test",
                }
            },
        )

        self.assertEqual(result["decision"], "IGNORE")
        self.assertIn("板块资金确认不足", result["reason"])
        self.assertEqual(result["sector_money"]["money_temperature"], "cold")


if __name__ == "__main__":
    unittest.main()
