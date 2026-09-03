# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What actually happened against each bill position, read back from the site.

The Cost Spine rollup answers this question already, and answers it in the
language of money: per cost line, what was budgeted, committed, contracted and
claimed. That is the right shape for a cost report and the wrong shape for the
person who wrote the estimate. An estimator works in bill positions, sees a
quantity and a rate, and wants one row per item of work.

So this module turns the rollup around. It is keyed by ``boq_position_id``, it
carries the position's own ordinal, description and unit, and it puts two
physical facts next to the money that the cost line does not hold:

* how much of the item is installed, from the progress module's latest
  percent-complete observation for that position;
* how much material was consumed against it and what that material cost, from
  the site inventory ledger;
* how many hours the crew and the plant booked against it, from approved field
  timesheets.

Which lets one row say the thing nobody could see before: you billed 120 m3 at
180, you have committed 1800 of it, the crew reports 40 percent installed, the
store has issued 55 m3 worth 9900 against it, and the gang has booked 21 hours
on it.

Hours, and the denominator under them
-------------------------------------

Booked hours are the half of the productivity question the platform can know.
The other half, what the estimate predicted, lives in the norm the line was
priced from. This file used to say that nothing records which norm that was.
That was wrong by one hop and stayed wrong long enough to be quoted as the
reason the predicted side was left out: a position built by applying an
assembly carries ``metadata["assembly_id"]``, and an assembly built from a
production norm carries its ``norm_id``, so the norm was always reachable
through the assembly row. What was missing was anybody making that hop, and a
hop through a row that can be edited or deleted after the fact is not
provenance anyway. A position now carries ``metadata["norm_id"]`` directly.

This module still reports only the measured side. Reading the predicted side
is a change to what it computes, not to what it can reach, and it is worth
doing separately rather than folding into the row that already exists.

Even the measured side has a trap in the denominator. Hours divided by the
BILLED quantity on a half-built item reads better the less of the item is
finished, which is the same failure as a zero risk dispersion: an item nobody
has touched would post the best productivity on the project. So the per-unit
figure is reported against the INSTALLED quantity and is None on any position
whose progress nobody has reported. A rate with no denominator is not a rate,
and a blank says so where a number would lie.

Two spines, met in one row
--------------------------

Assembling this means crossing the two links the platform keeps separate, and
the crossing is the reason this file exists rather than the numbers being read
ad hoc wherever they are wanted. The money aggregates are keyed by
``cost_line_id``; progress and inventory are keyed by ``boq_position_id``. The
position carries the cost line it rolls up into, and that field is the only
bridge between them. Nothing here writes either link, and no money value is
looked up by position or physical value by cost line.
``app.modules.procurement.cost_spine`` sets out why the two exist.

Positions off the spine
-----------------------

A position whose ``cost_line_id`` is unset gets a row with its estimate and its
physical progress and zeros for every money column. That is honest rather than
empty: the crew's work is real whether or not the project has generated a cost
spine, and a row that vanished for want of a link would read as no work done.
The ``on_cost_spine`` flag says which of the two a zero is.

Currency
--------

Every money value arrives already converted into the project base currency by
the aggregates in ``CostSpineRepository``, which convert per row so a missing
rate surfaces rather than silently zeroing. Consumed cost is summed from the
inventory ledger in the currency the movements were recorded in and is NOT
converted, because a stock movement carries no currency of its own; on a
project whose stock is valued in one currency, which is every project we have
seen, that is the base currency too. The response says which currency it is
reporting in rather than leaving the reader to assume.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

#: Money is quantised to two places on the way out, quantities to four, which
#: matches ``site_inventory.ledger`` and keeps a rate of 0.0001 from being
#: rounded away before it is multiplied by a quantity.
_MONEY_Q = Decimal("0.01")
_QTY_Q = Decimal("0.0001")
_PCT_Q = Decimal("0.01")
#: Hours to two places, matching ``field_time.field_time_math``, so a figure
#: does not change shape between the module that recorded it and this one.
_HOURS_Q = Decimal("0.01")
#: Hours per unit to four places: a norm of 0.30 h/m2 is quoted to two, and a
#: measured rate needs more room than the target it is compared against.
_RATE_Q = Decimal("0.0001")
_ZERO = Decimal("0")


def _to_decimal(raw: object) -> Decimal:
    """Parse a stored value into a Decimal, treating unusable input as zero.

    BOQ money and quantities are stored as strings, and an estimate that has
    never been filled in holds "" rather than "0". A read model must not 500 on
    that.
    """
    if raw is None:
        return _ZERO
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw).strip() or "0")
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO


