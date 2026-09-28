# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document Management service - business logic for document management.

Stateless service layer. Handles:
- Document CRUD
- File upload/download management
- Summary aggregation
- Photo gallery CRUD
- Sheet management (PDF split, OCR detection)
- Document ↔ BIM element linking
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cde_states import CDEState, CDEStateMachine
from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.upload_streaming import stream_upload_to_temp
from app.core.validation.messages import translate
from app.modules.bim_hub.models import BIMElement
from app.modules.documents.activity_service import record_activity
from app.modules.documents.models import Document, DocumentBIMLink, ProjectPhoto, Sheet
from app.modules.documents.repository import DocumentRepository, PhotoRepository, SheetRepository
from app.modules.documents.schemas import (
    PHOTO_CATEGORIES,
    DocumentBIMLinkCreate,
    DocumentReferenceItem,
    DocumentReferencesResponse,
    DocumentUpdate,
    PhotoUpdate,
    SheetUpdate,
)

logger = logging.getLogger(__name__)

# ── ISO 19650 CDE state machine (shared, stateless) ───────────────────────
#
# The Documents PATCH path enforces the SAME ISO 19650 lifecycle rules the
# CDE-container service uses, so a document promoted via ``PATCH /documents``
# obeys the identical forward-only transitions and role gates. The machine is
# stateless (encodes only rules) so a single module-level instance is safe.
_state_machine = CDEStateMachine()

# Mapping from canonical app roles (admin / manager / editor / viewer, see
# app.core.permissions.Role) onto the ISO 19650 role names the CDEStateMachine
# gates are keyed by (viewer / editor / task_team_manager / lead_ap / admin).
# The JWT payload only ever carries an app role, so without this translation a
# project ``manager`` resolved to rank -1 and could never cross any gate.
#
# Gate ranks: Gate A needs task_team_manager(2), Gate B needs lead_ap(3),
# Gate C needs admin(4). The ``documents.update`` permission is EDITOR-level
# and the CDE-document promotions are MANAGER-level, so a manager must clear
# Gate A and Gate B (→ lead_ap) while archiving (Gate C) stays admin-only.
_APP_ROLE_TO_ISO: dict[str, str] = {
    "admin": "admin",
    "manager": "lead_ap",
    "editor": "editor",
    "viewer": "viewer",
}

# Industry-title aliases that behave like one of the canonical four roles
# (mirrors app.core.permissions.ROLE_ALIASES so a "quantity_surveyor" maps to
# editor, "owner" to admin, etc.). Kept local to avoid importing the alias
# table at module import time.
_ROLE_ALIASES: dict[str, str] = {
    "estimator": "editor",
    "quantity_surveyor": "editor",
    "qs": "editor",
    "user": "editor",
    "superuser": "admin",
    "owner": "admin",
    "readonly": "viewer",
    "guest": "viewer",
}


def _iso_role_for(app_role: str | None) -> str:
    """Translate an app/JWT role into the ISO 19650 role the gates use.

    Unknown roles fall through to ``viewer`` (least authority) so an
    unrecognised role can never accidentally pass a gate.
    """
    role = (app_role or "viewer").strip().lower()
    role = _ROLE_ALIASES.get(role, role)
    return _APP_ROLE_TO_ISO.get(role, role)


async def _register_version_safely(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    file_kind: str,
    entity: Any,
    file_id: str,
    file_size: int,
    uploaded_by: str | None,
) -> None:
    """Best-effort register-new-version call.

    Epic C - every upload path must register a chain row so the version
    history is continuous. Wrapped in a try/except so a chain-write
    failure (e.g. ``oe_file_version`` table missing on a misconfigured
    install) cannot mask a successful upload. The kind-side row is the
    source of truth; the chain row is the index.

    The ``except`` needs a SAVEPOINT under it to mean what it says. A failed
    flush leaves the session unusable and catching the error does not revive
    it, so without one this "best effort" call would take down whatever the
    upload path does next - including the documents cross-link that runs two
    lines later and opens a savepoint of its own.
    """
    try:
        from app.modules.file_versions.helpers import canonical_name_for
        from app.modules.file_versions.schemas import FileVersionCreate
        from app.modules.file_versions.service import FileVersionService

        svc = FileVersionService(session)
        canonical = canonical_name_for(file_kind, entity)
        uploaded_by_uuid: uuid.UUID | None
        try:
            uploaded_by_uuid = uuid.UUID(str(uploaded_by)) if uploaded_by else None
        except (TypeError, ValueError):
            uploaded_by_uuid = None
        payload = FileVersionCreate(
            project_id=project_id,
            file_kind=file_kind,  # type: ignore[arg-type]
            file_id=file_id,
            canonical_name=canonical,
            file_size=int(file_size or 0),
        )
        # The savepoint the docstring above is about. This runs before the
        # rest of the upload path, so a failure here is the one with the most
        # left to damage.
        async with session.begin_nested():
            await svc.register_new_version(payload, uploaded_by_id=uploaded_by_uuid)
    except Exception:
        logger.warning(
            "Failed to register FileVersion chain row for kind=%s file_id=%s",
            file_kind,
            file_id,
            exc_info=True,
        )


def _upload_root() -> Path:
    """Base directory document/photo/sheet uploads are written under.

    Honours an explicit operator data dir (``OE_DATA_DIR`` / ``DATA_DIR`` /
    ``OE_CLI_DATA_DIR``) via the canonical resolver, so a containerised
    deployment that mounts a persistent volume (for example ``-v
    host_dir:/data`` with ``OE_DATA_DIR=/data``) actually gets its uploads
    written there. Previously these were hard-coded to ``~/.openestimator``;
    inside a container whose home is ``/app`` that resolved to
    ``/app/.openestimator``, so every uploaded document and drawing landed in
    the container's ephemeral layer and was lost on the next ``docker compose
    up`` / image rebuild, while the mounted ``/data`` volume stayed empty.

    When no data dir is configured we keep the historical ``~/.openestimator``
    location so existing installs keep finding files written by earlier
    versions - nothing is silently moved.
    """
    if os.environ.get("OE_DATA_DIR") or os.environ.get("DATA_DIR") or os.environ.get("OE_CLI_DATA_DIR"):
        from app.core.storage import resolve_data_dir

        return resolve_data_dir()
    return Path.home() / ".openestimator"


# Base directory for file uploads
UPLOAD_BASE = _upload_root() / "uploads"

# Base directory for photo uploads
PHOTO_BASE = _upload_root() / "photos"
# Base directory for photo thumbnails - stored next to originals under a sibling
# ``thumbs/`` subfolder so the gallery grid can ask for a small, cheap image
# instead of re-streaming the 50 MB original on every render.
PHOTO_THUMB_BASE = _upload_root() / "photos" / "thumbs"
# Longest side (in px) of a generated photo thumbnail. 512 is plenty for the
# grid view and keeps the thumbnail under ~60 kB for typical JPEGs.
PHOTO_THUMB_MAX_SIDE = 512
PHOTO_THUMB_QUALITY = 82

# Security constants
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
MAX_PHOTO_SIZE = 200 * 1024 * 1024  # 200MB
# A photo's PIXEL count, not its byte size, is what OOMs the image decoder: a
# ~150 MP image is only a few MB on disk (so it sails past MAX_PHOTO_SIZE) but
# decodes to ~600 MB of uncompressed RGB, enough to OOM-kill the single-worker
# container on the 3 GB target box while it blocks the event loop. Pillow ships
# NO pixel guard by default, so cap decoded pixels the same way geo_hub caps
# rasters (raster_pipeline.MAX_RASTER_PIXELS). 64 MP is ~8000x8000, well above
# any real construction-site phone or DSLR photo.
MAX_PHOTO_PIXELS = 64 * 1024 * 1024  # 64 MP (mirrors geo_hub MAX_RASTER_PIXELS)
VALID_CATEGORIES = {
    "drawing",
    "contract",
    "specification",
    "photo",
    "correspondence",
    "reality_capture",
    "other",
}
# Same set the edit schema validates against, so the two cannot drift again.
VALID_PHOTO_CATEGORIES = set(PHOTO_CATEGORIES)

# Reality-capture / drone-survey point-cloud file extensions. A file dropped
# into the generic documents upload with one of these extensions is auto-
# categorised as ``reality_capture`` (mirroring how a photo upload becomes a
# site picture) so it surfaces as a reality-capture asset instead of a nameless
# ``other`` blob.
#
# Scope note (deliberate boundary): only point-cloud container extensions are
# listed. Drone orthomosaic imagery uses ordinary raster extensions
# (``.tif`` / ``.tiff``) that are indistinguishable from a normal TIFF drawing
# without parsing GeoTIFF GeoKeys, so auto-treating every ``.tif`` as reality
# capture would hijack legitimate drawing uploads. GeoTIFF orthomosaics are
# therefore out of scope for auto-detection here - upload them through the
# dedicated Reality Capture ingest or set the category by hand.
REALITY_CAPTURE_EXTENSIONS = {
    ".las",  # ASPRS LAS point cloud
    ".laz",  # LASzip-compressed LAS
    ".e57",  # ASTM E57 point cloud / imagery
    ".copc",  # Cloud-Optimized Point Cloud (LAS-based)
    ".ply",  # Polygon / point cloud
    ".pcd",  # Point Cloud Data (PCL)
    ".pts",  # Leica point cloud (plain text)
    ".xyz",  # XYZ point cloud (plain text)
}
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/tiff",
}
BLOCKED_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".sh",
    ".ps1",
    ".com",
    ".scr",
    ".msi",
    ".dll",
    ".vbs",
    ".js",
    ".ws",
    ".wsf",
    ".pif",
    ".hta",
    ".cpl",
    ".msp",
    ".mst",
    ".reg",
}


