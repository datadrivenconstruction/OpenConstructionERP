# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Timeline service - read queries over the existing activity-log store.

The timeline is a cross-module rollup view. A row belongs to a project's
timeline when either:

* it was logged with ``parent_entity_id`` == the project id (the normal case
  for module events that carry their umbrella project - NCRs, approvals,
  change orders, ...), or
* it was logged directly against the project itself
  (``entity_id`` == the project id), e.g. a ``project.status_changed`` row.

No new table and no migration: this reads :class:`app.core.audit_log.ActivityLog`.
Statement construction lives in :mod:`app.modules.timeline.repository`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import ActivityLog
from app.modules.timeline import repository


async def get_project_timeline(
    session: AsyncSession,
    *,
    project_id: str | uuid.UUID,
    modules: list[str] | None = None,
    actions: list[str] | None = None,
    entity_type: str | None = None,
    actor_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ActivityLog]:
    """Newest-first slice of a project's cross-module activity timeline.

    Args:
        session: Active async session.
        project_id: The umbrella project to roll activity up to.
        modules: Optional ``module`` allowlist (e.g. ``["ncr", "approval"]``).
        actions: Optional ``action`` allowlist (full event names).
        entity_type: Optional exact ``entity_type`` filter.
        actor_id: Optional filter to one acting user.
        since / until: Optional inclusive ``created_at`` bounds (UTC).
        limit: Max rows to return.
        offset: Pagination offset.

    Returns:
        :class:`ActivityLog` rows, newest first, ordered totally so that paging
        cannot drop or repeat a row.
    """
    return await repository.list_for_project(
        session,
        project_id=project_id,
        modules=modules,
        actions=actions,
        entity_type=entity_type,
        actor_id=actor_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


async def count_project_timeline(
    session: AsyncSession,
    *,
    project_id: str | uuid.UUID,
    modules: list[str] | None = None,
    actions: list[str] | None = None,
    entity_type: str | None = None,
    actor_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    """Total number of timeline rows for a project under the same filters.

    Mirrors :func:`get_project_timeline` so the API can return an accurate
    ``total`` for pagination without re-fetching every row.
    """
    return await repository.count_for_project(
        session,
        project_id=project_id,
        modules=modules,
        actions=actions,
        entity_type=entity_type,
        actor_id=actor_id,
        since=since,
        until=until,
    )


async def get_entity_timeline(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    project_id: str | uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[ActivityLog]:
    """Newest-first history of one record, across every module that touched it.

    The project feed answers "what happened on this job"; this answers "what
    happened to this NCR", which is the question a reader asks once they have
    picked a row out of the feed. Scoped to *project_id* - see
    :func:`app.modules.timeline.repository._entity_scope` for why that is a
    correctness requirement and not a convenience.
    """
    return await repository.list_for_entity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )


async def count_entity_timeline(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    project_id: str | uuid.UUID,
) -> int:
    """Total number of history rows for one record within one project."""
    return await repository.count_for_entity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        project_id=project_id,
    )


__all__ = [
    "count_entity_timeline",
    "count_project_timeline",
    "get_entity_timeline",
    "get_project_timeline",
]
