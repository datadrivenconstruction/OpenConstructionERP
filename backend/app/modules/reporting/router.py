"""Reporting & Dashboards API routes.

Endpoints:
    GET    /kpi?project_id=X           — Latest KPI snapshot
    GET    /kpi/history?project_id=X   — KPI snapshots over time
    POST   /kpi/snapshot               — Create KPI snapshot
    GET    /templates                   — List report templates
    POST   /templates                   — Create custom template
    POST   /generate                    — Generate a report
    GET    /reports?project_id=X        — List generated reports
    GET    /reports/{report_id}         — Get a generated report
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.reporting.schemas import (
    GeneratedReportResponse,
    GenerateReportRequest,
    KPISnapshotCreate,
    KPISnapshotResponse,
    ReportTemplateCreate,
    ReportTemplateResponse,
)
from app.modules.reporting.service import ReportingService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> ReportingService:
    return ReportingService(session)


# ── KPI Snapshot endpoints ────────────────────────────────────────────────


@router.get("/kpi", response_model=KPISnapshotResponse | None)
async def get_latest_kpi(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ReportingService = Depends(_get_service),
) -> KPISnapshotResponse | None:
    """Get the latest KPI snapshot for a project."""
    snapshot = await service.get_latest_kpi(project_id)
    if snapshot is None:
        return None
    return KPISnapshotResponse.model_validate(snapshot)


@router.get("/kpi/history", response_model=list[KPISnapshotResponse])
async def list_kpi_history(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: ReportingService = Depends(_get_service),
) -> list[KPISnapshotResponse]:
    """List KPI snapshots for a project over time."""
    snapshots, _ = await service.list_kpi_history(
        project_id, offset=offset, limit=limit,
    )
    return [KPISnapshotResponse.model_validate(s) for s in snapshots]


@router.post("/kpi/snapshot", response_model=KPISnapshotResponse, status_code=201)
async def create_kpi_snapshot(
    data: KPISnapshotCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("reporting.create")),
    service: ReportingService = Depends(_get_service),
) -> KPISnapshotResponse:
    """Create a new KPI snapshot for a project."""
    snapshot = await service.create_kpi_snapshot(data, user_id=user_id)
    return KPISnapshotResponse.model_validate(snapshot)


# ── Report Template endpoints ─────────────────────────────────────────────


@router.get("/templates", response_model=list[ReportTemplateResponse])
async def list_templates(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ReportingService = Depends(_get_service),
) -> list[ReportTemplateResponse]:
    """List all report templates (system + custom)."""
    templates, _ = await service.list_templates(offset=offset, limit=limit)
    return [ReportTemplateResponse.model_validate(t) for t in templates]


@router.post("/templates", response_model=ReportTemplateResponse, status_code=201)
async def create_template(
    data: ReportTemplateCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("reporting.create")),
    service: ReportingService = Depends(_get_service),
) -> ReportTemplateResponse:
    """Create a custom report template."""
    template = await service.create_template(data, user_id=user_id)
    return ReportTemplateResponse.model_validate(template)


# ── Generated Report endpoints ────────────────────────────────────────────


@router.post("/generate", response_model=GeneratedReportResponse, status_code=201)
async def generate_report(
    data: GenerateReportRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("reporting.create")),
    service: ReportingService = Depends(_get_service),
) -> GeneratedReportResponse:
    """Generate a new report for a project."""
    report = await service.generate_report(data, user_id=user_id)
    return GeneratedReportResponse.model_validate(report)


@router.get("/reports", response_model=list[GeneratedReportResponse])
async def list_reports(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ReportingService = Depends(_get_service),
) -> list[GeneratedReportResponse]:
    """List generated reports for a project."""
    reports, _ = await service.list_reports(
        project_id, offset=offset, limit=limit,
    )
    return [GeneratedReportResponse.model_validate(r) for r in reports]


@router.get("/reports/{report_id}", response_model=GeneratedReportResponse)
async def get_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ReportingService = Depends(_get_service),
) -> GeneratedReportResponse:
    """Get a single generated report."""
    report = await service.get_report(report_id)
    return GeneratedReportResponse.model_validate(report)
