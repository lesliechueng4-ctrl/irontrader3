import unittest

from sector_flow_scorer import SectorFlowScorer


class _FetcherWithoutSectorData:
    def __init__(self):
        self.cache = {}
        self.source_client = None

    def _normalize_code(self, code):
        return str(code)

    def _get_cache(self, key):
        return self.cache.get(key)

    def _set_cache(self, key, value):
        self.cache[key] = value

    def get_limit_up_pool(self):
        return []

    def get_sector_money_flow_map(self):
        return {}


class SectorFlowScorerTest(unittest.TestCase):
    def test_missing_sector_is_neutral_not_outflow(self):
        scorer = SectorFlowScorer(_FetcherWithoutSectorData())

        result = scorer.score_sector("600000")

        self.assertEqual(result["score"], 50)
        self.assertEqual(result["status"], "未知")
        self.assertTrue(result["details"]["data_missing"])

    def test_missing_sector_money_flow_keeps_neutral_base(self):
        scorer = SectorFlowScorer(_FetcherWithoutSectorData())

        result = scorer.score_sector("600000", "半导体")

        self.assertEqual(result["score"], 50)
        self.assertEqual(result["status"], "未知")

    def test_sector_missing_from_flow_map_with_limit_ups_does_not_crash(self):
        # 东财板块资金流失败、退到同花顺行业时板块名对不上：资金流表非空但找不到这个板块，
        # 而板块里有涨停（热门候选正是这种情况）。以前 _detect_switching 拿 None 和 0 比较直接抛 TypeError。
        class Fetcher(_FetcherWithoutSectorData):
            def get_limit_up_pool(self):
                return [{"code": "002724", "sector": "照明设备", "limit_count": 2, "seal_amount": 30_000_000}]

            def get_sector_money_flow_map(self):
                return {"半导体": {"net_inflow": 8e8, "net_inflow_pct": 3.0, "rank": 1, "change_pct": 2.0},
                        "白酒": {"net_inflow": -2e8, "net_inflow_pct": -1.0, "rank": 2, "change_pct": -1.0}}

        scorer = SectorFlowScorer(Fetcher())

        result = scorer.score_sector("002724", "照明设备")

        self.assertEqual(result["details"]["switching_direction"], "中性")
        self.assertIsNone(result["details"]["sector_net_inflow"])
        self.assertEqual(result["details"]["sector_limit_up_count"], 1)
        # 只算涨停家数（+3），资金流、排名、切换方向都不加减分
        self.assertEqual(result["score"], 53)

    def test_switching_direction_still_works_when_flow_is_known(self):
        scorer = SectorFlowScorer(_FetcherWithoutSectorData())
        self.assertEqual(scorer._detect_switching("半导体", {"net_inflow": 1e8, "rank": 2, "total": 50}), "被切入")
        self.assertEqual(scorer._detect_switching("白酒", {"net_inflow": -1e8, "rank": 45, "total": 50}), "被切出")
        self.assertEqual(scorer._detect_switching("白酒", {"net_inflow": None, "rank": 0, "total": 50}), "中性")
        self.assertEqual(scorer._detect_switching("白酒", {"net_inflow": None, "rank": 30, "total": 50}), "中性")

    def test_stock_sector_uses_eastmoney_f127_fallback(self):
        class Response:
            @staticmethod
            def json():
                return {"data": {"f127": "化学制药"}}

        class SourceClient:
            def get(self, *args, **kwargs):
                return type("Result", (), {"ok": True, "response": Response()})()

        fetcher = _FetcherWithoutSectorData()
        fetcher.source_client = SourceClient()
        scorer = SectorFlowScorer(fetcher)

        sector = scorer._get_stock_sector("603259")

        self.assertEqual(sector, "化学制药")
        self.assertEqual(fetcher.cache["stock_sector_603259"], "化学制药")


if __name__ == "__main__":
    unittest.main()
