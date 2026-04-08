"""Document Management service — business logic for document management.

Stateless service layer. Handles:
- Document CRUD
- File upload/download management
- Summary aggregation
- Photo gallery CRUD
- Sheet management (PDF split, OCR detection)
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

from app.modules.documents.models import Document, ProjectPhoto, Sheet
from app.modules.documents.repository import DocumentRepository, PhotoRepository, SheetRepository
from app.modules.documents.schemas import DocumentUpdate, PhotoUpdate, SheetUpdate

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
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/tiff",
}
BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".ps1", ".com", ".scr",
    ".msi", ".dll", ".vbs", ".js", ".ws", ".wsf", ".pif",
    ".hta", ".cpl", ".msp", ".mst", ".reg",
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

        # Block dangerous file extensions
        ext = Path(safe_name).suffix.lower()
        if ext in BLOCKED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type '{ext}' is not allowed for security reasons.",
            )

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

    # Valid CDE state transitions (ISO 19650 workflow)
    VALID_CDE_TRANSITIONS: dict[str, list[str]] = {
        "wip": ["shared"],
        "shared": ["published", "wip"],
        "published": ["archived", "wip"],
        "archived": ["wip"],
    }

    async def update_document(
        self,
        document_id: uuid.UUID,
        data: DocumentUpdate,
    ) -> Document:
        """Update document metadata fields.

        Validates CDE state transitions if cde_state is being changed.
        """
        document = await self.get_document(document_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return document

        # Validate CDE state transition
        if "cde_state" in fields and fields["cde_state"] is not None:
            new_state = fields["cde_state"]
            current_state = document.cde_state
            if current_state is not None:
                allowed = self.VALID_CDE_TRANSITIONS.get(current_state, [])
                if new_state not in allowed:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Invalid CDE state transition: '{current_state}' -> '{new_state}'. "
                            f"Allowed: {allowed}"
                        ),
                    )

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
        recent_docs = await self.repo.recent_uploads(project_id, limit=5)

        by_category: dict[str, int] = {cat: count for cat, count in cat_rows}

        recent_uploads = [
            {
                "name": doc.name,
                "uploaded_at": doc.created_at.isoformat() if doc.created_at else "",
                "size": doc.file_size or 0,
            }
            for doc in recent_docs
        ]

        return {
            "total": total_count,
            "total_documents": total_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 1) if total_size else 0.0,
            "by_category": by_category,
            "recent_uploads": recent_uploads,
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

    async def get_gallery(self, project_id: uuid.UUID) -> list[ProjectPhoto]:
        """Get all photos for the gallery view."""
        photos, _ = await self.repo.list_for_project(project_id, offset=0, limit=500)
        return photos

    async def get_timeline(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Get photos grouped by date for timeline view."""
        photos, _ = await self.repo.list_for_project(project_id, offset=0, limit=500)

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


# ── Discipline prefix mapping ────────────────────────────────────────────

DISCIPLINE_PREFIX_MAP: dict[str, str] = {
    "A": "Architectural",
    "S": "Structural",
    "M": "Mechanical",
    "E": "Electrical",
    "P": "Plumbing",
    "C": "Civil",
    "L": "Landscape",
}

# Base directory for sheet thumbnails
SHEET_THUMB_BASE = Path.home() / ".openestimator" / "sheets"


def detect_discipline_from_sheet_number(sheet_number: str | None) -> str | None:
    """Auto-detect discipline from sheet number prefix.

    Common AEC convention: first letter indicates discipline.
    E.g., "A-201" -> Architectural, "S-100" -> Structural.
    """
    if not sheet_number:
        return None
    prefix = sheet_number.strip()[0].upper()
    return DISCIPLINE_PREFIX_MAP.get(prefix)


def detect_sheet_info(page_text: str) -> dict[str, str | None]:
    """Extract sheet number, title, scale, and revision from page text.

    Uses simple regex patterns on extracted text to find common title block fields.
    Does NOT rely on external OCR services — works on already-extracted text.

    Returns:
        Dict with keys: sheet_number, sheet_title, scale, revision
    """
    result: dict[str, str | None] = {
        "sheet_number": None,
        "sheet_title": None,
        "scale": None,
        "revision": None,
    }

    if not page_text:
        return result

    # Sheet number patterns: "A-201", "S-100", "M001", "E-2.01", "SHEET: A-201"
    sheet_num_patterns = [
        r"(?:SHEET\s*(?:NO\.?|NUMBER|#|:)\s*)([A-Z]\s*[-.]?\s*\d[\w.-]*)",
        r"(?:DWG\s*(?:NO\.?|#|:)\s*)([A-Z]?\s*[-.]?\s*\d[\w.-]*)",
        r"\b([A-Z]-\d{2,4}(?:\.\d+)?)\b",
        r"\b([A-Z]\d{3,4})\b",
    ]
    for pattern in sheet_num_patterns:
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            result["sheet_number"] = match.group(1).strip()
            break

    # Sheet title patterns: "TITLE: Floor Plan", "SHEET TITLE: ..."
    title_patterns = [
        r"(?:SHEET\s*TITLE|TITLE)\s*[:=]\s*(.+?)(?:\n|$)",
        r"(?:DRAWING\s*TITLE)\s*[:=]\s*(.+?)(?:\n|$)",
    ]
    for pattern in title_patterns:
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            if len(title) > 2:
                result["sheet_title"] = title[:500]
            break

    # Scale patterns: "1:100", "1/4\" = 1'-0\"", "SCALE: 1:50"
    scale_patterns = [
        r"(?:SCALE)\s*[:=]\s*([\d/:\"'\-\s]+\S*)",
        r"\b(1\s*:\s*\d{1,4})\b",
        r"(1/\d+\"\s*=\s*1'[\s-]*0\")",
    ]
    for pattern in scale_patterns:
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            result["scale"] = match.group(1).strip()[:50]
            break

    # Revision patterns: "REV A", "REVISION: 3", "Rev. B"
    rev_patterns = [
        r"(?:REV(?:ISION)?\.?\s*(?:NO\.?|#|:)?\s*)([A-Z0-9]+)",
    ]
    for pattern in rev_patterns:
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            result["revision"] = match.group(1).strip()[:50]
            break

    return result


