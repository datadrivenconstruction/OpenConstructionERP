# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure contractual notice / time-bar engine (runs on py3.11).

Covers the period config lookup, standard normalisation, clause labels, date
parsing, deadline derivation, status classification, the entitlement-at-risk
proof gating, and the register roll-up / ordering. No database, no app stack.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.change_intelligence.time_bar import (
    DEFAULT_DUE_SOON_DAYS,
    GENERIC_PERIODS,
    NOTICE_CLAIM,
    NOTICE_QUOTATION,
    STANDARD_AIA,
    STANDARD_CONSENSUSDOCS,
    STANDARD_FIDIC,
    STANDARD_JCT,
    STANDARD_NEC,
    STANDARD_UNKNOWN,
    STATUS_DUE_SOON,
    STATUS_MET,
    STATUS_OVERDUE,
    STATUS_UNKNOWN,
    STATUS_UPCOMING,
    ClockInput,
    add_days,
    build_clock,
    build_register,
    classify_status,
    clause_ref_for,
    derive_deadline,
    entitlement_at_risk,
    normalize_standard,
    parse_date,
    period_for,
    sort_register,
    summarize_register,
)

NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


def _input(
    *,
    source_kind: str = "variation_request",
    source_id: str = "1",
    source_ref: str = "VR-1",
    title: str = "Item",
    standard: str = STANDARD_FIDIC,
    notice_type: str = NOTICE_CLAIM,
    clause_ref: str = "FIDIC 20.1",
    trigger_date: datetime | None = None,
    explicit_due: datetime | None = None,
    period_days: int | None = 28,
    satisfied_at: datetime | None = None,
    requires_notice: bool = True,
    proof_on_file: bool = True,
    is_open: bool = True,
) -> ClockInput:
    return ClockInput(
        source_kind=source_kind,
        source_id=source_id,
        source_ref=source_ref,
        title=title,
        standard=standard,
        notice_type=notice_type,
        clause_ref=clause_ref,
        trigger_date=trigger_date,
        explicit_due=explicit_due,
        period_days=period_days,
        satisfied_at=satisfied_at,
        requires_notice=requires_notice,
        proof_on_file=proof_on_file,
        is_open=is_open,
    )


# --- normalize_standard ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("FIDIC", STANDARD_FIDIC),
        ("fidic_red_1999", STANDARD_FIDIC),
        ("NEC4 ECC Option A", STANDARD_NEC),
        ("nec3", STANDARD_NEC),
        ("JCT Standard 2016", STANDARD_JCT),
        ("AIA A201-2017", STANDARD_AIA),
        ("ConsensusDocs 200", STANDARD_CONSENSUSDOCS),
        ("", STANDARD_UNKNOWN),
        (None, STANDARD_UNKNOWN),
        ("some bespoke form", STANDARD_UNKNOWN),
    ],
)
def test_normalize_standard(raw: str | None, expected: str) -> None:
    assert normalize_standard(raw) == expected


# --- period_for ------------------------------------------------------------


def test_period_for_known_windows() -> None:
    assert period_for(STANDARD_FIDIC, NOTICE_CLAIM) == 28
    assert period_for(STANDARD_NEC, NOTICE_CLAIM) == 56
    assert period_for(STANDARD_NEC, NOTICE_QUOTATION) == 21
    assert period_for(STANDARD_AIA, NOTICE_CLAIM) == 21


def test_period_for_unknown_standard_falls_back_to_generic() -> None:
    assert period_for(STANDARD_UNKNOWN, NOTICE_CLAIM) == GENERIC_PERIODS[NOTICE_CLAIM]
    # An unknown notice type on a known standard also uses the generic table.
    assert period_for(STANDARD_FIDIC, "not_a_notice_type") is None


# --- clause_ref_for --------------------------------------------------------


def test_clause_ref_explicit_wins() -> None:
    assert clause_ref_for(STANDARD_FIDIC, NOTICE_CLAIM, "  20.2.1 ") == "20.2.1"


def test_clause_ref_defaults_per_standard() -> None:
    assert clause_ref_for(STANDARD_NEC, NOTICE_CLAIM) == "NEC 61.3"
    assert clause_ref_for(STANDARD_FIDIC, NOTICE_CLAIM) == "FIDIC 20.1"
    assert clause_ref_for(STANDARD_UNKNOWN, NOTICE_CLAIM) == ""


# --- parse_date ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-07-01", datetime(2026, 7, 1, tzinfo=UTC)),
        ("2026-07-01T09:00:00+00:00", datetime(2026, 7, 1, 9, tzinfo=UTC)),
        ("2026-07-01T09:00:00Z", datetime(2026, 7, 1, 9, tzinfo=UTC)),
        ("2026-07-01 09:00:00", datetime(2026, 7, 1, 9, tzinfo=UTC)),
    ],
)
def test_parse_date_iso_forms(value: str, expected: datetime) -> None:
    assert parse_date(value) == expected


