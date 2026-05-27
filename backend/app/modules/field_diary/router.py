# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Field Diary API routes (mounted at ``/api/v1/field-diary``).

Auth model:
    * ``POST /auth/request-magic-link/`` is **unauthenticated** — it
      provisions a magic-link + PIN for the supplied phone.
    * ``POST /auth/consume/`` is also unauthenticated — exchanges
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
    FieldMagicLinkConsume,
    FieldMagicLinkRequest,
    FieldMagicLinkRequestResponse,
    FieldModuleGrantCreate,
    FieldModuleGrantResponse,
    FieldSessionResponse,
)
from app.modules.field_diary.service import (
    FieldDiaryService,
)

router = APIRouter()
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
    module)`` tuple — callers should compare against the resource being
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

    Reads ``project_id`` from the live session (NOT from the URL —
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
    internal app). The user has no role + no permissions — access is
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
    silently scoped down to the session project — no IDOR window)."""
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
        # Hide existence — match HTTP 404 semantics used elsewhere.
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
    """Upload a file attachment (S3-style — stored as opaque bytes).

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
            detail="Unable to save attachment — storage error",
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
    """Operator-facing — grant a field user access to a module on a project.

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
