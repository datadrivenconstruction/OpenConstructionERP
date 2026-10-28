# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the pure interference risk matrix.

Exercises :mod:`app.modules.clash.risk_matrix` with plain values only - no
database, no ORM, no session. Covers overlap classification, the imminent /
upcoming / no-overlap / no-schedule-data split, closed-clash exclusion,
risk-score ordering, Decimal exactness on money, and a spread of date-input
shapes and edge cases.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.modules.clash.risk_matrix import (
    STATUS_IMMINENT,
    STATUS_NO_OVERLAP,
    STATUS_NO_SCHEDULE_DATA,
    STATUS_UPCOMING,
    ClashRiskRecord,
    ClashScheduleFacts,
    assess_clash,
    build_interference_risk_matrix,
    is_open_status,
)

TODAY = date(2026, 7, 16)


def _facts(
    clash_id: str = "c1",
    *,
    severity: str = "high",
    cost: str = "1000",
    trade_a: str = "structural",
    trade_b: str = "mechanical",
    windows_a=(("2026-07-16", "2026-07-20"),),
    windows_b=(("2026-07-18", "2026-07-25"),),
    status: str = "new",
) -> ClashScheduleFacts:
    return ClashScheduleFacts(
        clash_id=clash_id,
        severity=severity,
        cost_impact=Decimal(cost),
        trade_a=trade_a,
        trade_b=trade_b,
        activity_windows_a=windows_a,
        activity_windows_b=windows_b,
        status=status,
    )


# ── Overlap classification ───────────────────────────────────────────────────


def test_overlapping_windows_flag_imminent() -> None:
    rec = assess_clash(_facts(), today=TODAY)
    assert rec.overlaps is True
    assert rec.status == STATUS_IMMINENT
    # max(07-16,07-18)=07-18 .. min(07-20,07-25)=07-20 -> 2 days overlap.
    assert rec.overlap_days == 2
    # Shared window opens 07-18, two days after today.
    assert rec.days_until_overlap == 2
    assert rec.gap_days is None
    assert rec.risk_score > Decimal("0")


def test_disjoint_windows_are_no_overlap() -> None:
    rec = assess_clash(
        _facts(windows_a=(("2026-07-16", "2026-07-20"),), windows_b=(("2026-08-01", "2026-08-10"),)),
        today=TODAY,
    )
    assert rec.overlaps is False
    assert rec.status == STATUS_NO_OVERLAP
    assert rec.days_until_overlap is None
    # 07-20 -> 08-01 is 12 days apart.
    assert rec.gap_days == 12
    assert rec.overlap_days == 0


def test_missing_schedule_data_on_either_side() -> None:
    only_a = assess_clash(_facts(windows_a=(("2026-07-16", "2026-07-20"),), windows_b=()), today=TODAY)
    only_b = assess_clash(_facts(windows_a=(), windows_b=(("2026-07-16", "2026-07-20"),)), today=TODAY)
    neither = assess_clash(_facts(windows_a=(), windows_b=()), today=TODAY)
    for rec in (only_a, only_b, neither):
        assert rec.status == STATUS_NO_SCHEDULE_DATA
        assert rec.overlaps is False
        assert rec.days_until_overlap is None
        assert rec.gap_days is None


def test_far_future_overlap_is_upcoming() -> None:
    rec = assess_clash(
        _facts(windows_a=(("2026-09-01", "2026-09-10"),), windows_b=(("2026-09-05", "2026-09-15"),)),
        today=TODAY,
    )
    assert rec.overlaps is True
    assert rec.status == STATUS_UPCOMING  # 51 days out, beyond the 30-day horizon
    assert rec.days_until_overlap == 51
    assert rec.overlap_days == 5


def test_touching_boundary_counts_as_overlap() -> None:
    # A ends the same day B starts - both trades share the site that day.
    rec = assess_clash(
        _facts(windows_a=(("2026-07-16", "2026-07-20"),), windows_b=(("2026-07-20", "2026-07-25"),)),
        today=TODAY,
    )
    assert rec.overlaps is True
    assert rec.overlap_days == 0
    assert rec.status == STATUS_IMMINENT


def test_overlap_already_in_progress_has_negative_days_until() -> None:
    # Shared window opened before today; still an open clash -> imminent.
    rec = assess_clash(
        _facts(windows_a=(("2026-07-01", "2026-07-31"),), windows_b=(("2026-07-05", "2026-07-20"),)),
        today=TODAY,
    )
    assert rec.status == STATUS_IMMINENT
    assert rec.days_until_overlap is not None
    assert rec.days_until_overlap < 0  # opened 2026-07-05, before today


