# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure hours-saved engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the
local Python 3.11 test runner without app.* or SQLAlchemy on the path. Time
amounts are exercised exclusively with Decimal literals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.value.time_saved import (
    BY_FEATURE,
    BY_PERIOD,
    BY_PROJECT,
    BY_USER,
    DEFAULT_FACTORS,
    PERIOD_MONTH,
    PERIOD_WEEK,
    UNKNOWN,
    ActivityEvent,
    SavedBucket,
    aggregate_hours,
    estimate_saved_minutes,
    minutes_to_hours,
    total_hours,
)


def _event(
    action: str = "rfi_answered",
    module: str = "rfi",
    at: datetime | None = None,
    actor_id: str | None = "user-1",
    project_id: str | None = "proj-1",
    units: int = 1,
) -> ActivityEvent:
    """Build an ActivityEvent with sensible defaults for a single test."""
    return ActivityEvent(
        action=action,
        module=module,
        at=at if at is not None else datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
        actor_id=actor_id,
        project_id=project_id,
        units=units,
    )


# ---------------------------------------------------------------------------
# DEFAULT_FACTORS table
# ---------------------------------------------------------------------------


def test_default_factors_are_conservative_whole_minute_decimals() -> None:
    # Every factor must be a positive Decimal and a whole number of minutes -
    # the table is a documented, defensible minute lookup, not floats.
    assert DEFAULT_FACTORS  # non-empty
    for (module, action), minutes in DEFAULT_FACTORS.items():
        assert isinstance(module, str) and module
        assert isinstance(action, str) and action
        assert isinstance(minutes, Decimal)
        assert minutes > Decimal("0")
        assert minutes == minutes.to_integral_value()


def test_default_factors_cover_the_documented_ai_actions() -> None:
    # The actions the build spec calls out must each carry a seed factor.
    expected = {
        ("rfi", "rfi_answered"),
        ("changeorders", "change_order_logged"),
        ("changeorders", "change_order_updated"),
        ("change_intelligence", "comms_digest_generated"),
        ("change_intelligence", "change_request_clarified"),
        ("claims_evidence", "evidence_pack_assembled"),
        ("ai_estimator", "ai_estimate_produced"),
        ("takeoff", "takeoff_parsed"),
        ("change_intelligence", "delay_detected"),
    }
    assert expected <= set(DEFAULT_FACTORS)


# ---------------------------------------------------------------------------
# estimate_saved_minutes - factor lookup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("module", "action", "expected"),
    [
        ("rfi", "rfi_answered", Decimal("25")),
        ("changeorders", "change_order_logged", Decimal("20")),
        ("changeorders", "change_order_updated", Decimal("10")),
        ("change_intelligence", "comms_digest_generated", Decimal("30")),
        ("change_intelligence", "change_request_clarified", Decimal("15")),
        ("claims_evidence", "evidence_pack_assembled", Decimal("45")),
        ("ai_estimator", "ai_estimate_produced", Decimal("40")),
        ("takeoff", "takeoff_parsed", Decimal("35")),
        ("change_intelligence", "delay_detected", Decimal("20")),
    ],
)
def test_estimate_known_factor(module: str, action: str, expected: Decimal) -> None:
    assert estimate_saved_minutes(action, module) == expected


def test_estimate_unknown_action_is_zero() -> None:
    assert estimate_saved_minutes("danced_a_jig", "rfi") == Decimal("0")


def test_estimate_unknown_module_is_zero() -> None:
    # Known action token but the wrong module -> the (module, action) pair is
    # not in the table, so no saving is invented.
    assert estimate_saved_minutes("rfi_answered", "not_a_module") == Decimal("0")


def test_estimate_unknown_returns_exact_zero_type() -> None:
    result = estimate_saved_minutes("nope", "nope")
    assert isinstance(result, Decimal)
    assert result == Decimal("0")


# ---------------------------------------------------------------------------
# estimate_saved_minutes - units
# ---------------------------------------------------------------------------


def test_estimate_scales_with_units() -> None:
    assert estimate_saved_minutes("rfi_answered", "rfi", units=4) == Decimal("100")


