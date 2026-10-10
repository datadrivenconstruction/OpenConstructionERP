# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tax withholding data access.

Query and persistence only. Every decision - what the base is, which band a
party actually falls into, whether the figures hold together - lives in
:mod:`app.modules.tax_withholding.service`, so the arithmetic that decides how
much money leaves the business can be tested without a database.

No ``relationship()`` is declared in this module's models, so nothing here has
a lazy-loading strategy to choose: a deduction points at its regime and its
party standing by id and the service fetches what it needs. A statutory tax
line points at its header the same way. Filtering is on
real columns only - a ``.contains()`` against the JSON ``bands`` column would
compile to a string LIKE on PostgreSQL rather than to JSONB containment, so
bands are read whole and matched in Python.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tax_withholding.models import (
    STATUTORY_LINE_KINDS,
    PartyTaxStatus,
    ReverseChargeDetermination,
    StatutoryTaxCalc,
    StatutoryTaxLine,
    WithholdingDeduction,
    WithholdingRegime,
)

# ── Regimes ──────────────────────────────────────────────────────────────────


async def list_regimes(
    session: AsyncSession,
    *,
    country_code: str | None = None,
    active_only: bool = False,
) -> list[WithholdingRegime]:
    """Every scheme, newest country first, optionally filtered."""
    stmt = select(WithholdingRegime)
    if country_code:
        stmt = stmt.where(WithholdingRegime.country_code == country_code.upper())
    if active_only:
        stmt = stmt.where(WithholdingRegime.is_active.is_(True))
    stmt = stmt.order_by(WithholdingRegime.country_code.asc(), WithholdingRegime.scheme_code.asc())
    return list((await session.execute(stmt)).scalars().all())


