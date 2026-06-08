# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Match Elements REST router.

Endpoints (auto-mounted at /api/v1/match_elements/ by the module loader):

    POST   /sessions                       Create session (auto-bind catalogue)
    POST   /sessions/from-excel            Create session from an uploaded xlsx BoQ
    POST   /sessions/from-pdf              Create session from an uploaded tender PDF
    POST   /sessions/from-image            Create session from an uploaded photo/drawing
    GET    /sessions?project_id=...        List recent sessions for resume picker
    GET    /sessions/{id}                  Read one session
    PATCH  /sessions/{id}                  Update group_by / filters / archive / threshold
    POST   /sessions/{id}/touch            Bump last_active_at (cheap heartbeat)

    GET    /sessions/{id}/groups           Paginated list with summary counters
    GET    /sessions/{id}/group?group_key= Detailed group + matcher candidates
    POST   /sessions/{id}/groups/split     Split a group (per-item or by subset)
    POST   /sessions/{id}/groups/merge     Merge another group into this one

    POST   /sessions/{id}/match            Run vector / lexical / resources matcher
    POST   /sessions/{id}/confirm          Confirm a candidate as the chosen match
    POST   /sessions/{id}/bulk-confirm     Confirm all suggested above threshold
    POST   /sessions/{id}/apply            Dry-run preview / write to BOQ
    POST   /sessions/{id}/no-match         Mark group TBD / RFQ / custom

    GET    /sessions/{id}/attributes       Drag-source list of group-by chip keys
    GET    /sessions/{id}/categories       IFC class counts (with translated labels)

    GET    /projects/{project_id}/bim-models  BIM model strip for the BIM tabs

    GET    /templates                      Tenant template library
    POST   /templates/lookup               Bulk signature lookup
    DELETE /templates/{id}                 Remove template
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import CurrentUserId, SessionDep, verify_project_access
from app.modules.match_elements import pipeline, schemas
from app.modules.match_elements.analytics import compute_match_analytics
from app.modules.match_elements.excel_import import parse_boq_xlsx
from app.modules.match_elements.models import MatchGroup, MatchPromptTemplate, MatchSession
from app.modules.match_elements.pdf_import import parse_boq_pdf
from app.modules.match_elements.service import get_service
from app.modules.match_elements.signature_match_service import (
    descriptor_from_group_row,
    get_signature_service,
)

router = APIRouter(tags=["match_elements"])


# Directory where uploaded /sessions/from-image photos / drawing
# snapshots are stored on disk. The path form (over inline base64) keeps
# large photos out of the MatchSession.metadata_ JSON column so session
# listing pagination stays fast; the ImageSourceAdapter reads the file
# back lazily on iter_elements. Mirrors the takeoff module's
# ``_TAKEOFF_DOCUMENTS_DIR`` convention.
_MATCH_IMAGES_DIR: Path = Path.home() / ".openestimator" / "match_images"

# Per-image upload cap. Vision-LLM providers reject payloads well above
# this, and a 10 MB photo already exceeds the resolution any model uses
# internally, so we reject earlier to give the user a clear error rather
# than a downstream provider 4xx. Mirrors the design's 10 MB limit.
_MAX_IMAGE_BYTES: int = 10 * 1024 * 1024

# Accepted upload MIME types and their magic-byte signatures. We gate on
# the actual bytes (not just the Content-Type header or extension) so a
# renamed ``.exe`` / ``.zip`` can't slip a non-image into the vision
# pipeline. WebP carries a ``RIFF....WEBP`` container; the inner check
# below handles the 4-byte gap.
_IMAGE_MAGIC_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


def _detect_image_mime(content: bytes) -> str | None:
    """Return the canonical image MIME from magic bytes, or ``None``.

    Recognises JPEG, PNG and WebP (RIFF container). Anything else is
    rejected upstream as an unsupported upload - better a clean 400 than
    handing a non-image to the vision provider.
    """
    for prefix, mime in _IMAGE_MAGIC_PREFIXES:
        if content.startswith(prefix):
            return mime
    # WebP: bytes 0..4 == "RIFF", bytes 8..12 == "WEBP".
    if len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _u(s: str) -> uuid.UUID:
    return uuid.UUID(s)


