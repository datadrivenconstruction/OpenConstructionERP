# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure action-coordination engine (runs on py3.11)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.modules.change_intelligence.coordination import (
    ACTION_AWAIT,
    ACTION_ESCALATE,
    ACTION_NUDGE,
    ACTION_REVIEW,
    URGENCY_DUE_SOON,
    URGENCY_NO_DATE,
    URGENCY_OVERDUE,
    URGENCY_UPCOMING,
    ActionItem,
    build_plan,
    classify,
    days_between,
    parse_date,
    recommend,
)

NOW = datetime(2026, 6, 24)
TODAY = date(2026, 6, 24)


def _item(
    *,
    ref_id: str = "1",
    kind: str = "change_order",
    title: str = "Item",
    ball_in_court: str = "alice",
    status: str = "open",
    due_date: str | None = None,
    age_days: int | None = None,
) -> ActionItem:
    return ActionItem(
        ref_id=ref_id,
        kind=kind,
        title=title,
        ball_in_court=ball_in_court,
        status=status,
        due_date=due_date,
        age_days=age_days,
    )


# --- parse_date ------------------------------------------------------------


def test_parse_date_accepts_date_only() -> None:
    assert parse_date("2026-07-01") == date(2026, 7, 1)


def test_parse_date_accepts_full_datetime() -> None:
    assert parse_date("2026-07-01T09:30:00") == date(2026, 7, 1)


def test_parse_date_accepts_datetime_with_offset() -> None:
    assert parse_date("2026-07-01T09:30:00+02:00") == date(2026, 7, 1)


def test_parse_date_accepts_trailing_z() -> None:
    assert parse_date("2026-07-01T09:30:00Z") == date(2026, 7, 1)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_parse_date_blank_returns_none(value: str | None) -> None:
    assert parse_date(value) is None


@pytest.mark.parametrize("value", ["not-a-date", "2026-13-99", "07/01/2026", "abc"])
def test_parse_date_garbage_returns_none_without_raising(value: str) -> None:
    assert parse_date(value) is None


# --- days_between ----------------------------------------------------------


def test_days_between_forward() -> None:
    assert days_between(date(2026, 6, 24), date(2026, 6, 27)) == 3


def test_days_between_negative_when_end_precedes_start() -> None:
    assert days_between(date(2026, 6, 24), date(2026, 6, 23)) == -1


def test_days_between_same_day_is_zero() -> None:
    assert days_between(TODAY, TODAY) == 0


# --- classify (boundaries) -------------------------------------------------


def test_classify_due_yesterday_is_overdue() -> None:
    urgency, days = classify("2026-06-23", TODAY)
    assert urgency == URGENCY_OVERDUE
    assert days == -1


def test_classify_due_today_is_due_soon() -> None:
    urgency, days = classify("2026-06-24", TODAY)
    assert urgency == URGENCY_DUE_SOON
    assert days == 0


def test_classify_due_in_exactly_two_days_is_due_soon() -> None:
    urgency, days = classify("2026-06-26", TODAY)
    assert urgency == URGENCY_DUE_SOON
    assert days == 2


def test_classify_due_in_three_days_is_upcoming() -> None:
    urgency, days = classify("2026-06-27", TODAY)
    assert urgency == URGENCY_UPCOMING
    assert days == 3


def test_classify_no_date_is_no_date() -> None:
    urgency, days = classify(None, TODAY)
    assert urgency == URGENCY_NO_DATE
    assert days is None


def test_classify_unparseable_date_is_no_date() -> None:
    urgency, days = classify("garbage", TODAY)
    assert urgency == URGENCY_NO_DATE
    assert days is None


# --- recommend -------------------------------------------------------------


def test_recommend_overdue_escalates() -> None:
    action, reason = recommend(URGENCY_OVERDUE)
    assert action == ACTION_ESCALATE
    assert reason and isinstance(reason, str)


def test_recommend_due_soon_nudges() -> None:
    action, reason = recommend(URGENCY_DUE_SOON)
    assert action == ACTION_NUDGE
    assert reason and isinstance(reason, str)


def test_recommend_upcoming_reviews() -> None:
    action, reason = recommend(URGENCY_UPCOMING)
    assert action == ACTION_REVIEW
    assert reason and isinstance(reason, str)


