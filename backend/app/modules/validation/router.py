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

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.validation.schemas import (
    RunValidationRequest,
    RunValidationResponse,
    ValidationReportResponse,
    ValidationResultItem,
)
from app.modules.validation.service import ValidationModuleService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Validation"])


# ── Dependency ──────────────���────────────────────��────────────────────────


def _get_service(session: SessionDep) -> ValidationModuleService:
    return ValidationModuleService(session)


# ── POST /run — Run validation on a BOQ ──────────���───────────────────────


@router.post(
    "/run/",
    response_model=RunValidationResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
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


# ── GET /reports — List validation reports ────────────��───────────────────


@router.get(
    "/reports/",
    response_model=list[ValidationReportResponse],
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_reports(
    project_id: uuid.UUID = Query(..., description="Project ID to list reports for"),
    target_type: str | None = Query(None, description="Filter by target type (boq, document, etc.)"),
    limit: int = Query(50, ge=1, le=200),
    service: ValidationModuleService = Depends(_get_service),
) -> list[ValidationReportResponse]:
    """List validation reports for a project, newest first."""
    reports = await service.list_reports(project_id, target_type=target_type, limit=limit)
    return [ValidationReportResponse.model_validate(r) for r in reports]


# ── GET /reports/{report_id} — Get single report ──────��──────────────────


@router.get(
    "/reports/{report_id}",
    response_model=ValidationReportResponse,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_report(
    report_id: uuid.UUID,
    service: ValidationModuleService = Depends(_get_service),
) -> ValidationReportResponse:
    """Get a single validation report by ID."""
    report = await service.get_report(report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Validation report {report_id} not found",
        )
    return ValidationReportResponse.model_validate(report)


# ── DELETE /reports/{report_id} — Delete report ──────────────────────────


@router.delete(
    "/reports/{report_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def delete_report(
    report_id: uuid.UUID,
    service: ValidationModuleService = Depends(_get_service),
) -> None:
    """Delete a validation report."""
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
