from copy import deepcopy
from datetime import datetime, timezone

import pytest

import workbench_service
from workbench_service import (
    apply_candidate_risk_precheck,
    build_execution_context,
    build_today_workbench,
)


LIVE_TIME = datetime(2026, 8, 12, 10, 0)
REVIEW_TIME = datetime(2026, 8, 12, 12, 0)


@pytest.fixture(autouse=True)
def confirmed_trading_calendar(monkeypatch):
    """普通交易日用例不依赖网络日历，且保持可预测。"""

    monkeypatch.setattr(
        workbench_service, "_default_trading_day_checker", lambda _day: True
    )


def emotion(**overrides):
    value = {
        "score": 68,
        "level": "分歧",
        "confidence": 1.0,
        "as_of": "2026-08-12 10:00:00",
        "cached": False,
        "position": {
            "level": "分歧",
            "action": "半仓标准",
            "max_total_position": 0.5,
            "max_single_position": 0.15,
            "can_open": True,
        },
    }
    value.update(overrides)
    return value


def stock(code, **overrides):
    value = {
        "code": code,
        "name": f"股票{code}",
        "role": "龙头",
        "limit_count": 2,
        "divergence": "分歧",
        "cross": "昨弱今强",
        "buy_hint": True,
        "sell_alert": "",
    }
    value.update(overrides)
    return value


def ladder(stocks=None, **overrides):
    value = {
        "as_of": "2026-08-12 10:00:00",
        "data_as_of": "2026-08-12 09:59:00",
        "data_stale": False,
        "cached": False,
        "spirit": {"cycle": "中", "buy_hint_reliable": True},
        "sectors": [{"sector": "测试题材", "stocks": stocks or []}],
    }
    value.update(overrides)
    return value


def test_execution_context_allows_only_live_healthy_open_signal():
    context = build_execution_context(emotion(), LIVE_TIME)

    assert context["mode"] == "live"
    assert context["can_execute"] is True
    assert context["status_label"] == "盘中可执行"
    assert context["position"]["max_single_position"] == 0.15


@pytest.mark.parametrize(
    ("now", "overrides", "reason"),
    [
        (REVIEW_TIME, {}, "非A股交易时段"),
        (datetime(2026, 8, 15, 10, 0), {}, "非A股工作日"),
        (LIVE_TIME, {"stale": True}, "情绪数据陈旧"),
        (LIVE_TIME, {"degraded": True}, "情绪数据已降级"),
        (LIVE_TIME, {"confidence": 0.66}, "情绪可信度不足"),
        (LIVE_TIME, {"position": {"can_open": False}}, "不允许开仓"),
    ],
)
def test_execution_context_blocks_each_core_gate(now, overrides, reason):
    context = build_execution_context(emotion(**overrides), now)

    assert context["can_execute"] is False
    assert reason in context["reason"]


def test_execution_context_converts_aware_datetime_to_shanghai_time():
    # 02:00 UTC is 10:00 in Shanghai.
    context = build_execution_context(emotion(), datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc))

    assert context["mode"] == "live"
    assert context["checked_at"] == "2026-08-12 10:00:00"


def test_weekday_public_holiday_never_becomes_executable():
    holiday = datetime(2026, 10, 1, 10, 0)
    context = build_execution_context(
        emotion(
            as_of="2026-10-01 10:00:00",
            data_as_of="2026-10-01 10:00:00",
        ),
        holiday,
        trading_day_checker=lambda _day: False,
    )

    assert context["mode"] == "review"
    assert context["can_execute"] is False
    assert context["is_workday"] is True
    assert context["is_trading_day"] is False
    assert context["in_clock_window"] is True
    assert context["in_trading_window"] is False
    assert "非A股交易日" in context["blockers"]


def test_unavailable_calendar_fails_closed_even_with_same_day_data():
    context = build_execution_context(
        emotion(data_as_of="2026-08-12 09:59:00"),
        LIVE_TIME,
        trading_day_checker=lambda _day: None,
    )

    assert context["mode"] == "review"
    assert context["can_execute"] is False
    assert context["trading_day_status"] == "unconfirmed"
    assert context["freshness"]["emotion_data_is_today"] is True
    assert "交易日待确认" in context["blockers"]


