"""Per-project authorization for ACAP endpoints — closes the IDOR gap.

Every ACAP endpoint takes a ``project_id`` and, before Phase 8, only checked
that the caller was *authenticated* — not that they may touch *that* project.
These guards reuse the fork's own ownership model (``Project.owner_id`` + team
membership via :func:`app.modules.teams.access.is_project_member`) so ACAP
follows the SAME policy as the fork's native project routes:

  * reads  -> owner, team member, or admin; **404** on denial (deny and
    "not found" are indistinguishable — an outsider can't probe which project
    ids exist; matches the fork's ``_verify_project_access`` IDOR policy).
  * writes -> owner or admin; **403** on denial (matches ``_verify_project_owner``).

Authorization is SERVER-SIDE here, never a frontend filter. The ACAP child
tables (floor_plan / render / the persisted BOQ) are all project-scoped, so
gating on the parent project's ownership isolates every tenant's data without a
separate ``tenant_id`` column (tenant == owning user, per the fork's
``get_current_tenant_id``).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.teams.access import is_project_member

_ADMIN_ROLE = "admin"


async def _load_project(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
    return (
        await session.execute(select(Project).where(Project.id == project_id))
    ).scalars().first()


def _as_uuid(user_sub: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(user_sub)
    except (ValueError, TypeError, AttributeError):
        return None


async def require_project_access(
    session: AsyncSession, project_id: uuid.UUID, payload: dict[str, Any]
) -> None:
    """Read guard: allow owner, team member, or admin. Raise 404 otherwise.

    404 (not 403) is deliberate: a non-member must not be able to tell a
    project that exists-but-is-denied from one that does not exist.
    """
    user_sub = payload.get("sub", "")
    project = await _load_project(session, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if payload.get("role") == _ADMIN_ROLE:
        return
    if str(project.owner_id) == user_sub:
        return
    user_uuid = _as_uuid(user_sub)
    if user_uuid is not None and await is_project_member(session, project_id, user_uuid):
        return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


async def require_project_owner(
    session: AsyncSession, project_id: uuid.UUID, payload: dict[str, Any]
) -> None:
    """Write guard: allow owner or admin only. Raise 403 otherwise (404 if the
    project genuinely doesn't exist)."""
    user_sub = payload.get("sub", "")
    project = await _load_project(session, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if payload.get("role") == _ADMIN_ROLE:
        return
    if str(project.owner_id) == user_sub:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to this project",
    )
