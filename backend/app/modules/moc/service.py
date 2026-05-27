"""Management of Change (MoC) service — business logic.

State machine:
    proposed  -> reviewed    (moc.review)
    reviewed  -> accepted    (moc.approve)
    reviewed  -> declined    (moc.approve)
    accepted  -> implemented (moc.implement)
    declined  -> [terminal]
    implemented -> [terminal]

All status transitions write an ActivityLog row (``oe_activity_log``) in
the same transaction as the status update so the audit trail is atomic.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.moc.models import MoCEntry, MoCImpact
from app.modules.moc.repository import MoCImpactRepository, MoCRepository
from app.modules.moc.schemas import (
    MoCEntryCreate,
    MoCEntryUpdate,
    MoCImpactCreate,
    MoCImpactUpdate,
)

logger = logging.getLogger(__name__)


# ── FSM ─────────────────────────────────────────────────────────────────────

MOC_TRANSITIONS: dict[str, list[str]] = {
    "proposed": ["reviewed"],
    "reviewed": ["accepted", "declined"],
    "accepted": ["implemented"],
    "declined": [],
    "implemented": [],
}

# Transitions that require ``moc.approve`` (manager-level).
_APPROVE_TRANSITIONS = frozenset({"accepted", "declined"})
# Transitions that require ``moc.review`` (manager-level).
_REVIEW_TRANSITIONS = frozenset({"reviewed"})
# Transitions that require ``moc.implement`` (editor-level).
_IMPLEMENT_TRANSITIONS = frozenset({"implemented"})


def allowed_moc_transitions(current: str) -> list[str]:
    """Pure: return list of statuses a MoCEntry may move to."""
    return list(MOC_TRANSITIONS.get(current, []))


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_publish(name: str, data: dict[str, Any]) -> None:
    try:
        event_bus.publish_detached(name, data, source_module="oe_moc")
    except Exception:
        logger.debug("MoC event publish skipped: %s", name)


async def _write_audit(
    session: AsyncSession,
    *,
    actor_id: str | uuid.UUID | None,
    entry_id: uuid.UUID,
    from_status: str,
    to_status: str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write an ActivityLog row for a MoC status transition (best-effort)."""
    try:
        from app.core.audit_log import log_activity

        await log_activity(
            session,
            actor_id=actor_id,
            entity_type="moc_entry",
            entity_id=str(entry_id),
            action="status_changed",
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            metadata=dict(metadata or {}),
        )
    except Exception:
        logger.warning(
            "ActivityLog write skipped for moc_entry %s (%s -> %s)",
            entry_id,
            from_status,
            to_status,
            exc_info=True,
        )


