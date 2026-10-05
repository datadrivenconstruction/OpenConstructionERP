# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reporting & Dashboards API routes.

Endpoints:
    GET    /kpi?project_id=X                     - Latest KPI snapshot
    GET    /kpi/history?project_id=X             - KPI snapshots over time
    POST   /kpi/snapshot                         - Create KPI snapshot
    GET    /templates                             - List report templates
    POST   /templates                             - Create custom template
    POST   /templates/{id}/schedule               - Attach/replace/clear cron schedule
    POST   /templates/{id}/run-now                - Trigger an immediate render
    GET    /templates/scheduled                   - List all scheduled templates
    POST   /generate                              - Generate a report
    GET    /reports?project_id=X                  - List generated reports
    GET    /reports/{report_id}                   - Get a generated report
    GET    /reports/{report_id}/content           - Rendered HTML body
    GET    /reports/{report_id}/download?format=  - Download as pdf/xlsx/csv/html
    GET    /cobie/{project_id}/download           - Download a COBie handover workbook
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import HTMLResponse, Response

from app.core.content_disposition import attachment_disposition
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.reporting.report_translations import resolve_report_locale
from app.modules.reporting.schemas import (
    GeneratedReportResponse,
    GenerateReportRequest,
    KPISnapshotCreate,
    KPISnapshotResponse,
    ReportScheduleRequest,
    ReportTemplateCreate,
    ReportTemplateResponse,
)
from app.modules.reporting.service import ReportingService

router = APIRouter(tags=["reporting"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> ReportingService:
    return ReportingService(session)


# ── KPI Snapshot endpoints ────────────────────────────────────────────────


@router.get("/kpi/", response_model=KPISnapshotResponse | None)
async def get_latest_kpi(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("reporting.read")),
    service: ReportingService = Depends(_get_service),
) -> KPISnapshotResponse | None:
    """Get the latest KPI snapshot for a project."""
    await verify_project_access(project_id, user_id, session)
    snapshot = await service.get_latest_kpi(project_id)
    if snapshot is None:
        return None
    return KPISnapshotResponse.model_validate(snapshot)


@router.get("/kpi/history/", response_model=list[KPISnapshotResponse])
async def list_kpi_history(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("reporting.read")),
    service: ReportingService = Depends(_get_service),
) -> list[KPISnapshotResponse]:
    """List KPI snapshots for a project over time."""
    await verify_project_access(project_id, user_id, session)
    snapshots, _ = await service.list_kpi_history(
        project_id,
        offset=offset,
        limit=limit,
    )
    return [KPISnapshotResponse.model_validate(s) for s in snapshots]


@router.post("/kpi/snapshot/", response_model=KPISnapshotResponse, status_code=201)
async def create_kpi_snapshot(
    data: KPISnapshotCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("reporting.create")),
    service: ReportingService = Depends(_get_service),
) -> KPISnapshotResponse:
    """Create a new KPI snapshot for a project."""
    await verify_project_access(data.project_id, user_id, session)
    snapshot = await service.create_kpi_snapshot(data, user_id=user_id)
    return KPISnapshotResponse.model_validate(snapshot)


@router.post("/kpi/recalculate-all/", status_code=200)
async def recalculate_all_kpis(
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("reporting.distribute")),
    service: ReportingService = Depends(_get_service),
) -> dict:
    """Recalculate KPI snapshots for ALL active projects (MANAGER+).

    Queries finance, safety, RFI, submittals, schedule, and risk modules
    to produce up-to-date KPI values.  Creates or updates one KPISnapshot
    per project for today's date.

    Gated at ``reporting.distribute`` (MANAGER) rather than the per-row
    ``reporting.create`` (EDITOR): this is a portfolio-wide,
    cross-tenant recompute that ignores per-project membership and runs
    O(projects x 6 module queries). The privileged blast radius warrants
    the manager tier, mirroring how scheduling/distribution is gated
    (W2 audit, /reporting). The frontend hides the trigger for roles
    below manager so it is never a dead control.
    """
    return await service.auto_recalculate_kpis()


# ── PO retainage reconciliation (Gap F) ───────────────────────────────────


