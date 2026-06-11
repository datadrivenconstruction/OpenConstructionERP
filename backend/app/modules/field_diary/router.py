# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Field Diary API routes (mounted at ``/api/v1/field-diary``).

Auth model:
    * ``POST /auth/request-magic-link/`` is **unauthenticated** - it
      provisions a magic-link + PIN for the supplied phone.
    * ``POST /auth/consume/`` is also unauthenticated - exchanges
      ``(token, pin)`` for a long-lived session token.
    * Every other endpoint depends on :class:`RequirePinPlusMagicLink`
      (validates ``Authorization: Bearer <session-token>`` AND
      ``X-Field-PIN`` header) AND :class:`RequireFieldModuleGrant`
      (dedicated permission stack, bypasses standard RBAC).
    * Admin grant endpoints (``POST /grants/``, ``DELETE /grants/...``)
      use the standard internal RBAC (``RequireRole("admin")``) because
      they are operator-facing.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.dependencies import (
    CurrentUserId,
    RequireRole,
    SessionDep,
)
from app.modules.field_diary.schemas import (
    MAX_ATTACHMENT_BYTES,
    DiaryActivityCreate,
    DiaryActivityResponse,
    DiaryAttachmentResponse,
    DiaryEntryCreate,
    DiaryEntryResponse,
    DiaryEntryUpdate,
    FieldCaptureResponse,
    FieldInspectionCreate,
    FieldMagicLinkConsume,
    FieldMagicLinkRequest,
    FieldMagicLinkRequestResponse,
    FieldModuleGrantCreate,
    FieldModuleGrantResponse,
    FieldPunchCreate,
    FieldSessionResponse,
    FieldSyncBatch,
    FieldSyncOpResponse,
    FieldTodayResponse,
)
from app.modules.field_diary.service import (
    FieldDiaryService,
    FieldSyncService,
    now_utc,
)

router = APIRouter(tags=["field_diary"])
logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

# On-disk storage for field-diary attachments (mirrors RFI layout).
ATTACHMENTS_DIR = Path("uploads/field_diary/attachments")


def _get_service(session: SessionDep) -> FieldDiaryService:
    return FieldDiaryService(session)


# ── Combined PIN + magic-link session dependency ──────────────────────────


class RequirePinPlusMagicLink:
    """Verify ``Authorization: Bearer <session-token>`` + ``X-Field-PIN``.

    Returns the live :class:`FieldSession` on success; raises 401 on any
    failure. The session is scoped to a single ``(user, project,
    module)`` tuple - callers should compare against the resource being
    accessed.
    """

    async def __call__(
        self,
        session: SessionDep,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(_bearer),
        ],
        x_field_pin: Annotated[str | None, Header(alias="X-Field-PIN")] = None,
    ):
        if credentials is None or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing field session token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not x_field_pin:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Field-PIN header",
            )
        svc = FieldDiaryService(session)
        sess = await svc.verify_session(credentials.credentials, x_field_pin)
        if sess is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired field session",
            )
        return sess


require_field_session = RequirePinPlusMagicLink()


async def _require_field_module_grant(
    request: Request,
    session: SessionDep,
    field_session=Depends(require_field_session),
):
    """Gate every diary endpoint on the dedicated module-grant table.

    Reads ``project_id`` from the live session (NOT from the URL -
    sessions are pinned to one project, no IDOR window).
    """
    svc = FieldDiaryService(session)
    ok = await svc.check_module_grant(
        field_session.user_id,
        field_session.project_id,
        field_session.module_key,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(f"No active field-module grant for module '{field_session.module_key}' on this project"),
        )
    return field_session


# ── Auth endpoints (unauthenticated) ──────────────────────────────────────


