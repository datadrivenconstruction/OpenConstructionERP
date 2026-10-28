# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure, DB-free tests for the estimate-rollup composition engine.

The composition is factored out of the database precisely so the summation, the
double-counting decision (remaining, not held) and the FX fold can be asserted on
a bare interpreter with no PostgreSQL. These tests import only the pure engine and
the pure allowances / preliminaries engines it composes.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.allowances.allowance_math import AllowanceLine, roll_up_register
from app.modules.estimate_rollup.composition import (
    LINE_ALLOWANCES,
    LINE_BOQ_BASE,
    LINE_CONTINGENCY,
    LINE_PRELIMINARIES,
    AllowancesBreakdown,
    PreliminariesBreakdown,
    compose_estimate_rollup,
    fold_allowances_to_base,
    prelim_breakdown_from_rollup,
)
from app.modules.preliminaries.prelim_math import rollup_by_category

# ── Helpers ──────────────────────────────────────────────────────────────


def _empty_prelim() -> PreliminariesBreakdown:
    return PreliminariesBreakdown(
        total=Decimal("0.00"),
        fixed_total=Decimal("0.00"),
        time_related_total=Decimal("0.00"),
        item_count=0,
    )


def _empty_allowances() -> AllowancesBreakdown:
    return AllowancesBreakdown(
        total=Decimal("0.00"),
        provisional_sum_total=Decimal("0.00"),
        pc_sum_total=Decimal("0.00"),
        contingency_total=Decimal("0.00"),
        provisional_and_pc_count=0,
        contingency_count=0,
        allowance_count=0,
    )


# ── compose_estimate_rollup ──────────────────────────────────────────────


def test_estimate_total_is_boq_base_plus_prelims_plus_allowances() -> None:
    """estimate_total is the exact deliberate sum of the three parts."""
    prelim = PreliminariesBreakdown(
        total=Decimal("500.00"),
        fixed_total=Decimal("200.00"),
        time_related_total=Decimal("300.00"),
        item_count=2,
    )
    allowances = AllowancesBreakdown(
        total=Decimal("470.00"),
        provisional_sum_total=Decimal("70.00"),
        pc_sum_total=Decimal("0.00"),
        contingency_total=Decimal("400.00"),
        provisional_and_pc_count=1,
        contingency_count=1,
        allowance_count=2,
    )
    rollup = compose_estimate_rollup("EUR", Decimal("1500.00"), prelim, allowances)

    assert rollup.estimate_total == Decimal("2470.00")
    assert rollup.base_currency == "EUR"
    assert rollup.boq_base == Decimal("1500.00")


def test_component_lines_sum_exactly_to_estimate_total() -> None:
    """The shown lines are non-overlapping and reconstruct the total exactly."""
    prelim = PreliminariesBreakdown(Decimal("500.00"), Decimal("200.00"), Decimal("300.00"), 2)
    allowances = AllowancesBreakdown(
        total=Decimal("470.00"),
        provisional_sum_total=Decimal("70.00"),
        pc_sum_total=Decimal("0.00"),
        contingency_total=Decimal("400.00"),
        provisional_and_pc_count=1,
        contingency_count=1,
        allowance_count=2,
    )
    rollup = compose_estimate_rollup("EUR", Decimal("1500.00"), prelim, allowances)

    keys = [line.key for line in rollup.lines]
    assert keys == [LINE_BOQ_BASE, LINE_PRELIMINARIES, LINE_ALLOWANCES, LINE_CONTINGENCY]
    assert sum((line.amount for line in rollup.lines), Decimal("0")) == rollup.estimate_total
    # Contingency is called out on its own line, distinct from the other allowances.
    by_key = {line.key: line.amount for line in rollup.lines}
    assert by_key[LINE_CONTINGENCY] == Decimal("400.00")
    assert by_key[LINE_ALLOWANCES] == Decimal("70.00")


def test_no_prelims_no_allowances_returns_just_boq_base() -> None:
    """A project with only a BOQ composes to the BOQ base and one line."""
    rollup = compose_estimate_rollup("EUR", Decimal("1000.00"), _empty_prelim(), _empty_allowances())

    assert rollup.estimate_total == Decimal("1000.00")
    assert [line.key for line in rollup.lines] == [LINE_BOQ_BASE]
    assert rollup.lines[0].amount == Decimal("1000.00")


def test_empty_project_composes_to_zero() -> None:
    """A bare project (no BOQ, no prelims, no allowances) is all zeros, not an error."""
    rollup = compose_estimate_rollup("", Decimal("0"), _empty_prelim(), _empty_allowances())

    assert rollup.estimate_total == Decimal("0.00")
    assert rollup.boq_base == Decimal("0.00")
    assert [line.key for line in rollup.lines] == [LINE_BOQ_BASE]
    assert rollup.base_currency == ""


def test_negative_contingency_from_overdraw_reduces_the_total() -> None:
    """An over-drawn allowance (negative remaining) honestly lowers the total."""
    allowances = AllowancesBreakdown(
        total=Decimal("-50.00"),
        provisional_sum_total=Decimal("0.00"),
        pc_sum_total=Decimal("0.00"),
        contingency_total=Decimal("-50.00"),
        provisional_and_pc_count=0,
        contingency_count=1,
        allowance_count=1,
    )
    rollup = compose_estimate_rollup("EUR", Decimal("1000.00"), _empty_prelim(), allowances)

    assert rollup.estimate_total == Decimal("950.00")
    assert sum((line.amount for line in rollup.lines), Decimal("0")) == rollup.estimate_total


