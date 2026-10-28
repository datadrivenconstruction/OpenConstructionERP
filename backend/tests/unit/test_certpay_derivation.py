# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Deriving a certified payroll week from the payroll entries.

The pivot is the part of this module with the most ways to be quietly wrong: it
groups per-worker rows, spreads them across the days of the week, splits
straight from overtime, and works out how much of the rate paid was basic wage
and how much was fringe. All of that is exercised here against a fake data
layer, so the DB is never booted, matching the payroll unit tests next door.
"""

from decimal import Decimal
from typing import Any

import pytest

from app.modules.certified_payroll.models import (
    CertifiedPayrollWeek,
    WageClassification,
    WageDetermination,
    WorkerClassificationAssignment,
)
from app.modules.certified_payroll.service import CertifiedPayrollService

WEEK_ENDING = "2026-08-16"
MONDAY = "2026-08-10"
TUESDAY = "2026-08-11"
WEDNESDAY = "2026-08-12"


def _service() -> CertifiedPayrollService:
    """A service whose session is never touched - every reader is stubbed."""
    return CertifiedPayrollService(session=None)  # type: ignore[arg-type]


def _week(**overrides: Any) -> CertifiedPayrollWeek:
    week = CertifiedPayrollWeek(
        week_ending=WEEK_ENDING,
        status="draft",
        fringe_election="plan",
        currency="USD",
    )
    week.metadata_ = {
        "daily_overtime_threshold": "8",
        "weekly_overtime_threshold": None,
        "overtime_multiplier": "1.5",
    }
    for key, value in overrides.items():
        setattr(week, key, value)
    return week


def _determination() -> WageDetermination:
    determination = WageDetermination(
        authority="federal",
        identifier="WD-2026-0041",
        effective_date="2026-01-01",
        expires_on=None,
        currency="USD",
    )
    determination.id = "det-1"  # type: ignore[assignment]
    return determination


def _classification(basic: str = "40", fringe: str = "10") -> WageClassification:
    classification = WageClassification(
        code="ELEC-1",
        title="Electrician",
        basic_hourly_rate=basic,
        fringe_rate=fringe,
    )
    classification.id = "cls-1"  # type: ignore[assignment]
    classification.determination_id = "det-1"  # type: ignore[assignment]
    return classification


def _assignment(**overrides: Any) -> WorkerClassificationAssignment:
    assignment = WorkerClassificationAssignment(
        worker_name="R. Alvarez",
        worker_identifier="1234",
        classification_id="cls-1",
    )
    assignment.paid_basic_rate = None
    assignment.paid_fringe_rate = None
    assignment.fringe_election = None
    for key, value in overrides.items():
        setattr(assignment, key, value)
    return assignment


def _stub(service: CertifiedPayrollService, rows: list[dict[str, Any]], assignment=None) -> None:
    """Point the service at fixed payroll rows and a fixed classification index."""

    async def _rows(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return rows

    async def _index(*_args: Any, **_kwargs: Any):
        if assignment is None:
            return {}, {}, {}
        key = str(assignment.resource_id) if assignment.resource_id else assignment.worker_name.strip().lower()
        return (
            {key: assignment},
            {"cls-1": _classification()},
            {"det-1": _determination()},
        )

    service._payroll_rows = _rows  # type: ignore[method-assign]
    service._classification_index = _index  # type: ignore[method-assign]


def _row(work_date: str, hours: str, rate: str = "50", deductions: list | None = None) -> dict[str, Any]:
    return {
        "resource_id": None,
        "worker": "R. Alvarez",
        "work_date": work_date,
        "hours": Decimal(hours),
        "rate": Decimal(rate),
        "currency": "USD",
        "deductions": deductions or [],
    }


# ── The pivot ────────────────────────────────────────────────────────────────


async def test_day_rows_become_one_line_with_hours_spread_across_the_week() -> None:
    service = _service()
    _stub(service, [_row(MONDAY, "8"), _row(TUESDAY, "10"), _row(WEDNESDAY, "6")], _assignment())
    lines = await service.derive_lines(_week())

    assert len(lines) == 1
    line = lines[0]
    assert line["hours_by_day"][MONDAY] == {"straight": "8", "overtime": "0"}
    # The daily threshold of 8 makes the ninth and tenth hour overtime.
    assert line["hours_by_day"][TUESDAY] == {"straight": "8", "overtime": "2"}
    assert line["hours_by_day"][WEDNESDAY] == {"straight": "6", "overtime": "0"}
    assert line["straight_hours"] == "22"
    assert line["overtime_hours"] == "2"


async def test_two_entries_on_the_same_day_are_summed_not_duplicated() -> None:
    """Two bookings for one person on one day are one day's work."""
    service = _service()
    _stub(service, [_row(MONDAY, "4"), _row(MONDAY, "4")], _assignment())
    lines = await service.derive_lines(_week())

    assert len(lines) == 1
    assert lines[0]["hours_by_day"][MONDAY] == {"straight": "8", "overtime": "0"}


async def test_no_payroll_rows_yields_no_lines() -> None:
    service = _service()
    _stub(service, [], _assignment())
    assert await service.derive_lines(_week()) == []


# ── The pay split ────────────────────────────────────────────────────────────


