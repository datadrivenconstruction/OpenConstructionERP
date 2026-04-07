"""RFI service — business logic for RFI management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rfi.models import RFI
from app.modules.rfi.repository import RFIRepository
from app.modules.rfi.schemas import RFICreate, RFIUpdate

logger = logging.getLogger(__name__)


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
        """Create a new RFI with auto-generated number."""
        rfi_number = await self.repo.next_rfi_number(data.project_id)

        rfi = RFI(
            project_id=data.project_id,
            rfi_number=rfi_number,
            subject=data.subject,
            question=data.question,
            raised_by=data.raised_by,
            assigned_to=data.assigned_to,
            status=data.status,
            ball_in_court=data.ball_in_court,
            cost_impact=data.cost_impact,
            cost_impact_value=data.cost_impact_value,
            schedule_impact=data.schedule_impact,
            schedule_impact_days=data.schedule_impact_days,
            date_required=data.date_required,
            response_due_date=data.response_due_date,
            linked_drawing_ids=data.linked_drawing_ids,
            change_order_id=data.change_order_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        rfi = await self.repo.create(rfi)
        logger.info("RFI created: %s for project %s", rfi_number, data.project_id)
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
    ) -> tuple[list[RFI], int]:
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
        )

    async def update_rfi(
        self,
        rfi_id: uuid.UUID,
        data: RFIUpdate,
    ) -> RFI:
        rfi = await self.get_rfi(rfi_id)

        if rfi.status == "closed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit a closed RFI",
            )

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return rfi

        await self.repo.update_fields(rfi_id, **fields)
        await self.session.refresh(rfi)
        logger.info("RFI updated: %s (fields=%s)", rfi_id, list(fields.keys()))
        return rfi

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
        """Record an official response to an RFI."""
        rfi = await self.get_rfi(rfi_id)
        if rfi.status in ("closed", "void"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot respond to an RFI with status '{rfi.status}'",
            )

        from datetime import UTC, datetime

        await self.repo.update_fields(
            rfi_id,
            official_response=official_response,
            responded_by=responded_by,
            responded_at=datetime.now(UTC).strftime("%Y-%m-%d"),
            status="answered",
        )
        await self.session.refresh(rfi)
        logger.info("RFI responded: %s by %s", rfi_id, responded_by)
        return rfi

    async def close_rfi(self, rfi_id: uuid.UUID) -> RFI:
        """Close an RFI."""
        rfi = await self.get_rfi(rfi_id)
        if rfi.status == "closed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="RFI is already closed",
            )

        await self.repo.update_fields(rfi_id, status="closed")
        await self.session.refresh(rfi)
        logger.info("RFI closed: %s", rfi_id)
        return rfi
