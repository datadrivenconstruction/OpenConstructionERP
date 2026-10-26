# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Defects-liability API routes (mounted at ``/api/v1/defects-liability``).

Post-handover warranty and defects-liability-period governance: the per-project
register of warranty / DLP entries, the defect notices raised against each while
its period runs, and the derived register rollup and retention-release-readiness
view (which entries have finished their DLP clean and are clear for the final
retention money).

Every endpoint is scoped to a project in its path and gated twice, exactly like
the sibling modules: a ``RequirePermission`` dependency enforces the read/write
permission, and ``verify_project_access`` (which raises 404 on both "missing" and
"denied") is awaited as the first line of every handler so a stranger can never
read or mutate another project's defects-liability data. Any referenced
``warranty_id`` is additionally re-checked in the service layer against the same
project, so a defect can never be attached across projects.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.defects_liability.register import (
    ALL_DEFECT_SEVERITIES,
    ALL_DEFECT_STATUSES,
    ALL_WARRANTY_STATUSES,
    ALL_WARRANTY_TYPES,
)
from app.modules.defects_liability.schemas import (
    DefectCreate,
    DefectResponse,
    DefectUpdate,
    DlpRegisterResponse,
    LimitationReviewResponse,
    RetentionReleaseReadinessResponse,
    WarrantyCreate,
    WarrantyResponse,
    WarrantyUpdate,
)
from app.modules.defects_liability.service import DefectsLiabilityService

router = APIRouter(tags=["defects-liability"])

#: Same cap as the documents photo gallery the file is handed to.
_MAX_DEFECT_PHOTO_BYTES = 50 * 1024 * 1024

_READ = Depends(RequirePermission("defects_liability.read"))
_WRITE = Depends(RequirePermission("defects_liability.write"))


def _get_service(session: SessionDep) -> DefectsLiabilityService:
    return DefectsLiabilityService(session)


def _validate_filter(value: str | None, allowed: tuple[str, ...], field: str) -> str | None:
    """Reject an out-of-vocabulary filter value with 422, pass ``None`` through."""
    if value is None:
        return None
    if value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid {field}: {value!r}",
        )
    return value


def _parse_as_of(value: str | None) -> date | None:
    """Parse an optional ``as_of`` ISO date query param (422 on garbage)."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid as_of date (expected YYYY-MM-DD): {value!r}",
        ) from exc


# -- Warranties -------------------------------------------------------------


@router.post(
    "/projects/{project_id}/warranties",
    response_model=WarrantyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_warranty(
    project_id: uuid.UUID,
    payload: WarrantyCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> WarrantyResponse:
    """Create a warranty / DLP entry on a project."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.create_warranty(project_id, payload, created_by=user_id)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/warranties",
    response_model=list[WarrantyResponse],
    dependencies=[_READ],
)
async def list_warranties(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    warranty_status: str | None = Query(default=None, alias="status"),
    subcontractor_id: uuid.UUID | None = Query(default=None),
    work_package: str | None = Query(default=None),
    warranty_type: str | None = Query(default=None),
) -> list[WarrantyResponse]:
    """List a project's warranty / DLP entries, optionally filtered by status / subcontractor / package / type."""
    await verify_project_access(project_id, user_id, session)
    warranty_status = _validate_filter(warranty_status, ALL_WARRANTY_STATUSES, "status")
    warranty_type = _validate_filter(warranty_type, ALL_WARRANTY_TYPES, "warranty_type")
    service = _get_service(session)
    return await service.list_warranties(  # type: ignore[return-value]
        project_id,
        warranty_status=warranty_status,
        subcontractor_id=subcontractor_id,
        work_package=work_package,
        warranty_type=warranty_type,
    )