async def _assert_session_access(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: str,
) -> uuid.UUID:
    """‌⁠‍Authorise a request that targets a specific MatchSession.

    Loads the row, raises 404 if missing, and delegates project-level
    ownership to ``verify_project_access`` (which also returns 404 on
    deny so we don't leak existence). Returns the session's project_id
    so callers can avoid a second lookup.
    """
    row = (
        await db.execute(
            select(MatchSession.project_id).where(MatchSession.id == session_id),
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Match session not found")
    project_id = row[0]
    await verify_project_access(project_id, user_id, db)
    return project_id


# ── Sessions ─────────────────────────────────────────────────────────────


@router.post("/sessions", response_model=schemas.SessionRead, status_code=201)
async def create_session(
    spec: schemas.SessionCreate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.SessionRead:
    await verify_project_access(spec.project_id, current_user_id, session)
    try:
        return await get_service().create_session(
            session,
            spec,
            _u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/from-excel",
    response_model=schemas.SessionRead,
    status_code=201,
    summary="Create a BoQ match session by uploading an xlsx file",
)
async def create_session_from_excel(
    session: SessionDep,
    current_user_id: CurrentUserId,
    project_id: uuid.UUID = Form(...),
    file: UploadFile = File(..., description="Bill of Quantities .xlsx file"),
    name: str | None = Form(None),
    # Accepts a CWICR v3 region id ("DE_BERLIN", ...) or a legacy UUID -
    # the service layer routes each kind to its own storage slot. Was
    # ``uuid.UUID | None`` before, which 422'd every wizard submission.
    catalogue_id: str | None = Form(None),
    construction_stage: str | None = Form(None),
) -> schemas.SessionRead:
    """‌⁠‍Upload an xlsx BoQ and create a match session in one round-trip.

    Implements MAPPING_PROCESS.md §4.1.5 - the Excel BoQ source. Column
    detection is multi-language (English/German/Russian/Spanish/Chinese
    /Japanese/Korean/Turkish/Polish/etc.); see
    :mod:`match_elements.excel_import` for the full alias table.
    Caller-side parsing is still supported via the regular
    ``POST /sessions`` endpoint with ``boq_rows`` populated - this route
    is the convenience path for end users.
    """
    await verify_project_access(project_id, current_user_id, session)

    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail=("Only .xlsx files are supported. Save your BoQ as Excel (not .xls / .csv) and re-upload."),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        rows = parse_boq_xlsx(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "No valid BoQ rows found. Ensure your spreadsheet has a "
                "header row with at least a 'Description' column and at "
                "least one data row underneath."
            ),
        )

    spec = schemas.SessionCreate(
        project_id=project_id,
        source="boq",
        name=name or (file.filename or "BoQ Import"),
        catalogue_id=catalogue_id,
        construction_stage=construction_stage,  # type: ignore[arg-type]
        boq_rows=rows,
    )

    try:
        return await get_service().create_session(
            session,
            spec,
            _u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/from-pdf",
    response_model=schemas.SessionRead,
    status_code=201,
    summary="Create a BoQ match session by uploading a PDF file",
)
async def create_session_from_pdf(
    session: SessionDep,
    current_user_id: CurrentUserId,
    project_id: uuid.UUID = Form(...),
    file: UploadFile = File(..., description="Tender PDF (printed bill of quantities / priced schedule)"),
    name: str | None = Form(None),
    # Region id ("DE_BERLIN", ...) or a legacy UUID - the service routes
    # each kind to its own storage slot (mirrors the Excel endpoint).
    catalogue_id: str | None = Form(None),
    construction_stage: str | None = Form(None),
) -> schemas.SessionRead:
    """‌⁠‍Upload a tender PDF and create a match session in one round-trip.

    The backend extracts one line item per table row (preferred) or per
    text line (fallback) using the libraries already shipped with the
    platform; see :mod:`match_elements.pdf_import` for the extraction
    strategy. Caller-side parsing is still supported via the regular
    ``POST /sessions`` endpoint with ``pdf_rows`` populated - this route
    is the convenience path for end users.
    """
    await verify_project_access(project_id, current_user_id, session)

    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only .pdf files are supported. Upload the tender PDF (not an image or Office file).",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    # Magic-byte gate - reject anything that is not actually a PDF before
    # handing it to the parser (mirrors the takeoff upload guard).
    if content[:5] != b"%PDF-":
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a valid PDF (missing %PDF- header). Re-export and try again.",
        )

    try:
        rows = parse_boq_pdf(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "No line items could be extracted from this PDF. It may be a "
                "scanned image with no text layer - run OCR first, or paste the "
                "items via the Text source."
            ),
        )

    spec = schemas.SessionCreate(
        project_id=project_id,
        source="pdf",
        name=name or (file.filename or "PDF Import"),
        catalogue_id=catalogue_id,
        construction_stage=construction_stage,  # type: ignore[arg-type]
        pdf_rows=rows,
    )

    try:
        return await get_service().create_session(
            session,
            spec,
            _u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/from-image",
    response_model=schemas.SessionRead,
    status_code=201,
    summary="Create a match session by uploading a photo or drawing snapshot",
)
async def create_session_from_image(
    session: SessionDep,
    current_user_id: CurrentUserId,
    project_id: uuid.UUID = Form(...),
    image: UploadFile = File(..., description="Site photo / drawing snapshot (PNG / JPG / WebP)"),
    name: str | None = Form(None),
    # Region id ("DE_BERLIN", ...) or a legacy UUID - the service routes
    # each kind to its own storage slot (mirrors the Excel / PDF endpoints).
    catalogue_id: str | None = Form(None),
    construction_stage: str | None = Form(None),
) -> schemas.SessionRead:
    """‌⁠‍Upload one photo / drawing and create an image-source session.

    Implements MAPPING_PROCESS.md §3.1 / §4.1.4 - the "Image" source.
    The estimator uploads a single site photo, hand sketch or CAD
    elevation screenshot; the saved file is bound to
    ``MatchSession.metadata_["image"]`` as ``{"path", "mime",
    "filename", "image_id"}`` and read back lazily by
    :class:`ImageSourceAdapter`, which asks the configured vision-LLM to
    enumerate the visible construction elements with rough quantity
    estimates. Each element flows through the same matcher pipeline as
    BIM / DWG / text envelopes.

    Extraction is a *suggestion* the user reviews and confirms - the
    adapter degrades to zero extracted elements (a usable but empty
    session) when no AI provider is configured, never auto-applies a
    match, and always reports ``ai_confidence="low"``.

    Caller-side binding is still supported via the regular
    ``POST /sessions`` endpoint with ``source="image"`` and an inline
    ``image`` dict - this route is the convenience path for end users.
    """
    await verify_project_access(project_id, current_user_id, session)

    content = await image.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Image is too large. The limit is 10 MB - downscale the photo "
                "(most phones let you share a smaller copy) and re-upload."
            ),
        )

    # Magic-byte gate - reject anything that is not actually a PNG / JPG /
    # WebP before binding it to the session (mirrors the PDF / takeoff
    # upload guards). We trust the bytes over the Content-Type header.
    mime = _detect_image_mime(content)
    if mime is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Only PNG, JPG or WebP images are supported. Upload a photo or "
                "drawing snapshot (not a PDF, Office file or archive)."
            ),
        )

    # Persist the file to disk so the adapter reads a path (large photos
    # would otherwise bloat the metadata_ JSON column). The id doubles as
    # the SourceElement raw_ref so the UI can link results back to the
    # originating upload.
    image_id = uuid.uuid4()
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[mime]
    try:
        _MATCH_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        file_path = _MATCH_IMAGES_DIR / f"{image_id}{ext}"
        file_path.write_bytes(content)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not store the uploaded image on the server.",
        ) from exc

    spec = schemas.SessionCreate(
        project_id=project_id,
        source="image",
        name=name or (image.filename or "Photo / Drawing"),
        catalogue_id=catalogue_id,
        construction_stage=construction_stage,  # type: ignore[arg-type]
        image={
            "path": str(file_path),
            "mime": mime,
            "filename": image.filename or f"{image_id}{ext}",
            "image_id": str(image_id),
        },
    )

    try:
        return await get_service().create_session(
            session,
            spec,
            _u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get("/sessions", response_model=list[schemas.SessionSummary])
async def list_sessions(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
    include_archived: bool = False,
    limit: int = 50,
) -> list[schemas.SessionSummary]:
    await verify_project_access(project_id, current_user_id, session)
    try:
        return await get_service().list_sessions(
            session,
            project_id,
            include_archived=include_archived,
            limit=limit,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get("/sessions/{session_id}", response_model=schemas.SessionRead)
async def get_session_endpoint(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.SessionRead:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().get_session(session, session_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.patch("/sessions/{session_id}", response_model=schemas.SessionRead)
async def update_session(
    session_id: uuid.UUID,
    patch: schemas.SessionUpdate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.SessionRead:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().update_session(session, session_id, patch)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/touch", status_code=204)
async def touch_session(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> None:
    await _assert_session_access(session, session_id, current_user_id)
    await get_service().touch_session(session, session_id)


@router.get("/sessions/{session_id}/progress")
async def get_match_progress(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> dict[str, object]:
    """Lightweight progress poll for an in-flight or finished match run.

    Read-only - fetches from the process-local in-memory dict the
    match runner writes to. The wizard's MatchProgressCard polls this
    every ~800ms while the match is running and stops as soon as
    ``status`` flips to ``done`` or ``error``. Always 200 - an idle
    session returns a neutral payload so the FE never has to
    special-case 404 vs "no run yet".
    """
    await _assert_session_access(session, session_id, current_user_id)
    return await get_service().get_progress(session, session_id)


@router.post("/sessions/{session_id}/__debug_set_progress", include_in_schema=False)
async def debug_set_progress(
    session_id: uuid.UUID,
    payload: dict[str, object],
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> dict[str, str]:
    """Test-only hook to pre-seed the in-memory progress dict.

    Used by ``probe-match-progress-stages.mjs`` to capture the
    MatchProgressCard at each of the 5 stages even when the real
    match completes in <2s on the local backend's tiny text fixture.
    Hidden from the OpenAPI schema (``include_in_schema=False``)
    because it's not part of the public contract - the only legit
    caller is the QA probe.

    Safety: the same project-access check the real progress endpoint
    runs gates this one - a stranger can't poison someone else's
    session.
    """
    await _assert_session_access(session, session_id, current_user_id)
    from app.modules.match_elements.service import MatchElementsService  # noqa: PLC0415

    MatchElementsService._write_progress(
        session_id,
        stage=str(payload.get("stage", "init")),
        stage_idx=int(payload.get("stage_idx", 1) or 1),
        groups_done=int(payload.get("groups_done", 0) or 0),
        groups_total=int(payload.get("groups_total", 0) or 0),
        started_at=payload.get("started_at"),  # type: ignore[arg-type]
        status=str(payload.get("status", "running")),
        error=payload.get("error"),  # type: ignore[arg-type]
    )
    return {"ok": "set"}


# ── Groups ───────────────────────────────────────────────────────────────


@router.get(
    "/sessions/{session_id}/groups",
    response_model=schemas.GroupListResponse,
)
async def list_groups(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> schemas.GroupListResponse:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().list_groups(
            session,
            session_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get(
    "/sessions/{session_id}/group",
    response_model=schemas.GroupDetail,
)
async def get_group(
    session_id: uuid.UUID,
    group_key: str,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().get_group_detail(
            session,
            session_id,
            group_key,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/groups/split",
    response_model=schemas.GroupDetail,
)
async def split_group(
    session_id: uuid.UUID,
    group_key: str,
    spec: schemas.GroupSplitRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().split_group(
            session,
            session_id,
            group_key,
            spec,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/groups/merge",
    response_model=schemas.GroupDetail,
)
async def merge_groups(
    session_id: uuid.UUID,
    group_key: str,
    spec: schemas.GroupMergeRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().merge_groups(
            session,
            session_id,
            group_key,
            spec,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


# ── Attributes / categories ─────────────────────────────────────────────


@router.get(
    "/sessions/{session_id}/attributes",
    response_model=list[schemas.AttributeKey],
)
async def list_attribute_keys(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> list[schemas.AttributeKey]:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().list_attribute_keys(session, session_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get(
    "/sessions/{session_id}/categories",
    response_model=list[schemas.CategoryCount],
)
async def list_categories(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> list[schemas.CategoryCount]:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().list_categories(session, session_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


# ── BIM models for the BIM tab strip ─────────────────────────────────────


@router.get(
    "/projects/{project_id}/bim-models",
    response_model=list[schemas.BIMModelOption],
)
async def list_project_bim_models(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> list[schemas.BIMModelOption]:
    """BIM models attached to a project, ready-to-bind to a session.

    Mirrors the ``/api/v1/bim_hub/`` list shape, but returns only the
    fields the match-elements page renders (filename, format, status,
    counts, timestamps). Filters out errored/processing models so the
    user can't bind to a model that has nothing to match against.
    """
    await verify_project_access(project_id, current_user_id, session)
    from app.modules.bim_hub.models import BIMModel

    stmt = select(BIMModel).where(BIMModel.project_id == project_id).order_by(BIMModel.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    out: list[schemas.BIMModelOption] = []
    for m in rows:
        out.append(
            schemas.BIMModelOption(
                id=m.id,
                name=m.name,
                model_format=m.model_format,
                element_count=int(m.element_count or 0),
                storey_count=int(m.storey_count or 0),
                status=m.status or "",
                created_at=m.created_at,
            )
        )
    return out


# ── Match / confirm / apply ──────────────────────────────────────────────


@router.post(
    "/sessions/{session_id}/match",
    response_model=list[schemas.GroupSummary],
)
async def run_match(
    session_id: uuid.UUID,
    spec: schemas.RunMatchRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> list[schemas.GroupSummary]:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().run_match(
            session,
            session_id,
            spec,
            user_id=_u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/confirm",
    response_model=schemas.GroupDetail,
)
async def confirm_match(
    session_id: uuid.UUID,
    spec: schemas.ConfirmMatchRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().confirm(
            session,
            session_id,
            spec,
            _u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/bulk-confirm")
async def bulk_confirm(
    session_id: uuid.UUID,
    spec: schemas.BulkConfirmRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> dict[str, int]:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        n = await get_service().bulk_confirm(
            session,
            session_id,
            spec,
            _u(current_user_id),
        )
        return {"confirmed_count": n}
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/apply",
    response_model=schemas.ApplyToBoqResponse,
)
async def apply_to_boq(
    session_id: uuid.UUID,
    spec: schemas.ApplyToBoqRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.ApplyToBoqResponse:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().apply_to_boq(
            session,
            session_id,
            spec,
            _u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/no-match",
    response_model=schemas.GroupDetail,
)
async def no_match(
    session_id: uuid.UUID,
    spec: schemas.NoMatchRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().no_match(session, session_id, spec)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


# ── Templates (cross-project library) ────────────────────────────────────


@router.get("/templates", response_model=list[schemas.TemplateRead])
async def list_templates(
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> list[schemas.TemplateRead]:
    try:
        return await get_service().list_templates(session, tenant_id=None)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/templates/lookup",
    response_model=schemas.TemplateLookupResponse,
)
async def lookup_templates(
    spec: schemas.TemplateLookupRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.TemplateLookupResponse:
    try:
        return await get_service().lookup_templates(
            session,
            tenant_id=None,
            signatures=spec.signatures,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> None:
    try:
        await get_service().delete_template(session, template_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


# ── Symbol-signature suggestions (item #18) ──────────────────────────────


@router.post(
    "/suggest-symbols",
    response_model=schemas.SymbolSuggestResponse,
    summary="Rank symbol suggestions for an element / candidate descriptor",
)
async def suggest_symbols(
    spec: schemas.SymbolSuggestRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.SymbolSuggestResponse:
    """Deterministically rank a descriptor against the symbol library.

    Computes a shape/symbol signature from the descriptor (category +
    geometry quantities + property fingerprint) and ranks it against a
    built-in library of known symbol archetypes (door, window, column,
    beam, wall, pipe, duct, fixture). Each suggestion carries an honest
    confidence score (0..1) and the contributing factors.

    This is NOT computer vision. Raster CV symbol detection from drawing
    pixels is the separate cv-pipeline service (YOLO / PaddleOCR, roadmap
    Phase 3). The recogniser SUGGESTS; the human confirms downstream via
    the existing confirm/apply path - nothing is auto-applied.

    Provide either an inline descriptor, or a ``session_id`` + ``group_key``
    pointing at a stored group whose geometry/properties are turned into a
    descriptor. Group references are authorised first (IDOR -> 404). Inline
    descriptor fields, when present, override the resolved group fields.
    """
    descriptor: dict[str, object] = {
        "category": spec.category,
        "quantities": dict(spec.quantities),
        "properties": dict(spec.properties),
    }

    # If a stored group is referenced, authorise the owning session
    # (404 on missing / denied so we never leak ids) and fold its stored
    # geometry/properties into the descriptor. Inline fields win.
    if spec.session_id is not None and spec.group_key is not None:
        await _assert_session_access(session, spec.session_id, current_user_id)
        row = (
            await session.execute(
                select(
                    MatchGroup.group_key,
                    MatchGroup.quantities,
                    MatchGroup.metadata_,
                ).where(
                    MatchGroup.session_id == spec.session_id,
                    MatchGroup.group_key == spec.group_key,
                ),
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Match group not found")
        resolved = descriptor_from_group_row(row[0], row[1], row[2])
        # Inline overrides: only override category when the caller actually
        # sent one; merge inline quantities/properties on top of resolved.
        if not spec.category:
            descriptor["category"] = resolved.get("category", "")
        merged_q = dict(resolved.get("quantities") or {})
        merged_q.update(spec.quantities)
        descriptor["quantities"] = merged_q
        merged_p = dict(resolved.get("properties") or {})
        merged_p.update(spec.properties)
        descriptor["properties"] = merged_p

    result = get_signature_service().suggest(
        descriptor,
        top_k=spec.top_k,
        min_confidence=spec.min_confidence,
    )

    return schemas.SymbolSuggestResponse(
        signature=schemas.SymbolSignatureOut(
            category=result.signature.category,
            ratios=result.signature.ratios,
            property_fingerprint=list(result.signature.property_fingerprint),
            raw_dimensions=result.signature.raw_dimensions,
        ),
        suggestions=[
            schemas.SymbolSuggestion(
                symbol=s.symbol,
                confidence=s.confidence,
                confidence_band=s.confidence_band,  # type: ignore[arg-type]
                factors=[schemas.SymbolFactor(**f) for f in s.factors],
                rank=s.rank,
            )
            for s in result.suggestions
        ],
        note=result.note,
    )


# ── Visible pipeline (v3034 - 7-stage match wizard) ──────────────────────


@router.get(
    "/sessions/{session_id}/stages",
    response_model=schemas.StageListResponse,
)
async def list_pipeline_stages(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.StageListResponse:
    """Return the seven pipeline stages for a session in canonical order.

    Stages that have never run come back with status ``pending`` and
    empty inputs/output so the UI always renders a full timeline. The
    ``explainer`` / ``title`` / ``subtitle`` fields are the source of
    truth for the StageCard copy.
    """
    await _assert_session_access(session, session_id, current_user_id)
    await pipeline.ensure_system_prompts(session)
    stages = await pipeline.list_stages(session, session_id)
    return schemas.StageListResponse(
        session_id=session_id,
        stages=[schemas.StageState(**s) for s in stages],
    )


@router.post(
    "/sessions/{session_id}/stages/{stage_name}/run",
    response_model=schemas.RunStageResponse,
)
async def run_pipeline_stage(
    session_id: uuid.UUID,
    stage_name: str,
    spec: schemas.RunStageRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.RunStageResponse:
    """Execute one stage and persist its state.

    Downstream stages that were ``done`` are marked ``stale`` so the UI
    shows the user which steps need re-running after a tweak. An empty
    body re-runs the stage with whatever knobs are already stored on it.
    """
    await _assert_session_access(session, session_id, current_user_id)
    if stage_name not in pipeline.STAGE_NAMES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown stage: {stage_name!r}",
        )
    try:
        result = await pipeline.run_stage(
            session,
            session_id,
            stage_name,
            inputs_override=spec.inputs,
            prompt_template_id=spec.prompt_template_id,
            llm_provider=spec.llm_provider,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return schemas.RunStageResponse(**result)


# ── Prompt templates (user-editable LLM prompts) ─────────────────────────


@router.get(
    "/prompt-templates",
    response_model=list[schemas.PromptTemplateRead],
)
async def list_prompt_templates(
    session: SessionDep,
    current_user_id: CurrentUserId,
    key: str | None = Query(None, max_length=64),
) -> list[schemas.PromptTemplateRead]:
    """List system + own prompt templates, optionally filtered by stage key.

    System prompts (``is_system=True``, ``created_by=NULL``) are visible
    to everyone; user prompts are visible only to their creator. The UI
    groups them under each stage's ``prompt_key``.
    """
    await pipeline.ensure_system_prompts(session)
    try:
        uid = uuid.UUID(current_user_id)
    except (ValueError, TypeError):
        uid = None
    stmt = select(MatchPromptTemplate).where(
        (MatchPromptTemplate.is_system.is_(True)) | (MatchPromptTemplate.created_by == uid)
    )
    if key:
        stmt = stmt.where(MatchPromptTemplate.key == key)
    stmt = stmt.order_by(
        MatchPromptTemplate.key.asc(),
        MatchPromptTemplate.is_system.desc(),
        MatchPromptTemplate.version.desc(),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [schemas.PromptTemplateRead.model_validate(r) for r in rows]


@router.get(
    "/prompt-templates/{template_id}",
    response_model=schemas.PromptTemplateRead,
)
async def get_prompt_template(
    template_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.PromptTemplateRead:
    row = await session.get(MatchPromptTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail=translate("errors.prompt_not_found", locale=get_locale()))
    if not row.is_system:
        try:
            uid = uuid.UUID(current_user_id)
        except (ValueError, TypeError):
            uid = None
        if row.created_by != uid:
            raise HTTPException(
                status_code=404,
                detail=translate("errors.prompt_not_found", locale=get_locale()),
            )
    return schemas.PromptTemplateRead.model_validate(row)


@router.post(
    "/prompt-templates",
    response_model=schemas.PromptTemplateRead,
    status_code=201,
)
async def create_prompt_template(
    spec: schemas.PromptTemplateCreate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.PromptTemplateRead:
    """Create a user-owned prompt - typically a fork of a system prompt.

    The ``key`` is validated against the known stage hooks so a typo
    can't orphan a prompt that no stage will ever resolve.
    """
    valid_keys = {m["prompt_key"] for m in pipeline.STAGE_META.values() if m["prompt_key"]}
    if spec.key not in valid_keys:
        raise HTTPException(
            status_code=400,
            detail=(f"Unknown prompt key {spec.key!r}. Valid keys: {sorted(valid_keys)}"),
        )
    try:
        uid: uuid.UUID | None = uuid.UUID(current_user_id)
    except (ValueError, TypeError):
        uid = None
    # Next version for this (key) owned by the user.
    existing = (
        await session.execute(
            select(MatchPromptTemplate.version)
            .where(
                MatchPromptTemplate.key == spec.key,
                MatchPromptTemplate.created_by == uid,
            )
            .order_by(MatchPromptTemplate.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    next_version = (existing or 0) + 1
    row = MatchPromptTemplate(
        key=spec.key,
        name=spec.name,
        description=spec.description,
        system_prompt=spec.system_prompt or "",
        user_template=spec.user_template,
        allowed_providers=spec.allowed_providers,
        version=next_version,
        is_system=False,
        created_by=uid,
        forked_from_id=spec.forked_from_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return schemas.PromptTemplateRead.model_validate(row)


@router.patch(
    "/prompt-templates/{template_id}",
    response_model=schemas.PromptTemplateRead,
)
async def update_prompt_template(
    template_id: uuid.UUID,
    patch: schemas.PromptTemplateUpdate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.PromptTemplateRead:
    """Edit a user-owned prompt. System prompts are immutable - fork first."""
    row = await session.get(MatchPromptTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail=translate("errors.prompt_not_found", locale=get_locale()))
    if row.is_system:
        raise HTTPException(
            status_code=403,
            detail="System prompts are read-only - fork it first",
        )
    try:
        uid = uuid.UUID(current_user_id)
    except (ValueError, TypeError):
        uid = None
    if row.created_by != uid:
        raise HTTPException(status_code=404, detail=translate("errors.prompt_not_found", locale=get_locale()))
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(row, field, value)
    row.version = (row.version or 1) + 1
    await session.commit()
    await session.refresh(row)
    return schemas.PromptTemplateRead.model_validate(row)


@router.delete("/prompt-templates/{template_id}", status_code=204)
async def delete_prompt_template(
    template_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> None:
    row = await session.get(MatchPromptTemplate, template_id)
    if row is None:
        return
    if row.is_system:
        raise HTTPException(
            status_code=403,
            detail="System prompts cannot be deleted",
        )
    try:
        uid = uuid.UUID(current_user_id)
    except (ValueError, TypeError):
        uid = None
    if row.created_by != uid:
        raise HTTPException(status_code=404, detail=translate("errors.prompt_not_found", locale=get_locale()))
    await session.delete(row)
    await session.commit()


# ── Analytics (MAPPING_PROCESS.md §10) ───────────────────────────────────


@router.get("/analytics", response_model=schemas.AnalyticsResponse)
async def get_match_analytics(
    session: SessionDep,
    current_user_id: CurrentUserId,
    days: int = Query(7, ge=1, le=90),
    project_id: uuid.UUID | None = Query(None),
    catalog_id: str | None = Query(None, max_length=64),
) -> schemas.AnalyticsResponse:
    """Return aggregate match-quality metrics for the last ``days`` days.

    Pass ``project_id`` to scope to a single project (auth-checked the
    same way as other project routes); omit it for tenant-wide rollup
    (user must still be authenticated). ``catalog_id`` (e.g.
    ``cwicr_DE``) further narrows the window when diagnosing one
    catalogue's recall.

    Always 200 - empty windows return zero-counters with no alerts so
    the dashboard renders cleanly on a fresh deploy.
    """
    if project_id is not None:
        await verify_project_access(project_id, current_user_id, session)
    return await compute_match_analytics(
        session,
        days=days,
        project_id=project_id,
        catalog_id=catalog_id,
    )


# ── Qdrant supervisor (native binary, no Docker) ─────────────────────────


def _qdrant_health_to_dict(health: object) -> dict[str, object]:
    """Render a ``QdrantHealth`` dataclass as a JSON-safe dict.

    Frontend ``QdrantHealthCard`` consumes these fields verbatim; the
    shape is locked to the dataclass in ``qdrant_supervisor.py``.
    """
    return {
        "reachable": getattr(health, "reachable", False),
        "url": getattr(health, "url", None),
        "installed": getattr(health, "installed", False),
        "binary_path": getattr(health, "binary_path", None),
        "storage_dir": getattr(health, "storage_dir", ""),
        "spawn_attempted": getattr(health, "spawn_attempted", False),
        "message": getattr(health, "message", ""),
        "install_hint": getattr(health, "install_hint", ""),
        "download_url": getattr(health, "download_url", None),
    }


@router.get("/qdrant/health")
async def qdrant_health(_current_user_id: CurrentUserId) -> dict[str, object]:
    """Probe Qdrant and (if a local binary exists) auto-spawn it.

    Used by ``QdrantHealthCard`` on /match-elements to detect when the
    vector DB is down and surface a one-click install / refresh flow.
    Authentication is required so anonymous probes can't enumerate
    binary paths on disk.

    When the supervisor flips Qdrant from down→up (because the binary
    was already on disk and just needed to be spawned), we also drop
    the cached ``_qdrant_instance`` in ``app.core.vector`` so the rest
    of the backend's vector code paths (``/costs/vector/v3-status``,
    catalogue install, semantic search) recover without a process
    restart.
    """
    from app.config import get_settings
    from app.core.vector import reset_qdrant_client
    from app.modules.match_elements.qdrant_supervisor import ensure_qdrant_running

    settings = get_settings()
    health = ensure_qdrant_running(settings.qdrant_url, spawn_if_installed=True)
    if getattr(health, "reachable", False) and getattr(health, "spawn_attempted", False):
        # Spawning just succeeded → invalidate any cached "Qdrant not
        # reachable" state elsewhere in the process.
        reset_qdrant_client()
    return _qdrant_health_to_dict(health)


@router.post("/qdrant/install")
async def qdrant_install(_current_user_id: CurrentUserId) -> dict[str, object]:
    """Download the native Qdrant binary from GitHub Releases, then start it.

    Mirrors the converter-install pattern used by /takeoff and /bim:
    one-click, no Docker. The download is signed by Qdrant and stored
    under ``~/.openestimator/qdrant``. After install we re-probe so the
    response reflects the live binding state - front-end can branch on
    ``reachable`` to flip the card immediately.

    After a successful install we also drop the cached vector-client
    so ``/costs/vector/v3-status`` and the catalogue installer stop
    returning ``Qdrant not reachable`` for the rest of the process
    lifetime.
    """
    from app.config import get_settings
    from app.core.vector import reset_qdrant_client
    from app.modules.match_elements.qdrant_supervisor import (
        ensure_qdrant_running,
        install_qdrant_native,
    )

    settings = get_settings()
    try:
        install_qdrant_native(force=False)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    health = ensure_qdrant_running(settings.qdrant_url, spawn_if_installed=True)
    if getattr(health, "reachable", False):
        reset_qdrant_client()
    return _qdrant_health_to_dict(health)
