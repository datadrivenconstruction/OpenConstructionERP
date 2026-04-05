"""Field Reports API routes.

Endpoints:
    POST   /reports                        - Create field report
    GET    /reports?project_id=X           - List with filters
    GET    /reports/{id}                   - Get single
    PATCH  /reports/{id}                   - Update
    DELETE /reports/{id}                   - Delete
    POST   /reports/{id}/submit            - Submit for approval
    POST   /reports/{id}/approve           - Approve
    GET    /reports/summary?project_id=X   - Aggregated stats
    GET    /reports/{id}/export/pdf         - Download PDF
    GET    /reports/calendar?project_id=X  - Reports by month for calendar
"""

import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.fieldreports.schemas import (
    FieldReportCreate,
    FieldReportResponse,
    FieldReportSummary,
    FieldReportUpdate,
)
from app.modules.fieldreports.service import FieldReportService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> FieldReportService:
    return FieldReportService(session)


def _report_to_response(report: object) -> FieldReportResponse:
    """Build a FieldReportResponse from a FieldReport ORM object."""
    return FieldReportResponse(
        id=report.id,  # type: ignore[attr-defined]
        project_id=report.project_id,  # type: ignore[attr-defined]
        report_date=report.report_date,  # type: ignore[attr-defined]
        report_type=report.report_type,  # type: ignore[attr-defined]
        weather_condition=report.weather_condition,  # type: ignore[attr-defined]
        temperature_c=report.temperature_c,  # type: ignore[attr-defined]
        wind_speed=report.wind_speed,  # type: ignore[attr-defined]
        precipitation=report.precipitation,  # type: ignore[attr-defined]
        humidity=report.humidity,  # type: ignore[attr-defined]
        workforce=report.workforce or [],  # type: ignore[attr-defined]
        equipment_on_site=report.equipment_on_site or [],  # type: ignore[attr-defined]
        work_performed=report.work_performed,  # type: ignore[attr-defined]
        delays=report.delays,  # type: ignore[attr-defined]
        delay_hours=report.delay_hours,  # type: ignore[attr-defined]
        visitors=report.visitors,  # type: ignore[attr-defined]
        deliveries=report.deliveries,  # type: ignore[attr-defined]
        safety_incidents=report.safety_incidents,  # type: ignore[attr-defined]
        materials_used=report.materials_used or [],  # type: ignore[attr-defined]
        photos=report.photos or [],  # type: ignore[attr-defined]
        notes=report.notes,  # type: ignore[attr-defined]
        signature_by=report.signature_by,  # type: ignore[attr-defined]
        signature_data=report.signature_data,  # type: ignore[attr-defined]
        status=report.status,  # type: ignore[attr-defined]
        approved_by=report.approved_by,  # type: ignore[attr-defined]
        approved_at=report.approved_at,  # type: ignore[attr-defined]
        created_by=report.created_by,  # type: ignore[attr-defined]
        metadata=getattr(report, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=report.created_at,  # type: ignore[attr-defined]
        updated_at=report.updated_at,  # type: ignore[attr-defined]
    )


# ── Summary ──────────────────────────────────────────────────────────────────


@router.get("/reports/summary", response_model=FieldReportSummary)
async def get_summary(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: FieldReportService = Depends(_get_service),
) -> FieldReportSummary:
    """Aggregated field report stats for a project."""
    data = await service.get_summary(project_id)
    return FieldReportSummary(**data)


# ── Calendar ─────────────────────────────────────────────────────────────────


@router.get("/reports/calendar", response_model=list[FieldReportResponse])
async def get_calendar(
    project_id: uuid.UUID = Query(...),
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: FieldReportService = Depends(_get_service),
) -> list[FieldReportResponse]:
    """Get reports for a month (calendar view). Month format: YYYY-MM."""
    parts = month.split("-")
    year, mon = int(parts[0]), int(parts[1])
    reports = await service.get_calendar(project_id, year, mon)
    return [_report_to_response(r) for r in reports]


# ── Create ───────────────────────────────────────────────────────────────────


@router.post("/reports", response_model=FieldReportResponse, status_code=201)
async def create_report(
    data: FieldReportCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("fieldreports.create")),
    service: FieldReportService = Depends(_get_service),
) -> FieldReportResponse:
    """Create a new field report."""
    report = await service.create_report(data, user_id=user_id)
    return _report_to_response(report)


# ── List ─────────────────────────────────────────────────────────────────────


@router.get("/reports", response_model=list[FieldReportResponse])
async def list_reports(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    type_filter: str | None = Query(default=None, alias="type"),
    service: FieldReportService = Depends(_get_service),
) -> list[FieldReportResponse]:
    """List field reports for a project with optional filters."""
    reports, _ = await service.list_reports(
        project_id,
        offset=offset,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        report_type=type_filter,
        status_filter=status_filter,
    )
    return [_report_to_response(r) for r in reports]


# ── Get ──────────────────────────────────────────────────────────────────────


@router.get("/reports/{report_id}", response_model=FieldReportResponse)
async def get_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: FieldReportService = Depends(_get_service),
) -> FieldReportResponse:
    """Get a single field report."""
    report = await service.get_report(report_id)
    return _report_to_response(report)


# ── Update ───────────────────────────────────────────────────────────────────


@router.patch("/reports/{report_id}", response_model=FieldReportResponse)
async def update_report(
    report_id: uuid.UUID,
    data: FieldReportUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("fieldreports.update")),
    service: FieldReportService = Depends(_get_service),
) -> FieldReportResponse:
    """Update a field report."""
    report = await service.update_report(report_id, data)
    return _report_to_response(report)


# ── Delete ───────────────────────────────────────────────────────────────────


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("fieldreports.delete")),
    service: FieldReportService = Depends(_get_service),
) -> None:
    """Delete a field report."""
    await service.delete_report(report_id)


# ── Submit ───────────────────────────────────────────────────────────────────


@router.post("/reports/{report_id}/submit", response_model=FieldReportResponse)
async def submit_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("fieldreports.update")),
    service: FieldReportService = Depends(_get_service),
) -> FieldReportResponse:
    """Submit a draft report for approval."""
    report = await service.submit_report(report_id)
    return _report_to_response(report)


# ── Approve ──────────────────────────────────────────────────────────────────


@router.post("/reports/{report_id}/approve", response_model=FieldReportResponse)
async def approve_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("fieldreports.approve")),
    service: FieldReportService = Depends(_get_service),
) -> FieldReportResponse:
    """Approve a submitted report."""
    report = await service.approve_report(report_id, user_id)
    return _report_to_response(report)


# ── PDF Export ───────────────────────────────────────────────────────────────


@router.get("/reports/{report_id}/export/pdf")
async def export_pdf(
    report_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: FieldReportService = Depends(_get_service),
) -> Response:
    """Export a field report as PDF."""
    pdf_bytes = await service.generate_pdf(report_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=field_report_{report_id}.pdf"
        },
    )
