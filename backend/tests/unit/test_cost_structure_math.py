# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost structure arithmetic: tree totals with own amounts, and splitting a position."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.costmodel.structure import (
    MODE_PERCENT,
    MODE_QUANTITY,
    AllocationError,
    AllocationView,
    PositionView,
    TreeNodeIn,
    check_shares,
    estimate_fields,
    fractions_of,
    line_contributions,
    split_amount,
    tree_totals,
)

D = Decimal


# ── Tree totals ──────────────────────────────────────────────────────────────


def test_total_is_own_plus_posted_plus_children() -> None:
    totals = tree_totals(
        [
            TreeNodeIn("300", None, own_amount=D("1000")),
            TreeNodeIn("330", "300", posted=D("250.50")),
            TreeNodeIn("331", "330", posted=D("100.25"), own_amount=D("10")),
            TreeNodeIn("340", "300", posted=D("40")),
        ]
    )
    assert totals["331"].total == D("110.25")
    assert totals["330"].total == D("360.75")
    assert totals["330"].children_total == D("110.25")
    assert totals["300"].total == D("1400.75")
    assert [totals[k].level for k in ("300", "330", "331", "340")] == [1, 2, 3, 2]
    assert sorted(totals["300"].children) == ["330", "340"]


def test_a_node_whose_parent_is_missing_is_a_root() -> None:
    totals = tree_totals([TreeNodeIn("a", "gone", posted=D("5"))])
    assert totals["a"].level == 1
    assert totals["a"].total == D("5")


def test_a_cycle_is_counted_once_and_does_not_loop() -> None:
    totals = tree_totals(
        [TreeNodeIn("a", "b", posted=D("1")), TreeNodeIn("b", "a", posted=D("2")), TreeNodeIn("c", "a", posted=D("4"))]
    )
    assert totals["a"].in_cycle and totals["b"].in_cycle and not totals["c"].in_cycle
    grand = sum(t.total for k, t in totals.items() if t.level == 1)
    assert grand == D("7")


# ── Shares ───────────────────────────────────────────────────────────────────


def test_percent_shares_must_add_up_to_100_within_a_hundredth_of_a_percent() -> None:
    assert check_shares(MODE_PERCENT, [D("60"), D("40")], None).within_tolerance
    assert check_shares(MODE_PERCENT, [D("60"), D("39.995")], None).within_tolerance
    assert not check_shares(MODE_PERCENT, [D("60"), D("39.98")], None).within_tolerance


def test_quantity_shares_must_add_up_to_the_position_quantity() -> None:
    assert check_shares(MODE_QUANTITY, [D("120"), D("180")], D("300")).within_tolerance
    assert not check_shares(MODE_QUANTITY, [D("120"), D("170")], D("300")).within_tolerance


def test_fractions_refuse_shares_that_miss() -> None:
    with pytest.raises(AllocationError) as err:
        fractions_of(MODE_PERCENT, [D("50"), D("40")], None)
    assert err.value.problem == "shares_do_not_add_up"


@pytest.mark.parametrize(
    ("mode", "shares", "qty", "problem"),
    [
        ("weight", [D("100")], None, "unknown_mode"),
        (MODE_PERCENT, [], None, "no_shares"),
        (MODE_PERCENT, [D("120"), D("-20")], None, "share_not_positive"),
        (MODE_QUANTITY, [D("1")], D("0"), "quantity_split_without_quantity"),
    ],
)
def test_fractions_refuse_impossible_shares(
    mode: str, shares: list[Decimal], qty: Decimal | None, problem: str
) -> None:
    with pytest.raises(AllocationError) as err:
        fractions_of(mode, shares, qty)
    assert err.value.problem == problem


def test_quantity_fractions() -> None:
    assert fractions_of(MODE_QUANTITY, [D("120"), D("180")], D("300")) == [D("0.4"), D("0.6")]


# ── Splitting money ──────────────────────────────────────────────────────────


def test_split_adds_up_to_the_cent() -> None:
    parts = split_amount(D("100.00"), [D(1) / D(3)] * 3)
    assert parts == [D("33.34"), D("33.33"), D("33.33")]
    assert sum(parts) == D("100.00")


def test_split_of_a_credit_keeps_the_sign() -> None:
    parts = split_amount(D("-10.00"), [D("0.5"), D("0.5")])
    assert parts == [D("-5.00"), D("-5.00")]


def test_split_by_fractions_from_a_tolerated_percent() -> None:
    fractions = fractions_of(MODE_PERCENT, [D("33.333"), D("33.333"), D("33.333")], None)
    parts = split_amount(D("1000.01"), fractions)
    assert sum(parts) == D("1000.01")
    assert max(parts) - min(parts) == D("0.01")


# ── What cost lines carry ────────────────────────────────────────────────────


def _pos(
    pid: str, total: str, qty: str = "1", line: str | None = None, boq: str = "B1", rate: str = "1"
) -> PositionView:
    return PositionView(id=pid, boq_id=boq, total=total, quantity=qty, unit="m2", cost_line_id=line, unit_rate=rate)


def test_a_split_position_is_counted_once_across_its_lines() -> None:
    positions = [_pos("P", "1000.00", qty="300", line="L1"), _pos("Q", "50.00", line="L2")]
    rows = [AllocationView("P", "L1", MODE_QUANTITY, D("120")), AllocationView("P", "L2", MODE_QUANTITY, D("180"))]
    out = line_contributions(positions, rows)
    assert out["L1"].amount == D("400.00")
    assert out["L2"].amount == D("650.00")
    assert out["L1"].amount + out["L2"].amount == D("1050.00")
    assert out["L1"].quantity == D("120")


def test_an_unsplit_position_keeps_its_own_figures() -> None:
    out = line_contributions([_pos("P", "1234.567", qty="10", line="L1", rate="123.4567")], [])
    assert estimate_fields(out["L1"], "m2") == {
        "estimate_quantity": "10",
        "estimate_unit_rate": "123.4567",
        "estimate_amount": "1234.567",
    }


def test_a_line_owned_by_one_bill_takes_nothing_from_a_copy() -> None:
    original = _pos("P", "100.00", line="L1", boq="B1")
    copy = _pos("P2", "100.00", line="L1", boq="B2")
    out = line_contributions([original, copy], [], line_boq={"L1": "B1"})
    assert out["L1"].amount == D("100.00")
    assert out["L1"].positions == {"P"}


def test_a_stale_quantity_split_still_divides_the_whole_position() -> None:
    # Shares were 120 + 180 = 300 when stored; the position now measures 400.
    positions = [_pos("P", "800.00", qty="400")]
    rows = [AllocationView("P", "L1", MODE_QUANTITY, D("120")), AllocationView("P", "L2", MODE_QUANTITY, D("180"))]
    out = line_contributions(positions, rows)
    assert out["L1"].amount + out["L2"].amount == D("800.00")
    assert out["L1"].amount == D("320.00")


def test_section_rows_and_unallocated_positions_carry_nothing() -> None:
    header = PositionView(id="H", boq_id="B1", total="999", quantity="0", unit="", cost_line_id="L1")
    loose = _pos("X", "10.00")
    assert line_contributions([header, loose], []) == {}
    assert estimate_fields(None, "m2")["estimate_amount"] == "0"
