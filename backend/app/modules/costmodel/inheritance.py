# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The cost line ("vector") travels down the chain, set once and inherited.

A bill position is put on its cost line once, by the planner, possibly split
over several (:class:`~app.modules.costmodel.models.PositionAllocation`). From
there every later record of the same work takes the same answer without anyone
coding it again:

    bill position
      └─ bid package line          (copied when the line is made from the position)
           └─ contract line        (written by the award, from the bid line or the position)
                ├─ change item     (from the line it changes, else the position, else the contract)
                ├─ claim line      (reads its contract line, never stores its own)
                └─ invoice line    (from the contract line it bills)

A row keeps one ``cost_line_id``, the line with the largest share, so every
reader written before splits existed still finds the main line. A row that
inherits a split also keeps the whole split in
:class:`~app.modules.costmodel.models.LineAllocation` (shares in percent adding
up to 100). Readers that sum money per cost line expand a row over its split
with :func:`expand`, which cuts the money to the cent with the largest
remainder rule, so a split never makes or loses a cent.

The answer is frozen when the row is written, the same way an order freezes
its cost line (see :mod:`app.modules.procurement.cost_spine`): re-pointing a
position tomorrow does not rewrite what last month's contract committed.

This module holds the arithmetic (pure, no database) and the small async
helpers every writer in the chain calls, so the bid, award, change, invoice
and cost-control paths cannot drift apart.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.structure import ZERO, split_amount

HUNDRED = Decimal("100")
#: ``LineAllocation.share`` holds six decimals.
SHARE_QUANTUM = Decimal("0.000001")

# The tables a LineAllocation row can belong to.
SOURCE_BID_LINE = "bid_line"
SOURCE_CONTRACT_LINE = "contract_line"
SOURCE_PO_ITEM = "po_item"
SOURCE_INVOICE_LINE = "invoice_line"
SOURCE_TYPES: tuple[str, ...] = (SOURCE_BID_LINE, SOURCE_CONTRACT_LINE, SOURCE_PO_ITEM, SOURCE_INVOICE_LINE)

# Where an inherited cost line came from (``ChangeOrderItem.cost_line_source``
# and the ``source`` of :class:`Inherited`).
FROM_CONTRACT_LINE = "contract_line"
FROM_POSITION = "position"
FROM_BID_LINE = "bid_line"
FROM_CONTRACT = "contract"
FROM_MANUAL = "manual"

#: ``metadata_`` key under which a row records that a person put it on another
#: cost line than the one it inherits: ``{"reason", "by", "at", "inherited"}``.
#: The same key the cost structure rule V5 reads on contract lines.
OVERRIDE_META_KEY = "cost_line_override"


@dataclass(frozen=True, slots=True)
class Vector:
    """Which cost lines a row's money goes to.

    ``main`` is the line with the largest share (the one ``cost_line_id``
    holds). ``shares`` is the split as ``(cost_line_id, fraction)`` with the
    fractions adding up to 1, empty when the row sits whole on ``main``.
    """

    main: str | None
    shares: tuple[tuple[str, Decimal], ...] = ()

    @property
    def is_split(self) -> bool:
        return len(self.shares) > 1

    @property
    def lines(self) -> frozenset[str]:
        """Every cost line the row touches."""
        if self.shares:
            return frozenset(lid for lid, _ in self.shares)
        return frozenset({self.main}) if self.main else frozenset()

    @property
    def empty(self) -> bool:
        return self.main is None and not self.shares


NO_VECTOR = Vector(main=None)


@dataclass(frozen=True, slots=True)
class Inherited:
    """An inherited vector and the kind of record it came from (``FROM_*``), or empty."""

    vector: Vector = NO_VECTOR
    source: str | None = None


