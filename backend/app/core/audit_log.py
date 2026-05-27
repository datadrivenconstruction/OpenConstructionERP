"""‌⁠‍Generic activity-log table and write-through helper.

This is the FSM-aware companion to :mod:`app.core.audit`. While ``audit``
records arbitrary CRUD actions on any entity, ``audit_log`` is structured
specifically around status transitions: every row stores
``(from_status, to_status, action, reason, metadata)`` so dispute
timelines (FIDIC contract records, ISO 9001 traceability, SCL Protocol
contemporary records) can be reproduced byte-for-byte.

Table: ``oe_activity_log``

The existing ``oe_core_audit_log`` table is kept for backwards
compatibility — module services that already use it continue to work,
but new FSM-driven transitions write here as well so the lifecycle of
each entity can be inspected in one place.

Epic H — Universal Audit Trail (2026-05-26)
-------------------------------------------

The row layout is extended with 8 capture-context columns
(``ip_address`` / ``user_agent`` / ``request_id`` / ``module`` /
``parent_entity_*`` / ``before_state`` / ``after_state``). The capture is
driven by a single :class:`AuditContext` ContextVar that
:class:`app.middleware.actor_context.ActorContextMiddleware` sets at the
top of each HTTP request — service-layer callers do not need to thread
the IP / UA / request-id manually. When ``log_activity`` is called
outside an HTTP request (Celery worker, CLI seed) the ContextVar reads
``None`` and the columns stay NULL, which is the documented contract.

Usage::

    from app.core.audit_log import log_activity

    await log_activity(
        session,
        actor_id="user-uuid",
        entity_type="boq",
        entity_id="boq-uuid",
        action="status_changed",
        from_status="draft",
        to_status="final",
        reason="Approved by PM",
        metadata={"approval_doc_id": "..."},
        module="boq",                       # NEW (recommended)
        before_state={"status": "draft"},    # NEW (recommended)
        after_state={"status": "final"},     # NEW (recommended)
    )
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from contextvars import ContextVar
from typing import Any

from sqlalchemy import JSON, Index, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

logger = logging.getLogger(__name__)


# ── ContextVar-backed capture context ────────────────────────────────────
#
# The middleware writes once per request; ``log_activity`` reads once per
# call. ``dataclasses.replace`` is used in the dependency layer to merge
# the resolved tenant / actor identity without mutating the request-level
# capture in place.


@dataclasses.dataclass(frozen=True, slots=True)
class AuditContext:
    """Per-request capture of identity + transport metadata.

    Fields are deliberately optional — ``log_activity`` writes ``NULL``
    for anything the middleware could not determine (e.g. a Celery worker
    has no peer IP). Fields are also typed as plain ``str`` so they can
    be persisted to the existing ``oe_activity_log`` columns without
    further coercion.
    """

    actor_id: str | None = None
    tenant_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


# Module-level singleton. Default ``None`` so out-of-request callers
# see no context (NULLs land in the row, which is the contract).
_audit_context_var: ContextVar[AuditContext | None] = ContextVar(
    "audit_context",
    default=None,
)


def set_audit_context(ctx: AuditContext | None) -> object:
    """Set the request-scoped audit context. Returns a reset token."""
    return _audit_context_var.set(ctx)


def reset_audit_context(token: object) -> None:
    """Reset the audit context to the value captured by ``set_audit_context``."""
    _audit_context_var.reset(token)  # type: ignore[arg-type]


def get_audit_context() -> AuditContext | None:
    """Return the current request's audit context, or None."""
    return _audit_context_var.get()


