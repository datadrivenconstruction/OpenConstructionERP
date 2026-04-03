"""Document Management service — business logic for document management.

Stateless service layer. Handles:
- Document CRUD
- File upload/download management
- Summary aggregation
"""

import logging
import os
import re
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

# Security constants
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
VALID_CATEGORIES = {"drawing", "contract", "specification", "photo", "correspondence", "other"}


def _sanitize_filename(name: str) -> str:
    """Remove path components and dangerous characters from filename."""
    name = os.path.basename(name)
    name = re.sub(r"[^\w.\-]", "_", name)
    if not name or name.startswith("."):
        name = "untitled"
    return name


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
        """Upload a file and create a document record.

        Security measures:
        - Filename sanitization (path traversal prevention)
        - File size validation (max 100MB)
        - Category validation against allowed list
        - UUID-prefixed storage path to avoid collisions
        - File written AFTER DB record creation for easy rollback
        """
        # Sanitize filename
        raw_name = file.filename or "untitled"
        safe_name = _sanitize_filename(raw_name)

        # Validate category
        if category not in VALID_CATEGORIES:
            category = "other"

        # Read file content and validate size
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB.",
            )

        # Build storage path with UUID prefix to avoid collisions
        file_uuid = uuid.uuid4().hex[:12]
        storage_name = f"{file_uuid}_{safe_name}"
        upload_dir = UPLOAD_BASE / str(project_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / storage_name

        # Create DB record FIRST — if this fails we haven't written a file
        document = Document(
            project_id=project_id,
            name=safe_name,
            category=category,
            file_size=len(content),
            mime_type=file.content_type or "",
            file_path=str(file_path),
            uploaded_by=user_id,
        )
        document = await self.repo.create(document)

        # Write file AFTER DB record so we can rollback cleanly
        try:
            file_path.write_bytes(content)
        except Exception:
            logger.exception("Failed to write file to disk: %s", file_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save file to disk.",
            )

        logger.info(
            "Document uploaded: %s (%d bytes) for project %s",
            safe_name,
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
        """Delete a document and its file.

        DB record is deleted first so a failure there prevents orphan file removal.
        File removal failure is logged but not fatal — leaves an orphan file rather
        than an orphan DB record pointing to a missing file.
        """
        document = await self.get_document(document_id)
        file_path_str = document.file_path

        # Delete DB record FIRST — this is the authoritative state
        await self.repo.delete(document_id)
        logger.info("Document deleted: %s", document_id)

        # Then remove file from disk (best-effort)
        try:
            file_path = Path(file_path_str)
            if file_path.exists():
                file_path.unlink()
                logger.info("File removed: %s", file_path)
        except Exception:
            logger.warning("Failed to remove file: %s", file_path_str)

    # ── Summary ────────────────────────────────────────────────────────────

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get aggregated stats for a project's documents.

        Uses SQL COUNT/SUM aggregation instead of loading all records into memory.
        """
        total_count, total_size, cat_rows = await self.repo.summary_for_project(project_id)

        by_category: dict[str, int] = {cat: count for cat, count in cat_rows}

        return {
            "total_documents": total_count,
            "total_size_bytes": total_size,
            "by_category": by_category,
        }
