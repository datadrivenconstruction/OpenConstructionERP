"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the contract-exposure helpers.

These pin the behaviour of :mod:`app.modules.costmodel.contract_exposure`, a
pure, database-free layer that turns budget-vs-committed figures into a
contract-exposure view: how much budget is committed to contracts, how much is
still free to commit, the commitment ratio, and whether a group is
overcommitted. The focus is Decimal-exact money, a guarded division (no crash or
fabricated zero when a budget is zero or absent), the exact overcommit boundary
(committed equal to budget is fully committed but not an overrun), and a correct
project rollup.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.costmodel.contract_exposure import (
    ContractExposure,
    GroupExposure,
    commitment_ratio,
    compute_contract_exposure,
    compute_group_exposure,
)

# -- commitment_ratio (the single guarded division) --------------------------


def test_commitment_ratio_normal() -> None:
    assert commitment_ratio(Decimal("50"), Decimal("100")) == Decimal("0.5")


def test_commitment_ratio_zero_budget_is_none() -> None:
    """A zero budget has no baseline, so the ratio is undefined (None), not a crash."""
    assert commitment_ratio(Decimal("10"), Decimal("0")) is None


def test_commitment_ratio_negative_budget_is_none() -> None:
    assert commitment_ratio(Decimal("10"), Decimal("-5")) is None


def test_commitment_ratio_zero_committed_over_positive_budget_is_zero() -> None:
    assert commitment_ratio(Decimal("0"), Decimal("100")) == Decimal("0")


# -- compute_group_exposure --------------------------------------------------


def test_group_exposure_normal_case() -> None:
    row = compute_group_exposure("labor", Decimal("100000"), Decimal("60000"))
    assert isinstance(row, GroupExposure)
    assert row.group == "labor"
    assert row.budgeted == Decimal("100000")
    assert row.committed == Decimal("60000")
    assert row.remaining_to_commit == Decimal("40000")
    assert row.commitment_ratio == Decimal("0.6")
    assert row.overcommitted is False


def test_group_exposure_zero_budget_guard() -> None:
    """Committed against a zero budget: ratio None, remaining negative, overcommitted."""
    row = compute_group_exposure("contingency", "0", "500")
    assert row.budgeted == Decimal("0")
    assert row.committed == Decimal("500")
    assert row.remaining_to_commit == Decimal("-500")
    assert row.commitment_ratio is None
    assert row.overcommitted is True


def test_group_exposure_zero_budget_zero_committed() -> None:
    row = compute_group_exposure("overhead", "0", "0")
    assert row.remaining_to_commit == Decimal("0")
    assert row.commitment_ratio is None
    assert row.overcommitted is False


def test_group_exposure_boundary_committed_equals_budget_is_not_overcommit() -> None:
    """The exact boundary: committed == budget is fully committed but NOT an overrun."""
    row = compute_group_exposure("material", Decimal("100.00"), Decimal("100.00"))
    assert row.remaining_to_commit == Decimal("0.00")
    assert row.commitment_ratio == Decimal("1")
    assert row.overcommitted is False


def test_group_exposure_boundary_just_above_is_overcommit() -> None:
    """One cent above budget flips overcommitted to True."""
    row = compute_group_exposure("material", Decimal("100.00"), Decimal("100.01"))
    assert row.remaining_to_commit == Decimal("-0.01")
    assert row.overcommitted is True


def test_group_exposure_decimal_exactness() -> None:
    """Money stays Decimal-exact - no binary-float drift in remaining-to-commit."""
    # 100.30 - 33.33 = 66.97 exactly under Decimal; float subtraction drifts here.
    row = compute_group_exposure("equipment", Decimal("100.30"), Decimal("33.33"))
    assert row.remaining_to_commit == Decimal("66.97")


def test_group_exposure_parses_string_and_number_inputs() -> None:
    row = compute_group_exposure("subcontractor", "250.50", 100)
    assert row.budgeted == Decimal("250.50")
    assert row.committed == Decimal("100")
    assert row.remaining_to_commit == Decimal("150.50")


def test_group_exposure_junk_input_collapses_to_zero() -> None:
    """A dirty (unparseable / missing) figure collapses to 0, never crashes."""
    row = compute_group_exposure("misc", "not-a-number", None)
    assert row.budgeted == Decimal("0")
    assert row.committed == Decimal("0")
    assert row.commitment_ratio is None
    assert row.overcommitted is False


# -- compute_contract_exposure (project rollup) ------------------------------


def test_contract_exposure_empty() -> None:
    """No groups: empty rows, all-zero totals, undefined ratio, nothing overcommitted."""
    exposure = compute_contract_exposure([])
    assert isinstance(exposure, ContractExposure)
    assert exposure.groups == []
    assert exposure.total_budgeted == Decimal("0")
    assert exposure.total_committed == Decimal("0")
    assert exposure.total_remaining_to_commit == Decimal("0")
    assert exposure.total_commitment_ratio is None
    assert exposure.overcommitted is False
    assert exposure.overcommitted_group_count == 0


def test_contract_exposure_multi_line_rollup() -> None:
    """Totals sum every group; the project ratio, order and flags are correct."""
    exposure = compute_contract_exposure(
        [
            ("material", "100000", "40000"),
            ("labor", "50000", "50000"),  # exactly committed, not overcommitted
            ("equipment", "20000", "25000"),  # overcommitted by 5000
        ]
    )
    assert len(exposure.groups) == 3
    assert exposure.total_budgeted == Decimal("170000")
    assert exposure.total_committed == Decimal("115000")
    assert exposure.total_remaining_to_commit == Decimal("55000")
    # 115000 / 170000 = 0.6764705..., quantized half-up to six places.
    assert exposure.total_commitment_ratio == Decimal("0.676471")
    # Project total is within budget, but one group breaches its own budget.
    assert exposure.overcommitted is False
    assert exposure.overcommitted_group_count == 1
    # Row order is preserved.
    assert [g.group for g in exposure.groups] == ["material", "labor", "equipment"]


def test_contract_exposure_project_overcommitted_when_totals_breach() -> None:
    """The project flag reflects the totals: committed above budget overall."""
    exposure = compute_contract_exposure(
        [
            ("material", "10000", "12000"),
            ("labor", "5000", "4000"),
        ]
    )
    # Committed 16000 > budget 15000 overall.
    assert exposure.total_budgeted == Decimal("15000")
    assert exposure.total_committed == Decimal("16000")
    assert exposure.total_remaining_to_commit == Decimal("-1000")
    assert exposure.overcommitted is True
    assert exposure.overcommitted_group_count == 1


def test_contract_exposure_rollup_decimal_exactness() -> None:
    """Cent-level figures across groups roll up without float drift."""
    exposure = compute_contract_exposure(
        [
            ("a", "0.10", "0.03"),
            ("b", "0.20", "0.04"),
        ]
    )
    assert exposure.total_budgeted == Decimal("0.30")
    assert exposure.total_committed == Decimal("0.07")
    assert exposure.total_remaining_to_commit == Decimal("0.23")


def test_contract_exposure_all_zero_budget_ratio_none() -> None:
    """Every group has a zero budget: the project ratio stays undefined (None)."""
    exposure = compute_contract_exposure([("a", "0", "0"), ("b", "0", "0")])
    assert exposure.total_budgeted == Decimal("0")
    assert exposure.total_commitment_ratio is None
    assert exposure.overcommitted is False