def test_multicurrency_lines_reconcile_to_total_despite_per_type_rounding() -> None:
    """Lines still sum to estimate_total when per-type FX rounding would drift.

    ``fold_allowances_to_base`` rounds the grand total together but each type on
    its own, so converting foreign remainders can leave the separately-rounded
    provisional / PC and contingency figures a cent apart from the together-
    rounded total. Here two 10.005 remainders make ``total`` 20.01 while each
    part rounds up to 10.01 on its own (separately summing them gives 20.02). The
    composition must derive the provisional / PC line as the remainder so the
    shown lines reconstruct the total exactly.
    """
    allowances = AllowancesBreakdown(
        total=Decimal("20.01"),
        provisional_sum_total=Decimal("10.01"),
        pc_sum_total=Decimal("0.00"),
        contingency_total=Decimal("10.01"),
        provisional_and_pc_count=1,
        contingency_count=1,
        allowance_count=2,
    )
    rollup = compose_estimate_rollup("EUR", Decimal("0.00"), _empty_prelim(), allowances)

    assert rollup.estimate_total == Decimal("20.01")
    assert sum((line.amount for line in rollup.lines), Decimal("0")) == rollup.estimate_total
    by_key = {line.key: line.amount for line in rollup.lines}
    # Contingency is shown at its own rounded value; the provisional / PC line
    # takes the remainder (10.00), absorbing the sub-cent residual.
    assert by_key[LINE_CONTINGENCY] == Decimal("10.01")
    assert by_key[LINE_ALLOWANCES] == Decimal("10.00")


# ── fold_allowances_to_base (remaining + FX) ─────────────────────────────


def test_fold_uses_remaining_not_held_and_splits_contingency() -> None:
    """Allowances contribute remaining (held - drawn); contingency is broken out."""
    register = roll_up_register(
        [
            AllowanceLine("contingency", "EUR", Decimal("400"), ()),
            AllowanceLine("provisional_sum", "EUR", Decimal("100"), (Decimal("30"),)),
            AllowanceLine("pc_sum", "EUR", Decimal("50"), ()),
        ]
    )
    breakdown = fold_allowances_to_base(register, {}, "EUR")

    assert breakdown.contingency_total == Decimal("400.00")
    # provisional remaining = 100 - 30 = 70
    assert breakdown.provisional_sum_total == Decimal("70.00")
    assert breakdown.pc_sum_total == Decimal("50.00")
    assert breakdown.total == Decimal("520.00")
    assert breakdown.contingency_count == 1
    assert breakdown.provisional_and_pc_count == 2
    assert breakdown.allowance_count == 3
    assert breakdown.unconverted_currencies == ()


def test_fold_converts_foreign_currency_at_the_project_rate() -> None:
    """A foreign allowance is converted to base at rate = base units per foreign unit."""
    register = roll_up_register([AllowanceLine("contingency", "USD", Decimal("100"), ())])
    # 1 USD = 2 EUR
    breakdown = fold_allowances_to_base(register, {"USD": "2"}, "EUR")

    assert breakdown.contingency_total == Decimal("200.00")
    assert breakdown.total == Decimal("200.00")
    assert breakdown.unconverted_currencies == ()


def test_fold_keeps_own_units_and_flags_when_rate_missing() -> None:
    """A foreign allowance with no rate is summed in its own units and flagged."""
    register = roll_up_register([AllowanceLine("contingency", "USD", Decimal("100"), ())])
    breakdown = fold_allowances_to_base(register, {}, "EUR")

    assert breakdown.contingency_total == Decimal("100.00")
    assert breakdown.unconverted_currencies == ("USD",)


def test_empty_register_folds_to_zero() -> None:
    """No allowances folds to an all-zero breakdown."""
    breakdown = fold_allowances_to_base(roll_up_register([]), {}, "EUR")

    assert breakdown.total == Decimal("0.00")
    assert breakdown.allowance_count == 0
    assert breakdown.contingency_count == 0


# ── prelim_breakdown_from_rollup ─────────────────────────────────────────


def test_prelim_breakdown_projects_fixed_and_time_related() -> None:
    """The preliminaries breakdown carries the grand, fixed and time-related totals."""
    rollup = rollup_by_category(
        [
            {"item_type": "fixed", "category": "setup", "fixed_amount": "200"},
            {"item_type": "time_related", "category": "staff", "rate_per_period": "100", "periods": "3"},
        ]
    )
    breakdown = prelim_breakdown_from_rollup(rollup)

    assert breakdown.total == Decimal("500.00")
    assert breakdown.fixed_total == Decimal("200.00")
    assert breakdown.time_related_total == Decimal("300.00")
    assert breakdown.item_count == 2


def test_end_to_end_pure_composition_from_engines() -> None:
    """The pure engines compose into the same headline number, end to end."""
    prelim = prelim_breakdown_from_rollup(
        rollup_by_category([{"item_type": "fixed", "category": "setup", "fixed_amount": "500"}])
    )
    allowances = fold_allowances_to_base(
        roll_up_register(
            [
                AllowanceLine("contingency", "EUR", Decimal("400"), ()),
                AllowanceLine("provisional_sum", "EUR", Decimal("100"), (Decimal("30"),)),
            ]
        ),
        {},
        "EUR",
    )
    rollup = compose_estimate_rollup("EUR", Decimal("1500.00"), prelim, allowances)

    # 1500 base + 500 prelims + (400 contingency + 70 remaining provisional) = 2470
    assert rollup.estimate_total == Decimal("2470.00")
    assert sum((line.amount for line in rollup.lines), Decimal("0")) == rollup.estimate_total