def _sanitize_filename(name: str) -> str:
    """Remove path components and dangerous characters from filename."""
    name = os.path.basename(name)
    name = re.sub(r"[^\w.\-]", "_", name)
    if not name or name.startswith("."):
        name = "untitled"
    return name


def _blocked_extension_segment(name: str) -> str | None:
    """Return the first dangerous extension segment in ``name``, else None.

    A suffix-only check (``Path(name).suffix``) only inspects the final
    extension, so a double-extension payload slips through (A-DOC-10).
    This scans **every** dotted segment so a blocked executable/script
    extension anywhere in the name is caught (``x.exe.pdf`` → ``.exe``,
    ``run.bat.png`` → ``.bat``). ``.php`` is intentionally NOT blocked
    (no PHP runtime in this stack); the magic-byte gate + UUID-prefixed
    storage cover the residual content risk.

    It deliberately only flags segments that are in ``BLOCKED_EXTENSIONS``
    - ordinary multi-dot filenames (``drawing.v2.dwg``,
    ``report.2024.final.pdf``) are NOT rejected, so this is hardening,
    not over-restriction.
    """
    # ``a.php.png`` → segments ['php', 'png']; leading '' (hidden-file
    # dot) is skipped by [1:].
    for segment in name.split(".")[1:]:
        if f".{segment.lower()}" in BLOCKED_EXTENSIONS:
            return f".{segment.lower()}"
    return None


def _reality_capture_extension(name: str) -> str | None:
    """Return the reality-capture point-cloud extension of ``name``, else None.

    Matches only the final suffix against :data:`REALITY_CAPTURE_EXTENSIONS`, so
    ``site-scan.las`` is detected while an ordinary ``plan.pdf`` is not. Used to
    auto-categorise reality-capture / drone-survey point clouds uploaded through
    the generic documents path, mirroring the photo -> site-picture bridge.
    """
    suffix = Path(name).suffix.lower()
    if suffix in REALITY_CAPTURE_EXTENSIONS:
        return suffix
    return None


def _ensure_photo_within_pixel_cap(source_bytes: bytes) -> None:
    """Reject a photo whose pixel count would OOM the image decoder.

    ``Image.open`` is lazy: reading ``.size`` parses only the header and does
    NOT allocate the pixel buffer, so this rejects an over-resolution image
    BEFORE the expensive full decode in the AI-suggestion and thumbnail paths,
    where a ~150 MP photo would otherwise expand to hundreds of MB and OOM-kill
    the worker. ``Image.MAX_IMAGE_PIXELS`` is also pinned so that even a decode
    reached by another path trips Pillow's own bomb guard instead of exhausting
    memory (defence in depth).

    Args:
        source_bytes: The raw uploaded image bytes.

    Raises:
        HTTPException: 413 when the image exceeds ``MAX_PHOTO_PIXELS``.

    A missing Pillow or an unreadable header is deliberately NOT fatal: the
    magic-byte sniff already proved the bytes are a raster image and the
    thumbnail step is best-effort, so a header we cannot parse falls through to
    that existing graceful path rather than blocking a valid upload. Runs
    synchronously; call it via ``asyncio.to_thread`` so a slow header parse
    cannot block the event loop.
    """
    try:
        from io import BytesIO

        from PIL import Image
    except Exception:
        return

    # Defence in depth: cap what the decoder itself may allocate.
    Image.MAX_IMAGE_PIXELS = MAX_PHOTO_PIXELS

    try:
        with Image.open(BytesIO(source_bytes)) as img:
            width, height = img.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        # Declared dimensions blow past Pillow's own guard (> 2x the cap).
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Photo resolution exceeds the {MAX_PHOTO_PIXELS // (1024 * 1024)} MP limit. "
                f"Downscale the image before uploading."
            ),
        ) from exc
    except Exception:
        # A header we cannot parse - defer to the best-effort thumbnail path
        # rather than reject a file the magic-byte gate already accepted.
        return

    if width * height > MAX_PHOTO_PIXELS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Photo has too many pixels: {width}x{height} = {width * height} "
                f"(max {MAX_PHOTO_PIXELS} px / {MAX_PHOTO_PIXELS // (1024 * 1024)} MP). "
                f"Downscale the image before uploading."
            ),
        )


