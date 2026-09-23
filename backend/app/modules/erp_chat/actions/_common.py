# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Helpers the action specs share: the project in play and the actions still pending."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.modules.erp_chat.actions.base import (
    ActionContext,
    ActionNotFoundError,
    ActionValidationError,
    coerce_uuid,
)

PENDING_STATUSES: tuple[str, ...] = ("proposed", "failed")


@dataclass(frozen=True)
class ProjectInfo:
    """The project facts a preview needs."""

    id: uuid.UUID
    name: str
    currency: str


async def resolve_project(ctx: ActionContext, args: dict[str, Any]) -> ProjectInfo:
    """The project the change is for: the argument, else the conversation's project.

    The caller must have access to it (owner, team member or admin), checked
    with the platform's own ``verify_project_access``; a project that is not
    there and one the caller may not see are the same 404.
    """
    raw = args.get("project_id")
    project_id = coerce_uuid(raw) if raw not in (None, "") else ctx.project_id
    if raw not in (None, "") and project_id is None:
        raise ActionNotFoundError(code="project_not_found")
    if project_id is None:
        raise ActionValidationError(code="project_required")
    await ctx.require_project_access(project_id)
    return await load_project(ctx, project_id)


async def load_project(ctx: ActionContext, project_id: uuid.UUID) -> ProjectInfo:
    """Name and currency of a project the caller was already checked against."""
    from app.modules.projects.models import Project

    row = (
        await ctx.session.execute(select(Project.name, Project.currency).where(Project.id == project_id))
    ).one_or_none()
    if row is None:
        raise ActionNotFoundError(code="project_not_found")
    return ProjectInfo(id=project_id, name=str(row[0] or ""), currency=str(row[1] or ""))


async def pending_payloads(
    ctx: ActionContext,
    *,
    action_type: str,
    project_id: uuid.UUID,
    exclude_id: uuid.UUID | None,
) -> list[dict[str, Any]]:
    """Payloads of the still-pending actions of one type in one project (excluding ``exclude_id``).

    Used to keep proposals made in the same turn from claiming the same
    position number before any of them is applied.
    """
    from app.modules.erp_chat.models import ChatAction

    stmt = select(ChatAction.id, ChatAction.payload).where(
        ChatAction.action_type == action_type,
        ChatAction.project_id == project_id,
        ChatAction.status.in_(PENDING_STATUSES),
    )
    rows = (await ctx.session.execute(stmt)).all()
    return [dict(payload or {}) for action_id, payload in rows if exclude_id is None or action_id != exclude_id]
