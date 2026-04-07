"""Correspondence service — business logic for correspondence management."""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.correspondence.models import Correspondence
from app.modules.correspondence.repository import CorrespondenceRepository
from app.modules.correspondence.schemas import CorrespondenceCreate, CorrespondenceUpdate

logger = logging.getLogger(__name__)


class CorrespondenceService:
    """Business logic for correspondence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CorrespondenceRepository(session)

    async def create_correspondence(
        self,
        data: CorrespondenceCreate,
        user_id: str | None = None,
    ) -> Correspondence:
        """Create a new correspondence record with auto-generated reference number."""
        reference_number = await self.repo.next_reference_number(data.project_id)

        correspondence = Correspondence(
            project_id=data.project_id,
            reference_number=reference_number,
            direction=data.direction,
            subject=data.subject,
            from_contact_id=data.from_contact_id,
            to_contact_ids=data.to_contact_ids,
            date_sent=data.date_sent,
            date_received=data.date_received,
            correspondence_type=data.correspondence_type,
            linked_document_ids=data.linked_document_ids,
            linked_transmittal_id=data.linked_transmittal_id,
            linked_rfi_id=data.linked_rfi_id,
            notes=data.notes,
            created_by=user_id,
            metadata_=data.metadata,
        )
        correspondence = await self.repo.create(correspondence)
        logger.info(
            "Correspondence created: %s (%s/%s) for project %s",
            reference_number,
            data.direction,
            data.correspondence_type,
            data.project_id,
        )
        return correspondence

    async def get_correspondence(self, correspondence_id: uuid.UUID) -> Correspondence:
        correspondence = await self.repo.get_by_id(correspondence_id)
        if correspondence is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Correspondence not found",
            )
        return correspondence

    async def list_correspondences(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        direction: str | None = None,
        correspondence_type: str | None = None,
    ) -> tuple[list[Correspondence], int]:
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            direction=direction,
            correspondence_type=correspondence_type,
        )

    async def update_correspondence(
        self,
        correspondence_id: uuid.UUID,
        data: CorrespondenceUpdate,
    ) -> Correspondence:
        correspondence = await self.get_correspondence(correspondence_id)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return correspondence

        await self.repo.update_fields(correspondence_id, **fields)
        await self.session.refresh(correspondence)
        logger.info(
            "Correspondence updated: %s (fields=%s)",
            correspondence_id,
            list(fields.keys()),
        )
        return correspondence

    async def delete_correspondence(self, correspondence_id: uuid.UUID) -> None:
        await self.get_correspondence(correspondence_id)
        await self.repo.delete(correspondence_id)
        logger.info("Correspondence deleted: %s", correspondence_id)