async def test_a_stated_split_is_used_as_stated() -> None:
    """Real data somebody entered always beats an inference."""
    service = _service()
    _stub(service, [_row(MONDAY, "8")], _assignment(paid_basic_rate="42", paid_fringe_rate="9"))
    line = (await service.derive_lines(_week()))[0]

    assert line["paid_basic_rate"] == "42"
    assert line["paid_fringe_rate"] == "9"
    assert line["rate_split_source"] == "assignment"


async def test_an_unstated_split_is_derived_against_the_determination() -> None:
    """Paid 50 against a determination whose basic is 40: 40 basic, 10 fringe."""
    service = _service()
    _stub(service, [_row(MONDAY, "8", rate="50")], _assignment())
    line = (await service.derive_lines(_week()))[0]

    assert line["paid_basic_rate"] == "40"
    assert line["paid_fringe_rate"] == "10"
    assert line["rate_split_source"] == "derived_against_determination"


async def test_underpayment_is_not_hidden_inside_an_invented_fringe() -> None:
    """Paid 35 against a basic of 40: all of it is basic, and the fringe is zero.

    Splitting 35 into "40 basic minus something" would have made the shortfall
    disappear into a negative fringe. Reporting it as 35 basic and no fringe is
    what lets the compliance rule see an underpaid worker.
    """
    service = _service()
    _stub(service, [_row(MONDAY, "8", rate="35")], _assignment())
    line = (await service.derive_lines(_week()))[0]

    assert line["paid_basic_rate"] == "35"
    assert line["paid_fringe_rate"] == "0"
    assert line["rate_split_source"] == "derived_all_basic"
    assert line["required_basic_rate"] == "40"
    assert line["required_fringe_rate"] == "10"


async def test_the_overtime_base_is_the_basic_wage_not_the_package() -> None:
    """The whole reason this module exists, asserted on a derived line."""
    service = _service()
    _stub(service, [_row(MONDAY, "10", rate="50")], _assignment())
    line = (await service.derive_lines(_week()))[0]

    assert line["paid_basic_rate"] == "40"
    assert line["overtime_base_rate"] == "40"
    # 8 straight at 50 = 400, plus 2 overtime at (40 x 1.5 + 10) = 140 -> 540.
    assert line["gross_amount"] == "540.00"


# ── Classification and deductions ────────────────────────────────────────────


async def test_an_unclassified_worker_still_appears_with_empty_classification() -> None:
    """Dropping them would hide exactly the person the rules need to report."""
    service = _service()
    _stub(service, [_row(MONDAY, "8")], assignment=None)
    line = (await service.derive_lines(_week()))[0]

    assert line["worker_name"] == "R. Alvarez"
    assert line["classification_title"] == ""
    assert line["determination_id"] is None
    assert line["straight_hours"] == "8"


async def test_the_determination_is_carried_onto_the_line() -> None:
    service = _service()
    _stub(service, [_row(MONDAY, "8")], _assignment())
    line = (await service.derive_lines(_week()))[0]

    assert line["determination_identifier"] == "WD-2026-0041"
    assert line["determination_authority"] == "federal"
    assert line["determination_effective_date"] == "2026-01-01"


async def test_deductions_are_carried_through_and_net_is_gross_minus_them() -> None:
    service = _service()
    deductions = [
        {"label": "Income tax", "type": "tax", "amount": "50.00"},
        {"label": "Social security", "type": "social", "amount": "30.00"},
    ]
    _stub(service, [_row(MONDAY, "8", rate="50", deductions=deductions)], _assignment())
    line = (await service.derive_lines(_week()))[0]

    assert line["gross_amount"] == "400.00"
    assert line["total_deductions"] == "80.00"
    assert line["net_amount"] == "320.00"
    assert len(line["deductions_detail"]) == 2


async def test_net_pay_is_floored_at_zero_rather_than_going_negative() -> None:
    """An over-deduction is clamped; a payslip is never negative."""
    service = _service()
    deductions = [{"label": "Advance recovery", "type": "other", "amount": "999.00"}]
    _stub(service, [_row(MONDAY, "8", rate="50", deductions=deductions)], _assignment())
    line = (await service.derive_lines(_week()))[0]

    assert line["net_amount"] == "0"


async def test_the_week_election_applies_when_the_worker_states_none() -> None:
    service = _service()
    _stub(service, [_row(MONDAY, "8")], _assignment())
    line = (await service.derive_lines(_week(fringe_election="cash")))[0]
    assert line["fringe_election"] == "cash"


async def test_a_worker_election_overrides_the_week() -> None:
    service = _service()
    _stub(service, [_row(MONDAY, "8")], _assignment(fringe_election="cash"))
    line = (await service.derive_lines(_week(fringe_election="plan")))[0]
    assert line["fringe_election"] == "cash"


# ── Immutability of a certified week ─────────────────────────────────────────


def test_a_certified_week_refuses_to_be_edited() -> None:
    """The correction is a new payroll for the same week, not an edit."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        CertifiedPayrollService._reject_if_certified(_week(status="certified"))
    assert exc.value.status_code == 409
    assert "certified" in str(exc.value.detail)


def test_a_draft_week_edits_freely() -> None:
    CertifiedPayrollService._reject_if_certified(_week(status="draft"))


def test_a_locked_determination_refuses_to_be_edited() -> None:
    """The figures a signed statement of compliance rests on cannot move."""
    from fastapi import HTTPException

    determination = _determination()
    determination.locked = True
    with pytest.raises(HTTPException) as exc:
        CertifiedPayrollService._reject_if_locked(determination)
    assert exc.value.status_code == 409
    assert "WD-2026-0041" in str(exc.value.detail)
