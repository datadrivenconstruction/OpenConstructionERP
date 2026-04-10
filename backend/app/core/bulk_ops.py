"""Generic bulk operation helpers.

Provides reusable schemas and a bulk delete/update/status SQL builder so each
module can expose POST /batch/delete/, POST /batch/update/, and PATCH /batch/status/
endpoints with one-liner implementations.

Example usage in a router:

    from app.core.bulk_ops import BulkDeleteRequest, BulkStatusRequest, bulk_delete, bulk_status

    @router.post("/batch/delete/", status_code=200)
    async def batch_delete_tasks(
        body: BulkDeleteRequest,
        user_id: CurrentUserId,
        session: SessionDep,
    ) -> dict:
        deleted = await bulk_delete(session, Task, body.ids, project_id_field="project_id")
        return {"deleted": deleted}
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession


# ── Shared request schemas ──────────────────────────────────────────────────


class BulkDeleteRequest(BaseModel):
    """IDs of records to delete in a single transaction."""

    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)


class BulkStatusRequest(BaseModel):
    """IDs to update + new status string."""

    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)
    status: str = Field(..., min_length=1, max_length=50)


class BulkAssignRequest(BaseModel):
    """IDs to assign + new responsible/owner identifier."""

    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)
    assignee_id: str = Field(..., min_length=1, max_length=255)


class BulkUpdateRequest(BaseModel):
    """IDs + arbitrary fields to set (validated by the calling endpoint)."""

    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)
    fields: dict[str, Any] = Field(default_factory=dict)


# ── Generic SQL helpers ─────────────────────────────────────────────────────


async def bulk_delete(
    session: AsyncSession,
    model: type,
    ids: list[uuid.UUID],
) -> int:
    """Delete rows whose ID is in ``ids``. Returns the number of rows affected.

    Note: callers are responsible for ownership/permission checks BEFORE invoking
    this helper. The helper itself trusts the caller.
    """
    if not ids:
        return 0
    stmt = delete(model).where(model.id.in_(ids))
    result = await session.execute(stmt)
    await session.flush()
    return int(result.rowcount or 0)


async def bulk_update_status(
    session: AsyncSession,
    model: type,
    ids: list[uuid.UUID],
    new_status: str,
    *,
    allowed_statuses: set[str] | None = None,
) -> int:
    """Set ``status = new_status`` on the given rows.

    If ``allowed_statuses`` is provided, raises ``ValueError`` when ``new_status``
    is not a member.
    """
    if not ids:
        return 0
    if allowed_statuses is not None and new_status not in allowed_statuses:
        raise ValueError(
            f"Status '{new_status}' not allowed. Expected one of: {sorted(allowed_statuses)}"
        )
    stmt = update(model).where(model.id.in_(ids)).values(status=new_status)
    result = await session.execute(stmt)
    await session.flush()
    return int(result.rowcount or 0)


async def bulk_update_fields(
    session: AsyncSession,
    model: type,
    ids: list[uuid.UUID],
    fields: dict[str, Any],
) -> int:
    """Set ``fields`` on the given rows. Returns the number of rows affected.

    The caller is responsible for whitelisting which fields are safe to update —
    this helper trusts the dict it receives.
    """
    if not ids or not fields:
        return 0
    stmt = update(model).where(model.id.in_(ids)).values(**fields)
    result = await session.execute(stmt)
    await session.flush()
    return int(result.rowcount or 0)


async def filter_owned_ids(
    session: AsyncSession,
    model: type,
    ids: list[uuid.UUID],
    project_id_field: str = "project_id",
    project_ids: list[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    """Return the subset of ``ids`` that belong to one of ``project_ids``.

    Used to enforce project-scoped bulk operations: pass the user's authorized
    project IDs and only those records are returned.
    """
    if not ids or not project_ids:
        return []
    project_field = getattr(model, project_id_field)
    stmt = select(model.id).where(
        model.id.in_(ids),
        project_field.in_(project_ids),
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]
