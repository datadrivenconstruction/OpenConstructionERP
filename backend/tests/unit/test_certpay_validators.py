# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Certified payroll validation rules.

The rules take a plain dict, so these run without a database or an application.
Each test asserts on the rule that should fire AND on the message naming the
specific mistake, because a rule that fires with the word "invalid" in it has
told a payroll clerk nothing they can act on.
"""

from typing import Any

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.certified_payroll.validators import (
    CERTIFIED_PAYROLL_RULE_SET,
    CERTIFIED_PAYROLL_RULES,
    DeterminationOutOfWindowRule,
    FringeElectionUnstatedRule,
    HoursWithoutDeterminationRule,
    OvertimeBaseIncludesFringeRule,
    RateBelowDeterminationRule,
    StatementOfComplianceMissingRule,
    WorkerWithoutClassificationRule,
    register_certified_payroll_rules,
)


def _line(**overrides: Any) -> dict[str, Any]:
    """A compliant line. Every test breaks exactly one thing about it."""
    line = {
        "worker_name": "R. Alvarez",
        "resource_id": None,
        "classification_code": "ELEC-1",
        "classification_title": "Electrician",
        "determination_id": "d-1",
        "determination_identifier": "WD-2026-0041",
        "determination_authority": "federal",
        "straight_hours": "40",
        "overtime_hours": "8",
        "required_basic_rate": "40",
        "required_fringe_rate": "10",
        "paid_basic_rate": "40",
        "paid_fringe_rate": "10",
        "overtime_base_rate": "40",
        "overtime_multiplier": "1.5",
        "fringe_election": "plan",
        "currency": "USD",
    }
    line.update(overrides)
    return line


def _week(**overrides: Any) -> dict[str, Any]:
    week = {
        "id": "w-1",
        "week_ending": "2026-08-16",
        "status": "draft",
        "signatory_name": "M. Okafor",
        "signatory_title": "Project Accountant",
        "signed_at": "2026-08-17T09:00:00+00:00",
        "statement_text": "I do hereby state ...",
        "fringe_election": "plan",
    }
    week.update(overrides)
    return week


def _context(lines: list[dict[str, Any]], week: dict[str, Any] | None = None) -> ValidationContext:
    return ValidationContext(data={"week": week or _week(), "lines": lines})


def _failures(results: list[Any]) -> list[Any]:
    return [r for r in results if not r.passed]


# ── The happy path stays quiet ───────────────────────────────────────────────


async def test_a_compliant_week_produces_no_failures() -> None:
    """Every rule must pass a correct payroll, or the set is unusable noise."""
    context = _context([_line()])
    for rule_cls in CERTIFIED_PAYROLL_RULES:
        results = await rule_cls().validate(context)
        assert not _failures(results), f"{rule_cls.__name__} fired on a compliant payroll"


# ── Worker with no classification ────────────────────────────────────────────


async def test_worker_without_classification_is_an_error() -> None:
    results = await WorkerWithoutClassificationRule().validate(
        _context([_line(classification_title="", classification_code="")])
    )
    failures = _failures(results)
    assert len(failures) == 1
    assert "R. Alvarez" in failures[0].message
    assert "no trade classification" in failures[0].message


async def test_a_classification_code_alone_is_enough() -> None:
    """A code with no title is untidy, not a compliance failure."""
    results = await WorkerWithoutClassificationRule().validate(_context([_line(classification_title="")]))
    assert not _failures(results)


# ── Hours with no determination ──────────────────────────────────────────────


async def test_hours_without_a_determination_are_an_error() -> None:
    results = await HoursWithoutDeterminationRule().validate(
        _context([_line(determination_id=None, determination_identifier="")])
    )
    failures = _failures(results)
    assert len(failures) == 1
    assert "no wage determination" in failures[0].message
    assert "Electrician" in failures[0].message


async def test_a_classification_with_no_hours_is_not_reported() -> None:
    """Nobody worked under it, so no rate needed establishing."""
    results = await HoursWithoutDeterminationRule().validate(
        _context([_line(determination_id=None, determination_identifier="", straight_hours="0", overtime_hours="0")])
    )
    assert not _failures(results)


# ── Paid below the determination ─────────────────────────────────────────────


async def test_a_package_below_the_determination_is_an_error() -> None:
    results = await RateBelowDeterminationRule().validate(_context([_line(paid_basic_rate="35")]))
    failures = _failures(results)
    assert len(failures) == 1
    assert "shortfall of 5" in failures[0].message
    assert "WD-2026-0041" in failures[0].message


async def test_a_lawful_reshuffle_of_basic_and_fringe_is_not_reported() -> None:
    """More fringe and less basic wage still meets the package, with no overtime."""
    results = await RateBelowDeterminationRule().validate(
        _context([_line(paid_basic_rate="45", paid_fringe_rate="5", overtime_hours="0", overtime_base_rate="45")])
    )
    assert not _failures(results)


async def test_a_basic_wage_below_the_determination_is_caught_when_overtime_exists() -> None:
    """The package is whole but the overtime base is short, so overtime underpays."""
    results = await RateBelowDeterminationRule().validate(
        _context([_line(paid_basic_rate="35", paid_fringe_rate="15", overtime_base_rate="35")])
    )
    failures = _failures(results)
    assert len(failures) == 1
    assert "met the total package" in failures[0].message
    assert "overtime premium is computed on the basic wage" in failures[0].message


async def test_a_rounding_difference_is_not_underpayment() -> None:
    results = await RateBelowDeterminationRule().validate(_context([_line(paid_basic_rate="39.999")]))
    assert not _failures(results)


# ── Overtime computed on fringe ──────────────────────────────────────────────


async def test_overtime_base_above_the_basic_wage_is_an_error() -> None:
    """The whole point of the module: the multiplier touched the fringe money."""
    results = await OvertimeBaseIncludesFringeRule().validate(_context([_line(overtime_base_rate="50")]))
    failures = _failures(results)
    assert len(failures) == 1
    assert "fringe benefit money" in failures[0].message
    assert "10" in failures[0].message


async def test_no_overtime_hours_means_nothing_to_check() -> None:
    results = await OvertimeBaseIncludesFringeRule().validate(
        _context([_line(overtime_hours="0", overtime_base_rate="50")])
    )
    assert not _failures(results)


async def test_an_overtime_base_below_the_basic_wage_is_not_this_rules_business() -> None:
    """Underpaying is the other rule's finding; this one only reports overpaying the base."""
    results = await OvertimeBaseIncludesFringeRule().validate(_context([_line(overtime_base_rate="30")]))
    assert not _failures(results)


