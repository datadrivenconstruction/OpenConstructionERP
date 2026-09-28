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

from fastapi import APIRouter, Depends, HTTPException, Query, status

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
