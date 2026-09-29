"""Tests for the pure unified research-conclusion aggregator."""

import unittest

from research_conclusion import build_final_conclusion


def dragon(decision="IGNORE", is_limit_up=False, can_trade=True):
    return {
        "decision": decision,
        "stock_info": {"is_limit_up": is_limit_up},
        "market_state": {"can_trade": can_trade},
    }


def lowbuy(decision="等待", veto=False, can_open=True):
    return {
        "decision": decision,
        "veto_triggered": veto,
        "veto_reason": "下降趋势风险" if veto else None,
        "emotion_gate": {"can_open": can_open, "max_single_position": 0.15},
        "timestamp": "2026-08-12 14:30:00",
    }


class ResearchConclusionMatrixTest(unittest.TestCase):
    def assert_conclusion(self, expected_status, expected_primary, d, lb, **kwargs):
        result = build_final_conclusion(d, lb, **kwargs)
        self.assertEqual(result["status"], expected_status)
        self.assertEqual(result["primary_strategy"], expected_primary)
        self.assertEqual(result["label"], {
            "EXECUTABLE": "可执行",
            "CONFIRM": "等确认",
            "OBSERVE": "仅观察",
            "NOT_APPLICABLE": "不适用",
        }[expected_status])
        return result

    def test_non_limit_up_uses_lowbuy_buy_signal(self):
        result = self.assert_conclusion(
            "EXECUTABLE", "lowbuy", dragon(is_limit_up=False), lowbuy("低吸")
        )
        self.assertEqual(result["reason_code"], "BUY_SETUP")

    def test_lowbuy_watch_requires_confirmation(self):
        self.assert_conclusion(
            "CONFIRM", "lowbuy", dragon(is_limit_up=False), lowbuy("观察")
        )

    def test_lowbuy_wait_is_observe(self):
        self.assert_conclusion(
            "OBSERVE", "lowbuy", dragon(is_limit_up=False), lowbuy("等待")
        )

    def test_lowbuy_avoid_without_veto_is_observe(self):
        self.assert_conclusion(
            "OBSERVE", "lowbuy", dragon(is_limit_up=False), lowbuy("回避")
        )

    def test_limit_up_dragon_buy_is_primary(self):
        self.assert_conclusion(
            "EXECUTABLE", "dragon", dragon("BUY", True), lowbuy("观察")
        )

    def test_limit_up_dragon_watch_is_primary(self):
        self.assert_conclusion(
            "CONFIRM", "dragon", dragon("WATCH", True), lowbuy("低吸")
        )

    def test_limit_up_dragon_ignore_is_observe(self):
        self.assert_conclusion(
            "OBSERVE", "dragon", dragon("IGNORE", True), lowbuy("低吸")
        )

    def test_global_veto_overrides_dragon_buy(self):
        result = self.assert_conclusion(
            "NOT_APPLICABLE", "none", dragon("BUY", True), lowbuy("回避", veto=True)
        )
        self.assertEqual(result["reason_code"], "GLOBAL_VETO")

    def test_market_block_downgrades_to_observe(self):
        result = self.assert_conclusion(
            "OBSERVE", "dragon", dragon("BUY", True, can_trade=False), lowbuy("观察")
        )
        self.assertEqual(result["reason_code"], "MARKET_BLOCKED")

    def test_emotion_block_downgrades_to_observe(self):
        result = self.assert_conclusion(
            "OBSERVE", "lowbuy", dragon(is_limit_up=False), lowbuy("低吸", can_open=False)
        )
        self.assertEqual(result["reason_code"], "EMOTION_BLOCKED")

    def test_ttl_cached_data_does_not_downgrade_by_itself(self):
        result = self.assert_conclusion(
            "EXECUTABLE",
            "lowbuy",
            dragon(is_limit_up=False),
            lowbuy("低吸"),
            execution={"freshness": "cached"},
        )
        self.assertEqual(result["reason_code"], "BUY_SETUP")
        self.assertEqual(result["data"]["freshness"], "cached")

    def test_structured_dragon_data_error_caps_lowbuy_at_confirmation(self):
        broken_dragon = dragon(is_limit_up=False)
        broken_dragon["stock_info"]["error"] = "所有数据源均不可用"
        result = self.assert_conclusion(
            "CONFIRM", "lowbuy", broken_dragon, lowbuy("低吸")
        )
        self.assertEqual(result["reason_code"], "DATA_ERROR")
        self.assertEqual(result["strategies"]["dragon"]["reason_code"], "DATA_ERROR")
        self.assertEqual(result["data"]["status"], "partial")
        self.assertFalse(result["position"]["can_open"])

    def test_structured_dragon_data_error_without_fallback_is_not_applicable(self):
        broken_dragon = dragon(is_limit_up=False)
        broken_dragon["stock_info"]["error"] = "所有数据源均不可用"
        result = self.assert_conclusion(
            "NOT_APPLICABLE", "none", broken_dragon, None
        )
        self.assertEqual(result["reason_code"], "DATA_ERROR")
        self.assertEqual(result["data"]["status"], "unavailable")

    def test_structured_lowbuy_data_error_caps_dragon_at_confirmation(self):
        broken_lowbuy = lowbuy("回避")
        broken_lowbuy.update(data_error=True, error="实时行情数据不可用")
        result = self.assert_conclusion(
            "CONFIRM", "dragon", dragon("BUY", True), broken_lowbuy
        )
        self.assertEqual(result["reason_code"], "DATA_ERROR")
        self.assertEqual(result["strategies"]["lowbuy"]["reason_code"], "DATA_ERROR")

    def test_review_with_only_session_blocker_requires_confirmation(self):
        result = self.assert_conclusion(
            "CONFIRM",
            "lowbuy",
            dragon(is_limit_up=False),
            lowbuy("低吸"),
            execution={
                "mode": "review",
                "can_execute": False,
                "blockers": ["非A股交易时段"],
                "freshness": "off_session",
            },
        )
        self.assertEqual(result["reason_code"], "OFF_SESSION")
        self.assertTrue(any(
            item["code"] == "SESSION_REVIEW" and item["message"] == "非A股交易时段"
            for item in result["blockers"]
        ))

    def test_review_on_market_holiday_keeps_plan_as_confirmation(self):
        result = self.assert_conclusion(
            "CONFIRM",
            "lowbuy",
            dragon(is_limit_up=False),
            lowbuy("低吸"),
            execution={
                "mode": "review",
                "can_execute": False,
                "blockers": ["非A股交易日"],
                "freshness": "off_session",
            },
        )
        self.assertFalse(result["position"]["can_open"])
        self.assertTrue(any(
            item["message"] == "非A股交易日" for item in result["blockers"]
        ))

    def test_review_with_unconfirmed_calendar_keeps_plan_but_surfaces_blocker(self):
        result = self.assert_conclusion(
            "CONFIRM",
            "lowbuy",
            dragon(is_limit_up=False),
            lowbuy("低吸"),
            execution={
                "mode": "review",
                "can_execute": False,
                "blockers": ["交易日待确认"],
                "freshness": "off_session",
            },
        )
        self.assertFalse(result["position"]["can_open"])
        self.assertTrue(any(
            item["message"] == "交易日待确认" for item in result["blockers"]
        ))

    def test_review_with_data_blocker_is_observe(self):
        result = self.assert_conclusion(
            "OBSERVE",
            "lowbuy",
            dragon(is_limit_up=False),
            lowbuy("低吸"),
            execution={
                "mode": "review",
                "can_execute": False,
                "blockers": ["非A股交易时段", "情绪可信度不足（0%）"],
                "freshness": "off_session",
            },
        )
        self.assertEqual(result["reason_code"], "EXECUTION_BLOCKED")

    def test_review_without_blocker_details_fails_closed(self):
        result = self.assert_conclusion(
            "OBSERVE",
            "lowbuy",
            dragon(is_limit_up=False),
            lowbuy("低吸"),
            execution={"mode": "review", "can_execute": False, "freshness": "off_session"},
        )
        self.assertEqual(result["reason_code"], "EXECUTION_BLOCKED")

    def test_one_engine_error_caps_valid_strategy_at_confirmation(self):
        result = self.assert_conclusion(
            "CONFIRM", "lowbuy", None, lowbuy("低吸"), errors={"dragon": "failed"}
        )
        self.assertEqual(result["data"]["status"], "partial")
        self.assertEqual(result["reason_code"], "PARTIAL_DATA")

    def test_both_engines_unavailable(self):
        result = self.assert_conclusion(
            "NOT_APPLICABLE",
            "none",
            None,
            None,
            errors={"dragon": "failed", "lowbuy": "failed"},
        )
        self.assertEqual(result["reason_code"], "DATA_UNAVAILABLE")
        self.assertEqual(result["data"]["status"], "unavailable")

    def test_explicit_unavailable_data_has_highest_priority(self):
        result = self.assert_conclusion(
            "NOT_APPLICABLE",
            "none",
            dragon("BUY", True),
            lowbuy("低吸"),
            execution={"data_status": "unavailable"},
        )
        self.assertEqual(result["reason_code"], "DATA_UNAVAILABLE")

    def test_position_is_carried_only_as_an_executable_permission(self):
        result = build_final_conclusion(
            dragon(is_limit_up=False),
            lowbuy("低吸"),
            execution={"position": {"max_total_position": 0.5, "max_single_position": 0.1}},
        )
        self.assertEqual(result["position"], {
            "can_open": True,
            "max_total_position": 0.5,
            "max_single_position": 0.1,
        })


