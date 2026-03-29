"""Document Management service — business logic for document management.

Stateless service layer. Handles:
- Document CRUD
- File upload/download management
- Summary aggregation
"""

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document
from app.modules.documents.repository import DocumentRepository
from app.modules.documents.schemas import DocumentUpdate

logger = logging.getLogger(__name__)

# Base directory for file uploads
UPLOAD_BASE = Path.home() / ".openestimator" / "uploads"


class DocumentService:
    """Business logic for document operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DocumentRepository(session)

    # ── Upload ─────────────────────────────────────────────────────────────

    async def upload_document(
        self,
        project_id: uuid.UUID,
        file: UploadFile,
        category: str,
        user_id: str,
    ) -> Document:
        """Upload a file and create a document record."""
        upload_dir = UPLOAD_BASE / str(project_id)
        upload_dir.mkdir(parents=True, exist_ok=True)

        filename = file.filename or "untitled"
        file_path = upload_dir / filename

        # Read file content
        content = await file.read()
        file_path.write_bytes(content)

        document = Document(
            project_id=project_id,
            name=filename,
            category=category,
            file_size=len(content),
            mime_type=file.content_type or "",
            file_path=str(file_path),
            uploaded_by=user_id,
        )
        document = await self.repo.create(document)

        logger.info(
            "Document uploaded: %s (%d bytes) for project %s",
            filename,
            len(content),
            project_id,
        )
        return document

    # ── Read ───────────────────────────────────────────────────────────────

    async def get_document(self, document_id: uuid.UUID) -> Document:
        """Get document by ID. Raises 404 if not found."""
        document = await self.repo.get_by_id(document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )
        return document

    async def list_documents(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        category: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Document], int]:
        """List documents for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            category=category,
            search=search,
        )

    # ── Update ─────────────────────────────────────────────────────────────

    async def update_document(
        self,
        document_id: uuid.UUID,
        data: DocumentUpdate,
    ) -> Document:
        """Update document metadata fields."""
        document = await self.get_document(document_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return document

        await self.repo.update_fields(document_id, **fields)
        await self.session.refresh(document)

        logger.info("Document updated: %s (fields=%s)", document_id, list(fields.keys()))
        return document

    # ── Delete ─────────────────────────────────────────────────────────────

    async def delete_document(self, document_id: uuid.UUID) -> None:
        """Delete a document and its file."""
        document = await self.get_document(document_id)

        # Remove file from disk
        try:
            file_path = Path(document.file_path)
            if file_path.exists():
                file_path.unlink()
                logger.info("File removed: %s", file_path)
        except Exception:
            logger.warning("Failed to remove file: %s", document.file_path)

        await self.repo.delete(document_id)
        logger.info("Document deleted: %s", document_id)

    # ── Summary ────────────────────────────────────────────────────────────

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get aggregated stats for a project's documents."""
        items = await self.repo.all_for_project(project_id)

        by_category: dict[str, int] = {}
        total_size = 0

        for item in items:
            by_category[item.category] = by_category.get(item.category, 0) + 1
            total_size += item.file_size

        return {
            "total_documents": len(items),
            "total_size_bytes": total_size,
            "by_category": by_category,
        }
