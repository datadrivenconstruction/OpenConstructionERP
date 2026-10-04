# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Where an approved change order lands on the schedule of values, line by line.

A change order used to reach the schedule as one pooled line carrying its
whole amount, whatever its items said. A change that adds 40 m3 to the
concrete line and deletes a door then showed up as a new line called "CO-004"
next to an unchanged concrete line, so the line the work is measured and
billed on never grew, and percent complete on it was read against the wrong
scheduled value from that day on.

An item says which line it changes in one of two ways, both read from the
item's free-form metadata:

* ``contract_line_id`` names the schedule line outright.
* ``boq_position_id`` names the bill position the item was picked from (the
  change order item form stamps it), and the schedule line linked to that same
  position is the one it changes, when exactly one leaf line on this contract
  carries the link.

A reference to a line on another contract, to a roll-up parent, or to a
position two lines share is not followed; the item's money goes to the new
line instead and the reason is kept on the adjustment, so nothing is lost and
a person can see why.

The split, :func:`allocate`, is pure and decides three cases:

``pooled``
    No item references a line (or the change order has no items): one new
    line carries the whole amount, exactly as before.
``itemized``
    The items add up to the change order amount: every referenced line moves
    by the sum of its own items, and the items without a reference share one
    new line.
``pro_rata``
    The items add up to something else with the same sign (an engineer's
    figure, or a mirrored change order priced by its variation): each group's
    share is ``amount x group / items total``, cut toward zero to the cent;
    the cents that leaves over go one each to the groups that lost the most
    (largest remainder, ties in item order), and a part of a cent, when the
    amount is stated to four decimals, goes to the largest share. So the
    shares add up to the amount exactly, none is more than a cent from its
    exact value, and none changes sign.
``itemized_with_balance``
    The items add up to zero or to the opposite sign of the amount, where
    scaling would flip the direction of every item: the items move their
    lines as itemized and the difference goes on the new line.

Every share is posted in the transaction that moved the contract sum, under
the change's source key, so a replayed approval posts nothing and the
per-line deltas always add up to the amount the contract sum moved by.

A referenced line keeps ``quantity x unit_rate == total_value``, because the
claim generators price a line off quantity times rate (see
``auto_generate_claim_lines``) and a hand edit recomputes the total the same
way; a total moved on its own would never be billed, and the next edit would
throw it away. How a line is billed matters as much: a unit-price or
remeasurement contract (:data:`MEASURED_CONTRACT_TYPES`) bills measured
quantity times the line's rate, so a restated rate multiplies every later
measurement, while every other type bills a percent of quantity times rate.
:func:`placement` decides, in this order:

* a line whose total is its quantity times its rate takes the change as
  quantity at that rate, when the items state a quantity change (new less
  original quantity) in the line's unit and that quantity at the contract
  rate is exactly the share, fits the fourth decimal the column holds and
  does not take the line below zero. The quantity is the one the items state,
  never one worked out from the money: 1,000 on a 50 line is not 20 more
  units when the item repriced 100 units from 50 to 60;
* a lump sum line becomes quantity 1 at the new total: one priced in a lump
  sum unit at quantity 0 or 1, and on a contract billed by percent also any
  line at quantity 1, or at quantity 0 with no rate;
* anything else (a rate change, a pro-rata share, a measured line priced at
  an agreed figure, a cost-only change on a line billed by measurement) is not
  rewritten. The share goes on a new line beside it that names the line it
  adjusts, because restating a contract rate is a commercial decision this
  code does not make.

A deduction may take a line below what earlier claims billed on it. That is
posted as approved; the next claim's ``pay_application.line_overbilled``
check then blocks submission until a person settles the credit, which is the
decision it is.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
#: The scale of ``ContractLine.quantity``.
QUANTITY_QUANTUM = Decimal("0.0001")

METHOD_POOLED = "pooled"
METHOD_ITEMIZED = "itemized"
METHOD_PRO_RATA = "pro_rata"
METHOD_ITEMIZED_WITH_BALANCE = "itemized_with_balance"