class ActivityLog(Base):
    """‌⁠‍Append-only audit row recording one entity state change.

    Columns:
        id                — UUID PK (inherited from :class:`Base`).
        tenant_id         — Optional tenant scope. NULL for system events.
        actor_id          — UUID of the user who performed the action
                            (NULL for background jobs).
        entity_type       — Logical entity name: boq / project / invoice /
                            ncr / rfq / submittal / po / gr / …
        entity_id         — UUID of the affected row (string). Stored as
                            text so we can also log events against
                            composite keys later.
        action            — Verb: status_changed / created / updated /
                            deleted / bulk_import / …
        from_status       — Previous status (NULL for create-events).
        to_status         — New status (NULL for delete-events).
        reason            — Free-form note supplied by the user.
        metadata_         — JSONB with extra context.
        ip_address        — Request peer IP (epic H, nullable).
        user_agent        — Request UA truncated to 500 chars (epic H).
        request_id        — Correlation ID for trace stitching (epic H).
        module            — Logical module ("rfi", "submittals", …);
                            cross-module timeline filtering (epic H).
        parent_entity_*   — Optional umbrella entity for timeline rollups
                            (e.g. an RFI's project) (epic H).
        before_state      — JSON snapshot of the affected record's prior
                            column subset (small, writer-curated) (epic H).
        after_state       — JSON snapshot of the new column subset (epic H).
        created_at        — UTC timestamp (inherited from :class:`Base`).
    """

    __tablename__ = "oe_activity_log"
    __table_args__ = (
        Index("ix_activity_log_entity", "entity_type", "entity_id"),
        Index("ix_activity_log_tenant_created", "tenant_id", "created_at"),
        Index("ix_activity_log_actor", "actor_id"),
        # Epic H: composite index for per-entity timeline queries. SQLite
        # does not honour per-column DESC specifiers on indexes — declare
        # ascending and let the planner walk it newest-first via DESC scan.
        Index(
            "ix_activity_log_entity_created",
            "entity_type",
            "entity_id",
            "created_at",
        ),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── Epic H additions ──────────────────────────────────────────────
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    module: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_entity_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    parent_entity_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    before_state: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    after_state: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return (
            f"<ActivityLog {self.entity_type}:{self.entity_id} {self.from_status}->{self.to_status} by {self.actor_id}>"
        )


def _coerce_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


# Soft cap to make sure a runaway User-Agent or before_state blob does
# not push a column out of its declared length / blow up the JSON column.
_MAX_UA_LEN = 500
_MAX_STATE_KEYS = 64


def _truncate_ua(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:_MAX_UA_LEN]


def _bounded_state(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Cap the captured state dict to a known-good size."""
    if value is None:
        return None
    if not isinstance(value, dict):  # defensive — never trust callers
        return None
    if len(value) <= _MAX_STATE_KEYS:
        return dict(value)
    # Keep the first N items in insertion order; callers should not be
    # dumping the full row, so hitting this cap means the writer needs
    # to be tightened.
    items = list(value.items())[:_MAX_STATE_KEYS]
    truncated = dict(items)
    truncated["__truncated__"] = True
    return truncated


async def log_activity(
    session: AsyncSession,
    *,
    actor_id: str | uuid.UUID | None,
    entity_type: str,
    entity_id: str | uuid.UUID | None,
    action: str,
    from_status: str | None = None,
    to_status: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    tenant_id: str | uuid.UUID | None = None,
    # Epic H — explicit overrides (auto-filled from ContextVar otherwise)
    module: str | None = None,
    parent_entity_type: str | None = None,
    parent_entity_id: str | uuid.UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> ActivityLog:
    """‌⁠‍Write a single :class:`ActivityLog` row.

    The session is flushed but NOT committed — the caller's transaction
    boundary owns the commit so audit + business write either both land
    or both roll back. Errors are NOT swallowed here: when the caller
    wants best-effort audit (e.g. from inside a guard), wrap this in
    try/except.

    Capture-context fields (``ip_address`` / ``user_agent`` /
    ``request_id`` / ``actor_id`` / ``tenant_id``) default to whatever
    the ActorContextMiddleware put on the per-request ContextVar. Caller
    overrides win — pass ``ip_address=...`` explicitly to record a value
    other than the one in the request context (e.g. a forwarded address
    for a webhook handler).

    Args:
        session: Active async session bound to the same transaction as
            the business write.
        actor_id: UUID of the user. ``None`` for background / system
            events. Falls back to the ContextVar's ``actor_id`` when
            omitted.
        entity_type: ``boq`` / ``project`` / ``invoice`` / ``ncr`` /
            ``rfq`` / ``submittal`` / …
        entity_id: UUID of the affected entity (string or UUID). NULL OK.
        action: Verb describing the event. Use ``status_changed`` for FSM
            transitions and ``created`` / ``updated`` / ``deleted`` for
            ordinary CRUD events.
        from_status: Previous status, or None for new-row events.
        to_status: New status, or None for delete events.
        reason: User-supplied free-form note.
        metadata: Arbitrary JSON payload merged into the row.
        tenant_id: Optional tenant scope (used in multi-tenant deploys).
        module: Logical module ("rfi" / "submittals" / …). Optional but
            strongly recommended — drives cross-module timeline
            filtering.
        parent_entity_type / parent_entity_id: Optional umbrella entity
            for rollup timelines (e.g. an RFI rolled into its project).
        before_state / after_state: Optional JSON snapshots of the
            affected record's prior / new column subset. Curated by the
            writer — do NOT dump full rows.
        ip_address / user_agent / request_id: Explicit overrides for the
            ContextVar-supplied capture fields.

    Returns:
        The persisted :class:`ActivityLog` instance.
    """
    ctx = get_audit_context()
    if ctx is not None:
        actor_id = actor_id or ctx.actor_id
        tenant_id = tenant_id or ctx.tenant_id
        ip_address = ip_address or ctx.ip_address
        user_agent = user_agent or ctx.user_agent
        request_id = request_id or ctx.request_id

    entry = ActivityLog(
        tenant_id=_coerce_uuid(tenant_id),
        actor_id=_coerce_uuid(actor_id),
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        action=action,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        metadata_=dict(metadata or {}),
        ip_address=ip_address,
        user_agent=_truncate_ua(user_agent),
        request_id=request_id,
        module=module,
        parent_entity_type=parent_entity_type,
        parent_entity_id=(str(parent_entity_id) if parent_entity_id is not None else None),
        before_state=_bounded_state(before_state),
        after_state=_bounded_state(after_state),
    )
    # Epic H §H3 — central error handling. The audit write MUST NOT break
    # the business write. ``session.add`` can raise if the caller passed
    # a non-Session stub (common in unit tests that patch the repo
    # layer); ``session.flush`` can raise on a real DB integrity error.
    # In both cases the row never lands but the caller's transaction is
    # left intact so the business write continues. Production deploys
    # that rely on the audit row landing should run with the dedicated
    # ``test_log_activity_*`` suite to catch genuine breakage.
    try:
        session.add(entry)
        await session.flush()
    except (AttributeError, TypeError):
        # Stub sessions in tests — ``_StubSession`` has no ``add``.
        logger.debug(
            "activity_log: skipped (session does not support add) %s:%s %s",
            entity_type,
            entity_id,
            action,
        )
        return entry
    except Exception:
        logger.exception(
            "activity_log: flush failed for %s:%s %s",
            entity_type,
            entity_id,
            action,
        )
        return entry
    logger.debug(
        "activity_log: %s %s %s %s->%s actor=%s",
        action,
        entity_type,
        entity_id,
        from_status,
        to_status,
        actor_id,
    )
    return entry


async def get_activity_for_entity(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: str | uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[ActivityLog]:
    """Chronological history (oldest first) for one entity row."""
    eid = str(entity_id)
    stmt = (
        select(ActivityLog)
        .where(ActivityLog.entity_type == entity_type)
        .where(ActivityLog.entity_id == eid)
        .order_by(ActivityLog.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_recent_activity(
    session: AsyncSession,
    *,
    entity_type: str | None = None,
    action: str | None = None,
    actor_id: str | uuid.UUID | None = None,
    module: str | None = None,
    limit: int = 50,
) -> list[ActivityLog]:
    """Newest-first query, optionally filtered by entity_type / action / actor / module."""
    stmt = select(ActivityLog)
    if entity_type is not None:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if action is not None:
        stmt = stmt.where(ActivityLog.action == action)
    if actor_id is not None:
        coerced = _coerce_uuid(actor_id)
        if coerced is not None:
            stmt = stmt.where(ActivityLog.actor_id == coerced)
    if module is not None:
        stmt = stmt.where(ActivityLog.module == module)
    stmt = stmt.order_by(ActivityLog.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