@router.post(
    "/auth/request-magic-link/",
    response_model=FieldMagicLinkRequestResponse,
    status_code=202,
)
async def request_magic_link(
    payload: FieldMagicLinkRequest,
    session: SessionDep,
    service: FieldDiaryService = Depends(_get_service),
) -> FieldMagicLinkRequestResponse:
    """Mint a PIN-gated magic link for a field worker.

    Provisions an ``oe_users_user`` row for the phone number if one
    doesn't already exist (field workers may have never logged into the
    internal app). The user has no role + no permissions - access is
    granted exclusively via the ``oe_field_module_grant`` table.

    Always returns 202 with ``accepted=true`` to avoid leaking whether
    the phone is provisioned. In dev/test (``APP_DEBUG=true``) the
    plaintext token + PIN are returned so the consume flow can be
    driven without an SMS provider.
    """
    from sqlalchemy import select

    from app.config import get_settings
    from app.modules.users.models import User

    # Find-or-provision the user by phone-derived synthetic email so the
    # FK target exists. A dedicated ``phone`` column on ``oe_users_user``
    # is a follow-up; this MVP encodes it in the email local-part.
    synth_email = f"field+{payload.phone.lstrip('+')}@field.local"
    result = await session.execute(select(User).where(User.email == synth_email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=synth_email,
            hashed_password="!FIELD_NO_PASSWORD!",
            full_name=f"Field worker {payload.phone}",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)

    link, plain_token, plain_pin = await service.request_magic_link(
        phone=payload.phone,
        project_id=payload.project_id,
        module_key=payload.module_key,
        user_id=user.id,
    )

    settings = get_settings()
    if getattr(settings, "app_debug", False):
        return FieldMagicLinkRequestResponse(
            accepted=True,
            dev_token=plain_token,
            dev_pin=plain_pin,
            expires_at=link.expires_at,
        )
    return FieldMagicLinkRequestResponse(accepted=True)


@router.post(
    "/auth/consume/",
    response_model=FieldSessionResponse,
    status_code=200,
)
async def consume_magic_link(
    payload: FieldMagicLinkConsume,
    service: FieldDiaryService = Depends(_get_service),
) -> FieldSessionResponse:
    sess, plain = await service.consume_magic_link(
        token=payload.token,
        pin=payload.pin,
    )
    return FieldSessionResponse(
        session_token=plain,
        expires_at=sess.expires_at,
        project_id=sess.project_id,
        user_id=sess.user_id,
        module_key=sess.module_key,
    )


# ── Diary entries ─────────────────────────────────────────────────────────


@router.get("/entries/", response_model=list[DiaryEntryResponse])
async def list_entries(
    field_session=Depends(_require_field_module_grant),
    project_id: uuid.UUID | None = Query(default=None),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: FieldDiaryService = Depends(_get_service),
) -> list[DiaryEntryResponse]:
    """List entries for the session's project (cross-project queries are
    silently scoped down to the session project - no IDOR window)."""
    target_project = field_session.project_id
    if project_id is not None and project_id != target_project:
        # Session is pinned to one project; reject mismatching ?project_id=.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session is scoped to a different project",
        )
    items = await service.list_diary_entries(
        target_project,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )
    return [DiaryEntryResponse.model_validate(i) for i in items]


@router.post("/entries/", response_model=DiaryEntryResponse, status_code=201)
async def create_entry(
    payload: DiaryEntryCreate,
    field_session=Depends(_require_field_module_grant),
    service: FieldDiaryService = Depends(_get_service),
) -> DiaryEntryResponse:
    if payload.project_id != field_session.project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session is scoped to a different project",
        )
    entry = await service.create_diary_entry(
        payload,
        author_id=field_session.user_id,
    )
    return DiaryEntryResponse.model_validate(entry)


@router.get("/entries/{entry_id}/", response_model=DiaryEntryResponse)
async def get_entry(
    entry_id: uuid.UUID,
    field_session=Depends(_require_field_module_grant),
    service: FieldDiaryService = Depends(_get_service),
) -> DiaryEntryResponse:
    entry = await service.get_diary_entry(entry_id)
    if entry.project_id != field_session.project_id:
        # Hide existence - match HTTP 404 semantics used elsewhere.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diary entry not found",
        )
    return DiaryEntryResponse.model_validate(entry)


@router.patch("/entries/{entry_id}/", response_model=DiaryEntryResponse)
async def update_entry(
    entry_id: uuid.UUID,
    payload: DiaryEntryUpdate,
    field_session=Depends(_require_field_module_grant),
    service: FieldDiaryService = Depends(_get_service),
) -> DiaryEntryResponse:
    entry = await service.get_diary_entry(entry_id)
    if entry.project_id != field_session.project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diary entry not found",
        )
    entry = await service.update_diary_entry(entry_id, payload)
    return DiaryEntryResponse.model_validate(entry)


@router.post(
    "/entries/{entry_id}/submit/",
    response_model=DiaryEntryResponse,
)
async def submit_entry(
    entry_id: uuid.UUID,
    field_session=Depends(_require_field_module_grant),
    service: FieldDiaryService = Depends(_get_service),
) -> DiaryEntryResponse:
    entry = await service.get_diary_entry(entry_id)
    if entry.project_id != field_session.project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diary entry not found",
        )
    entry = await service.submit_diary_entry(entry_id)
    return DiaryEntryResponse.model_validate(entry)


