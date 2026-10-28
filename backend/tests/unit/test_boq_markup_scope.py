# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for markup inheritance with per-position and per-section override.

``_calculate_markup_amounts_scoped`` is the composition layer over the bill's
markup cascade. It partitions the direct cost into buckets of leaves that see
the same set of overrides, runs the existing cascade once per bucket, and adds
each line's earnings back up. These tests pin the three things that decide
whether that is safe to ship:

* Nothing moves when nothing is scoped. Every bill in every database today has
  no scoped line, and the founder refused a rounding reconciliation precisely
  because it would reprice stored estimates. A partition that shifts a total by
  a cent would do the same thing under another name, so the unscoped path is
  asserted to be identical to the cascade it delegates to, not merely close.
* The buckets sum to the caller's own direct cost, whatever tree they walked.
* The override semantics that are easy to get subtly wrong: an exception
  changes a rate and never the compounding order, a nearer scope beats a wider
  one, and an inactive override means the company line is inherited again.

Amounts are asserted against the base each line was computed on rather than
against the grand total. A total can agree for the wrong reasons; a base
cannot.

Run (CI):
    cd backend
    python -m pytest tests/unit/test_boq_markup_scope.py -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.boq.models import BOQMarkup, Position
from app.modules.boq.service import (
    DEFAULT_MARKUP_TEMPLATES,
    _calculate_markup_amounts,
    _calculate_markup_amounts_scoped,
    _effective_stack,
    _scope_chain,
)

# ── Fixtures built by hand, no session ──────────────────────────────────────


def _mk(
    name: str,
    *,
    percentage: str = "0",
    markup_type: str = "percentage",
    fixed_amount: str = "0",
    apply_to: str = "direct_cost",
    sort_order: int = 0,
    is_active: bool = True,
    category: str = "overhead",
    scope_position_id: uuid.UUID | None = None,
    overrides_id: uuid.UUID | None = None,
    markup_id: uuid.UUID | None = None,
) -> BOQMarkup:
    """Build a transient markup row with a stable id.

    The id is assigned here rather than by a flush because the function under
    test resolves ``overrides_id`` against it, and a test that had to touch the
    database to name a line would not be a unit test of a pure helper.
    """
    markup = BOQMarkup(
        boq_id=None,
        name=name,
        markup_type=markup_type,
        category=category,
        percentage=percentage,
        fixed_amount=fixed_amount,
        apply_to=apply_to,
        sort_order=sort_order,
        is_active=is_active,
        scope_position_id=scope_position_id,
        overrides_id=overrides_id,
        metadata_={},
    )
    markup.id = markup_id or uuid.uuid4()
    return markup


def _pos(
    total: str,
    *,
    parent_id: uuid.UUID | None = None,
    is_section: bool = False,
    position_id: uuid.UUID | None = None,
) -> Position:
    """Build a transient position; a section carries no money of its own.

    ``_is_section`` reads unit, quantity and unit_rate and nothing else, so a
    section here is a row with a blank unit and two zeros, exactly the shape
    the service detects.
    """
    position = Position(
        boq_id=None,
        parent_id=parent_id,
        ordinal="1",
        description="Section" if is_section else "Item",
        unit="" if is_section else "m2",
        quantity="0" if is_section else "1",
        unit_rate="0" if is_section else total,
        total="0" if is_section else total,
        classification={},
    )
    position.id = position_id or uuid.uuid4()
    return position


def _amounts(results: list[tuple[BOQMarkup, Decimal]]) -> dict[str, Decimal]:
    """Collapse a result list into ``{markup name: amount}``."""
    return {markup.name: amount for markup, amount in results}


# ── The guarantee: an unscoped bill is untouched ────────────────────────────