@router.get(
    "/projects/{project_id}/warranties/{warranty_id}",
    response_model=WarrantyResponse,
    dependencies=[_READ],
)
async def get_warranty(
    project_id: uuid.UUID,
    warranty_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> WarrantyResponse:
    """Get one warranty / DLP entry, scoped to the project (404 if missing/foreign)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.require_warranty(project_id, warranty_id)  # type: ignore[return-value]


@router.patch(
    "/projects/{project_id}/warranties/{warranty_id}",
    response_model=WarrantyResponse,
    dependencies=[_WRITE],
)
async def update_warranty(
    project_id: uuid.UUID,
    warranty_id: uuid.UUID,
    payload: WarrantyUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> WarrantyResponse:
    """Patch a warranty / DLP entry (only provided fields change)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.update_warranty(project_id, warranty_id, payload)  # type: ignore[return-value]


@router.delete(
    "/projects/{project_id}/warranties/{warranty_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_WRITE],
)
async def delete_warranty(
    project_id: uuid.UUID,
    warranty_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Delete a warranty / DLP entry and its defects (404 if missing/foreign)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    await service.delete_warranty(project_id, warranty_id)


# -- Defects ----------------------------------------------------------------


@router.post(
    "/projects/{project_id}/warranties/{warranty_id}/defects",
    response_model=DefectResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_defect(
    project_id: uuid.UUID,
    warranty_id: uuid.UUID,
    payload: DefectCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> DefectResponse:
    """Raise a defect against a warranty (service re-verifies the warranty in-project)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.create_defect(project_id, warranty_id, payload, created_by=user_id)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/defects",
    response_model=list[DefectResponse],
    dependencies=[_READ],
)
async def list_defects(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    warranty_id: uuid.UUID | None = Query(default=None),
    defect_status: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
) -> list[DefectResponse]:
    """List a project's defects, optionally filtered by warranty / status / severity."""
    await verify_project_access(project_id, user_id, session)
    defect_status = _validate_filter(defect_status, ALL_DEFECT_STATUSES, "status")
    severity = _validate_filter(severity, ALL_DEFECT_SEVERITIES, "severity")
    service = _get_service(session)
    return await service.list_defects(  # type: ignore[return-value]
        project_id,
        warranty_id=warranty_id,
        defect_status=defect_status,
        severity=severity,
    )


@router.patch(
    "/projects/{project_id}/defects/{defect_id}",
    response_model=DefectResponse,
    dependencies=[_WRITE],
)
async def update_defect(
    project_id: uuid.UUID,
    defect_id: uuid.UUID,
    payload: DefectUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> DefectResponse:
    """Patch (or close) a defect (only provided fields change)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.update_defect(project_id, defect_id, payload)  # type: ignore[return-value]


# -- Derived register views -------------------------------------------------


@router.get(
    "/projects/{project_id}/register",
    response_model=DlpRegisterResponse,
    dependencies=[_READ],
)
async def get_register(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    as_of: str | None = Query(default=None, description="As-of date YYYY-MM-DD (defaults to today)"),
    horizon_days: int = Query(default=30, ge=0, le=3650, description="Days ahead an entry counts as expiring"),
) -> DlpRegisterResponse:
    """Full defects-liability register rollup: counts, expiry, defect load, health, readiness."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.build_register(  # type: ignore[return-value]
        project_id,
        as_of=_parse_as_of(as_of),
        horizon_days=horizon_days,
    )


@router.get(
    "/projects/{project_id}/retention-release-readiness",
    response_model=RetentionReleaseReadinessResponse,
    dependencies=[_READ],
)
async def get_retention_release_readiness(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    as_of: str | None = Query(default=None, description="As-of date YYYY-MM-DD (defaults to today)"),
) -> RetentionReleaseReadinessResponse:
    """Entries whose DLP has ended with no outstanding defects, clear for final retention release."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.get_retention_release_readiness(project_id, as_of=_parse_as_of(as_of))  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/limitation-review",
    response_model=LimitationReviewResponse,
    dependencies=[_READ],
)
async def get_limitation_review(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> LimitationReviewResponse:
    """Where a recorded warranty period disagrees with the legal regime it names.

    Reviews only the entries that named a regime. A project whose entries never
    named one reviews nothing and reports nothing, which is why the screen only
    asks for this once a regime is actually in use.
    """
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.review_limitation_periods(project_id)  # type: ignore[return-value]


# -- Photo evidence ---------------------------------------------------------


@router.post(
    "/projects/{project_id}/defects/{defect_id}/photos",
    response_model=DefectResponse,
    dependencies=[_WRITE],
)
async def upload_defect_photo(
    project_id: uuid.UUID,
    defect_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    capture_lat: float | None = Form(default=None),
    capture_lon: float | None = Form(default=None),
    capture_accuracy_m: float | None = Form(default=None),
    capture_altitude_m: float | None = Form(default=None),
    captured_at: str | None = Form(default=None),
    capture_heading_deg: float | None = Form(default=None),
    capture_pitch_deg: float | None = Form(default=None),
    capture_roll_deg: float | None = Form(default=None),
) -> DefectResponse:
    """Attach a photo with capture evidence to a defect.

    The file goes through the documents photo gallery (category ``defect``),
    which owns the size and pixel caps, the magic-byte check, thumbnails and
    the GPS privacy default. The defect keeps the gallery photo id and an
    evidence record: SHA-256 of the stored file, the browser's location fix
    with its accuracy, capture time and device orientation, and the EXIF read
    from the original upload.
    """
    from app.core.photo_evidence import (
        build_evidence_record,
        parse_device_capture,
        read_exif_evidence,
        sha256_hex,
    )
    from app.modules.documents.service import PhotoService

    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    defect = await service.require_defect(project_id, defect_id)

    original = await file.read(_MAX_DEFECT_PHOTO_BYTES + 1)
    if len(original) > _MAX_DEFECT_PHOTO_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Photo too large")
    await file.seek(0)
    exif = read_exif_evidence(original)
    device = parse_device_capture(
        lat=capture_lat,
        lon=capture_lon,
        accuracy_m=capture_accuracy_m,
        altitude_m=capture_altitude_m,
        captured_at=captured_at,
        heading_deg=capture_heading_deg,
        pitch_deg=capture_pitch_deg,
        roll_deg=capture_roll_deg,
    )
    located = device is not None and device.location_valid()
    photo = await PhotoService(session).upload_photo(
        project_id=project_id,
        file=file,
        category="defect",
        user_id=str(user_id),
        caption=caption or defect.reference,
        gps_lat=device.lat if located and device else None,
        gps_lon=device.lon if located and device else None,
        tags=["defects_liability", defect.reference],
        taken_at=device.captured_at if device else None,
    )
    stored = await _read_stored_photo(photo.file_path)
    original_sha = sha256_hex(original)
    evidence = build_evidence_record(
        stored if stored is not None else original,
        path=f"photo:{photo.id}",
        device=device,
        exif=exif,
        uploaded_by=str(user_id),
        original_sha256=original_sha,
    )
    photo.metadata_ = {**(photo.metadata_ or {}), "evidence": evidence, "defect_id": str(defect_id)}
    entry = {
        "photo_id": str(photo.id),
        "document_id": photo.document_id,
        "filename": photo.filename,
        "caption": photo.caption,
        "evidence": evidence,
    }
    return await service.add_photo(project_id, defect_id, entry)  # type: ignore[return-value]


@router.delete(
    "/projects/{project_id}/defects/{defect_id}/photos/{index}",
    response_model=DefectResponse,
    dependencies=[_WRITE],
)
async def remove_defect_photo(
    project_id: uuid.UUID,
    defect_id: uuid.UUID,
    index: int,
    user_id: CurrentUserId,
    session: SessionDep,
) -> DefectResponse:
    """Detach a photo from a defect. The gallery photo itself stays in Documents."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    await service.remove_photo(project_id, defect_id, index)
    return await service.require_defect(project_id, defect_id)  # type: ignore[return-value]


async def _read_stored_photo(file_path: str | None) -> bytes | None:
    """Bytes of the stored gallery file, for the evidence hash (``None`` if unreadable)."""
    import asyncio
    from pathlib import Path

    if not file_path:
        return None
    try:
        return await asyncio.to_thread(Path(file_path).read_bytes)
    except OSError:
        return None


@router.get("/projects/{project_id}/defects-evidence-check", dependencies=[_READ])
async def defects_evidence_check(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Run the defect photo-evidence rule set over the project's defects."""
    from app.core.i18n import get_locale
    from app.core.validation.engine import validation_engine
    from app.modules.defects_liability.validators import DEFECT_EVIDENCE_RULE_SET

    await verify_project_access(project_id, user_id, session)
    defects = await _get_service(session).list_defects(project_id)
    data = {
        "defects": [
            {"id": str(d.id), "reference": d.reference, "status": d.status, "photos": list(d.photos or [])}
            for d in defects
        ]
    }
    report = await validation_engine.validate(
        data=data,
        rule_sets=[DEFECT_EVIDENCE_RULE_SET],
        target_type="defects_liability",
        target_id=str(project_id),
        project_id=str(project_id),
        metadata={"locale": get_locale()},
    )
    failed = [r for r in report.results if not r.passed]
    return {
        "status": "errors" if report.errors else "warnings" if report.warnings else "passed",
        "checked": len(report.results),
        "results": [
            {"rule_id": r.rule_id, "severity": str(r.severity), "message": r.message, "element_ref": r.element_ref}
            for r in failed
        ],
    }