@router.post(
    "/entries/{entry_id}/activities/",
    response_model=DiaryActivityResponse,
    status_code=201,
)
async def append_activity(
    entry_id: uuid.UUID,
    payload: DiaryActivityCreate,
    field_session=Depends(_require_field_module_grant),
    service: FieldDiaryService = Depends(_get_service),
) -> DiaryActivityResponse:
    entry = await service.get_diary_entry(entry_id)
    if entry.project_id != field_session.project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diary entry not found",
        )
    activity = await service.append_activity(entry_id, payload)
    return DiaryActivityResponse.model_validate(activity)


@router.post(
    "/entries/by-date/{entry_date}/activities/",
    response_model=DiaryActivityResponse,
    status_code=201,
)
async def append_activity_by_date(
    entry_date: str,
    payload: DiaryActivityCreate,
    field_session=Depends(_require_field_module_grant),
    service: FieldDiaryService = Depends(_get_service),
) -> DiaryActivityResponse:
    """Append a time activity to the session author's diary entry for a date.

    Find-or-creates the ``(project, author, date)`` entry first, so an offline
    capture replayed from the field shell needs no server entry id. The date is
    validated as ISO ``YYYY-MM-DD``; the project + author come from the live
    session (no IDOR window - the URL carries no project).
    """
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", entry_date):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="entry_date must be ISO YYYY-MM-DD",
        )
    activity = await service.append_activity_by_date(
        project_id=field_session.project_id,
        author_id=field_session.user_id,
        entry_date=entry_date,
        data=payload,
        op_kind="field.diary.activity",
    )
    return DiaryActivityResponse.model_validate(activity)


