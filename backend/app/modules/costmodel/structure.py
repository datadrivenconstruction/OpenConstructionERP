# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost structure and allocation arithmetic, with no database in sight.

Two pieces of money logic every reader of the cost structure has to agree on,
so they live in one pure module the service, the validation rules and the
tests all call:

* **The tree total.** A node of the structure is worth what is posted on it,
  plus its own amount (an allowance the planner has not broken down yet), plus
  the totals of its children: ``total = own + posted + sum(children)``. A node
  is counted once however deep the tree is, and a cycle in the parent links
  (which the service refuses to write, but an imported database could carry)
  cannot make the sum loop.

* **The split of one bill position over several cost lines** (its "vector").
  Shares are either percentages adding up to 100 or partial quantities adding
  up to the position's quantity, within :data:`TOLERANCE` (0.01 %). The money
  each share carries is cut to the cent with the largest-remainder rule, so the
  parts always add up to the position total exactly and no cent appears or
  disappears in a report.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")

MODE_PERCENT = "percent"
MODE_QUANTITY = "quantity"
ALLOCATION_MODES: tuple[str, ...] = (MODE_PERCENT, MODE_QUANTITY)

#: How far the shares may miss their target, as a fraction of it: 0.01 %.
TOLERANCE = Decimal("0.0001")


class AllocationError(ValueError):
    """Shares that cannot be applied. ``problem`` is a stable key the UI translates."""

    def __init__(self, problem: str, **params: object) -> None:
        super().__init__(problem)
        self.problem = problem
        self.params = params


@dataclass(frozen=True, slots=True)
class ShareCheck:
    """How a set of shares compares with what they must add up to."""

    mode: str
    total: Decimal
    expected: Decimal
    difference: Decimal
    within_tolerance: bool


def _dec(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value if value.is_finite() else ZERO
    try:
        out = Decimal(str(value if value not in (None, "") else "0"))
    except (ArithmeticError, ValueError):
        return ZERO
    return out if out.is_finite() else ZERO


def check_shares(mode: str, shares: Sequence[object], quantity: object) -> ShareCheck:
    """Compare the shares with 100 (percent) or with the position quantity (quantity)."""
    total = sum((_dec(s) for s in shares), ZERO)
    expected = HUNDRED if mode == MODE_PERCENT else _dec(quantity)
    difference = total - expected
    allowed = abs(expected) * TOLERANCE
    return ShareCheck(
        mode=mode,
        total=total,
        expected=expected,
        difference=difference,
        within_tolerance=abs(difference) <= allowed,
    )


def fractions_of(mode: str, shares: Sequence[object], quantity: object) -> list[Decimal]:
    """The fraction of the position each share carries, after checking the shares.

    Raises:
        AllocationError: unknown mode, a share that is not positive, a quantity
            split of a position without quantity, or shares that miss their
            target by more than :data:`TOLERANCE`.
    """
    if mode not in ALLOCATION_MODES:
        raise AllocationError("unknown_mode", mode=mode)
    values = [_dec(s) for s in shares]
    if not values:
        raise AllocationError("no_shares")
    if any(v <= ZERO for v in values):
        raise AllocationError("share_not_positive")
    qty = _dec(quantity)
    if mode == MODE_QUANTITY and qty <= ZERO:
        raise AllocationError("quantity_split_without_quantity")
    check = check_shares(mode, values, qty)
    if not check.within_tolerance:
        raise AllocationError(
            "shares_do_not_add_up",
            mode=mode,
            total=str(check.total),
            expected=str(check.expected),
        )
    # Normalise to the shares' own sum so a split inside the tolerance still
    # hands out exactly the whole position and not 99.995 % of it.
    return [v / check.total for v in values]


def split_amount(total: object, fractions: Sequence[Decimal]) -> list[Decimal]:
    """Cut ``total`` into cent amounts proportional to ``fractions``; the parts add up to ``total``.

    Largest remainder: every part is first rounded down to the cent, then the
    cents still missing go one each to the parts that lost the most in rounding
    (the earlier part wins a tie, so the result is deterministic). A negative
    total (a credit position) is split as its absolute value and the sign put
    back, so a credit is cut the same way a charge is.
    """
    # Half away from zero, as the bill and the browser preview round a total to the cent.
    amount = _dec(total).quantize(CENT, rounding=ROUND_HALF_UP)
    if not fractions:
        return []
    sign = -1 if amount < ZERO else 1
    whole = abs(amount)
    weight = sum(fractions, ZERO)
    if weight <= ZERO:
        return [ZERO for _ in fractions]
    raw = [whole * f / weight for f in fractions]
    floors = [r.quantize(CENT, rounding=ROUND_DOWN) for r in raw]
    missing = int(((whole - sum(floors, ZERO)) / CENT).to_integral_value())
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), i))
    for i in order[:missing]:
        floors[i] += CENT
    return [f * sign for f in floors]