#: Why an item's line reference was not followed.
UNRESOLVED_NOT_ON_CONTRACT = "line_not_on_contract"
UNRESOLVED_ROLL_UP = "roll_up_line"
UNRESOLVED_AMBIGUOUS_BOQ = "boq_position_on_several_lines"
UNRESOLVED_BAD_ID = "unreadable_line_id"

PLACE_LUMP_SUM = "lump_sum"
PLACE_QUANTITY = "quantity"
PLACE_LINKED_LINE = "linked_line"

#: ``ContractLine.metadata_`` key naming the line a linked adjustment line adjusts.
ADJUSTS_LINE_META_KEY = "adjusts_line_id"

#: Contract types billed as measured quantity x unit rate
#: (``generate_unit_price_claim``); every other type bills a percent.
MEASURED_CONTRACT_TYPES: frozenset[str] = frozenset({"unit_price", "remeasurement"})

#: Used when the bill of quantities module is not installed.
_FALLBACK_LUMP_SUM_UNITS: frozenset[str] = frozenset({"ls", "lsum", "lump sum", "lumpsum", "psch", "pauschal"})


def is_measured_contract(contract: Any) -> bool:
    """Whether ``contract`` bills measured quantity times the line rate."""
    return str(getattr(contract, "contract_type", "") or "") in MEASURED_CONTRACT_TYPES


def _is_lump_sum_unit(unit: object) -> bool:
    text = str(unit or "")
    try:
        from app.modules.boq.units import is_lump_sum_unit  # noqa: PLC0415
    except ImportError:  # pragma: no cover - the boq module is optional
        return text.strip().lower().rstrip(".") in _FALLBACK_LUMP_SUM_UNITS
    return is_lump_sum_unit(text)


def _unit_key(unit: object) -> str:
    return str(unit or "").strip().lower().rstrip(".")


@dataclass(frozen=True, slots=True)
class AllocationItem:
    """One change order item, as the allocator sees it.

    ``line_id`` is the schedule line it changes, already resolved, or None
    for the new line. ``unresolved`` says why a reference was not followed.
    ``quantity`` is the quantity change the item states (new less original
    quantity), in ``unit``.
    """

    weight: Decimal
    line_id: uuid.UUID | None = None
    item_id: str = ""
    unresolved: str | None = None
    quantity: Decimal = ZERO
    unit: str = ""


@dataclass(frozen=True, slots=True)
class LineShare:
    """What one schedule line, or the new line (``line_id`` None), takes.

    ``quantity`` is the quantity change its items state, summed, and
    ``units`` the units they state it in. A pro-rata share scales the money,
    never the quantity, so the two then no longer agree and the share is not
    written as quantity.
    """

    line_id: uuid.UUID | None
    delta: Decimal
    item_ids: tuple[str, ...] = ()
    quantity: Decimal = ZERO
    units: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Allocation:
    """A change order amount split over schedule lines.

    ``shares`` lists the referenced lines in the order their first item came,
    then the new line when it takes anything. The deltas add up to ``amount``
    exactly. ``unresolved`` maps item ids to why their reference was dropped.
    """

    amount: Decimal
    method: str
    shares: tuple[LineShare, ...]
    unresolved: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> Decimal:
        return sum((share.delta for share in self.shares), ZERO)

    @property
    def new_line_delta(self) -> Decimal:
        return sum((share.delta for share in self.shares if share.line_id is None), ZERO)


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


def _sign(value: Decimal) -> int:
    return (value > ZERO) - (value < ZERO)


def _largest_remainder(
    amount: Decimal, weighted: list[tuple[uuid.UUID | None, Decimal]], weight_total: Decimal
) -> dict[uuid.UUID | None, Decimal]:
    """``amount x weight / weight_total`` per key, in cents that add up to ``amount``.

    Every share is cut toward zero to the cent. The whole cents that leaves
    over go one each, in the direction of the leftover, to the shares that
    lost the most in that direction, ties in input order; so no share moves
    more than a cent from its exact value and none changes sign. A part of a
    cent (an amount stated to four decimals) goes to the largest share, the
    first one on a tie.
    """
    exact = {key: amount * weight / weight_total for key, weight in weighted}
    shares = {key: value.quantize(CENT, rounding=ROUND_DOWN) for key, value in exact.items()}
    left = amount - sum(shares.values(), ZERO)
    direction = _sign(left)
    if direction:
        cents = int(abs(left) / CENT)
        order = {key: index for index, (key, _weight) in enumerate(weighted)}
        candidates = sorted(
            (key for key in shares if _sign(exact[key] - shares[key]) == direction),
            key=lambda key: (-abs(exact[key] - shares[key]), order[key]),
        )
        for key in candidates[:cents]:
            shares[key] += CENT * direction
        left = amount - sum(shares.values(), ZERO)
        if left:
            biggest = max(shares, key=lambda key: (abs(shares[key]), -order[key]))
            shares[biggest] += left
    return shares