@dataclass(frozen=True)
class PositionActuals:
    """One bill position with everything recorded against it.

    Money is in the project base currency. Quantities are in the position's own
    unit; ``consumed_quantity`` is only comparable with ``estimate_quantity``
    when the store issues material in that same unit, which is why both the
    unit and the raw numbers are reported rather than a ratio.
    """

    boq_position_id: uuid.UUID
    ordinal: str = ""
    description: str = ""
    unit: str = ""

    cost_line_id: uuid.UUID | None = None
    cost_line_code: str = ""

    estimate_quantity: Decimal = _ZERO
    estimate_unit_rate: Decimal = _ZERO
    estimate_amount: Decimal = _ZERO

    budget_planned: Decimal = _ZERO
    budget_actual: Decimal = _ZERO
    committed_amount: Decimal = _ZERO
    contracted_amount: Decimal = _ZERO
    claimed_amount: Decimal = _ZERO

    installed_percent: Decimal | None = None
    installed_amount: Decimal = _ZERO

    consumed_quantity: Decimal = _ZERO
    consumed_amount: Decimal = _ZERO

    labour_hours: Decimal = _ZERO
    plant_hours: Decimal = _ZERO

    @property
    def labour_hours_per_installed_unit(self) -> Decimal | None:
        """Booked labour hours per unit of work actually in place.

        None when the crew has not reported progress on this position, or has
        reported none, or the position carries no quantity. Those are three
        different reasons and all three make the same point: there is no
        denominator, so there is no rate. Reporting hours over the BILLED
        quantity instead would make every half-built item look fast and every
        untouched item look fastest of all.
        """
        if self.installed_percent is None or self.installed_percent <= _ZERO:
            return None
        installed_quantity = self.estimate_quantity * self.installed_percent / Decimal("100")
        if installed_quantity <= _ZERO:
            return None
        return (self.labour_hours / installed_quantity).quantize(_RATE_Q)

    @property
    def on_cost_spine(self) -> bool:
        """Whether the money columns can mean anything for this position."""
        return self.cost_line_id is not None

    @property
    def uncommitted_amount(self) -> Decimal:
        """Estimate not yet committed to a purchase order.

        The number the founder asked for by name. Negative means more has been
        ordered against the item than was estimated for it, which is a finding
        rather than an error, so it is reported signed rather than floored.
        """
        return (self.estimate_amount - self.committed_amount).quantize(_MONEY_Q)


@dataclass
class PositionActualsReport:
    """Every requested position, plus the project totals over them."""

    currency: str = ""
    rows: list[PositionActuals] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, Decimal]:
        keys = (
            "estimate_amount",
            "budget_planned",
            "budget_actual",
            "committed_amount",
            "contracted_amount",
            "claimed_amount",
            "installed_amount",
            "consumed_amount",
        )
        out = {k: sum((getattr(r, k) for r in self.rows), _ZERO) for k in keys}
        out["uncommitted_amount"] = out["estimate_amount"] - out["committed_amount"]
        totals = {k: v.quantize(_MONEY_Q) for k, v in out.items()}
        # Hours quantise to their own scale rather than to money's. No project
        # total for hours per unit: adding up rates over positions in different
        # units would produce a number with no unit at all.
        for key in ("labour_hours", "plant_hours"):
            totals[key] = sum((getattr(r, key) for r in self.rows), _ZERO).quantize(_HOURS_Q)
        return totals

    @property
    def positions_off_spine(self) -> int:
        """How many rows carry no cost line, and so no money.

        Reported rather than left to be counted, because a page of zeros has
        two very different causes and this is the one the reader can act on:
        generate the cost spine.
        """
        return sum(1 for r in self.rows if not r.on_cost_spine)


