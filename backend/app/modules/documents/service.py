"""Document Management service — business logic for document management.

Stateless service layer. Handles:
- Document CRUD
- File upload/download management
- Summary aggregation
- Photo gallery CRUD
"""

import logging
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document, ProjectPhoto
from app.modules.documents.repository import DocumentRepository, PhotoRepository
from app.modules.documents.schemas import DocumentUpdate, PhotoUpdate

logger = logging.getLogger(__name__)

# Base directory for file uploads
UPLOAD_BASE = Path.home() / ".openestimator" / "uploads"

# Base directory for photo uploads
PHOTO_BASE = Path.home() / ".openestimator" / "photos"

# Security constants
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_PHOTO_SIZE = 50 * 1024 * 1024  # 50MB
VALID_CATEGORIES = {"drawing", "contract", "specification", "photo", "correspondence", "other"}
VALID_PHOTO_CATEGORIES = {"site", "progress", "defect", "delivery", "safety", "other"}
ALLOWED_IMAGE_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "image/tiff",
}


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


class PhotoService:
    """Business logic for project photo operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PhotoRepository(session)

    # ── Upload ─────────────────────────────────────────────────────────────

    async def upload_photo(
        self,
        project_id: uuid.UUID,
        file: UploadFile,
        category: str,
        user_id: str,
        caption: str | None = None,
        gps_lat: float | None = None,
        gps_lon: float | None = None,
        tags: list[str] | None = None,
        taken_at: datetime | None = None,
    ) -> ProjectPhoto:
        """Upload a photo and create a record.

        Security measures:
        - MIME type validation (images only)
        - Filename sanitization
        - File size validation (max 50MB)
        - Category validation
        - UUID-prefixed storage path
        """
        # Validate MIME type
        content_type = file.content_type or ""
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type: {content_type}. Only image files are allowed.",
            )

        # Sanitize filename
        raw_name = file.filename or "untitled.jpg"
        safe_name = _sanitize_filename(raw_name)

        # Validate category
        if category not in VALID_PHOTO_CATEGORIES:
            category = "site"

        # Read file content and validate size
        content = await file.read()
        if len(content) > MAX_PHOTO_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Photo too large. Maximum size is {MAX_PHOTO_SIZE // (1024 * 1024)}MB.",
            )

        # Build storage path
        file_uuid = uuid.uuid4().hex[:12]
        storage_name = f"{file_uuid}_{safe_name}"
        upload_dir = PHOTO_BASE / str(project_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / storage_name

        # Create DB record FIRST
        photo = ProjectPhoto(
            project_id=project_id,
            filename=safe_name,
            file_path=str(file_path),
            caption=caption,
            gps_lat=gps_lat,
            gps_lon=gps_lon,
            tags=tags or [],
            taken_at=taken_at,
            category=category,
            created_by=user_id,
        )
        photo = await self.repo.create(photo)

        # Write file AFTER DB record
        try:
            file_path.write_bytes(content)
        except Exception:
            logger.exception("Failed to write photo to disk: %s", file_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save photo to disk.",
            )

        logger.info(
            "Photo uploaded: %s (%d bytes) for project %s",
            safe_name,
            len(content),
            project_id,
        )
        return photo

    # ── Read ───────────────────────────────────────────────────────────────

    async def get_photo(self, photo_id: uuid.UUID) -> ProjectPhoto:
        """Get photo by ID. Raises 404 if not found."""
        photo = await self.repo.get_by_id(photo_id)
        if photo is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Photo not found",
            )
        return photo

    async def list_photos(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        category: str | None = None,
        tag: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
    ) -> tuple[list[ProjectPhoto], int]:
        """List photos for a project with filters."""
        photos, total = await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            category=category,
            tag=tag,
            date_from=date_from,
            date_to=date_to,
            search=search,
        )

        # Filter by tag in Python (JSON column)
        if tag:
            photos = [p for p in photos if tag in (p.tags or [])]

        return photos, total

    async def get_gallery(
        self, project_id: uuid.UUID
    ) -> list[ProjectPhoto]:
        """Get all photos for the gallery view."""
        photos, _ = await self.repo.list_for_project(
            project_id, offset=0, limit=500
        )
        return photos

    async def get_timeline(
        self, project_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Get photos grouped by date for timeline view."""
        photos, _ = await self.repo.list_for_project(
            project_id, offset=0, limit=500
        )

        groups: dict[str, list[ProjectPhoto]] = defaultdict(list)
        for photo in photos:
            date_key = (photo.taken_at or photo.created_at).strftime("%Y-%m-%d")
            groups[date_key].append(photo)

        # Sort by date descending
        sorted_dates = sorted(groups.keys(), reverse=True)
        return [{"date": d, "photos": groups[d]} for d in sorted_dates]

    # ── Update ─────────────────────────────────────────────────────────────

    async def update_photo(
        self,
        photo_id: uuid.UUID,
        data: PhotoUpdate,
    ) -> ProjectPhoto:
        """Update photo metadata fields."""
        photo = await self.get_photo(photo_id)

        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return photo

        await self.repo.update_fields(photo_id, **fields)
        await self.session.refresh(photo)

        logger.info("Photo updated: %s (fields=%s)", photo_id, list(fields.keys()))
        return photo

    # ── Delete ─────────────────────────────────────────────────────────────

    async def delete_photo(self, photo_id: uuid.UUID) -> None:
        """Delete a photo and its file."""
        photo = await self.get_photo(photo_id)
        file_path_str = photo.file_path

        # Delete DB record FIRST
        await self.repo.delete(photo_id)
        logger.info("Photo deleted: %s", photo_id)

        # Then remove file from disk (best-effort)
        try:
            file_path = Path(file_path_str)
            if file_path.exists():
                file_path.unlink()
                logger.info("Photo file removed: %s", file_path)
        except Exception:
            logger.warning("Failed to remove photo file: %s", file_path_str)
