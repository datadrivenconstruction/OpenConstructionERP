# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CVR (Cost-Value Reconciliation) & Cashflow API routes.

Endpoints (mounted at /api/v1/cvr):

    Reports
      GET    /reports/?project_id=X            - list reports
      POST   /reports/                          - create report
      GET    /reports/{report_id}               - get report
      PATCH  /reports/{report_id}               - update report
      DELETE /reports/{report_id}               - delete report
      POST   /reports/{report_id}/finalize/     - strike report final
      GET    /reports/{report_id}/summary/      - roll-up totals + margins
      GET    /reports/{report_id}/lines/        - list lines
      POST   /reports/{report_id}/lines/        - add a line

    Lines
      GET    /lines/{line_id}                    - get line
      PATCH  /lines/{line_id}                    - update line
      DELETE /lines/{line_id}                    - delete line

    Cashflow
      GET    /cashflow/series/?project_id=X      - cumulative S-curve series
      GET    /cashflow/?project_id=X             - list points
      POST   /cashflow/                          - create point
      GET    /cashflow/{point_id}                - get point
      PATCH  /cashflow/{point_id}                - update point
      DELETE /cashflow/{point_id}                - delete point

    Payment applications
      GET    /payment-applications/?project_id=X - list applications
      POST   /payment-applications/              - create application
      GET    /payment-applications/{app_id}      - get application
      PATCH  /payment-applications/{app_id}      - update application
      DELETE /payment-applications/{app_id}      - delete application
      GET    /progress-claims/?project_id=X      - claims an application can be raised from

Reads need cvr.read; writes (create / update / delete) need cvr.write; striking a
report final is the manager-level cvr.finalize. Mutating handlers commit
explicitly. Fixed paths (/cashflow/series) are registered before the parametric
/{id} route so a path segment is never parsed as a UUID, and every route
declares a concrete ``response_model`` - no union-typed responses.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.cvr.models import CvrLine, CvrReport, PaymentApplication
from app.modules.cvr.schemas import (
    CashflowPointCreate,
    CashflowPointResponse,
    CashflowPointUpdate,
    CashflowSeriesResponse,
    CvrLineCreate,
    CvrLineResponse,
    CvrLineUpdate,
    CvrReportCreate,
    CvrReportListResponse,
    CvrReportResponse,
    CvrReportUpdate,
    CvrSummaryResponse,
    PaymentApplicationCreate,
    PaymentApplicationListResponse,
    PaymentApplicationResponse,
    PaymentApplicationUpdate,
    ProgressClaimOptionListResponse,
)
from app.modules.cvr.service import CvrService

