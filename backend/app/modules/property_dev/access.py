# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project-access gate shared by every property_dev route.

Every property_dev entity hangs off a Project (directly, or through a
Development). Who may reach the entity is therefore decided by who may reach
that project, and this module is the one place that answers it.

The rule is the platform rule from :func:`app.dependencies.verify_project_access`
for owners and team members: the project owner passes, and so does anyone with
a ``TeamMembership`` on one of the project's teams. Membership is resolved
through :mod:`app.modules.teams.access`, the same primitives the shared helper
uses, so a sales team member reaches condo sales without owning the project.

What a member may DO is not decided here. As everywhere else on the platform,
membership grants reach and the caller's RBAC role decides read vs write: each
route still carries its ``RequirePermission(...)`` dependency, so a viewer who
is a team member can read and still gets 403 on every mutating route.

One deliberate difference from the shared helper: the global ``admin`` role
does not bypass this gate. property_dev decided that an admin reaches a named
object only through ownership or membership (see
``tests/modules/property_dev/test_admin_tenant_boundary.py``), so this gate is
never more permissive than ``verify_project_access``, only stricter for admins.

Denial is always 404, never 403, so "exists but not yours" and "does not
exist" are indistinguishable (no UUID-existence oracle), the same policy as
``verify_project_access``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def payload_user_id(payload: dict[str, Any] | None) -> uuid.UUID | None:
    """Return the caller's user id from a JWT payload, or ``None`` if unusable."""
    if not payload:
        return None
    raw = payload.get("sub") or payload.get("user_id")
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


async def can_reach_project(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    user_id: uuid.UUID | str | None,
) -> bool:
    """True when *user_id* owns the project or is a member of one of its teams.

    Fails closed: a missing project, a missing or malformed user id, or a
    membership lookup that errors all answer ``False``.
    """
    from app.modules.projects.repository import ProjectRepository
    from app.modules.teams.access import is_project_member

    if project_id is None or user_id is None:
        return False
    try:
        uid = uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return False
    project = await ProjectRepository(session).get_by_id(project_id)
    if project is None:
        return False
    if project.owner_id is not None and str(project.owner_id) == str(uid):
        return True
    return await is_project_member(session, project.id, uid)


async def require_project_access(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    payload: dict[str, Any] | None,
    *,
    detail: str,
) -> None:
    """Raise 404 with *detail* unless the caller may reach the project.

    *detail* is the calling endpoint's own "not found" text, so a denial reads
    exactly like the entity being absent.
    """
    if not await can_reach_project(session, project_id, payload_user_id(payload)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


async def reachable_project_ids(
    session: AsyncSession,
    user_id: uuid.UUID | str | None,
    *,
    live_only: bool = False,
) -> list[uuid.UUID]:
    """Every project id the caller owns or is a team member of.

    The set-level companion to :func:`can_reach_project`, for list endpoints.
    Owned projects come first (in id order), then member projects, so a caller
    that needs "a default project" picks one they own whenever one exists.
    An unusable user id yields an empty list, never "everything".
    """
    from app.modules.projects.models import Project
    from app.modules.teams.access import member_project_ids_subquery

    if user_id is None:
        return []
    try:
        uid = uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return []
    stmt = (
        select(Project.id, Project.owner_id)
        .where((Project.owner_id == uid) | (Project.id.in_(member_project_ids_subquery(uid))))
        .order_by(Project.id)
    )
    if live_only:
        stmt = stmt.where(Project.status != "archived")
    rows = (await session.execute(stmt)).all()
    owned = [pid for pid, owner in rows if owner is not None and str(owner) == str(uid)]
    member = [pid for pid, owner in rows if owner is None or str(owner) != str(uid)]
    return owned + member