def assemble_rows(
    positions: list[object],
    *,
    budget: dict[str, dict[str, Decimal]],
    committed: dict[str, Decimal],
    contracted: dict[str, Decimal],
    claimed: dict[str, Decimal],
    cost_line_codes: dict[str, str],
    installed_pct: dict[uuid.UUID, float],
    consumed: dict[uuid.UUID, tuple[Decimal, Decimal]],
    booked_hours: dict[uuid.UUID, tuple[Decimal, Decimal]] | None = None,
) -> list[PositionActuals]:
    """Join the aggregates onto the positions. Pure, so it can be tested alone.

    ``positions`` are BOQ ``Position`` rows, taken as plain objects so this
    function needs neither the ORM nor a session. Each aggregate is keyed the
    way its own module keys it: money by cost-line id as a string, physical
    facts by position id.
    """
    rows: list[PositionActuals] = []
    for pos in positions:
        cost_line_id = getattr(pos, "cost_line_id", None)
        key = str(cost_line_id) if cost_line_id is not None else ""
        line_budget = budget.get(key, {})

        estimate_amount = _to_decimal(getattr(pos, "total", None))
        pct_raw = installed_pct.get(pos.id)
        installed_percent = Decimal(str(pct_raw)).quantize(_PCT_Q) if pct_raw is not None else None
        installed_amount = (
            (estimate_amount * installed_percent / Decimal("100")).quantize(_MONEY_Q)
            if installed_percent is not None
            else _ZERO
        )
        consumed_qty, consumed_amount = consumed.get(pos.id, (_ZERO, _ZERO))
        labour_hours, plant_hours = (booked_hours or {}).get(pos.id, (_ZERO, _ZERO))

        rows.append(
            PositionActuals(
                boq_position_id=pos.id,
                ordinal=getattr(pos, "ordinal", "") or "",
                description=getattr(pos, "description", "") or "",
                unit=getattr(pos, "unit", "") or "",
                cost_line_id=cost_line_id,
                cost_line_code=cost_line_codes.get(key, ""),
                estimate_quantity=_to_decimal(getattr(pos, "quantity", None)).quantize(_QTY_Q),
                estimate_unit_rate=_to_decimal(getattr(pos, "unit_rate", None)),
                estimate_amount=estimate_amount.quantize(_MONEY_Q),
                budget_planned=line_budget.get("planned", _ZERO).quantize(_MONEY_Q),
                budget_actual=line_budget.get("actual", _ZERO).quantize(_MONEY_Q),
                committed_amount=committed.get(key, _ZERO).quantize(_MONEY_Q),
                contracted_amount=contracted.get(key, _ZERO).quantize(_MONEY_Q),
                claimed_amount=claimed.get(key, _ZERO).quantize(_MONEY_Q),
                installed_percent=installed_percent,
                installed_amount=installed_amount,
                consumed_quantity=consumed_qty.quantize(_QTY_Q),
                consumed_amount=consumed_amount.quantize(_MONEY_Q),
                labour_hours=labour_hours.quantize(_HOURS_Q),
                plant_hours=plant_hours.quantize(_HOURS_Q),
            )
        )
    return rows


async def consumption_by_position(
    session: AsyncSession,
    project_id: uuid.UUID,
    position_ids: list[uuid.UUID],
) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """Quantity and value consumed against each position, in one grouped query.

    Only ``CONSUMPTION`` movements count. Waste is deliberately excluded: it is
    material that left the store without becoming part of the works, and adding
    it here would report an item as further advanced than it is. The site
    inventory module reports waste separately and that is where it belongs.

    The movement's own ``quantity`` and ``unit_cost`` are non-negative
    magnitudes; direction lives in ``movement_type``, so there is nothing to
    sign-correct here.
    """
    if not position_ids:
        return {}

    from app.modules.site_inventory.ledger import MovementType
    from app.modules.site_inventory.models import StockMovement

    stmt = (
        select(
            StockMovement.boq_position_id,
            func.sum(StockMovement.quantity),
            func.sum(StockMovement.quantity * StockMovement.unit_cost),
        )
        .where(
            StockMovement.project_id == project_id,
            StockMovement.movement_type == MovementType.CONSUMPTION.value,
            StockMovement.boq_position_id.in_(position_ids),
        )
        .group_by(StockMovement.boq_position_id)
    )
    rows = (await session.execute(stmt)).all()
    return {row[0]: (_to_decimal(row[1]), _to_decimal(row[2])) for row in rows}


async def hours_by_position(
    session: AsyncSession,
    project_id: uuid.UUID,
    position_ids: list[uuid.UUID],
) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """Labour and plant hours booked against each position, in one grouped query.

    Only approved timesheets count, and only those that have not been reversed.
    That single condition is what makes a corrected day net to nothing, and it
    is worth spelling out because the obvious filter gets it exactly backwards.
    Correcting an approved timesheet does not edit it: the original flips to
    ``reversed`` and a mirror sheet is written with ``reverses_id`` set and its
    hours still POSITIVE, because in this module the sign lives on the sheet
    and not on the row (see ``field_time_math.net_hours``). Filter on
    ``status == 'approved'`` alone and the original drops out while its mirror
    is counted at face value, so a day that was cancelled reports its hours
    twice over - once, in full, in the wrong direction. Excluding sheets that
    reverse something removes both halves and leaves zero, which is what a
    cancelled day is worth.

    Draft and submitted sheets are excluded too. Hours nobody has approved are
    a proposal, and an estimate compared against proposals is compared against
    nothing.

    Labour and plant come back separately because they answer different
    questions and only one of them is a productivity norm. A line is one or the
    other by a CHECK constraint, so nothing is counted twice and nothing that
    is neither is counted at all.
    """
    if not position_ids:
        return {}

    from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine

    labour = func.sum(case((FieldTimesheetLine.resource_id.isnot(None), FieldTimesheetLine.hours), else_=0))
    plant = func.sum(case((FieldTimesheetLine.equipment_id.isnot(None), FieldTimesheetLine.hours), else_=0))
    stmt = (
        select(FieldTimesheetLine.boq_position_id, labour, plant)
        .join(FieldTimesheet, FieldTimesheetLine.timesheet_id == FieldTimesheet.id)
        .where(
            FieldTimesheet.project_id == project_id,
            FieldTimesheet.status == "approved",
            FieldTimesheet.reverses_id.is_(None),
            FieldTimesheetLine.boq_position_id.in_(position_ids),
        )
        .group_by(FieldTimesheetLine.boq_position_id)
    )
    rows = (await session.execute(stmt)).all()
    return {row[0]: (_to_decimal(row[1]), _to_decimal(row[2])) for row in rows}