def test_horizon_boundary_is_inclusive() -> None:
    # Overlap opening exactly `horizon` days out is imminent; one more is upcoming.
    at = assess_clash(
        _facts(windows_a=(("2026-08-15", "2026-08-20"),), windows_b=(("2026-08-15", "2026-08-20"),)),
        today=TODAY,
        imminent_within_days=30,
    )
    assert at.days_until_overlap == 30
    assert at.status == STATUS_IMMINENT
    beyond = assess_clash(
        _facts(windows_a=(("2026-08-16", "2026-08-20"),), windows_b=(("2026-08-16", "2026-08-20"),)),
        today=TODAY,
        imminent_within_days=30,
    )
    assert beyond.days_until_overlap == 31
    assert beyond.status == STATUS_UPCOMING


def test_multiple_windows_pick_closest_approach() -> None:
    # Trade A has two windows; the second overlaps trade B even though the
    # first does not. The correlation must find the overlap.
    rec = assess_clash(
        _facts(
            windows_a=(("2026-07-16", "2026-07-18"), ("2026-08-01", "2026-08-10")),
            windows_b=(("2026-08-05", "2026-08-12"),),
        ),
        today=TODAY,
    )
    assert rec.overlaps is True
    assert rec.overlap_days == 5  # 08-05 .. 08-10


# ── Date-input shapes ────────────────────────────────────────────────────────


def test_accepts_date_and_datetime_objects() -> None:
    rec = assess_clash(
        _facts(
            windows_a=((date(2026, 7, 16), date(2026, 7, 20)),),
            windows_b=((datetime(2026, 7, 18, 9, 0), datetime(2026, 7, 25, 17, 0)),),
        ),
        today=TODAY,
    )
    assert rec.overlaps is True
    assert rec.overlap_days == 2


def test_unparseable_window_is_dropped() -> None:
    # The only B window is junk -> B has no usable window -> no-schedule-data.
    rec = assess_clash(
        _facts(windows_a=(("2026-07-16", "2026-07-20"),), windows_b=(("not-a-date", ""),)),
        today=TODAY,
    )
    assert rec.status == STATUS_NO_SCHEDULE_DATA


def test_backwards_window_is_normalised() -> None:
    # End before start on A - defensively swapped, still overlaps B.
    rec = assess_clash(
        _facts(windows_a=(("2026-07-20", "2026-07-16"),), windows_b=(("2026-07-18", "2026-07-25"),)),
        today=TODAY,
    )
    assert rec.overlaps is True
    assert rec.window_a == (date(2026, 7, 16), date(2026, 7, 20))


# ── Status filtering ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["new", "active", "reviewed", "persisted"])
def test_open_statuses_are_included(status: str) -> None:
    out = build_interference_risk_matrix([_facts(status=status)], today=TODAY)
    assert len(out) == 1


@pytest.mark.parametrize("status", ["resolved", "approved", "ignored", "archived", "closed"])
def test_closed_statuses_are_excluded(status: str) -> None:
    out = build_interference_risk_matrix([_facts(status=status)], today=TODAY)
    assert out == []


def test_mixed_open_and_closed_only_keeps_open() -> None:
    facts = [
        _facts("open1", status="new"),
        _facts("closed1", status="resolved"),
        _facts("open2", status="reviewed"),
        _facts("closed2", status="ignored"),
    ]
    out = build_interference_risk_matrix(facts, today=TODAY)
    assert {r.clash_id for r in out} == {"open1", "open2"}


def test_is_open_status_helper() -> None:
    assert is_open_status("NEW") is True
    assert is_open_status(" reviewed ") is True
    assert is_open_status("resolved") is False
    assert is_open_status(None) is False


# ── Risk-score ordering ──────────────────────────────────────────────────────


def test_higher_severity_ranks_first() -> None:
    facts = [
        _facts("low", severity="low"),
        _facts("critical", severity="critical"),
        _facts("medium", severity="medium"),
        _facts("high", severity="high"),
    ]
    out = build_interference_risk_matrix(facts, today=TODAY)
    assert [r.clash_id for r in out] == ["critical", "high", "medium", "low"]


def test_higher_cost_ranks_first_at_equal_severity() -> None:
    facts = [
        _facts("cheap", cost="100"),
        _facts("dear", cost="9000"),
        _facts("mid", cost="1500"),
    ]
    out = build_interference_risk_matrix(facts, today=TODAY)
    assert [r.clash_id for r in out] == ["dear", "mid", "cheap"]


def test_sooner_overlap_ranks_above_later_at_equal_severity_and_cost() -> None:
    imminent = _facts(
        "soon",
        windows_a=(("2026-07-16", "2026-07-20"),),
        windows_b=(("2026-07-16", "2026-07-20"),),
    )
    upcoming = _facts(
        "later",
        windows_a=(("2026-09-01", "2026-09-10"),),
        windows_b=(("2026-09-05", "2026-09-15"),),
    )
    out = build_interference_risk_matrix([upcoming, imminent], today=TODAY)
    assert [r.clash_id for r in out] == ["soon", "later"]
    assert out[0].risk_score > out[1].risk_score


