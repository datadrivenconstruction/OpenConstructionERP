# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure computation core for on-site material metering and stock.

Materials arrive on site (a goods receipt), get installed against a BoQ position
(consumption), are lost to breakage or theft (waste / shrinkage), or move between
storage locations (transfer). This module turns a flat list of such movements
into the numbers a site engineer and a cost controller need: stock on hand,
inventory turnover and days-on-hand, the waste ratio, and the material-cost
variance of what was actually consumed against what the estimate budgeted per
position.

Everything here is a plain value object plus a set of functions. It is
``Decimal``-exact and carries no ORM, database or FastAPI dependency, exactly
like :mod:`app.modules.postcalc.model`, so the whole core is trivially
constructed and asserted from plain values. The DB loaders that build
:class:`Movement` lists and the per-position budgets live in
:mod:`app.modules.site_inventory.service`.

Sign convention for stock on hand (the signed sum of movements):

* ``INBOUND``      adds to stock (+quantity)
* ``CONSUMPTION``  removes from stock (-quantity)
* ``WASTE``        removes from stock (-quantity)
* ``TRANSFER``     nets to zero for the whole project (material only relocates);
                   for a single location it is -quantity at the source and
                   +quantity at the destination.

Money is never a float: quantities and unit costs are :class:`decimal.Decimal`
throughout and every division is guarded, returning ``None`` rather than raising
when the denominator is zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

# Quantisation quanta - quantities to 4 dp, money to 2 dp, ratios to 6 dp,
# percentages and day counts to 2 dp. Matches the platform-wide convention used
# by ``postcalc`` and ``price_breakdown``.
_QTY_Q = Decimal("0.0001")
_MONEY_Q = Decimal("0.01")
_RATIO_Q = Decimal("0.000001")
_PCT_Q = Decimal("0.01")
_DAYS_Q = Decimal("0.01")

_ZERO = Decimal("0")


class MovementType(StrEnum):
    """The four kinds of stock movement recorded on site."""

    INBOUND = "INBOUND"  # material received into a storage location
    CONSUMPTION = "CONSUMPTION"  # material installed / used against a BoQ position
    WASTE = "WASTE"  # breakage, shrinkage, off-cut, theft
    TRANSFER = "TRANSFER"  # relocation between two storage locations


# Signed multiplier applied to a movement's (positive) quantity when rolling up
# the whole-project stock on hand. TRANSFER nets to zero because the material
# never leaves the project - it only changes location.
_ONHAND_SIGN: dict[str, Decimal] = {
    MovementType.INBOUND.value: Decimal("1"),
    MovementType.CONSUMPTION.value: Decimal("-1"),
    MovementType.WASTE.value: Decimal("-1"),
    MovementType.TRANSFER.value: _ZERO,
}


def _as_decimal(value: Decimal | str | int | None) -> Decimal:
    """Coerce a value to :class:`Decimal`, treating ``None`` as zero.

    Accepts a ``Decimal`` (returned unchanged), or a ``str`` / ``int`` that
    ``Decimal`` can parse. A ``float`` is deliberately routed through ``str`` so
    a caller that ignores the type hint still cannot inject binary-float noise
    into a money figure.
    """
    if value is None:
        return _ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _movement_type_value(movement_type: str | MovementType) -> str:
    """Return the canonical string value of a movement type."""
    return movement_type.value if isinstance(movement_type, MovementType) else str(movement_type)


@dataclass(frozen=True)
class Movement:
    """One stock movement, as consumed by the pure functions here.

    A DB-free projection of a persisted ``StockMovement`` row. ``quantity`` and
    ``unit_cost`` are always non-negative magnitudes; the direction of a
    movement comes from its ``movement_type`` via the sign convention above, not
    from a negative quantity.
    """

    movement_type: str
    quantity: Decimal
    unit_cost: Decimal = _ZERO
    # Currency of ``unit_cost``. Carried so a valuation can be bucketed by it
    # rather than blending two currencies into one meaningless total; blank
    # means the money on this movement is unlabelled.
    currency: str = ""
    item_id: str | None = None
    location_id: str | None = None
    to_location_id: str | None = None
    boq_position_id: str | None = None
    occurred_at: datetime | None = None

    @property
    def line_cost(self) -> Decimal:
        """Extended cost of this movement = ``quantity * unit_cost``."""
        return _as_decimal(self.quantity) * _as_decimal(self.unit_cost)


