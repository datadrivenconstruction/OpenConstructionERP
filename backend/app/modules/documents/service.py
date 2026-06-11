"""‌⁠‍Document Management service - business logic for document management.

Stateless service layer. Handles:
- Document CRUD
- File upload/download management
- Summary aggregation
- Photo gallery CRUD
- Sheet management (PDF split, OCR detection)
- Document ↔ BIM element linking
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cde_states import CDEState, CDEStateMachine
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.bim_hub.models import BIMElement
from app.modules.documents.activity_service import record_activity
from app.modules.documents.models import Document, DocumentBIMLink, ProjectPhoto, Sheet
from app.modules.documents.repository import DocumentRepository, PhotoRepository, SheetRepository
from app.modules.documents.schemas import (
    DocumentBIMLinkCreate,
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
        await svc.register_new_version(payload, uploaded_by_id=uploaded_by_uuid)
    except Exception:
        logger.warning(
            "Failed to register FileVersion chain row for kind=%s file_id=%s",
            file_kind,
            file_id,
            exc_info=True,
        )


# Base directory for file uploads
UPLOAD_BASE = Path.home() / ".openestimator" / "uploads"

# Base directory for photo uploads
PHOTO_BASE = Path.home() / ".openestimator" / "photos"
# Base directory for photo thumbnails - stored next to originals under a sibling
# ``thumbs/`` subfolder so the gallery grid can ask for a small, cheap image
# instead of re-streaming the 50 MB original on every render.
PHOTO_THUMB_BASE = Path.home() / ".openestimator" / "photos" / "thumbs"
# Longest side (in px) of a generated photo thumbnail. 512 is plenty for the
# grid view and keeps the thumbnail under ~60 kB for typical JPEGs.
PHOTO_THUMB_MAX_SIDE = 512
PHOTO_THUMB_QUALITY = 82

# Security constants
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
MAX_PHOTO_SIZE = 200 * 1024 * 1024  # 200MB
VALID_CATEGORIES = {"drawing", "contract", "specification", "photo", "correspondence", "other"}
VALID_PHOTO_CATEGORIES = {"site", "progress", "defect", "delivery", "safety", "other"}
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
    """‌⁠‍Remove path components and dangerous characters from filename."""
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


def _generate_photo_thumbnail(
    source_bytes: bytes,
    dest_path: Path,
) -> bool:
    """‌⁠‍Write a JPEG thumbnail of ``source_bytes`` to ``dest_path``.

    Returns ``True`` on success, ``False`` if anything went wrong (missing
    Pillow, corrupt image, unsupported mode). Thumbnail generation is a
    best-effort optimisation - a failure must never block the upload.
    """
    try:
        from io import BytesIO

        from PIL import Image, ImageOps
    except Exception:
        logger.warning("Pillow not available - skipping photo thumbnail")
        return False

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

        # Enforce size cap (defence in depth - max also expected at the
        # API gateway level). Done after reading because UploadFile is a
        # streaming object: we cap on read by checking length before
        # acceptance. 100 MB is enough for typical AEC drawings and
        # contracts; oversized assets belong on direct-to-S3 paths.
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File too large: {len(content)} bytes "
                    f"(max {MAX_FILE_SIZE} bytes / "
                    f"{MAX_FILE_SIZE // (1024 * 1024)} MB)."
                ),
            )

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

        # Create DB record FIRST - if this fails we haven't written a file
        document = Document(
            project_id=project_id,
            name=safe_name,
            category=category,
            file_size=len(content),
            mime_type=stored_mime,
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

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(f"File too large: {len(content)} bytes (max {MAX_FILE_SIZE} bytes)."),
            )

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
    ) -> tuple[list[Document], int]:
        """List documents for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            category=category,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
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
            fields["metadata_"] = fields.pop("metadata")

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

        # Enforce size cap (defence in depth; max also expected at the
        # API gateway level). 50 MB is enough for 12 MP JPEGs and
        # construction-site phone photos; bigger assets belong on
        # direct-to-S3 paths.
        content = await file.read()
        if len(content) > MAX_PHOTO_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Photo too large: {len(content)} bytes "
                    f"(max {MAX_PHOTO_SIZE} bytes / "
                    f"{MAX_PHOTO_SIZE // (1024 * 1024)} MB)."
                ),
            )

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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="uploaded file content does not match an image format",
            )

        # Use the magic-byte-derived MIME for the cross-linked Document
        # row below (P0-1). The header value is left in ``content_type``
        # for backwards-compat with the photo response field but the
        # stored canonical MIME is server-derived.
        stored_mime = _mime_for_signature(detected_photo_type)

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
        # the serve endpoint falls back to the original on miss.
        thumb_generated = _generate_photo_thumbnail(content, thumb_path)
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

        # Also create a Document record so photos appear in Documents hub
        try:
            import json as _json

            from sqlalchemy import text as _text

            doc_id = str(uuid.uuid4())
            # Write a NAIVE UTC timestamp so the cross-linked Document row
            # round-trips identical to every other oe_documents_document row
            # (SQLAlchemy stores model created_at/updated_at as naive UTC on
            # SQLite). Mixing aware here with naive elsewhere previously broke
            # the file-manager modified-sort with a TypeError → HTTP 500.
            now = datetime.now(UTC).replace(tzinfo=None).isoformat()
            tags_json = _json.dumps(["photo", category or "site"])
            await self.session.execute(
                _text(
                    "INSERT INTO oe_documents_document "
                    "(id, project_id, name, description, category, file_size, mime_type, "
                    "file_path, version, uploaded_by, tags, metadata, created_at, updated_at) "
                    "VALUES (:id, :pid, :name, :desc, :cat, :fsize, :mime, :fpath, 1, :by, :tags, '{}', :now, :now)"
                ),
                {
                    "id": doc_id,
                    "pid": str(project_id),
                    "name": safe_name,
                    "desc": caption or "",
                    "cat": "photo",
                    "fsize": len(content),
                    "mime": stored_mime,
                    "fpath": str(file_path),
                    "by": user_id or "",
                    "tags": tags_json,
                    "now": now,
                },
            )
            logger.info("Cross-linked photo → document %s (tags: photo, %s)", doc_id, category)
        except Exception:
            logger.exception("CROSS-LINK FAILED")

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

    async def recent_across_projects(
        self,
        user_id: str | None,
        *,
        limit: int = 12,
    ) -> list[tuple[ProjectPhoto, str]]:
        """Return the most recent photos across every project the caller can see.

        Access control mirrors the dashboard / project-list endpoints
        (owner-OR-member, admins see every project) so the widget never
        leaks photos from a project the user cannot open. The accessible
        project-id set is resolved here and handed to the repository join,
        so the SQL can never return a row outside that set.
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
    Does NOT rely on external OCR services - works on already-extracted text.

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
        # Defence-in-depth size cap (also expected at API gateway level).
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"PDF too large: {len(content)} bytes "
                    f"(max {MAX_FILE_SIZE} bytes / "
                    f"{MAX_FILE_SIZE // (1024 * 1024)} MB)."
                ),
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
            "PDF split into %d sheets: %s for project %s",
            len(sheets),
            safe_name,
            project_id,
        )
        return sheets


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
