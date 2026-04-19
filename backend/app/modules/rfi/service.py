"""RFI service — business logic for RFI management.

- Event publishing on create/update/delete
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.rfi.models import RFI
from app.modules.rfi.repository import RFIRepository
from app.modules.rfi.schemas import RFICreate, RFIStatsResponse, RFIUpdate

logger = logging.getLogger(__name__)
_logger_ev = logging.getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)

_RFI_RESPONSE_DUE_DAYS = 14

# ── Allowed RFI status transitions ────────────────────────────────────────────

_RFI_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"open", "void"},
    "open": {"answered", "closed", "void"},
    "answered": {"closed", "open"},
    "closed": set(),  # terminal
    "void": set(),  # terminal
}


def _add_business_days(start: datetime, days: int) -> str:
    """Return ISO date string after adding *days* business days to *start*."""
    added = 0
    current = start
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            added += 1
    return current.strftime("%Y-%m-%d")


class RFIService:
    """Business logic for RFI operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = RFIRepository(session)

    async def create_rfi(
        self,
        data: RFICreate,
        user_id: str | None = None,
    ) -> RFI:
        """Create a new RFI with auto-generated number.

        Ball-in-court is automatically set to ``assigned_to`` when present.
        Response due date defaults to 14 business days from today when the
        status is ``open`` and no explicit due date is provided.
        """
        rfi_number = await self.repo.next_rfi_number(data.project_id)

        # Auto-set ball_in_court to assigned_to on creation
        ball_in_court = data.ball_in_court
        if ball_in_court is None and data.assigned_to is not None:
            ball_in_court = data.assigned_to

        # Auto-calculate response_due_date (14 business days) when status
        # is 'open' and no explicit due date was given.
        response_due_date = data.response_due_date
        if response_due_date is None and data.status == "open":
            response_due_date = _add_business_days(datetime.now(UTC), _RFI_RESPONSE_DUE_DAYS)

        rfi = RFI(
            project_id=data.project_id,
            rfi_number=rfi_number,
            subject=data.subject,
            question=data.question,
            raised_by=data.raised_by or (uuid.UUID(user_id) if user_id else None),
            assigned_to=data.assigned_to,
            status=data.status,
            ball_in_court=ball_in_court,
            cost_impact=data.cost_impact,
            cost_impact_value=data.cost_impact_value,
            schedule_impact=data.schedule_impact,
            schedule_impact_days=data.schedule_impact_days,
            date_required=data.date_required,
            response_due_date=response_due_date,
            linked_drawing_ids=data.linked_drawing_ids,
            change_order_id=data.change_order_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        rfi = await self.repo.create(rfi)
        logger.info("RFI created: %s for project %s", rfi_number, data.project_id)

        # Publish rfi.assigned event so notification handlers fire
        if data.assigned_to:
            await _safe_publish(
                "rfi.assigned",
                {
                    "project_id": str(data.project_id),
                    "rfi_id": str(rfi.id),
                    "rfi_number": rfi_number,
                    "subject": data.subject,
                    "assigned_to": str(data.assigned_to),
                    "assigned_by": user_id or "",
                },
                source_module="oe_rfi",
            )

        return rfi

    async def get_rfi(self, rfi_id: uuid.UUID) -> RFI:
        rfi = await self.repo.get_by_id(rfi_id)
        if rfi is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RFI not found",
            )
        return rfi

    async def list_rfis(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        search: str | None = None,
    ) -> tuple[list[RFI], int]:
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            search=search,
        )

    async def update_rfi(
        self,
        rfi_id: uuid.UUID,
        data: RFIUpdate,
    ) -> RFI:
        rfi = await self.get_rfi(rfi_id)

        if rfi.status in ("closed", "void"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot edit an RFI with status '{rfi.status}'",
            )

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Validate status transition if status is being changed
        new_status = fields.get("status")
        if new_status is not None and new_status != rfi.status:
            allowed = _RFI_STATUS_TRANSITIONS.get(rfi.status, set())
            if new_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot transition RFI from '{rfi.status}' to '{new_status}'. "
                        f"Allowed transitions: {', '.join(sorted(allowed)) or 'none'}"
                    ),
                )

        # When status transitions to 'open' and no response_due_date is set,
        # auto-calculate it (14 business days from now).
        new_status = fields.get("status")
        if new_status == "open" and not rfi.response_due_date:
            if "response_due_date" not in fields or fields["response_due_date"] is None:
                fields["response_due_date"] = _add_business_days(
                    datetime.now(UTC), _RFI_RESPONSE_DUE_DAYS
                )

        # Auto-update ball_in_court when assigned_to changes
        if "assigned_to" in fields and "ball_in_court" not in fields:
            fields["ball_in_court"] = fields["assigned_to"]

        if not fields:
            return rfi

        # Detect reassignment so we can fire rfi.assigned
        old_assigned = str(rfi.assigned_to) if rfi.assigned_to else None
        new_assigned = fields.get("assigned_to")
        # Snapshot attrs before update_fields detaches them from the session.
        project_id_s = str(rfi.project_id)
        rfi_number_s = rfi.rfi_number
        subject_s = rfi.subject

        await self.repo.update_fields(rfi_id, **fields)
        fresh = await self.repo.get_by_id(rfi_id)
        logger.info("RFI updated: %s (fields=%s)", rfi_id, list(fields.keys()))

        # Fire rfi.assigned when assigned_to changes to a new user
        if (
            new_assigned is not None
            and str(new_assigned) != old_assigned
        ):
            await _safe_publish(
                "rfi.assigned",
                {
                    "project_id": project_id_s,
                    "rfi_id": str(rfi_id),
                    "rfi_number": rfi_number_s,
                    "subject": subject_s,
                    "assigned_to": str(new_assigned),
                },
                source_module="oe_rfi",
            )

        return fresh or rfi

    async def delete_rfi(self, rfi_id: uuid.UUID) -> None:
        await self.get_rfi(rfi_id)
        await self.repo.delete(rfi_id)
        logger.info("RFI deleted: %s", rfi_id)

    async def respond_to_rfi(
        self,
        rfi_id: uuid.UUID,
        official_response: str,
        responded_by: str,
    ) -> RFI:
        """Record an official response to an RFI.

        Ball-in-court automatically flips to ``raised_by`` so the originator
        can review the answer. Publishes ``rfi.responded`` event so
        subscribers (notifications, project intelligence) can react.
        """
        rfi = await self.get_rfi(rfi_id)
        if rfi.status in ("closed", "void"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot respond to an RFI with status '{rfi.status}'",
            )

        # Snapshot attrs before update_fields.
        project_id_s = str(rfi.project_id)
        rfi_number_s = rfi.rfi_number
        subject_s = rfi.subject
        raised_by_s = str(rfi.raised_by) if rfi.raised_by else None

        await self.repo.update_fields(
            rfi_id,
            official_response=official_response,
            responded_by=responded_by,
            responded_at=datetime.now(UTC).strftime("%Y-%m-%d"),
            status="answered",
            ball_in_court=str(rfi.raised_by),
        )
        fresh = await self.repo.get_by_id(rfi_id)

        await _safe_publish(
            "rfi.responded",
            {
                "project_id": project_id_s,
                "rfi_id": str(rfi_id),
                "rfi_number": rfi_number_s,
                "subject": subject_s,
                "responded_by": responded_by,
                "raised_by": raised_by_s,
                "ball_in_court": raised_by_s,
            },
            source_module="oe_rfi",
        )

        logger.info("RFI responded: %s by %s", rfi_id, responded_by)
        return fresh or rfi

    async def close_rfi(self, rfi_id: uuid.UUID, *, closed_by: str | None = None) -> RFI:
        """Close an RFI.

        Requires an official response before closing to prevent
        unanswered RFIs from being silently closed. Publishes ``rfi.closed`` event.
        """
        rfi = await self.get_rfi(rfi_id)
        if rfi.status == "closed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="RFI is already closed",
            )
        if not rfi.official_response:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot close an RFI without an official response",
            )

        project_id_s = str(rfi.project_id)
        rfi_number_s = rfi.rfi_number
        subject_s = rfi.subject

        await self.repo.update_fields(rfi_id, status="closed", ball_in_court=None)
        fresh = await self.repo.get_by_id(rfi_id)

        await _safe_publish(
            "rfi.closed",
            {
                "project_id": project_id_s,
                "rfi_id": str(rfi_id),
                "rfi_number": rfi_number_s,
                "subject": subject_s,
                "closed_by": closed_by,
            },
            source_module="oe_rfi",
        )

        logger.info("RFI closed: %s by %s", rfi_id, closed_by)
        return fresh or rfi

    async def get_stats(self, project_id: uuid.UUID) -> RFIStatsResponse:
        """Compute summary statistics for all RFIs in a project.

        Returns total, open, overdue counts, average response time,
        and cost/schedule impact counts.
        """
        from sqlalchemy import select

        now = datetime.now(UTC)
        today_str = now.strftime("%Y-%m-%d")

        # Fetch all RFIs for the project (unfiltered, no pagination)
        base = select(RFI).where(RFI.project_id == project_id)
        result = await self.session.execute(base)
        rfis = list(result.scalars().all())

        total = len(rfis)
        by_status: dict[str, int] = {}
        open_count = 0
        overdue_count = 0
        cost_impact_count = 0
        schedule_impact_count = 0
        response_days: list[float] = []

        for rfi in rfis:
            # Count by status
            by_status[rfi.status] = by_status.get(rfi.status, 0) + 1

            # Open = draft or open
            if rfi.status in ("draft", "open"):
                open_count += 1

            # Overdue = open/draft + past due date
            if rfi.status in ("draft", "open") and rfi.response_due_date:
                try:
                    if rfi.response_due_date < today_str:
                        overdue_count += 1
                except (TypeError, ValueError):
                    pass

            # Impact counts
            if rfi.cost_impact:
                cost_impact_count += 1
            if rfi.schedule_impact:
                schedule_impact_count += 1

            # Average response time (only for answered/closed with responded_at)
            if rfi.status in ("answered", "closed") and rfi.responded_at and rfi.created_at:
                try:
                    resp_date = datetime.fromisoformat(str(rfi.responded_at))
                    if resp_date.tzinfo is None:
                        resp_date = resp_date.replace(tzinfo=UTC)
                    created = rfi.created_at
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=UTC)
                    days = max(0.0, (resp_date - created).total_seconds() / 86400)
                    response_days.append(days)
                except (ValueError, TypeError):
                    pass

        avg_days_to_response: float | None = None
        if response_days:
            avg_days_to_response = round(sum(response_days) / len(response_days), 1)

        return RFIStatsResponse(
            total=total,
            by_status=by_status,
            open=open_count,
            overdue=overdue_count,
            avg_days_to_response=avg_days_to_response,
            cost_impact_count=cost_impact_count,
            schedule_impact_count=schedule_impact_count,
        )
