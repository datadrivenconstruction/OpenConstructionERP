"""‌⁠‍Audit log API routes (admin-only).

Endpoints:
    GET    /api/v1/audit                            — list audit entries with filters
    GET    /api/v1/audit/count                      — count rows matching the same filter set
    GET    /api/v1/audit/{entity_type}/{entity_id}  — audit trail for a specific entity
    GET    /api/v1/audit/timeline/                  — unified Epic H timeline (oe_activity_log)
    POST   /api/v1/audit/redact-actor/              — GDPR right-to-erasure (2-step confirm)

Filter params accepted by ``GET /v1/audit`` and ``/v1/audit/count``:

* ``entity_type`` — logical entity name (boq / project / …)
* ``entity_id`` — single UUID
* ``user_id_filter`` — UUID of the acting user (aliased to avoid colliding
  with the path-param of the entity trail route)
* ``action`` — verb (create / update / …)
* ``date_from`` / ``date_to`` — ISO-8601 inclusive bounds on ``created_at``
* ``sort`` — ``desc`` (default) or ``asc`` — list only
* ``limit`` / ``offset`` — pagination, list only

The frontend's filter bar in ``AuditLogPage.tsx`` is the canonical
consumer — keep this signature in sync with that page's ``AuditFilters``
type when adding new params.
"""

import logging
import uuid as _uuid_mod
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import update

from app.core.audit import (
    AuditEntry,
    count_audit_entries,
    get_audit_entries,
)
from app.dependencies import CurrentUserId, RequirePermission, SessionDep

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])
logger = logging.getLogger(__name__)


def _entry_to_dict(entry: AuditEntry) -> dict[str, Any]:
    """‌⁠‍Serialise an ``AuditEntry`` to a plain dict for JSON response."""
    return {
        "id": str(entry.id),
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "user_id": str(entry.user_id) if entry.user_id else None,
        "ip_address": entry.ip_address,
        "details": entry.details,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@router.get("", response_model=list[dict[str, Any]])
async def list_audit_entries(
    session: SessionDep,
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("audit.view")),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None, alias="user_id_filter"),
    action: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """‌⁠‍List audit log entries with optional filters (admin only)."""
    entries = await get_audit_entries(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return [_entry_to_dict(e) for e in entries]


@router.get("/count", response_model=dict[str, int])
async def count_audit(
    session: SessionDep,
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("audit.view")),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None, alias="user_id_filter"),
    action: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> dict[str, int]:
    """‌⁠‍Total rows matching the current filter (used by the admin pager)."""
    total = await count_audit_entries(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
    return {"total": total}


@router.get("/{entity_type}/{entity_id}", response_model=list[dict[str, Any]])
async def entity_audit_trail(
    entity_type: str,
    entity_id: str,
    session: SessionDep,
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("audit.view")),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Get the full audit trail for a specific entity."""
    entries = await get_audit_entries(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
    return [_entry_to_dict(e) for e in entries]


# ── Epic H — unified timeline ──────────────────────────────────────────


def _activity_to_dict(row: Any) -> dict[str, Any]:
    """Serialise an ``ActivityLog`` row for the timeline endpoint.

    Mirrors :func:`_entry_to_dict` shape so the frontend's AuditLogPage
    filter bar can switch between the legacy ``oe_core_audit_log`` and
    the unified ``oe_activity_log`` without a second response model.
    """
    return {
        "id": str(row.id),
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "reason": row.reason,
        "metadata": row.metadata_,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "request_id": row.request_id,
        "module": row.module,
        "parent_entity_type": row.parent_entity_type,
        "parent_entity_id": row.parent_entity_id,
        "before_state": row.before_state,
        "after_state": row.after_state,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/timeline/", response_model=list[dict[str, Any]])
async def get_timeline(
    session: SessionDep,
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("audit.view")),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    module: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Unified timeline from ``oe_activity_log`` (Epic H).

    The legacy ``/v1/audit`` endpoints still serve ``oe_core_audit_log``
    one row at a time. This endpoint pivots on the universal-audit
    table — newest-first, optionally filtered by entity / actor / module
    — so the frontend AuditLogPage can render a cross-module timeline
    without union-querying two tables.
    """
    from sqlalchemy import select

    from app.core.audit_log import ActivityLog

    stmt = select(ActivityLog)
    if entity_type is not None:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(ActivityLog.entity_id == entity_id)
    if module is not None:
        stmt = stmt.where(ActivityLog.module == module)
    if actor_id is not None:
        try:
            import uuid as _uuid

            stmt = stmt.where(ActivityLog.actor_id == _uuid.UUID(actor_id))
        except (ValueError, AttributeError):
            return []
    stmt = stmt.order_by(ActivityLog.created_at.desc()).offset(offset).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())
    return [_activity_to_dict(r) for r in rows]


