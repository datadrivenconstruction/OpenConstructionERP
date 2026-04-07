"""Inspections service — business logic for quality inspection management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.inspections.models import QualityInspection
from app.modules.inspections.repository import InspectionRepository
from app.modules.inspections.schemas import InspectionCreate, InspectionUpdate

logger = logging.getLogger(__name__)


def _validate_checklist_structure(checklist: list[dict[str, Any]]) -> None:
    """Validate checklist_data JSON structure.

    Each item must have at minimum a ``question`` field (non-empty string).
    ``response_type`` must be one of the known types if provided.

    Raises:
        HTTPException 422 if structure is invalid.
    """
    valid_response_types = {"yes_no", "pass_fail", "numeric", "text", "rating"}
    for idx, item in enumerate(checklist):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Checklist item {idx} must be a dict, got {type(item).__name__}",
            )
        question = item.get("question", "")
        if not question or not isinstance(question, str) or len(question.strip()) < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Checklist item {idx} must have a non-empty 'question' field",
            )
        resp_type = item.get("response_type", "yes_no")
        if resp_type and resp_type not in valid_response_types:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Checklist item {idx} has invalid response_type '{resp_type}'. "
                    f"Valid types: {sorted(valid_response_types)}"
                ),
            )


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
        """Create a new inspection with auto-generated number.

        Validates checklist_data structure before persisting.
        """
        inspection_number = await self.repo.next_inspection_number(data.project_id)

        checklist = [entry.model_dump() for entry in data.checklist_data]
        if checklist:
            _validate_checklist_structure(checklist)

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
            _validate_checklist_structure(fields["checklist_data"])

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
        result: str,
    ) -> QualityInspection:
        """Mark an inspection as completed with a required result.

        Args:
            inspection_id: Inspection to complete.
            result: Must be one of ``pass``, ``fail``, or ``partial``.

        Emits ``inspection.completed.failed`` event when result is ``fail``
        or ``partial`` to trigger punchlist item creation flow.
        """
        if result not in ("pass", "fail", "partial"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Result must be 'pass', 'fail', or 'partial', got '{result}'",
            )

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

        # Emit event for failed/partial inspections -> punchlist creation flow
        if result in ("fail", "partial"):
            # Collect failed checklist items for the event payload
            checklist = inspection.checklist_data or []
            failed_items = [
                item for item in checklist
                if isinstance(item, dict) and item.get("response") in ("fail", "no", "false")
            ]
            await event_bus.publish(
                "inspection.completed.failed",
                data={
                    "project_id": str(inspection.project_id),
                    "inspection_id": str(inspection_id),
                    "inspection_number": inspection.inspection_number,
                    "result": result,
                    "failed_items": failed_items,
                },
                source_module="inspections",
            )

        return inspection
