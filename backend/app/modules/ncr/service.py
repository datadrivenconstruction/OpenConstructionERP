"""NCR service — business logic for non-conformance report management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.ncr.models import NCR
from app.modules.ncr.repository import NCRRepository
from app.modules.ncr.schemas import NCRCreate, NCRUpdate

logger = logging.getLogger(__name__)

# ── Allowed NCR status transitions ────────────────────────────────────────────

_NCR_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "identified": {"under_review", "void"},
    "under_review": {"corrective_action", "identified", "void"},
    "corrective_action": {"verification", "under_review", "void"},
    "verification": {"closed", "corrective_action"},
    "closed": set(),  # terminal
    "void": set(),  # terminal
}


class NCRService:
    """Business logic for NCR operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NCRRepository(session)

    async def create_ncr(
        self,
        data: NCRCreate,
        user_id: str | None = None,
    ) -> NCR:
        """Create a new NCR with auto-generated number."""
        ncr_number = await self.repo.next_ncr_number(data.project_id)

        ncr = NCR(
            project_id=data.project_id,
            ncr_number=ncr_number,
            title=data.title,
            description=data.description,
            ncr_type=data.ncr_type,
            severity=data.severity,
            root_cause=data.root_cause,
            root_cause_category=data.root_cause_category,
            corrective_action=data.corrective_action,
            preventive_action=data.preventive_action,
            status=data.status,
            cost_impact=data.cost_impact,
            schedule_impact_days=data.schedule_impact_days,
            location_description=data.location_description,
            linked_inspection_id=data.linked_inspection_id,
            change_order_id=data.change_order_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        ncr = await self.repo.create(ncr)
        logger.info(
            "NCR created: %s (%s/%s) for project %s",
            ncr_number,
            data.ncr_type,
            data.severity,
            data.project_id,
        )

        # Create notification for project owner (same session avoids
        # SQLite write-lock contention from event_bus handlers)
        try:
            from sqlalchemy import select

            from app.modules.notifications.service import NotificationService
            from app.modules.projects.models import Project

            result = await self.session.execute(
                select(Project.owner_id).where(Project.id == data.project_id)
            )
            owner_id = result.scalar_one_or_none()
            if owner_id:
                notif_svc = NotificationService(self.session)
                await notif_svc.create(
                    user_id=owner_id,
                    notification_type="warning",
                    title_key="notification.ncr_created_title",
                    entity_type="ncr",
                    entity_id=str(ncr.id),
                    body_key="notification.ncr_created_body",
                    body_context={
                        "ncr_number": ncr_number,
                        "title": data.title[:200],
                        "severity": data.severity,
                    },
                    action_url=f"/projects/{data.project_id}/ncr",
                )
        except Exception:
            logger.exception("Failed to create notification for NCR %s", ncr_number)

        # Emit event for additional cross-module handlers (analytics, etc.)
        await event_bus.publish(
            "ncr.created",
            {
                "project_id": str(data.project_id),
                "ncr_id": str(ncr.id),
                "ncr_number": ncr_number,
                "title": data.title,
                "severity": data.severity,
                "ncr_type": data.ncr_type,
                "created_by": user_id,
                "notify_user_ids": [],
            },
            source_module="ncr",
        )

        return ncr

    async def get_ncr(self, ncr_id: uuid.UUID) -> NCR:
        ncr = await self.repo.get_by_id(ncr_id)
        if ncr is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="NCR not found",
            )
        return ncr

    async def list_ncrs(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        ncr_type: str | None = None,
        status_filter: str | None = None,
        severity: str | None = None,
    ) -> tuple[list[NCR], int]:
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            ncr_type=ncr_type,
            status=status_filter,
            severity=severity,
        )

    async def update_ncr(
        self,
        ncr_id: uuid.UUID,
        data: NCRUpdate,
    ) -> NCR:
        ncr = await self.get_ncr(ncr_id)

        if ncr.status in ("closed", "void"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot edit an NCR with status '{ncr.status}'",
            )

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Validate status transition if status is being changed
        new_status = fields.get("status")
        if new_status is not None and new_status != ncr.status:
            allowed = _NCR_STATUS_TRANSITIONS.get(ncr.status, set())
            if new_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot transition NCR from '{ncr.status}' to '{new_status}'. "
                        f"Allowed transitions: {', '.join(sorted(allowed)) or 'none'}"
                    ),
                )

        if not fields:
            return ncr

        await self.repo.update_fields(ncr_id, **fields)
        await self.session.refresh(ncr)
        logger.info("NCR updated: %s (fields=%s)", ncr_id, list(fields.keys()))
        return ncr

    async def delete_ncr(self, ncr_id: uuid.UUID) -> None:
        await self.get_ncr(ncr_id)
        await self.repo.delete(ncr_id)
        logger.info("NCR deleted: %s", ncr_id)

    async def close_ncr(self, ncr_id: uuid.UUID) -> NCR:
        """Close an NCR after verification.

        Closing requires a corrective action to be recorded.  When the NCR
        carries a ``cost_impact`` an event is emitted so the variations
        module (or any subscriber) can create a corresponding variation order.
        """
        ncr = await self.get_ncr(ncr_id)
        if ncr.status == "closed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="NCR is already closed",
            )
        if ncr.status == "void":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot close a voided NCR",
            )
        if not ncr.corrective_action:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot close an NCR without a corrective action",
            )

        await self.repo.update_fields(ncr_id, status="closed")
        await self.session.refresh(ncr)
        logger.info("NCR closed: %s", ncr_id)

        # Emit event for variation creation when cost impact exists
        if ncr.cost_impact:
            await event_bus.publish(
                "ncr.closed_with_cost_impact",
                {
                    "ncr_id": str(ncr.id),
                    "project_id": str(ncr.project_id),
                    "ncr_number": ncr.ncr_number,
                    "title": ncr.title,
                    "cost_impact": ncr.cost_impact,
                    "schedule_impact_days": ncr.schedule_impact_days,
                },
                source_module="ncr",
            )

        return ncr