router = APIRouter(tags=["cvr"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> CvrService:
    return CvrService(session)


def _report_to_response(report: CvrReport, line_count: int) -> CvrReportResponse:
    """Build a report response, injecting the separately-counted line_count."""
    resp = CvrReportResponse.model_validate(report)
    resp.line_count = line_count
    return resp


# ── Reports ───────────────────────────────────────────────────────────────────


@router.get(
    "/reports",
    response_model=CvrReportListResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
    include_in_schema=False,
)
@router.get(
    "/reports/",
    response_model=CvrReportListResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def list_reports(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    report_status: str | None = Query(default=None, alias="status"),
    service: CvrService = Depends(_get_service),
) -> CvrReportListResponse:
    """List CVR reports for a project (newest period first)."""
    await verify_project_access(project_id, user_id, session)
    reports, total = await service.list_reports(
        project_id,
        offset=offset,
        limit=limit,
        report_status=report_status,
    )
    items = [_report_to_response(r, await service.report_line_count(r.id)) for r in reports]
    return CvrReportListResponse(items=items, total=total)


@router.post(
    "/reports/",
    response_model=CvrReportResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def create_report(
    data: CvrReportCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CvrReportResponse:
    """Create a new CVR report (one per project per period)."""
    await verify_project_access(data.project_id, user_id, session)
    report = await service.create_report(data, user_id=user_id)
    resp = _report_to_response(report, 0)
    await session.commit()
    return resp


@router.get(
    "/reports/{report_id}",
    response_model=CvrReportResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def get_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CvrReportResponse:
    """Get a single CVR report."""
    report = await service.get_report(report_id)
    await verify_project_access(report.project_id, user_id, session)
    return _report_to_response(report, await service.report_line_count(report_id))


@router.patch(
    "/reports/{report_id}",
    response_model=CvrReportResponse,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def update_report(
    report_id: uuid.UUID,
    data: CvrReportUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CvrReportResponse:
    """Update a CVR report."""
    existing = await service.get_report(report_id)
    await verify_project_access(existing.project_id, user_id, session)
    report = await service.update_report(report_id, data)
    resp = _report_to_response(report, await service.report_line_count(report_id))
    await session.commit()
    return resp


@router.delete(
    "/reports/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def delete_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> None:
    """Delete a CVR report and its lines."""
    existing = await service.get_report(report_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_report(report_id)
    await session.commit()


@router.post(
    "/reports/{report_id}/finalize/",
    response_model=CvrReportResponse,
    dependencies=[Depends(RequirePermission("cvr.finalize"))],
)
async def finalize_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CvrReportResponse:
    """Strike a report 'final' (commercial sign-off)."""
    existing = await service.get_report(report_id)
    await verify_project_access(existing.project_id, user_id, session)
    report = await service.finalize_report(report_id)
    resp = _report_to_response(report, await service.report_line_count(report_id))
    await session.commit()
    return resp


@router.get(
    "/reports/{report_id}/summary/",
    response_model=CvrSummaryResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def get_report_summary(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CvrSummaryResponse:
    """Return roll-up totals, margin-to-date and forecast margin for a report."""
    report = await service.get_report(report_id)
    await verify_project_access(report.project_id, user_id, session)
    return await service.get_report_summary(report_id)


@router.get(
    "/reports/{report_id}/lines/",
    response_model=list[CvrLineResponse],
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def list_lines(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> list[CvrLineResponse]:
    """List the cost heads of a report."""
    report = await service.get_report(report_id)
    await verify_project_access(report.project_id, user_id, session)
    lines = await service.list_lines(report_id)
    return [CvrLineResponse.model_validate(line) for line in lines]


@router.post(
    "/reports/{report_id}/lines/",
    response_model=CvrLineResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def create_line(
    report_id: uuid.UUID,
    data: CvrLineCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CvrLineResponse:
    """Add a cost head to a report."""
    report = await service.get_report(report_id)
    await verify_project_access(report.project_id, user_id, session)
    line = await service.create_line(report_id, data)
    resp = CvrLineResponse.model_validate(line)
    await session.commit()
    return resp


# ── Lines (by id) ─────────────────────────────────────────────────────────────


async def _line_with_access(
    line_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
    service: CvrService,
) -> CvrLine:
    """Fetch a line and verify the caller can reach its parent report's project."""
    line = await service.get_line(line_id)
    report = await service.get_report(line.report_id)
    await verify_project_access(report.project_id, user_id, session)
    return line


@router.get(
    "/lines/{line_id}",
    response_model=CvrLineResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def get_line(
    line_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CvrLineResponse:
    """Get a single CVR line."""
    line = await _line_with_access(line_id, user_id, session, service)
    return CvrLineResponse.model_validate(line)


@router.patch(
    "/lines/{line_id}",
    response_model=CvrLineResponse,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def update_line(
    line_id: uuid.UUID,
    data: CvrLineUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CvrLineResponse:
    """Update a CVR line."""
    await _line_with_access(line_id, user_id, session, service)
    line = await service.update_line(line_id, data)
    resp = CvrLineResponse.model_validate(line)
    await session.commit()
    return resp


@router.delete(
    "/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def delete_line(
    line_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> None:
    """Delete a CVR line."""
    await _line_with_access(line_id, user_id, session, service)
    await service.delete_line(line_id)
    await session.commit()


# ── Cashflow ──────────────────────────────────────────────────────────────────
# NOTE: /cashflow/series/ is declared BEFORE /cashflow/{point_id} so "series"
# is never parsed as a UUID path parameter.


@router.get(
    "/cashflow/series/",
    response_model=CashflowSeriesResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def cashflow_series(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: CvrService = Depends(_get_service),
) -> CashflowSeriesResponse:
    """Return the cumulative cash-in / cash-out / net S-curve for a project."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_cashflow_series(project_id)


@router.get(
    "/cashflow",
    response_model=list[CashflowPointResponse],
    dependencies=[Depends(RequirePermission("cvr.read"))],
    include_in_schema=False,
)
@router.get(
    "/cashflow/",
    response_model=list[CashflowPointResponse],
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def list_cashflow_points(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: CvrService = Depends(_get_service),
) -> list[CashflowPointResponse]:
    """List a project's cashflow points, oldest period first."""
    await verify_project_access(project_id, user_id, session)
    points = await service.list_cashflow_points(project_id)
    return [CashflowPointResponse.model_validate(p) for p in points]


@router.post(
    "/cashflow/",
    response_model=CashflowPointResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def create_cashflow_point(
    data: CashflowPointCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CashflowPointResponse:
    """Create a cash-in / cash-out point for a project period."""
    await verify_project_access(data.project_id, user_id, session)
    point = await service.create_cashflow_point(data)
    resp = CashflowPointResponse.model_validate(point)
    await session.commit()
    return resp


@router.get(
    "/cashflow/{point_id}",
    response_model=CashflowPointResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def get_cashflow_point(
    point_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CashflowPointResponse:
    """Get a single cashflow point."""
    point = await service.get_cashflow_point(point_id)
    await verify_project_access(point.project_id, user_id, session)
    return CashflowPointResponse.model_validate(point)


@router.patch(
    "/cashflow/{point_id}",
    response_model=CashflowPointResponse,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def update_cashflow_point(
    point_id: uuid.UUID,
    data: CashflowPointUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> CashflowPointResponse:
    """Update a cashflow point."""
    existing = await service.get_cashflow_point(point_id)
    await verify_project_access(existing.project_id, user_id, session)
    point = await service.update_cashflow_point(point_id, data)
    resp = CashflowPointResponse.model_validate(point)
    await session.commit()
    return resp


@router.delete(
    "/cashflow/{point_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def delete_cashflow_point(
    point_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> None:
    """Delete a cashflow point."""
    existing = await service.get_cashflow_point(point_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_cashflow_point(point_id)
    await session.commit()


# ── Payment applications ──────────────────────────────────────────────────────


def _payapp_to_response(application: PaymentApplication) -> PaymentApplicationResponse:
    return PaymentApplicationResponse.model_validate(application)


@router.get(
    "/payment-applications",
    response_model=PaymentApplicationListResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
    include_in_schema=False,
)
@router.get(
    "/payment-applications/",
    response_model=PaymentApplicationListResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def list_payment_applications(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    app_status: str | None = Query(default=None, alias="status"),
    service: CvrService = Depends(_get_service),
) -> PaymentApplicationListResponse:
    """List a project's interim payment applications."""
    await verify_project_access(project_id, user_id, session)
    applications, total = await service.list_payment_applications(
        project_id,
        offset=offset,
        limit=limit,
        app_status=app_status,
    )
    return PaymentApplicationListResponse(
        items=[_payapp_to_response(a) for a in applications],
        total=total,
    )


@router.get(
    "/progress-claims/",
    response_model=ProgressClaimOptionListResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def list_progress_claim_options(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: CvrService = Depends(_get_service),
) -> ProgressClaimOptionListResponse:
    """Contract progress claims of the project, for the payment application picker."""
    await verify_project_access(project_id, user_id, session)
    claims = await service.list_progress_claims_for_project(project_id)
    return ProgressClaimOptionListResponse(items=claims, total=len(claims))


@router.post(
    "/payment-applications/",
    response_model=PaymentApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def create_payment_application(
    data: PaymentApplicationCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> PaymentApplicationResponse:
    """Create an interim payment application (net = gross - retention)."""
    await verify_project_access(data.project_id, user_id, session)
    application = await service.create_payment_application(data, user_id=user_id)
    resp = _payapp_to_response(application)
    await session.commit()
    return resp


@router.get(
    "/payment-applications/{app_id}",
    response_model=PaymentApplicationResponse,
    dependencies=[Depends(RequirePermission("cvr.read"))],
)
async def get_payment_application(
    app_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> PaymentApplicationResponse:
    """Get a single payment application."""
    application = await service.get_payment_application(app_id)
    await verify_project_access(application.project_id, user_id, session)
    return _payapp_to_response(application)


@router.patch(
    "/payment-applications/{app_id}",
    response_model=PaymentApplicationResponse,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def update_payment_application(
    app_id: uuid.UUID,
    data: PaymentApplicationUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> PaymentApplicationResponse:
    """Update a payment application (net_value is always recomputed)."""
    existing = await service.get_payment_application(app_id)
    await verify_project_access(existing.project_id, user_id, session)
    application = await service.update_payment_application(app_id, data)
    resp = _payapp_to_response(application)
    await session.commit()
    return resp


@router.delete(
    "/payment-applications/{app_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("cvr.write"))],
)
async def delete_payment_application(
    app_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: CvrService = Depends(_get_service),
) -> None:
    """Delete a payment application."""
    existing = await service.get_payment_application(app_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_payment_application(app_id)
    await session.commit()