@pytest.mark.parametrize("region", sorted(DEFAULT_MARKUP_TEMPLATES))
def test_a_bill_with_no_scoped_line_prices_exactly_as_before(region: str) -> None:
    """Every shipped template must come out identical through the new path.

    Not "within a cent". Identical. This is the assertion that says the feature
    cannot reprice an estimate that does not use it, and it runs against all
    fourteen regional defaults rather than one hand-built stack, because the
    templates are what customers actually have in their databases.
    """
    direct_cost = Decimal("1000000")
    stack = [
        _mk(
            entry["name"],
            markup_type=str(entry.get("markup_type", "percentage")),
            percentage=str(entry.get("percentage", "0")),
            fixed_amount=str(entry.get("fixed_amount", "0")),
            apply_to=str(entry.get("apply_to", "direct_cost")),
            sort_order=int(entry.get("sort_order", 0)),
            category=str(entry.get("category", "overhead")),
        )
        for entry in sorted(DEFAULT_MARKUP_TEMPLATES[region], key=lambda e: int(e.get("sort_order", 0)))
    ]
    positions = [_pos("250000") for _ in range(4)]

    before = _calculate_markup_amounts(direct_cost, stack)
    after = _calculate_markup_amounts_scoped(direct_cost, stack, positions)

    assert [m.name for m, _ in after] == [m.name for m, _ in before]
    assert [a for _, a in after] == [a for _, a in before]
    # Not merely equal line by line: the bill's total is the same object-for-
    # object figure the old path produced.
    assert sum(a for _, a in after) == sum(a for _, a in before)


def test_an_inactive_scoped_line_does_not_partition_the_bill() -> None:
    """A deactivated override is not there, so the company line is inherited.

    The alternative reading, where an inactive override still suppresses the
    line it points at, would make deactivating a row change money in a
    direction nobody can see on screen.
    """
    section = _pos("0", is_section=True)
    leaf = _pos("400000", parent_id=section.id)
    other = _pos("600000")
    company = _mk("Overhead", percentage="10", sort_order=1)
    exception = _mk(
        "Overhead (fit-out)",
        percentage="4",
        sort_order=1,
        is_active=False,
        scope_position_id=section.id,
        overrides_id=company.id,
    )

    results = _calculate_markup_amounts_scoped(Decimal("1000000"), [company, exception], [section, leaf, other])

    assert _amounts(results) == {"Overhead": Decimal("100000"), "Overhead (fit-out)": Decimal("0")}


# ── Buckets have to add up ──────────────────────────────────────────────────


def test_the_buckets_sum_to_the_direct_cost_the_caller_reported() -> None:
    """A tree that walks to less than the caller's figure keeps the caller's.

    Callers compute direct cost in several different ways (FX-converted,
    resource-aware, raw). The partition must never become a second opinion on
    what the bill costs, so the difference lands in the bill-wide bucket and
    the reported total is unchanged.
    """
    section = _pos("0", is_section=True)
    leaf = _pos("300000", parent_id=section.id)
    company = _mk("Overhead", percentage="10", sort_order=1)
    exception = _mk(
        "Overhead (fit-out)",
        percentage="20",
        sort_order=1,
        scope_position_id=section.id,
        overrides_id=company.id,
    )

    # The caller says the bill is 1,000,000 but hands over a tree worth
    # 300,000. The missing 700,000 is unscoped money.
    results = _calculate_markup_amounts_scoped(Decimal("1000000"), [company, exception], [section, leaf])

    amounts = _amounts(results)
    assert amounts["Overhead"] == Decimal("70000")  # 700,000 at 10 %
    assert amounts["Overhead (fit-out)"] == Decimal("60000")  # 300,000 at 20 %
    # And the two together are what a single 10 % line would have been, plus
    # exactly the extra the exception asked for.
    assert amounts["Overhead"] + amounts["Overhead (fit-out)"] == Decimal("130000")


def test_a_bill_with_no_positions_still_prices_its_bill_wide_lines() -> None:
    """An empty tree is not a reason to drop the company standard."""
    section_id = uuid.uuid4()
    company = _mk("Overhead", percentage="10", sort_order=1)
    exception = _mk("Overhead (fit-out)", percentage="20", sort_order=1, scope_position_id=section_id)

    results = _calculate_markup_amounts_scoped(Decimal("500000"), [company, exception], [])

    assert _amounts(results)["Overhead"] == Decimal("50000")
    assert _amounts(results)["Overhead (fit-out)"] == Decimal("0")