def allocate(amount: Decimal, items: Sequence[AllocationItem]) -> Allocation:
    """Split ``amount`` over the lines ``items`` reference; see the module docstring.

    Pure. A zero amount allocates nothing. The returned shares always add up to
    ``amount`` exactly, and a share of zero is left out.
    """
    amount = _money(amount)
    unresolved = {item.item_id: item.unresolved for item in items if item.unresolved}
    if amount == ZERO:
        return Allocation(amount=amount, method=METHOD_POOLED, shares=(), unresolved=unresolved)
    if not any(item.line_id is not None for item in items):
        ids = tuple(item.item_id for item in items if item.item_id)
        return Allocation(
            amount=amount,
            method=METHOD_POOLED,
            shares=(LineShare(line_id=None, delta=amount, item_ids=ids),),
            unresolved=unresolved,
        )

    # Group by target, referenced lines first in the order they appear, the
    # new line last.
    order: list[uuid.UUID | None] = []
    weights: dict[uuid.UUID | None, Decimal] = {}
    item_ids: dict[uuid.UUID | None, list[str]] = {}
    quantities: dict[uuid.UUID | None, Decimal] = {}
    units: dict[uuid.UUID | None, list[str]] = {}
    for item in sorted(items, key=lambda it: it.line_id is None):
        key = item.line_id
        if key not in weights:
            order.append(key)
            weights[key] = ZERO
            item_ids[key] = []
            quantities[key] = ZERO
            units[key] = []
        weights[key] += _money(item.weight)
        quantities[key] += _money(item.quantity)
        if item.item_id:
            item_ids[key].append(item.item_id)
        if item.unit and item.unit not in units[key]:
            units[key].append(item.unit)
    items_total = sum(weights.values(), ZERO)

    if items_total == amount:
        method = METHOD_ITEMIZED
        deltas = dict(weights)
    elif items_total != ZERO and _sign(items_total) == _sign(amount):
        method = METHOD_PRO_RATA
        deltas = _largest_remainder(amount, [(key, weights[key]) for key in order], items_total)
    else:
        method = METHOD_ITEMIZED_WITH_BALANCE
        deltas = dict(weights)
        if None not in deltas:
            order.append(None)
            item_ids[None] = []
            quantities[None] = ZERO
            units[None] = []
            deltas[None] = ZERO
        deltas[None] += amount - items_total

    shares = tuple(
        LineShare(
            line_id=key,
            delta=deltas[key],
            item_ids=tuple(item_ids[key]),
            quantity=quantities[key],
            units=tuple(units[key]),
        )
        for key in order
        if deltas[key] != ZERO
    )
    return Allocation(amount=amount, method=method, shares=shares, unresolved=unresolved)


@dataclass(frozen=True, slots=True)
class Placement:
    """How a share is written on a referenced line.

    For ``lump_sum`` and ``quantity`` the line takes ``quantity``,
    ``unit_rate`` and ``total_value`` as given; for ``linked_line`` the line is
    left alone and the share goes on a new line beside it.
    """

    kind: str
    quantity: Decimal | None = None
    unit_rate: Decimal | None = None
    total_value: Decimal | None = None
    delta_quantity: Decimal = ZERO


