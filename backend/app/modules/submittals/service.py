"""Submittals service — business logic for submittal management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.submittals.models import Submittal
from app.modules.submittals.repository import SubmittalRepository
from app.modules.submittals.schemas import SubmittalCreate, SubmittalUpdate

logger = logging.getLogger(__name__)


class SubmittalService:
    """Business logic for submittal operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SubmittalRepository(session)

    async def create_submittal(
        self,
        data: SubmittalCreate,
        user_id: str | None = None,
    ) -> Submittal:
        """Create a new submittal with auto-generated number."""
        submittal_number = await self.repo.next_submittal_number(data.project_id)

        submittal = Submittal(
            project_id=data.project_id,
            submittal_number=submittal_number,
            title=data.title,
            spec_section=data.spec_section,
            submittal_type=data.submittal_type,
            status=data.status,
            ball_in_court=data.ball_in_court,
            current_revision=data.current_revision,
            submitted_by_org=data.submitted_by_org,
            reviewer_id=data.reviewer_id,
            approver_id=data.approver_id,
            date_submitted=data.date_submitted,
            date_required=data.date_required,
            date_returned=data.date_returned,
            linked_boq_item_ids=data.linked_boq_item_ids,
            created_by=user_id,
            metadata_=data.metadata,
        )
        submittal = await self.repo.create(submittal)
        logger.info(
            "Submittal created: %s (%s) for project %s",
            submittal_number,
            data.submittal_type,
            data.project_id,
        )
        return submittal

    async def get_submittal(self, submittal_id: uuid.UUID) -> Submittal:
        submittal = await self.repo.get_by_id(submittal_id)
        if submittal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submittal not found",
            )
        return submittal

    async def list_submittals(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        submittal_type: str | None = None,
    ) -> tuple[list[Submittal], int]:
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            submittal_type=submittal_type,
        )

    async def update_submittal(
        self,
        submittal_id: uuid.UUID,
        data: SubmittalUpdate,
    ) -> Submittal:
        submittal = await self.get_submittal(submittal_id)

        if submittal.status == "closed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit a closed submittal",
            )

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return submittal

        await self.repo.update_fields(submittal_id, **fields)
        await self.session.refresh(submittal)
        logger.info("Submittal updated: %s (fields=%s)", submittal_id, list(fields.keys()))
        return submittal

    async def delete_submittal(self, submittal_id: uuid.UUID) -> None:
        await self.get_submittal(submittal_id)
        await self.repo.delete(submittal_id)
        logger.info("Submittal deleted: %s", submittal_id)

    async def submit_submittal(self, submittal_id: uuid.UUID) -> Submittal:
        """Move submittal from draft to submitted."""
        submittal = await self.get_submittal(submittal_id)
        if submittal.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Can only submit from draft status, current: {submittal.status}",
            )

        from datetime import UTC, datetime

        await self.repo.update_fields(
            submittal_id,
            status="submitted",
            date_submitted=datetime.now(UTC).strftime("%Y-%m-%d"),
        )
        await self.session.refresh(submittal)
        logger.info("Submittal submitted: %s", submittal_id)
        return submittal

    async def review_submittal(
        self,
        submittal_id: uuid.UUID,
        new_status: str,
        reviewer_id: str,
    ) -> Submittal:
        """Review a submittal (approve, reject, etc.)."""
        submittal = await self.get_submittal(submittal_id)
        if submittal.status not in ("submitted", "under_review"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot review submittal with status '{submittal.status}'",
            )

        from datetime import UTC, datetime

        fields: dict[str, Any] = {
            "status": new_status,
            "reviewer_id": reviewer_id,
            "date_returned": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        await self.repo.update_fields(submittal_id, **fields)
        await self.session.refresh(submittal)
        logger.info("Submittal reviewed: %s -> %s by %s", submittal_id, new_status, reviewer_id)
        return submittal

    async def approve_submittal(
        self,
        submittal_id: uuid.UUID,
        approver_id: str,
    ) -> Submittal:
        """Final approval of a submittal."""
        submittal = await self.get_submittal(submittal_id)
        if submittal.status in ("closed", "rejected"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve submittal with status '{submittal.status}'",
            )

        from datetime import UTC, datetime

        fields: dict[str, Any] = {
            "status": "approved",
            "approver_id": approver_id,
            "date_returned": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        await self.repo.update_fields(submittal_id, **fields)
        await self.session.refresh(submittal)
        logger.info("Submittal approved: %s by %s", submittal_id, approver_id)
        return submittal