@dataclass(frozen=True)
class PositionVariance:
    """Material-cost variance of one BoQ position: actual consumed vs budget."""

    position_id: str
    budgeted_cost: Decimal
    actual_cost: Decimal
    variance: Decimal  # actual - budget; positive means over budget
    variance_pct: Decimal | None  # None when the budget is zero (guarded)
    consumed_quantity: Decimal

    @property
    def is_over_budget(self) -> bool:
        """True when more was spent on the material than the estimate allowed."""
        return self.variance > _ZERO

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view (money 2 dp, quantity 4 dp, percentage 2 dp)."""
        return {
            "position_id": self.position_id,
            "budgeted_cost": _q(self.budgeted_cost, _MONEY_Q),
            "actual_cost": _q(self.actual_cost, _MONEY_Q),
            "variance": _q(self.variance, _MONEY_Q),
            "variance_pct": _q(self.variance_pct, _PCT_Q),
            "consumed_quantity": _q(self.consumed_quantity, _QTY_Q),
            "is_over_budget": self.is_over_budget,
        }


@dataclass(frozen=True)
class MaterialVarianceSummary:
    """Project rollup of the per-position material-cost variance."""

    total_budgeted_cost: Decimal
    total_actual_cost: Decimal
    total_variance: Decimal
    variance_pct: Decimal | None
    position_count: int
    over_budget_count: int
    lines: list[PositionVariance] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view of the whole variance report."""
        return {
            "total_budgeted_cost": _q(self.total_budgeted_cost, _MONEY_Q),
            "total_actual_cost": _q(self.total_actual_cost, _MONEY_Q),
            "total_variance": _q(self.total_variance, _MONEY_Q),
            "variance_pct": _q(self.variance_pct, _PCT_Q),
            "position_count": self.position_count,
            "over_budget_count": self.over_budget_count,
            "lines": [line.to_dict() for line in self.lines],
        }


def _q(value: Decimal | None, quant: Decimal) -> str | None:
    """Quantise a ``Decimal`` to a string, passing ``None`` through unchanged."""
    if value is None:
        return None
    return str(value.quantize(quant, rounding=ROUND_HALF_UP))


