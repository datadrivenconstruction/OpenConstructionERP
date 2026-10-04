# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Splitting an approved change order over schedule of values lines, on paper.

Every case is arithmetic a person can check by hand. The property that
matters to the owner is asserted in all of them: the per-line deltas add up
to the change order amount exactly, to the fourth decimal the column holds,
so the schedule of values and the contract sum to date cannot drift apart.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.contracts.sov_adjustments import (
    METHOD_ITEMIZED,
    METHOD_ITEMIZED_WITH_BALANCE,
    METHOD_POOLED,
    METHOD_PRO_RATA,
    PLACE_LINKED_LINE,
    PLACE_LUMP_SUM,
    PLACE_QUANTITY,
    UNRESOLVED_AMBIGUOUS_BOQ,
    UNRESOLVED_BAD_ID,
    UNRESOLVED_NOT_ON_CONTRACT,
    UNRESOLVED_ROLL_UP,
    AllocationItem,
    allocate,
    placement,
    resolve_items,
)

D = Decimal
A = uuid.uuid4()
B = uuid.uuid4()
C = uuid.uuid4()


def _shares(allocation) -> dict:
    return {share.line_id: share.delta for share in allocation.shares}


# ── allocate ─────────────────────────────────────────────────────────────


def test_a_change_order_without_references_is_one_pooled_line() -> None:
    allocation = allocate(D("12500"), [AllocationItem(weight=D("12500"), item_id="i1")])
    assert allocation.method == METHOD_POOLED
    assert _shares(allocation) == {None: D("12500")}
    assert allocation.shares[0].item_ids == ("i1",)


def test_a_change_order_with_no_items_is_one_pooled_line() -> None:
    allocation = allocate(D("-800"), [])
    assert allocation.method == METHOD_POOLED
    assert _shares(allocation) == {None: D("-800")}


def test_a_zero_amount_allocates_nothing() -> None:
    assert allocate(D("0"), [AllocationItem(weight=D("10"), line_id=A)]).shares == ()


def test_items_that_add_up_move_each_line_by_its_own_items() -> None:
    items = [
        AllocationItem(weight=D("4000"), line_id=A, item_id="a1"),
        AllocationItem(weight=D("-1500"), line_id=B, item_id="b1"),
        AllocationItem(weight=D("1000"), line_id=A, item_id="a2"),
        AllocationItem(weight=D("700"), item_id="new"),
    ]
    allocation = allocate(D("4200"), items)
    assert allocation.method == METHOD_ITEMIZED
    assert _shares(allocation) == {A: D("5000"), B: D("-1500"), None: D("700")}
    # Referenced lines first in the order they appear, the new line last.
    assert [share.line_id for share in allocation.shares] == [A, B, None]
    assert allocation.shares[0].item_ids == ("a1", "a2")
    assert allocation.total == D("4200")


def test_a_different_amount_of_the_same_sign_is_split_pro_rata() -> None:
    # Items priced at 10,000 and the engineer approved 9,000: every line takes 90%.
    items = [
        AllocationItem(weight=D("6000"), line_id=A),
        AllocationItem(weight=D("3000"), line_id=B),
        AllocationItem(weight=D("1000")),
    ]
    allocation = allocate(D("9000"), items)
    assert allocation.method == METHOD_PRO_RATA
    assert _shares(allocation) == {A: D("5400"), B: D("2700"), None: D("900")}


def test_pro_rata_rounding_goes_to_the_largest_remainder_and_the_total_is_exact() -> None:
    # 100 over three equal items: 33.33 each, and the one cent left goes to the
    # first of the equal remainders.
    items = [AllocationItem(weight=D("1"), line_id=key) for key in (A, B, C)]
    allocation = allocate(D("100"), items)
    assert _shares(allocation) == {A: D("33.34"), B: D("33.33"), C: D("33.33")}
    assert allocation.total == D("100")


def test_a_sub_cent_amount_still_adds_up_to_the_fourth_decimal() -> None:
    # 666.667 and 333.3335 cut to 666.66 and 333.33; the whole cent goes to the
    # larger remainder and the half of a tenth of a cent to the larger share.
    items = [AllocationItem(weight=D("2"), line_id=A), AllocationItem(weight=D("1"), line_id=B)]
    allocation = allocate(D("1000.0005"), items)
    assert allocation.total == D("1000.0005")
    # The larger share carries the rounding and the sub-cent part.
    assert _shares(allocation) == {A: D("666.6705"), B: D("333.33")}


def test_three_cents_over_five_items_go_to_three_of_them_and_none_turns_negative() -> None:
    items = [AllocationItem(weight=D("1"), line_id=uuid.uuid4()) for _ in range(5)]
    allocation = allocate(D("0.03"), items)
    assert [share.delta for share in allocation.shares] == [D("0.01")] * 3
    assert [share.line_id for share in allocation.shares] == [item.line_id for item in items[:3]]


def test_pro_rata_keeps_the_sign_of_each_item() -> None:
    # +12,000 and -2,000 itemised at 10,000, approved at 5,000: halve both.
    items = [AllocationItem(weight=D("12000"), line_id=A), AllocationItem(weight=D("-2000"), line_id=B)]
    allocation = allocate(D("5000"), items)
    assert _shares(allocation) == {A: D("6000"), B: D("-1000")}


def test_items_that_net_to_zero_keep_their_figures_and_the_amount_goes_on_a_new_line() -> None:
    items = [AllocationItem(weight=D("2000"), line_id=A), AllocationItem(weight=D("-2000"), line_id=B)]
    allocation = allocate(D("500"), items)
    assert allocation.method == METHOD_ITEMIZED_WITH_BALANCE
    assert _shares(allocation) == {A: D("2000"), B: D("-2000"), None: D("500")}


