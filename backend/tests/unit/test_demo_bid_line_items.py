# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Seeded bids have to carry the lines the price comparison compares.

The leveling matrix and the budget comparison are both built by indexing a
bid's ``line_items`` on ``position_id``. The demo seeder used to write
``line_items=[]``, so both screens rendered a full grid of empty cells no
matter how many bidders had submitted: the page whose entire purpose is
per-line spread had no per-line data in it.

What is pinned here is not "there are lines" but the three properties that
decide whether the screen reads as real:

* the submitted total is an input, not an output - several packs state their
  bid figures in the package description and derive the bid factor from them,
  so the lines have to add up to the number already written down;
* rate times quantity equals the line total exactly, because the matrix reads
  any disagreement between the two as a *scaled* bid line and badges it, and a
  demo where every cell is badged says the opposite of what it means to;
* two bidders pricing the same line differ by more than rounding, or the
  matrix has nothing to colour.

Pure arithmetic over stub positions, so it needs no database.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.demo_projects import _bid_line_items, _tender_scopes


class _Pos:
    """The three fields the pricing reads off a BOQ position."""

    def __init__(self, index: int, quantity: float, unit_rate: float) -> None:
        self.id = f"11111111-0000-0000-0000-{index:012d}"
        self.quantity = f"{quantity:.2f}"
        self.unit_rate = f"{unit_rate:.2f}"
        self.description = f"Position {index}"
        self.unit = "m2"


def _scope(count: int) -> list:
    """A scope whose quantities and rates vary the way a real BOQ's do."""
    return [_Pos(i, 10.0 + (i * 37 % 1200), 12.5 + (i * 17 % 480)) for i in range(count)]


def _column_total(lines: list[dict]) -> Decimal:
    return sum((Decimal(str(line["total"])) for line in lines), Decimal(0))


def test_the_lines_add_up_to_the_total_the_pack_wrote_down() -> None:
    """Within the cents that 2-decimal rates cannot express, and no further."""
    scope = _scope(40)
    for bidder, total in enumerate((812_400.00, 858_900.00, 901_200.00)):
        lines = _bid_line_items(scope, bid_total=total, bidder_index=bidder)
        assert lines, "a priced scope produced no bid lines"
        gap = abs(Decimal(str(total)) - _column_total(lines))
        assert gap <= Decimal("0.05"), f"bidder {bidder} column is off by {gap}"


def test_no_line_reads_as_scaled() -> None:
    """rate x quantity == total, exactly, or every cell gets badged."""
    scope = _scope(40)
    for bidder in range(3):
        for line in _bid_line_items(scope, bid_total=750_000.00, bidder_index=bidder):
            product = Decimal(str(line["unit_rate"])) * Decimal(str(line["quantity"]))
            assert product == Decimal(str(line["total"])), f"line {line['position_id']} would be badged as scaled"


def test_two_bidders_disagree_on_the_same_line() -> None:
    """Identical totals must still produce different per-line rates."""
    scope = _scope(40)
    first = _bid_line_items(scope, bid_total=812_400.00, bidder_index=0)
    third = _bid_line_items(scope, bid_total=812_400.00, bidder_index=2)
    by_position = {line["position_id"]: Decimal(str(line["unit_rate"])) for line in third}
    gaps = [
        abs(by_position[line["position_id"]] - Decimal(str(line["unit_rate"])))
        for line in first
        if line["position_id"] in by_position
    ]
    assert len(gaps) >= 30, "the two bidders barely overlap, so there is nothing to compare"
    assert max(gaps) > Decimal("1"), "every shared line priced the same - the matrix has nothing to colour"


def test_a_later_bidder_leaves_scope_out_and_an_early_one_does_not() -> None:
    """Omissions are what the imputation path exists for, and they are seeded."""
    scope = _scope(40)
    full = _bid_line_items(scope, bid_total=800_000.00, bidder_index=0)
    partial = _bid_line_items(scope, bid_total=800_000.00, bidder_index=1)
    assert len(full) == len(scope), "the first bidder should quote the whole scope"
    assert len(partial) < len(scope), "no bidder omitted a line, so nothing is ever imputed"


def test_a_short_scope_keeps_every_line() -> None:
    """Dropping a line out of six removes a visible share, not a detail."""
    scope = _scope(6)
    for bidder in range(3):
        lines = _bid_line_items(scope, bid_total=100_000.00, bidder_index=bidder)
        assert len(lines) == 6, f"bidder {bidder} dropped a line from a six-line package"


def test_pricing_is_decided_by_position_not_by_chance() -> None:
    """A reseed has to produce the same comparison as the seed before it."""
    scope = _scope(40)
    once = _bid_line_items(scope, bid_total=812_400.00, bidder_index=1)
    twice = _bid_line_items(scope, bid_total=812_400.00, bidder_index=1)
    assert once == twice


def test_an_unpriced_package_produces_no_lines_rather_than_zeroes() -> None:
    """A scope with nothing to price must not invent a row of zeroes."""
    assert _bid_line_items([], bid_total=1_000.00, bidder_index=0) == []
    assert _bid_line_items([_Pos(0, 10.0, 0.0)], bid_total=1_000.00, bidder_index=0) == []


def test_every_scope_line_lands_in_exactly_one_package() -> None:
    """The split covers the BOQ once - no line quoted twice, none dropped."""
    scope = _scope(41)
    scopes = _tender_scopes(scope, 4)
    assert len(scopes) == 4
    seen = [position.id for chunk in scopes for position in chunk]
    assert seen == [position.id for position in scope]
    # Fewer lines than packages: the tail packages are empty, not short by a
    # line someone else already has.
    assert [len(s) for s in _tender_scopes(_scope(3), 4)] == [1, 1, 1, 0]
    assert len(_tender_scopes(scope, 1)) == 1


def _value(positions: list) -> Decimal:
    return sum((Decimal(p.quantity) * Decimal(p.unit_rate) for p in positions), Decimal(0))


def test_each_package_is_worth_about_the_share_its_bidders_quote() -> None:
    """Every package's bids are the same share of the grand total.

    The budget comparison measures a bid against the lines its own package
    holds, so a scope worth half of what its bidders quote shows all three of
    them 100% over budget for a reason nobody can read off the screen. Splitting
    41 lines into four equal counts does exactly that, because BOQ lines differ
    by two orders of magnitude in value.
    """
    scope = _scope(41)
    scopes = _tender_scopes(scope, 4)
    share = _value(scope) / 4
    ratios = [_value(chunk) / share for chunk in scopes]
    assert all(Decimal("0.8") < r < Decimal("1.25") for r in ratios), ratios


def test_one_expensive_line_does_not_empty_the_packages_behind_it() -> None:
    """A line worth most of the bill takes its package, not everyone else's."""
    fat = [_Pos(0, 1000.0, 1000.0)] + [_Pos(i, 1.0, 1.0) for i in range(1, 9)]
    scopes = _tender_scopes(fat, 4)
    assert all(chunk for chunk in scopes), [len(s) for s in scopes]
    # An unpriced bill has no value to balance and falls back to line count.
    assert [len(s) for s in _tender_scopes([_Pos(i, 0.0, 0.0) for i in range(9)], 4)] == [3, 2, 2, 2]
