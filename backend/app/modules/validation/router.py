"""Validation API routes.

Endpoints:
    POST  /validation/run                    — Run validation on a BOQ
    GET   /validation/reports?project_id=X   — List validation reports
    GET   /validation/reports/{report_id}    — Get single report
    DELETE /validation/reports/{report_id}   — Delete report
    GET   /validation/rule-sets              — List available rule sets
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.validation.bim_validation_service import BIMValidationService
from app.modules.validation.models import ValidationReport
from app.modules.validation.schemas import (
    CheckBIMModelRequest,
    RunValidationRequest,
    RunValidationResponse,
    ValidationReportResponse,
    ValidationResultItem,
)
from app.modules.validation.service import ValidationModuleService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Validation"])


# ── Dependency ────────────────────────────────────────────────────────────


def _get_service(session: SessionDep) -> ValidationModuleService:
    return ValidationModuleService(session)


# ── IDOR protection helpers ───────────────────────────────────────────────


async def _require_project_access(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    user_id: str | None,
) -> None:
    """Verify the current user owns (or is admin on) the referenced project.

    Central choke-point for project-scoped validation endpoints. Mirrors
    the pattern used by ``finance.router._require_project_access``.
    Raises HTTP 403 if the user has no access. ``None`` project_id is a
    no-op — callers that accept global aggregates must scope at the
    service layer.
    """
    if project_id is None:
        return
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        from app.modules.projects.repository import ProjectRepository
        from app.modules.users.repository import UserRepository

        proj_repo = ProjectRepository(session)
        project = await proj_repo.get_by_id(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )

        # Admin bypass
        try:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_id(user_id)
            if user is not None and getattr(user, "role", "") == "admin":
                return
        except Exception:  # noqa: BLE001 — best-effort admin check
            pass

        if str(getattr(project, "owner_id", "")) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you do not own this project",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Validation project access check failed for %s: %s", project_id, exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization check failed",
        )


async def _require_report_access(
    session: AsyncSession,
    report_id: uuid.UUID,
    user_id: str | None,
) -> ValidationReport:
    """Load a report and verify the caller owns its parent project."""
    report = await session.get(ValidationReport, report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Validation report {report_id} not found",
        )
    await _require_project_access(session, report.project_id, user_id)
    return report


# ── POST /run — Run validation on a BOQ ──────────────────────────────────


@router.post(
    "/run/",
    response_model=RunValidationResponse,
    dependencies=[Depends(RequirePermission("validation.create"))],
)
async def run_validation(
    data: RunValidationRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ValidationModuleService = Depends(_get_service),
) -> RunValidationResponse:
    """Run validation rules against a BOQ.

    Loads the BOQ positions, applies the requested rule sets, and returns
    a full validation report with per-rule results.

    The report is also persisted to the database for historical review.
    """
    await _require_project_access(session, data.project_id, user_id)
    try:
        result = await service.run_validation(
            project_id=data.project_id,
            boq_id=data.boq_id,
            rule_sets=data.rule_sets,
            user_id=uuid.UUID(user_id),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return RunValidationResponse(
        report_id=uuid.UUID(result["report_id"]),
        status=result["status"],
        score=result["score"],
        total_rules=result["total_rules"],
        passed_count=result["passed_count"],
        warning_count=result["warning_count"],
        error_count=result["error_count"],
        info_count=result["info_count"],
        rule_sets=result["rule_sets"],
        duration_ms=result["duration_ms"],
        results=[
            ValidationResultItem(
                rule_id=r["rule_id"],
                status=r["status"],
                message=r["message"],
                element_ref=r.get("element_ref"),
                details=r.get("details"),
                suggestion=r.get("suggestion"),
            )
            for r in result["results"]
        ],
    )


# ── POST /check-bim-model — Run per-element BIM rules ───────────────────


@router.post(
    "/check-bim-model",
    response_model=ValidationReportResponse,
    dependencies=[Depends(RequirePermission("validation.create"))],
)
async def check_bim_model(
    request: CheckBIMModelRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ValidationReportResponse:
    """Run per-element :class:`BIMElementRule` checks against a BIM model.

    Persists a :class:`ValidationReport` row with ``target_type='bim_model'``
    and ``results`` that carry ``element_id`` references so the UI can map
    each failure back to the offending element. Large models are capped at
    ``MAX_RESULTS_PER_REPORT`` failures with a ``_truncated`` sentinel.
    """
    # Ownership check — resolve the BIM model to its project first.
    from app.modules.bim_hub.repository import BIMModelRepository

    model_repo = BIMModelRepository(session)
    model = await model_repo.get(request.model_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"BIM model {request.model_id} not found",
        )
    await _require_project_access(session, model.project_id, user_id)

    service = BIMValidationService(session)
    try:
        report = await service.validate_bim_model(
            model_id=request.model_id,
            rule_ids=request.rule_ids,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return ValidationReportResponse.model_validate(report)


# ── GET /reports — List validation reports ───────────────────────────────


@router.get(
    "/reports/",
    response_model=list[ValidationReportResponse],
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def list_reports(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(..., description="Project ID to list reports for"),
    target_type: str | None = Query(None, description="Filter by target type (boq, document, etc.)"),
    limit: int = Query(50, ge=1, le=200),
    service: ValidationModuleService = Depends(_get_service),
) -> list[ValidationReportResponse]:
    """List validation reports for a project, newest first."""
    await _require_project_access(session, project_id, user_id)
    reports = await service.list_reports(project_id, target_type=target_type, limit=limit)
    return [ValidationReportResponse.model_validate(r) for r in reports]


# ── GET /reports/{report_id} — Get single report ─────────────────────────


@router.get(
    "/reports/{report_id}",
    response_model=ValidationReportResponse,
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def get_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ValidationModuleService = Depends(_get_service),
) -> ValidationReportResponse:
    """Get a single validation report by ID."""
    report = await _require_report_access(session, report_id, user_id)
    return ValidationReportResponse.model_validate(report)


# ── DELETE /reports/{report_id} — Delete report ──────────────────────────


@router.delete(
    "/reports/{report_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("validation.delete"))],
)
async def delete_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ValidationModuleService = Depends(_get_service),
) -> None:
    """Delete a validation report."""
    await _require_report_access(session, report_id, user_id)
    deleted = await service.delete_report(report_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Validation report {report_id} not found",
        )


# ── GET /rule-sets — List available rule sets ─────────────────────────────


@router.get(
    "/rule-sets/",
)
async def list_rule_sets(
    service: ValidationModuleService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List all available validation rule sets with descriptions.

    Returns each rule set's name, description, rule count, and individual rules.
    This endpoint does not require authentication so it can be used by
    public documentation pages.
    """
    return service.get_available_rule_sets()


