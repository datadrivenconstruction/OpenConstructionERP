"""Activity feed — aggregates recent actions from the audit log.

Usage:
    GET /api/v1/activity?project_id=X&limit=20

Returns a chronological feed of recent actions across all modules,
enriched with entity details for human-friendly display.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEntry

logger = logging.getLogger(__name__)

# Map entity_type to human-readable labels and icon hints for the frontend
_ENTITY_META: dict[str, dict[str, str]] = {
    "project": {"icon": "folder", "url_tpl": "/projects/{entity_id}"},
    "boq": {"icon": "table", "url_tpl": "/boq/{entity_id}"},
    "position": {"icon": "list", "url_tpl": "/boq"},
    "contact": {"icon": "users", "url_tpl": "/contacts"},
    "document": {"icon": "file", "url_tpl": "/documents"},
    "rfi": {"icon": "help-circle", "url_tpl": "/rfi"},
    "task": {"icon": "check-square", "url_tpl": "/tasks"},
    "cost_item": {"icon": "database", "url_tpl": "/costs"},
    "meeting": {"icon": "calendar", "url_tpl": "/meetings"},
    "inspection": {"icon": "clipboard", "url_tpl": "/inspections"},
    "quality_inspection": {"icon": "clipboard", "url_tpl": "/inspections"},
    "ncr": {"icon": "alert-triangle", "url_tpl": "/ncr"},
    "invoice": {"icon": "receipt", "url_tpl": "/finance"},
    "submittal": {"icon": "file-text", "url_tpl": "/submittals"},
    "safety_observation": {"icon": "shield", "url_tpl": "/safety"},
    "safety_incident": {"icon": "shield", "url_tpl": "/safety"},
    "transmittal": {"icon": "send", "url_tpl": "/transmittals"},
    "variation": {"icon": "git-branch", "url_tpl": "/variations"},
    "change_order": {"icon": "git-branch", "url_tpl": "/variations"},
    "purchase_order": {"icon": "shopping-cart", "url_tpl": "/procurement"},
    "schedule": {"icon": "calendar", "url_tpl": "/schedule"},
}


async def get_activity_feed(
    session: AsyncSession,
    project_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Aggregate recent activity from the audit log.

    Returns a list of activity entries, each with:
        type, entity_type, entity_id, title, action, user_id,
        user_name, timestamp, url, icon, details
    """
    stmt = select(AuditEntry).order_by(AuditEntry.created_at.desc())

    if project_id:
        # Filter audit entries where details contains the project_id.
        # Since details is JSON, we check for entries that have a matching
        # project_id in the details column OR the entity_type is "project"
        # and entity_id matches.
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                # Direct project entity
                (AuditEntry.entity_type == "project") & (AuditEntry.entity_id == project_id),
                # Entries that reference the project in details (JSON contains)
                AuditEntry.details.contains(project_id),
            )
        )

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    entries = result.scalars().all()

    # Collect unique user_ids for name resolution
    user_ids = {str(e.user_id) for e in entries if e.user_id}
    user_names = await _resolve_user_names(session, user_ids)

    feed: list[dict[str, Any]] = []
    for entry in entries:
        meta = _ENTITY_META.get(entry.entity_type, {})
        icon = meta.get("icon", "activity")
        url_tpl = meta.get("url_tpl", "")
        url = url_tpl.format(entity_id=entry.entity_id or "") if url_tpl else ""

        # Build a human-readable title from action + entity_type + details
        title = _build_title(entry)
        user_id_str = str(entry.user_id) if entry.user_id else None

        feed.append({
            "type": entry.action,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "title": title,
            "action": entry.action,
            "user_id": user_id_str,
            "user_name": user_names.get(user_id_str, "System") if user_id_str else "System",
            "timestamp": entry.created_at.isoformat() if entry.created_at else None,
            "url": url,
            "icon": icon,
            "details": entry.details,
        })

    return feed


def _build_title(entry: AuditEntry) -> str:
    """Build a human-readable description from the audit entry."""
    action = entry.action.replace("_", " ").title()
    entity = entry.entity_type.replace("_", " ").title()

    # Try to extract a meaningful name from details
    details = entry.details or {}
    name = (
        details.get("name")
        or details.get("title")
        or details.get("subject")
        or details.get("company_name")
        or details.get("transmittal_number")
        or details.get("rfi_number")
        or details.get("ncr_number")
        or details.get("inspection_number")
        or details.get("meeting_number")
        or details.get("document_name")
        or ""
    )

    if name:
        return f"{action} {entity}: {str(name)[:100]}"
    return f"{action} {entity}"


async def _resolve_user_names(
    session: AsyncSession,
    user_ids: set[str],
) -> dict[str, str]:
    """Resolve user UUIDs to full names. Returns {user_id_str: full_name}."""
    if not user_ids:
        return {}

    try:
        import uuid as _uuid

        from app.modules.users.models import User

        parsed_ids = []
        for uid in user_ids:
            try:
                parsed_ids.append(_uuid.UUID(uid))
            except (ValueError, AttributeError):
                continue

        if not parsed_ids:
            return {}

        stmt = select(User.id, User.full_name).where(User.id.in_(parsed_ids))
        rows = (await session.execute(stmt)).all()
        return {str(row[0]): row[1] for row in rows}
    except Exception:
        logger.debug("Failed to resolve user names", exc_info=True)
        return {}