class ResearchConclusionInvariantTest(unittest.TestCase):
    def test_secondary_strategy_never_upgrades_primary(self):
        for primary_decision, expected in (("WATCH", "CONFIRM"), ("IGNORE", "OBSERVE")):
            with self.subTest(primary_decision=primary_decision):
                result = build_final_conclusion(
                    dragon(primary_decision, is_limit_up=True),
                    lowbuy("低吸"),
                )
                self.assertEqual(result["primary_strategy"], "dragon")
                self.assertEqual(result["status"], expected)

    def test_veto_or_unavailable_data_can_never_be_executable(self):
        cases = (
            {"lowbuy_value": lowbuy("低吸", veto=True), "execution": None},
            {"lowbuy_value": lowbuy("低吸"), "execution": {"data_status": "unavailable"}},
        )
        for case in cases:
            with self.subTest(case=case):
                result = build_final_conclusion(
                    dragon("BUY", is_limit_up=True),
                    case["lowbuy_value"],
                    execution=case["execution"],
                )
                self.assertNotEqual(result["status"], "EXECUTABLE")


if __name__ == "__main__":
    unittest.main()


def test_key_reason_names_the_concrete_problem_first():
    from research_conclusion import build_final_conclusion

    dragon = {"decision": "IGNORE", "reason": "⚠️ 一字板，无法买入", "stock_info": {"is_limit_up": True}, "market_state": {
        "can_trade": False, "state_type": "空仓态", "reason": "指数在MA5下方"}}
    lowbuy = {"decision": "观察", "total_score": 80.1,
              "position_check": {"ok": False, "reason": "当日涨停，不是低吸位置，等回踩再看"}}
    result = build_final_conclusion(dragon, lowbuy, execution={"can_execute": True, "mode": "live"})
    assert result["key_reason"] == "龙头策略未通过：一字板，无法买入"
    messages = [b["message"] for b in result["blockers"]]
    assert "指数空仓态：指数在MA5下方，今日不开新仓" in messages