# ── Vector / semantic memory endpoints ───────────────────────────────────
#
# ``/vector/status/`` + ``/vector/reindex/`` wired via the shared factory
# (see ``include_router`` at the bottom of the file).  The
# ``/{report_id}/similar/`` endpoint stays module-specific.


@router.get(
    "/{report_id}/similar/",
    dependencies=[Depends(RequirePermission("validation.read"))],
)
async def validation_report_similar(
    report_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
    limit: int = Query(default=5, ge=1, le=20),
    cross_project: bool = Query(default=True),
) -> dict[str, Any]:
    """Return validation reports semantically similar to the given one."""
    from app.core.vector_index import find_similar
    from app.modules.validation.vector_adapter import validation_report_adapter

    row = await session.get(ValidationReport, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Validation report not found")
    project_id = str(row.project_id) if row.project_id else None
    hits = await find_similar(
        validation_report_adapter,
        row,
        project_id=project_id,
        cross_project=cross_project,
        limit=limit,
    )
    return {
        "source_id": str(report_id),
        "limit": limit,
        "cross_project": cross_project,
        "hits": [h.to_dict() for h in hits],
    }


# ── Mount vector status + reindex via the shared factory ────────────────
from app.core.vector_index import COLLECTION_VALIDATION  # noqa: E402
from app.core.vector_routes import create_vector_routes  # noqa: E402
from app.modules.validation.vector_adapter import (  # noqa: E402
    validation_report_adapter as _validation_report_adapter,
)

router.include_router(
    create_vector_routes(
        collection=COLLECTION_VALIDATION,
        adapter=_validation_report_adapter,
        model=ValidationReport,
        read_permission="validation.read",
        write_permission="validation.create",
        project_id_attr="project_id",
    )
)
