"""Inspections service — business logic for quality inspection management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inspections.models import QualityInspection
from app.modules.inspections.repository import InspectionRepository
from app.modules.inspections.schemas import InspectionCreate, InspectionUpdate

logger = logging.getLogger(__name__)


class InspectionService:
    """Business logic for inspection operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = InspectionRepository(session)

    async def create_inspection(
        self,
        data: InspectionCreate,
        user_id: str | None = None,
    ) -> QualityInspection:
        """Create a new inspection with auto-generated number."""
        inspection_number = await self.repo.next_inspection_number(data.project_id)

        checklist = [entry.model_dump() for entry in data.checklist_data]

        inspection = QualityInspection(
            project_id=data.project_id,
            inspection_number=inspection_number,
            inspection_type=data.inspection_type,
            title=data.title,
            description=data.description,
            location=data.location,
            wbs_id=data.wbs_id,
            inspector_id=data.inspector_id,
            inspection_date=data.inspection_date,
            status=data.status,
            result=data.result,
            checklist_data=checklist,
            created_by=user_id,
            metadata_=data.metadata,
        )
        inspection = await self.repo.create(inspection)
        logger.info(
            "Inspection created: %s (%s) for project %s",
            inspection_number,
            data.inspection_type,
            data.project_id,
        )
        return inspection

    async def get_inspection(self, inspection_id: uuid.UUID) -> QualityInspection:
        """Get inspection by ID. Raises 404 if not found."""
        inspection = await self.repo.get_by_id(inspection_id)
        if inspection is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Inspection not found",
            )
        return inspection

    async def list_inspections(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        inspection_type: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[QualityInspection], int]:
        """List inspections for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            inspection_type=inspection_type,
            status=status_filter,
        )

    async def update_inspection(
        self,
        inspection_id: uuid.UUID,
        data: InspectionUpdate,
    ) -> QualityInspection:
        """Update inspection fields."""
        inspection = await self.get_inspection(inspection_id)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if "checklist_data" in fields and fields["checklist_data"] is not None:
            fields["checklist_data"] = [
                entry.model_dump() if hasattr(entry, "model_dump") else entry
                for entry in fields["checklist_data"]
            ]

        if not fields:
            return inspection

        await self.repo.update_fields(inspection_id, **fields)
        await self.session.refresh(inspection)
        logger.info("Inspection updated: %s (fields=%s)", inspection_id, list(fields.keys()))
        return inspection

    async def delete_inspection(self, inspection_id: uuid.UUID) -> None:
        """Delete an inspection."""
        await self.get_inspection(inspection_id)
        await self.repo.delete(inspection_id)
        logger.info("Inspection deleted: %s", inspection_id)

    async def complete_inspection(
        self,
        inspection_id: uuid.UUID,
        result: str = "pass",
    ) -> QualityInspection:
        """Mark an inspection as completed with a result."""
        inspection = await self.get_inspection(inspection_id)
        if inspection.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inspection is already completed",
            )
        if inspection.status == "cancelled":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot complete a cancelled inspection",
            )

        await self.repo.update_fields(
            inspection_id,
            status="completed",
            result=result,
        )
        await self.session.refresh(inspection)
        logger.info("Inspection completed: %s (result=%s)", inspection_id, result)
        return inspection
