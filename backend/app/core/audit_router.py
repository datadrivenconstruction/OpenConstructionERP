"""Audit log API routes (admin-only).

Endpoints:
    GET /api/v1/audit                          — list audit entries with filters
    GET /api/v1/audit/{entity_type}/{entity_id} — audit trail for a specific entity
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.audit import AuditEntry, get_audit_entries
from app.dependencies import CurrentUserId, RequirePermission, SessionDep

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])
logger = logging.getLogger(__name__)


def _entry_to_dict(entry: AuditEntry) -> dict[str, Any]:
    """Serialise an ``AuditEntry`` to a plain dict for JSON response."""
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
    _user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("audit.view")),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None, alias="user_id_filter"),
    action: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """List audit log entries with optional filters (admin only)."""
    entries = await get_audit_entries(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return [_entry_to_dict(e) for e in entries]


@router.get("/{entity_type}/{entity_id}", response_model=list[dict[str, Any]])
async def entity_audit_trail(
    entity_type: str,
    entity_id: str,
    session: SessionDep,
    _user_id: CurrentUserId = None,  # type: ignore[assignment]
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
