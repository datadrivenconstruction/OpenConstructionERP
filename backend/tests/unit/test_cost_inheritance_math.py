# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The vector arithmetic every link of the chain shares: build, store as percent, expand to cents."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.costmodel.inheritance import (
    FROM_CONTRACT,
    FROM_CONTRACT_LINE,
    FROM_POSITION,
    NO_VECTOR,
    Vector,
    add_expanded,
    expand,
    first_inherited,
    percent_shares,
    vector_of,
)

D = Decimal


def test_a_row_without_shares_sits_whole_on_its_line() -> None:
    v = vector_of("L1")
    assert v == Vector(main="L1")
    assert not v.is_split
    assert v.lines == frozenset({"L1"})


def test_no_line_and_no_shares_is_the_empty_vector() -> None:
    assert vector_of(None).empty
    assert NO_VECTOR.lines == frozenset()


def test_shares_are_normalised_whatever_unit_they_are_in() -> None:
    by_percent = vector_of("A", [("A", "60"), ("B", "40")])
    by_quantity = vector_of("A", [("A", "120"), ("B", "80")])
    assert by_percent.shares == by_quantity.shares
    assert dict(by_percent.shares) == {"A": D("0.6"), "B": D("0.4")}


def test_main_follows_the_largest_share_not_a_stale_pointer() -> None:
    v = vector_of("A", [("A", "30"), ("B", "70")])
    assert v.main == "B"


def test_a_tie_keeps_the_first_share_as_main() -> None:
    assert vector_of(None, [("X", "50"), ("Y", "50")]).main == "X"


def test_a_split_left_with_one_line_is_that_line_whole() -> None:
    v = vector_of("OLD", [("B", "100")])
    assert v == Vector(main="B")


def test_the_same_line_twice_is_merged() -> None:
    v = vector_of(None, [("A", "25"), ("A", "25"), ("B", "50")])
    assert dict(v.shares) == {"A": D("0.5"), "B": D("0.5")}


def test_percent_shares_add_up_to_exactly_one_hundred() -> None:
    v = vector_of(None, [("A", "1"), ("B", "1"), ("C", "1")])
    pct = percent_shares(v)
    assert sum(p for _, p in pct) == D("100")
    assert [p for _, p in pct] == [D("33.333334"), D("33.333333"), D("33.333333")]


def test_a_single_line_stores_no_shares() -> None:
    assert percent_shares(Vector(main="A")) == []


def test_stored_percent_reads_back_to_the_same_money() -> None:
    original = vector_of(None, [("A", "1"), ("B", "2")])
    restored = vector_of(None, percent_shares(original))
    assert expand("1000.00", original) == expand("1000.00", restored)


def test_expand_a_single_line_passes_the_amount_untouched() -> None:
    assert expand(D("12.3456"), Vector(main="A")) == [("A", D("12.3456"))]


def test_expand_no_line_is_money_in_suspense() -> None:
    assert expand("50", NO_VECTOR) == [(None, D("50"))]


@pytest.mark.parametrize("amount", ["100.00", "0.01", "999999.99", "-250.03", "10.0050"])
def test_expand_never_makes_or_loses_a_cent(amount: str) -> None:
    v = vector_of(None, [("A", "1"), ("B", "1"), ("C", "1")])
    parts = expand(amount, v)
    assert sum(p for _, p in parts) == D(amount)
    assert {lid for lid, _ in parts} == {"A", "B", "C"}


def test_expand_follows_the_shares() -> None:
    v = vector_of("A", [("A", "60"), ("B", "40")])
    assert dict(expand("1000.00", v)) == {"A": D("600.00"), "B": D("400.00")}


def test_add_expanded_sums_per_line_and_returns_the_loose_part() -> None:
    acc: dict[str, Decimal] = {}
    assert add_expanded(acc, "100", vector_of(None, [("A", "1"), ("B", "1")])) == D("0")
    assert add_expanded(acc, "30", Vector(main="A")) == D("0")
    assert add_expanded(acc, "7", NO_VECTOR) == D("7")
    assert acc == {"A": D("80.00"), "B": D("50.00")}


def test_first_inherited_takes_the_first_source_that_names_a_line() -> None:
    picked = first_inherited(
        [(FROM_CONTRACT_LINE, None), (FROM_POSITION, NO_VECTOR), (FROM_CONTRACT, Vector(main="C"))]
    )
    assert picked.source == FROM_CONTRACT
    assert picked.vector.main == "C"


def test_first_inherited_with_nothing_is_empty() -> None:
    picked = first_inherited([(FROM_POSITION, None)])
    assert picked.vector.empty
    assert picked.source is None
