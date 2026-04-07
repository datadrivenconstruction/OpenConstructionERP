"""System-wide audit log for tracking important entity changes.

Usage:
    from app.core.audit import audit_log
    await audit_log(session, action="create", entity_type="contact", entity_id=str(id),
                    user_id=str(user_id), details={"company_name": "Siemens"})
"""

import logging
import uuid

from sqlalchemy import JSON, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

logger = logging.getLogger(__name__)


class AuditEntry(Base):
    """Audit log entry tracking important entity changes.

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
    """Write a single audit log entry.

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
    return entry


async def get_audit_entries(
    session: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEntry]:
    """Query audit log entries with optional filters.

    All filter parameters are optional — when omitted, that filter is not
    applied.  Results are ordered newest-first.
    """
    stmt = select(AuditEntry)
    if entity_type is not None:
        stmt = stmt.where(AuditEntry.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEntry.entity_id == entity_id)
    if user_id is not None:
        stmt = stmt.where(AuditEntry.user_id == uuid.UUID(user_id))
    if action is not None:
        stmt = stmt.where(AuditEntry.action == action)
    stmt = stmt.order_by(AuditEntry.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
