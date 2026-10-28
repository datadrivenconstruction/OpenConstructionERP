# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Timeline data access over the shared activity-log table.

The timeline owns no table of its own, so this repository is read-only: it
builds the selects against :class:`app.core.audit_log.ActivityLog` and hands
back ORM rows. Keeping them here rather than in the service means the ordering
contract lives in exactly one place, which is the whole point - see
:func:`_ordered`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import ActivityLog


def project_scope(project_id: str | uuid.UUID):
    """Predicate selecting rows that belong to a project's timeline.

    A row is in scope when its ``parent_entity_id`` is the project (module
    events rolled up to their umbrella project) OR its ``entity_id`` is the
    project (events logged directly against the project row).
    """
    pid = str(project_id)
    return or_(
        ActivityLog.parent_entity_id == pid,
        ActivityLog.entity_id == pid,
    )


def _ordered(stmt: Select) -> Select:
    """Apply the newest-first ordering, with ``id`` as the tiebreaker.

    ``created_at`` alone is not a total order. It is filled from a Python-side
    default (``app.database.Base``), so a burst of bridge writes can land
    several rows on the same timestamp, and PostgreSQL is then free to return
    tied rows in any order it likes - including a different order per query.
    Under ``OFFSET``/``LIMIT`` paging that silently drops some rows and repeats
    others, which is the failure a reader would blame on the data.

    ``id`` is the primary key, so appending it makes the order total and the
    paging stable.
    """
    return stmt.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())


def apply_filters(
    stmt: Select,
    *,
    modules: list[str] | None = None,
    actions: list[str] | None = None,
    entity_type: str | None = None,
    actor_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select:
    """Apply the optional timeline filters to a select statement."""
    if modules:
        stmt = stmt.where(ActivityLog.module.in_(list(modules)))
    if actions:
        stmt = stmt.where(ActivityLog.action.in_(list(actions)))
    if entity_type is not None:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if actor_id is not None:
        stmt = stmt.where(ActivityLog.actor_id == actor_id)
    if since is not None:
        stmt = stmt.where(ActivityLog.created_at >= since)
    if until is not None:
        stmt = stmt.where(ActivityLog.created_at <= until)
    return stmt


async def list_for_project(
    session: AsyncSession,
    *,
    project_id: str | uuid.UUID,
    limit: int,
    offset: int,
    **filters,
) -> list[ActivityLog]:
    """One newest-first page of a project's timeline."""
    stmt = apply_filters(select(ActivityLog).where(project_scope(project_id)), **filters)
    result = await session.execute(_ordered(stmt).offset(offset).limit(limit))
    return list(result.scalars().all())


async def count_for_project(
    session: AsyncSession,
    *,
    project_id: str | uuid.UUID,
    **filters,
) -> int:
    """Total rows on a project's timeline under the same filters."""
    stmt = apply_filters(
        select(func.count()).select_from(ActivityLog).where(project_scope(project_id)),
        **filters,
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


def _entity_scope(entity_type: str, entity_id: str, project_id: str | uuid.UUID):
    """Predicate selecting one record's history within one project.

    ``(entity_type, entity_id)`` is covered by the existing
    ``ix_activity_log_entity_created`` index. The project clause is not
    optional: ``entity_id`` is a free ``String(64)`` on the activity log, not a
    foreign key, so ids are only unique by convention. Without it, a caller
    authorised for one project could read another project's record history by
    guessing an id, and the guess needs no luck when ids are sequential.
    """
    return (
        (ActivityLog.entity_type == entity_type)
        & (ActivityLog.entity_id == str(entity_id))
        & (ActivityLog.parent_entity_id == str(project_id))
    )


async def list_for_entity(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    project_id: str | uuid.UUID,
    limit: int,
    offset: int,
) -> list[ActivityLog]:
    """One newest-first page of a single record's own history."""
    stmt = select(ActivityLog).where(_entity_scope(entity_type, entity_id, project_id))
    result = await session.execute(_ordered(stmt).offset(offset).limit(limit))
    return list(result.scalars().all())


async def count_for_entity(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    project_id: str | uuid.UUID,
) -> int:
    """Total rows in one record's history within one project."""
    stmt = select(func.count()).select_from(ActivityLog).where(_entity_scope(entity_type, entity_id, project_id))
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


__all__ = [
    "apply_filters",
    "count_for_entity",
    "count_for_project",
    "list_for_entity",
    "list_for_project",
    "project_scope",
]