@router.post(
    "/entries/{entry_id}/attachments/",
    response_model=DiaryAttachmentResponse,
    status_code=201,
)
async def upload_attachment(
    entry_id: uuid.UUID,
    file: UploadFile = File(...),
    field_session=Depends(_require_field_module_grant),
    service: FieldDiaryService = Depends(_get_service),
) -> DiaryAttachmentResponse:
    """Upload a file attachment (S3-style - stored as opaque bytes).

    Hard cap of 25 MB. The filename supplied by the client is kept as
    metadata only; the on-disk storage key is server-derived to defuse
    path-traversal attempts.
    """
    entry = await service.get_diary_entry(entry_id)
    if entry.project_id != field_session.project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diary entry not found",
        )

    try:
        content = await file.read()
    except Exception as exc:
        logger.exception(
            "Unable to read field-diary attachment upload",
            extra={"entry_id": str(entry_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read uploaded attachment",
        ) from exc

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"Attachment exceeds {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB cap"),
        )

    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "attachment.bin").suffix or ".bin"
    ext = ext.replace("/", "").replace("\\", "")
    safe_name = f"{entry_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = ATTACHMENTS_DIR / safe_name
    try:
        filepath.write_bytes(content)
    except Exception as exc:
        logger.exception(
            "Unable to save field-diary attachment",
            extra={"entry_id": str(entry_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save attachment - storage error",
        ) from exc

    relative_path = f"field_diary/attachments/{safe_name}"
    attachment = await service.register_attachment(
        entry_id,
        filename=file.filename or safe_name,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        storage_key=relative_path,
        uploaded_by=field_session.user_id,
    )
    return DiaryAttachmentResponse.model_validate(attachment)


# ── Field Today screen ─────────────────────────────────────────────────────


@router.get("/today/", response_model=FieldTodayResponse)
async def field_today(
    session: SessionDep,
    field_session=Depends(_require_field_module_grant),
) -> FieldTodayResponse:
    """Single round-trip seed for the offline Today screen.

    Returns the session author's diary entry for today, open punch/inspection
    counts and the top open punch items, all scoped to the session project. The
    client caches this as its offline seed; ``server_time`` lets it reconcile
    clock skew against the device's local capture time.
    """
    import datetime as _dt

    from app.modules.field_diary.service import FieldDiaryService as _FDS
    from app.modules.inspections.repository import InspectionRepository
    from app.modules.punchlist.repository import PunchListRepository

    project_id = field_session.project_id
    today_iso = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")

    fds = _FDS(session)
    entries = await fds.list_diary_entries(
        project_id,
        date_from=today_iso,
        date_to=today_iso,
        limit=50,
    )
    mine = next((e for e in entries if e.author_id == field_session.user_id), None)

    punch_repo = PunchListRepository(session)
    open_punch, open_punch_total = await punch_repo.list_for_project(
        project_id,
        offset=0,
        limit=5,
        status="open",
    )
    insp_repo = InspectionRepository(session)
    _open_insp, open_insp_total = await insp_repo.list_for_project(
        project_id,
        offset=0,
        limit=1,
        status="scheduled",
    )

    return FieldTodayResponse(
        project_id=project_id,
        diary=DiaryEntryResponse.model_validate(mine) if mine is not None else None,
        open_punch_count=open_punch_total,
        top_punch=[
            {
                "id": str(p.id),
                "title": p.title,
                "priority": p.priority,
                "status": p.status,
            }
            for p in open_punch
        ],
        open_inspection_count=open_insp_total,
        server_time=now_utc().isoformat(),
    )


# ── Field capture (cross-module, idempotent) ───────────────────────────────


@router.post("/capture/punch/", response_model=FieldCaptureResponse, status_code=201)
async def capture_punch(
    payload: FieldPunchCreate,
    session: SessionDep,
    field_session=Depends(_require_field_module_grant),
) -> FieldCaptureResponse:
    """Create a punch item from a field capture, scoped to the session project.

    Idempotent on ``client_op_id``: a replayed op returns the original punch id
    (HTTP 200) instead of creating a second row.
    """
    svc = FieldSyncService(session)
    return await svc.capture_punch(field_session, payload)


@router.post("/capture/inspection/", response_model=FieldCaptureResponse, status_code=201)
async def capture_inspection(
    payload: FieldInspectionCreate,
    session: SessionDep,
    field_session=Depends(_require_field_module_grant),
) -> FieldCaptureResponse:
    """Create an inspection from a field capture, scoped to the session project.

    Idempotent on ``client_op_id``. The created inspection feeds the existing
    desktop ``create-defect`` / ``create-ncr`` bridges with no new bridge code.
    """
    svc = FieldSyncService(session)
    return await svc.capture_inspection(field_session, payload)


@router.post("/capture/photo/", response_model=FieldCaptureResponse, status_code=201)
async def capture_photo(
    session: SessionDep,
    field_session=Depends(_require_field_module_grant),
    file: UploadFile = File(...),
    punch_item_id: Annotated[uuid.UUID | None, Header(alias="X-Punch-Item-Id")] = None,
    client_op_id: Annotated[str | None, Header(alias="X-Client-Op-Id")] = None,
) -> FieldCaptureResponse:
    """Attach a photo to a field-captured punch item.

    The image is magic-byte gated against the photo allow-list (the request
    Content-Type is attacker-controlled), stored under ``uploads/punchlist/
    photos`` and cross-linked into the Documents hub, reusing the punchlist
    photo path. The target punch item must belong to the session project (a
    cross-project ``punch_item_id`` resolves to 404, not 403).
    """
    from app.core.file_signature import (
        ALLOWED_PHOTO_TYPES,
        SIGNATURE_BYTES_REQUIRED,
        FileSignatureMismatch,
        mime_for_signature,
    )
    from app.core.file_signature import require as require_signature
    from app.modules.punchlist.service import PunchListService

    if punch_item_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Punch-Item-Id header is required for a field photo capture",
        )
    if not client_op_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Client-Op-Id header is required for a field photo capture",
        )

    punch_svc = PunchListService(session)
    item = await punch_svc.get_item(punch_item_id)
    if item.project_id != field_session.project_id:
        # Hide existence - IDOR returns 404 for cross-project ids.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Punch item not found",
        )

    try:
        content = await file.read()
    except Exception as exc:
        logger.exception("Unable to read field photo capture for punch %s", punch_item_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read uploaded photo",
        ) from exc

    try:
        detected = require_signature(
            content[:SIGNATURE_BYTES_REQUIRED],
            ALLOWED_PHOTO_TYPES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    safe_mime = mime_for_signature(detected)

    photos_dir = Path("uploads/punchlist/photos")
    photos_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "photo.jpg").suffix or ".jpg"
    ext = ext.replace("/", "").replace("\\", "")
    safe_name = f"{punch_item_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = photos_dir / safe_name
    try:
        filepath.write_bytes(content)
    except Exception as exc:
        logger.exception("Unable to save field photo for punch %s", punch_item_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save photo - storage error",
        ) from exc

    await punch_svc.add_photo(punch_item_id, f"punchlist/photos/{safe_name}")

    # Cross-link into the Documents hub (best-effort - the photo is persisted).
    try:
        from app.modules.documents.models import Document

        doc = Document(
            project_id=item.project_id,
            name=safe_name,
            description=f"Field punch photo for item {punch_item_id}",
            category="photo",
            file_size=len(content),
            mime_type=safe_mime,
            file_path=str(filepath),
            version=1,
            uploaded_by=str(field_session.user_id),
            tags=["punchlist", "photo", "field"],
        )
        session.add(doc)
        await session.flush()
    except Exception:
        logger.exception("Failed to cross-link field punch photo to Documents hub")

    return FieldCaptureResponse(
        client_op_id=client_op_id,
        status="applied",
        target_module="punchlist",
        target_kind="punch_photo",
        result_id=punch_item_id,
        http_status=201,
    )