def _dec(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value if value.is_finite() else ZERO
    try:
        out = Decimal(str(value if value not in (None, "") else "0"))
    except (ArithmeticError, ValueError):
        return ZERO
    return out if out.is_finite() else ZERO


def _key(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def vector_of(main: object, shares: Iterable[tuple[object, object]] = ()) -> Vector:
    """Build a vector from a row's ``cost_line_id`` and its stored shares (any positive weights).

    The weights are normalised to their own sum, so percent shares, partial
    quantities and fractions all read the same. A split with one line left is
    that line whole. ``main`` follows the largest share (the first one on a
    tie, in the order given) when there is a split, so a stale pointer cannot
    name a line the split no longer has.
    """
    rows = [(_key(lid), max(_dec(w), ZERO)) for lid, w in shares]
    rows = [(lid, w) for lid, w in rows if lid is not None]
    merged: dict[str, Decimal] = {}
    for lid, w in rows:
        merged[lid] = merged.get(lid, ZERO) + w
    weight = sum(merged.values(), ZERO)
    if len(merged) <= 1:
        only = next(iter(merged), None)
        return Vector(main=only or _key(main))
    if weight <= ZERO:
        fractions = {lid: Decimal(1) / Decimal(len(merged)) for lid in merged}
    else:
        fractions = {lid: w / weight for lid, w in merged.items()}
    ordered = tuple(fractions.items())
    biggest = max(ordered, key=lambda kv: kv[1])[1]
    head = next(lid for lid, f in ordered if f == biggest)
    return Vector(main=head, shares=ordered)


def percent_shares(vector: Vector) -> list[tuple[str, Decimal]]:
    """The split as stored percentages, six decimals, adding up to exactly 100.

    Largest remainder at the sixth decimal, the same rule :func:`expand` uses
    for cents, so storing a split and reading it back gives the same money.
    """
    if not vector.is_split:
        return []
    raw = [(lid, f * HUNDRED) for lid, f in vector.shares]
    floors = [(lid, v.quantize(SHARE_QUANTUM, rounding=ROUND_DOWN)) for lid, v in raw]
    missing = int(((HUNDRED - sum((v for _, v in floors), ZERO)) / SHARE_QUANTUM).to_integral_value())
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i][1] - floors[i][1]), i))
    out = [list(x) for x in floors]
    for i in order[:missing]:
        out[i][1] += SHARE_QUANTUM
    return [(str(lid), v) for lid, v in out]


def expand(amount: object, vector: Vector) -> list[tuple[str | None, Decimal]]:
    """Cut ``amount`` over the vector's cost lines; the parts add up to ``amount`` to the cent.

    A row on one line gives that line the whole amount, untouched (no rounding),
    so a reader that switched to :func:`expand` reports exactly what it did
    before. A row with no line gives ``(None, amount)``: money in suspense.
    """
    value = _dec(amount)
    if not vector.is_split:
        return [(vector.main, value)]
    parts = split_amount(value, [f for _, f in vector.shares])
    # split_amount works in cents; a four-decimal amount keeps its sub-cent rest on the main line.
    rest = value - sum(parts, ZERO)
    out: list[tuple[str | None, Decimal]] = []
    for (lid, _), part in zip(vector.shares, parts, strict=True):
        out.append((lid, part + (rest if lid == vector.main else ZERO)))
    return out


def first_inherited(candidates: Sequence[tuple[str, Vector | None]]) -> Inherited:
    """The first candidate that names a cost line, in the order of precedence given."""
    for source, vector in candidates:
        if vector is not None and not vector.empty:
            return Inherited(vector=vector, source=source)
    return Inherited()


def add_expanded(acc: dict[str, Decimal], amount: object, vector: Vector) -> Decimal:
    """Add ``amount`` to ``acc`` per cost line; returns the part that went to no line."""
    loose = ZERO
    for lid, part in expand(amount, vector):
        if lid is None:
            loose += part
        else:
            acc[lid] = acc.get(lid, ZERO) + part
    return loose


# ── Database helpers ─────────────────────────────────────────────────────────


