# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""NCR service - business logic for non-conformance report management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus, publish_after_commit
from app.core.json_merge import merge_metadata
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

    async def _check_change_order(self, project_id: uuid.UUID, change_order_id: str) -> str:
        """Return *change_order_id* normalised, or 400 unless it is a change order of the project.

        ``change_order_id`` is a plain ``VARCHAR(36)`` with no foreign key. A
        database foreign key is deliberately not added: running installs
        already hold free strings in the column, the boot heal would add the
        key ``NOT VALID`` over them (such a row can never be repointed), and
        the change orders table belongs to another module. So the link is
        checked here, on every write that names one.
        """
        try:
            order_uuid = uuid.UUID(str(change_order_id).strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="change_order_id is not a change order id",
            ) from exc
        # Lazy import: ncr stays loadable without the changeorders module.
        from sqlalchemy import select  # noqa: PLC0415

        from app.modules.changeorders.models import ChangeOrder  # noqa: PLC0415

        found = await self.session.scalar(
            select(ChangeOrder.id).where(ChangeOrder.id == order_uuid, ChangeOrder.project_id == project_id)
        )
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Change order not found in this project",
            )
        return str(order_uuid)

    async def create_ncr(
        self,
        data: NCRCreate,
        user_id: str | None = None,
    ) -> NCR:
        """Create a new NCR with auto-generated number."""
        change_order_id = data.change_order_id or None
        if change_order_id:
            change_order_id = await self._check_change_order(data.project_id, change_order_id)
        ncr = NCR(
            project_id=data.project_id,
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
            location_lat=data.location_lat,
            location_lon=data.location_lon,
            location_accuracy_m=data.location_accuracy_m,
            linked_inspection_id=data.linked_inspection_id,
            change_order_id=change_order_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        ncr = await self.repo.create(ncr)
        # The repository assigns ncr_number (with a collision retry) at insert
        # time, so read the committed value back for logging and notifications.
        ncr_number = ncr.ncr_number
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

            result = await self.session.execute(select(Project.owner_id).where(Project.id == data.project_id))
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

        # Emit event for additional cross-module handlers (analytics,
        # webhooks, smart-notifications, geo pins, etc.).
        #
        # Two properties this call site has to hold, both of them learned the
        # hard way:
        #
        # 1. It publishes AFTER the caller's transaction commits. Every
        #    subscriber opens its own session, so a publish from inside the
        #    open transaction shows them an NCR that does not exist yet.
        # 2. The payload is self-sufficient. Everything a subscriber could
        #    reasonably want - including the coordinates the geo_hub pin is
        #    drawn from - is in here, so no subscriber ever has to go and read
        #    ``oe_ncr_ncr`` back. A payload that only carries an id makes
        #    every subscriber depend on commit ordering all over again.
        #
        # ``publish_detached`` (not a bare ``asyncio.create_task``) keeps a
        # strong reference to the task, so it cannot be garbage-collected
        # while suspended at an await.
        #
        # Every value is snapshotted into a local here, not read off ``ncr``
        # inside the closure: the closure runs during the commit, and an ORM
        # instance is not a safe thing to read attributes off from there.
        ncr_id = str(ncr.id)
        location_lat = str(ncr.location_lat) if ncr.location_lat is not None else None
        location_lon = str(ncr.location_lon) if ncr.location_lon is not None else None
        location_accuracy_m = str(ncr.location_accuracy_m) if ncr.location_accuracy_m is not None else None

        publish_after_commit(
            self.session,
            "ncr.created",
            {
                "project_id": str(data.project_id),
                "ncr_id": ncr_id,
                "ncr_number": ncr_number,
                "title": data.title,
                "description": data.description,
                "severity": data.severity,
                "ncr_type": data.ncr_type,
                "status": data.status,
                "location_description": data.location_description,
                "lat": location_lat,
                "lon": location_lon,
                "accuracy_m": location_accuracy_m,
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
        # Checked only when it changes: a row written before the check may hold
        # a free string, and echoing it back on an unrelated edit must not fail.
        if fields.get("change_order_id") and fields["change_order_id"] != ncr.change_order_id:
            fields["change_order_id"] = await self._check_change_order(ncr.project_id, fields["change_order_id"])
        # Merge a partial metadata patch into the existing column instead of
        # replacing it wholesale - a PATCH touching one key must not wipe the
        # rest. NCRs are auto-created with source/report tracking keys in
        # metadata, which a naive overwrite would silently drop.
        if "metadata" in fields:
            incoming_meta = fields.pop("metadata")
            if isinstance(incoming_meta, dict):
                fields["metadata_"] = merge_metadata(getattr(ncr, "metadata_", None), incoming_meta)
            else:
                fields["metadata_"] = incoming_meta

        # A position needs both halves. ``NCRUpdate`` deliberately does not
        # enforce this on its own - a PATCH carrying only a longitude is a
        # legitimate correction to a row that already has a latitude - so the
        # rule is applied here, against the merged result, which is the only
        # place both halves are visible. Sending both as null clears it.
        merged_lat = fields.get("location_lat", ncr.location_lat)
        merged_lon = fields.get("location_lon", ncr.location_lon)
        if (merged_lat is None) != (merged_lon is None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="location_lat and location_lon must both be set or both be cleared",
            )

        # Validate status transition if status is being changed
        new_status = fields.get("status")
        prior_status = ncr.status
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

        # FSM audit row when status changed
        if new_status is not None and new_status != prior_status:
            try:
                from app.core.audit_log import log_activity

                await log_activity(
                    self.session,
                    actor_id=None,
                    entity_type="ncr",
                    entity_id=str(ncr_id),
                    action="status_changed",
                    from_status=prior_status,
                    to_status=new_status,
                    reason="NCR status updated via update_ncr()",
                    metadata={"ncr_number": ncr.ncr_number},
                )
            except Exception:
                logger.debug("FSM audit log skipped for NCR %s update", ncr_id)

        logger.info("NCR updated: %s (fields=%s)", ncr_id, list(fields.keys()))
        return ncr

    async def delete_ncr(self, ncr_id: uuid.UUID) -> None:
        ncr = await self.get_ncr(ncr_id)
        # A closed NCR is the verified record update_ncr freezes, and a void
        # one is how an NCR raised in error leaves the register. Change orders
        # and MoC entries reference both by id, so they are kept.
        if ncr.status in ("closed", "void"):
            remedy = "" if ncr.status == "closed" else " Voiding already takes it out of the open register."
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot delete a {ncr.status} NCR: it is kept as the quality record.{remedy}",
            )
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
        # FSM guard: per _NCR_STATUS_TRANSITIONS only 'verification' -> 'closed'
        # is allowed. Without this an NCR in 'identified', 'under_review' or
        # 'corrective_action' could skip the mandatory verification step.
        if "closed" not in _NCR_STATUS_TRANSITIONS.get(ncr.status, set()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot close an NCR from status '{ncr.status}'. "
                    "An NCR must be in 'verification' status before it can be closed."
                ),
            )
        if not ncr.corrective_action:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot close an NCR without a corrective action",
            )

        prior_status = ncr.status
        await self.repo.update_fields(ncr_id, status="closed")
        await self.session.refresh(ncr)

        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=None,
                entity_type="ncr",
                entity_id=str(ncr_id),
                action="status_changed",
                from_status=prior_status,
                to_status="closed",
                reason="NCR closed via close_ncr()",
                metadata={"ncr_number": ncr.ncr_number},
            )
        except Exception:
            logger.debug("FSM audit log skipped for NCR %s close", ncr_id)

        logger.info("NCR closed: %s", ncr_id)

        # Emit event for variation creation when cost impact exists
        if ncr.cost_impact:
            event_bus.publish_detached(
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
