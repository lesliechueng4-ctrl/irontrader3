"""市场风控降级（_apply_market_gate）回归测试

背景：原逻辑在指数跌破 MA5（空仓态）时直接拦截分析返回 IGNORE；
现改为照常完整分析，仅将 BUY 降级为 WATCH 并附加 risk_warning。
本测试固化该行为，防止回归。
"""

import unittest

from decision_maker import DecisionMaker
from decision_maker_enhanced import DecisionMakerEnhanced


BAD_MARKET = {
    'can_trade': False,
    'state': '单边下跌',
    'suggestion': '⛔ 严禁操作 - 空仓观望',
}

GOOD_MARKET = {
    'can_trade': True,
    'state': '主升浪',
    'suggestion': '🚀 重仓主线 - 追涨龙头',
}


def _bare(cls):
    """跳过 __init__（避免真实 DataFetcher 网络初始化）"""
    return object.__new__(cls)


class MarketGateTestMixin:
    """两个决策引擎共用的断言，子类提供 self.dm"""

    def test_buy_downgraded_to_watch_when_market_blocked(self):
        result = self.dm._apply_market_gate(
            {'decision': 'BUY', 'confidence': 5, 'reason': '符合买入条件'},
            BAD_MARKET,
        )
        self.assertEqual(result['decision'], 'WATCH')
        self.assertLessEqual(result['confidence'], 2)
        self.assertIn('风控警告', result['risk_warning'])
        self.assertIn('风控警告', result['reason'])

    def test_buy_unchanged_when_market_tradable(self):
        result = self.dm._apply_market_gate(
            {'decision': 'BUY', 'confidence': 5, 'reason': 'ok'},
            GOOD_MARKET,
        )
        self.assertEqual(result['decision'], 'BUY')
        self.assertEqual(result['confidence'], 5)
        self.assertNotIn('risk_warning', result)

    def test_ignore_keeps_decision_but_gets_warning(self):
        result = self.dm._apply_market_gate(
            {'decision': 'IGNORE', 'confidence': 3, 'reason': 'x'},
            BAD_MARKET,
        )
        self.assertEqual(result['decision'], 'IGNORE')
        self.assertTrue(result.get('risk_warning'))

    def test_warning_text_empty_when_tradable(self):
        self.assertEqual(self.dm._market_risk_warning(GOOD_MARKET), '')
        self.assertEqual(self.dm._market_risk_warning({}), '')
        self.assertEqual(self.dm._market_risk_warning(None), '')

    def test_warning_text_present_when_blocked(self):
        warning = self.dm._market_risk_warning(BAD_MARKET)
        self.assertIn('单边下跌', warning)
        self.assertIn('空仓观望', warning)


class DecisionMakerGateTest(MarketGateTestMixin, unittest.TestCase):
    def setUp(self):
        self.dm = _bare(DecisionMaker)


class DecisionMakerEnhancedGateTest(MarketGateTestMixin, unittest.TestCase):
    def setUp(self):
        self.dm = _bare(DecisionMakerEnhanced)


class IgnoreResultWarningTest(unittest.TestCase):
    """_ignore_result 在空仓态应自动附加 risk_warning（仅增强版有该方法）"""

    def test_ignore_result_attaches_warning(self):
        dm = _bare(DecisionMakerEnhanced)
        result = dm._ignore_result('600000', '⚠️ 测试理由', BAD_MARKET)
        self.assertEqual(result['decision'], 'IGNORE')
        self.assertIn('风控警告', result.get('risk_warning', ''))

    def test_ignore_result_no_warning_when_tradable(self):
        dm = _bare(DecisionMakerEnhanced)
        result = dm._ignore_result('600000', '⚠️ 测试理由', GOOD_MARKET)
        self.assertNotIn('risk_warning', result)


if __name__ == '__main__':
    unittest.main()
