# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment clock data access layer.

Pure database queries with no business logic. The service layer calls these
and adds the statutory arithmetic, the schedule computation and the breach
register reconciliation on top.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payment_clock.models import (
    PaymentClockEvent,
    PaymentNotice,
    PaymentRegime,
    StatutoryPaymentApplication,
)

# Statuses that close an application: the money arrived, or the row was retired.
TERMINAL_STATUSES: frozenset[str] = frozenset({"paid", "closed"})


# ── Regimes ──────────────────────────────────────────────────────────────────


async def list_regimes(session: AsyncSession, *, country_code: str = "") -> list[PaymentRegime]:
    """The regime catalogue, alphabetically by jurisdiction."""
    stmt = select(PaymentRegime)
    if country_code:
        stmt = stmt.where(PaymentRegime.country_code == country_code.upper())
    stmt = stmt.order_by(PaymentRegime.jurisdiction.asc(), PaymentRegime.code.asc())
    return list((await session.execute(stmt)).scalars().all())


async def get_regime(session: AsyncSession, *, regime_id: uuid.UUID) -> PaymentRegime | None:
    """One regime by id."""
    return (await session.execute(select(PaymentRegime).where(PaymentRegime.id == regime_id))).scalar_one_or_none()


async def get_regime_by_code(session: AsyncSession, *, code: str) -> PaymentRegime | None:
    """One regime by its stable code, which is how callers name it."""
    return (await session.execute(select(PaymentRegime).where(PaymentRegime.code == code.strip()))).scalar_one_or_none()


async def count_regimes(session: AsyncSession) -> int:
    """How many regimes are in the table."""
    return await session.scalar(select(func.count()).select_from(PaymentRegime)) or 0


# ── Applications ─────────────────────────────────────────────────────────────


async def list_applications(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    status: str = "",
    regime_id: uuid.UUID | None = None,
    overdue_as_of: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[StatutoryPaymentApplication]:
    """Applications on one project, newest application date first.

    ``overdue_as_of`` narrows to the rows whose final date for payment has
    passed and which are not closed - the ones somebody is owed money on.
    """
    stmt = select(StatutoryPaymentApplication).where(StatutoryPaymentApplication.project_id == project_id)
    if status:
        stmt = stmt.where(StatutoryPaymentApplication.status == status)
    if regime_id is not None:
        stmt = stmt.where(StatutoryPaymentApplication.regime_id == regime_id)
    if overdue_as_of is not None:
        stmt = stmt.where(
            StatutoryPaymentApplication.final_date.is_not(None),
            StatutoryPaymentApplication.final_date < overdue_as_of,
            StatutoryPaymentApplication.status.not_in(tuple(TERMINAL_STATUSES)),
        )
    stmt = stmt.order_by(
        StatutoryPaymentApplication.application_date.desc(),
        StatutoryPaymentApplication.created_at.desc(),
    )
    stmt = stmt.limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def get_application(
    session: AsyncSession,
    *,
    application_id: uuid.UUID,
) -> StatutoryPaymentApplication | None:
    """One application by id, or ``None``."""
    return (
        await session.execute(
            select(StatutoryPaymentApplication).where(StatutoryPaymentApplication.id == application_id)
        )
    ).scalar_one_or_none()


async def add_application(session: AsyncSession, application: StatutoryPaymentApplication) -> None:
    """Persist a new application. The caller owns the transaction."""
    session.add(application)
    await session.flush()


async def flush_application(session: AsyncSession) -> None:
    """Flush pending changes on an application already in the session."""
    await session.flush()


async def remove_application(session: AsyncSession, application: StatutoryPaymentApplication) -> None:
    """Delete a clock. Its notices and events cascade in the database."""
    await session.delete(application)
    await session.flush()


# ── Notices ──────────────────────────────────────────────────────────────────


async def list_notices(session: AsyncSession, *, application_id: uuid.UUID) -> list[PaymentNotice]:
    """Notices served against one application, in the order they were served."""
    stmt = (
        select(PaymentNotice)
        .where(PaymentNotice.application_id == application_id)
        .order_by(PaymentNotice.issued_at.asc(), PaymentNotice.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_notice(session: AsyncSession, *, notice_id: uuid.UUID) -> PaymentNotice | None:
    """One notice by id, or ``None``."""
    return (await session.execute(select(PaymentNotice).where(PaymentNotice.id == notice_id))).scalar_one_or_none()


async def add_notice(session: AsyncSession, notice: PaymentNotice) -> None:
    """Persist a new notice. The caller owns the transaction."""
    session.add(notice)
    await session.flush()


async def remove_notice(session: AsyncSession, notice: PaymentNotice) -> None:
    """Delete a notice that was recorded in error."""
    await session.delete(notice)
    await session.flush()


# ── Events ───────────────────────────────────────────────────────────────────


async def list_events(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    event_type: str = "",
    limit: int = 200,
    offset: int = 0,
) -> list[PaymentClockEvent]:
    """The breach register, newest first.

    Scoped to one application, or to a whole project through a join on the
    application table. There is no ``relationship()`` between the two, so the
    join is written out and nothing lazy-loads behind it.
    """
    stmt = select(PaymentClockEvent)
    if application_id is not None:
        stmt = stmt.where(PaymentClockEvent.application_id == application_id)
    if project_id is not None:
        stmt = stmt.join(
            StatutoryPaymentApplication,
            StatutoryPaymentApplication.id == PaymentClockEvent.application_id,
        ).where(StatutoryPaymentApplication.project_id == project_id)
    if event_type:
        stmt = stmt.where(PaymentClockEvent.event_type == event_type)
    stmt = stmt.order_by(PaymentClockEvent.detected_at.desc()).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def list_events_for_application(
    session: AsyncSession,
    *,
    application_id: uuid.UUID,
) -> list[PaymentClockEvent]:
    """All events for one application, for the register reconciliation."""
    return list(
        (await session.execute(select(PaymentClockEvent).where(PaymentClockEvent.application_id == application_id)))
        .scalars()
        .all()
    )


async def add_event(session: AsyncSession, event: PaymentClockEvent) -> None:
    """Persist a new event. The caller owns the transaction."""
    session.add(event)


async def delete_stale_events(session: AsyncSession, event_ids: list[uuid.UUID]) -> None:
    """Remove events whose findings no longer appear."""
    if event_ids:
        await session.execute(sa_delete(PaymentClockEvent).where(PaymentClockEvent.id.in_(event_ids)))


async def flush_events(session: AsyncSession) -> None:
    """Flush pending event changes."""
    await session.flush()


__all__ = [
    "TERMINAL_STATUSES",
    "add_application",
    "add_event",
    "add_notice",
    "count_regimes",
    "delete_stale_events",
    "flush_application",
    "flush_events",
    "get_application",
    "get_notice",
    "get_regime",
    "get_regime_by_code",
    "list_applications",
    "list_events",
    "list_events_for_application",
    "list_notices",
    "list_regimes",
    "remove_application",
    "remove_notice",
]