@router.get("/po-retainage-reconciliation/", response_model=dict)
async def get_po_retainage_reconciliation(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    period_start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    period_end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("reporting.read")),
    service: ReportingService = Depends(_get_service),
) -> dict:
    """Period-end PO retainage reconciliation for a project.

    Aggregates POs issued in ``[period_start, period_end]`` (inclusive,
    ISO ``YYYY-MM-DD``) that carry a non-zero retention percentage. Money is
    rolled up per currency (never blended). Deterministic; no AI.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.render_po_retainage_reconciliation(
        project_id=project_id,
        period_start=period_start,
        period_end=period_end,
    )


# ── Report Template endpoints ─────────────────────────────────────────────


@router.get("/templates/", response_model=list[ReportTemplateResponse])
async def list_templates(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    _perm: None = Depends(RequirePermission("reporting.read")),
    service: ReportingService = Depends(_get_service),
) -> list[ReportTemplateResponse]:
    """List all report templates (system + custom)."""
    templates, _ = await service.list_templates(offset=offset, limit=limit)
    return [ReportTemplateResponse.model_validate(t) for t in templates]


@router.post("/templates/", response_model=ReportTemplateResponse, status_code=201)
async def create_template(
    data: ReportTemplateCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("reporting.create")),
    service: ReportingService = Depends(_get_service),
) -> ReportTemplateResponse:
    """Create a custom report template."""
    template = await service.create_template(data, user_id=user_id)
    return ReportTemplateResponse.model_validate(template)


@router.get("/templates/scheduled/", response_model=list[ReportTemplateResponse])
async def list_scheduled_templates(
    session: SessionDep,
    user_id: CurrentUserId,
    service: ReportingService = Depends(_get_service),
) -> list[ReportTemplateResponse]:
    """List every template that has a cron schedule attached.

    IDOR-guarded: templates whose ``project_id_scope`` points at a
    project the caller cannot access are filtered out - otherwise the
    response would leak project UUIDs (and recipient email lists) for
    every other tenant on the platform. Portfolio-wide templates
    (``project_id_scope is None``) remain visible to all authenticated
    callers since they are not bound to any single tenant's data.
    """
    from fastapi import HTTPException

    from app.modules.projects.repository import ProjectRepository
    from app.modules.reporting.models import ReportTemplate
    from app.modules.users.repository import UserRepository

    templates = await service.list_scheduled_templates()

    # Admin bypass - admins can see every scheduled template.
    try:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(uuid.UUID(user_id))
        if user is not None and getattr(user, "role", "") == "admin":
            return [ReportTemplateResponse.model_validate(t) for t in templates]
    except Exception:
        logger.exception("Admin-role lookup failed during scheduled template list")

    # Non-admins: include portfolio-wide templates and only those scoped
    # to projects the caller owns. Re-using ``ProjectRepository.get_by_id``
    # keeps the ownership check colocated with the project module.
    proj_repo = ProjectRepository(session)
    visible: list[ReportTemplate] = []
    for tmpl in templates:
        scope = getattr(tmpl, "project_id_scope", None)
        if scope is None:
            visible.append(tmpl)
            continue
        try:
            project = await proj_repo.get_by_id(scope)
        except HTTPException:
            continue
        if project is None:
            continue
        if str(getattr(project, "owner_id", "")) == str(user_id):
            visible.append(tmpl)

    return [ReportTemplateResponse.model_validate(t) for t in visible]


@router.post(
    "/templates/{template_id}/schedule/",
    response_model=ReportTemplateResponse,
)
async def schedule_template(
    template_id: uuid.UUID,
    data: ReportScheduleRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("reporting.distribute")),
    service: ReportingService = Depends(_get_service),
) -> ReportTemplateResponse:
    """Attach/replace/clear a cron schedule on an existing template.

    IDOR-guarded: if the template is already scoped to a project, the
    caller must have access to that project before they can re-schedule
    it (otherwise a viewer could hijack another tenant's scheduled
    template by re-pointing it at their own project, or silently clear
    its schedule). Returns 404 to avoid leaking which template IDs exist.
    """
    # Existing-scope check: the current schedule may already be locked to
    # a project the caller cannot see. Resolve the template first and gate
    # on its existing project_id_scope so the caller cannot mutate a
    # template they wouldn't otherwise be allowed to read.
    template = await service.get_template(template_id)
    if template.project_id_scope is not None:
        await verify_project_access(template.project_id_scope, user_id, session)
    # New-scope check: the *target* scope must also be one the caller can
    # access. Without this gate, a caller with read access to project X
    # could re-target a template they don't own to project Y they DO own.
    if data.project_id_scope is not None:
        await verify_project_access(data.project_id_scope, user_id, session)
    template = await service.schedule_template(template_id, data)
    return ReportTemplateResponse.model_validate(template)


@router.post(
    "/templates/{template_id}/run-now/",
    response_model=GeneratedReportResponse,
    status_code=201,
)
async def run_template_now(
    template_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("reporting.create")),
    service: ReportingService = Depends(_get_service),
) -> GeneratedReportResponse:
    """Render a scheduled template immediately without waiting for its
    cron trigger. Useful for 'preview' buttons and for backfilling a
    missed run. Respects the template's ``project_id_scope``.
    """
    template = await service.get_template(template_id)
    if template.project_id_scope is None:
        from fastapi import HTTPException
        from fastapi import status as http_status

        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Portfolio-wide run-now is not supported yet; set project_id_scope first",
        )
    await verify_project_access(template.project_id_scope, user_id, session)
    # Use the existing generate_report path so the history is consistent.
    gen_data = GenerateReportRequest(
        project_id=template.project_id_scope,
        template_id=template.id,
        report_type=template.report_type,
        title=f"{template.name} (ad-hoc)",
        format="pdf",
        metadata={"triggered_by": "run-now"},
    )
    report = await service.generate_report(gen_data, user_id=user_id)
    await service.mark_template_ran(template)
    # Distribute to the template's recipients (emails + portal users) when
    # any are configured. Best-effort: a notification failure never blocks
    # the run-now response (the report is already persisted).
    if template.recipients:
        await service.dispatch_report_email(report, list(template.recipients))
    return GeneratedReportResponse.model_validate(report)


# ── Generated Report endpoints ────────────────────────────────────────────


@router.post("/generate/", response_model=GeneratedReportResponse, status_code=201)
async def generate_report(
    data: GenerateReportRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("reporting.create")),
    service: ReportingService = Depends(_get_service),
) -> GeneratedReportResponse:
    """Generate a new report for a project."""
    await verify_project_access(data.project_id, user_id, session)
    report = await service.generate_report(data, user_id=user_id)
    return GeneratedReportResponse.model_validate(report)


@router.get("/reports/", response_model=list[GeneratedReportResponse])
async def list_reports(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ReportingService = Depends(_get_service),
) -> list[GeneratedReportResponse]:
    """List generated reports for a project."""
    await verify_project_access(project_id, user_id, session)
    reports, _ = await service.list_reports(
        project_id,
        offset=offset,
        limit=limit,
    )
    return [GeneratedReportResponse.model_validate(r) for r in reports]


@router.get(
    "/reports/{report_id}/content",
    response_class=HTMLResponse,
    responses={
        200: {"content": {"text/html": {}}},
        404: {"description": "Report not found"},
        410: {"description": "Report body not yet rendered or removed from storage"},
    },
)
async def get_report_content(
    report_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str | None = Query(
        default=None,
        description="Language to render the report in; falls back to Accept-Language, then English",
    ),
    accept_language: str | None = Header(default=None, alias="Accept-Language"),
    service: ReportingService = Depends(_get_service),
) -> HTMLResponse:
    """Return the rendered HTML body of a generated report.

    The matching metadata row must exist (404 otherwise) and have a
    populated ``storage_key`` (410 Gone otherwise - the metadata exists
    but the renderer never produced or persisted a body). IDOR-guarded
    via ``verify_project_access`` on the report's parent project.

    Before this endpoint landed (W23 P0 audit, task #252) the frontend
    history panels listed report rows but had no way to open them
    because no endpoint exposed the rendered body.

    The language comes from ``?locale=`` first and ``Accept-Language``
    second, and the response declares what was actually rendered rather
    than what was asked for: the report catalogue holds fewer languages
    than the interface offers, so a request the catalogue cannot satisfy
    gets an English body that says so in ``Content-Language``.
    """
    # Resolve the metadata row first (raises 404 if unknown) so we know
    # which project to gate on, then verify access *before* fetching the
    # rendered body from the storage backend.  Reversing the order would
    # waste a storage I/O for every unauthorised request and, more
    # importantly, would read sensitive report content into memory before
    # the caller's access is confirmed.
    report = await service.get_report(report_id)
    await verify_project_access(report.project_id, user_id, session)
    resolved = resolve_report_locale(locale, accept_language)
    _, body_html = await service.get_report_content(report_id, locale=resolved)
    return HTMLResponse(content=body_html, status_code=200, headers={"Content-Language": resolved})


@router.get(
    "/reports/{report_id}/download/",
    responses={
        200: {
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "text/csv": {},
                "text/html": {},
            },
            "description": "Report rendered as a downloadable file",
        },
        400: {"description": "Unsupported export format"},
        404: {"description": "Report not found"},
    },
)
@router.get(
    "/reports/{report_id}/download",
    include_in_schema=False,
)
async def download_report(
    report_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    format: str = Query(  # noqa: A002 - mirrors GenerateReportRequest.format wording
        default="pdf",
        pattern=r"^(pdf|xlsx|csv|html)$",
        description="Export format: pdf, xlsx, csv, or html",
    ),
    locale: str | None = Query(
        default=None,
        description="Language to write the file in; falls back to Accept-Language, then English",
    ),
    accept_language: str | None = Header(default=None, alias="Accept-Language"),
    service: ReportingService = Depends(_get_service),
) -> Response:
    """Download a generated report as a real PDF / Excel / CSV / HTML file.

    The tabular report types (cost breakdown, BOQ-style summaries, KPI
    sections, retainage roll-ups) export to ``xlsx`` and ``csv``; the
    executive/summary view exports to ``pdf``. ``html`` serves the existing
    rendered body unchanged so nothing regresses for callers that still want
    HTML.

    IDOR-guarded the same way as ``/content``: the report metadata row is
    resolved first (404 if unknown) so we know which project to gate on, then
    ``verify_project_access`` confirms the caller may read that project before
    any body is rendered. A report therefore only ever contains the caller's
    own project/tenant data.

    The response carries a ``Content-Disposition: attachment`` header so the
    browser downloads a file rather than rendering it inline, matching the
    BOQ export endpoints' convention.

    The language comes from ``?locale=`` first and ``Accept-Language``
    second, and applies to every format the endpoint serves.
    """
    report = await service.get_report(report_id)
    await verify_project_access(report.project_id, user_id, session)
    resolved = resolve_report_locale(locale, accept_language)
    filename, media_type, blob = await service.export_report_file(report_id, format, locale=resolved)
    return Response(
        content=blob,
        media_type=media_type,
        headers={
            "Content-Disposition": attachment_disposition(filename),
            "Content-Length": str(len(blob)),
            # What was written, not what was asked for. The report catalogue
            # holds fewer languages than the interface offers, so a request
            # it cannot satisfy falls back to English and this header is how
            # the client finds out. It used to be pinned to "en" because no
            # locale reached the exporters at all; one does now, and pinning
            # it would put the reader's language on a document written in
            # ours - the mislabelling the header exists to prevent.
            "Content-Language": resolved,
        },
    )


@router.get(
    "/cobie/{project_id}/download/",
    responses={
        200: {
            "content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}},
            "description": "COBie handover workbook",
        },
        404: {"description": "Project has no BIM models to hand over"},
    },
    dependencies=[Depends(RequirePermission("reporting.read"))],
)
@router.get(
    "/cobie/{project_id}/download",
    include_in_schema=False,
    dependencies=[Depends(RequirePermission("reporting.read"))],
)
async def download_cobie(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ReportingService = Depends(_get_service),
) -> Response:
    """Download a project's COBie (ISO 19650 handover) workbook.

    Unlike ``/reports/{id}/download`` this is not tied to a previously
    generated report row - it is a live projection of the project's BIM
    asset register (every BIM model attached to the project, unioned), so
    it always reflects the current state of the model without requiring a
    "generate" step first.
    """
    await verify_project_access(project_id, user_id, session)
    filename, media_type, blob = await service.export_project_cobie(project_id)
    return Response(
        content=blob,
        media_type=media_type,
        headers={
            "Content-Disposition": attachment_disposition(filename),
            "Content-Length": str(len(blob)),
        },
    )


@router.get("/reports/{report_id}", response_model=GeneratedReportResponse)
async def get_report(
    report_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: ReportingService = Depends(_get_service),
) -> GeneratedReportResponse:
    """Get a single generated report.

    The caller must have access to the report's parent project. Reports
    owned by another tenant return 404 (not 403) to avoid leaking the
    existence of report UUIDs - same convention as
    ``verify_project_access``.
    """
    # Resolve the report first so we know which project to gate on.
    # ``service.get_report`` already raises 404 when the ID is unknown,
    # which keeps "report missing" and "access denied" indistinguishable
    # to the caller.
    report = await service.get_report(report_id)
    await verify_project_access(report.project_id, user_id, session)
    return GeneratedReportResponse.model_validate(report)


@router.post("/reports/{report_id}/publish", response_model=GeneratedReportResponse)
async def publish_report(
    report_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("reporting.distribute")),
    service: ReportingService = Depends(_get_service),
) -> GeneratedReportResponse:
    """Release a generated report to the client portal.

    Only a published report is listed and served to portal users. 404 when
    the report is missing or its project is not the caller's.
    """
    report = await service.get_report(report_id)
    await verify_project_access(report.project_id, user_id, session)
    report = await service.set_published(report_id, published=True, user_id=uuid.UUID(str(user_id)))
    return GeneratedReportResponse.model_validate(report)


@router.post("/reports/{report_id}/unpublish", response_model=GeneratedReportResponse)
async def unpublish_report(
    report_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("reporting.distribute")),
    service: ReportingService = Depends(_get_service),
) -> GeneratedReportResponse:
    """Take a report back from the client portal. Same gates as publishing."""
    report = await service.get_report(report_id)
    await verify_project_access(report.project_id, user_id, session)
    report = await service.set_published(report_id, published=False, user_id=None)
    return GeneratedReportResponse.model_validate(report)


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(
    report_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("reporting.delete")),
    service: ReportingService = Depends(_get_service),
) -> None:
    """Hard-delete a generated report. 404 if missing or if caller lacks
    access to the report's parent project (same opaque-error convention
    used by ``verify_project_access`` elsewhere).
    """
    report = await service.get_report(report_id)
    await verify_project_access(report.project_id, user_id, session)
    await service.delete_report(report_id)