async def position_vectors(session: AsyncSession, position_ids: Iterable[object]) -> dict[str, Vector]:
    """The vector of each bill position: its split when it has one, else its ``cost_line_id``."""
    from app.modules.boq.models import Position
    from app.modules.costmodel.models import PositionAllocation

    wanted = {uuid.UUID(str(p)) for p in position_ids if p}
    if not wanted:
        return {}
    pointers = dict(
        (await session.execute(select(Position.id, Position.cost_line_id).where(Position.id.in_(wanted)))).all()
    )
    rows = (
        await session.execute(
            select(PositionAllocation.position_id, PositionAllocation.cost_line_id, PositionAllocation.share)
            .where(PositionAllocation.position_id.in_(wanted))
            .order_by(PositionAllocation.position_id, PositionAllocation.cost_line_id)
        )
    ).all()
    shares: dict[str, list[tuple[object, object]]] = {}
    for pid, lid, share in rows:
        shares.setdefault(str(pid), []).append((lid, share))
    return {str(pid): vector_of(main, shares.get(str(pid), [])) for pid, main in pointers.items()}


async def row_vectors(session: AsyncSession, source_type: str, mains: dict[object, object]) -> dict[str, Vector]:
    """The vector of each row of one ``source_type``: ``mains`` maps row id to its ``cost_line_id``.

    One query for the whole set; a row without stored shares is its main line.
    """
    from app.modules.costmodel.models import LineAllocation

    ids = [uuid.UUID(str(k)) for k in mains if k]
    out = {str(k): Vector(main=_key(v)) for k, v in mains.items()}
    if not ids:
        return out
    shares: dict[str, list[tuple[object, object]]] = {}
    # Chunked so a large contract never builds an IN list past the driver's limit.
    for start in range(0, len(ids), 2000):
        rows = (
            await session.execute(
                select(LineAllocation.source_id, LineAllocation.cost_line_id, LineAllocation.share)
                .where(
                    LineAllocation.source_type == source_type, LineAllocation.source_id.in_(ids[start : start + 2000])
                )
                .order_by(LineAllocation.source_id, LineAllocation.cost_line_id)
            )
        ).all()
        for sid, lid, share in rows:
            shares.setdefault(str(sid), []).append((lid, share))
    for sid, rows_ in shares.items():
        out[sid] = vector_of(out.get(sid, NO_VECTOR).main, rows_)
    return out


async def row_vector(session: AsyncSession, source_type: str, source_id: object, main: object) -> Vector:
    return (await row_vectors(session, source_type, {source_id: main})).get(str(source_id), Vector(main=_key(main)))


async def write_split(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID,
    vector: Vector,
) -> uuid.UUID | None:
    """Store the split of one row (or remove it when the row sits on one line).

    The caller writes the returned main line into the row's own
    ``cost_line_id``; the two always go together.
    """
    from app.modules.costmodel.models import LineAllocation

    if source_type not in SOURCE_TYPES:
        raise ValueError(f"Unknown allocation source {source_type!r}")
    await session.execute(
        delete(LineAllocation).where(LineAllocation.source_type == source_type, LineAllocation.source_id == source_id)
    )
    for lid, pct in percent_shares(vector):
        session.add(
            LineAllocation(
                project_id=project_id,
                source_type=source_type,
                source_id=source_id,
                cost_line_id=uuid.UUID(lid),
                share=pct,
            )
        )
    return uuid.UUID(vector.main) if vector.main else None


async def drop_splits(session: AsyncSession, source_type: str, source_ids: Iterable[uuid.UUID]) -> None:
    """Forget the stored splits of rows that are deleted or put on a single line."""
    from app.modules.costmodel.models import LineAllocation

    ids = list(source_ids)
    if ids:
        await session.execute(
            delete(LineAllocation).where(LineAllocation.source_type == source_type, LineAllocation.source_id.in_(ids))
        )


async def lines_in_project(session: AsyncSession, project_id: uuid.UUID, line_ids: Iterable[object]) -> set[str]:
    """The ids among ``line_ids`` that are cost lines of ``project_id``."""
    from app.modules.costmodel.models import CostLine

    wanted = {uuid.UUID(str(x)) for x in line_ids if x}
    if not wanted:
        return set()
    rows = await session.execute(select(CostLine.id).where(CostLine.id.in_(wanted), CostLine.project_id == project_id))
    return {str(r) for (r,) in rows.all()}