def test_estimate_units_one_is_default() -> None:
    assert estimate_saved_minutes("rfi_answered", "rfi") == estimate_saved_minutes("rfi_answered", "rfi", units=1)


def test_estimate_zero_units_is_zero() -> None:
    assert estimate_saved_minutes("rfi_answered", "rfi", units=0) == Decimal("0")


def test_estimate_negative_units_is_zero() -> None:
    assert estimate_saved_minutes("rfi_answered", "rfi", units=-3) == Decimal("0")


def test_estimate_custom_factor_table() -> None:
    # Callers (the admin-editable table) can override the seed factors.
    custom = {("rfi", "rfi_answered"): Decimal("12")}
    assert estimate_saved_minutes("rfi_answered", "rfi", factors=custom) == Decimal("12")
    # A pair not in the custom table is still zero - no fall-through to defaults.
    assert estimate_saved_minutes("takeoff_parsed", "takeoff", factors=custom) == Decimal("0")


# ---------------------------------------------------------------------------
# minutes_to_hours - rounding
# ---------------------------------------------------------------------------


def test_minutes_to_hours_exact() -> None:
    assert minutes_to_hours(Decimal("60")) == Decimal("1.00")
    assert minutes_to_hours(Decimal("90")) == Decimal("1.50")


def test_minutes_to_hours_rounds_half_up() -> None:
    # 25 minutes = 0.41666.. hours -> 0.42 half-up.
    assert minutes_to_hours(Decimal("25")) == Decimal("0.42")


def test_minutes_to_hours_zero() -> None:
    assert minutes_to_hours(Decimal("0")) == Decimal("0.00")


# ---------------------------------------------------------------------------
# aggregate_hours - by user
# ---------------------------------------------------------------------------


def test_aggregate_by_user_sums_per_actor() -> None:
    rows = [
        _event(actor_id="alice", action="rfi_answered", module="rfi"),  # 25
        _event(actor_id="alice", action="change_order_logged", module="changeorders"),  # 20
        _event(actor_id="bob", action="takeoff_parsed", module="takeoff"),  # 35
    ]
    buckets = aggregate_hours(rows, by=BY_USER)
    by_key = {b.key: b for b in buckets}
    assert set(by_key) == {"alice", "bob"}
    assert by_key["alice"].minutes == Decimal("45")
    assert by_key["alice"].hours == Decimal("0.75")
    assert by_key["alice"].event_count == 2
    assert by_key["bob"].minutes == Decimal("35")
    assert by_key["bob"].hours == Decimal("0.58")  # 35/60 = 0.5833 -> 0.58


def test_aggregate_by_user_missing_actor_is_unknown() -> None:
    rows = [_event(actor_id=None, action="rfi_answered", module="rfi")]
    buckets = aggregate_hours(rows, by=BY_USER)
    assert len(buckets) == 1
    assert buckets[0].key == UNKNOWN


# ---------------------------------------------------------------------------
# aggregate_hours - by project
# ---------------------------------------------------------------------------


def test_aggregate_by_project_sums_per_project() -> None:
    rows = [
        _event(project_id="P1", action="rfi_answered", module="rfi"),  # 25
        _event(project_id="P1", action="rfi_answered", module="rfi"),  # 25
        _event(project_id="P2", action="evidence_pack_assembled", module="claims_evidence"),  # 45
    ]
    buckets = aggregate_hours(rows, by=BY_PROJECT)
    by_key = {b.key: b for b in buckets}
    assert by_key["P1"].minutes == Decimal("50")
    assert by_key["P1"].event_count == 2
    assert by_key["P2"].minutes == Decimal("45")


def test_aggregate_by_project_missing_project_is_unknown() -> None:
    rows = [_event(project_id=None, action="rfi_answered", module="rfi")]
    buckets = aggregate_hours(rows, by=BY_PROJECT)
    assert buckets[0].key == UNKNOWN


# ---------------------------------------------------------------------------
# aggregate_hours - by feature (module/action)
# ---------------------------------------------------------------------------


