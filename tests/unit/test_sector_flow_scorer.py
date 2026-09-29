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