@pytest.mark.parametrize("value", ["", "   ", None, "not-a-date", "2026-13-99"])
def test_parse_date_bad_values(value: str | None) -> None:
    assert parse_date(value) is None


def test_add_days() -> None:
    assert add_days(NOW, 28) == NOW + timedelta(days=28)


# --- derive_deadline -------------------------------------------------------


def test_derive_deadline_explicit_wins_over_period() -> None:
    explicit = datetime(2026, 8, 1, tzinfo=UTC)
    got = derive_deadline(trigger_date=NOW, period_days=28, explicit_due=explicit)
    assert got == explicit


def test_derive_deadline_from_trigger_plus_period() -> None:
    got = derive_deadline(trigger_date=NOW, period_days=28, explicit_due=None)
    assert got == NOW + timedelta(days=28)


def test_derive_deadline_none_when_undatable() -> None:
    assert derive_deadline(trigger_date=None, period_days=28, explicit_due=None) is None
    assert derive_deadline(trigger_date=NOW, period_days=None, explicit_due=None) is None


# --- classify_status -------------------------------------------------------


def test_classify_unknown_without_deadline() -> None:
    status, served_late = classify_status(deadline=None, now=NOW, satisfied_at=NOW)
    assert status == STATUS_UNKNOWN
    assert served_late is False


def test_classify_met_when_satisfied_in_time() -> None:
    deadline = NOW + timedelta(days=5)
    status, served_late = classify_status(deadline=deadline, now=NOW, satisfied_at=NOW)
    assert status == STATUS_MET
    assert served_late is False


def test_classify_served_late_is_overdue() -> None:
    deadline = NOW
    status, served_late = classify_status(
        deadline=deadline, now=NOW + timedelta(days=30), satisfied_at=NOW + timedelta(days=3)
    )
    assert status == STATUS_OVERDUE
    assert served_late is True


def test_classify_overdue_unsatisfied() -> None:
    status, served_late = classify_status(deadline=NOW - timedelta(days=1), now=NOW, satisfied_at=None)
    assert status == STATUS_OVERDUE
    assert served_late is False


@pytest.mark.parametrize(
    ("days_ahead", "expected"),
    [
        (DEFAULT_DUE_SOON_DAYS, STATUS_DUE_SOON),  # exactly on the boundary
        (1, STATUS_DUE_SOON),
        (DEFAULT_DUE_SOON_DAYS + 1, STATUS_UPCOMING),
        (30, STATUS_UPCOMING),
    ],
)
def test_classify_due_soon_boundary(days_ahead: int, expected: str) -> None:
    deadline = NOW + timedelta(days=days_ahead)
    status, _ = classify_status(deadline=deadline, now=NOW, satisfied_at=None)
    assert status == expected


# --- entitlement_at_risk ---------------------------------------------------


def test_at_risk_never_when_notice_not_required() -> None:
    assert (
        entitlement_at_risk(
            requires_notice=False,
            status=STATUS_OVERDUE,
            served_late=True,
            proof_on_file=False,
            satisfied_at=None,
        )
        is False
    )


def test_at_risk_when_served_late() -> None:
    assert entitlement_at_risk(
        requires_notice=True, status=STATUS_OVERDUE, served_late=True, proof_on_file=True, satisfied_at=NOW
    )


def test_at_risk_when_overdue_and_unserved() -> None:
    assert entitlement_at_risk(
        requires_notice=True, status=STATUS_OVERDUE, served_late=False, proof_on_file=True, satisfied_at=None
    )


def test_at_risk_when_proof_missing_even_if_upcoming() -> None:
    # A required notice with nothing on file is flagged while still upcoming.
    assert entitlement_at_risk(
        requires_notice=True, status=STATUS_UPCOMING, served_late=False, proof_on_file=False, satisfied_at=None
    )


def test_not_at_risk_when_met_with_proof() -> None:
    assert (
        entitlement_at_risk(
            requires_notice=True, status=STATUS_MET, served_late=False, proof_on_file=True, satisfied_at=NOW
        )
        is False
    )


# --- build_clock -----------------------------------------------------------