async def get_regime(session: AsyncSession, regime_id: uuid.UUID) -> WithholdingRegime | None:
    """One scheme by id."""
    stmt = select(WithholdingRegime).where(WithholdingRegime.id == regime_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_regime_by_scheme(
    session: AsyncSession,
    *,
    country_code: str,
    scheme_code: str,
) -> WithholdingRegime | None:
    """One scheme by its country and code - the pair the seeder matches on."""
    stmt = select(WithholdingRegime).where(
        and_(
            WithholdingRegime.country_code == country_code.upper(),
            WithholdingRegime.scheme_code == scheme_code,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_regime(session: AsyncSession, regime: WithholdingRegime) -> WithholdingRegime:
    """Store a scheme."""
    session.add(regime)
    await session.flush()
    return regime


async def delete_regime(session: AsyncSession, regime: WithholdingRegime) -> None:
    """Remove a scheme. Deductions quoting it hold the FK, so the database refuses."""
    await session.delete(regime)
    await session.flush()


# ── Party tax status ─────────────────────────────────────────────────────────


async def list_party_statuses(
    session: AsyncSession,
    *,
    party_id: uuid.UUID | None = None,
    regime_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[PartyTaxStatus]:
    """Recorded standings, most recently valid first."""
    stmt = select(PartyTaxStatus)
    if party_id is not None:
        stmt = stmt.where(PartyTaxStatus.party_id == party_id)
    if regime_id is not None:
        stmt = stmt.where(PartyTaxStatus.regime_id == regime_id)
    if status:
        stmt = stmt.where(PartyTaxStatus.status == status)
    stmt = stmt.order_by(PartyTaxStatus.valid_from.desc(), PartyTaxStatus.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_party_status(session: AsyncSession, status_id: uuid.UUID) -> PartyTaxStatus | None:
    """One recorded standing by id."""
    stmt = select(PartyTaxStatus).where(PartyTaxStatus.id == status_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def current_party_status(
    session: AsyncSession,
    *,
    party_id: uuid.UUID,
    regime_id: uuid.UUID,
    on_date: date,
) -> PartyTaxStatus | None:
    """The standing whose window contains ``on_date``, latest window first.

    An open-ended standing (no ``valid_to``) qualifies for any date at or after
    its start. Note what this deliberately does *not* do: it does not filter on
    ``status``, so an expired row inside its own window is still returned and
    the caller gets to say so. Hiding it would turn "this certificate ran out"
    into "this party was never verified", and those are answered differently.
    """
    stmt = (
        select(PartyTaxStatus)
        .where(
            and_(
                PartyTaxStatus.party_id == party_id,
                PartyTaxStatus.regime_id == regime_id,
                PartyTaxStatus.valid_from <= on_date,
            )
        )
        .order_by(PartyTaxStatus.valid_from.desc(), PartyTaxStatus.created_at.desc())
    )
    for row in (await session.execute(stmt)).scalars().all():
        if row.valid_to is None or row.valid_to >= on_date:
            return row
    return None


async def expiring_party_statuses(
    session: AsyncSession,
    *,
    through: date,
    from_date: date,
) -> list[PartyTaxStatus]:
    """Standings whose window closes inside ``[from_date, through]``.

    The list a payment run needs before it is made rather than after: a
    verification lapsing mid-period moves the party to the higher band without
    anybody being told.
    """
    stmt = (
        select(PartyTaxStatus)
        .where(
            and_(
                PartyTaxStatus.valid_to.is_not(None),
                PartyTaxStatus.valid_to >= from_date,
                PartyTaxStatus.valid_to <= through,
            )
        )
        .order_by(PartyTaxStatus.valid_to.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def add_party_status(session: AsyncSession, row: PartyTaxStatus) -> PartyTaxStatus:
    """Store a standing."""
    session.add(row)
    await session.flush()
    return row


async def delete_party_status(session: AsyncSession, row: PartyTaxStatus) -> None:
    """Remove a standing. Deductions that quoted it keep their own copy of the band."""
    await session.delete(row)
    await session.flush()


# ── Deductions ───────────────────────────────────────────────────────────────


async def list_deductions(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    regime_id: uuid.UUID | None = None,
    status: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> list[WithholdingDeduction]:
    """Deductions, newest period first."""
    stmt = select(WithholdingDeduction)
    if project_id is not None:
        stmt = stmt.where(WithholdingDeduction.project_id == project_id)
    if regime_id is not None:
        stmt = stmt.where(WithholdingDeduction.regime_id == regime_id)
    if status:
        stmt = stmt.where(WithholdingDeduction.status == status)
    if period_start is not None:
        stmt = stmt.where(WithholdingDeduction.period_end >= period_start)
    if period_end is not None:
        stmt = stmt.where(WithholdingDeduction.period_start <= period_end)
    stmt = stmt.order_by(WithholdingDeduction.period_end.desc(), WithholdingDeduction.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_deduction(session: AsyncSession, deduction_id: uuid.UUID) -> WithholdingDeduction | None:
    """One deduction by id."""
    stmt = select(WithholdingDeduction).where(WithholdingDeduction.id == deduction_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_deduction(session: AsyncSession, row: WithholdingDeduction) -> WithholdingDeduction:
    """Store a deduction."""
    session.add(row)
    await session.flush()
    return row


async def delete_deduction(session: AsyncSession, row: WithholdingDeduction) -> None:
    """Remove a deduction."""
    await session.delete(row)
    await session.flush()


# ── Reverse charge ───────────────────────────────────────────────────────────


async def list_determinations(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    country_code: str | None = None,
    status: str | None = None,
) -> list[ReverseChargeDetermination]:
    """Reverse-charge determinations, newest first."""
    stmt = select(ReverseChargeDetermination)
    if project_id is not None:
        stmt = stmt.where(ReverseChargeDetermination.project_id == project_id)
    if country_code:
        stmt = stmt.where(ReverseChargeDetermination.country_code == country_code.upper())
    if status:
        stmt = stmt.where(ReverseChargeDetermination.status == status)
    stmt = stmt.order_by(ReverseChargeDetermination.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_determination(
    session: AsyncSession,
    determination_id: uuid.UUID,
) -> ReverseChargeDetermination | None:
    """One determination by id."""
    stmt = select(ReverseChargeDetermination).where(ReverseChargeDetermination.id == determination_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_determination_for_invoice(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    invoice_reference: str,
) -> ReverseChargeDetermination | None:
    """The determination for one invoice on one project, if there is one."""
    stmt = select(ReverseChargeDetermination).where(
        and_(
            ReverseChargeDetermination.project_id == project_id,
            ReverseChargeDetermination.invoice_reference == invoice_reference,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_determination(
    session: AsyncSession,
    row: ReverseChargeDetermination,
) -> ReverseChargeDetermination:
    """Store a determination."""
    session.add(row)
    await session.flush()
    return row


async def delete_determination(session: AsyncSession, row: ReverseChargeDetermination) -> None:
    """Remove a determination."""
    await session.delete(row)
    await session.flush()


# ── Statutory tax lines ──────────────────────────────────────────────────────


async def get_statutory_calc(
    session: AsyncSession,
    *,
    source_kind: str,
    source_id: uuid.UUID,
) -> StatutoryTaxCalc | None:
    """The statutory tax header of one source document, if one is stored.

    Matched on the kind and the id together. Two modules hand out their ids
    independently, so the same GUID under two kinds is two documents.
    """
    stmt = select(StatutoryTaxCalc).where(
        and_(
            StatutoryTaxCalc.source_kind == source_kind,
            StatutoryTaxCalc.source_id == source_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_statutory_calc(session: AsyncSession, row: StatutoryTaxCalc) -> StatutoryTaxCalc | None:
    """Store a header, or return ``None`` when another request stored it first.

    The insert runs inside a savepoint. Two saves of the same new document can
    both find nothing and both insert; the unique key lets one through, and the
    loser's savepoint is rolled back without taking the caller's transaction
    with it. The caller then reads the winner's row and carries on as an
    update, which is what makes the save idempotent under a double click.
    """
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        return None
    return row


async def list_statutory_lines(session: AsyncSession, calc_id: uuid.UUID) -> list[StatutoryTaxLine]:
    """The lines of one header, in the order a document prints them."""
    stmt = select(StatutoryTaxLine).where(StatutoryTaxLine.calc_id == calc_id)
    rows = list((await session.execute(stmt)).scalars().all())
    order = {kind: position for position, kind in enumerate(STATUTORY_LINE_KINDS)}
    return sorted(rows, key=lambda line: order.get(line.kind, len(order)))


async def add_statutory_line(session: AsyncSession, row: StatutoryTaxLine) -> StatutoryTaxLine:
    """Store one line."""
    session.add(row)
    await session.flush()
    return row


__all__ = [
    "add_deduction",
    "add_determination",
    "add_party_status",
    "add_regime",
    "add_statutory_calc",
    "add_statutory_line",
    "current_party_status",
    "delete_deduction",
    "delete_determination",
    "delete_party_status",
    "delete_regime",
    "expiring_party_statuses",
    "get_deduction",
    "get_determination",
    "get_determination_for_invoice",
    "get_party_status",
    "get_regime",
    "get_regime_by_scheme",
    "get_statutory_calc",
    "list_deductions",
    "list_determinations",
    "list_party_statuses",
    "list_regimes",
    "list_statutory_lines",
]
