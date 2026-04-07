"""CDE service — business logic for ISO 19650 Common Data Environment.

Stateless service layer. Handles:
- Document container CRUD
- CDE state transitions (wip -> shared -> published -> archived)
- Revision management with auto-numbering
"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cde.models import DocumentContainer, DocumentRevision
from app.modules.cde.repository import ContainerRepository, RevisionRepository
from app.modules.cde.schemas import (
    ContainerCreate,
    ContainerUpdate,
    RevisionCreate,
    StateTransitionRequest,
)

logger = logging.getLogger(__name__)

# Valid CDE state transitions per ISO 19650
_VALID_TRANSITIONS: dict[str, list[str]] = {
    "wip": ["shared"],
    "shared": ["wip", "published"],
    "published": ["archived"],
    "archived": [],
}


class CDEService:
    """Business logic for CDE operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.container_repo = ContainerRepository(session)
        self.revision_repo = RevisionRepository(session)

    # ── Container CRUD ────────────────────────────────────────────────────

    async def create_container(
        self,
        data: ContainerCreate,
        user_id: str | None = None,
    ) -> DocumentContainer:
        """Create a new document container."""
        container = DocumentContainer(
            project_id=data.project_id,
            container_code=data.container_code,
            originator_code=data.originator_code,
            functional_breakdown=data.functional_breakdown,
            spatial_breakdown=data.spatial_breakdown,
            form_code=data.form_code,
            discipline_code=data.discipline_code,
            sequence_number=data.sequence_number,
            classification_system=data.classification_system,
            classification_code=data.classification_code,
            cde_state=data.cde_state,
            suitability_code=data.suitability_code,
            title=data.title,
            description=data.description,
            security_classification=data.security_classification,
            created_by=user_id,
            metadata_=data.metadata,
        )
        container = await self.container_repo.create(container)
        logger.info(
            "CDE container created: %s (%s) for project %s",
            data.container_code,
            data.cde_state,
            data.project_id,
        )
        return container

    async def get_container(self, container_id: uuid.UUID) -> DocumentContainer:
        """Get container by ID. Raises 404 if not found."""
        container = await self.container_repo.get_by_id(container_id)
        if container is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document container not found",
            )
        return container

    async def list_containers(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        cde_state: str | None = None,
        discipline_code: str | None = None,
    ) -> tuple[list[DocumentContainer], int]:
        """List containers for a project."""
        return await self.container_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            cde_state=cde_state,
            discipline_code=discipline_code,
        )

    async def update_container(
        self,
        container_id: uuid.UUID,
        data: ContainerUpdate,
    ) -> DocumentContainer:
        """Update container fields."""
        container = await self.get_container(container_id)

        if container.cde_state == "archived":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit an archived container",
            )

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return container

        await self.container_repo.update_fields(container_id, **fields)
        await self.session.refresh(container)

        logger.info(
            "CDE container updated: %s (fields=%s)",
            container_id,
            list(fields.keys()),
        )
        return container

    # ── CDE State Transitions ─────────────────────────────────────────────

    async def transition_state(
        self,
        container_id: uuid.UUID,
        data: StateTransitionRequest,
    ) -> DocumentContainer:
        """Transition a container's CDE state following ISO 19650 rules."""
        container = await self.get_container(container_id)
        current_state = container.cde_state
        target_state = data.target_state

        if target_state == current_state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Container is already in '{current_state}' state",
            )

        allowed = _VALID_TRANSITIONS.get(current_state, [])
        if target_state not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid state transition: '{current_state}' -> '{target_state}'. "
                    f"Allowed transitions: {allowed}"
                ),
            )

        await self.container_repo.update_fields(container_id, cde_state=target_state)
        await self.session.refresh(container)

        logger.info(
            "CDE state transition: %s -> %s for container %s (reason: %s)",
            current_state,
            target_state,
            container_id,
            data.reason,
        )
        return container

    # ── Revision Management ───────────────────────────────────────────────

    async def create_revision(
        self,
        container_id: uuid.UUID,
        data: RevisionCreate,
        user_id: str | None = None,
    ) -> DocumentRevision:
        """Create a new revision for a container."""
        container = await self.get_container(container_id)

        if container.cde_state == "archived":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot add revisions to an archived container",
            )

        rev_number = await self.revision_repo.next_revision_number(container_id)

        # Generate revision code: P.01.01 for preliminary, C.01 for contractual
        if data.is_preliminary:
            revision_code = f"P.{rev_number:02d}.01"
        else:
            revision_code = f"C.{rev_number:02d}"

        revision = DocumentRevision(
            container_id=container_id,
            revision_code=revision_code,
            revision_number=rev_number,
            is_preliminary=data.is_preliminary,
            content_hash=data.content_hash,
            file_name=data.file_name,
            file_size=data.file_size,
            mime_type=data.mime_type,
            storage_key=data.storage_key,
            status="draft",
            change_summary=data.change_summary,
            created_by=user_id,
            metadata_=data.metadata,
        )
        revision = await self.revision_repo.create(revision)

        # Update the container's current_revision_id
        await self.container_repo.update_fields(
            container_id,
            current_revision_id=str(revision.id),
        )

        logger.info(
            "CDE revision created: %s (rev %s) for container %s",
            revision_code,
            rev_number,
            container_id,
        )
        return revision

    async def get_revision(self, revision_id: uuid.UUID) -> DocumentRevision:
        """Get revision by ID. Raises 404 if not found."""
        revision = await self.revision_repo.get_by_id(revision_id)
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document revision not found",
            )
        return revision

    async def list_revisions(
        self,
        container_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[DocumentRevision], int]:
        """List revisions for a container."""
        # Verify container exists
        await self.get_container(container_id)
        return await self.revision_repo.list_for_container(
            container_id,
            offset=offset,
            limit=limit,
        )
