"""‌⁠‍System-wide audit log for tracking important entity changes.

Usage:
    from app.core.audit import audit_log
    await audit_log(session, action="create", entity_type="contact", entity_id=str(id),
                    user_id=str(user_id), details={"company_name": "Siemens"})
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import JSON, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

logger = logging.getLogger(__name__)


class AuditEntry(Base):
    """‌⁠‍Audit log entry tracking important entity changes.

    Stores who did what, to which entity, and when.  The ``details``
    column holds arbitrary JSON context (old/new values, extra info).
    """

    __tablename__ = "oe_core_audit_log"

    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    details: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )


async def audit_log(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    user_id: str | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> AuditEntry:
    """‌⁠‍Write a single audit log entry.

    Parameters:
        session: Active async database session (will be flushed but NOT committed).
        action: Verb describing the event (create/update/delete/enable/disable/
                approve/reject/login/export).
        entity_type: Logical entity name (contact/project/boq/invoice/...).
        entity_id: UUID of the target entity (optional).
        user_id: UUID of the user who performed the action (optional).
        ip_address: Client IP address (optional).
        details: Arbitrary JSON context — old/new values, extra info.

    Returns:
        The persisted ``AuditEntry`` instance.
    """
    entry = AuditEntry(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=uuid.UUID(user_id) if user_id else None,
        ip_address=ip_address,
        details=details or {},
    )
    session.add(entry)
    await session.flush()
    logger.debug(
        "audit: %s %s %s by user=%s",
        action,
        entity_type,
        entity_id or "-",
        user_id or "system",
    )

    # Epic H — shim: mirror every legacy ``oe_core_audit_log`` write into
    # the unified ``oe_activity_log`` so callers building dispute
    # timelines from a single table see the full history. Best-effort: a
    # failure here MUST NOT roll the legacy write back, since callers
    # have been relying on it for two years. If the activity-log write
    # raises, we swallow + log so the legacy contract stays unchanged.
    try:
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            session,
            actor_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            reason=None,
            metadata=details or {},
            module="audit_legacy_shim",
            ip_address=ip_address,
        )
    except Exception:  # pragma: no cover — defensive, see docstring
        logger.exception(
            "audit shim: mirror to oe_activity_log failed (legacy write preserved)",
        )

    return entry


def _parse_iso(value: str | None) -> datetime | None:
    """Best-effort ISO-8601 → ``datetime`` parser.

    Accepts the trailing ``Z`` shorthand for UTC. Returns ``None`` for
    blank/unparseable inputs — callers should treat that as "no filter".
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


async def get_audit_entries(
    session: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEntry]:
    """Query audit log entries with optional filters.

    All filter parameters are optional — when omitted, that filter is not
    applied. ``date_from``/``date_to`` accept ISO-8601 strings (``Z``
    accepted as UTC). ``sort`` is ``"desc"`` (newest first, default) or
    ``"asc"`` (oldest first).
    """
    stmt = select(AuditEntry)
    if entity_type is not None:
        stmt = stmt.where(AuditEntry.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEntry.entity_id == entity_id)
    if user_id is not None:
        try:
            stmt = stmt.where(AuditEntry.user_id == uuid.UUID(user_id))
        except (ValueError, AttributeError):
            # Malformed UUID — return an empty result rather than 500.
            return []
    if action is not None:
        stmt = stmt.where(AuditEntry.action == action)
    parsed_from = _parse_iso(date_from)
    parsed_to = _parse_iso(date_to)
    if parsed_from is not None:
        stmt = stmt.where(AuditEntry.created_at >= parsed_from)
    if parsed_to is not None:
        stmt = stmt.where(AuditEntry.created_at <= parsed_to)
    order_col = AuditEntry.created_at.asc() if sort == "asc" else AuditEntry.created_at.desc()
    stmt = stmt.order_by(order_col).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_audit_entries(
    session: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    """Count audit-log rows matching the same filter set as
    :func:`get_audit_entries`. Used by the admin UI to render
    "Showing 1-50 of 318" — the row paginator on the listing page.
    """
    stmt = select(func.count(AuditEntry.id))
    if entity_type is not None:
        stmt = stmt.where(AuditEntry.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEntry.entity_id == entity_id)
    if user_id is not None:
        try:
            stmt = stmt.where(AuditEntry.user_id == uuid.UUID(user_id))
        except (ValueError, AttributeError):
            return 0
    if action is not None:
        stmt = stmt.where(AuditEntry.action == action)
    parsed_from = _parse_iso(date_from)
    parsed_to = _parse_iso(date_to)
    if parsed_from is not None:
        stmt = stmt.where(AuditEntry.created_at >= parsed_from)
    if parsed_to is not None:
        stmt = stmt.where(AuditEntry.created_at <= parsed_to)
    result = await session.execute(stmt)
    return int(result.scalar() or 0)
