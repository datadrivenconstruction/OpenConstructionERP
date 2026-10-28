"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the leading vs lagging safety indicators rollup.

Scope:
    Pure-logic coverage of :mod:`app.modules.safety.safety_indicators`: the
    guarded frequency rates (TRIR/LTIFR/severity) and corrective-action close
    rate, counts, multi-record aggregation, period filtering, and Decimal
    exactness. Plus one check that the response schema emits Decimal rates as
    plain strings. No database, no app lifespan, no I/O.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.safety import safety_indicators as si

# ---------------------------------------------------------------------------
# Small builders keep each test focused on the fields under assertion.
# ---------------------------------------------------------------------------


def _incident(
    *,
    recordable: bool = False,
    lost_time: bool = False,
    days_lost: int = 0,
    man_hours: str = "0",
    incident_type: str = "injury",
    on_date: date | None = None,
    corrective_action_statuses: tuple[str, ...] = (),
) -> si.IncidentInput:
    return si.IncidentInput(
        recordable=recordable,
        lost_time=lost_time,
        days_lost=days_lost,
        man_hours=Decimal(man_hours),
        incident_type=incident_type,
        on_date=on_date,
        corrective_action_statuses=corrective_action_statuses,
    )


def _observation(
    *,
    status: str = "open",
    observation_type: str = "unsafe_act",
    on_date: date | None = None,
) -> si.ObservationInput:
    return si.ObservationInput(status=status, observation_type=observation_type, on_date=on_date)


# ---------------------------------------------------------------------------
# Empty
# ---------------------------------------------------------------------------


def test_empty_rollup_is_all_zero_and_rates_none() -> None:
    result = si.compute_safety_indicators([], [])

    lagging = result.lagging
    assert lagging.total_incidents == 0
    assert lagging.recordable_incidents == 0
    assert lagging.lost_time_incidents == 0
    assert lagging.total_days_lost == 0
    assert lagging.total_hours_worked == Decimal("0")
    assert lagging.trir is None
    assert lagging.ltifr is None
    assert lagging.severity_rate is None

    leading = result.leading
    assert leading.near_misses_reported == 0
    assert leading.observations_total == 0
    assert leading.observations_open == 0
    assert leading.observations_closed == 0
    assert leading.corrective_actions_total == 0
    assert leading.corrective_action_close_rate is None


# ---------------------------------------------------------------------------
# Guarded frequency rates
# ---------------------------------------------------------------------------


def test_frequency_rate_zero_hours_returns_none() -> None:
    assert si.frequency_rate(5, Decimal("0"), si.TRIR_BASE_HOURS) is None


def test_frequency_rate_negative_hours_returns_none() -> None:
    assert si.frequency_rate(5, Decimal("-100"), si.TRIR_BASE_HOURS) is None


def test_frequency_rate_zero_count_is_zero_not_none() -> None:
    # Zero incidents with real exposure hours is a genuine 0.00 rate, not the
    # "no data" None case.
    rate = si.frequency_rate(0, Decimal("200000"), si.TRIR_BASE_HOURS)
    assert rate == Decimal("0.00")
    assert str(rate) == "0.00"


def test_zero_hours_guard_in_rollup_keeps_counts_but_null_rates() -> None:
    incidents = [
        _incident(recordable=True, lost_time=True, days_lost=4, man_hours="0"),
        _incident(recordable=True, man_hours="0"),
    ]
    result = si.compute_safety_indicators(incidents, [])

    assert result.lagging.recordable_incidents == 2
    assert result.lagging.lost_time_incidents == 1
    assert result.lagging.total_days_lost == 4
    assert result.lagging.total_hours_worked == Decimal("0")
    # No exposure hours -> every rate is guarded to None, never a crash.
    assert result.lagging.trir is None
    assert result.lagging.ltifr is None
    assert result.lagging.severity_rate is None


# ---------------------------------------------------------------------------
# Standard rate formula exactness (Decimal)
# ---------------------------------------------------------------------------


def test_trir_formula_exact() -> None:
    # TRIR = recordable * 200000 / hours = 3 * 200000 / 600000 = 1.00
    incidents = [_incident(recordable=True, man_hours="200000") for _ in range(3)]
    result = si.compute_safety_indicators(incidents, [])
    assert result.lagging.total_hours_worked == Decimal("600000")
    assert result.lagging.trir == Decimal("1.00")
    assert str(result.lagging.trir) == "1.00"
    assert isinstance(result.lagging.trir, Decimal)


def test_ltifr_formula_exact() -> None:
    # LTIFR = lost_time * 1000000 / hours = 2 * 1000000 / 500000 = 4.00
    incidents = [
        _incident(lost_time=True, days_lost=1, man_hours="250000"),
        _incident(lost_time=True, days_lost=1, man_hours="250000"),
    ]
    result = si.compute_safety_indicators(incidents, [])
    assert result.lagging.total_hours_worked == Decimal("500000")
    assert result.lagging.ltifr == Decimal("4.00")
    assert str(result.lagging.ltifr) == "4.00"