def test_items_of_the_opposite_sign_are_not_flipped() -> None:
    # Scaling 3,000 of additions to a -1,000 deduction would turn every
    # addition into a deduction. The items stand and the balance is its own line.
    items = [AllocationItem(weight=D("3000"), line_id=A), AllocationItem(weight=D("200"))]
    allocation = allocate(D("-1000"), items)
    assert allocation.method == METHOD_ITEMIZED_WITH_BALANCE
    assert _shares(allocation) == {A: D("3000"), None: D("-4000")}
    assert allocation.total == D("-1000")


@pytest.mark.parametrize(
    ("amount", "weights"),
    [
        ("9999.99", ["1", "1", "1", "1", "1", "1", "1"]),
        ("-1234.5678", ["3", "5", "7"]),
        ("0.03", ["1", "1", "1", "1", "1"]),
        ("250000", ["0.01", "99999.99"]),
        ("17", ["5", "-3", "4"]),
    ],
)
def test_the_shares_always_add_up_to_the_amount(amount: str, weights: list[str]) -> None:
    items = [AllocationItem(weight=D(w), line_id=uuid.uuid4()) for w in weights]
    allocation = allocate(D(amount), items)
    assert allocation.total == D(amount)
    assert all(share.delta != 0 for share in allocation.shares)


def test_unresolved_references_are_reported() -> None:
    items = [
        AllocationItem(weight=D("10"), line_id=A, item_id="ok"),
        AllocationItem(weight=D("5"), item_id="lost", unresolved=UNRESOLVED_NOT_ON_CONTRACT),
    ]
    allocation = allocate(D("15"), items)
    assert allocation.unresolved == {"lost": UNRESOLVED_NOT_ON_CONTRACT}
    assert _shares(allocation) == {A: D("10"), None: D("5")}


# ── placement ────────────────────────────────────────────────────────────


def _line(quantity: str, rate: str, total: str) -> SimpleNamespace:
    return SimpleNamespace(quantity=D(quantity), unit_rate=D(rate), total_value=D(total))


def test_a_lump_sum_line_takes_the_change_in_its_total_and_rate() -> None:
    placed = placement(_line("1", "50000", "50000"), D("-1250.50"))
    assert placed.kind == PLACE_LUMP_SUM
    assert (placed.quantity, placed.unit_rate, placed.total_value) == (D("1"), D("48749.50"), D("48749.50"))
    assert placed.quantity * placed.unit_rate == placed.total_value


def test_a_measured_line_takes_whole_units_at_its_contract_rate() -> None:
    # 120 m3 at 250 = 30,000; the change adds 10,000, which is 40 m3.
    placed = placement(_line("120", "250", "30000"), D("10000"))
    assert placed.kind == PLACE_QUANTITY
    assert (placed.quantity, placed.unit_rate, placed.total_value) == (D("160"), D("250"), D("40000"))
    assert placed.delta_quantity == D("40")


def test_a_measured_line_is_not_repriced_when_the_change_is_not_whole_units() -> None:
    # 10,000 at 333 per m3 is 30.03003... m3, not a quantity the column can hold.
    assert placement(_line("120", "333", "39960"), D("10000")).kind == PLACE_LINKED_LINE


def test_a_line_priced_at_an_agreed_figure_is_left_alone() -> None:
    # 0.7 x 37 is 25.90 only by agreement; the stored total is 26.00.
    assert placement(_line("0.7", "37", "26.00"), D("5")).kind == PLACE_LINKED_LINE


# ── resolve_items ────────────────────────────────────────────────────────


def _sov(line_id, *, parent=None, position=None) -> SimpleNamespace:
    meta = {"boq_position_id": str(position)} if position else {}
    return SimpleNamespace(id=line_id, parent_line_id=parent, metadata_=meta)


def _item(cost: str, **meta) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), cost_delta=D(cost), metadata_=meta)


def test_an_item_finds_its_line_by_id_or_by_the_bill_position() -> None:
    position = uuid.uuid4()
    lines = [_sov(A), _sov(B, position=position)]
    resolved = resolve_items(
        [_item("100", contract_line_id=str(A)), _item("50", boq_position_id=str(position)), _item("7")], lines
    )
    assert [item.line_id for item in resolved] == [A, B, None]
    assert [item.unresolved for item in resolved] == [None, None, None]
    assert [item.weight for item in resolved] == [D("100"), D("50"), D("7")]


def test_references_that_cannot_be_followed_go_to_the_new_line_with_a_reason() -> None:
    shared = uuid.uuid4()
    parent = uuid.uuid4()
    lines = [_sov(parent), _sov(A, parent=parent), _sov(B, position=shared), _sov(C, position=shared)]
    resolved = resolve_items(
        [
            _item("1", contract_line_id=str(uuid.uuid4())),
            _item("1", contract_line_id=str(parent)),
            _item("1", boq_position_id=str(shared)),
            _item("1", contract_line_id="not-a-uuid"),
            _item("1", boq_position_id=str(uuid.uuid4())),
        ],
        lines,
    )
    assert all(item.line_id is None for item in resolved)
    assert [item.unresolved for item in resolved] == [
        UNRESOLVED_NOT_ON_CONTRACT,
        UNRESOLVED_ROLL_UP,
        UNRESOLVED_AMBIGUOUS_BOQ,
        UNRESOLVED_BAD_ID,
        # A bill position no line carries is simply new scope.
        None,
    ]