class MoCService:
    """Business logic for the Management of Change lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MoCRepository(session)
        self.impact_repo = MoCImpactRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_entry(self, data: MoCEntryCreate, user_id: str | None = None) -> MoCEntry:
        """Create a new MoC entry in 'proposed' status."""
        code = await self.repo.next_code(data.project_id)
        now = _now_iso()
        entry = MoCEntry(
            project_id=data.project_id,
            code=code,
            title=data.title,
            description=data.description,
            change_category=data.change_category,
            risk_level=data.risk_level,
            cost_impact=_to_decimal(data.cost_impact),
            schedule_delta_days=data.schedule_delta_days,
            currency=data.currency,
            proposed_by=user_id,
            proposed_at=now,
            status="proposed",
            variation_request_id=data.variation_request_id,
            variation_order_id=data.variation_order_id,
            change_order_id=data.change_order_id,
            metadata_=data.metadata,
        )
        entry = await self.repo.create(entry)
        _safe_publish(
            "moc.entry.proposed",
            {
                "project_id": str(data.project_id),
                "entry_id": str(entry.id),
                "code": code,
                "risk_level": data.risk_level,
            },
        )
        return entry

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_entry(self, entry_id: uuid.UUID) -> MoCEntry:
        row = await self.repo.get_by_id(entry_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="MoC entry not found",
            )
        return row

    async def list_entries(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[MoCEntry], int]:
        return await self.repo.list_for_project(project_id, offset=offset, limit=limit, status=status)

    # ── Update ────────────────────────────────────────────────────────────

    async def update_entry(self, entry_id: uuid.UUID, data: MoCEntryUpdate) -> MoCEntry:
        entry = await self.get_entry(entry_id)
        if entry.status in {"implemented", "declined"}:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"MoC entry is {entry.status} and can no longer be edited",
            )
        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if "cost_impact" in fields and fields["cost_impact"] is not None:
            fields["cost_impact"] = _to_decimal(fields["cost_impact"])
        if not fields:
            return entry
        await self.repo.update_fields(entry_id, **fields)
        await self.session.refresh(entry)
        return entry

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_entry(self, entry_id: uuid.UUID) -> None:
        entry = await self.get_entry(entry_id)
        if entry.status not in {"proposed"}:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Only proposed MoC entries can be deleted",
            )
        await self.repo.delete(entry_id)

    # ── FSM transitions ───────────────────────────────────────────────────

    async def transition(
        self,
        entry_id: uuid.UUID,
        to_status: str,
        user_id: str | None = None,
        notes: str | None = None,
    ) -> MoCEntry:
        """Move a MoCEntry along its FSM. Writes audit log and emits event.

        Allowed transitions are enforced server-side; an invalid ``to_status``
        raises HTTP 409 rather than silently overwriting the column.
        """
        entry = await self.get_entry(entry_id)
        if to_status not in allowed_moc_transitions(entry.status):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot transition MoC entry from '{entry.status}' to '{to_status}'. "
                    f"Allowed: {allowed_moc_transitions(entry.status)}"
                ),
            )
        from_status = entry.status
        now = _now_iso()
        fields: dict[str, Any] = {"status": to_status}

        if to_status == "reviewed":
            fields["reviewed_by"] = user_id
            fields["reviewed_at"] = now
            if notes is not None:
                fields["review_notes"] = notes

        elif to_status in {"accepted", "declined"}:
            fields["decided_by"] = user_id
            fields["decided_at"] = now
            if notes is not None:
                fields["decision_notes"] = notes

        elif to_status == "implemented":
            fields["implemented_by"] = user_id
            fields["implemented_at"] = now

        await self.repo.update_fields(entry_id, **fields)
        await self.session.refresh(entry)

        # Audit trail — same transaction as status write.
        await _write_audit(
            self.session,
            actor_id=user_id,
            entry_id=entry_id,
            from_status=from_status,
            to_status=to_status,
            reason=notes,
            metadata={"code": entry.code, "risk_level": entry.risk_level},
        )

        event_name = {
            "reviewed": "moc.entry.reviewed",
            "accepted": "moc.entry.accepted",
            "declined": "moc.entry.declined",
            "implemented": "moc.entry.implemented",
        }.get(to_status, f"moc.entry.{to_status}")
        _safe_publish(
            event_name,
            {
                "project_id": str(entry.project_id),
                "entry_id": str(entry_id),
                "code": entry.code,
                "to_status": to_status,
                "actor_id": str(user_id) if user_id else None,
            },
        )
        logger.info(
            "MoC entry %s: %s -> %s by %s",
            entry.code,
            from_status,
            to_status,
            user_id,
        )
        return entry

    # ── Impact lines ──────────────────────────────────────────────────────

    async def add_impact(self, entry_id: uuid.UUID, data: MoCImpactCreate) -> MoCImpact:
        await self.get_entry(entry_id)  # 404 guard
        impact = MoCImpact(
            moc_entry_id=entry_id,
            impact_area=data.impact_area,
            description=data.description,
            severity=data.severity,
            cost_impact=_to_decimal(data.cost_impact),
            schedule_delta_days=data.schedule_delta_days,
            currency=data.currency,
            mitigation=data.mitigation,
        )
        return await self.impact_repo.create(impact)

    async def get_impact(self, impact_id: uuid.UUID) -> MoCImpact:
        row = await self.impact_repo.get_by_id(impact_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="MoC impact not found",
            )
        return row

    async def update_impact(self, impact_id: uuid.UUID, data: MoCImpactUpdate) -> MoCImpact:
        impact = await self.get_impact(impact_id)
        fields = data.model_dump(exclude_unset=True)
        if "cost_impact" in fields and fields["cost_impact"] is not None:
            fields["cost_impact"] = _to_decimal(fields["cost_impact"])
        if not fields:
            return impact
        await self.impact_repo.update_fields(impact_id, **fields)
        await self.session.refresh(impact)
        return impact

    async def delete_impact(self, impact_id: uuid.UUID) -> None:
        await self.get_impact(impact_id)  # 404 guard
        await self.impact_repo.delete(impact_id)

    async def list_impacts(self, entry_id: uuid.UUID) -> list[MoCImpact]:
        await self.get_entry(entry_id)  # 404 guard
        return await self.impact_repo.list_for_entry(entry_id)