def _generate_photo_thumbnail(
    source_bytes: bytes,
    dest_path: Path,
) -> bool:
    """Write a JPEG thumbnail of ``source_bytes`` to ``dest_path``.

    Returns ``True`` on success, ``False`` if anything went wrong (missing
    Pillow, corrupt image, unsupported mode). Thumbnail generation is a
    best-effort optimisation - a failure must never block the upload. CPU-bound
    (decode + LANCZOS resample), so call it via ``asyncio.to_thread`` to keep it
    off the event loop.
    """
    try:
        from io import BytesIO

        from PIL import Image, ImageOps
    except Exception:
        logger.warning("Pillow not available - skipping photo thumbnail")
        return False

    # Cap decoded pixels here too, so this best-effort path degrades to a clean
    # False (no thumbnail) instead of OOMing if ever reached without the
    # upfront _ensure_photo_within_pixel_cap gate.
    Image.MAX_IMAGE_PIXELS = MAX_PHOTO_PIXELS

    try:
        with Image.open(BytesIO(source_bytes)) as img:
            # Respect EXIF orientation so the thumbnail matches what the user
            # will see in the full viewer.
            img = ImageOps.exif_transpose(img)
            # Pillow's thumbnail() is in-place and preserves aspect ratio.
            img.thumbnail(
                (PHOTO_THUMB_MAX_SIDE, PHOTO_THUMB_MAX_SIDE),
                Image.Resampling.LANCZOS,
            )
            # Normalise to RGB so we can always write JPEG regardless of the
            # original mode (RGBA, P, CMYK, etc.).
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(
                str(dest_path),
                format="JPEG",
                quality=PHOTO_THUMB_QUALITY,
                optimize=True,
                progressive=True,
            )
        return True
    except Exception:
        logger.exception("Failed to generate photo thumbnail for %s", dest_path)
        return False


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
        - File size validation (max ``MAX_FILE_SIZE`` = 100MB - defence
          in depth; the API gateway / nginx is expected to enforce the
          same cap, but the service rejects oversize uploads itself so
          a misconfigured gateway can't surface a memory-DoS vector)
        - Category validation against allowed list
        - UUID-prefixed storage path to avoid collisions
        - File written AFTER DB record creation for easy rollback
        - Stored ``mime_type`` is derived from the detected magic-byte
          signature, NOT the attacker-controlled request header (P0-1)
        """
        # Sanitize filename
        raw_name = file.filename or "untitled"
        safe_name = _sanitize_filename(raw_name)

        # Block dangerous file extensions - scan EVERY dotted segment so
        # a double-extension payload (shell.php.png) is rejected, not just
        # the final suffix (A-DOC-10).
        bad_ext = _blocked_extension_segment(safe_name)
        if bad_ext is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type '{bad_ext}' is not allowed for security reasons.",
            )

        # Validate category
        if category not in VALID_CATEGORIES:
            category = "other"

        # Reality-capture / drone bridge: a point-cloud file dropped into the
        # generic uploads path is auto-categorised as ``reality_capture`` so it
        # surfaces as a reality-capture asset instead of a nameless ``other``
        # blob - mirroring how a photo upload becomes a site picture. Only done
        # when the caller did NOT pick a specific category (``other`` is the
        # non-specific default), so an explicit choice always wins. The heavy
        # scan ingest is NEVER run here; this only labels the stored file and
        # announces it (see the detached event below) for the Reality Capture
        # module / a later ingest phase to pick up.
        reality_capture_ext: str | None = None
        if category == "other":
            reality_capture_ext = _reality_capture_extension(safe_name)
            if reality_capture_ext is not None:
                category = "reality_capture"

        # Enforce the size cap while streaming (defence in depth; a cap is also
        # expected at the API gateway). A bare ``await file.read()`` here pulls
        # the entire body into RAM before the length check, so a multi-GB upload
        # would OOM-kill the single worker first. Stream to a temp file in 1 MB
        # chunks (aborts past the cap), then read the now-bounded bytes back for
        # the magic-byte checks and the on-disk write below. 100 MB is enough
        # for typical AEC drawings and contracts; oversized assets belong on
        # direct-to-S3 paths.
        try:
            async with stream_upload_to_temp(file, max_bytes=MAX_FILE_SIZE) as staged:
                content = staged.path.read_bytes()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB). "
                    "Upload a smaller file or use a direct-to-storage path."
                ),
            ) from exc

        # Magic-byte validation - BLOCKED_EXTENSIONS only rejects known-bad
        # names; this catches an attacker who renames evil.exe → evil.pdf.
        # ``xml`` / ``ole`` types included because DDC converters and many
        # legitimate design files use those containers. Unknown binary
        # blobs (detected == None) are tolerated so plain-text uploads
        # (CSV, JSON, TXT) still work - the extension gate above still
        # filters executables by name.
        from app.core.file_signature import (
            ALLOWED_CAD_TYPES,
            ALLOWED_DOCUMENT_TYPES,
            BANNED_SIGNATURE_TOKENS,
            SIGNATURE_BYTES_REQUIRED,
        )
        from app.core.file_signature import (
            detect as _sig_detect,
        )
        from app.core.file_signature import (
            mime_for_signature as _mime_for_signature,
        )

        allowed_signatures = ALLOWED_DOCUMENT_TYPES | ALLOWED_CAD_TYPES
        detected_type = _sig_detect(content[:SIGNATURE_BYTES_REQUIRED])
        # Reject explicitly banned types (executables, scripts, …) even
        # if a future detector update surfaces them as named tokens.
        if detected_type is not None and detected_type in BANNED_SIGNATURE_TOKENS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Executable/script content is not allowed (detected: {detected_type})."),
            )
        if detected_type is not None and detected_type not in allowed_signatures:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Uploaded file content does not match an allowed format. "
                    f"Detected: {detected_type}. "
                    f"Allowed: {', '.join(sorted(allowed_signatures))}"
                ),
            )

        # Derive the stored MIME from the detected signature (P0-1).
        # ``file.content_type`` is fully attacker-controlled - an .exe
        # uploaded with header ``image/png`` previously round-tripped
        # into the DB and downstream consumers (vector indexer, viewers)
        # would happily trust it.
        stored_mime = _mime_for_signature(detected_type)

        # Build storage path with UUID prefix to avoid collisions
        file_uuid = uuid.uuid4().hex[:12]
        storage_name = f"{file_uuid}_{safe_name}"
        upload_dir = UPLOAD_BASE / str(project_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / storage_name

        # Tag reality-capture assets so they are easy to find in the Documents
        # hub (which supports a tag/category filter) and so downstream consumers
        # can recognise a point-cloud drop without re-sniffing the extension.
        doc_tags: list[str] = []
        if reality_capture_ext is not None:
            doc_tags = ["reality-capture", "point-cloud", reality_capture_ext.lstrip(".")]

        # Create DB record FIRST - if this fails we haven't written a file
        document = Document(
            project_id=project_id,
            name=safe_name,
            category=category,
            file_size=len(content),
            mime_type=stored_mime,
            file_path=str(file_path),
            uploaded_by=user_id,
            tags=doc_tags,
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

        # Publish document.uploaded event for notification/CDE workflows
        try:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "document.uploaded",
                {
                    "project_id": str(project_id),
                    "document_id": str(document.id),
                    "name": safe_name,
                    "category": category,
                    "file_size": len(content),
                    "mime_type": stored_mime,
                    "uploaded_by": user_id,
                },
                source_module="oe_documents",
            )
        except Exception as exc:
            logger.debug("Failed to publish document.uploaded event: %s", exc)

        # Publish the standardized documents.document.created event so
        # cross-module subscribers (vector indexer, activity log, …) get
        # a consistent name per OpenEstimate event conventions.
        try:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "documents.document.created",
                {
                    "project_id": str(project_id),
                    "document_id": str(document.id),
                    "name": safe_name,
                    "category": category,
                },
                source_module="oe_documents",
            )
        except Exception as exc:
            logger.debug("Failed to publish documents.document.created event: %s", exc)

        # Reality-capture bridge event - give the Reality Capture / point-cloud
        # module a clean subscription seam so a later ingest phase can promote
        # this already-stored file into a scan dataset. Fail-soft: a publish
        # failure must never block the upload, and no heavy processing runs in
        # the request path. Boundary: the pointcloud module's own list_scans is
        # backed by object storage (MinIO) with a stricter format subset
        # (e57/las/laz/copc) and a tenant-namespaced multipart ingest, so we do
        # NOT fabricate a scan row here; the document is discoverable today via
        # the Documents hub category filter, and this event is the honest hand-
        # off point for real ingest.
        if reality_capture_ext is not None:
            try:
                from app.core.events import event_bus

                event_bus.publish_detached(
                    "documents.reality_capture.detected",
                    {
                        "project_id": str(project_id),
                        "document_id": str(document.id),
                        "name": safe_name,
                        "file_path": str(file_path),
                        "file_size": len(content),
                        "extension": reality_capture_ext,
                    },
                    source_module="oe_documents",
                )
            except Exception as exc:
                logger.debug("Failed to publish documents.reality_capture.detected event: %s", exc)

        logger.info(
            "Document uploaded: %s (%d bytes) for project %s",
            safe_name,
            len(content),
            project_id,
        )

        # Audit log - the timeline UI in /files relies on this row to
        # explain "where did this document come from?" without joining
        # event-bus archives. Failures are swallowed inside the helper
        # so the audit log never blocks the upload itself.
        await record_activity(
            self.session,
            document.id,
            user_id or None,
            "uploaded",
            {
                "name": safe_name,
                "category": category,
                "file_size": len(content),
                "mime_type": stored_mime,
            },
        )

        # Epic C - register the chain row. A re-upload with the same
        # ``name`` rolls the chain forward (old row superseded, new row
        # current). Wrapped so a chain-write failure cannot block the
        # upload itself; the file is on disk and the Document row is in
        # the DB regardless.
        await _register_version_safely(
            self.session,
            project_id=project_id,
            file_kind="document",
            entity=document,
            file_id=str(document.id),
            file_size=len(content),
            uploaded_by=user_id,
        )

        return document

    # ── Revisions (Epic C) ─────────────────────────────────────────────────

    async def upload_document_revision(
        self,
        document_id: uuid.UUID,
        file: UploadFile,
        user_id: str,
        notes: str | None = None,
    ) -> Document:
        """Upload a NEW revision for an existing document.

        Reuses ``upload_document`` security gates (magic-byte, blocked
        extensions, size cap) by inlining the same checks here - but
        keys the chain off the EXISTING document's ``name`` so the
        re-upload lands in the same chain regardless of what the user
        names their incoming file.

        Args:
            document_id: The document whose chain we are extending.
            file: The freshly uploaded file (already opened by FastAPI).
            user_id: Caller's id, recorded as uploader.
            notes: Optional version-note carried into ``FileVersion.notes``.

        Returns:
            The original ``Document`` row (with a refreshed
            ``updated_at``). The new chain row is fetchable via
            ``GET /file-versions/?file_id={id}&kind=document``.
        """
        document = await self.get_document(document_id)
        safe_name = _sanitize_filename(file.filename or document.name)

        bad_ext = _blocked_extension_segment(safe_name)
        if bad_ext is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type '{bad_ext}' is not allowed for security reasons.",
            )

        try:
            async with stream_upload_to_temp(file, max_bytes=MAX_FILE_SIZE) as staged:
                content = staged.path.read_bytes()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB)."),
            ) from exc

        from app.core.file_signature import (
            ALLOWED_CAD_TYPES,
            ALLOWED_DOCUMENT_TYPES,
            BANNED_SIGNATURE_TOKENS,
            SIGNATURE_BYTES_REQUIRED,
        )
        from app.core.file_signature import detect as _sig_detect
        from app.core.file_signature import mime_for_signature as _mime_for_signature

        allowed = ALLOWED_DOCUMENT_TYPES | ALLOWED_CAD_TYPES
        detected = _sig_detect(content[:SIGNATURE_BYTES_REQUIRED])
        if detected is not None and detected in BANNED_SIGNATURE_TOKENS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Executable/script content is not allowed (detected: {detected})."),
            )
        if detected is not None and detected not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Uploaded content does not match an allowed format (detected: {detected})."),
            )

        stored_mime = _mime_for_signature(detected)

        file_uuid = uuid.uuid4().hex[:12]
        storage_name = f"{file_uuid}_{safe_name}"
        upload_dir = UPLOAD_BASE / str(document.project_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / storage_name

        try:
            file_path.write_bytes(content)
        except Exception:
            logger.exception("Failed to write revision to disk: %s", file_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save file to disk.",
            )

        # Bump the Document row's audit fields. We deliberately do NOT
        # mutate ``Document.name`` - the chain key follows the original
        # name so the version dropdown stays continuous.
        from app.modules.documents.repository import DocumentRepository

        repo = DocumentRepository(self.session)
        await repo.update_fields(
            document_id,
            file_path=str(file_path),
            file_size=len(content),
            mime_type=stored_mime,
        )
        await self.session.refresh(document)

        # Register the new chain row. ``canonical_name`` is derived from
        # the EXISTING document row so re-uploads land in the same chain.
        try:
            from app.modules.file_versions.helpers import canonical_name_for
            from app.modules.file_versions.schemas import FileVersionCreate
            from app.modules.file_versions.service import FileVersionService

            svc = FileVersionService(self.session)
            try:
                uploader_uuid = uuid.UUID(str(user_id)) if user_id else None
            except (TypeError, ValueError):
                uploader_uuid = None
            payload = FileVersionCreate(
                project_id=document.project_id,
                file_kind="document",
                file_id=str(document.id),
                canonical_name=canonical_name_for("document", document),
                file_size=len(content),
                notes=notes,
            )
            await svc.register_new_version(payload, uploaded_by_id=uploader_uuid)
        except Exception:
            logger.warning(
                "Failed to register FileVersion chain row for revision (doc=%s)",
                document.id,
                exc_info=True,
            )

        await record_activity(
            self.session,
            document.id,
            user_id or None,
            "revision_uploaded",
            {
                "name": safe_name,
                "file_size": len(content),
                "mime_type": stored_mime,
                "notes": notes or "",
            },
        )

        return document

    # ── Read ───────────────────────────────────────────────────────────────

    async def get_document(self, document_id: uuid.UUID) -> Document:
        """Get document by ID. Raises 404 if not found."""
        document = await self.repo.get_by_id(document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.document_not_found", locale=get_locale()),
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
        sort_by: str | None = None,
        sort_order: str = "desc",
        visible_categories: frozenset[str | None] | None = None,
    ) -> tuple[list[Document], int]:
        """List documents for a project.

        ``visible_categories`` narrows the total to the folders the caller may
        read; it does not touch the page, which the route filters itself. See
        :meth:`DocumentRepository.list_for_project`.
        """
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            category=category,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            visible_categories=visible_categories,
        )

    # ── Update ─────────────────────────────────────────────────────────────

    # Valid CDE state transitions (ISO 19650 workflow).
    #
    # ISO 19650 is a FORWARD-ONLY lifecycle: WIP -> SHARED -> PUBLISHED ->
    # ARCHIVED. Backtracking (e.g. SHARED -> WIP) is NOT permitted - a
    # superseded document is archived and a fresh revision starts a new
    # chain, it never demotes its suitability state. The previous map
    # allowed every state to drop back to ``wip``, which let a published
    # (and therefore construction-issued) document silently revert to a
    # work-in-progress state, breaking the audit trail. ``archived`` is
    # terminal. These rules mirror ``CDEStateMachine`` in
    # ``app.core.cde_states`` exactly so the Documents PATCH path and the
    # CDE-container service stay unified.
    VALID_CDE_TRANSITIONS: dict[str, list[str]] = {
        "wip": ["shared"],
        "shared": ["published"],
        "published": ["archived"],
        "archived": [],
    }

    async def update_document(
        self,
        document_id: uuid.UUID,
        data: DocumentUpdate,
        user_id: str | None = None,
        user_role: str | None = None,
    ) -> Document:
        """Update document metadata fields.

        Validates CDE state transitions if cde_state is being changed and,
        when ``user_role`` is supplied, enforces the ISO 19650 role gates
        (Gate A: WIP→SHARED needs a task team manager; Gate B:
        SHARED→PUBLISHED needs a lead appointed party + an approver
        signature; Gate C: PUBLISHED→ARCHIVED needs an admin). It also
        validates the suitability code against the resulting CDE state so
        an invalid combination (e.g. ``A1`` while ``shared``) is rejected.

        ``user_id`` is passed through to the activity log so the timeline
        attributes the rename / CDE-state-change to the right operator.
        ``user_role`` is the canonical app role from the JWT (admin /
        manager / editor / viewer). When it is ``None`` the role gates are
        skipped and only the structural forward-only transition rules
        apply - this keeps internal / unauthenticated service callers
        working while every HTTP caller (which always carries a role) is
        gated.
        """
        document = await self.get_document(document_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(document, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )

        # The approver signature is a Gate-B precondition, never a column -
        # pop it out of the persisted field set so it isn't passed to
        # ``update_fields`` (the Document model has no such attribute). It is
        # captured into the document metadata's compliance block below.
        approver_signature = fields.pop("approver_signature", None)

        if not fields:
            return document

        # Snapshot the values we may want to audit BEFORE the update so
        # the meta-blob captures the actual transition (old → new).
        old_name = document.name
        old_cde = document.cde_state

        # Validate CDE state transition.
        #
        # A document that has never had a state set (``cde_state IS NULL``
        # - true for seed rows and every freshly-uploaded document) is
        # treated as being in the ISO 19650 initial state ``wip``. This
        # closes A-DOC-09: previously the whole guard was skipped while
        # ``current_state is None``, so ``wip -> published`` (or any
        # arbitrary jump) was accepted on a stateless document. Re-asserting
        # the same state (``wip -> wip``) is allowed so a client can
        # explicitly initialise the field without a spurious 400.
        current_state = document.cde_state or "wip"
        new_state = current_state
        if "cde_state" in fields and fields["cde_state"] is not None:
            new_state = fields["cde_state"]
            if new_state != current_state:
                allowed = self.VALID_CDE_TRANSITIONS.get(current_state, [])
                if new_state not in allowed:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Invalid CDE state transition: '{current_state}' -> '{new_state}'. Allowed: {allowed}"
                        ),
                    )

                # Role-gate enforcement - only when the caller's role is
                # known. ``validate_transition`` re-checks the structural
                # transition (belt-and-braces) AND the role gate keyed by
                # ISO 19650 role names, so an editor cannot publish and a
                # manager cannot archive. The app role is translated to the
                # ISO role first; an unknown role falls through to ``viewer``
                # (least authority) so it can never accidentally pass a gate.
                if user_role is not None:
                    iso_role = _iso_role_for(user_role)
                    ok, reason = _state_machine.validate_transition(
                        current_state,
                        new_state,
                        user_role=iso_role,
                    )
                    if not ok:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=reason,
                        )

                    # Gate B (SHARED → PUBLISHED) additionally requires a
                    # non-empty approver signature in the request. Reuse the
                    # shared gate registry so the precondition stays unified
                    # with the CDE-container service (Epic H).
                    gate_meta = _state_machine.get_gate_requirements(current_state, new_state)
                    gate_code = gate_meta.get("gate")
                    if gate_code:
                        from app.core.audit_gates import gate_registry as _gate_registry

                        _gate_registry.enforce(gate_code, {"approver_signature": approver_signature})

                    # Capture the Gate-B approval block in the document
                    # metadata for the compliance trail (scoped key so it
                    # never collides with caller-supplied metadata).
                    is_gate_b = new_state == CDEState.PUBLISHED.value and current_state == CDEState.SHARED.value
                    if is_gate_b:
                        md = dict(fields.get("metadata_", document.metadata_) or {})
                        md["cde_last_approval"] = {
                            "by": user_id,
                            "at": datetime.now(UTC).isoformat(),
                            "signature": approver_signature,
                            "from_state": current_state,
                            "to_state": new_state,
                        }
                        fields["metadata_"] = md

        # Validate the suitability code against the resulting CDE state.
        #
        # This covers BOTH the combined PATCH (cde_state + suitability_code
        # in one body - also pre-checked by the schema validator) AND the
        # suitability-only PATCH against an already-stateful document (which
        # the schema validator cannot see). A blank / None code is always
        # accepted because suitability is optional. ISO 19650 codes are
        # state-scoped (S0 only in wip, S1-S7 in shared, A1-A5 in published,
        # AR in archived) so an out-of-state code is a 400.
        if "suitability_code" in fields and fields["suitability_code"]:
            from app.modules.cde.suitability import validate_suitability_for_state

            ok, reason = validate_suitability_for_state(fields["suitability_code"], new_state)
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=reason,
                )

        # P1 - revision-conflict guard. Two concurrent updates that both
        # set ``is_current_revision=True`` under the same parent
        # ``parent_document_id`` would silently leave the chain with two
        # "current" rows; downstream consumers (viewer, vector index)
        # then have to pick one and the choice diverges across tenants.
        # Reject the second update with 409 so the client retries against
        # the row that won.
        if fields.get("is_current_revision") is True:
            parent_id = fields.get("parent_document_id", document.parent_document_id)
            if parent_id is not None:
                stmt = select(Document).where(
                    Document.parent_document_id == parent_id,
                    Document.is_current_revision.is_(True),
                    Document.id != document_id,
                )
                existing = (await self.session.execute(stmt)).scalars().first()
                if existing is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Revision conflict: document {existing.id} is "
                            f"already the current revision under parent "
                            f"{parent_id}. Demote it first."
                        ),
                    )

        await self.repo.update_fields(document_id, **fields)
        await self.session.refresh(document)

        logger.info("Document updated: %s (fields=%s)", document_id, list(fields.keys()))

        # Activity log - split into distinct actions so the timeline UI
        # can colour them differently. Rename and CDE state change are
        # by far the most useful audit events.
        if "name" in fields and fields["name"] is not None and fields["name"] != old_name:
            await record_activity(
                self.session,
                document_id,
                user_id,
                "renamed",
                {"old": old_name, "new": fields["name"]},
            )
        if "cde_state" in fields and fields["cde_state"] != old_cde:
            await record_activity(
                self.session,
                document_id,
                user_id,
                "cde_state_changed",
                {"old": old_cde, "new": fields["cde_state"]},
            )

        # Publish documents.document.updated so the vector indexer and
        # other subscribers can re-embed the row with the fresh metadata.
        try:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "documents.document.updated",
                {
                    "project_id": str(document.project_id),
                    "document_id": str(document.id),
                    "fields": list(fields.keys()),
                },
                source_module="oe_documents",
            )
        except Exception as exc:
            logger.debug("Failed to publish documents.document.updated event: %s", exc)

        return document

    # ── Delete ─────────────────────────────────────────────────────────────

    async def get_references(self, document_id: uuid.UUID) -> DocumentReferencesResponse:
        """Summarise what still points at a document, for the delete prompt.

        Read-only, and deliberately not consulted by :meth:`delete_document`:
        the links these counts describe are severable by design, so what the
        caller does with the answer is a decision for the person confirming.
        See :mod:`app.modules.documents.references` for how the set is
        curated and why it is not derived from column names.
        """
        from app.modules.documents.references import (
            count_references,
            resolved_references,
        )

        counts = await count_references(self.session, document_id)
        by_key = {ref.key: ref for ref in resolved_references()}

        items: list[DocumentReferenceItem] = []
        totals = {"strands": 0, "unlinks": 0, "retains": 0}
        for key, hits in counts.items():
            ref = by_key.get(key)
            if ref is None:  # pragma: no cover - resolved set built above
                continue
            totals[ref.impact] += hits
            items.append(
                DocumentReferenceItem(
                    key=key,
                    module=ref.module,
                    model=ref.model,
                    impact=ref.impact,
                    count=hits,
                )
            )

        # Heaviest consequence first, then biggest, so the prompt leads with
        # what cannot be repaired.
        order = {"strands": 0, "unlinks": 1, "retains": 2}
        items.sort(key=lambda item: (order[item.impact], -item.count, item.key))

        return DocumentReferencesResponse(
            document_id=document_id,
            total=sum(totals.values()),
            strands=totals["strands"],
            unlinks=totals["unlinks"],
            retains=totals["retains"],
            references=items,
        )

    async def delete_document(
        self,
        document_id: uuid.UUID,
        user_id: str | None = None,
    ) -> None:
        """Delete a document and its file.

        DB record is deleted first so a failure there prevents orphan file removal.
        File removal failure is logged but not fatal - leaves an orphan file rather
        than an orphan DB record pointing to a missing file.
        """
        document = await self.get_document(document_id)
        file_path_str = document.file_path
        project_id = document.project_id
        doc_name = document.name

        # Audit log BEFORE delete - the row is wiped by the FK cascade
        # together with the document itself, but the event-bus publish
        # downstream carries the same payload for any external audit
        # collector that wants to retain "deleted" hits.
        await record_activity(
            self.session,
            document_id,
            user_id,
            "deleted",
            {"name": doc_name},
        )

        # Delete DB record FIRST - this is the authoritative state
        await self.repo.delete(document_id)
        logger.info("Document deleted: %s", document_id)

        # Publish documents.document.deleted so the vector indexer and
        # other subscribers can evict the row from their stores.
        try:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "documents.document.deleted",
                {
                    "project_id": str(project_id) if project_id else "",
                    "document_id": str(document_id),
                },
                source_module="oe_documents",
            )
        except Exception as exc:
            logger.debug("Failed to publish documents.document.deleted event: %s", exc)

        # Takeoff can reference this blob instead of holding a second copy of
        # it, so hand it its own copy BEFORE the unlink below. Called directly
        # rather than driven off the deleted event above: that event is
        # published detached, so a subscriber would race this unlink and lose
        # nondeterministically - passing on a developer's box and failing on a
        # loaded one. A False return means the copy did not happen, and we then
        # keep the original on disk. That is the same trade the docstring above
        # already makes: an orphaned file is recoverable, a document row
        # pointing at a deleted blob is not.
        may_unlink = True
        if file_path_str:
            try:
                from app.modules.takeoff.service import preserve_blobs_for_deleted_source

                may_unlink = await preserve_blobs_for_deleted_source(
                    self.session,
                    source_document_id=str(document_id),
                    source_file_path=file_path_str,
                )
            except Exception:
                # Never let this stop the deletion itself - the row is already
                # gone. Keep the blob so nothing that referenced it breaks.
                logger.exception(
                    "Failed to preserve takeoff copies of %s; keeping the file",
                    file_path_str,
                )
                may_unlink = False

        # Then remove file from disk (best-effort)
        if not may_unlink:
            logger.warning(
                "File kept because a takeoff document still references it: %s",
                file_path_str,
            )
            return
        # A blob can belong to more than one document. The demo seeder stores
        # document bytes under the digest of their content, so the one native
        # model every demo project shows is a single file that every project's
        # row points at, and deleting one of those documents must not take the
        # file away from the rest. The id is excluded explicitly instead of
        # relying on the delete above having reached the database, so the
        # count means the same thing whether or not it has been flushed.
        if file_path_str and await self._file_has_other_documents(document_id, file_path_str):
            return

        try:
            file_path = Path(file_path_str)
            if file_path.exists():
                file_path.unlink()
                logger.info("File removed: %s", file_path)
        except Exception:
            logger.warning("Failed to remove file: %s", file_path_str)

    async def _file_has_other_documents(self, document_id: uuid.UUID, file_path: str) -> bool:
        """True when documents other than ``document_id`` point at ``file_path``.

        A failure to answer counts as "yes" on purpose. That keeps the trade
        the delete path already makes everywhere else: an orphaned file is
        recoverable, and a document row pointing at a blob somebody else's
        deletion removed is not.
        """
        try:
            others = (
                await self.session.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(Document.file_path == file_path, Document.id != document_id)
                )
            ).scalar_one()
        except Exception:
            logger.exception(
                "Failed to count the documents sharing %s; keeping the file",
                file_path,
            )
            return True
        if others:
            logger.info(
                "File kept because %d other document(s) reference it: %s",
                others,
                file_path,
            )
            return True
        return False

    # ── Summary ────────────────────────────────────────────────────────────

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get aggregated stats for a project's documents.

        Uses SQL COUNT/SUM aggregation instead of loading all records into memory.
        """
        total_count, total_size, cat_rows = await self.repo.summary_for_project(project_id)
        recent_docs = await self.repo.recent_uploads(project_id, limit=5)

        # Normalise to the documented whitelist (A-DOC-11). Upload coerces
        # unknown categories to ``other``, but seed rows and other raw
        # INSERT paths (e.g. the photo cross-link) bypass that, so the
        # stored column can hold ``certificate``/``engineering``/``permit``
        # etc. Fold every non-whitelisted category into ``other`` -
        # aggregating counts so the totals still reconcile - instead of
        # surfacing categories the rest of the API contract rejects.
        by_category: dict[str, int] = {}
        for cat, count in cat_rows:
            key = cat if cat in VALID_CATEGORIES else "other"
            by_category[key] = by_category.get(key, 0) + count

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
        - MIME type validation (images only) - header used only as a
          quick pre-check; the authoritative gate is the magic-byte
          sniff below, and the stored ``mime_type`` is derived from it
        - Filename sanitization
        - File size validation (max ``MAX_PHOTO_SIZE`` = 50MB - defence
          in depth; the API gateway is expected to enforce the same
          cap, but we reject oversize uploads here so a misconfigured
          gateway can't surface a memory-DoS vector)
        - Category validation
        - UUID-prefixed storage path
        """
        # Validate MIME type (header - fully attacker-controlled, so this
        # is only a fast pre-check; the magic-byte sniff below is the
        # authoritative gate and the stored value below comes from it).
        content_type = file.content_type or ""
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type: {content_type}. Only image files are allowed.",
            )

        # Sanitize filename
        raw_name = file.filename or "untitled.jpg"
        safe_name = _sanitize_filename(raw_name)

        # Block dangerous extensions on the photo path too - a renamed
        # ``evil.exe`` with a fake ``image/jpeg`` content_type still gets
        # caught here even before the magic-byte check. Scans every
        # dotted segment so ``shell.php.png`` is rejected (A-DOC-10).
        bad_ext = _blocked_extension_segment(safe_name)
        if bad_ext is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type '{bad_ext}' is not allowed for security reasons.",
            )

        # Validate category
        if category not in VALID_PHOTO_CATEGORIES:
            category = "site"

        # Enforce the size cap while streaming (defence in depth; a cap is also
        # expected at the API gateway). A bare ``await file.read()`` here pulls
        # the entire body into RAM before any check, so a multi-GB upload would
        # OOM-kill the single worker before the size guard could fire. Stream to
        # a temp file in 1 MB chunks (aborts past the cap), then read the
        # now-bounded bytes back for the magic-byte / pixel / EXIF checks below.
        try:
            async with stream_upload_to_temp(file, max_bytes=MAX_PHOTO_SIZE) as staged:
                content = staged.path.read_bytes()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Photo too large (max {MAX_PHOTO_SIZE // (1024 * 1024)} MB). "
                    "Resize the image or upload it at a lower resolution."
                ),
            ) from exc

        # Magic-byte cross-check - content_type is fully attacker-controlled
        # (it's a request header), so we re-derive the real format from the
        # bytes. Reject anything that isn't a recognised raster image.
        from app.core.file_signature import (
            ALLOWED_PHOTO_TYPES,
            BANNED_SIGNATURE_TOKENS,
            SIGNATURE_BYTES_REQUIRED,
        )
        from app.core.file_signature import (
            detect as _sig_detect,
        )
        from app.core.file_signature import (
            mime_for_signature as _mime_for_signature,
        )

        detected_photo_type = _sig_detect(content[:SIGNATURE_BYTES_REQUIRED])
        if detected_photo_type is not None and detected_photo_type in BANNED_SIGNATURE_TOKENS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Executable/script content is not allowed (detected: {detected_photo_type})."),
            )
        if detected_photo_type is None or detected_photo_type not in ALLOWED_PHOTO_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="uploaded file content does not match an image format",
            )

        # Use the magic-byte-derived MIME for the cross-linked Document
        # row below (P0-1). The header value is left in ``content_type``
        # for backwards-compat with the photo response field but the
        # stored canonical MIME is server-derived.
        stored_mime = _mime_for_signature(detected_photo_type)

        # Reject a decompression-bomb / over-resolution image BEFORE any full
        # decode below (EXIF read, AI suggestion, thumbnail). A byte-size cap
        # alone does not catch this: a few-MB file can still declare ~150 MP and
        # OOM-kill the worker on decode. Runs in a worker thread so a slow header
        # parse never blocks the event loop. Raises 413 for an over-cap image.
        await asyncio.to_thread(_ensure_photo_within_pixel_cap, content)

        # ── AI photo intelligence (Lane 7) ──────────────────────────────
        # 1) Auto-extract EXIF GPS so geotagged photos place themselves on
        #    the map. The CALLER's explicit lat/lon stays authoritative - we
        #    only fill in coordinates that were left blank.
        ai_meta: dict[str, Any] = {}
        if gps_lat is None or gps_lon is None:
            from app.core.match_service.extractors.photo import extract_exif_gps

            coords = extract_exif_gps(content)
            if coords is not None:
                exif_lat, exif_lon = coords
                if gps_lat is None:
                    gps_lat = exif_lat
                if gps_lon is None:
                    gps_lon = exif_lon
                ai_meta["gps_source"] = "exif"

        # 1b) Auto-extract the EXIF capture timestamp so photos sort and group
        #     chronologically by when the shutter fired, not by upload time.
        #     The CALLER's explicit ``taken_at`` stays authoritative - we only
        #     fill it when left blank.
        if taken_at is None:
            from app.core.match_service.extractors.photo import extract_exif_datetime

            exif_dt = extract_exif_datetime(content)
            if exif_dt is not None:
                taken_at = exif_dt
                ai_meta["taken_at_source"] = "exif"

        # 2) Compute a defect-category SUGGESTION. This is NEVER auto-applied
        #    - it is stored in metadata for the user to confirm in the UI. The
        #    persisted ``category`` remains exactly what the caller chose.
        suggestion = await self._suggest_category_safe(
            user_id=user_id,
            image_bytes=content,
            media_type=stored_mime or content_type or "image/jpeg",
            filename=safe_name,
            caption=caption or "",
            tags=tags or [],
        )
        if suggestion is not None:
            ai_meta["category_suggestion"] = suggestion

        # Build storage path
        file_uuid = uuid.uuid4().hex[:12]
        storage_name = f"{file_uuid}_{safe_name}"
        upload_dir = PHOTO_BASE / str(project_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / storage_name
        # Thumbnail sits in a sibling directory with a stable .jpg extension
        # so the serve endpoint never has to guess the format.
        thumb_dir = PHOTO_THUMB_BASE / str(project_id)
        thumb_name = f"{file_uuid}_thumb.jpg"
        thumb_path = thumb_dir / thumb_name

        # Create DB record FIRST. ``ai_meta`` carries the EXIF-GPS source flag
        # and the (never-auto-applied) category suggestion in the existing
        # JSON ``metadata`` column - no schema change needed (LIGHTWEIGHT).
        photo = ProjectPhoto(
            project_id=project_id,
            filename=safe_name,
            file_path=str(file_path),
            thumbnail_path=None,
            caption=caption,
            gps_lat=gps_lat,
            gps_lon=gps_lon,
            tags=tags or [],
            taken_at=taken_at,
            category=category,
            metadata_=ai_meta or {},
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

        # Generate thumbnail from the in-memory bytes - failure is non-fatal;
        # the serve endpoint falls back to the original on miss. Offloaded to a
        # worker thread: the decode + LANCZOS resample is CPU-bound and must not
        # block the event loop for other requests.
        thumb_generated = await asyncio.to_thread(_generate_photo_thumbnail, content, thumb_path)
        if thumb_generated:
            await self.repo.update_fields(photo.id, thumbnail_path=str(thumb_path))
            await self.session.refresh(photo)

        logger.info(
            "Photo uploaded: %s (%d bytes, thumb=%s) for project %s",
            safe_name,
            len(content),
            "yes" if thumb_generated else "no",
            project_id,
        )

        # Epic C - register the chain row. ``file_id`` is the photo row
        # id; ``canonical_name`` derives from ``filename``.
        await _register_version_safely(
            self.session,
            project_id=project_id,
            file_kind="photo",
            entity=photo,
            file_id=str(photo.id),
            file_size=len(content),
            uploaded_by=user_id,
        )

        # Also create a Document record so photos appear in Documents hub.
        #
        # Through the ORM, the same way the BIM cross-link does it, and NOT
        # through a raw INSERT. The raw version bound an isoformat STRING to
        # created_at/updated_at, which are ``DateTime(timezone=True)``. Under
        # ``text()`` the parameter has no type for SQLAlchemy to coerce, so the
        # string reached asyncpg, which will not accept text for a timestamptz
        # argument. Every photo upload on PostgreSQL therefore created no
        # Document row at all, and the bare ``except Exception`` below turned
        # that into a silent 201. The ORM fills both timestamps from the
        # ``Base`` Python-side default, so there is no hand-written timestamp
        # to get wrong, and the column list cannot drift as the table grows.
        #
        # The SAVEPOINT is what makes "non-fatal" true rather than aspirational:
        # a failed flush poisons the whole session, so catching the error
        # without one would leave the photo unsaveable anyway and fail the
        # request a few lines later, somewhere that reads like an unrelated bug.
        try:
            async with self.session.begin_nested():
                doc = Document(
                    project_id=project_id,
                    name=safe_name,
                    description=caption or "",
                    category="photo",
                    file_size=len(content),
                    mime_type=stored_mime,
                    # Byte-identical to the photo's own path: this string is the
                    # only link between the two rows, and ``delete_photo`` finds
                    # the row to remove by matching on it.
                    file_path=str(file_path),
                    version=1,
                    uploaded_by=user_id or "",
                    tags=["photo", category or "site"],
                    metadata_={},
                )
                self.session.add(doc)
                await self.session.flush()
            logger.info("Cross-linked photo %s → document %s (tags: photo, %s)", photo.id, doc.id, category)
        except SQLAlchemyError:
            # Named, so the row can be found and the failure is actionable. Not
            # a bare ``except``: a NameError or a TypeError in this block is a
            # defect in it, and swallowing those is how the bug above survived.
            logger.exception(
                "Failed to cross-link photo %s (project %s) into the documents hub",
                photo.id,
                project_id,
            )

        return photo

    async def _suggest_category_safe(
        self,
        *,
        user_id: str,
        image_bytes: bytes,
        media_type: str,
        filename: str,
        caption: str,
        tags: list[str],
    ) -> dict[str, Any] | None:
        """Best-effort photo-category suggestion (Lane 7).

        Delegates to the AI module's :meth:`AIService.suggest_photo_category`
        which uses the configured AI provider when a key exists, otherwise a
        deterministic heuristic. Wrapped so any AI/import failure degrades to
        "no suggestion" rather than failing the upload. The suggestion is
        advisory only - the caller's chosen category stays authoritative.
        """
        try:
            from app.modules.ai.service import AIService

            uid: str | None = str(user_id) if user_id else None
            if not uid:
                # No user → fall back to the deterministic heuristic directly
                # (the AI path needs a user to resolve provider keys).
                from app.modules.ai.service import heuristic_photo_suggestion

                return heuristic_photo_suggestion(filename=filename, caption=caption, tags=tags)

            ai_service = AIService(self.session)
            return await ai_service.suggest_photo_category(
                uid,
                image_bytes=image_bytes,
                media_type=media_type,
                filename=filename,
                caption=caption,
                tags=tags,
            )
        except Exception:
            logger.debug("Photo-category suggestion skipped", exc_info=True)
            return None

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

    async def get_gallery(self, project_id: uuid.UUID, *, limit: int = 500) -> tuple[list[ProjectPhoto], int]:
        """Read one page of a project's photos, newest first.

        Backs both the gallery grid and the timeline, which are the same read
        with different presentation. Returns ``(photos, total)`` where
        ``total`` is every photo the project holds, so a caller that got
        ``limit`` rows can tell whether that was all of them.

        The date grouping the timeline used to get from here now happens in
        the client: it is a pure function of the rows, and keeping it on this
        side forced the route to answer with a list of days that could not
        report how many photos it had left out.

        Args:
            project_id: Project whose photos to read.
            limit: Largest number of photos to return.

        Returns:
            The page of photos and the project's full photo count.
        """
        return await self.repo.list_for_project(project_id, offset=0, limit=limit)

    async def recent_across_projects(
        self,
        user_id: str | None,
        *,
        limit: int = 12,
        project_id: uuid.UUID | None = None,
    ) -> list[tuple[ProjectPhoto, str]]:
        """Return the most recent photos across every project the caller can see.

        Access control mirrors the dashboard / project-list endpoints
        (owner-OR-member, admins see every project) so the widget never
        leaks photos from a project the user cannot open. The accessible
        project-id set is resolved here and handed to the repository join,
        so the SQL can never return a row outside that set.

        ``project_id`` narrows the answer to one project. It is applied as an
        intersection with the accessible set and never as a replacement for
        it, so asking for a project the caller cannot open returns nothing
        rather than that project's photos. The caller is the dashboard, whose
        card is project facing: clicking a photo opens that project's gallery,
        so an unscoped answer put another project's site documentation under
        the name of the one the reader had selected.
        """
        if not user_id:
            return []

        from sqlalchemy import select as _select

        from app.modules.projects.models import Project
        from app.modules.teams.access import member_project_ids_subquery
        from app.modules.users.repository import UserRepository

        try:
            user_uuid = uuid.UUID(str(user_id))
        except (TypeError, ValueError):
            return []

        # Owner-OR-member set, mirroring ``list_projects`` / ``dashboard_cards``
        # / ``file_types_by_project``. Admins bypass the ownership check and
        # see photos for every project.
        user = await UserRepository(self.session).get_by_id(user_uuid)
        is_admin = user is not None and getattr(user, "role", "") == "admin"
        if is_admin:
            proj_stmt = _select(Project.id)
        else:
            proj_stmt = _select(Project.id).where(
                (Project.owner_id == user_uuid) | (Project.id.in_(member_project_ids_subquery(user_uuid)))
            )
        accessible_ids = list((await self.session.execute(proj_stmt)).scalars().all())
        if project_id is not None:
            # Intersection, not replacement. An id the caller cannot reach
            # falls out here and the empty list short-circuits below, which is
            # the same answer an empty project gives. Narrowing must never be
            # able to widen.
            # Compared as text: the GUID column is VARCHAR(36) while the
            # migrations declare a native uuid, so which Python type comes back
            # is not something this line should have an opinion about.
            wanted = str(project_id)
            accessible_ids = [pid for pid in accessible_ids if str(pid) == wanted]
        if not accessible_ids:
            return []

        # Fetch a wider window than requested so we can collapse visually
        # identical photos. Demo seeding shares the same build-stage shots
        # across several projects, so a naive "newest first" feed shows the
        # same image and caption a dozen times. Dedupe by caption (keeping the
        # newest occurrence) so the dashboard strip reads as a diverse set of
        # site photos. Photos without a caption fall back to their own id, so
        # genuinely distinct caption-less uploads are never collapsed together.
        fetch_limit = max(limit * 8, 48)
        rows = await self.repo.recent_across_projects(accessible_ids, limit=fetch_limit)

        seen: set[str] = set()
        deduped: list[tuple[ProjectPhoto, str]] = []
        for photo, project_name in rows:
            key = (photo.caption or "").strip().lower() or f"__id::{photo.id}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append((photo, project_name))
            if len(deduped) >= limit:
                break
        return deduped

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
        """Delete a photo, its file, and the cross-linked Documents-hub row.

        ``upload_photo`` mirrors every photo into ``oe_documents_document``
        (category ``photo``) so it shows up in the file manager. Deleting
        only the ``ProjectPhoto`` row used to leave that Document orphaned
        (A-DOC-06): the summary still counted it and downloading it 403'd
        because its ``file_path`` lives under ``PHOTO_BASE`` while the
        download route only allows ``UPLOAD_BASE``. We now remove the
        cross-linked Document(s) in the same transaction so the hub stays
        consistent.
        """
        photo = await self.get_photo(photo_id)
        file_path_str = photo.file_path
        thumb_path_str = getattr(photo, "thumbnail_path", None)

        # Remove the cross-linked Documents-hub row(s) created by
        # ``upload_photo``. The link is the shared ``file_path`` (the raw
        # INSERT stores the photo's on-disk path verbatim) scoped to this
        # project's photo-category documents - robust even though the
        # cross-link is not a real FK.
        if file_path_str:
            cross_linked = (
                (
                    await self.session.execute(
                        select(Document).where(
                            Document.project_id == photo.project_id,
                            Document.category == "photo",
                            Document.file_path == file_path_str,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for doc in cross_linked:
                await self.session.delete(doc)
            if cross_linked:
                await self.session.flush()
                logger.info(
                    "Removed %d cross-linked Document row(s) for photo %s",
                    len(cross_linked),
                    photo_id,
                )

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

        # Remove thumbnail too - orphan .jpg files in the thumbs directory
        # accumulate quickly and they share the same storage budget as the
        # originals.
        if thumb_path_str:
            try:
                thumb_path = Path(thumb_path_str)
                if thumb_path.exists():
                    thumb_path.unlink()
            except Exception:
                logger.warning("Failed to remove photo thumbnail: %s", thumb_path_str)


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
SHEET_THUMB_BASE = _upload_root() / "sheets"


def detect_discipline_from_sheet_number(sheet_number: str | None) -> str | None:
    """Auto-detect discipline from sheet number prefix.

    Common AEC convention: first letter indicates discipline.
    E.g., "A-201" -> Architectural, "S-100" -> Structural.
    """
    if not sheet_number:
        return None
    prefix = sheet_number.strip()[0].upper()
    return DISCIPLINE_PREFIX_MAP.get(prefix)


# A title block lays its fields out in columns, and the text extractor joins
# the cells that share a visual row into one line separated by runs of spaces.
# So "SCALE: 1:50    DRAWN: AB    DATE: 2026-01-14" arrives as a single line and
# a pattern that captures to the end of it captures three fields, not one.
#
# Two independent signals mark where the next field begins. A run of two or more
# spaces is the column gap. A following label is the field name itself, and the
# label carries no internal space so that "AS NOTED" is not mistaken for one.
_FIELD_LABEL_BREAK = re.compile(r"[ \t]+(?=[A-Za-z][A-Za-z.]{0,14}[ \t]*[:=])")
_COLUMN_GAP_BREAK = re.compile(r"[ \t]{2,}")


def _trim_title_block_value(value: str, *, cut_on_column_gap: bool) -> str:
    """Cut a captured title block value where the next field starts.

    Args:
        value: The raw capture, already bounded to a single line.
        cut_on_column_gap: Whether a run of two or more spaces also ends the
            value. True for narrow-vocabulary fields like the scale, where such
            a run can only be a column gap. False for free text like the sheet
            title, where wide letter spacing inside one cell can produce the
            same run and cutting on it would truncate a real title.

    Returns:
        The value up to the first break, stripped.
    """
    cuts = [m.start() for m in (_FIELD_LABEL_BREAK.search(value),) if m is not None]
    if cut_on_column_gap:
        gap = _COLUMN_GAP_BREAK.search(value)
        if gap is not None:
            cuts.append(gap.start())
    return (value[: min(cuts)] if cuts else value).strip()


def detect_sheet_info(page_text: str) -> dict[str, str | None]:
    """Extract sheet number, title, scale, and revision from page text.

    Uses simple regex patterns on extracted text to find common title block fields.
    Does NOT rely on external OCR services - works on already-extracted text.

    Scale reads both the ratio forms ("1:50", '1/4" = 1\'-0"') and the written
    ones ("NTS", "N.T.S.", "VARIES", "AS NOTED"). Revision date is not read at
    all, which is why a split row's ``revision_date`` is always null.

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
            # Free text, so only a following label ends it. A run of spaces
            # inside a title can be letter spacing rather than a column gap.
            title = _trim_title_block_value(match.group(1), cut_on_column_gap=False)
            if len(title) > 2:
                result["sheet_title"] = title[:500]
            break

    # Scale patterns: "1:100", "1/4\" = 1'-0\"", "SCALE: 1:50"
    #
    # The labelled pattern is bounded to the label's own line. It used to allow
    # \s inside the character class, which matches a newline, so the capture ran
    # off the end of the line and the trailing \S* then took the first token of
    # the next one. A title block reading "SCALE: 1:50" above "REV C" was stored
    # as "1:50\nREV", and that string is what the sheet detail drawer prints.
    # Horizontal whitespace only, on both sides of the separator, because a
    # title block field and its value share a line and a scale value can contain
    # spaces of its own ("1/4\" = 1'-0\"", "AS NOTED").
    #
    # The old pattern also had no "=" in its character class, so the imperial
    # form was cut at the equals and stored as '1/4" ='. The third pattern below
    # reads that form correctly but never ran, because the labelled pattern is
    # tried first and the loop breaks on the first match.
    scale_patterns = [
        r"(?:SCALE)[ \t]*[:=][ \t]*([^\r\n]+?)[ \t]*(?:\r?\n|$)",
        r"\b(1\s*:\s*\d{1,4})\b",
        r"(1/\d+\"\s*=\s*1'[\s-]*0\")",
    ]
    for idx, pattern in enumerate(scale_patterns):
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            value = match.group(1)
            if idx == 0:
                # Only the labelled pattern can run into a neighbouring column;
                # the two below are bounded by their own character sets.
                value = _trim_title_block_value(value, cut_on_column_gap=True)
            result["scale"] = value.strip()[:50]
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

    async def delete_sheet(self, sheet_id: uuid.UUID) -> None:
        """Hard-delete a sheet and its rendered thumbnail (best-effort).

        Mirrors :meth:`PhotoService.delete_photo` - the DB row goes first
        so a partial filesystem failure cannot leave an orphan record.
        Caller is expected to enforce project access via
        ``verify_project_access`` before invoking this.
        """
        sheet = await self.get_sheet(sheet_id)
        thumb_path_str = getattr(sheet, "thumbnail_path", None)

        await self.repo.delete(sheet_id)
        logger.info("Sheet deleted: %s", sheet_id)

        if thumb_path_str:
            try:
                thumb_path = Path(thumb_path_str)
                if thumb_path.exists():
                    thumb_path.unlink()
                    logger.info("Sheet thumbnail removed: %s", thumb_path)
            except Exception:
                logger.warning("Failed to remove sheet thumbnail: %s", thumb_path_str)

    async def update_sheet(
        self,
        sheet_id: uuid.UUID,
        data: SheetUpdate,
    ) -> Sheet:
        """Update sheet metadata fields."""
        sheet = await self.get_sheet(sheet_id)

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(sheet, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )

        if not fields:
            return sheet

        await self.repo.update_fields(sheet_id, **fields)
        await self.session.refresh(sheet)

        logger.info("Sheet updated: %s (fields=%s)", sheet_id, list(fields.keys()))
        return sheet

    # ── Split PDF ──────────────────────────────────────────────────────────

    async def _supersede_previous_sheets(
        self,
        project_id: uuid.UUID,
        sheets: list[Sheet],
    ) -> int:
        """Point each incoming sheet at the one it replaces and retire that one.

        Called with rows that are built but not yet inserted, so the links are
        written before the insert and the retirements ride the same flush.

        The rules, and why each one is the way it is:

        A page with no readable ``sheet_number`` is never chained. There is no
        key to chain it on, and treating "unreadable" as a value would collect
        every unreadable page in the project into one bogus history.

        A number carried by two pages of the SAME upload is a fault in the
        drawing set, not something to resolve by guessing. The earlier page
        takes the link, the predecessor retires because this upload does
        supersede it, and the later page stays current and unlinked. The
        register then shows two current rows for that number, which is the
        truth about the file that was uploaded. It is logged, because the
        alternative is that it looks like our duplication rather than theirs.

        Nothing is deleted and nothing is overwritten. A retired row keeps every
        column it had and only stops being current.

        Args:
            project_id: Project the upload belongs to.
            sheets: Freshly built, not yet inserted rows.

        Returns:
            How many existing sheets were retired.
        """
        numbered = [s for s in sheets if s.sheet_number]
        if not numbered:
            return 0

        predecessors = await self.repo.current_by_sheet_numbers(
            project_id,
            sorted({str(s.sheet_number) for s in numbered}),
        )
        if not predecessors:
            return 0

        claimed: set[str] = set()
        retired = 0
        for sheet in sorted(numbered, key=lambda s: s.page_number):
            number = str(sheet.sheet_number)
            previous = predecessors.get(number)
            if previous is None:
                continue
            if number in claimed:
                logger.warning(
                    "Sheet number %s appears on more than one page of this upload "
                    "for project %s; page %d is kept as a separate current sheet",
                    number,
                    project_id,
                    sheet.page_number,
                )
                continue
            claimed.add(number)
            sheet.previous_version_id = previous.id
            previous.is_current = False
            retired += 1

        return retired

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

        A sheet number already current in this project is superseded rather than
        duplicated, so uploading a revised set leaves one current row per number
        with the earlier row retired and linked. See
        ``_supersede_previous_sheets`` for the rules that decide this.

        Returns:
            List of created Sheet records. Only the new rows, never the ones
            they superseded.
        """
        try:
            import pdfplumber
        except ImportError:
            # pdfplumber is a base dependency and is in requirements-desktop.lock,
            # so a bundle that cannot import it is damaged rather than lean: the
            # repair wording, never DESKTOP_NO_EXTRA, which would claim the build
            # never carried it.
            from app.core.self_upgrade import repair_hint  # noqa: PLC0415

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="pdfplumber is not installed. " + repair_hint("Install with: pip install pdfplumber"),
            )

        # Read uploaded file
        raw_name = file.filename or "untitled.pdf"
        safe_name = _sanitize_filename(raw_name)

        # Stream to a temp file (aborts past the cap) so a multi-GB upload never
        # lands fully in RAM, then read the now-bounded bytes back for the split.
        try:
            async with stream_upload_to_temp(file, max_bytes=MAX_FILE_SIZE, suffix=".pdf") as staged:
                content = staged.path.read_bytes()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(f"PDF too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB)."),
            ) from exc

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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Failed to process PDF file: {exc}",
            )

        # A revised drawing set arrives as a new PDF, so without this every
        # re-upload doubled the register: two rows per sheet number, both
        # flagged current, distinguishable only by parent document. It also fed
        # a doubled ACTUAL set into ``check_completeness``, which reads
        # ``current_only=True`` and reconciles against a drawing index by
        # number. Run before the insert so the retirements and the new rows
        # land in one flush.
        superseded = await self._supersede_previous_sheets(project_id, sheets)

        if sheets:
            sheets = await self.repo.create_many(sheets)

        # Epic C - register a chain row per sheet AND one for the
        # parent PDF so the document hub also sees the chain.
        await _register_version_safely(
            self.session,
            project_id=project_id,
            file_kind="document",
            entity=document,
            file_id=str(document.id),
            file_size=len(content),
            uploaded_by=user_id,
        )
        for sheet in sheets:
            await _register_version_safely(
                self.session,
                project_id=project_id,
                file_kind="sheet",
                entity=sheet,
                file_id=str(sheet.id),
                file_size=0,
                uploaded_by=user_id,
            )

        logger.info(
            "PDF split into %d sheets (%d earlier sheets superseded): %s for project %s",
            len(sheets),
            superseded,
            safe_name,
            project_id,
        )
        return sheets

    # ── Sheet completeness (drawing index reconciliation) ──────────────────

    async def check_completeness(
        self,
        project_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
        index_document_id: uuid.UUID | None = None,
        index_page: int | None = None,
        pasted_index: str | None = None,
        expected_sheets: list[Any] | None = None,
        current_only: bool = True,
    ) -> dict[str, Any]:
        """Reconcile the project's sheet set against a drawing index.

        Builds the EXPECTED sheet set from whichever index source was supplied
        (a structured override, a pasted list, or an uploaded index PDF), loads
        the ACTUAL ``Sheet`` rows, and hands both to the validation module which
        runs the ``sheet_completeness`` rule set and persists a document report.

        Parsing lives here (documents owns sheets + the index PDF); persistence
        lives in the validation module. Raises :class:`ValueError` (mapped to
        404 / 422 by the router) for a missing/foreign index document or an
        unreadable index.
        """
        from app.modules.documents.sheet_index import (
            ExpectedSheet,
            normalize_sheet_number,
            parse_index_tables,
            parse_pasted_index,
            reconcile,
        )

        # 1. Build the EXPECTED set.
        if expected_sheets:
            expected = [
                ExpectedSheet(
                    sheet_number=s.sheet_number,
                    sheet_number_norm=normalize_sheet_number(s.sheet_number),
                    sheet_title=s.sheet_title,
                    revision=s.revision,
                )
                for s in expected_sheets
            ]
        elif pasted_index:
            expected = parse_pasted_index(pasted_index)
        elif index_document_id:
            doc = await DocumentRepository(self.session).get_by_id(index_document_id)
            # Re-assert the index document belongs to this project (IDOR-safe):
            # raise the same "not found" for missing and foreign so a caller on
            # one project cannot probe another project's document ids.
            if doc is None or doc.project_id != project_id:
                raise ValueError("Index document not found")
            expected = parse_index_tables(doc.file_path, index_page)
        else:
            raise ValueError("No index source provided")

        if not expected:
            raise ValueError("Could not read any sheet numbers from the index")

        # 2. Load the ACTUAL sheet rows (current-only by default so superseded
        #    revisions do not read as extra).
        sheets, _ = await self.list_sheets(project_id, limit=2000, current_only=current_only)
        actual = [
            {
                "id": str(s.id),
                "sheet_number": s.sheet_number,
                "revision": s.revision,
                "sheet_title": s.sheet_title,
                "discipline": s.discipline,
                "page_number": s.page_number,
            }
            for s in sheets
        ]

        # 3. Reconcile for the summary snapshot, then persist via the validation
        #    module (which re-runs the same diff through the rule set).
        result = reconcile(expected, actual)
        target_id = str(index_document_id) if index_document_id else str(project_id)
        source_meta = {
            "index_source": "document" if index_document_id else "pasted",
            "index_document_id": str(index_document_id) if index_document_id else None,
            "index_page": index_page,
            "expected_count": result.expected_count,
            "actual_count": result.actual_count,
            "missing": result.missing,
            "extra": result.extra,
            "matched": result.matched,
            "rev_mismatch": result.rev_mismatch,
        }

        from app.modules.validation.service import ValidationModuleService

        return await ValidationModuleService(self.session).run_sheet_completeness(
            project_id,
            target_id=target_id,
            expected=[e.__dict__ for e in expected],
            actual=actual,
            source_meta=source_meta,
            user_id=user_id,
        )


# ── DocumentBIMLink service ──────────────────────────────────────────────


class DocumentBIMLinkService:
    """Business logic for Document ↔ BIM element links.

    Mirrors the ``BOQElementLink`` flow in ``bim_hub.service`` but connects
    documents to BIM elements so the viewer and document hub can cross-link.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_links_for_element(
        self,
        bim_element_id: uuid.UUID,
    ) -> list[DocumentBIMLink]:
        """Return every DocumentBIMLink pointing at a given BIM element."""
        stmt = (
            select(DocumentBIMLink)
            .where(DocumentBIMLink.bim_element_id == bim_element_id)
            .order_by(DocumentBIMLink.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_links_for_document(
        self,
        document_id: uuid.UUID,
    ) -> list[DocumentBIMLink]:
        """Return every DocumentBIMLink attached to a given document."""
        stmt = (
            select(DocumentBIMLink)
            .where(DocumentBIMLink.document_id == document_id)
            .order_by(DocumentBIMLink.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_link(
        self,
        payload: DocumentBIMLinkCreate,
        user_id: uuid.UUID | None = None,
    ) -> DocumentBIMLink:
        """Create a new Document ↔ BIM element link.

        Raises:
            HTTPException(404): if document or BIM element does not exist.
            HTTPException(409): if a link for this (document, element) pair
                already exists.
        """
        # Verify document exists
        document = await self.session.get(Document, payload.document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.document_not_found", locale=get_locale()),
            )

        # Verify BIM element exists
        element = await self.session.get(BIMElement, payload.bim_element_id)
        if element is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element not found",
            )

        link = DocumentBIMLink(
            document_id=payload.document_id,
            bim_element_id=payload.bim_element_id,
            link_type=payload.link_type,
            confidence=payload.confidence,
            region_bbox=payload.region_bbox,
            created_by=user_id,
            metadata_=payload.metadata or {},
        )
        self.session.add(link)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document is already linked to this BIM element",
            ) from exc

        logger.info(
            "DocumentBIMLink created: doc=%s element=%s type=%s",
            payload.document_id,
            payload.bim_element_id,
            payload.link_type,
        )
        return link

    async def delete_link(self, link_id: uuid.UUID) -> None:
        """Delete a DocumentBIMLink. Raises 404 if not found."""
        link = await self.session.get(DocumentBIMLink, link_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="DocumentBIMLink not found",
            )
        await self.session.delete(link)
        await self.session.flush()
        logger.info("DocumentBIMLink deleted: %s", link_id)