def test_aggregate_by_feature_groups_module_action() -> None:
    rows = [
        _event(action="rfi_answered", module="rfi"),  # 25
        _event(action="rfi_answered", module="rfi"),  # 25
        _event(action="change_order_logged", module="changeorders"),  # 20
    ]
    buckets = aggregate_hours(rows, by=BY_FEATURE)
    by_key = {b.key: b for b in buckets}
    assert set(by_key) == {"rfi/rfi_answered", "changeorders/change_order_logged"}
    assert by_key["rfi/rfi_answered"].minutes == Decimal("50")
    assert by_key["rfi/rfi_answered"].unit_count == 2
    assert by_key["changeorders/change_order_logged"].minutes == Decimal("20")


def test_aggregate_counts_zero_factor_rows_in_denominator() -> None:
    # An unrecognised action saves no minutes but still counts as an event /
    # unit, so the saved-hours figure is honest about how much work happened.
    rows = [
        _event(action="rfi_answered", module="rfi"),  # 25 min
        _event(action="logged_in", module="auth"),  # 0 min, unknown
    ]
    buckets = aggregate_hours(rows, by=BY_FEATURE)
    by_key = {b.key: b for b in buckets}
    assert by_key["auth/logged_in"].minutes == Decimal("0")
    assert by_key["auth/logged_in"].event_count == 1
    assert by_key["auth/logged_in"].unit_count == 1
    assert by_key["auth/logged_in"].hours == Decimal("0.00")


def test_aggregate_unit_count_respects_units() -> None:
    rows = [_event(action="rfi_answered", module="rfi", units=5)]
    buckets = aggregate_hours(rows, by=BY_FEATURE)
    assert buckets[0].unit_count == 5
    assert buckets[0].minutes == Decimal("125")  # 25 * 5


# ---------------------------------------------------------------------------
# aggregate_hours - by period (weekly / monthly bucketing)
# ---------------------------------------------------------------------------


def test_aggregate_by_period_week_buckets_by_iso_week() -> None:
    rows = [
        # 2026-06-22 is a Monday in ISO week 26; 06-25 is the Thursday of the
        # same week; 06-29 is the Monday of week 27.
        _event(at=datetime(2026, 6, 22, 9, 0, tzinfo=UTC), action="rfi_answered", module="rfi"),
        _event(at=datetime(2026, 6, 25, 9, 0, tzinfo=UTC), action="rfi_answered", module="rfi"),
        _event(at=datetime(2026, 6, 29, 9, 0, tzinfo=UTC), action="rfi_answered", module="rfi"),
    ]
    buckets = aggregate_hours(rows, by=BY_PERIOD, period=PERIOD_WEEK)
    by_key = {b.key: b for b in buckets}
    assert set(by_key) == {"2026-W26", "2026-W27"}
    assert by_key["2026-W26"].event_count == 2
    assert by_key["2026-W26"].minutes == Decimal("50")
    assert by_key["2026-W27"].event_count == 1


def test_aggregate_by_period_week_handles_year_boundary() -> None:
    # 2026-12-31 falls in ISO week 53 of 2026; 2027-01-01 stays in the same
    # ISO week, which belongs to ISO year 2026 - the isocalendar year, not the
    # calendar year, keeps them together.
    rows = [
        _event(at=datetime(2026, 12, 31, 9, 0, tzinfo=UTC), action="rfi_answered", module="rfi"),
        _event(at=datetime(2027, 1, 1, 9, 0, tzinfo=UTC), action="rfi_answered", module="rfi"),
    ]
    buckets = aggregate_hours(rows, by=BY_PERIOD, period=PERIOD_WEEK)
    assert len(buckets) == 1
    assert buckets[0].key == "2026-W53"
    assert buckets[0].event_count == 2