# ── Override semantics ──────────────────────────────────────────────────────


def test_an_override_replaces_the_rate_only_inside_its_own_subtree() -> None:
    """The base of each line is asserted, not just the total.

    Fit-out is 400,000 of a 1,000,000 bill and carries 4 % overhead instead of
    the company's 10 %. The company line must therefore be computed on the
    600,000 that is left, and the exception on the 400,000 that is scoped, so
    that neither line is charged for the other's work.
    """
    fitout = _pos("0", is_section=True)
    fitout_leaf = _pos("400000", parent_id=fitout.id)
    shell = _pos("600000")
    company = _mk("Overhead", percentage="10", sort_order=1)
    exception = _mk(
        "Overhead (fit-out)",
        percentage="4",
        sort_order=1,
        scope_position_id=fitout.id,
        overrides_id=company.id,
    )

    results = _calculate_markup_amounts_scoped(Decimal("1000000"), [company, exception], [fitout, fitout_leaf, shell])

    amounts = _amounts(results)
    assert amounts["Overhead"] == Decimal("60000")  # base 600,000 at 10 %
    assert amounts["Overhead (fit-out)"] == Decimal("16000")  # base 400,000 at 4 %
    # A single blanket rate would have been 100,000. The exception is worth
    # 24,000 to the bid, and that difference is the entire point of the feature.
    assert sum(amounts.values()) == Decimal("76000")


def test_an_override_keeps_the_place_of_the_line_it_replaces() -> None:
    """An exception changes a rate; it must not move the compounding order.

    The overriding line declares ``sort_order`` 99, which would put it after
    profit if its own order counted. It does not: it stands where the overhead
    line stood, so profit still compounds onto overhead and not the other way
    round. Both bases are asserted, because a wrong order still produces a
    plausible-looking total.
    """
    section = _pos("0", is_section=True)
    leaf = _pos("1000000", parent_id=section.id)
    overhead = _mk("Overhead", percentage="10", sort_order=1)
    profit = _mk("Profit", percentage="5", apply_to="cumulative", sort_order=2, category="profit")
    exception = _mk(
        "Overhead (civils)",
        percentage="20",
        sort_order=99,
        scope_position_id=section.id,
        overrides_id=overhead.id,
    )

    results = _calculate_markup_amounts_scoped(Decimal("1000000"), [overhead, profit, exception], [section, leaf])

    amounts = _amounts(results)
    assert amounts["Overhead"] == Decimal("0")  # replaced everywhere it applied
    assert amounts["Overhead (civils)"] == Decimal("200000")  # base 1,000,000 at 20 %
    # Profit is cumulative and must see 1,000,000 + 200,000, never 1,000,000.
    assert amounts["Profit"] == Decimal("60000")


def test_a_scoped_line_with_nothing_to_override_is_an_addition() -> None:
    """A per-trade extra takes its own sort_order because it replaces nothing."""
    section = _pos("0", is_section=True)
    leaf = _pos("400000", parent_id=section.id)
    other = _pos("600000")
    overhead = _mk("Overhead", percentage="10", sort_order=1)
    profit = _mk("Profit", percentage="5", apply_to="cumulative", sort_order=3, category="profit")
    extra = _mk(
        "Scaffold levy",
        percentage="2",
        sort_order=2,
        scope_position_id=section.id,
        category="other",
    )

    results = _calculate_markup_amounts_scoped(Decimal("1000000"), [overhead, profit, extra], [section, leaf, other])

    amounts = _amounts(results)
    assert amounts["Scaffold levy"] == Decimal("8000")  # 400,000 at 2 %, that section only
    # Profit is cumulative, so in the scoped bucket it sees 400,000 + 40,000 +
    # 8,000 and in the unscoped one 600,000 + 60,000.
    assert amounts["Overhead"] == Decimal("100000")
    assert amounts["Profit"] == Decimal("22400") + Decimal("33000")