# ── Statement of compliance ──────────────────────────────────────────────────


async def test_an_unsigned_week_is_an_error() -> None:
    results = await StatementOfComplianceMissingRule().validate(
        _context([_line()], _week(signatory_name="", signatory_title="", signed_at=None, statement_text=""))
    )
    failures = _failures(results)
    assert len(failures) == 1
    assert "no statement of compliance has been made" in failures[0].message
    assert "2026-08-16" in failures[0].message


async def test_a_half_signed_week_names_what_is_missing() -> None:
    results = await StatementOfComplianceMissingRule().validate(_context([_line()], _week(signatory_title="")))
    failures = _failures(results)
    assert len(failures) == 1
    assert "their position" in failures[0].message


# ── Fringe election ──────────────────────────────────────────────────────────


async def test_fringe_with_no_election_is_a_warning() -> None:
    results = await FringeElectionUnstatedRule().validate(_context([_line(fringe_election="")]))
    failures = _failures(results)
    assert len(failures) == 1
    assert str(failures[0].severity) == "warning"
    assert "benefit plan or was paid in cash" in failures[0].message


async def test_no_fringe_means_no_election_to_state() -> None:
    results = await FringeElectionUnstatedRule().validate(
        _context([_line(paid_fringe_rate="0", paid_basic_rate="50", fringe_election="")])
    )
    assert not _failures(results)


# ── Determination window ─────────────────────────────────────────────────────


async def test_a_determination_that_starts_after_the_week_is_a_warning() -> None:
    results = await DeterminationOutOfWindowRule().validate(
        _context([_line(determination_effective_date="2026-09-01")])
    )
    failures = _failures(results)
    assert len(failures) == 1
    assert "does not take effect until 2026-09-01" in failures[0].message


async def test_a_superseded_determination_is_a_warning() -> None:
    results = await DeterminationOutOfWindowRule().validate(_context([_line(determination_expires_on="2026-07-01")]))
    failures = _failures(results)
    assert len(failures) == 1
    assert "was superseded on 2026-07-01" in failures[0].message


async def test_a_determination_in_force_during_the_week_passes() -> None:
    results = await DeterminationOutOfWindowRule().validate(
        _context([_line(determination_effective_date="2026-01-01", determination_expires_on="2026-12-31")])
    )
    assert not _failures(results)


async def test_a_determination_expiring_inside_the_week_is_not_flagged() -> None:
    """It was in force for part of the week, which is a real and lawful case."""
    results = await DeterminationOutOfWindowRule().validate(_context([_line(determination_expires_on="2026-08-13")]))
    assert not _failures(results)


# ── Registration ─────────────────────────────────────────────────────────────


def test_registration_is_idempotent_and_registers_every_rule() -> None:
    register_certified_payroll_rules()
    register_certified_payroll_rules()
    registered = rule_registry.get_rules_for_sets([CERTIFIED_PAYROLL_RULE_SET])
    ids = [r.rule_id for r in registered]
    assert len(ids) == len(set(ids)) == len(CERTIFIED_PAYROLL_RULES)
    assert "certified_payroll.overtime_base_includes_fringe" in ids


def test_every_rule_has_a_distinct_id_and_a_description() -> None:
    ids = {rule_cls.rule_id for rule_cls in CERTIFIED_PAYROLL_RULES}
    assert len(ids) == len(CERTIFIED_PAYROLL_RULES)
    for rule_cls in CERTIFIED_PAYROLL_RULES:
        assert rule_cls.description.strip(), f"{rule_cls.__name__} has no description"
        assert rule_cls.rule_id.startswith("certified_payroll.")