# ── Tree totals ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TreeNodeIn:
    """One account as the tree arithmetic needs it."""

    id: str
    parent_id: str | None
    own_amount: Decimal = ZERO
    posted: Decimal = ZERO


@dataclass(slots=True)
class TreeNodeTotals:
    """What the arithmetic says about one account."""

    level: int
    children: list[str] = field(default_factory=list)
    children_total: Decimal = ZERO
    total: Decimal = ZERO
    in_cycle: bool = False


def tree_totals(nodes: Iterable[TreeNodeIn]) -> dict[str, TreeNodeTotals]:
    """Level, children and ``total = own + posted + sum(children totals)`` for every node.

    A node whose parent is not in the set is a root. Nodes caught in a parent
    cycle are marked ``in_cycle``, treated as roots of their own (level 1) and
    their cycle links are not followed, so the sum is finite and every node is
    still counted exactly once.
    """
    by_id = {n.id: n for n in nodes}
    parent: dict[str, str | None] = {}
    in_cycle: set[str] = set()
    for node in by_id.values():
        parent[node.id] = node.parent_id if node.parent_id in by_id else None
    # Find cycles by walking up from every node.
    state: dict[str, int] = {}  # 1 = on the current path, 2 = done
    for start in by_id:
        path: list[str] = []
        current: str | None = start
        while current is not None and state.get(current, 0) == 0:
            state[current] = 1
            path.append(current)
            current = parent.get(current)
        if current is not None and state.get(current) == 1:
            in_cycle.update(path[path.index(current) :])
        for member in path:
            state[member] = 2
    for member in in_cycle:
        parent[member] = None

    out: dict[str, TreeNodeTotals] = {
        node_id: TreeNodeTotals(level=1, in_cycle=node_id in in_cycle) for node_id in by_id
    }
    for node_id, parent_id in parent.items():
        if parent_id is not None:
            out[parent_id].children.append(node_id)

    def _level(node_id: str) -> int:
        depth = 1
        current = parent.get(node_id)
        while current is not None:
            depth += 1
            current = parent.get(current)
        return depth

    for node_id in by_id:
        out[node_id].level = _level(node_id)
    # Children before parents: deepest first.
    for node_id in sorted(by_id, key=lambda n: -out[n].level):
        node = by_id[node_id]
        totals = out[node_id]
        totals.children_total = sum((out[c].total for c in totals.children), ZERO)
        totals.total = _dec(node.own_amount) + _dec(node.posted) + totals.children_total
    return out


# ── What each cost line carries from the bill ───────────────────────────────


@dataclass(frozen=True, slots=True)
class PositionView:
    """A bill position as the estimate of a cost line needs it."""

    id: str
    boq_id: str
    total: object
    quantity: object
    unit: str
    cost_line_id: str | None
    unit_rate: object = None


@dataclass(frozen=True, slots=True)
class AllocationView:
    """One stored share of a split position."""

    position_id: str
    cost_line_id: str
    mode: str
    share: object


@dataclass(slots=True)
class LineContribution:
    """The part of the bill a cost line carries: money, quantity, and from how many positions."""

    amount: Decimal = ZERO
    quantity: Decimal = ZERO
    units: set[str] = field(default_factory=set)
    positions: set[str] = field(default_factory=set)
    #: The untouched figures of the only position, when one whole position is all the line carries.
    single: tuple[object, object, object] | None = None