def safe_div(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Divide two ``Decimal`` values, returning ``None`` when dividing by zero.

    The single guarded-division primitive every ratio in this module is built
    on, so "undefined" is represented uniformly as ``None`` and never as a raised
    ``ZeroDivisionError`` or a silent zero.
    """
    if denominator == _ZERO:
        return None
    return numerator / denominator


def signed_quantity(movement: Movement) -> Decimal:
    """Signed stock-on-hand contribution of a single movement.

    An unknown movement type contributes zero rather than raising, so a stray
    row can never poison a whole-project rollup; write-time validation (the
    schema ``Literal``) is what rejects bad types at the edge.
    """
    sign = _ONHAND_SIGN.get(_movement_type_value(movement.movement_type), _ZERO)
    return sign * _as_decimal(movement.quantity)


def stock_on_hand(movements: Iterable[Movement]) -> Decimal:
    """Whole-project stock on hand as the signed sum of every movement.

    Empty input yields ``Decimal('0')`` (nothing received, nothing on hand).
    """
    total = _ZERO
    for movement in movements:
        total += signed_quantity(movement)
    return total


def stock_on_hand_by_item(movements: Iterable[Movement]) -> dict[str, Decimal]:
    """Stock on hand per ``item_id`` (movements with no item id are ignored)."""
    totals: dict[str, Decimal] = {}
    for movement in movements:
        if movement.item_id is None:
            continue
        totals[movement.item_id] = totals.get(movement.item_id, _ZERO) + signed_quantity(movement)
    return totals


def stock_on_hand_by_location(movements: Iterable[Movement]) -> dict[str | None, Decimal]:
    """Stock on hand per storage location.

    Unlike the whole-project view, a ``TRANSFER`` is not net zero here: it
    subtracts its quantity from the source ``location_id`` and adds it to the
    destination ``to_location_id`` so each location's balance is correct.
    """
    totals: dict[str | None, Decimal] = {}
    for movement in movements:
        mtype = _movement_type_value(movement.movement_type)
        qty = _as_decimal(movement.quantity)
        if mtype == MovementType.TRANSFER.value:
            totals[movement.location_id] = totals.get(movement.location_id, _ZERO) - qty
            totals[movement.to_location_id] = totals.get(movement.to_location_id, _ZERO) + qty
            continue
        delta = _ONHAND_SIGN.get(mtype, _ZERO) * qty
        totals[movement.location_id] = totals.get(movement.location_id, _ZERO) + delta
    return totals


def location_delta(movement: Movement, location_id: str | None) -> Decimal:
    """Signed contribution of one movement to a single location's stock.

    For an ``INBOUND`` / ``CONSUMPTION`` / ``WASTE`` the movement only touches its
    own ``location_id``. A ``TRANSFER`` touches two: it subtracts at the source
    ``location_id`` and adds at the destination ``to_location_id``.
    """
    mtype = _movement_type_value(movement.movement_type)
    qty = _as_decimal(movement.quantity)
    if mtype == MovementType.TRANSFER.value:
        delta = _ZERO
        if movement.location_id == location_id:
            delta -= qty
        if movement.to_location_id == location_id:
            delta += qty
        return delta
    if movement.location_id != location_id:
        return _ZERO
    return _ONHAND_SIGN.get(mtype, _ZERO) * qty


def stock_on_hand_by_item_at_location(
    movements: Iterable[Movement],
    location_id: str | None,
) -> dict[str, Decimal]:
    """Stock on hand per ``item_id`` within a single storage location.

    Only movements that touch the location (as source or transfer destination)
    contribute, so the result lists exactly the items seen at that location.
    """
    totals: dict[str, Decimal] = {}
    for movement in movements:
        if movement.item_id is None:
            continue
        if movement.location_id != location_id and movement.to_location_id != location_id:
            continue
        totals[movement.item_id] = totals.get(movement.item_id, _ZERO) + location_delta(movement, location_id)
    return totals


def total_quantity(movements: Iterable[Movement], movement_type: str | MovementType) -> Decimal:
    """Sum the (positive) quantity of every movement of a given type."""
    wanted = _movement_type_value(movement_type)
    total = _ZERO
    for movement in movements:
        if _movement_type_value(movement.movement_type) == wanted:
            total += _as_decimal(movement.quantity)
    return total


def total_inbound(movements: Iterable[Movement]) -> Decimal:
    """Total quantity received (all ``INBOUND`` movements)."""
    return total_quantity(movements, MovementType.INBOUND)


def total_consumed(movements: Iterable[Movement]) -> Decimal:
    """Total quantity installed / used (all ``CONSUMPTION`` movements)."""
    return total_quantity(movements, MovementType.CONSUMPTION)


def total_wasted(movements: Iterable[Movement]) -> Decimal:
    """Total quantity lost to waste / shrinkage (all ``WASTE`` movements)."""
    return total_quantity(movements, MovementType.WASTE)


def consumed_cost(movements: Iterable[Movement]) -> Decimal:
    """Total actual cost of consumed material = sum of ``quantity * unit_cost``."""
    total = _ZERO
    for movement in movements:
        if _movement_type_value(movement.movement_type) == MovementType.CONSUMPTION.value:
            total += _as_decimal(movement.quantity) * _as_decimal(movement.unit_cost)
    return total


def waste_ratio(movements: Iterable[Movement]) -> Decimal | None:
    """Waste as a fraction of consumption = ``total_wasted / total_consumed``.

    Returns ``None`` when nothing has been consumed yet (guarded division), so a
    project with waste but no recorded consumption reads "undefined" rather than
    dividing by zero. The materials do not need to be listed twice: waste and
    consumption are summed from the same movement list in a single pass each.
    """
    consumed = total_consumed(movements)
    return safe_div(total_wasted(movements), consumed)


def average_inventory(opening: Decimal, closing: Decimal) -> Decimal:
    """Simple average inventory over a period = ``(opening + closing) / 2``."""
    return (_as_decimal(opening) + _as_decimal(closing)) / Decimal("2")


def inventory_turnover(consumed: Decimal, avg_inventory: Decimal) -> Decimal | None:
    """Inventory turnover = ``consumed / average_inventory`` over a period.

    Returns ``None`` when the average inventory is zero or negative (guarded), so
    turnover is only reported when there is a stock base to turn over.
    """
    avg = _as_decimal(avg_inventory)
    if avg <= _ZERO:
        return None
    return _as_decimal(consumed) / avg


def days_on_hand(
    avg_inventory: Decimal,
    consumed: Decimal,
    period_days: Decimal | int,
) -> Decimal | None:
    """Inventory days on hand = ``average_inventory * period_days / consumed``.

    This is ``period_days / turnover`` re-expressed to avoid a second guarded
    division: it answers "at the current burn rate, how many days will the
    stock on hand last". Returns ``None`` when nothing has been consumed or the
    period is non-positive, since the burn rate is then undefined.
    """
    consumed_d = _as_decimal(consumed)
    period_d = _as_decimal(period_days)
    if consumed_d <= _ZERO or period_d <= _ZERO:
        return None
    return _as_decimal(avg_inventory) * period_d / consumed_d


def variance_pct(actual: Decimal, budget: Decimal) -> Decimal | None:
    """Percentage variance of an actual cost against a budget.

    ``(actual - budget) / budget * 100``. Positive means over budget. Returns
    ``None`` when the budget is zero (guarded division), which is the honest
    answer for consumption booked against a position that carries no estimate.
    """
    budget_d = _as_decimal(budget)
    ratio = safe_div(_as_decimal(actual) - budget_d, budget_d)
    if ratio is None:
        return None
    return ratio * Decimal("100")


def period_days(movements: Iterable[Movement]) -> Decimal | None:
    """Span in days between the earliest and latest dated movement.

    Convenience for deriving a turnover window straight from the ledger.
    Returns ``None`` when fewer than two movements carry an ``occurred_at``.
    """
    stamps = [m.occurred_at for m in movements if m.occurred_at is not None]
    if len(stamps) < 2:
        return None
    span = max(stamps) - min(stamps)
    return Decimal(str(span.total_seconds())) / Decimal("86400")


def material_cost_variance(
    movements: Iterable[Movement],
    budgets: Mapping[str, Decimal],
) -> list[PositionVariance]:
    """Per-position material-cost variance: actual consumed cost vs BoQ budget.

    Consumption movements are grouped by ``boq_position_id`` and their extended
    costs summed into the actual material spend for each position. That actual is
    then compared against the budgeted material cost the estimate carries for the
    position (supplied in ``budgets`` as ``position_id -> Decimal``).

    The returned lines cover the union of positions that were consumed against
    and positions that carry a budget, so both a budgeted position with no
    consumption (actual zero) and consumption against an unbudgeted position
    (``variance_pct`` is ``None``) are reported. Consumption with no
    ``boq_position_id`` cannot be attributed and is excluded. Lines are ordered
    by ``position_id`` for a stable report.
    """
    actual_cost: dict[str, Decimal] = {}
    consumed_qty: dict[str, Decimal] = {}
    for movement in movements:
        if _movement_type_value(movement.movement_type) != MovementType.CONSUMPTION.value:
            continue
        position_id = movement.boq_position_id
        if position_id is None:
            continue
        qty = _as_decimal(movement.quantity)
        actual_cost[position_id] = actual_cost.get(position_id, _ZERO) + qty * _as_decimal(movement.unit_cost)
        consumed_qty[position_id] = consumed_qty.get(position_id, _ZERO) + qty

    position_ids = sorted(set(actual_cost) | set(budgets))
    lines: list[PositionVariance] = []
    for position_id in position_ids:
        budget = _as_decimal(budgets.get(position_id))
        actual = actual_cost.get(position_id, _ZERO)
        lines.append(
            PositionVariance(
                position_id=position_id,
                budgeted_cost=budget,
                actual_cost=actual,
                variance=actual - budget,
                variance_pct=variance_pct(actual, budget),
                consumed_quantity=consumed_qty.get(position_id, _ZERO),
            ),
        )
    return lines


def summarize_variance(variances: Iterable[PositionVariance]) -> MaterialVarianceSummary:
    """Roll per-position variance lines up into a single project summary."""
    lines = list(variances)
    total_budget = sum((line.budgeted_cost for line in lines), _ZERO)
    total_actual = sum((line.actual_cost for line in lines), _ZERO)
    over_budget = sum(1 for line in lines if line.is_over_budget)
    return MaterialVarianceSummary(
        total_budgeted_cost=total_budget,
        total_actual_cost=total_actual,
        total_variance=total_actual - total_budget,
        variance_pct=variance_pct(total_actual, total_budget),
        position_count=len(lines),
        over_budget_count=over_budget,
        lines=lines,
    )


# -- Units -------------------------------------------------------------------
#
# A BoQ position carries a unit and a stock item carries a unit, and the two do
# not always agree: the estimate prices "m3" of concrete while the yard meters
# it in "m³", or the bill says "m2" of formwork while the store counts "pcs" of
# panels. Comparing a quantity across a disagreement is arithmetic on two
# different things, so every quantity comparison in this module is gated on the
# tri-state below and simply withheld when the units do not agree.


class UnitAgreement(StrEnum):
    """Whether two units may be compared as quantities of the same thing."""

    MATCH = "match"  # both known and equivalent after normalisation
    MISMATCH = "mismatch"  # both known and different - never compare
    UNKNOWN = "unknown"  # at least one side is blank - cannot confirm


# Superscript digits are folded to their ASCII form so "m³" and "m3" agree.
_UNIT_SUPERSCRIPTS = str.maketrans({"²": "2", "³": "3"})


def normalise_unit(unit: str | None) -> str:
    """Fold a unit label to the form used for comparison.

    Casefolds, drops all whitespace and trailing full stops, and folds the
    superscript digits so ``"m³"``, ``"M3 "`` and ``"m3."`` are one unit. This is
    deliberately conservative: it removes only differences of typography, never
    of meaning, so ``"m2"`` and ``"pcs"`` stay distinct.
    """
    if not unit:
        return ""
    folded = unit.translate(_UNIT_SUPERSCRIPTS).casefold()
    return "".join(folded.split()).rstrip(".")


def unit_agreement(left: str | None, right: str | None) -> UnitAgreement:
    """Compare two unit labels, distinguishing "differs" from "not stated".

    A blank on either side yields :attr:`UnitAgreement.UNKNOWN` rather than a
    mismatch: an unstated unit is not evidence of disagreement, but it is not
    evidence of agreement either, and a quantity comparison needs the latter.
    """
    left_n = normalise_unit(left)
    right_n = normalise_unit(right)
    if not left_n or not right_n:
        return UnitAgreement.UNKNOWN
    return UnitAgreement.MATCH if left_n == right_n else UnitAgreement.MISMATCH


def units_comparable(left: str | None, right: str | None) -> bool:
    """True only when two units are known to be the same unit."""
    return unit_agreement(left, right) is UnitAgreement.MATCH


# -- The item and position projections the reports need ----------------------


@dataclass(frozen=True)
class StockItemRef:
    """A DB-free projection of a stock item, as the reports here consume it."""

    item_id: str
    name: str = ""
    unit: str = ""
    boq_position_id: str | None = None
    procurement_req_item_id: str | None = None
    standard_unit_cost: Decimal | None = None
    currency: str = ""


@dataclass(frozen=True)
class PositionRef:
    """A DB-free projection of the BoQ position stock is bought against."""

    position_id: str
    ordinal: str = ""
    description: str = ""
    unit: str = ""
    quantity: Decimal = _ZERO
    unit_rate: Decimal = _ZERO
    total: Decimal = _ZERO

    @property
    def budget(self) -> Decimal:
        """Budgeted cost of the position: its stored total, else qty * rate."""
        stored = _as_decimal(self.total)
        if stored != _ZERO:
            return stored
        return _as_decimal(self.quantity) * _as_decimal(self.unit_rate)


@dataclass(frozen=True)
class OrderedRef:
    """Quantity ordered on the procurement line a stock item was bought on."""

    req_item_id: str
    unit: str = ""
    quantity_ordered: Decimal = _ZERO


# -- Effective position: the item's link stands in for the movement's --------


def item_position_map(items: Iterable[StockItemRef]) -> dict[str, str]:
    """Map ``item_id -> boq_position_id`` for the items that carry a link."""
    return {item.item_id: item.boq_position_id for item in items if item.boq_position_id}


def effective_position_id(
    movement: Movement,
    positions_by_item: Mapping[str, str],
) -> str | None:
    """The BoQ position a movement is attributed to.

    A movement's own ``boq_position_id`` wins when it is set - the storeman
    booked this delivery against that position explicitly. Otherwise the
    movement inherits the position of the item it moves, because an item linked
    to a position is material bought for that position and moving it is
    therefore activity against it.

    Resolving at read time rather than stamping the id at write time keeps the
    attribution correct when the item's link is later corrected, and means the
    movements recorded before a link existed are attributed too, instead of
    staying invisible forever.
    """
    if movement.boq_position_id:
        return movement.boq_position_id
    if movement.item_id is None:
        return None
    return positions_by_item.get(movement.item_id)


def resolve_positions(
    movements: Iterable[Movement],
    items: Iterable[StockItemRef],
) -> list[Movement]:
    """Return the movements with every ``boq_position_id`` resolved.

    The result feeds the existing per-position functions unchanged, so
    attribution lives in exactly one place. Callers must derive the set of
    positions they need budgets for from *this* list, never from the raw
    movements, or every inherited line is priced against a zero budget.
    """
    positions_by_item = item_position_map(items)
    resolved: list[Movement] = []
    for movement in movements:
        position_id = effective_position_id(movement, positions_by_item)
        if position_id == movement.boq_position_id:
            resolved.append(movement)
        else:
            resolved.append(replace(movement, boq_position_id=position_id))
    return resolved


# -- Valuation of the material standing on site ------------------------------


class ValuationBasis(StrEnum):
    """Where an item's valuation unit cost came from."""

    INBOUND_AVERAGE = "inbound_average"  # weighted average of what was paid
    STANDARD_COST = "standard_cost"  # the item's own standard unit cost
    NONE = "none"  # nothing to value it with


def average_inbound_unit_cost(movements: Iterable[Movement], item_id: str) -> Decimal | None:
    """Weighted-average unit cost of everything received for one item.

    ``sum(quantity * unit_cost) / sum(quantity)`` over the item's ``INBOUND``
    movements that carry a non-zero cost. Receipts booked at zero cost are left
    out of both sides rather than dragging the average down: a receipt with no
    price recorded is a missing price, not a free delivery. Returns ``None`` when
    no priced receipt exists.
    """
    value = _ZERO
    quantity = _ZERO
    for movement in movements:
        if _movement_type_value(movement.movement_type) != MovementType.INBOUND.value:
            continue
        if movement.item_id != item_id:
            continue
        cost = _as_decimal(movement.unit_cost)
        if cost <= _ZERO:
            continue
        qty = _as_decimal(movement.quantity)
        value += qty * cost
        quantity += qty
    return safe_div(value, quantity)


def item_valuation(
    movements: Iterable[Movement],
    item: StockItemRef,
) -> tuple[Decimal | None, ValuationBasis]:
    """The unit cost used to value an item's stock, and where it came from.

    Prefers the weighted average actually paid on receipt; falls back to the
    item's ``standard_unit_cost``; reports ``None`` when the item carries neither,
    so unvalued stock is counted and named rather than silently valued at zero.
    """
    average = average_inbound_unit_cost(movements, item.item_id)
    if average is not None:
        return average, ValuationBasis.INBOUND_AVERAGE
    standard = item.standard_unit_cost
    if standard is not None and _as_decimal(standard) > _ZERO:
        return _as_decimal(standard), ValuationBasis.STANDARD_COST
    return None, ValuationBasis.NONE


def price_unpriced_consumption(
    movements: Iterable[Movement],
    items: Iterable[StockItemRef],
) -> list[Movement]:
    """Return the movements with zero-cost consumption valued at the item's valuation cost.

    A consumption booked without a price (the API default is ``0``) would add
    nothing to the actual spend and make a position read under budget. It is
    valued at what the item was received for, else its standard cost; with
    neither it stays at zero because there is nothing honest to value it by.
    """
    movement_list = list(movements)
    by_item = {item.item_id: item for item in items}
    priced: list[Movement] = []
    for movement in movement_list:
        item = by_item.get(movement.item_id) if movement.item_id is not None else None
        if (
            item is None
            or _movement_type_value(movement.movement_type) != MovementType.CONSUMPTION.value
            or _as_decimal(movement.unit_cost) > _ZERO
        ):
            priced.append(movement)
            continue
        cost, _basis = item_valuation(movement_list, item)
        priced.append(movement if cost is None else replace(movement, unit_cost=cost))
    return priced


def item_currency(movements: Iterable[Movement], item: StockItemRef) -> str:
    """The currency an item's stock is valued in.

    The item's own currency when it states one, else the first currency seen on
    one of its receipts. A blank result means the money is unlabelled, which is
    why :func:`unfixed_value` buckets by this string instead of adding
    everything into one total.
    """
    if item.currency:
        return item.currency
    for movement in movements:
        if movement.item_id != item.item_id:
            continue
        if _movement_type_value(movement.movement_type) != MovementType.INBOUND.value:
            continue
        if movement.currency:
            return movement.currency
    return ""


@dataclass(frozen=True)
class UnfixedItemValue:
    """Value of one item's material standing on site, not yet installed."""

    item_id: str
    name: str
    unit: str
    on_hand: Decimal
    unit_cost: Decimal | None
    value: Decimal | None
    currency: str
    valuation_basis: str
    boq_position_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view (quantity 4 dp, money 2 dp)."""
        return {
            "item_id": self.item_id,
            "name": self.name,
            "unit": self.unit,
            "on_hand": _q(self.on_hand, _QTY_Q),
            "unit_cost": _q(self.unit_cost, _MONEY_Q),
            "value": _q(self.value, _MONEY_Q),
            "currency": self.currency,
            "valuation_basis": self.valuation_basis,
            "boq_position_id": self.boq_position_id,
        }


@dataclass(frozen=True)
class UnfixedValueSummary:
    """Project rollup of the value of unfixed material standing on site."""

    lines: list[UnfixedItemValue] = field(default_factory=list)
    totals_by_currency: dict[str, Decimal] = field(default_factory=dict)
    unvalued_item_count: int = 0

    @property
    def is_single_currency(self) -> bool:
        """True when every valued line shares one currency (a total is safe)."""
        return len(self.totals_by_currency) <= 1

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view; totals stay split per currency, never blended."""
        return {
            "lines": [line.to_dict() for line in self.lines],
            "totals_by_currency": [
                {"currency": code, "value": _q(value, _MONEY_Q)}
                for code, value in sorted(self.totals_by_currency.items())
            ],
            "unvalued_item_count": self.unvalued_item_count,
            "is_single_currency": self.is_single_currency,
        }


def unfixed_value(
    movements: Iterable[Movement],
    items: Iterable[StockItemRef],
) -> UnfixedValueSummary:
    """Value the material that is on site and not yet installed.

    For each item: ``stock on hand * valuation unit cost``. Stock on hand is
    already net of consumption and waste, so what is valued here is exactly the
    material that has been paid for and is still standing in the yard - the
    figure a cost controller needs when the certificate asks what is on site
    unfixed.

    Totals are bucketed by currency code and never blended: two items priced in
    different currencies have no common sum, and one invented total is worse
    than two honest ones. Items with nothing to value them by are counted in
    ``unvalued_item_count`` so the report says how much of the stock it could
    not price instead of quietly valuing it at zero.
    """
    movement_list = list(movements)
    on_hand = stock_on_hand_by_item(movement_list)

    lines: list[UnfixedItemValue] = []
    totals: dict[str, Decimal] = {}
    unvalued = 0
    for item in items:
        quantity = on_hand.get(item.item_id, _ZERO)
        if quantity == _ZERO:
            continue
        unit_cost, basis = item_valuation(movement_list, item)
        currency = item_currency(movement_list, item)
        value = quantity * unit_cost if unit_cost is not None else None
        if value is None:
            unvalued += 1
        else:
            totals[currency] = totals.get(currency, _ZERO) + value
        lines.append(
            UnfixedItemValue(
                item_id=item.item_id,
                name=item.name,
                unit=item.unit,
                on_hand=quantity,
                unit_cost=unit_cost,
                value=value,
                currency=currency,
                valuation_basis=basis.value,
                boq_position_id=item.boq_position_id,
            ),
        )
    lines.sort(key=lambda line: line.item_id)
    return UnfixedValueSummary(
        lines=lines,
        totals_by_currency=totals,
        unvalued_item_count=unvalued,
    )


# -- Ordered against delivered against the bill ------------------------------


@dataclass(frozen=True)
class PositionCoverage:
    """What one BoQ position has ordered, delivered, installed and left over.

    Every quantity here is a magnitude in some unit, and the three units in play
    (the bill's, the store's and the purchase order's) need not agree. The two
    agreement flags say which comparisons were safe to make; the derived figures
    they gate are ``None`` when they were not.
    """

    position_id: str
    ordinal: str
    description: str
    bill_unit: str
    bill_quantity: Decimal
    inventory_unit: str
    bill_unit_agreement: str
    order_unit_agreement: str
    ordered_quantity: Decimal | None
    delivered_quantity: Decimal
    consumed_quantity: Decimal
    wasted_quantity: Decimal
    on_hand_quantity: Decimal
    outstanding_quantity: Decimal | None
    delivered_pct: Decimal | None
    installed_pct: Decimal | None
    item_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view (quantities 4 dp, percentages 2 dp)."""
        return {
            "position_id": self.position_id,
            "ordinal": self.ordinal,
            "description": self.description,
            "bill_unit": self.bill_unit,
            "bill_quantity": _q(self.bill_quantity, _QTY_Q),
            "inventory_unit": self.inventory_unit,
            "bill_unit_agreement": self.bill_unit_agreement,
            "order_unit_agreement": self.order_unit_agreement,
            "ordered_quantity": _q(self.ordered_quantity, _QTY_Q),
            "delivered_quantity": _q(self.delivered_quantity, _QTY_Q),
            "consumed_quantity": _q(self.consumed_quantity, _QTY_Q),
            "wasted_quantity": _q(self.wasted_quantity, _QTY_Q),
            "on_hand_quantity": _q(self.on_hand_quantity, _QTY_Q),
            "outstanding_quantity": _q(self.outstanding_quantity, _QTY_Q),
            "delivered_pct": _q(self.delivered_pct, _PCT_Q),
            "installed_pct": _q(self.installed_pct, _PCT_Q),
            "item_ids": list(self.item_ids),
        }


def _pct_of_bill(
    quantity: Decimal,
    bill_quantity: Decimal,
    agreement: UnitAgreement,
) -> Decimal | None:
    """A store quantity as a percentage of the bill quantity, unit-gated.

    Normally withheld unless the two units are known to match. The exception is
    a zero quantity: nothing has arrived, and nothing is nothing in every unit,
    so ``0%`` is exact rather than a comparison across a mismatch. Without that
    exception a coverage report reads "unknown" on precisely the positions where
    nothing has been delivered, which is the one answer it exists to give.
    """
    if quantity == _ZERO:
        return _ZERO if bill_quantity != _ZERO else None
    if agreement is not UnitAgreement.MATCH:
        return None
    ratio = safe_div(quantity, bill_quantity)
    return ratio * Decimal("100") if ratio is not None else None


def _distinct_unit(units: Iterable[str]) -> str:
    """The one unit a group of items shares, or ``""`` when they differ.

    Two stock items feeding one position in different units have no single
    inventory unit, and saying so as a blank is what makes the comparison read
    UNKNOWN rather than silently picking one of them.
    """
    seen = {normalise_unit(u): u for u in units if normalise_unit(u)}
    if len(seen) != 1:
        return ""
    return next(iter(seen.values()))


def position_coverage(
    movements: Iterable[Movement],
    items: Iterable[StockItemRef],
    positions: Mapping[str, PositionRef],
    ordered: Mapping[str, OrderedRef] | None = None,
) -> list[PositionCoverage]:
    """Per-position: how much was ordered, delivered, installed and is left.

    Answers the two questions an inventory is kept for. How much of what we
    bought is still to arrive is ``ordered - delivered``; what is standing on
    site against this position is ``delivered - consumed - wasted``, which is the
    signed stock on hand of the items linked to it.

    ``movements`` must already have been through :func:`resolve_positions`.
    ``ordered`` maps ``req_item_id -> OrderedRef`` and may be empty, in which
    case the ordered leg simply reads as unknown rather than zero - a position
    with no requisition line behind it has not ordered nothing, we just do not
    know.

    Unit discipline: ``delivered_pct`` and ``installed_pct`` compare a store
    quantity against the bill quantity and are only produced when the two units
    are known to match. ``outstanding_quantity`` compares a store quantity
    against a purchase-order quantity and is gated on its own agreement flag.
    Where a comparison was refused the figure is ``None``; the raw quantities are
    still reported, because they are true on their own.
    """
    item_list = list(items)
    movement_list = list(movements)
    ordered_map = dict(ordered or {})

    items_by_position: dict[str, list[StockItemRef]] = {}
    for item in item_list:
        if item.boq_position_id:
            items_by_position.setdefault(item.boq_position_id, []).append(item)

    # Quantities are summed from the movements, grouped by resolved position, so
    # a movement booked straight against a position still counts even when its
    # item carries no link of its own.
    delivered: dict[str, Decimal] = {}
    consumed: dict[str, Decimal] = {}
    wasted: dict[str, Decimal] = {}
    on_hand: dict[str, Decimal] = {}
    moved_units: dict[str, list[str]] = {}
    units_by_item = {item.item_id: item.unit for item in item_list}
    for movement in movement_list:
        position_id = movement.boq_position_id
        if not position_id:
            continue
        mtype = _movement_type_value(movement.movement_type)
        qty = _as_decimal(movement.quantity)
        if mtype == MovementType.INBOUND.value:
            delivered[position_id] = delivered.get(position_id, _ZERO) + qty
        elif mtype == MovementType.CONSUMPTION.value:
            consumed[position_id] = consumed.get(position_id, _ZERO) + qty
        elif mtype == MovementType.WASTE.value:
            wasted[position_id] = wasted.get(position_id, _ZERO) + qty
        on_hand[position_id] = on_hand.get(position_id, _ZERO) + signed_quantity(movement)
        if movement.item_id is not None:
            moved_units.setdefault(position_id, []).append(units_by_item.get(movement.item_id, ""))

    position_ids = sorted(set(items_by_position) | set(on_hand) | set(positions))
    rows: list[PositionCoverage] = []
    for position_id in position_ids:
        position = positions.get(position_id)
        linked_items = items_by_position.get(position_id, [])
        inventory_unit = _distinct_unit(
            [item.unit for item in linked_items] or moved_units.get(position_id, []),
        )
        bill_unit = position.unit if position is not None else ""
        bill_quantity = _as_decimal(position.quantity) if position is not None else _ZERO

        # The ordered leg: sum the requisition lines behind the linked items.
        ordered_qty: Decimal | None = None
        ordered_units: list[str] = []
        for item in linked_items:
            ref = ordered_map.get(item.procurement_req_item_id or "")
            if ref is None:
                continue
            ordered_qty = (ordered_qty or _ZERO) + _as_decimal(ref.quantity_ordered)
            ordered_units.append(ref.unit)

        delivered_qty = delivered.get(position_id, _ZERO)
        bill_agreement = unit_agreement(bill_unit, inventory_unit)
        order_agreement = unit_agreement(_distinct_unit(ordered_units), inventory_unit)

        outstanding = None
        if ordered_qty is not None and order_agreement is UnitAgreement.MATCH:
            outstanding = ordered_qty - delivered_qty

        delivered_pct = _pct_of_bill(delivered_qty, bill_quantity, bill_agreement)
        installed_pct = _pct_of_bill(consumed.get(position_id, _ZERO), bill_quantity, bill_agreement)

        rows.append(
            PositionCoverage(
                position_id=position_id,
                ordinal=position.ordinal if position is not None else "",
                description=position.description if position is not None else "",
                bill_unit=bill_unit,
                bill_quantity=bill_quantity,
                inventory_unit=inventory_unit,
                bill_unit_agreement=bill_agreement.value,
                order_unit_agreement=order_agreement.value,
                ordered_quantity=ordered_qty,
                delivered_quantity=delivered_qty,
                consumed_quantity=consumed.get(position_id, _ZERO),
                wasted_quantity=wasted.get(position_id, _ZERO),
                on_hand_quantity=on_hand.get(position_id, _ZERO),
                outstanding_quantity=outstanding,
                delivered_pct=delivered_pct,
                installed_pct=installed_pct,
                item_ids=sorted(item.item_id for item in linked_items),
            ),
        )
    return rows