class SheetService:
    """Business logic for drawing sheet operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SheetRepository(session)

    # ── Read ───────────────────────────────────────────────────────────────

    async def get_sheet(self, sheet_id: uuid.UUID) -> Sheet:
        """Get sheet by ID. Raises 404 if not found."""
        sheet = await self.repo.get_by_id(sheet_id)
        if sheet is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sheet not found",
            )
        return sheet

    async def list_sheets(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        discipline: str | None = None,
        revision: str | None = None,
        document_id: str | None = None,
        current_only: bool = False,
    ) -> tuple[list[Sheet], int]:
        """List sheets for a project with filters."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            discipline=discipline,
            revision=revision,
            document_id=document_id,
            current_only=current_only,
        )

    async def get_disciplines(self, project_id: uuid.UUID) -> list[str]:
        """Return distinct discipline values for a project."""
        return await self.repo.distinct_disciplines(project_id)

    async def get_version_history(self, sheet_id: uuid.UUID) -> dict[str, Any]:
        """Get version history for a sheet.

        Returns the current sheet and all historical revisions.
        """
        current = await self.get_sheet(sheet_id)
        chain = await self.repo.get_version_chain(sheet_id)
        # Remove current sheet from history list
        history = [s for s in chain if s.id != current.id]
        return {"current": current, "history": history}

    # ── Update ─────────────────────────────────────────────────────────────

    async def update_sheet(
        self,
        sheet_id: uuid.UUID,
        data: SheetUpdate,
    ) -> Sheet:
        """Update sheet metadata fields."""
        sheet = await self.get_sheet(sheet_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return sheet

        await self.repo.update_fields(sheet_id, **fields)
        await self.session.refresh(sheet)

        logger.info("Sheet updated: %s (fields=%s)", sheet_id, list(fields.keys()))
        return sheet

    # ── Split PDF ──────────────────────────────────────────────────────────

    async def split_pdf_to_sheets(
        self,
        project_id: uuid.UUID,
        file: UploadFile,
        user_id: str,
    ) -> list[Sheet]:
        """Upload a multi-page PDF, split into individual sheets.

        For each page:
        1. Extract text using pdfplumber
        2. Detect sheet number, title, scale, revision from text
        3. Auto-detect discipline from sheet number prefix
        4. Save page thumbnail as PNG
        5. Create Sheet record in database

        Returns:
            List of created Sheet records.
        """
        try:
            import pdfplumber
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="pdfplumber is not installed. Install with: pip install pdfplumber",
            )

        # Read uploaded file
        raw_name = file.filename or "untitled.pdf"
        safe_name = _sanitize_filename(raw_name)

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB.",
            )

        # Save the original PDF to uploads
        file_uuid = uuid.uuid4().hex[:12]
        upload_dir = UPLOAD_BASE / str(project_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = upload_dir / f"{file_uuid}_{safe_name}"
        pdf_path.write_bytes(content)

        # Also create a Document record for the uploaded PDF
        doc_repo = DocumentRepository(self.session)
        document = Document(
            project_id=project_id,
            name=safe_name,
            category="drawing",
            file_size=len(content),
            mime_type="application/pdf",
            file_path=str(pdf_path),
            uploaded_by=user_id,
        )
        document = await doc_repo.create(document)
        document_id = str(document.id)

        # Create thumbnail directory
        thumb_dir = SHEET_THUMB_BASE / str(project_id)
        thumb_dir.mkdir(parents=True, exist_ok=True)

        sheets: list[Sheet] = []

        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    page_number = page_idx + 1

                    # Extract text for sheet info detection
                    page_text = page.extract_text() or ""

                    # Detect sheet info from text
                    info = detect_sheet_info(page_text)
                    sheet_number = info["sheet_number"]
                    discipline = detect_discipline_from_sheet_number(sheet_number)

                    # Generate thumbnail
                    thumbnail_path_str: str | None = None
                    try:
                        page_image = page.to_image(resolution=72)
                        thumb_filename = f"{file_uuid}_page_{page_number}.png"
                        thumb_path = thumb_dir / thumb_filename
                        page_image.save(str(thumb_path), format="PNG")
                        thumbnail_path_str = str(thumb_path)
                    except Exception:
                        logger.warning(
                            "Failed to generate thumbnail for page %d of %s",
                            page_number,
                            safe_name,
                        )

                    sheet = Sheet(
                        project_id=project_id,
                        document_id=document_id,
                        page_number=page_number,
                        sheet_number=sheet_number,
                        sheet_title=info["sheet_title"],
                        discipline=discipline,
                        revision=info["revision"],
                        scale=info["scale"],
                        is_current=True,
                        thumbnail_path=thumbnail_path_str,
                        created_by=user_id,
                    )
                    sheets.append(sheet)

        except Exception as exc:
            logger.exception("Failed to process PDF: %s", safe_name)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to process PDF file: {exc}",
            )

        if sheets:
            sheets = await self.repo.create_many(sheets)

        logger.info(
            "PDF split into %d sheets: %s for project %s",
            len(sheets),
            safe_name,
            project_id,
        )
        return sheets