def test_a_nearer_scope_beats_a_wider_one_and_the_wider_one_still_applies() -> None:
    """Nesting reads the way it looks: phase override, trade override inside it.

    The trade override wins on overhead inside its own subtree. The phase
    override still applies to the rest of the phase, and the company line still
    applies to everything outside both.
    """
    phase = _pos("0", is_section=True)
    trade = _pos("0", parent_id=phase.id, is_section=True)
    trade_leaf = _pos("200000", parent_id=trade.id)
    phase_leaf = _pos("300000", parent_id=phase.id)
    outside = _pos("500000")

    company = _mk("Overhead", percentage="10", sort_order=1)
    phase_rate = _mk(
        "Overhead (phase 2)",
        percentage="8",
        sort_order=1,
        scope_position_id=phase.id,
        overrides_id=company.id,
    )
    trade_rate = _mk(
        "Overhead (mechanical)",
        percentage="3",
        sort_order=1,
        scope_position_id=trade.id,
        overrides_id=company.id,
    )

    results = _calculate_markup_amounts_scoped(
        Decimal("1000000"),
        [company, phase_rate, trade_rate],
        [phase, trade, trade_leaf, phase_leaf, outside],
    )

    amounts = _amounts(results)
    assert amounts["Overhead"] == Decimal("50000")  # base 500,000 at 10 %
    assert amounts["Overhead (phase 2)"] == Decimal("24000")  # base 300,000 at 8 %
    assert amounts["Overhead (mechanical)"] == Decimal("6000")  # base 200,000 at 3 %


def test_an_override_pointing_at_a_line_that_is_not_bill_wide_still_prices() -> None:
    """A dangling override becomes an addition rather than disappearing.

    ``overrides_id`` is ``ON DELETE SET NULL``, so a deleted company line
    leaves the section's own number standing. Until the row is cleaned up the
    money it carries has to keep showing, because silently dropping a line an
    estimator entered is worse than showing one that no longer replaces
    anything.
    """
    section = _pos("0", is_section=True)
    leaf = _pos("400000", parent_id=section.id)
    other = _pos("600000")
    company = _mk("Overhead", percentage="10", sort_order=1)
    orphan = _mk(
        "Overhead (fit-out)",
        percentage="4",
        sort_order=1,
        scope_position_id=section.id,
        overrides_id=uuid.uuid4(),  # names nothing on this bill
    )

    results = _calculate_markup_amounts_scoped(Decimal("1000000"), [company, orphan], [section, leaf, other])

    amounts = _amounts(results)
    assert amounts["Overhead"] == Decimal("100000")  # still charged on the whole bill
    assert amounts["Overhead (fit-out)"] == Decimal("16000")  # and the orphan adds on top


# ── The two pure helpers, on their own ──────────────────────────────────────


def test_scope_chain_returns_ancestors_outermost_first() -> None:
    root = uuid.uuid4()
    middle = uuid.uuid4()
    leaf = uuid.uuid4()
    parent_of = {leaf: middle, middle: root, root: None}

    assert _scope_chain(leaf, parent_of, {root, middle}) == (root, middle)
    assert _scope_chain(leaf, parent_of, {middle}) == (middle,)
    assert _scope_chain(leaf, parent_of, {uuid.uuid4()}) == ()


def test_scope_chain_stops_on_a_parent_cycle() -> None:
    """A corrupt tree must terminate the walk, not spin in it."""
    first = uuid.uuid4()
    second = uuid.uuid4()
    parent_of = {first: second, second: first}

    assert _scope_chain(first, parent_of, {second}) == (second,)


def test_effective_stack_is_the_bill_wide_stack_when_nothing_is_scoped() -> None:
    bill_wide = [_mk("A", sort_order=1), _mk("B", sort_order=2)]

    assert _effective_stack(bill_wide, {}, ()) == bill_wide
