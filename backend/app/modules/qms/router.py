"""‌⁠‍QMS API routes (mount point: ``/api/v1/qms/``).

All endpoints require an authenticated user via :func:`get_current_user_payload`.
Per-project access is enforced via :func:`verify_project_access`.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.core.file_signature import (
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
)
from app.core.file_signature import (
    require as require_signature,
)
from app.core.permissions import permission_registry
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)

# Allow-list of magic-byte tokens we accept for QMS attachments. Mirrors
# the correspondence module's tightened list: PDFs, common images, and
# Office ZIP / OLE containers. XML/HTML deliberately excluded — these
# files are rendered back as clickable links and HTML has repeatedly
# been an XSS sink in audited modules.
_QMS_ALLOWED_ATTACHMENT_TYPES = frozenset({"pdf", "png", "jpeg", "gif", "webp", "zip", "ole"})

# Per-attachment storage root. Lazy-created on first upload so fresh
# installs that never use the feature don't ship the directory.
_QMS_ATTACHMENTS_DIR = Path("uploads/qms/attachments")
from app.modules.qms.schemas import (
    AuditCreate,
    AuditFindingCreate,
    AuditFindingRead,
    AuditRead,
    AuditUpdate,
    CalibrationCreate,
    CalibrationRead,
    CalibrationUpdate,
    COPQDetailed,
    COPQReport,
    FirstPassYieldReport,
    FPYTrendBucket,
    FPYTrendReport,
    InspectionCreate,
    InspectionRead,
    InspectionSignatureCreate,
    InspectionSignatureRead,
    InspectionUpdate,
    ITPItemCreate,
    ITPItemRead,
    ITPPlanCreate,
    ITPPlanRead,
    ITPTemplateCloneRequest,
    ITPTemplateCreate,
    ITPTemplateRead,
    ITPTemplateUpdate,
    ManagementReviewReport,
    ManagementReviewRequest,
    NCRActionCreate,
    NCRActionRead,
    NCRCreate,
    NCRRead,
    NCRUpdate,
    PunchItemCreate,
    PunchItemRead,
    PunchItemUpdate,
    SupplierAuditLink,
)
from app.modules.qms.service import QMSService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> QMSService:
    return QMSService(session)


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


# ── ITP Plans ─────────────────────────────────────────────────────────────


@router.get("/itp-plans", response_model=list[ITPPlanRead])
async def list_itp_plans(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern=r"^(draft|active|superseded|closed)$",
    ),
    _perm: None = Depends(RequirePermission("qms.itp.read")),
    service: QMSService = Depends(_get_service),
) -> list[ITPPlanRead]:
    """‌⁠‍List ITP plans for a project."""
    await verify_project_access(project_id, user_id, session)
    plans, _ = await service.repo.list_itp_plans(
        project_id,
        offset=offset,
        limit=limit,
        status=status_filter,
    )
    return [ITPPlanRead.model_validate(p) for p in plans]


@router.post("/itp-plans", response_model=ITPPlanRead, status_code=201)
async def create_itp_plan(
    data: ITPPlanCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.itp.write")),
    service: QMSService = Depends(_get_service),
) -> ITPPlanRead:
    await verify_project_access(data.project_id, user_id, session)
    try:
        plan = await service.create_itp_plan(data, user_id=user_id)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return ITPPlanRead.model_validate(plan)


@router.post("/itp-plans/{plan_id}/items", response_model=ITPItemRead, status_code=201)
async def add_itp_item(
    plan_id: uuid.UUID,
    data: ITPItemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.itp.write")),
    service: QMSService = Depends(_get_service),
) -> ITPItemRead:
    plan = await service.repo.get_itp_plan(plan_id)
    if plan is None:
        raise _not_found("ITP plan not found")
    await verify_project_access(plan.project_id, user_id, session)
    try:
        item = await service.add_itp_item(plan_id, data)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return ITPItemRead.model_validate(item)


@router.post("/itp-plans/{plan_id}/activate", response_model=ITPPlanRead)
async def activate_itp_plan(
    plan_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.itp.write")),
    service: QMSService = Depends(_get_service),
) -> ITPPlanRead:
    plan = await service.repo.get_itp_plan(plan_id)
    if plan is None:
        raise _not_found("ITP plan not found")
    await verify_project_access(plan.project_id, user_id, session)
    try:
        plan = await service.activate_itp_plan(plan_id)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return ITPPlanRead.model_validate(plan)


# ── Inspections ───────────────────────────────────────────────────────────


@router.get("/inspections", response_model=list[InspectionRead])
async def list_inspections(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern=r"^(scheduled|in_progress|passed|failed|conditional)$",
    ),
    _perm: None = Depends(RequirePermission("qms.inspection.read")),
    service: QMSService = Depends(_get_service),
) -> list[InspectionRead]:
    await verify_project_access(project_id, user_id, session)
    rows, _ = await service.repo.list_inspections(
        project_id,
        offset=offset,
        limit=limit,
        status=status_filter,
    )
    return [InspectionRead.model_validate(r) for r in rows]


@router.post("/inspections", response_model=InspectionRead, status_code=201)
async def schedule_inspection(
    data: InspectionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.inspection.write")),
    service: QMSService = Depends(_get_service),
) -> InspectionRead:
    await verify_project_access(data.project_id, user_id, session)
    try:
        inspection = await service.schedule_inspection(data, user_id=user_id)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return InspectionRead.model_validate(inspection)


@router.post(
    "/inspections/{inspection_id}/sign",
    response_model=InspectionSignatureRead,
    status_code=201,
)
async def sign_inspection(
    inspection_id: uuid.UUID,
    data: InspectionSignatureCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.inspection.sign")),
    service: QMSService = Depends(_get_service),
) -> InspectionSignatureRead:
    inspection = await service.repo.get_inspection(inspection_id)
    if inspection is None:
        raise _not_found("Inspection not found")
    await verify_project_access(inspection.project_id, user_id, session)
    try:
        sig = await service.add_signature(inspection_id, data)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return InspectionSignatureRead.model_validate(sig)


@router.post("/inspections/{inspection_id}/complete", response_model=InspectionRead)
async def complete_inspection(
    inspection_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    result: str = Query(..., pattern=r"^(passed|failed|conditional)$"),
    notes: str | None = Query(default=None, max_length=10000),
    _perm: None = Depends(RequirePermission("qms.inspection.write")),
    service: QMSService = Depends(_get_service),
) -> InspectionRead:
    inspection = await service.repo.get_inspection(inspection_id)
    if inspection is None:
        raise _not_found("Inspection not found")
    await verify_project_access(inspection.project_id, user_id, session)
    try:
        inspection = await service.complete_inspection(
            inspection_id,
            result=result,
            notes=notes,
        )
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return InspectionRead.model_validate(inspection)


@router.patch("/inspections/{inspection_id}", response_model=InspectionRead)
async def update_inspection(
    inspection_id: uuid.UUID,
    data: InspectionUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.inspection.write")),
    service: QMSService = Depends(_get_service),
) -> InspectionRead:
    inspection = await service.repo.get_inspection(inspection_id)
    if inspection is None:
        raise _not_found("Inspection not found")
    await verify_project_access(inspection.project_id, user_id, session)
    try:
        inspection = await service.update_inspection(inspection_id, data)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return InspectionRead.model_validate(inspection)


@router.get("/inspections/{inspection_id}", response_model=InspectionRead)
async def get_inspection(
    inspection_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.inspection.read")),
    service: QMSService = Depends(_get_service),
) -> InspectionRead:
    """‌⁠‍Fetch one inspection (IDOR-gated by project ownership)."""
    inspection = await service.repo.get_inspection(inspection_id)
    if inspection is None:
        raise _not_found("Inspection not found")
    # IDOR: 404 (not 403) on cross-project access to avoid UUID disclosure.
    await verify_project_access(inspection.project_id, user_id, session)
    return InspectionRead.model_validate(inspection)


@router.post(
    "/inspections/{inspection_id}/attachments",
    status_code=201,
)
async def upload_inspection_attachment(
    inspection_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("qms.inspection.write")),
    service: QMSService = Depends(_get_service),
) -> dict[str, object]:
    """‌⁠‍Upload an attachment to an inspection (magic-byte gated).

    The ``Content-Type`` header is fully attacker-controlled — magic-byte
    sniffing is the only thing that decides whether we keep the file. The
    IDOR check runs BEFORE we read the body so an unauthorised caller
    never causes us to learn whether the inspection exists.
    """
    inspection = await service.repo.get_inspection(inspection_id)
    if inspection is None:
        raise _not_found("Inspection not found")
    await verify_project_access(inspection.project_id, user_id, session)

    try:
        content = await file.read()
    except Exception as exc:
        logger.exception(
            "Unable to read attachment upload for inspection %s",
            inspection_id,
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

    try:
        require_signature(
            content[:SIGNATURE_BYTES_REQUIRED],
            _QMS_ALLOWED_ATTACHMENT_TYPES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    _QMS_ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "attachment.bin").suffix or ".bin"
    ext = ext.replace("/", "").replace("\\", "")
    safe_name = f"insp_{inspection_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = _QMS_ATTACHMENTS_DIR / safe_name
    try:
        filepath.write_bytes(content)
    except Exception as exc:
        logger.exception(
            "Unable to save attachment for inspection %s",
            inspection_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save attachment — storage error",
        ) from exc

    return {
        "inspection_id": str(inspection_id),
        "filename": safe_name,
        "original_filename": file.filename or "",
        "size_bytes": len(content),
        "relative_path": f"qms/attachments/{safe_name}",
    }


# ── NCRs ──────────────────────────────────────────────────────────────────


@router.get("/ncrs", response_model=list[NCRRead])
async def list_ncrs(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern=r"^(open|action_pending|verifying|closed|cancelled)$",
    ),
    severity: str | None = Query(
        default=None,
        pattern=r"^(minor|major|critical)$",
    ),
    _perm: None = Depends(RequirePermission("qms.ncr.read")),
    service: QMSService = Depends(_get_service),
) -> list[NCRRead]:
    await verify_project_access(project_id, user_id, session)
    rows, _ = await service.repo.list_ncrs(
        project_id,
        offset=offset,
        limit=limit,
        status=status_filter,
        severity=severity,
    )
    return [NCRRead.model_validate(r) for r in rows]


@router.post("/ncrs", response_model=NCRRead, status_code=201)
async def raise_ncr(
    data: NCRCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.ncr.write")),
    service: QMSService = Depends(_get_service),
) -> NCRRead:
    await verify_project_access(data.project_id, user_id, session)
    try:
        ncr = await service.raise_ncr(data, user_id=user_id)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return NCRRead.model_validate(ncr)


@router.patch("/ncrs/{ncr_id}", response_model=NCRRead)
async def update_ncr(
    ncr_id: uuid.UUID,
    data: NCRUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.ncr.write")),
    service: QMSService = Depends(_get_service),
) -> NCRRead:
    ncr = await service.repo.get_ncr(ncr_id)
    if ncr is None:
        raise _not_found("NCR not found")
    await verify_project_access(ncr.project_id, user_id, session)
    try:
        ncr = await service.update_ncr(ncr_id, data)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return NCRRead.model_validate(ncr)


@router.post("/ncrs/{ncr_id}/actions", response_model=NCRActionRead, status_code=201)
async def add_ncr_action(
    ncr_id: uuid.UUID,
    data: NCRActionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.ncr.write")),
    service: QMSService = Depends(_get_service),
) -> NCRActionRead:
    ncr = await service.repo.get_ncr(ncr_id)
    if ncr is None:
        raise _not_found("NCR not found")
    await verify_project_access(ncr.project_id, user_id, session)
    try:
        action = await service.assign_ncr_action(ncr_id, data)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return NCRActionRead.model_validate(action)


@router.post(
    "/ncrs/{ncr_id}/escalate-to-variation",
    response_model=NCRRead,
)
async def escalate_ncr_to_variation(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    variation_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("qms.ncr.escalate")),
    service: QMSService = Depends(_get_service),
) -> NCRRead:
    ncr = await service.repo.get_ncr(ncr_id)
    if ncr is None:
        raise _not_found("NCR not found")
    await verify_project_access(ncr.project_id, user_id, session)
    try:
        ncr = await service.escalate_ncr_to_variation(
            ncr_id,
            variation_id=variation_id,
        )
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return NCRRead.model_validate(ncr)


@router.post("/ncrs/{ncr_id}/close", response_model=NCRRead)
async def close_ncr(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.ncr.write")),
    service: QMSService = Depends(_get_service),
) -> NCRRead:
    ncr = await service.repo.get_ncr(ncr_id)
    if ncr is None:
        raise _not_found("NCR not found")
    await verify_project_access(ncr.project_id, user_id, session)
    try:
        ncr = await service.close_ncr(ncr_id)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return NCRRead.model_validate(ncr)


@router.get("/ncrs/{ncr_id}", response_model=NCRRead)
async def get_ncr(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.ncr.read")),
    service: QMSService = Depends(_get_service),
) -> NCRRead:
    """‌⁠‍Fetch one NCR (IDOR-gated by project ownership)."""
    ncr = await service.repo.get_ncr(ncr_id)
    if ncr is None:
        raise _not_found("NCR not found")
    await verify_project_access(ncr.project_id, user_id, session)
    return NCRRead.model_validate(ncr)


@router.post(
    "/ncrs/{ncr_id}/attachments",
    status_code=201,
)
async def upload_ncr_attachment(
    ncr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("qms.ncr.write")),
    service: QMSService = Depends(_get_service),
) -> dict[str, object]:
    """‌⁠‍Upload an attachment to an NCR (magic-byte gated, IDOR-gated)."""
    ncr = await service.repo.get_ncr(ncr_id)
    if ncr is None:
        raise _not_found("NCR not found")
    await verify_project_access(ncr.project_id, user_id, session)

    try:
        content = await file.read()
    except Exception as exc:
        logger.exception(
            "Unable to read attachment upload for NCR %s",
            ncr_id,
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

    try:
        require_signature(
            content[:SIGNATURE_BYTES_REQUIRED],
            _QMS_ALLOWED_ATTACHMENT_TYPES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    _QMS_ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "attachment.bin").suffix or ".bin"
    ext = ext.replace("/", "").replace("\\", "")
    safe_name = f"ncr_{ncr_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = _QMS_ATTACHMENTS_DIR / safe_name
    try:
        filepath.write_bytes(content)
    except Exception as exc:
        logger.exception(
            "Unable to save attachment for NCR %s",
            ncr_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save attachment — storage error",
        ) from exc

    return {
        "ncr_id": str(ncr_id),
        "filename": safe_name,
        "original_filename": file.filename or "",
        "size_bytes": len(content),
        "relative_path": f"qms/attachments/{safe_name}",
    }


# ── Punch items ───────────────────────────────────────────────────────────


@router.get("/punch-items", response_model=list[PunchItemRead])
async def list_punch_items(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern=r"^(open|assigned|in_progress|ready_for_inspection|closed|rejected)$",
    ),
    _perm: None = Depends(RequirePermission("qms.punch.read")),
    service: QMSService = Depends(_get_service),
) -> list[PunchItemRead]:
    await verify_project_access(project_id, user_id, session)
    rows, _ = await service.repo.list_punch(
        project_id,
        offset=offset,
        limit=limit,
        status=status_filter,
    )
    return [PunchItemRead.model_validate(r) for r in rows]


@router.post("/punch-items", response_model=PunchItemRead, status_code=201)
async def add_punch_item(
    data: PunchItemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.punch.write")),
    service: QMSService = Depends(_get_service),
) -> PunchItemRead:
    await verify_project_access(data.project_id, user_id, session)
    try:
        item = await service.add_punch_item(data, user_id=user_id)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return PunchItemRead.model_validate(item)


@router.patch("/punch-items/{punch_id}/assign", response_model=PunchItemRead)
async def assign_punch_item(
    punch_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    assigned_to: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("qms.punch.write")),
    service: QMSService = Depends(_get_service),
) -> PunchItemRead:
    punch = await service.repo.get_punch(punch_id)
    if punch is None:
        raise _not_found("Punch item not found")
    await verify_project_access(punch.project_id, user_id, session)
    try:
        punch = await service.assign_punch_item(punch_id, assigned_to=assigned_to)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return PunchItemRead.model_validate(punch)


@router.patch("/punch-items/{punch_id}", response_model=PunchItemRead)
async def update_punch_item(
    punch_id: uuid.UUID,
    data: PunchItemUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.punch.write")),
    service: QMSService = Depends(_get_service),
) -> PunchItemRead:
    punch = await service.repo.get_punch(punch_id)
    if punch is None:
        raise _not_found("Punch item not found")
    await verify_project_access(punch.project_id, user_id, session)
    try:
        punch = await service.update_punch_item(punch_id, data)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return PunchItemRead.model_validate(punch)


@router.post("/punch-items/{punch_id}/close", response_model=PunchItemRead)
async def close_punch_item(
    punch_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.punch.write")),
    service: QMSService = Depends(_get_service),
) -> PunchItemRead:
    punch = await service.repo.get_punch(punch_id)
    if punch is None:
        raise _not_found("Punch item not found")
    await verify_project_access(punch.project_id, user_id, session)
    try:
        punch = await service.close_punch_item(punch_id)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return PunchItemRead.model_validate(punch)


# ── Audits ────────────────────────────────────────────────────────────────


@router.get("/audits", response_model=list[AuditRead])
async def list_audits(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern=r"^(planned|in_progress|completed|closed)$",
    ),
    _perm: None = Depends(RequirePermission("qms.audit.read")),
    service: QMSService = Depends(_get_service),
) -> list[AuditRead]:
    await verify_project_access(project_id, user_id, session)
    rows, _ = await service.repo.list_audits(
        project_id,
        offset=offset,
        limit=limit,
        status=status_filter,
    )
    return [AuditRead.model_validate(r) for r in rows]


@router.post("/audits", response_model=AuditRead, status_code=201)
async def plan_audit(
    data: AuditCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.audit.write")),
    service: QMSService = Depends(_get_service),
) -> AuditRead:
    await verify_project_access(data.project_id, user_id, session)
    try:
        audit = await service.plan_audit(data)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return AuditRead.model_validate(audit)


@router.patch("/audits/{audit_id}", response_model=AuditRead)
async def update_audit(
    audit_id: uuid.UUID,
    data: AuditUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.audit.write")),
    service: QMSService = Depends(_get_service),
) -> AuditRead:
    audit = await service.repo.get_audit(audit_id)
    if audit is None:
        raise _not_found("Audit not found")
    await verify_project_access(audit.project_id, user_id, session)
    try:
        audit = await service.update_audit(audit_id, data)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return AuditRead.model_validate(audit)


@router.post(
    "/audits/{audit_id}/findings",
    response_model=AuditFindingRead,
    status_code=201,
)
async def add_audit_finding(
    audit_id: uuid.UUID,
    data: AuditFindingCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.audit.write")),
    service: QMSService = Depends(_get_service),
) -> AuditFindingRead:
    audit = await service.repo.get_audit(audit_id)
    if audit is None:
        raise _not_found("Audit not found")
    await verify_project_access(audit.project_id, user_id, session)
    try:
        finding = await service.add_finding(audit_id, data)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return AuditFindingRead.model_validate(finding)


@router.post("/audits/{audit_id}/complete", response_model=AuditRead)
async def complete_audit(
    audit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    overall_rating: int | None = Query(default=None, ge=1, le=5),
    _perm: None = Depends(RequirePermission("qms.audit.write")),
    service: QMSService = Depends(_get_service),
) -> AuditRead:
    audit = await service.repo.get_audit(audit_id)
    if audit is None:
        raise _not_found("Audit not found")
    await verify_project_access(audit.project_id, user_id, session)
    try:
        audit = await service.complete_audit(
            audit_id,
            overall_rating=overall_rating,
        )
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return AuditRead.model_validate(audit)


# ── Analytics ─────────────────────────────────────────────────────────────


@router.get("/reports/copq", response_model=COPQReport)
async def copq_report(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    currency: str = Query(default=""),
    _perm: None = Depends(RequirePermission("qms.ncr.read")),
    service: QMSService = Depends(_get_service),
) -> COPQReport:
    """‌⁠‍Cost of Poor Quality report for a project."""
    await verify_project_access(project_id, user_id, session)
    data = await service.compute_copq(project_id, currency=currency)
    return COPQReport(**data)


@router.get("/reports/first-pass-yield", response_model=FirstPassYieldReport)
async def first_pass_yield_report(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("qms.inspection.read")),
    service: QMSService = Depends(_get_service),
) -> FirstPassYieldReport:
    """First-pass yield (passed/total) report."""
    await verify_project_access(project_id, user_id, session)
    data = await service.compute_first_pass_yield(project_id)
    return FirstPassYieldReport(**data)


@router.get("/reports/fpy-trend", response_model=FPYTrendReport)
async def fpy_trend_report(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    period_days: int = Query(default=7, ge=1, le=90),
    periods: int = Query(default=12, ge=1, le=52),
    work_type: str | None = Query(default=None, max_length=100),
    _perm: None = Depends(RequirePermission("qms.report.read")),
    service: QMSService = Depends(_get_service),
) -> FPYTrendReport:
    """First-pass-yield trend bucketed by period."""
    await verify_project_access(project_id, user_id, session)
    try:
        data = await service.compute_fpy_trend(
            project_id,
            period_days=period_days,
            periods=periods,
            work_type=work_type,
        )
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return FPYTrendReport(
        project_id=data["project_id"],
        work_type=data["work_type"],
        period_days=data["period_days"],
        buckets=[FPYTrendBucket(**b) for b in data["buckets"]],
    )


@router.get("/reports/copq-detailed", response_model=COPQDetailed)
async def copq_detailed_report(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    rework_cost_per_punch: Decimal | None = Query(default=None, ge=0),
    warranty_cost: Decimal | None = Query(default=None, ge=0),
    delay_penalty_cost: Decimal | None = Query(default=None, ge=0),
    currency: str = Query(default=""),
    _perm: None = Depends(RequirePermission("qms.report.read")),
    service: QMSService = Depends(_get_service),
) -> COPQDetailed:
    """Detailed COPQ — NCRs + rework + warranty + delay penalty."""
    await verify_project_access(project_id, user_id, session)
    data = await service.compute_copq_detailed(
        project_id,
        rework_cost_per_punch=rework_cost_per_punch,
        warranty_cost=warranty_cost,
        delay_penalty_cost=delay_penalty_cost,
        currency=currency,
    )
    return COPQDetailed(**data)


@router.post(
    "/reports/management-review",
    response_model=ManagementReviewReport,
)
async def management_review_report(
    payload: ManagementReviewRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.report.read")),
    service: QMSService = Depends(_get_service),
) -> ManagementReviewReport:
    """ISO 9001:2015 §9.3 management-review report."""
    await verify_project_access(payload.project_id, user_id, session)
    try:
        data = await service.generate_management_review(
            payload.project_id,
            period_from=payload.period_from,
            period_to=payload.period_to,
            currency=payload.currency,
        )
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return ManagementReviewReport(**data)


# ── ITP Template library ──────────────────────────────────────────────────


@router.get("/itp-templates", response_model=list[ITPTemplateRead])
async def list_itp_templates(
    csi_division: str | None = Query(default=None, max_length=16),
    work_type: str | None = Query(default=None, max_length=100),
    active_only: bool = Query(default=True),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("qms.template.read")),
    service: QMSService = Depends(_get_service),
) -> list[ITPTemplateRead]:
    rows, _ = await service.repo.list_itp_templates(
        csi_division=csi_division,
        work_type=work_type,
        active_only=active_only,
        offset=offset,
        limit=limit,
    )
    return [ITPTemplateRead.model_validate(r) for r in rows]


@router.post("/itp-templates", response_model=ITPTemplateRead, status_code=201)
async def create_itp_template(
    data: ITPTemplateCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("qms.template.write")),
    service: QMSService = Depends(_get_service),
) -> ITPTemplateRead:
    try:
        tpl = await service.create_itp_template(data, user_id=user_id)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return ITPTemplateRead.model_validate(tpl)


@router.patch("/itp-templates/{tpl_id}", response_model=ITPTemplateRead)
async def update_itp_template(
    tpl_id: uuid.UUID,
    data: ITPTemplateUpdate,
    _perm: None = Depends(RequirePermission("qms.template.write")),
    service: QMSService = Depends(_get_service),
) -> ITPTemplateRead:
    try:
        tpl = await service.update_itp_template(tpl_id, data)
    except ValueError as exc:
        raise _not_found(str(exc)) from exc
    return ITPTemplateRead.model_validate(tpl)


@router.delete("/itp-templates/{tpl_id}", status_code=204)
async def delete_itp_template(
    tpl_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("qms.template.delete")),
    service: QMSService = Depends(_get_service),
) -> None:
    try:
        await service.delete_itp_template(tpl_id)
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


@router.post(
    "/itp-templates/{tpl_id}/clone",
    response_model=ITPPlanRead,
    status_code=201,
)
async def clone_itp_template(
    tpl_id: uuid.UUID,
    request: ITPTemplateCloneRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.itp.write")),
    service: QMSService = Depends(_get_service),
) -> ITPPlanRead:
    """Deep-clone a tenant-level ITP template into a project as a Plan."""
    await verify_project_access(request.project_id, user_id, session)
    try:
        plan = await service.clone_itp_template_to_project(
            tpl_id,
            request,
            user_id=user_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise _not_found(msg) from exc
        raise _bad(msg) from exc
    return ITPPlanRead.model_validate(plan)


# ── Calibration tracking ──────────────────────────────────────────────────


@router.get("/calibrations", response_model=list[CalibrationRead])
async def list_calibrations(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    instrument_type: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern=r"^(valid|expired|withdrawn)$",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("qms.calibration.read")),
    service: QMSService = Depends(_get_service),
) -> list[CalibrationRead]:
    """List calibrations.

    A ``project_id`` is required to prevent cross-tenant disclosure.
    Without it we cannot gate the response by project ownership — the
    Round-4 IDOR convention for list endpoints.
    """
    if project_id is None:
        raise _bad(
            "project_id is required (cross-project listing is restricted)",
        )
    await verify_project_access(project_id, user_id, session)
    rows, _ = await service.repo.list_calibrations(
        project_id=project_id,
        instrument_type=instrument_type,
        status=status_filter,
        offset=offset,
        limit=limit,
    )
    return [CalibrationRead.model_validate(r) for r in rows]


@router.post("/calibrations", response_model=CalibrationRead, status_code=201)
async def create_calibration(
    data: CalibrationCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("qms.calibration.write")),
    service: QMSService = Depends(_get_service),
) -> CalibrationRead:
    """‌⁠‍Create a calibration certificate.

    Two flavours:

    * **project-scoped** (``data.project_id`` set) — gated by per-project
      ownership (Round-5 IDOR).
    * **tenant-wide** (``data.project_id`` is None) — visible to every
      reader in the tenant and used for shared instruments (e.g. a
      single torque wrench rotating across projects). A plain EDITOR
      must NOT be able to mint these because they bypass the per-project
      access gate; require the dedicated ``qms.calibration.tenant_write``
      permission, which is MANAGER+ by default. This matches the way
      ``qms.template.write`` is also a MANAGER-level call.
    """
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    else:
        role = payload.get("role", "")
        permissions = payload.get("permissions", [])
        has_perm = (
            role == "admin"
            or "qms.calibration.tenant_write" in permissions
            or permission_registry.role_has_permission(
                role,
                "qms.calibration.tenant_write",
            )
        )
        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=("Tenant-wide calibration creation requires qms.calibration.tenant_write (MANAGER+)"),
            )
    try:
        cal = await service.create_calibration(data, user_id=user_id)
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return CalibrationRead.model_validate(cal)


@router.get("/calibrations/expiring", response_model=list[CalibrationRead])
async def list_expiring_calibrations(
    session: SessionDep,
    user_id: CurrentUserId,
    days: int = Query(default=30, ge=0, le=365),
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("qms.calibration.read")),
    service: QMSService = Depends(_get_service),
) -> list[CalibrationRead]:
    if project_id is None:
        raise _bad(
            "project_id is required (cross-project listing is restricted)",
        )
    await verify_project_access(project_id, user_id, session)
    rows = await service.expiring_calibrations(days=days, project_id=project_id)
    return [CalibrationRead.model_validate(r) for r in rows]


@router.get("/calibrations/{cal_id}", response_model=CalibrationRead)
async def get_calibration(
    cal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.calibration.read")),
    service: QMSService = Depends(_get_service),
) -> CalibrationRead:
    cal = await service.repo.get_calibration(cal_id)
    if cal is None:
        raise _not_found("Calibration not found")
    if cal.project_id is not None:
        await verify_project_access(cal.project_id, user_id, session)
    return CalibrationRead.model_validate(cal)


@router.patch("/calibrations/{cal_id}", response_model=CalibrationRead)
async def update_calibration(
    cal_id: uuid.UUID,
    data: CalibrationUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.calibration.write")),
    service: QMSService = Depends(_get_service),
) -> CalibrationRead:
    existing = await service.repo.get_calibration(cal_id)
    if existing is None:
        raise _not_found("Calibration not found")
    if existing.project_id is not None:
        await verify_project_access(existing.project_id, user_id, session)
    try:
        cal = await service.update_calibration(cal_id, data)
    except ValueError as exc:
        raise _not_found(str(exc)) from exc
    return CalibrationRead.model_validate(cal)


@router.delete("/calibrations/{cal_id}", status_code=204)
async def delete_calibration(
    cal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("qms.calibration.delete")),
    service: QMSService = Depends(_get_service),
) -> None:
    existing = await service.repo.get_calibration(cal_id)
    if existing is None:
        raise _not_found("Calibration not found")
    if existing.project_id is not None:
        await verify_project_access(existing.project_id, user_id, session)
    try:
        await service.delete_calibration(cal_id)
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


# ── Supplier audit linkage ────────────────────────────────────────────────


@router.post(
    "/audits/{audit_id}/link-subcontractor",
    response_model=SupplierAuditLink,
)
async def link_audit_to_subcontractor(
    audit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    subcontractor_id: uuid.UUID = Query(...),
    rating_delta: int = Query(default=0, ge=-5, le=5),
    _perm: None = Depends(RequirePermission("qms.audit.write")),
    service: QMSService = Depends(_get_service),
) -> SupplierAuditLink:
    """Link a supplier audit to a subcontractor (delta their quality rating)."""
    audit = await service.repo.get_audit(audit_id)
    if audit is None:
        raise _not_found("Audit not found")
    await verify_project_access(audit.project_id, user_id, session)
    try:
        await service.link_audit_to_subcontractor(
            audit_id,
            subcontractor_id=subcontractor_id,
            rating_delta=rating_delta,
        )
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    return SupplierAuditLink(
        audit_id=audit_id,
        subcontractor_id=subcontractor_id,
        rating_delta=rating_delta,
    )