def test_non_today_emotion_data_is_an_execution_blocker():
    context = build_execution_context(
        emotion(
            as_of="2026-08-12 10:00:00",
            data_as_of="2026-08-11 15:00:00",
        ),
        LIVE_TIME,
        trading_day_checker=lambda _day: True,
    )

    assert context["can_execute"] is False
    assert context["freshness"]["emotion_data_date_source"] == "data_as_of"
    assert context["freshness"]["emotion_data_is_today"] is False
    assert "情绪数据非当日" in context["blockers"]


def test_workbench_keeps_research_candidates_when_calendar_is_unconfirmed():
    result = build_today_workbench(
        emotion(data_as_of="2026-08-12 09:59:00"),
        ladder([stock("000001")]),
        LIVE_TIME,
        trading_day_checker=lambda _day: None,
    )

    assert result["executable"] is False
    assert [item["code"] for item in result["primary"]] == ["000001"]
    assert "交易日待确认" in result["warnings"]


def test_workbench_scores_stably_and_splits_primary_and_watch():
    rows = [
        stock("000003", cross="", buy_hint=False, role="龙三", limit_count=3),
        stock("000002", cross="", buy_hint=True, role="龙头", limit_count=2),
        stock("000001", cross="昨弱今强", buy_hint=False, role="龙二", limit_count=2),
    ]

    result = build_today_workbench(emotion(), ladder(rows), LIVE_TIME)

    assert [item["code"] for item in result["primary"]] == ["000002", "000001"]
    assert [item["code"] for item in result["watch"]] == ["000003"]
    assert result["primary"][0]["precheck_score"] > result["primary"][1]["precheck_score"]
    assert result["watch"][0]["blockers"] == ["缺少昨弱今强或可靠买点"]


def test_review_mode_keeps_research_priority_but_never_marks_it_executable():
    result = build_today_workbench(emotion(), ladder([stock("000001")]), REVIEW_TIME)

    assert [item["code"] for item in result["primary"]] == ["000001"]
    assert result["executable"] is False
    assert result["execution"]["mode"] == "review"
    assert "非A股交易时段" in result["warnings"]


def test_workbench_deduplicates_by_code_and_keeps_best_ranked_record():
    data = ladder(
        [stock("000001", role="龙二", buy_hint=False)],
        sectors=[
            {"sector": "主线", "stocks": [stock("000001", role="龙头", name="最佳记录")]},
            {"sector": "支线", "stocks": [stock("000001", role="龙二", name="次优记录")]},
        ],
    )

    result = build_today_workbench(emotion(), data, LIVE_TIME)

    assert len(result["primary"]) == 1
    assert result["primary"][0]["name"] == "最佳记录"
    assert result["source_summary"]["duplicate_count"] == 1


def test_workbench_enforces_primary_and_watch_limits():
    rows = [stock(f"{index:06d}") for index in range(1, 20)]

    result = build_today_workbench(emotion(), ladder(rows), LIVE_TIME)

    assert len(result["primary"]) == 3
    assert len(result["watch"]) == 10
    assert all(item["blockers"] == ["主选名额已满"] for item in result["watch"])


def test_workbench_degrades_primary_when_emotion_or_ladder_is_unreliable():
    result = build_today_workbench(
        emotion(confidence=0.5),
        ladder([stock("000001")], data_stale=True),
        LIVE_TIME,
    )

    assert result["status"] == "degraded"
    assert result["quality"] == "low"
    assert result["executable"] is False
    assert result["primary"] == []
    assert result["watch"][0]["code"] == "000001"
    assert "情绪可信度不足（50%）" in result["watch"][0]["blockers"]
    assert "梯队数据陈旧" in result["watch"][0]["blockers"]