def test_severity_rate_formula_exact() -> None:
    # severity = days_lost * 1000000 / hours = 10 * 1000000 / 1000000 = 10.00
    incidents = [_incident(lost_time=True, days_lost=10, man_hours="1000000")]
    result = si.compute_safety_indicators(incidents, [])
    assert result.lagging.severity_rate == Decimal("10.00")
    assert str(result.lagging.severity_rate) == "10.00"


def test_frequency_rate_rounds_half_up_to_two_decimals() -> None:
    # 1 * 200000 / 700000 = 0.285714... -> 0.29 at two decimals.
    rate = si.frequency_rate(1, Decimal("700000"), si.TRIR_BASE_HOURS)
    assert str(rate) == "0.29"


# ---------------------------------------------------------------------------
# Corrective-action close rate
# ---------------------------------------------------------------------------


def test_close_rate_basic_ratio() -> None:
    rate = si.close_rate(3, 4)
    assert rate == Decimal("0.7500")
    assert str(rate) == "0.7500"


def test_close_rate_zero_total_is_none() -> None:
    assert si.close_rate(0, 0) is None


def test_close_rate_all_open_is_zero_ratio() -> None:
    rate = si.close_rate(0, 3)
    assert rate == Decimal("0.0000")
    assert str(rate) == "0.0000"


def test_rollup_close_rate_zero_applicable_guard() -> None:
    # Incidents exist but none carry corrective actions -> close rate None.
    incidents = [_incident(recordable=True, man_hours="100000")]
    result = si.compute_safety_indicators(incidents, [])
    assert result.leading.corrective_actions_total == 0
    assert result.leading.corrective_action_close_rate is None


def test_rollup_close_rate_from_incident_actions() -> None:
    incidents = [
        _incident(corrective_action_statuses=("completed", "open")),
        _incident(corrective_action_statuses=("in_progress", "completed")),
    ]
    result = si.compute_safety_indicators(incidents, [])
    assert result.leading.corrective_actions_total == 4
    assert result.leading.corrective_actions_open == 2  # open + in_progress
    assert result.leading.corrective_actions_closed == 2  # two completed
    assert result.leading.corrective_action_close_rate == Decimal("0.5000")


def test_close_rate_denominator_includes_unrecognized_status() -> None:
    # An out-of-vocabulary status still counts toward the total (denominator)
    # but is neither open nor closed, so it lowers the close rate honestly.
    incidents = [_incident(corrective_action_statuses=("completed", "unknown_status"))]
    result = si.compute_safety_indicators(incidents, [])
    assert result.leading.corrective_actions_total == 2
    assert result.leading.corrective_actions_closed == 1
    assert result.leading.corrective_actions_open == 0
    assert result.leading.corrective_action_close_rate == Decimal("0.5000")


# ---------------------------------------------------------------------------
# Counts and near-miss handling
# ---------------------------------------------------------------------------


def test_counts_multi_record() -> None:
    incidents = [
        _incident(recordable=True, lost_time=True, days_lost=3, incident_type="injury"),
        _incident(recordable=True, incident_type="injury"),
        _incident(incident_type="near_miss"),
        _incident(incident_type="property_damage"),
    ]
    observations = [
        _observation(status="open"),
        _observation(status="in_progress"),
        _observation(status="closed"),
        _observation(status="closed", observation_type="near_miss"),
    ]
    result = si.compute_safety_indicators(incidents, observations)

    assert result.lagging.total_incidents == 4
    assert result.lagging.recordable_incidents == 2
    assert result.lagging.lost_time_incidents == 1
    assert result.lagging.total_days_lost == 3

    assert result.leading.observations_total == 4
    assert result.leading.observations_open == 2
    assert result.leading.observations_closed == 2
    # One near-miss incident + one near-miss observation.
    assert result.leading.near_misses_reported == 2


def test_near_miss_incident_does_not_enter_rate_numerator() -> None:
    # A near-miss (no injury) is recordable=False/lost_time=False, so with
    # exposure hours present it must not inflate TRIR/LTIFR.
    incidents = [
        _incident(recordable=True, man_hours="100000"),
        _incident(incident_type="near_miss", man_hours="100000"),
    ]
    result = si.compute_safety_indicators(incidents, [])
    assert result.lagging.total_incidents == 2
    assert result.lagging.recordable_incidents == 1
    # TRIR = 1 * 200000 / 200000 = 1.00 (near-miss excluded from numerator).
    assert result.lagging.trir == Decimal("1.00")
    assert result.lagging.ltifr == Decimal("0.00")
    assert result.leading.near_misses_reported == 1


# ---------------------------------------------------------------------------
# Multi-record aggregation and Decimal exactness of the hours sum
# ---------------------------------------------------------------------------