def placement(
    line: Any,
    delta: Decimal,
    *,
    quantity: Decimal = ZERO,
    units: Sequence[str] = (),
    measured: bool,
) -> Placement:
    """Decide how ``delta`` is written on ``line``; see the module docstring. Pure.

    ``quantity`` and ``units`` are what the share's items state
    (:attr:`LineShare.quantity`, :attr:`LineShare.units`); ``measured`` is
    whether the contract bills measured quantity times rate
    (:func:`is_measured_contract`).
    """
    line_quantity = _money(getattr(line, "quantity", 0))
    rate = _money(getattr(line, "unit_rate", 0))
    total = _money(getattr(line, "total_value", 0))
    unit = getattr(line, "unit", None)
    new_total = total + delta
    stated = _money(quantity)

    line_unit = _unit_key(unit)
    same_unit = not line_unit or all(_unit_key(u) in ("", line_unit) for u in units)
    if (
        stated != ZERO
        and rate != ZERO
        and same_unit
        and line_quantity * rate == total
        and stated * rate == delta
        and stated == stated.quantize(QUANTITY_QUANTUM)
        and line_quantity + stated >= ZERO
    ):
        return Placement(
            kind=PLACE_QUANTITY,
            quantity=line_quantity + stated,
            unit_rate=rate,
            total_value=new_total,
            delta_quantity=stated,
        )

    # A lump sum moves in money, not in units, so no quantity is recorded.
    # Never on a line whose items state a quantity: "item" and "kpl" are in
    # the lump-sum vocabulary and are still counted.
    lump_sum = stated == ZERO and line_quantity in (ZERO, ONE) and _is_lump_sum_unit(unit)
    if not measured:
        lump_sum = lump_sum or line_quantity == ONE or (line_quantity == ZERO and rate == ZERO)
    if lump_sum:
        return Placement(kind=PLACE_LUMP_SUM, quantity=ONE, unit_rate=new_total, total_value=new_total)
    return Placement(kind=PLACE_LINKED_LINE)


def resolve_items(raw_items: Sequence[Any], lines: Sequence[Any]) -> list[AllocationItem]:
    """Turn change order items into :class:`AllocationItem`, references resolved against ``lines``.

    ``lines`` are the contract's schedule lines. Only a leaf line can be
    referenced: a roll-up parent is summed from its children and is never
    billed. Each item carries the quantity change it states, new less
    original quantity, and its unit. Pure.
    """
    parents = {ln.parent_line_id for ln in lines if getattr(ln, "parent_line_id", None) is not None}
    leaf_ids = {ln.id for ln in lines if ln.id not in parents}
    all_ids = {ln.id for ln in lines}
    by_position: dict[str, list[uuid.UUID]] = {}
    for ln in lines:
        if ln.id not in leaf_ids:
            continue
        meta = getattr(ln, "metadata_", None)
        position = meta.get("boq_position_id") if isinstance(meta, dict) else None
        if position:
            by_position.setdefault(str(position), []).append(ln.id)

    resolved: list[AllocationItem] = []
    for raw in raw_items:
        meta = getattr(raw, "metadata_", None)
        meta = meta if isinstance(meta, dict) else {}
        item_id = str(getattr(raw, "id", "") or "")
        weight = _money(getattr(raw, "cost_delta", 0))
        stated = _money(getattr(raw, "new_quantity", 0)) - _money(getattr(raw, "original_quantity", 0))
        line_id: uuid.UUID | None = None
        reason: str | None = None
        explicit = meta.get("contract_line_id")
        if explicit:
            try:
                wanted = uuid.UUID(str(explicit))
            except (ValueError, TypeError, AttributeError):
                reason = UNRESOLVED_BAD_ID
            else:
                if wanted in leaf_ids:
                    line_id = wanted
                elif wanted in all_ids:
                    reason = UNRESOLVED_ROLL_UP
                else:
                    reason = UNRESOLVED_NOT_ON_CONTRACT
        elif meta.get("boq_position_id"):
            matches = by_position.get(str(meta["boq_position_id"]), [])
            if len(matches) == 1:
                line_id = matches[0]
            elif len(matches) > 1:
                reason = UNRESOLVED_AMBIGUOUS_BOQ
        resolved.append(
            AllocationItem(
                weight=weight,
                line_id=line_id,
                item_id=item_id,
                unresolved=reason,
                quantity=stated,
                unit=str(getattr(raw, "unit", "") or "").strip(),
            )
        )
    return resolved