def test_weak_cycle_downgrades_buy_hint_but_allows_cross_signal():
    data = ladder(
        [
            stock("000001", cross="", buy_hint=True),
            stock("000002", cross="昨弱今强", buy_hint=True),
        ],
        spirit={"cycle": "弱", "buy_hint_reliable": False},
    )

    result = build_today_workbench(emotion(), data, LIVE_TIME)

    assert [item["code"] for item in result["primary"]] == ["000002"]
    assert result["watch"][0]["code"] == "000001"
    assert "弱周期分歧买点不进入主选" in result["watch"][0]["blockers"]


def test_hard_exclusions_remove_missing_code_sell_alert_and_irrelevant_rows():
    rows = [
        stock(""),
        stock("000001", sell_alert="一致加速"),
        stock("000002", role="梯队", cross="", buy_hint=False),
        stock("000003", role="梯队", cross="昨弱今强", buy_hint=False),
    ]

    result = build_today_workbench(emotion(), ladder(rows), LIVE_TIME)

    assert [item["code"] for item in result["primary"]] == ["000003"]
    assert result["source_summary"]["hard_excluded_count"] == 3


def test_empty_or_malformed_fields_return_a_safe_degraded_response():
    result = build_today_workbench({}, {"sectors": "invalid"}, LIVE_TIME)

    assert result["status"] == "degraded"
    assert result["executable"] is False
    assert result["primary"] == []
    assert result["watch"] == []
    assert result["source_summary"]["stock_count"] == 0
    assert "暂无符合预检条件的梯队候选" in result["warnings"]


def test_inputs_are_not_mutated():
    emotion_input = emotion()
    ladder_input = ladder([stock("000001")])
    original_stock = dict(ladder_input["sectors"][0]["stocks"][0])

    build_today_workbench(emotion_input, ladder_input, LIVE_TIME)

    assert ladder_input["sectors"][0]["stocks"][0] == original_stock
    assert "tier" not in ladder_input["sectors"][0]["stocks"][0]


def analysis(code, decision="低吸", **overrides):
    value = {
        "stock_code": code,
        "decision": decision,
        "veto_triggered": False,
        "veto_reason": None,
        "total_score": 70,
        "timestamp": "2026-08-12 10:01:00",
    }
    value.update(overrides)
    return value


def test_risk_precheck_excludes_vetoed_top_one_and_backfills_fourth():
    base = build_today_workbench(
        emotion(),
        ladder([stock(f"{index:06d}") for index in range(1, 6)]),
        LIVE_TIME,
    )
    analyses = {
        "000001": analysis(
            "000001", veto_triggered=True, veto_reason="主力资金持续流出"
        ),
        **{
            f"{index:06d}": analysis(f"{index:06d}")
            for index in range(2, 6)
        },
    }

    result = apply_candidate_risk_precheck(base, analyses)

    assert [item["code"] for item in result["primary"]] == ["000002", "000003", "000004"]
    assert [item["code"] for item in result["risk_excluded"]] == ["000001"]
    assert result["risk_excluded"][0]["risk_precheck"]["status"] == "excluded"
    assert result["deep_precheck"] == {
        "reviewed": 5,
        "passed": 4,
        "excluded": 1,
        "errors": 0,
    }


def test_unanalysed_candidate_never_remains_primary():
    base = build_today_workbench(
        emotion(), ladder([stock("000001"), stock("000002")]), LIVE_TIME
    )

    result = apply_candidate_risk_precheck(
        base, {"000002": analysis("000002", decision="观察")}
    )

    assert [item["code"] for item in result["primary"]] == ["000002"]
    pending = next(item for item in result["watch"] if item["code"] == "000001")
    assert pending["risk_precheck"]["status"] == "pending"
    assert "个股风险预检未完成" in pending["blockers"]


def test_avoid_decision_and_analysis_error_are_watch_only():
    base = build_today_workbench(
        emotion(),
        ladder([stock("000001"), stock("000002"), stock("000003")]),
        LIVE_TIME,
    )

    result = apply_candidate_risk_precheck(
        base,
        {
            "000001": analysis("000001", decision="回避"),
            "000002": {"success": False, "error": "行情获取失败"},
            "000003": analysis("000003", decision="观察"),
        },
    )

    assert [item["code"] for item in result["primary"]] == ["000003"]
    by_code = {item["code"]: item for item in result["watch"]}
    assert "个股风险预检结论为回避" in by_code["000001"]["blockers"]
    assert by_code["000002"]["risk_precheck"]["status"] == "error"
    assert "个股风险预检异常" in by_code["000002"]["blockers"]
    assert result["deep_precheck"]["errors"] == 1