def test_hours_sum_is_exact_decimal() -> None:
    incidents = [
        _incident(recordable=True, man_hours="100.50"),
        _incident(man_hours="200.25"),
    ]
    result = si.compute_safety_indicators(incidents, [])
    # Exact Decimal addition, no float drift.
    assert result.lagging.total_hours_worked == Decimal("300.75")


def test_multi_record_rollup_rates_over_totals() -> None:
    incidents = [
        _incident(recordable=True, lost_time=True, days_lost=2, man_hours="400000"),
        _incident(recordable=True, man_hours="400000"),
        _incident(incident_type="near_miss", man_hours="200000"),
    ]
    result = si.compute_safety_indicators(incidents, [])
    # Totals: recordable=2, lost_time=1, hours=1,000,000.
    assert result.lagging.total_hours_worked == Decimal("1000000")
    # TRIR = 2 * 200000 / 1000000 = 0.40
    assert result.lagging.trir == Decimal("0.40")
    # LTIFR = 1 * 1000000 / 1000000 = 1.00
    assert result.lagging.ltifr == Decimal("1.00")
    # severity = 2 * 1000000 / 1000000 = 2.00
    assert result.lagging.severity_rate == Decimal("2.00")


# ---------------------------------------------------------------------------
# Period filtering (inclusive window, undated handling)
# ---------------------------------------------------------------------------


def test_period_filter_excludes_out_of_window() -> None:
    incidents = [
        _incident(recordable=True, man_hours="100000", on_date=date(2026, 3, 15)),
        _incident(recordable=True, man_hours="100000", on_date=date(2025, 12, 31)),
    ]
    result = si.compute_safety_indicators(
        incidents,
        [],
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
    )
    assert result.lagging.total_incidents == 1
    assert result.lagging.recordable_incidents == 1
    assert result.lagging.total_hours_worked == Decimal("100000")
    assert result.period_start == date(2026, 1, 1)
    assert result.period_end == date(2026, 6, 30)


def test_period_filter_inclusive_bounds() -> None:
    incidents = [
        _incident(on_date=date(2026, 1, 1)),
        _incident(on_date=date(2026, 6, 30)),
    ]
    result = si.compute_safety_indicators(
        incidents,
        [],
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
    )
    assert result.lagging.total_incidents == 2


def test_period_filter_undated_excluded_when_window_set() -> None:
    incidents = [_incident(on_date=None), _incident(on_date=date(2026, 3, 1))]
    result = si.compute_safety_indicators(incidents, [], period_start=date(2026, 1, 1))
    assert result.lagging.total_incidents == 1


def test_no_window_includes_undated_records() -> None:
    incidents = [_incident(on_date=None), _incident(on_date=date(2026, 3, 1))]
    result = si.compute_safety_indicators(incidents, [])
    assert result.lagging.total_incidents == 2


def test_corrective_actions_only_from_in_period_incidents() -> None:
    incidents = [
        _incident(on_date=date(2026, 3, 1), corrective_action_statuses=("completed", "open")),
        _incident(on_date=date(2025, 1, 1), corrective_action_statuses=("completed", "completed")),
    ]
    result = si.compute_safety_indicators(
        incidents,
        [],
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
    )
    # Only the in-period incident's two actions count.
    assert result.leading.corrective_actions_total == 2
    assert result.leading.corrective_actions_closed == 1
    assert result.leading.corrective_action_close_rate == Decimal("0.5000")


def test_observation_period_filter_uses_observation_date() -> None:
    observations = [
        _observation(status="closed", on_date=date(2026, 2, 1)),
        _observation(status="open", on_date=date(2027, 2, 1)),
    ]
    result = si.compute_safety_indicators(
        [],
        observations,
        period_end=date(2026, 12, 31),
    )
    assert result.leading.observations_total == 1
    assert result.leading.observations_closed == 1


# ---------------------------------------------------------------------------
# Response schema serialises Decimal rates as strings
# ---------------------------------------------------------------------------


def test_response_schema_emits_rates_as_strings() -> None:
    from uuid import uuid4

    from app.modules.safety.schemas import (
        LaggingIndicatorsResponse,
        LeadingIndicatorsResponse,
        SafetyIndicatorsResponse,
    )

    response = SafetyIndicatorsResponse(
        project_id=uuid4(),
        lagging=LaggingIndicatorsResponse(
            total_hours_worked=Decimal("600000"),
            trir=Decimal("1.00"),
            ltifr=None,
            severity_rate=Decimal("2.50"),
        ),
        leading=LeadingIndicatorsResponse(corrective_action_close_rate=Decimal("0.7500")),
    )
    dumped = response.model_dump(mode="json")
    assert dumped["lagging"]["trir"] == "1.00"
    assert dumped["lagging"]["ltifr"] is None
    assert dumped["lagging"]["severity_rate"] == "2.50"
    assert dumped["lagging"]["total_hours_worked"] == "600000"
    assert dumped["leading"]["corrective_action_close_rate"] == "0.7500"