# ── Epic H §H9 — GDPR right-to-erasure (redact actor) ────────────────


class RedactActorRequest(BaseModel):
    """2-step confirm payload for actor redaction.

    The first request returns 200 with ``preview=<int>`` and does NOT
    mutate. The second request — with ``confirm`` set to the exact value
    returned by the preview ("yes-<uuid>") and ``commit=True`` — runs the
    redaction. This is enough to stop an accidental Postman click from
    nuking compliance data without forcing a separate "dry-run" endpoint.
    """

    actor_id: str = Field(..., description="UUID of the actor to redact")
    confirm: str | None = Field(
        default=None,
        description=("Echoes back the ``confirm`` token returned by a preview call. Required when ``commit=True``."),
    )
    commit: bool = Field(
        default=False,
        description="Set to True on the second call to actually redact.",
    )


@router.post("/redact-actor/", response_model=dict[str, Any])
async def redact_actor(
    session: SessionDep,
    _user_id: CurrentUserId,
    body: RedactActorRequest = Body(...),
    _perm: None = Depends(RequirePermission("audit.redact")),
) -> dict[str, Any]:
    """GDPR Article 17 — overwrite ``actor_id`` (and IP / UA) on every row
    written by the data subject. The row stays — the operational
    audit-trail is preserved — but the personally identifying capture
    columns are NULL'd out so the data subject can no longer be re-linked
    to their actions.

    Two-step confirm: the first call (``commit=False``) returns the
    preview count + a per-actor confirm token. The second call must
    include that token and ``commit=True`` to actually run. This stops
    accidental clicks but is still scriptable (a real GDPR runbook does
    both calls back-to-back with the token piped between them).
    """
    try:
        actor_uuid = _uuid_mod.UUID(body.actor_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid actor_id — must be a UUID",
        ) from exc

    # Always count first so the response shape is identical between
    # preview and commit — the frontend hides ``preview`` vs ``redacted``
    # under the same key.
    from sqlalchemy import func
    from sqlalchemy import select as _select

    from app.core.audit_log import ActivityLog

    count_stmt = _select(func.count(ActivityLog.id)).where(ActivityLog.actor_id == actor_uuid)
    affected = int((await session.execute(count_stmt)).scalar() or 0)

    confirm_token = f"yes-{actor_uuid}"

    if not body.commit:
        return {
            "preview": affected,
            "confirm_token": confirm_token,
            "redacted": 0,
            "actor_id": str(actor_uuid),
        }

    if body.confirm != confirm_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Confirmation token mismatch. POST again without ``commit`` to retrieve the current token."),
        )

    redact_stmt = (
        update(ActivityLog)
        .where(ActivityLog.actor_id == actor_uuid)
        .values(actor_id=None, ip_address=None, user_agent=None)
    )
    result = await session.execute(redact_stmt)
    await session.flush()
    redacted = int(result.rowcount or affected)
    logger.warning(
        "GDPR redact-actor: actor_id=%s rows=%d by admin=%s",
        actor_uuid,
        redacted,
        _user_id,
    )
    return {
        "preview": affected,
        "confirm_token": confirm_token,
        "redacted": redacted,
        "actor_id": str(actor_uuid),
    }