def test_aggregate_by_period_month_buckets_by_calendar_month() -> None:
    rows = [
        _event(at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC), action="rfi_answered", module="rfi"),
        _event(at=datetime(2026, 6, 30, 9, 0, tzinfo=UTC), action="rfi_answered", module="rfi"),
        _event(at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC), action="rfi_answered", module="rfi"),
    ]
    buckets = aggregate_hours(rows, by=BY_PERIOD, period=PERIOD_MONTH)
    by_key = {b.key: b for b in buckets}
    assert set(by_key) == {"2026-06", "2026-07"}
    assert by_key["2026-06"].event_count == 2
    assert by_key["2026-07"].event_count == 1


def test_aggregate_by_period_requires_granularity() -> None:
    rows = [_event()]
    with pytest.raises(ValueError):
        aggregate_hours(rows, by=BY_PERIOD)


def test_aggregate_by_period_rejects_unknown_granularity() -> None:
    rows = [_event()]
    with pytest.raises(ValueError):
        aggregate_hours(rows, by=BY_PERIOD, period="fortnight")


# ---------------------------------------------------------------------------
# aggregate_hours - sort order, empty input, validation
# ---------------------------------------------------------------------------


def test_aggregate_sorted_by_hours_desc_then_key() -> None:
    rows = [
        _event(actor_id="low", action="change_order_updated", module="changeorders"),  # 10
        _event(actor_id="high", action="evidence_pack_assembled", module="claims_evidence"),  # 45
        _event(actor_id="mid", action="rfi_answered", module="rfi"),  # 25
    ]
    buckets = aggregate_hours(rows, by=BY_USER)
    assert [b.key for b in buckets] == ["high", "mid", "low"]


def test_aggregate_sort_tie_break_on_key_ascending() -> None:
    # Two users with identical savings -> ascending key breaks the tie.
    rows = [
        _event(actor_id="zoe", action="rfi_answered", module="rfi"),  # 25
        _event(actor_id="amy", action="rfi_answered", module="rfi"),  # 25
    ]
    buckets = aggregate_hours(rows, by=BY_USER)
    assert [b.key for b in buckets] == ["amy", "zoe"]


def test_aggregate_empty_input_returns_empty_tuple() -> None:
    assert aggregate_hours([], by=BY_USER) == ()
    assert aggregate_hours([], by=BY_PERIOD, period=PERIOD_WEEK) == ()


def test_aggregate_rejects_unknown_axis() -> None:
    rows = [_event()]
    with pytest.raises(ValueError):
        aggregate_hours(rows, by="team")


def test_aggregate_returns_saved_bucket_instances() -> None:
    buckets = aggregate_hours([_event()], by=BY_USER)
    assert all(isinstance(b, SavedBucket) for b in buckets)


# ---------------------------------------------------------------------------
# total_hours
# ---------------------------------------------------------------------------


def test_total_hours_sums_all_rows() -> None:
    rows = [
        _event(action="rfi_answered", module="rfi"),  # 25
        _event(action="change_order_logged", module="changeorders"),  # 20
        _event(action="takeoff_parsed", module="takeoff"),  # 35
    ]
    # 80 minutes -> 1.33 hours half-up.
    assert total_hours(rows) == Decimal("1.33")


def test_total_hours_ignores_unknown_actions() -> None:
    rows = [
        _event(action="rfi_answered", module="rfi"),  # 25
        _event(action="logged_in", module="auth"),  # 0
    ]
    assert total_hours(rows) == minutes_to_hours(Decimal("25"))


def test_total_hours_empty_is_zero() -> None:
    assert total_hours([]) == Decimal("0.00")


def test_total_hours_reconciles_with_bucket_minutes() -> None:
    # The headline total converts the summed minutes once; it must equal the
    # conversion of the summed per-bucket minutes (no double-rounding drift).
    rows = [
        _event(actor_id="a", action="rfi_answered", module="rfi"),  # 25
        _event(actor_id="b", action="rfi_answered", module="rfi"),  # 25
        _event(actor_id="c", action="rfi_answered", module="rfi"),  # 25
    ]
    buckets = aggregate_hours(rows, by=BY_USER)
    summed_minutes = sum((b.minutes for b in buckets), Decimal("0"))
    assert total_hours(rows) == minutes_to_hours(summed_minutes)