async def _cost_line_codes(
    session: AsyncSession,
    project_id: uuid.UUID,
    cost_line_ids: set[uuid.UUID],
) -> dict[str, str]:
    """Map ``str(cost_line_id) -> code`` for lines of this project, in one query."""
    if not cost_line_ids:
        return {}
    from app.modules.costmodel.models import CostLine

    stmt = select(CostLine.id, CostLine.code).where(
        CostLine.project_id == project_id,
        CostLine.id.in_(sorted(cost_line_ids)),
    )
    return {str(row[0]): row[1] for row in (await session.execute(stmt)).all()}


async def _project_currency(session: AsyncSession, project_id: uuid.UUID) -> str:
    """The project's base currency, or "" when it has none.

    Best-effort on purpose, mirroring the same lookup in procurement and BOQ: a
    read model must not fail because the currency could not be read, and an
    empty string is an honest unknown where a hardcoded EUR would be a wrong
    answer (task #217).
    """
    from app.modules.projects.models import Project

    try:
        value = (await session.execute(select(Project.currency).where(Project.id == project_id))).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - the currency is a label, not a value
        return ""
    return (value or "").strip().upper()


async def build_position_actuals(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    boq_id: uuid.UUID | None = None,
    position_ids: list[uuid.UUID] | None = None,
    offset: int = 0,
    limit: int = 200,
) -> PositionActualsReport:
    """Assemble the report for a project, optionally narrowed to some positions.

    A fixed number of queries regardless of how many positions come back: the
    positions themselves, then one grouped aggregate each for budget, purchase
    orders, contracts, claims, progress, consumption and booked hours.
    Narrowing happens before the aggregates run, so a drawer asking about one
    position does not pay for the whole project.
    """
    from app.modules.boq.repository import PositionRepository
    from app.modules.costmodel.repository import CostSpineRepository
    from app.modules.progress.repository import ProgressRepository

    position_repo = PositionRepository(session)
    if position_ids:
        positions = await position_repo.list_by_ids(position_ids)
        # list_by_ids does not know about projects, and an id from another
        # project would otherwise be reported with this project's money.
        boq_projects = await position_repo.project_ids_for_boqs(sorted({p.boq_id for p in positions}))
        positions = [p for p in positions if boq_projects.get(p.boq_id) == project_id]
        positions.sort(key=lambda p: (p.ordinal or "", p.sort_order))
    elif boq_id is not None:
        positions = await position_repo.list_all_for_boq(boq_id)
        boq_projects = await position_repo.project_ids_for_boqs([boq_id])
        if boq_projects.get(boq_id) != project_id:
            positions = []
    else:
        positions = await position_repo.list_for_project(project_id)
        positions = positions[offset : offset + limit]

    report = PositionActualsReport()
    if not positions:
        return report

    spine_repo = CostSpineRepository(session)
    budget = await spine_repo.budget_aggregate_by_cost_line(project_id)
    committed = await spine_repo.po_committed_by_cost_line(project_id)
    contracted = await spine_repo.contract_value_by_cost_line(project_id)
    claimed = await spine_repo.claimed_to_date_by_cost_line(project_id)

    # Resolve the codes from the ids the positions themselves carry rather than
    # from the generator's by-position index: a position may point at a cost
    # line that was created by hand and so has no ``boq_position_id`` of its
    # own, and that line still has a code worth showing. Scoping the lookup to
    # the project means a dangling or foreign link simply comes back without a
    # code instead of borrowing another project's.
    cost_line_codes = await _cost_line_codes(
        session, project_id, {p.cost_line_id for p in positions if p.cost_line_id is not None}
    )

    ids = [p.id for p in positions]
    installed_pct = await ProgressRepository(session).latest_pct_for_positions(project_id, ids)
    consumed = await consumption_by_position(session, project_id, ids)
    booked_hours = await hours_by_position(session, project_id, ids)

    report.rows = assemble_rows(
        list(positions),
        budget=budget,
        committed=committed,
        contracted=contracted,
        claimed=claimed,
        cost_line_codes=cost_line_codes,
        installed_pct=installed_pct,
        consumed=consumed,
        booked_hours=booked_hours,
    )
    report.currency = await _project_currency(session, project_id)
    return report
