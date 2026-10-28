# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cases service - author, read, duplicate and pin case scenarios.

Stateless helpers over :class:`UserCase` and :class:`CasePin`.

Visibility is two rules and no more. You may **read** a case if you own it or
it is shared. You may **edit or delete** it only if you own it. Sharing is
therefore safe to offer on a checkbox: it publishes a walkthrough without
handing anyone else the pen.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases.models import CasePin, UserCase

logger = logging.getLogger(__name__)


def can_edit(case: UserCase, user_id: uuid.UUID) -> bool:
    """Only the author edits. Sharing grants reading, never writing."""
    return case.owner_id == user_id


# ── Cases ────────────────────────────────────────────────────────────────────


async def list_cases(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    category: str | None = None,
    mine_only: bool = False,
) -> list[UserCase]:
    """Cases the caller may read: their own, plus everyone's shared ones."""
    stmt = select(UserCase)
    if mine_only:
        stmt = stmt.where(UserCase.owner_id == user_id)
    else:
        stmt = stmt.where(
            or_(UserCase.owner_id == user_id, UserCase.is_shared.is_(True)),
        )
    if category:
        stmt = stmt.where(UserCase.category == category)
    stmt = stmt.order_by(UserCase.updated_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_case(
    session: AsyncSession,
    *,
    case_id: uuid.UUID,
    user_id: uuid.UUID,
) -> UserCase | None:
    """One case, or ``None`` when it does not exist or is not visible.

    A private case belonging to someone else is reported the same way as a
    case that was never there. That is deliberate: distinguishing the two
    would confirm the existence of a record the caller has no right to know
    about.
    """
    stmt = select(UserCase).where(
        and_(
            UserCase.id == case_id,
            or_(UserCase.owner_id == user_id, UserCase.is_shared.is_(True)),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _apply(case: UserCase, body: Any) -> None:
    """Copy the writable fields of a validated request onto the row."""
    case.title = body.title
    case.description = body.description
    case.long_description = body.long_description
    case.category = body.category
    case.company_types = list(body.company_types)
    case.roles = list(body.roles)
    case.stage = body.stage
    case.est_minutes = body.est_minutes
    case.icon = body.icon
    case.steps = [step.model_dump() for step in body.steps]
    case.source_playbook_id = body.source_playbook_id
    case.is_shared = body.is_shared


async def create_case(session: AsyncSession, *, owner_id: uuid.UUID, body: Any) -> UserCase:
    """Store a new case owned by the caller."""
    case = UserCase(owner_id=owner_id)
    _apply(case, body)
    session.add(case)
    await session.flush()
    return case


async def update_case(session: AsyncSession, *, case: UserCase, body: Any) -> UserCase:
    """Replace the contents of an existing case. Caller checks ownership."""
    _apply(case, body)
    await session.flush()
    return case


async def delete_case(session: AsyncSession, *, case: UserCase) -> None:
    """Delete a case and every pin that pointed at it.

    ``CasePin.case_id`` carries either a shipped playbook slug or a case UUID,
    so it cannot be a foreign key and the database will not cascade for us.
    Without this second delete a removed case would leave pins behind that
    resolve to nothing, and the pinned strip would render gaps that no screen
    offers a way to clear.
    """
    case_id = str(case.id)
    await session.execute(
        delete(CasePin).where(
            and_(CasePin.case_source == "custom", CasePin.case_id == case_id),
        )
    )
    await session.delete(case)
    await session.flush()


async def duplicate_case(
    session: AsyncSession,
    *,
    source: UserCase,
    owner_id: uuid.UUID,
    title: str | None = None,
) -> UserCase:
    """Fork a readable case into a new one owned by the caller.

    The copy starts private whatever the original was: duplicating someone
    else's shared case is the start of a draft, not a second publication.
    """
    copy = UserCase(
        owner_id=owner_id,
        title=title or f"{source.title} (copy)",
        description=source.description,
        long_description=source.long_description,
        category=source.category,
        company_types=list(source.company_types or []),
        roles=list(source.roles or []),
        stage=source.stage,
        est_minutes=source.est_minutes,
        icon=source.icon,
        steps=[dict(step) for step in (source.steps or [])],
        source_playbook_id=source.source_playbook_id,
        is_shared=False,
    )
    session.add(copy)
    await session.flush()
    return copy


# ── Pins ─────────────────────────────────────────────────────────────────────


async def list_pins(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
) -> list[CasePin]:
    """The caller's pinned cases, in the order they arranged them."""
    stmt = select(CasePin).where(CasePin.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(CasePin.project_id == project_id)
    stmt = stmt.order_by(CasePin.sort_order.asc(), CasePin.created_at.asc())
    return list((await session.execute(stmt)).scalars().all())


async def add_pin(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    case_source: str,
    case_id: str,
    sort_order: int = 0,
    note: str = "",
) -> tuple[CasePin, bool]:
    """Pin a case to a project. Returns ``(row, created)``.

    Idempotent on the unique key, so a double click cannot produce two pins.
    """
    existing = (
        await session.execute(
            select(CasePin).where(
                and_(
                    CasePin.user_id == user_id,
                    CasePin.project_id == project_id,
                    CasePin.case_source == case_source,
                    CasePin.case_id == case_id,
                )
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if note and existing.note != note:
            existing.note = note
            await session.flush()
        return existing, False

    row = CasePin(
        user_id=user_id,
        project_id=project_id,
        case_source=case_source,
        case_id=case_id,
        sort_order=sort_order,
        note=note,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        # Concurrent insert - fall back to the row the other request wrote.
        await session.rollback()
        existing = (
            await session.execute(
                select(CasePin).where(
                    and_(
                        CasePin.user_id == user_id,
                        CasePin.project_id == project_id,
                        CasePin.case_source == case_source,
                        CasePin.case_id == case_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        return existing, False
    return row, True


async def remove_pin(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    case_source: str,
    case_id: str,
) -> bool:
    """Unpin. Returns ``True`` iff a row was removed."""
    result = await session.execute(
        delete(CasePin).where(
            and_(
                CasePin.user_id == user_id,
                CasePin.project_id == project_id,
                CasePin.case_source == case_source,
                CasePin.case_id == case_id,
            )
        )
    )
    return bool(result.rowcount or 0)


async def reorder_pins(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    pin_ids: list[uuid.UUID],
) -> list[CasePin]:
    """Renumber the caller's pins on one project to the given order.

    Only rows the caller owns on that project are touched, so a stray id in
    the list is ignored rather than moving somebody else's pin.
    """
    rows = await list_pins(session, user_id=user_id, project_id=project_id)
    by_id = {row.id: row for row in rows}
    next_place = 0
    for pin_id in pin_ids:
        row = by_id.pop(pin_id, None)
        if row is None:
            continue
        row.sort_order = next_place
        next_place += 1
    # Anything the client did not mention keeps a stable place behind the rest
    # instead of collapsing to zero and colliding.
    for row in sorted(by_id.values(), key=lambda r: (r.sort_order, r.created_at)):
        row.sort_order = next_place
        next_place += 1
    await session.flush()
    return await list_pins(session, user_id=user_id, project_id=project_id)


__all__ = [
    "add_pin",
    "can_edit",
    "create_case",
    "delete_case",
    "duplicate_case",
    "get_case",
    "list_cases",
    "list_pins",
    "remove_pin",
    "reorder_pins",
    "update_case",
]