def test_recommend_no_date_awaits() -> None:
    action, reason = recommend(URGENCY_NO_DATE)
    assert action == ACTION_AWAIT
    assert reason and isinstance(reason, str)


# --- build_plan: cross-bucket ordering -------------------------------------


def test_build_plan_orders_overdue_before_due_soon_before_upcoming_before_no_date() -> None:
    items = [
        _item(ref_id="no", due_date=None),
        _item(ref_id="up", due_date="2026-06-30"),  # +6 -> upcoming
        _item(ref_id="ds", due_date="2026-06-25"),  # +1 -> due_soon
        _item(ref_id="od", due_date="2026-06-20"),  # -4 -> overdue
    ]
    plan = build_plan(items, NOW)
    assert [s.ref_id for s in plan.steps] == ["od", "ds", "up", "no"]
    assert [s.urgency for s in plan.steps] == [
        URGENCY_OVERDUE,
        URGENCY_DUE_SOON,
        URGENCY_UPCOMING,
        URGENCY_NO_DATE,
    ]


# --- build_plan: within-bucket ordering ------------------------------------


def test_build_plan_more_overdue_ranks_first() -> None:
    items = [
        _item(ref_id="late1", due_date="2026-06-23"),  # -1
        _item(ref_id="late10", due_date="2026-06-14"),  # -10
    ]
    plan = build_plan(items, NOW)
    assert [s.ref_id for s in plan.steps] == ["late10", "late1"]


def test_build_plan_sooner_due_soon_ranks_first() -> None:
    items = [
        _item(ref_id="in2", due_date="2026-06-26"),  # +2
        _item(ref_id="in0", due_date="2026-06-24"),  # 0
    ]
    plan = build_plan(items, NOW)
    assert [s.ref_id for s in plan.steps] == ["in0", "in2"]


def test_build_plan_sooner_upcoming_ranks_first() -> None:
    items = [
        _item(ref_id="far", due_date="2026-08-01"),
        _item(ref_id="near", due_date="2026-06-28"),
    ]
    plan = build_plan(items, NOW)
    assert [s.ref_id for s in plan.steps] == ["near", "far"]


def test_build_plan_ties_break_by_ref_id() -> None:
    items = [
        _item(ref_id="b", due_date="2026-06-25"),
        _item(ref_id="a", due_date="2026-06-25"),
    ]
    plan = build_plan(items, NOW)
    assert [s.ref_id for s in plan.steps] == ["a", "b"]


# --- build_plan: counts, metadata, empty -----------------------------------


def test_build_plan_counts_overdue_and_due_soon() -> None:
    items = [
        _item(ref_id="od1", due_date="2026-06-20"),
        _item(ref_id="od2", due_date="2026-06-21"),
        _item(ref_id="ds1", due_date="2026-06-25"),
        _item(ref_id="up1", due_date="2026-07-10"),
        _item(ref_id="no1", due_date=None),
    ]
    plan = build_plan(items, NOW)
    assert plan.total == 5
    assert plan.overdue_count == 2
    assert plan.due_soon_count == 1


def test_build_plan_generated_at_is_set_from_now() -> None:
    plan = build_plan([_item()], NOW)
    assert plan.generated_at == "2026-06-24"


def test_build_plan_accepts_plain_date_for_now() -> None:
    plan = build_plan([_item(ref_id="od", due_date="2026-06-20")], TODAY)
    assert plan.generated_at == "2026-06-24"
    assert plan.steps[0].urgency == URGENCY_OVERDUE


def test_build_plan_empty_input_gives_zero_total_and_empty_steps() -> None:
    plan = build_plan([], NOW)
    assert plan.total == 0
    assert plan.overdue_count == 0
    assert plan.due_soon_count == 0
    assert plan.steps == ()


def test_build_plan_step_carries_action_and_reason() -> None:
    plan = build_plan([_item(ref_id="od", due_date="2026-06-20")], NOW)
    step = plan.steps[0]
    assert step.recommended_action == ACTION_ESCALATE
    assert step.reason
    assert step.days_to_due == -4


def test_build_plan_steps_is_a_tuple() -> None:
    plan = build_plan([_item()], NOW)
    assert isinstance(plan.steps, tuple)