def share_fractions(rows: Sequence[AllocationView], quantity: object) -> list[Decimal]:
    """Fractions for stored shares, proportional to the shares themselves.

    Stored rows were checked when they were written, but a quantity split goes
    stale when the position's quantity is edited afterwards. Rather than lose or
    invent money, the position is then divided in proportion to the shares
    still on record, and the allocation rule reports that they no longer add up.
    """
    del quantity  # the shares' own sum is the reference, see above
    values = [max(_dec(r.share), ZERO) for r in rows]
    weight = sum(values, ZERO)
    if weight <= ZERO:
        return [Decimal(1) / Decimal(len(rows)) for _ in rows] if rows else []
    return [v / weight for v in values]


def line_contributions(
    positions: Iterable[PositionView],
    allocations: Iterable[AllocationView],
    *,
    line_boq: dict[str, str | None] | None = None,
) -> dict[str, LineContribution]:
    """What each cost line carries from the given positions, each position counted once.

    A position with stored shares is divided over their lines; a position without
    any goes whole to its ``cost_line_id``; a position with neither carries
    nothing (it is unallocated). ``line_boq`` names the bill that owns each line:
    a line owned by one bill takes nothing from the positions of another, which
    is what keeps a copied bill (whose positions keep their vectors) from
    counting the same work twice. A line missing from ``line_boq`` takes from
    every bill.
    """
    by_position: dict[str, list[AllocationView]] = {}
    for row in allocations:
        by_position.setdefault(row.position_id, []).append(row)
    owners = line_boq or {}
    out: dict[str, LineContribution] = {}

    def _take(line_id: str, pos: PositionView) -> bool:
        owner = owners.get(line_id)
        return owner is None or owner == pos.boq_id

    for pos in positions:
        if not pos.unit:
            continue
        rows = sorted(by_position.get(pos.id, []), key=lambda r: r.cost_line_id)
        if rows:
            fractions = share_fractions(rows, pos.quantity)
            amounts = split_amount(pos.total, fractions)
            qty = _dec(pos.quantity)
            for row, fraction, amount in zip(rows, fractions, amounts, strict=True):
                if not _take(row.cost_line_id, pos):
                    continue
                c = out.setdefault(row.cost_line_id, LineContribution())
                c.amount += amount
                c.quantity += _dec(row.share) if row.mode == MODE_QUANTITY else qty * fraction
                c.units.add(pos.unit)
                c.positions.add(pos.id)
                c.single = None
            continue
        if pos.cost_line_id and _take(pos.cost_line_id, pos):
            c = out.setdefault(pos.cost_line_id, LineContribution())
            first = not c.positions
            c.amount += _dec(pos.total)
            c.quantity += _dec(pos.quantity)
            c.units.add(pos.unit)
            c.positions.add(pos.id)
            c.single = (pos.quantity, pos.unit_rate, pos.total) if first else None
    return out


def estimate_fields(contribution: LineContribution | None, unit: str | None) -> dict[str, str]:
    """The ``estimate_*`` columns a cost line gets from what it carries.

    One whole position keeps its own figures as written, so a line generated
    from an unsplit position reads exactly as before splits existed. Anything
    else is summed: the quantity only when every part is in the line's unit,
    the rate as amount over quantity.
    """
    if contribution is None or not contribution.positions:
        return {"estimate_quantity": "0", "estimate_unit_rate": "0", "estimate_amount": "0"}
    amount = contribution.amount
    if contribution.single is not None:
        qty, rate, total = contribution.single
        return {
            "estimate_quantity": str(qty or "0"),
            "estimate_unit_rate": str(rate or "0"),
            "estimate_amount": str(total or "0"),
        }
    same_unit = bool(unit) and contribution.units == {unit}
    qty = contribution.quantity if same_unit else ZERO
    rate = (amount / qty).quantize(Decimal("0.0001")) if qty != ZERO else ZERO
    return {
        "estimate_quantity": str(qty.normalize()) if qty != ZERO else "0",
        "estimate_unit_rate": str(rate) if qty != ZERO else "0",
        "estimate_amount": str(amount),
    }