# ── Sync (bulk drain + op history) ─────────────────────────────────────────


@router.post("/sync/batch/", response_model=list[FieldCaptureResponse])
async def sync_batch(
    payload: FieldSyncBatch,
    session: SessionDep,
    field_session=Depends(_require_field_module_grant),
) -> list[FieldCaptureResponse]:
    """Bulk-drain up to 50 queued ops through the idempotency ledger.

    The client may replay one op at a time against the ``capture/*`` endpoints
    or batch them here; both paths go through the same per-``client_op_id``
    dedup, so a batch that overlaps a prior single replay never double-applies.
    """
    svc = FieldSyncService(session)
    results: list[FieldCaptureResponse] = []
    # The offline queue often serializes the whole op, so payload can carry the
    # same envelope keys we pass explicitly below. Spreading both would raise
    # "got multiple values for keyword argument" and 500 the entire batch, so
    # drop the envelope keys from payload before spreading.
    _envelope_keys = {
        "client_op_id",
        "captured_at",
        "lat",
        "lon",
        "accuracy_m",
        "device_hint",
        "target_kind",
    }
    for op in payload.ops:
        extra = {k: v for k, v in (op.payload or {}).items() if k not in _envelope_keys}
        if op.target_kind == "punch_item":
            body = FieldPunchCreate(
                client_op_id=op.client_op_id,
                captured_at=op.captured_at,
                lat=op.lat,
                lon=op.lon,
                accuracy_m=op.accuracy_m,
                device_hint=op.device_hint,
                **extra,
            )
            results.append(await svc.capture_punch(field_session, body))
        elif op.target_kind == "inspection":
            body = FieldInspectionCreate(
                client_op_id=op.client_op_id,
                captured_at=op.captured_at,
                lat=op.lat,
                lon=op.lon,
                accuracy_m=op.accuracy_m,
                device_hint=op.device_hint,
                **extra,
            )
            results.append(await svc.capture_inspection(field_session, body))
    return results


@router.get("/sync/ops/", response_model=list[FieldSyncOpResponse])
async def sync_ops(
    session: SessionDep,
    field_session=Depends(_require_field_module_grant),
    since: str | None = Query(default=None),
) -> list[FieldSyncOpResponse]:
    """The worker's own applied-op history (newest first), scoped to the session.

    Drives the "what synced / what conflicted" review surface. ``since`` is an
    optional ISO timestamp filter.
    """
    svc = FieldSyncService(session)
    ops = await svc.list_ops(field_session, since=since)
    return [FieldSyncOpResponse.model_validate(o) for o in ops]


# ── Admin grant endpoints (internal RBAC) ─────────────────────────────────


@router.post(
    "/grants/",
    response_model=FieldModuleGrantResponse,
    status_code=201,
    dependencies=[Depends(RequireRole("admin"))],
)
async def create_grant(
    payload: FieldModuleGrantCreate,
    user_id: CurrentUserId,
    service: FieldDiaryService = Depends(_get_service),
) -> FieldModuleGrantResponse:
    """Operator-facing - grant a field user access to a module on a project.

    Gated by standard RBAC (``RequireRole("admin")``) because it modifies
    permissions; the data path it gates (the field worker's requests)
    uses the dedicated grant check.
    """
    grant = await service.create_grant(payload, granted_by=uuid.UUID(user_id))
    return FieldModuleGrantResponse.model_validate(grant)


@router.delete(
    "/grants/{grant_id}/",
    status_code=204,
    dependencies=[Depends(RequireRole("admin"))],
)
async def revoke_grant(
    grant_id: uuid.UUID,
    service: FieldDiaryService = Depends(_get_service),
) -> None:
    await service.revoke_grant(grant_id)