def test_build_clock_fidic_claim_overdue_and_at_risk() -> None:
    # Event 40 days ago, FIDIC 28-day claim notice never served, no proof -> the
    # bar lapsed and the entitlement is at risk.
    inp = _input(
        trigger_date=NOW - timedelta(days=40),
        period_days=28,
        satisfied_at=None,
        requires_notice=True,
        proof_on_file=False,
    )
    clock = build_clock(inp, now=NOW)
    assert clock.deadline == NOW - timedelta(days=12)
    assert clock.days_remaining == -12.0
    assert clock.status == STATUS_OVERDUE
    assert clock.entitlement_at_risk is True


def test_build_clock_met_stops_the_clock() -> None:
    inp = _input(
        trigger_date=NOW - timedelta(days=10),
        period_days=28,
        satisfied_at=NOW - timedelta(days=5),
        requires_notice=True,
        proof_on_file=True,
    )
    clock = build_clock(inp, now=NOW)
    assert clock.status == STATUS_MET
    assert clock.days_remaining is None
    assert clock.served_late is False
    assert clock.entitlement_at_risk is False


def test_build_clock_met_but_no_proof_is_flagged() -> None:
    inp = _input(
        trigger_date=NOW - timedelta(days=10),
        period_days=28,
        satisfied_at=NOW - timedelta(days=5),
        requires_notice=True,
        proof_on_file=False,
    )
    clock = build_clock(inp, now=NOW)
    assert clock.status == STATUS_MET
    assert clock.entitlement_at_risk is True  # proof missing


def test_build_clock_upcoming_positive_days_remaining() -> None:
    inp = _input(
        trigger_date=NOW,
        period_days=28,
        satisfied_at=None,
        requires_notice=True,
        proof_on_file=True,
    )
    clock = build_clock(inp, now=NOW)
    assert clock.status == STATUS_UPCOMING
    assert clock.days_remaining == 28.0


def test_build_clock_unknown_when_dates_missing() -> None:
    inp = _input(trigger_date=None, explicit_due=None, period_days=28, requires_notice=False)
    clock = build_clock(inp, now=NOW)
    assert clock.deadline is None
    assert clock.days_remaining is None
    assert clock.status == STATUS_UNKNOWN


# --- sort_register + summarize_register ------------------------------------


def test_register_orders_worst_first_and_summarizes() -> None:
    overdue = _input(
        source_id="a",
        source_ref="VR-A",
        trigger_date=NOW - timedelta(days=40),
        period_days=28,
        requires_notice=True,
        proof_on_file=False,
    )
    due_soon = _input(
        source_id="b",
        source_ref="VR-B",
        trigger_date=NOW - timedelta(days=25),
        period_days=28,  # deadline in 3 days
        requires_notice=True,
        proof_on_file=True,
    )
    upcoming = _input(
        source_id="c",
        source_ref="VR-C",
        trigger_date=NOW,
        period_days=28,  # deadline in 28 days
        requires_notice=True,
        proof_on_file=True,
    )
    met = _input(
        source_id="d",
        source_ref="VR-D",
        trigger_date=NOW - timedelta(days=10),
        period_days=28,
        satisfied_at=NOW - timedelta(days=5),
        requires_notice=True,
        proof_on_file=True,
    )

    ordered, summary = build_register([met, upcoming, due_soon, overdue], now=NOW)

    assert [c.source_ref for c in ordered] == ["VR-A", "VR-B", "VR-C", "VR-D"]
    assert summary.total == 4
    assert summary.overdue == 1
    assert summary.due_soon == 1
    assert summary.counts_by_status[STATUS_UPCOMING] == 1
    assert summary.counts_by_status[STATUS_MET] == 1
    assert summary.at_risk == 1  # only the overdue-no-proof one
    assert summary.proof_missing == 1


def test_summarize_empty() -> None:
    summary = summarize_register([])
    assert summary.total == 0
    assert summary.open_total == 0
    assert summary.at_risk == 0
    assert summary.counts_by_status[STATUS_OVERDUE] == 0


def test_sort_register_at_risk_first_within_same_status() -> None:
    # Two overdue clocks: the at-risk one (no proof) must sort ahead.
    safe = build_clock(
        _input(
            source_id="s",
            source_ref="VR-S",
            trigger_date=NOW - timedelta(days=30),
            period_days=28,
            satisfied_at=NOW - timedelta(days=1),  # served late -> overdue + at risk
            requires_notice=False,  # not a notice clock -> not at risk
            proof_on_file=True,
        ),
        now=NOW,
    )
    risky = build_clock(
        _input(
            source_id="r",
            source_ref="VR-R",
            trigger_date=NOW - timedelta(days=30),
            period_days=28,
            satisfied_at=None,
            requires_notice=True,
            proof_on_file=False,
        ),
        now=NOW,
    )
    ordered = sort_register([safe, risky])
    assert ordered[0].source_ref == "VR-R"
    assert ordered[0].entitlement_at_risk is True