def test_overlap_outranks_no_overlap_outranks_no_data() -> None:
    # Same severity + cost; only the schedule relationship differs.
    overlap = _facts(
        "overlap",
        windows_a=(("2026-07-16", "2026-07-20"),),
        windows_b=(("2026-07-16", "2026-07-20"),),
    )
    near_miss = _facts(
        "near_miss",
        windows_a=(("2026-07-16", "2026-07-20"),),
        windows_b=(("2026-07-22", "2026-07-25"),),
    )
    blind = _facts("blind", windows_a=(("2026-07-16", "2026-07-20"),), windows_b=())
    out = build_interference_risk_matrix([blind, near_miss, overlap], today=TODAY)
    assert [r.clash_id for r in out] == ["overlap", "near_miss", "blind"]


def test_unknown_severity_uses_lowest_weight() -> None:
    known_low = assess_clash(_facts("low", severity="low"), today=TODAY)
    unknown = assess_clash(_facts("weird", severity="banana"), today=TODAY)
    # Unknown falls back to the low weight - identical everything else.
    assert unknown.risk_score == known_low.risk_score


def test_deterministic_tie_break_by_clash_id() -> None:
    # Two clashes identical in every scoring dimension - id breaks the tie ascending.
    a = _facts("bbb")
    b = _facts("aaa")
    out = build_interference_risk_matrix([a, b], today=TODAY)
    assert [r.clash_id for r in out] == ["aaa", "bbb"]


def test_explicit_score_value() -> None:
    # critical (weight 4) x cost 100 x proximity 1.0 (overlap open today) = 400.
    rec = assess_clash(
        _facts(
            severity="critical",
            cost="100",
            windows_a=(("2026-07-16", "2026-07-20"),),
            windows_b=(("2026-07-16", "2026-07-20"),),
        ),
        today=TODAY,
    )
    assert rec.days_until_overlap == 0
    assert rec.risk_score == Decimal("400.0000")


# ── Money / Decimal exactness ────────────────────────────────────────────────


def test_cost_impact_echoed_exactly_as_decimal() -> None:
    rec = assess_clash(_facts(cost="1234.5678"), today=TODAY)
    assert isinstance(rec.cost_impact, Decimal)
    assert rec.cost_impact == Decimal("1234.5678")
    # No binary-float drift on the way through.
    assert str(rec.cost_impact) == "1234.5678"


def test_float_cost_does_not_pick_up_binary_noise() -> None:
    facts = ClashScheduleFacts(
        clash_id="f",
        severity="high",
        cost_impact=0.1,  # deliberately a float
        trade_a="a",
        trade_b="b",
        activity_windows_a=(("2026-07-16", "2026-07-20"),),
        activity_windows_b=(("2026-07-18", "2026-07-25"),),
    )
    rec = assess_clash(facts, today=TODAY)
    assert rec.cost_impact == Decimal("0.1")


def test_risk_score_is_decimal() -> None:
    rec = assess_clash(_facts(), today=TODAY)
    assert isinstance(rec.risk_score, Decimal)


def test_zero_cost_yields_zero_score() -> None:
    rec = assess_clash(_facts(cost="0"), today=TODAY)
    assert rec.risk_score == Decimal("0.0000")


# ── Shape / misc ─────────────────────────────────────────────────────────────


def test_empty_input_returns_empty_list() -> None:
    assert build_interference_risk_matrix([], today=TODAY) == []


def test_record_type_and_fields() -> None:
    rec = assess_clash(_facts(), today=TODAY)
    assert isinstance(rec, ClashRiskRecord)
    assert rec.trade_a == "structural"
    assert rec.trade_b == "mechanical"
    assert rec.window_a == (date(2026, 7, 16), date(2026, 7, 20))
    assert rec.explanation  # non-empty human sentence


def test_explanation_has_no_long_dashes() -> None:
    # Explanations are user-facing prose; the house style bans em / en dashes.
    # Build the banned characters via chr() so this file stays clean too.
    banned = {chr(0x2014), chr(0x2013), chr(0x2012), chr(0x2015)}
    for windows_a, windows_b in (
        (("2026-07-16", "2026-07-20"), ("2026-07-18", "2026-07-25")),  # overlap
        (("2026-07-16", "2026-07-20"), ("2026-08-01", "2026-08-10")),  # no-overlap
        (("2026-07-16", "2026-07-20"), ()),  # no-schedule-data
    ):
        rec = assess_clash(_facts(windows_a=(windows_a,), windows_b=(windows_b,) if windows_b else ()), today=TODAY)
        assert not banned.intersection(rec.explanation)


def test_horizon_clamped_to_at_least_one() -> None:
    # A zero / negative horizon must not divide by zero; it clamps to 1.
    rec = assess_clash(_facts(), today=TODAY, imminent_within_days=0)
    assert rec.risk_score >= Decimal("0")