def test_analyzed_code_without_result_is_an_error_and_watch_only():
    base = build_today_workbench(emotion(), ladder([stock("000001")]), LIVE_TIME)

    result = apply_candidate_risk_precheck(base, {}, analyzed_codes=["000001"])

    assert result["primary"] == []
    assert result["watch"][0]["risk_precheck"]["status"] == "error"
    assert result["deep_precheck"]["errors"] == 1


def test_risk_precheck_keeps_limits_and_does_not_mutate_inputs():
    base = build_today_workbench(
        emotion(),
        ladder([stock(f"{index:06d}") for index in range(1, 20)]),
        LIVE_TIME,
    )
    analyses = {
        item["code"]: analysis(item["code"], decision="观察")
        for item in [*base["primary"], *base["watch"]]
    }
    base_before = deepcopy(base)
    analyses_before = deepcopy(analyses)

    result = apply_candidate_risk_precheck(base, analyses)

    assert len(result["primary"]) == 3
    assert len(result["watch"]) == 10
    assert base == base_before
    assert analyses == analyses_before
    assert all("risk_precheck" not in item for item in base["primary"])


# ---------- 统一执行闸：情绪闸 + 指数闸取更严格者 ----------
BLOCKED_MARKET = {
    "can_trade": False,
    "state": "无主线震荡",
    "state_type": "空仓态",
    "reason": "指数在MA5下方",
    "suggestion": "空仓观望",
}


def test_market_gate_overrides_aggressive_emotion_action():
    hot = emotion(position={
        "level": "高潮", "action": "满仓进攻", "can_open": True,
        "max_total_position": 1.0, "max_single_position": 0.3,
    })
    context = build_execution_context(hot, LIVE_TIME, market_state=BLOCKED_MARKET)

    assert context["can_execute"] is False
    assert context["position"]["can_open"] is False
    assert context["action"] == "暂停新增开仓"  # 不再同时出现"满仓进攻"与"禁止开仓"
    assert any("指数空仓态" in b for b in context["blockers"])
    assert "以更严格的指数闸为准" in context["decided_by"]
    assert context["gates"]["emotion"]["can_open"] is True
    assert context["gates"]["market"]["can_trade"] is False


def test_unknown_market_state_fails_closed_but_missing_input_is_ignored():
    assert build_execution_context(emotion(), LIVE_TIME)["can_execute"] is True
    context = build_execution_context(emotion(), LIVE_TIME, market_state={"error": "timeout"})
    assert context["can_execute"] is False
    assert "指数状态未知" in context["blockers"]


def test_workbench_uses_market_gate_for_all_candidates():
    result = build_today_workbench(
        emotion(), ladder([stock("000001")]), generated_at=LIVE_TIME, market_state=BLOCKED_MARKET
    )
    assert result["executable"] is False
    assert result["primary"] == []
    assert any("指数空仓态" in b for b in result["watch"][0]["blockers"])


def test_unbuyable_limit_up_never_becomes_primary_during_session():
    sealed = stock("000001", first_limit_time="09:25:01", turnover_rate=1.6)
    tradable = stock("000002", first_limit_time="10:12:00", turnover_rate=8.0, role="龙二")
    result = build_today_workbench(emotion(), ladder([sealed, tradable]), generated_at=LIVE_TIME)

    assert [c["code"] for c in result["primary"]] == ["000002"]
    watched = {c["code"]: c for c in result["watch"]}
    assert "盘中一字板，无法买入" in watched["000001"]["blockers"]


def test_unbuyable_limit_up_stays_researchable_in_review_mode():
    sealed = stock("000001", first_limit_time="09:25:01", turnover_rate=1.6)
    result = build_today_workbench(emotion(), ladder([sealed]), generated_at=REVIEW_TIME)
    assert all("一字板" not in b for c in result["primary"] + result["watch"] for b in c["blockers"])
