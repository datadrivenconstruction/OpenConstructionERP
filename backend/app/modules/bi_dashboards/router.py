# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""FastAPI router for the BI Dashboards module.

Mounted by the module loader at ``/api/v1/bi-dashboards/``.

Security model (v3.0.x IDOR sweep):

* **KPI endpoints** (compute / history / drill-down): if a ``project_id``
  is supplied in the body or query, the caller must own that project
  (``verify_project_access``). Project-less (portfolio) calls are scoped to
  the caller's accessible projects via ``accessible_project_ids`` and the
  ``allowed_project_ids`` set threaded into the KPI layer: a non-admin only
  ever aggregates over projects they own or are a team member of, while an
  admin (helper returns ``None``) keeps the tenant-wide portfolio view. An
  empty accessible set yields empty/zero, never every project.
* **Dashboards / Widgets / Reports / Schedules / Saved Filters**: these
  belong to a single user (``owner_user_id``). We enforce ownership
  inline: load the object, compare ``owner_user_id`` to the current user,
  raise 404 on mismatch (404 not 403 to avoid leaking existence). Widgets
  and schedules inherit ownership from their parent (dashboard / report).
* **Project dimension** (v14.9): each of those assets also carries a
  nullable ``project_id`` whose NULL means company-wide. The list
  endpoints accept an optional ``project_id`` so the project route
  ``/projects/{id}/bi-dashboards`` answers for the project in the address
  bar instead of quietly rendering the company-wide page; the answer is
  the project's own rows plus the company-wide ones. Naming a project
  requires access to it (``verify_project_access``), on reads and on
  writes alike, so the new column cannot be used to pin an asset to
  someone else's project. Ownership is unchanged either way - a project
  never widens who sees what.
* **Alerts are outside that dimension.** ``AlertRule`` has carried its own
  ``scope_project_id`` since before this, with its own audience rules, and
  ``GET /alerts`` still answers by what the caller can access rather than
  by the project in the address bar. Bringing that endpoint in line is a
  separate change: it would narrow who is notified, which is a decision
  about alerting rather than about routing.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)
from app.modules.bi_dashboards import kpi_spec, performance
from app.modules.bi_dashboards.alert_dsl import AlertExpressionError
from app.modules.bi_dashboards.models import (
    AlertRule,
    Dashboard,
    DashboardWidget,
    ReportDefinition,
    ReportSchedule,
)
from app.modules.bi_dashboards.schemas import (
    AlertRuleCreate,
    AlertRuleRead,
    BenchmarkCohort,
    BenchmarkSetCreate,
    BenchmarkSetEvaluateRequest,
    BenchmarkSetPage,
    BenchmarkSetRead,
    BenchmarkSetUpdate,
    CostIndexOptions,
    DashboardCreate,
    DashboardEvaluateRequest,
    DashboardEvaluateResponse,
    DashboardRead,
    DashboardRenderResponse,
    DashboardUpdate,
    DrillDownRequest,
    DrillDownResponse,
    KPIComputeRequest,
    KPIComputeResponse,
    KPIDefinitionCreate,
    KPIDefinitionRead,
    KPIHistoryResponse,
    PerformanceAdHocCheckRequest,
    PerformanceBenchmarkFigures,
    PerformanceBenchmarkRequest,
    PerformanceBenchmarkResponse,
    PerformanceCheckRequest,
    PerformanceCheckResponse,
    PerformanceCohortOptions,
    PerformanceCompareColumn,
    PerformanceCompareRequest,
    PerformanceCompareResponse,
    PerformanceConversion,
    PerformanceCostIndex,
    PerformanceCurrencyConversion,
    PerformanceDataQualityRequest,
    PerformanceDataQualityResponse,
    PerformanceDrilldownRequest,
    PerformanceDrilldownResponse,
    PerformanceDrillRecord,
    PerformanceEvidence,
    PerformanceGroup,
    PerformancePositionContextItem,
    PerformancePositionContextRequest,
    PerformancePositionContextResponse,
    PerformancePreset,
    PerformanceProjectLabel,
    PerformanceProjectRow,
    ReportDefinitionCreate,
    ReportDefinitionRead,
    ReportRunResponse,
    ReportScheduleCreate,
    ReportScheduleRead,
    ReportScheduleUpdate,
    SavedFilterCreate,
    SavedFilterRead,
    SavedFilterShareRequest,
    WidgetCreate,
    WidgetRead,
    WidgetUpdate,
)
from app.modules.bi_dashboards.service import (
    BIDashboardsService,
    CustomKPICodeInUse,
    CustomKPIInUse,
    CustomKPIIsSystem,
    CustomKPINotFound,
    EstimateNotFound,
    KPIScopeUnavailable,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bi_dashboards"])


def _service(session: SessionDep) -> BIDashboardsService:
    return BIDashboardsService(session)


def _user_uuid(user_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(user_id))
    except Exception:
        return None


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


# ── Ownership helpers ─────────────────────────────────────────────────


async def _verify_optional_project(
    project_id: uuid.UUID | None,
    user_id: str,
    session: SessionDep,
) -> None:
    """Access-check a project the caller named on a list endpoint.

    The list endpoints below are reachable from two routes: the plain
    module route, which names no project, and the project route, which
    does. When a project is named it is access-checked exactly the way
    the KPI endpoints check theirs - ``verify_project_access``, which
    404s on a miss or a denial rather than 403 so project UUIDs do not
    leak across tenants.

    A project-less call is left alone on purpose. These lists are already
    scoped by ownership, so unlike the cross-project KPI aggregates they
    need no ``accessible_project_ids`` fallback; adding one would remove
    rows callers see today.

    Args:
        project_id: The project named by the caller, or ``None``.
        user_id: The authenticated caller.
        session: Database session for the access check.
    """
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)


async def _is_admin(user_id: str, session: SessionDep) -> bool:
    """Return True if the supplied user is an active admin.

    Mirrors :func:`app.dependencies.verify_project_access`'s admin
    bypass logic so admins keep their cross-tenant superpowers for
    BI assets too.
    """
    try:
        from app.modules.users.repository import UserRepository

        repo = UserRepository(session)
        user = await repo.get_by_id(uuid.UUID(str(user_id)))
        return bool(user is not None and getattr(user, "role", "") == "admin")
    except Exception:
        logger.exception("admin lookup failed in bi_dashboards ownership check")
        return False


async def _ensure_dashboard_owner(
    dashboard_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
) -> Dashboard:
    """Load a dashboard and require the caller is its owner (or admin).

    Returns the dashboard for downstream use. Raises 404 on miss or
    ownership mismatch to avoid leaking dashboard UUIDs across tenants.
    Global/role-scoped dashboards (``scope in ('global', 'role')``) are
    treated as public-read but still ownership-gated for mutations -
    enforcement of read-vs-write semantics lives at the handler level.
    """
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise _not_found("Dashboard not found")
    caller = _user_uuid(user_id)
    if dashboard.owner_user_id is not None and dashboard.owner_user_id == caller:
        return dashboard
    if await _is_admin(user_id, session):
        return dashboard
    raise _not_found("Dashboard not found")


async def _ensure_dashboard_read_access(
    dashboard_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
) -> Dashboard:
    """Authorize READ access (render / evaluate), mirroring list visibility.

    Closes the read-vs-write RBAC gap: ``_ensure_dashboard_owner`` was
    gating reads too, so non-owners saw shared (global/role) dashboards in
    the grid via ``list_dashboards_visible_to`` but got 404 on open, and
    project team members with legitimate project access could never read a
    project-scoped dashboard.

    Read policy - kept in sync with
    :meth:`BIDashboardsRepository.list_dashboards_visible_to`:

    * admin                      -> allowed (cross-tenant superpower)
    * owner                      -> allowed
    * scope in ('global','role') -> allowed (shared dashboards)
    * scope == 'project'         -> require ``verify_project_access`` on the
      dashboard's ``project_id`` (team-inclusive: project owner, admin,
      team members; 404 on denial)
    * otherwise (personal/unknown, non-owner) -> 404 (IDOR-safe, no leak)

    Writes are unaffected - mutation endpoints keep ``_ensure_dashboard_owner``.
    """
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise _not_found("Dashboard not found")
    caller = _user_uuid(user_id)
    if dashboard.owner_user_id is not None and dashboard.owner_user_id == caller:
        return dashboard
    if await _is_admin(user_id, session):
        return dashboard
    scope = getattr(dashboard, "scope", None)
    if scope in ("global", "role"):
        return dashboard
    if scope == "project":
        # verify_project_access raises 404 on denial; grants owner/admin/team.
        await verify_project_access(getattr(dashboard, "project_id", None), user_id, session)
        return dashboard
    raise _not_found("Dashboard not found")


async def _ensure_widget_owner(
    widget_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
) -> DashboardWidget:
    """Load a widget and verify the caller owns its parent dashboard."""
    widget = await session.get(DashboardWidget, widget_id)
    if widget is None:
        raise _not_found("Widget not found")
    await _ensure_dashboard_owner(widget.dashboard_id, user_id, session)
    return widget


async def _ensure_report_owner(
    report_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
) -> ReportDefinition:
    """Load a report definition and require ownership (or admin)."""
    report = await session.get(ReportDefinition, report_id)
    if report is None:
        raise _not_found("Report not found")
    caller = _user_uuid(user_id)
    if report.owner_user_id is not None and report.owner_user_id == caller:
        return report
    if await _is_admin(user_id, session):
        return report
    raise _not_found("Report not found")


async def _ensure_schedule_owner(
    schedule_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
) -> ReportSchedule:
    """Load a schedule and verify the caller owns the parent report."""
    schedule = await session.get(ReportSchedule, schedule_id)
    if schedule is None:
        raise _not_found("Schedule not found")
    await _ensure_report_owner(schedule.report_definition_id, user_id, session)
    return schedule


async def _ensure_alert_access(
    alert_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
) -> AlertRule:
    """Load an alert and gate project-scoped ones to the project owner.

    Mirrors the ``create_alert`` guard: an alert carrying a
    ``scope_project_id`` is data about one project, so mutating it
    (toggle) must be restricted to a caller who can access that project
    (``verify_project_access`` - which 404s on miss/denied to avoid
    leaking UUIDs across tenants). Tenant-wide alerts
    (``scope_project_id is None``) stay gated by the route-level
    ``bi.alert.write`` permission only, matching the documented model.
    """
    alert = await session.get(AlertRule, alert_id)
    if alert is None:
        raise _not_found("Alert not found")
    if alert.scope_project_id is not None:
        await verify_project_access(alert.scope_project_id, user_id, session)
    return alert


# ── KPI ────────────────────────────────────────────────────────────────


@router.get(
    "/kpis",
    response_model=list[KPIDefinitionRead],
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def list_kpis(
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
    category: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
) -> list[KPIDefinitionRead]:
    """List the KPI library, optionally as one project sees it.

    Args:
        user_id: The authenticated caller.
        session: Database session, used for the project access check.
        service: Module service.
        category: Restrict to a single KPI category.
        project_id: The project named in the address bar. Access is
            verified the same way the compute / history endpoints below
            verify it, and the answer is that project's own definitions
            plus the company-wide ones.

    Returns:
        The KPI definitions the caller may see.
    """
    await _verify_optional_project(project_id, user_id, session)
    rows = await service.list_kpi_definitions(category=category, project_id=project_id)
    return [KPIDefinitionRead.model_validate(r) for r in rows]


@router.get(
    "/kpis/spec-catalog",
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def kpi_spec_catalog() -> dict[str, Any]:
    """The vocabulary a custom KPI spec may be written in.

    A whitelist nobody can read is a guessing game, so it is served: the
    documented entities, the fields each one exposes and their kinds, the
    aggregations and the filter operators. Everything ``POST /kpis``
    accepts appears here, and nothing else does.
    """
    return {
        "entities": kpi_spec.catalog_as_dict(),
        "aggregations": list(kpi_spec.AGGREGATIONS),
        "filter_operators": list(kpi_spec.FILTER_OPERATORS),
        "max_breakdown_groups": kpi_spec.MAX_BREAKDOWN_GROUPS,
    }


@router.get(
    "/performance/presets",
    response_model=list[PerformancePreset],
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def performance_presets() -> list[PerformancePreset]:
    """The ready-made performance KPIs, each as the spec it evaluates.

    The keys are stable and the UI names its labels after them; the spec is
    served so a reader can see exactly what a preset measures.
    """
    return [PerformancePreset(key=key, spec=spec) for key, spec in performance.VALIDATED_PRESETS.items()]


@router.get(
    "/performance/cohort-options",
    response_model=PerformanceCohortOptions,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def performance_cohort_options(user_id: CurrentUserId, session: SessionDep) -> PerformanceCohortOptions:
    """The client, region and project type values a cohort can be filtered by.

    Read from the projects the caller may open and nothing else, so the list
    of clients is not a list of everyone the company works for.
    """
    accessible = await accessible_project_ids(session, user_id, live_only=True)
    return PerformanceCohortOptions(
        **await performance.cohort_options(session, accessible or set()),
        project_splits=list(performance.PROJECT_SPLITS),
    )


def _spec_error(exc: kpi_spec.KPISpecError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.as_dict())


def _top_by_error() -> HTTPException:
    return _spec_error(
        kpi_spec.KPISpecError(
            "spec.aggregation",
            "'top_by' names a row, not a measure, so it has no per-project value to benchmark.",
            value="top_by",
        )
    )


async def _resolve_benchmark_spec(
    session: SessionDep,
    *,
    kpi: str | None,
    spec: dict[str, Any] | None,
    row_filters: list[dict[str, Any]],
) -> dict[str, Any]:
    """The validated spec of a request, with its row filters, or the HTTP error."""
    try:
        resolved = await performance.resolve_spec(session, kpi=kpi, spec=spec)
        if resolved["aggregation"] == "top_by":
            raise _top_by_error()
        return performance.with_row_filters(resolved, row_filters)
    except kpi_spec.KPISpecError as exc:
        raise _spec_error(exc) from exc
    except performance.UnknownPerformanceKPI as exc:
        raise _not_found(f"Unknown performance KPI: {exc.code}") from exc


async def _cohort_projects(session: SessionDep, user_id: str, cohort: BenchmarkCohort) -> set[uuid.UUID]:
    """The cohort's projects: requested, narrowed to what the caller may open, then filtered."""
    accessible = await accessible_project_ids(session, user_id, live_only=True)
    projects = performance.resolve_cohort(cohort.project_ids, accessible or set())
    projects -= set(cohort.exclude_project_ids)
    return await performance.filter_projects(
        session,
        projects,
        clients=cohort.clients,
        regions=cohort.regions,
        project_types=cohort.project_types,
        statuses=cohort.statuses,
    )


def _split_or_error(spec: dict[str, Any], split_by: str | None) -> performance.Split | None:
    try:
        return performance.resolve_split(spec, split_by)
    except kpi_spec.KPISpecError as exc:
        raise _spec_error(exc) from exc


async def _fx_or_none(
    session: SessionDep, reporting_currency: str | None, on_date: Any = None
) -> performance.FxRates | None:
    if not reporting_currency:
        return None
    return await performance.load_fx_rates(session, reporting_currency, on_date=on_date)


async def _cost_index_or_none(session: SessionDep, options: CostIndexOptions | None) -> performance.CostIndex | None:
    """The register's series and regional factors a request names; 422 when it lacks them."""
    if options is None:
        return None
    try:
        return await performance.load_cost_index(
            session,
            series_id=options.index_series_id,
            target_period=options.index_target_period,
            target_region=options.location_target_region,
        )
    except performance.CostIndexError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _cost_index_read(index: performance.CostIndex | None, spec: dict[str, Any]) -> PerformanceCostIndex | None:
    if index is None:
        return None
    return PerformanceCostIndex(
        series_id=index.series_id,
        series_name=index.series_name,
        target_period=index.target_period,
        target_region=index.target_region,
        target_region_factor=index.target_region_factor,
        applicable=performance.cost_index_applies(spec),
    )


def _unconverted(groups: list[performance.BenchmarkGroup], fx: performance.FxRates | None) -> list[str]:
    if fx is None:
        return []
    return sorted(performance.reading_currencies(groups) - {fx.to_currency})


async def _run_benchmark(
    session: SessionDep,
    user_id: str,
    *,
    kpi: str | None,
    spec: dict[str, Any],
    cohort: BenchmarkCohort,
    convert_units: bool,
    min_projects: int,
    min_records: int,
    statistic: str,
    split_by: str | None = None,
    reporting_currency: str | None = None,
    fx_date: Any = None,
    cost_index: CostIndexOptions | None = None,
) -> PerformanceBenchmarkResponse:
    """One benchmark, from a request or a saved set: the single place both run."""
    split = _split_or_error(spec, split_by)
    fx = await _fx_or_none(session, reporting_currency, fx_date)
    index = await _cost_index_or_none(session, cost_index)
    projects = await _cohort_projects(session, user_id, cohort)
    groups = await performance.benchmark(
        session,
        spec=spec,
        cohort=projects,
        period_start=cohort.period_start,
        period_end=cohort.period_end,
        convert=convert_units,
        split=split,
        fx=fx,
        cost_index=index,
    )
    kept, omitted = performance.cap_groups(groups)
    selected = len(projects)
    with_data = {r.project_id for g in groups for r in g.readings}
    return PerformanceBenchmarkResponse(
        kpi=kpi,
        spec=spec,
        aggregation=spec["aggregation"],
        projects_selected=selected,
        projects=[PerformanceProjectLabel(**p) for p in await performance.project_labels(session, projects)],
        groups=[
            _performance_group(
                g, selected, spec=spec, statistic=statistic, min_projects=min_projects, min_records=min_records
            )
            for g in kept
        ],
        convert_units=convert_units,
        min_projects=min_projects,
        min_records=min_records,
        statistic=statistic,
        split_by=split.name if split else None,
        reporting_currency=fx.to_currency if fx else None,
        currencies_unconverted=_unconverted(groups, fx),
        cost_index=_cost_index_read(index, spec),
        groups_omitted=omitted,
        projects_without_data=max(0, selected - len(with_data)),
    )


@router.post(
    "/performance/benchmark",
    response_model=PerformanceBenchmarkResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def performance_benchmark(
    payload: PerformanceBenchmarkRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PerformanceBenchmarkResponse:
    """Read one KPI per project over a cohort and benchmark the cohort.

    The cohort is the requested projects intersected with those the caller
    can open (every such project when none is requested), then narrowed by
    client, region and project type. A project outside that set is dropped
    without a trace in the response, so naming a project id here reveals
    nothing about it, not even whether it exists.

    Each unit and currency the KPI spans is its own group, with per-project
    values, the weighted benchmark (a ratio of sums for a ratio KPI), the
    mean, median and P25-P75 over projects, the evidence behind them, and
    coverage: projects with a value over projects selected. With
    ``convert_units`` compatible units share a group and each conversion is
    listed; a group below ``min_projects`` or ``min_records`` is flagged as
    not a reliable benchmark.

    Args:
        payload: Cohort, KPI, optional period and reading options.
        user_id: The authenticated caller.
        session: Database session.

    Returns:
        The benchmark, one group per unit/currency partition.
    """
    spec = await _resolve_benchmark_spec(session, kpi=payload.kpi, spec=payload.spec, row_filters=payload.row_filters)
    return await _run_benchmark(
        session,
        user_id,
        kpi=payload.kpi,
        spec=spec,
        cohort=payload,
        convert_units=payload.convert_units,
        min_projects=payload.min_projects,
        min_records=payload.min_records,
        statistic=payload.statistic,
        split_by=payload.split_by,
        reporting_currency=payload.reporting_currency,
        fx_date=payload.fx_date,
        cost_index=payload,
    )


def _variance(value: Decimal | None, lead: Decimal | None) -> Decimal | None:
    if value is None or lead is None or lead == 0:
        return None
    return (value - lead) / lead


def _performance_group(
    group: performance.BenchmarkGroup,
    selected: int,
    *,
    spec: dict[str, Any] | None = None,
    statistic: str = "weighted",
    min_projects: int = 0,
    min_records: int = 0,
) -> PerformanceGroup:
    summary = group.summary or performance.summarise(group.readings, "")
    lead, used = performance.headline(summary, statistic)
    shortfall = performance.evidence_shortfall(summary, min_projects=min_projects, min_records=min_records)
    return PerformanceGroup(
        key=group.key,
        dimensions=group.dimensions,
        rows=[
            PerformanceProjectRow(
                project_id=r.project_id,
                value=r.value,
                numerator=r.numerator,
                denominator=r.denominator,
                records=r.records,
                unavailable_reason=r.unavailable_reason,
                converted_from=list(r.converted_from),
                variance=_variance(r.value, lead),
                converted_from_currency=list(r.converted_from_currency),
                original_value=r.original_value,
                original_currency=r.original_currency,
                fx_rate=r.fx_rate,
                index_series=r.index_series,
                index_base_periods=list(r.index_base_periods),
                index_target_period=r.index_target_period,
                index_factor=r.index_factor,
                index_missing_periods=list(r.index_missing_periods),
                location_region=r.location_region,
                location_factor=r.location_factor,
                unadjusted_value=r.unadjusted_value,
            )
            for r in group.readings
        ],
        benchmark=PerformanceBenchmarkFigures(
            weighted=summary.weighted,
            weighted_unavailable_reason=summary.weighted_unavailable_reason,
            mean=summary.mean,
            median=summary.median,
            p25=summary.p25,
            p75=summary.p75,
            min=summary.minimum,
            max=summary.maximum,
            p10=summary.p10,
            p90=summary.p90,
            stddev=summary.stddev,
            cv=summary.cv,
        ),
        evidence=PerformanceEvidence(
            projects_with_data=summary.projects_with_data,
            projects_with_value=summary.projects_with_value,
            records=summary.records,
            records_with_value=summary.records_with_value,
        ),
        coverage=(
            (Decimal(summary.projects_with_value) / Decimal(selected)).quantize(Decimal("0.0001"))
            if selected
            else Decimal("0")
        ),
        conversions=[
            PerformanceConversion(from_unit=c.from_unit, to_unit=c.to_unit, factor=c.factor) for c in group.conversions
        ],
        currency_conversions=[
            PerformanceCurrencyConversion(
                from_currency=c.from_currency,
                to_currency=c.to_currency,
                rate=c.rate,
                as_of=c.as_of,
                source=c.source,
            )
            for c in group.currency_conversions
        ],
        value_unit=performance.value_unit(spec, group.dimensions) if spec else None,
        excluded=dict(summary.excluded),
        headline=lead,
        headline_statistic=used,
        sufficient=not shortfall,
        shortfall=shortfall,
    )


# ── Benchmark sets ─────────────────────────────────────────────────────


def _benchmark_set_read(row: Any, viewer: uuid.UUID | None) -> BenchmarkSetRead:
    return BenchmarkSetRead(
        id=row.id,
        name=row.name,
        description=row.description or "",
        owner_user_id=row.owner_user_id,
        scope=row.scope,
        kpis=list(row.kpis_json or []),
        cohort=BenchmarkCohort.model_validate(row.cohort_json or {}),
        statistic=row.statistic,
        min_projects=row.min_projects,
        min_records=row.min_records,
        convert_units=bool(row.convert_units),
        split_by=row.split_by,
        reporting_currency=row.reporting_currency,
        is_owner=viewer is not None and row.owner_user_id == viewer,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _definition_error(exc: Exception) -> HTTPException:
    if isinstance(exc, performance.UnknownPerformanceKPI):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "unknown_kpi", "path": "kpis", "value": exc.code},
        )
    assert isinstance(exc, kpi_spec.KPISpecError)
    return _spec_error(exc)


@router.get(
    "/performance/benchmark-sets",
    response_model=BenchmarkSetPage,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def list_benchmark_sets(
    user_id: CurrentUserId,
    service: BIDashboardsService = Depends(_service),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> BenchmarkSetPage:
    """The caller's own benchmark sets and every shared one, by name."""
    viewer = _user_uuid(user_id)
    rows = await service.list_benchmark_sets(viewer_user_id=viewer)
    return BenchmarkSetPage(
        items=[_benchmark_set_read(r, viewer) for r in rows[offset : offset + limit]],
        total=len(rows),
        offset=offset,
        limit=limit,
    )


@router.post(
    "/performance/benchmark-sets",
    response_model=BenchmarkSetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bi.filter.write"))],
)
async def create_benchmark_set(
    payload: BenchmarkSetCreate,
    user_id: CurrentUserId,
    service: BIDashboardsService = Depends(_service),
) -> BenchmarkSetRead:
    """Save a named benchmark: cohort, KPIs, minimum evidence and the leading statistic.

    Every KPI must exist and every row filter must fit every KPI's entity,
    so a saved set cannot fail the first time it is read.
    """
    viewer = _user_uuid(user_id)
    try:
        row = await service.create_benchmark_set(payload, owner_user_id=viewer)
    except (kpi_spec.KPISpecError, performance.UnknownPerformanceKPI) as exc:
        raise _definition_error(exc) from exc
    return _benchmark_set_read(row, viewer)


@router.get(
    "/performance/benchmark-sets/{set_id}",
    response_model=BenchmarkSetRead,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def get_benchmark_set(
    set_id: uuid.UUID,
    user_id: CurrentUserId,
    service: BIDashboardsService = Depends(_service),
) -> BenchmarkSetRead:
    """One benchmark set the caller owns or that is shared."""
    viewer = _user_uuid(user_id)
    row = await service.get_visible_benchmark_set(set_id, viewer_user_id=viewer)
    if row is None:
        raise _not_found("Benchmark set not found")
    return _benchmark_set_read(row, viewer)


@router.patch(
    "/performance/benchmark-sets/{set_id}",
    response_model=BenchmarkSetRead,
    dependencies=[Depends(RequirePermission("bi.filter.write"))],
)
async def update_benchmark_set(
    set_id: uuid.UUID,
    payload: BenchmarkSetUpdate,
    user_id: CurrentUserId,
    service: BIDashboardsService = Depends(_service),
) -> BenchmarkSetRead:
    """Edit a set the caller owns. Anyone else's set is a 404, shared or not."""
    viewer = _user_uuid(user_id)
    try:
        row = await service.update_benchmark_set(set_id, payload, owner_user_id=viewer)
    except (kpi_spec.KPISpecError, performance.UnknownPerformanceKPI) as exc:
        raise _definition_error(exc) from exc
    if row is None:
        raise _not_found("Benchmark set not found")
    return _benchmark_set_read(row, viewer)


@router.delete(
    "/performance/benchmark-sets/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("bi.filter.write"))],
)
async def delete_benchmark_set(
    set_id: uuid.UUID,
    user_id: CurrentUserId,
    service: BIDashboardsService = Depends(_service),
) -> None:
    """Delete a set the caller owns. Anyone else's set is a 404, shared or not."""
    if not await service.delete_benchmark_set(set_id, owner_user_id=_user_uuid(user_id)):
        raise _not_found("Benchmark set not found")


async def _visible_set_and_spec(
    set_id: uuid.UUID,
    kpi: str | None,
    user_id: str,
    session: SessionDep,
    service: BIDashboardsService,
) -> tuple[Any, str, dict[str, Any], BenchmarkCohort]:
    row = await service.get_visible_benchmark_set(set_id, viewer_user_id=_user_uuid(user_id))
    if row is None:
        raise _not_found("Benchmark set not found")
    kpis = list(row.kpis_json or [])
    code = kpi or (kpis[0] if kpis else "")
    if code not in kpis:
        raise _not_found(f"KPI {code!r} is not part of this benchmark set")
    cohort = BenchmarkCohort.model_validate(row.cohort_json or {})
    spec = await _resolve_benchmark_spec(session, kpi=code, spec=None, row_filters=cohort.row_filters)
    return row, code, spec, cohort


@router.post(
    "/performance/benchmark-sets/{set_id}/evaluate",
    response_model=PerformanceBenchmarkResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def evaluate_benchmark_set(
    set_id: uuid.UUID,
    payload: BenchmarkSetEvaluateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> PerformanceBenchmarkResponse:
    """Read one of a saved set's KPIs over its cohort, as the reader may see it.

    Computed fresh on every call, over the set's cohort intersected with the
    projects the reader may open, so the same shared set can show two
    colleagues two different populations and never shows either one a
    project they could not open.
    """
    row, code, spec, cohort = await _visible_set_and_spec(set_id, payload.kpi, user_id, session, service)
    return await _run_benchmark(
        session,
        user_id,
        kpi=code,
        spec=spec,
        cohort=cohort,
        convert_units=bool(row.convert_units),
        min_projects=row.min_projects,
        min_records=row.min_records,
        statistic=row.statistic,
        split_by=row.split_by,
        reporting_currency=row.reporting_currency,
    )


async def _check_estimate(
    session: SessionDep,
    user_id: str,
    *,
    code: str,
    spec: dict[str, Any],
    cohort: BenchmarkCohort,
    convert_units: bool,
    statistic: str,
    min_projects: int,
    min_records: int,
    value: Decimal | None,
    unit: str | None,
    currency: str | None,
    boq_position_id: uuid.UUID | None,
    split_by: str | None = None,
    split_value: str | None = None,
    reporting_currency: str | None = None,
    fx_date: Any = None,
    cost_index: CostIndexOptions | None = None,
) -> PerformanceCheckResponse:
    """Place one estimate in a cohort's range: the single place both check routes run.

    With a split the estimate is compared with the groups of ``split_value``
    only (a check under the "330" card is against 330, not every m2 job).
    """
    if boq_position_id is not None:
        accessible = await accessible_project_ids(session, user_id, live_only=True)
        found = await performance.position_estimate(session, boq_position_id, spec, accessible or set())
        if found is None:
            raise _not_found("Position not found")
        if isinstance(found, str):
            return PerformanceCheckResponse(kpi=code, status=found)
        value, unit, currency = found
    assert value is not None

    split = _split_or_error(spec, split_by)
    fx = await _fx_or_none(session, reporting_currency, fx_date)
    index = await _cost_index_or_none(session, cost_index)
    projects = await _cohort_projects(session, user_id, cohort)
    groups = await performance.benchmark(
        session,
        spec=spec,
        cohort=projects,
        period_start=cohort.period_start,
        period_end=cohort.period_end,
        convert=convert_units,
        split=split,
        fx=fx,
        cost_index=index,
    )
    if split is not None:
        wanted = split_value if split_value not in ("", kpi_spec.NULL_GROUP_KEY) else None
        groups = [g for g in groups if g.dimensions.get(split.name) == wanted]
    if fx is not None and currency and currency.strip().upper() in fx.rates:
        # An estimate in another currency is compared in the reporting one.
        rate = fx.rates[currency.strip().upper()]
        value = value * rate if performance.currency_value_exponent(spec) == 1 else value
        currency = fx.to_currency
    match = performance.find_group(groups, unit=unit, currency=currency)
    base = {
        "kpi": code,
        "input_value": value,
        "input_unit": unit,
        "input_currency": currency,
        "cost_index": _cost_index_read(index, spec),
    }
    if match is None:
        return PerformanceCheckResponse(status=performance.CHECK_NO_GROUP, **base)
    group, from_unit = match
    check = performance.check_value(
        group,
        value,
        spec=spec,
        from_unit=from_unit,
        statistic=statistic,
        min_projects=min_projects,
        min_records=min_records,
    )
    return PerformanceCheckResponse(
        status="ok",
        value=check.value,
        unit_factor=check.unit_factor,
        group=_performance_group(
            group,
            len(projects),
            spec=spec,
            statistic=statistic,
            min_projects=min_projects,
            min_records=min_records,
        ),
        headline=check.headline,
        statistic=check.statistic,
        variance=check.variance,
        percentile_rank=check.percentile_rank,
        band=check.band,
        confidence=check.confidence,
        shortfall=check.shortfall,
        **base,
    )


@router.post(
    "/performance/benchmark-sets/{set_id}/check",
    response_model=PerformanceCheckResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def check_against_benchmark_set(
    set_id: uuid.UUID,
    payload: PerformanceCheckRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> PerformanceCheckResponse:
    """Where an estimate sits in a benchmark set's historical range.

    The estimate is a value the estimator typed, or a bill position's own
    figure (its unit rate, or the labour hours per unit of its resource
    split). It is compared with the group of the same currency whose unit is
    the same or converts to it, and placed against the range with a
    percentile rank, the variance from the set's leading figure, the sample
    size and a confidence that follows the number of projects behind it.

    This is a suggestion for a person to weigh. Nothing is written: not the
    position, not the rate, not the set.
    """
    row, code, spec, cohort = await _visible_set_and_spec(set_id, payload.kpi, user_id, session, service)
    return await _check_estimate(
        session,
        user_id,
        code=code,
        spec=spec,
        cohort=cohort,
        convert_units=bool(row.convert_units),
        statistic=row.statistic,
        min_projects=row.min_projects,
        min_records=row.min_records,
        value=payload.value,
        unit=payload.unit,
        currency=payload.currency,
        boq_position_id=payload.boq_position_id,
        cost_index=payload,
    )


@router.post(
    "/performance/check",
    response_model=PerformanceCheckResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def check_against_cohort(
    payload: PerformanceAdHocCheckRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PerformanceCheckResponse:
    """The same check as for a saved set, against a cohort described in the request.

    So the estimator who is looking at a benchmark on screen can test a
    number against exactly that screen without saving it first. Nothing is
    written.
    """
    spec = await _resolve_benchmark_spec(session, kpi=payload.kpi, spec=payload.spec, row_filters=payload.row_filters)
    return await _check_estimate(
        session,
        user_id,
        code=payload.kpi or "",
        spec=spec,
        cohort=payload,
        convert_units=payload.convert_units,
        statistic=payload.statistic,
        min_projects=payload.min_projects,
        min_records=payload.min_records,
        value=payload.value,
        unit=payload.unit,
        currency=payload.currency,
        boq_position_id=payload.boq_position_id,
        split_by=payload.split_by,
        split_value=payload.split_value,
        reporting_currency=payload.reporting_currency,
        fx_date=payload.fx_date,
        cost_index=payload,
    )


@router.post(
    "/performance/compare",
    response_model=PerformanceCompareResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def compare_projects(
    payload: PerformanceCompareRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PerformanceCompareResponse:
    """Several KPIs side by side, one row per project and one column per KPI group.

    The cohort is resolved once (requested, narrowed to what the caller may
    open, filtered) and every KPI is read over exactly that set with one
    grouped query each, never once per project. A KPI spanning several units
    or currencies gives one column per group, the largest first, at most
    :data:`COMPARE_GROUPS_PER_KPI`; the rest are counted.
    """
    specs: list[tuple[str, dict[str, Any]]] = []
    for code in payload.kpis:
        specs.append(
            (code, await _resolve_benchmark_spec(session, kpi=code, spec=None, row_filters=payload.row_filters))
        )
    fx = await _fx_or_none(session, payload.reporting_currency, payload.fx_date)
    index = await _cost_index_or_none(session, payload)
    projects = await _cohort_projects(session, user_id, payload)
    selected = len(projects)
    columns: list[PerformanceCompareColumn] = []
    omitted: dict[str, int] = {}
    unconverted: set[str] = set()
    for code, spec in specs:
        groups = await performance.benchmark(
            session,
            spec=spec,
            cohort=projects,
            period_start=payload.period_start,
            period_end=payload.period_end,
            convert=payload.convert_units,
            fx=fx,
            cost_index=index,
        )
        unconverted.update(_unconverted(groups, fx))
        kept, extra = performance.cap_groups(groups, COMPARE_GROUPS_PER_KPI)
        if extra:
            omitted[code] = extra
        columns.extend(
            PerformanceCompareColumn(
                kpi=code,
                aggregation=spec["aggregation"],
                group=_performance_group(
                    g,
                    selected,
                    spec=spec,
                    statistic=payload.statistic,
                    min_projects=payload.min_projects,
                    min_records=payload.min_records,
                ),
            )
            for g in kept
        )
    return PerformanceCompareResponse(
        projects_selected=selected,
        projects=[PerformanceProjectLabel(**p) for p in await performance.project_labels(session, projects)],
        columns=columns,
        groups_omitted=omitted,
        reporting_currency=fx.to_currency if fx else None,
        currencies_unconverted=sorted(unconverted),
        statistic=payload.statistic,
        cost_index=_cost_index_read(index, specs[0][1]) if index is not None else None,
    )


@router.post(
    "/performance/data-quality",
    response_model=PerformanceDataQualityResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def performance_data_quality(
    payload: PerformanceDataQualityRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PerformanceDataQualityResponse:
    """How much of the cohort's site data a productivity benchmark can use.

    Counted hours and the share booked against a bill position, priced
    positions and the share with reported progress, and, for a classification
    standard, the share of positions carrying a code under it. Over the same
    cohort a benchmark reads, so the figures describe the evidence behind it.
    """
    projects = await _cohort_projects(session, user_id, payload)
    found = await performance.data_quality(
        session,
        projects,
        period_start=payload.period_start,
        period_end=payload.period_end,
        classification_key=payload.classification_key,
    )
    return PerformanceDataQualityResponse(**found.__dict__)


@router.post(
    "/performance/drilldown",
    response_model=PerformanceDrilldownResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def performance_drilldown(
    payload: PerformanceDrilldownRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PerformanceDrilldownResponse:
    """The records behind one project's reading, a page at a time, with totals that reconcile.

    The project must be one the caller may open; any other id is a 404,
    whether it exists or not. The totals are summed in SQL over every
    matching record and restated into the group's unit and currency the way
    the benchmark restated the reading, so they equal that reading's
    numerator and denominator.
    """
    accessible = await accessible_project_ids(session, user_id, live_only=True)
    if payload.project_id not in (accessible or set()):
        raise _not_found("Project not found")
    spec = await _resolve_benchmark_spec(session, kpi=payload.kpi, spec=payload.spec, row_filters=payload.row_filters)
    split = _split_or_error(spec, payload.split_by)
    fx = await _fx_or_none(session, payload.reporting_currency, payload.fx_date)
    index = await _cost_index_or_none(session, payload)
    region: str | None = None
    if index is not None and index.target_region:
        region = (await performance.project_regions(session, {payload.project_id})).get(payload.project_id)
    try:
        found = await performance.drilldown(
            session,
            spec,
            project_id=payload.project_id,
            dimensions=payload.dimensions,
            split=split,
            target_unit=payload.target_unit or None,
            fx=fx,
            period_start=payload.period_start,
            period_end=payload.period_end,
            offset=payload.offset,
            limit=payload.limit,
            cost_index=index,
            project_region=region,
        )
    except ImportError:
        found = performance.DrillResult(
            records=[],
            total_records=0,
            numerator=None,
            denominator=None,
            value=None,
            unavailable_reason=kpi_spec.UNAVAILABLE_NO_DATA,
        )
    group_dims: dict[str, str | None] = {}
    if payload.target_unit:
        group_dims[performance.UNIT_DIMENSION] = payload.target_unit
    if fx is not None:
        group_dims[performance.CURRENCY_DIMENSION] = fx.to_currency
    elif payload.dimensions.get(performance.CURRENCY_DIMENSION):
        group_dims[performance.CURRENCY_DIMENSION] = payload.dimensions[performance.CURRENCY_DIMENSION][0]
    return PerformanceDrilldownResponse(
        project_id=payload.project_id,
        kpi=payload.kpi,
        aggregation=spec["aggregation"],
        total_records=found.total_records,
        numerator=found.numerator,
        denominator=found.denominator,
        value=found.value,
        unavailable_reason=found.unavailable_reason,
        value_unit=performance.value_unit(spec, group_dims),
        offset=payload.offset,
        limit=payload.limit,
        records=[
            PerformanceDrillRecord(
                record_id=r.record_id,
                boq_id=_uuid_or_none(r.boq_id),
                position_id=_uuid_or_none(r.position_id),
                ref=r.ref,
                description=r.description,
                dimensions=r.dimensions,
                numerator=r.numerator,
                denominator=r.denominator,
                counted_numerator=r.counted_numerator,
                counted_denominator=r.counted_denominator,
                index_factor=r.index_factor,
            )
            for r in found.records
        ],
    )


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


@router.post(
    "/performance/position-context",
    response_model=PerformancePositionContextResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def performance_position_context(
    payload: PerformancePositionContextRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PerformancePositionContextResponse:
    """Historical context for bill positions, as an extra source of evidence beside market data.

    Each position is compared with past positions carrying the same
    classification code (under the standard the positions use most, unless one
    is named) in a unit that is the same or converts, across the projects the
    caller may open other than the positions' own. Read with one grouped query
    whatever the number of positions. A position the caller may not open is
    left out of the answer. Nothing is written: not the position, not its rate.
    """
    spec = await _resolve_benchmark_spec(session, kpi=payload.kpi, spec=None, row_filters=[])
    accessible = await accessible_project_ids(session, user_id, live_only=True)
    try:
        key, contexts = await performance.position_context(
            session,
            spec,
            position_ids=payload.position_ids,
            accessible=accessible or set(),
            classification_key=payload.classification_key,
            include_own_projects=payload.include_own_projects,
            convert=payload.convert_units,
            statistic=payload.statistic,
            min_projects=payload.min_projects,
            min_records=payload.min_records,
        )
    except kpi_spec.KPISpecError as exc:
        raise _spec_error(exc) from exc
    items: list[PerformancePositionContextItem] = []
    for ctx in contexts:
        item = PerformancePositionContextItem(
            position_id=ctx.position_id,
            status=ctx.status,
            classification_code=ctx.classification_code,
            unit=ctx.unit,
            currency=ctx.currency,
            estimate=ctx.estimate,
        )
        check = ctx.check
        if check is not None:
            summary = check.group.summary or performance.summarise(check.group.readings, spec["aggregation"])
            item.value = check.value
            item.value_unit = performance.value_unit(spec, check.group.dimensions)
            item.headline = check.headline
            item.statistic = check.statistic
            item.median = summary.median
            item.p25 = summary.p25
            item.p75 = summary.p75
            item.variance = check.variance
            item.percentile_rank = check.percentile_rank
            item.band = check.band
            item.confidence = check.confidence
            item.projects = summary.projects_with_value
            item.records = summary.records_with_value
            item.shortfall = list(check.shortfall)
        items.append(item)
    return PerformancePositionContextResponse(kpi=payload.kpi, classification_key=key, items=items)


#: Columns one KPI may contribute to a comparison; a KPI read in m2, m3, m
#: and pcs is four columns already, and more stop being a comparison.
COMPARE_GROUPS_PER_KPI = 4


@router.post(
    "/kpis",
    response_model=KPIDefinitionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bi.kpi.write"))],
)
async def create_kpi(
    payload: KPIDefinitionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> KPIDefinitionRead:
    """Register a custom KPI from a whitelisted spec.

    The spec is checked now, not at compute time, so a definition that is
    accepted here is one that will produce a number rather than one that
    will read zero forever. A rejection carries the path into the spec
    that failed (``spec.field``, ``spec.filters[0].op``) together with the
    vocabulary that path accepts.

    Args:
        payload: The definition, including its ``spec``. A ``project_id``
            pins the KPI to one project; omitting it leaves it
            company-wide.
        user_id: The authenticated caller.
        session: Database session, used for the project access check.
        service: Module service.

    Returns:
        The created KPI definition.
    """
    await _verify_optional_project(payload.project_id, user_id, session)
    try:
        row = await service.create_custom_kpi(payload)
    except kpi_spec.KPISpecError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.as_dict(),
        ) from exc
    except CustomKPICodeInUse as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "kpi_code_in_use", "code": exc.code, "message": str(exc)},
        ) from exc
    return KPIDefinitionRead.model_validate(row)


@router.delete(
    "/kpis/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("bi.kpi.write"))],
)
async def delete_kpi(
    code: str,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> None:
    """Delete a custom KPI definition.

    Refused with 409 while any widget, alert rule or report definition
    still names the code. Nothing in the schema stops the row from going -
    the code is held as data, because it may equally be served by a
    built-in formula that has no row at all - so the referential answer is
    given here, and it names every referrer so the user can act on them
    instead of hunting for what broke.

    A definition pinned to a project is access-checked against that
    project the same way :func:`create_kpi` checks the one it pins to.
    Codes are globally unique, so leaving that out let any holder of
    ``bi.kpi.write`` delete another project's KPI.

    Args:
        code: The KPI code to delete.
        user_id: The authenticated caller.
        session: Database session, used for the project access check.
        service: Module service.
    """
    try:
        await service.delete_custom_kpi(code, user_id=user_id)
    except CustomKPINotFound as exc:
        raise _not_found("KPI definition not found") from exc
    except CustomKPIIsSystem as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "kpi_is_system", "code": code, "message": str(exc)},
        ) from exc
    except CustomKPIInUse as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "kpi_in_use",
                "code": code,
                "message": str(exc),
                "widget_ids": [str(w) for w in exc.referrers.get("widgets", [])],
                "alert_rule_ids": [str(a) for a in exc.referrers.get("alerts", [])],
                "report_definition_ids": [str(r) for r in exc.referrers.get("reports", [])],
            },
        ) from exc


@router.post(
    "/kpis/{code}/compute",
    response_model=KPIComputeResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.compute"))],
)
async def compute_kpi(
    code: str,
    payload: KPIComputeRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> KPIComputeResponse:
    # IDOR guard - if the caller asks for a project-scoped computation,
    # verify they own that project. A project-less (portfolio) call is
    # scoped to the caller's accessible projects so a non-admin cannot
    # aggregate across every tenant's projects (admins get None = no filter).
    #
    # An estimate is not a second, independent way to name a row set. It is
    # resolved to the project that owns it and THAT project is access-checked,
    # because ``allowed_project_ids`` knows nothing about estimate ids: an
    # estimate-scoped query adds its predicate alongside a project predicate
    # the rows already satisfy, so an unresolved estimate id would read
    # another tenant's bill through a call that looks scoped.
    project_id = payload.project_id
    if payload.boq_id is not None:
        try:
            owner = await service.estimate_owner_project(payload.boq_id)
        except EstimateNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "estimate_not_found", "boq_id": str(payload.boq_id), "message": str(exc)},
            ) from exc
        if project_id is not None and project_id != owner:
            # Two scopes that disagree. Silently preferring either one
            # answers a question the caller did not ask, and the reading
            # would look ordinary.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "scope_conflict",
                    "message": (
                        f"estimate {payload.boq_id} belongs to project {owner}, not to the "
                        f"requested project {project_id}."
                    ),
                },
            )
        project_id = owner

    allowed: set[uuid.UUID] | None = None
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    else:
        # A portfolio KPI counts live projects only: a deleted (archived)
        # project is not part of it, for admins either.
        allowed = await accessible_project_ids(session, user_id, live_only=True)
    try:
        return await service.compute_kpi(
            code,
            project_id=project_id,
            boq_id=payload.boq_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            filters=payload.filters,
            persist=payload.persist,
            allowed_project_ids=allowed,
        )
    except KPIScopeUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "kpi_scope_unavailable", "code": exc.code, "message": str(exc)},
        ) from exc
    except CustomKPINotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "kpi_not_found", "code": exc.code, "message": str(exc)},
        ) from exc


@router.get(
    "/kpis/{code}/history",
    response_model=KPIHistoryResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def kpi_history(
    code: str,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
    project_id: uuid.UUID | None = Query(default=None),
    boq_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=24, ge=1, le=500),
) -> KPIHistoryResponse:
    # Same portfolio IDOR scope as compute_kpi: a specific project is
    # access-checked; a project-less history is scoped to the caller's
    # accessible projects (admins get None = unrestricted). And the same
    # rule for an estimate: resolved to its owning project, which is what
    # gets checked.
    if boq_id is not None:
        try:
            owner = await service.estimate_owner_project(boq_id)
        except EstimateNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "estimate_not_found", "boq_id": str(boq_id), "message": str(exc)},
            ) from exc
        if project_id is not None and project_id != owner:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "scope_conflict",
                    "message": f"estimate {boq_id} belongs to project {owner}, not to the requested project.",
                },
            )
        project_id = owner
    allowed: set[uuid.UUID] | None = None
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    else:
        allowed = await accessible_project_ids(session, user_id)
    points = await service.kpi_history(
        code,
        project_id=project_id,
        boq_id=boq_id,
        limit=limit,
        allowed_project_ids=allowed,
    )
    return KPIHistoryResponse(kpi_code=code, history=points)


@router.get(
    "/kpi-freshness",
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def kpi_freshness(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID | None = Query(default=None),
) -> dict[str, str | None]:
    """Return the live KPI/EVM freshness watermark for a project.

    Upstream data changes (cost, schedule progress, finance, contracts) bump an
    in-process watermark. The frontend polls this cheap endpoint; when
    ``invalidated_at`` advances past the value it last saw, it refetches the
    heavier live EVM/KPI payloads. This is the event-driven live-refresh signal,
    so the UI updates within seconds of an upstream change without a WebSocket.
    """
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    from app.modules.bi_dashboards.events import get_kpi_freshness

    return get_kpi_freshness(str(project_id) if project_id else None)


@router.post(
    "/kpis/{code}/drill-down",
    response_model=DrillDownResponse,
    dependencies=[Depends(RequirePermission("bi.kpi.read"))],
)
async def drill_down(
    code: str,
    payload: DrillDownRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> DrillDownResponse:
    # Same portfolio IDOR scope as compute_kpi: a specific project is
    # access-checked; a project-less drill-down is scoped to the caller's
    # accessible live projects, the same set compute_kpi counts.
    allowed: set[uuid.UUID] | None = None
    if payload.project_id is not None:
        await verify_project_access(payload.project_id, user_id, session)
    else:
        allowed = await accessible_project_ids(session, user_id, live_only=True)
    result = await service.drill_down(
        code,
        project_id=payload.project_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        filters=payload.filters,
        depth=payload.depth,
        limit=payload.limit,
        allowed_project_ids=allowed,
    )
    return DrillDownResponse(
        kpi_code=result["kpi_code"],
        records=result["records"],
        record_count=result["record_count"],
        aggregate_value=result.get("aggregate_value"),
        aggregate_unit=result.get("aggregate_unit"),
    )


# ── Dashboards ─────────────────────────────────────────────────────────


# v3.12.1 Wave 1 - fresh-install dashboards bootstrap. The page used
# to render an empty grid on every new tenant because the seed_all()
# helper that materialises the 5 role-based starter dashboards was only
# called from tests. Exposing it as an idempotent POST lets the FE
# offer a one-click "Install starter pack" CTA from the empty state
# instead of asking the user to wire dashboards by hand before they
# see anything render.
@router.post(
    "/install-starter-pack",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RequirePermission("bi.dashboard.write"))],
)
async def install_starter_pack(
    session: SessionDep,
) -> dict[str, int]:
    """Seed system KPIs, 5 role-based dashboards, 3 reports, 2 schedules
    and 4 alert rules. Idempotent - re-running is safe and only inserts
    rows that don't already exist. Returns per-step row counts so the
    UI can toast a meaningful result.
    """
    from app.modules.bi_dashboards.seed import seed_all

    counts = await seed_all(session)
    await session.commit()
    logger.info("BI starter pack installed: %s", counts)
    return counts


@router.get(
    "/dashboards",
    response_model=list[DashboardRead],
    dependencies=[Depends(RequirePermission("bi.dashboard.read"))],
)
async def list_dashboards(
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
    project_id: uuid.UUID | None = Query(default=None),
) -> list[DashboardRead]:
    """List the dashboards the caller can see.

    Args:
        user_id: The authenticated caller.
        session: Database session, used for the project access check.
        service: Module service.
        project_id: The project named in the address bar. The answer is
            then that project's own dashboards plus the company-wide
            ones; who may see what is unchanged by naming a project.

    Returns:
        The dashboards the caller may see.
    """
    await _verify_optional_project(project_id, user_id, session)
    rows = await service.list_dashboards(
        owner_user_id=_user_uuid(user_id),
        project_id=project_id,
    )
    return [DashboardRead.model_validate(r) for r in rows]


@router.post(
    "/dashboards",
    response_model=DashboardRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bi.dashboard.write"))],
)
async def create_dashboard(
    payload: DashboardCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> DashboardRead:
    """Create a dashboard, optionally pinned to a project.

    Args:
        payload: The dashboard to create. A ``project_id`` pins it to one
            project; omitting it leaves the dashboard company-wide.
        user_id: The authenticated caller.
        session: Database session, used for the project access check.
        service: Module service.

    Returns:
        The created dashboard.
    """
    await _verify_optional_project(payload.project_id, user_id, session)
    row = await service.create_dashboard(
        payload,
        owner_user_id=_user_uuid(user_id),
    )
    return DashboardRead.model_validate(row)


@router.patch(
    "/dashboards/{dashboard_id}",
    response_model=DashboardRead,
    dependencies=[Depends(RequirePermission("bi.dashboard.write"))],
)
async def update_dashboard(
    dashboard_id: uuid.UUID,
    payload: DashboardUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> DashboardRead:
    """Update a dashboard, including the project it is pinned to.

    Owning a dashboard is not the same as reaching a project, so a payload that
    names one is access-checked as well. Without that, an owner could repoint
    their own dashboard at a project they cannot see, which is the same hole
    the create endpoint closes from the other side.

    Args:
        dashboard_id: The dashboard to update.
        payload: The fields to change. A ``project_id`` moves the dashboard to
            that project. The update is ``exclude_unset``, so omitting the
            field leaves the pin alone while sending it as null clears it
            back to company-wide.
        user_id: The authenticated caller.
        session: Database session, used for the ownership and project checks.
        service: Module service.

    Returns:
        The updated dashboard.
    """
    await _ensure_dashboard_owner(dashboard_id, user_id, session)
    await _verify_optional_project(payload.project_id, user_id, session)
    row = await service.update_dashboard(dashboard_id, payload)
    if row is None:
        raise _not_found("Dashboard not found")
    return DashboardRead.model_validate(row)


@router.delete(
    "/dashboards/{dashboard_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("bi.dashboard.delete"))],
)
async def delete_dashboard(
    dashboard_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> None:
    await _ensure_dashboard_owner(dashboard_id, user_id, session)
    ok = await service.delete_dashboard(dashboard_id)
    if not ok:
        raise _not_found("Dashboard not found")


@router.get(
    "/dashboards/{dashboard_id}/render",
    response_model=DashboardRenderResponse,
    dependencies=[Depends(RequirePermission("bi.dashboard.read"))],
)
async def render_dashboard(
    dashboard_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> DashboardRenderResponse:
    # Read-vs-write RBAC: render is a READ - allow owner/admin + shared
    # (global/role) + project-team access, matching the dashboards grid.
    await _ensure_dashboard_read_access(dashboard_id, user_id, session)
    # IDOR scope: portfolio widgets (no project pin) must aggregate only over
    # the caller's accessible projects, never every tenant's. Admins get None
    # (unrestricted). Same pattern as the standalone /kpis/* routes.
    allowed = await accessible_project_ids(session, user_id)
    result = await service.render_dashboard(
        dashboard_id,
        allowed_project_ids=allowed,
    )
    if result is None:
        raise _not_found("Dashboard not found")
    return result


@router.post(
    "/dashboards/{dashboard_id}/evaluate",
    response_model=DashboardEvaluateResponse,
    dependencies=[Depends(RequirePermission("bi.dashboard.read"))],
)
async def evaluate_dashboard(
    dashboard_id: uuid.UUID,
    payload: DashboardEvaluateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> DashboardEvaluateResponse:
    """Cross-filter evaluate (Wave 4 / T11).

    Re-evaluates every widget on the dashboard against the supplied
    filter dict, returning per-widget values + drill_path. When the
    dashboard's ``cross_filter_enabled`` flag is False the filter dict
    is ignored and widgets return their static aggregate.

    If ``filters['project_id']`` is supplied we also verify the caller
    can access that project - same IDOR pattern as the KPI endpoints.
    """
    # Read-vs-write RBAC: evaluate is a READ - allow owner/admin + shared
    # (global/role) + project-team access, matching the dashboards grid.
    await _ensure_dashboard_read_access(dashboard_id, user_id, session)
    filters = payload.filters or {}
    project_filter = filters.get("project_id")
    if project_filter:
        try:
            project_uuid = project_filter if isinstance(project_filter, uuid.UUID) else uuid.UUID(str(project_filter))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="filters.project_id must be a UUID",
            ) from exc
        await verify_project_access(project_uuid, user_id, session)
    # IDOR scope: portfolio widgets (no project pin) must aggregate only over
    # the caller's accessible projects, never every tenant's. Admins get None
    # (unrestricted). Same pattern as the standalone /kpis/* routes.
    allowed = await accessible_project_ids(session, user_id)
    result = await service.evaluate_dashboard(
        dashboard_id,
        filters=filters,
        allowed_project_ids=allowed,
    )
    if result is None:
        raise _not_found("Dashboard not found")
    return result


# ── Widgets ───────────────────────────────────────────────────────────


@router.post(
    "/widgets",
    response_model=WidgetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bi.dashboard.write"))],
)
async def create_widget(
    payload: WidgetCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> WidgetRead:
    await _ensure_dashboard_owner(payload.dashboard_id, user_id, session)
    row = await service.create_widget(payload)
    if row is None:
        raise _not_found("Dashboard not found")
    return WidgetRead.model_validate(row)


@router.patch(
    "/widgets/{widget_id}",
    response_model=WidgetRead,
    dependencies=[Depends(RequirePermission("bi.dashboard.write"))],
)
async def update_widget(
    widget_id: uuid.UUID,
    payload: WidgetUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> WidgetRead:
    await _ensure_widget_owner(widget_id, user_id, session)
    row = await service.update_widget(widget_id, payload)
    if row is None:
        raise _not_found("Widget not found")
    return WidgetRead.model_validate(row)


@router.delete(
    "/widgets/{widget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("bi.dashboard.write"))],
)
async def delete_widget(
    widget_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> None:
    await _ensure_widget_owner(widget_id, user_id, session)
    ok = await service.delete_widget(widget_id)
    if not ok:
        raise _not_found("Widget not found")


# ── Reports ───────────────────────────────────────────────────────────


@router.get(
    "/reports",
    response_model=list[ReportDefinitionRead],
    dependencies=[Depends(RequirePermission("bi.report.read"))],
)
async def list_reports(
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
    project_id: uuid.UUID | None = Query(default=None),
) -> list[ReportDefinitionRead]:
    """List the report definitions the caller can see.

    Args:
        user_id: The authenticated caller.
        session: Database session, used for the project access check.
        service: Module service.
        project_id: The project named in the address bar. The answer is
            then that project's own reports plus the company-wide ones.

    Returns:
        The report definitions the caller may see.
    """
    await _verify_optional_project(project_id, user_id, session)
    rows = await service.list_reports(
        owner_user_id=_user_uuid(user_id),
        project_id=project_id,
    )
    return [ReportDefinitionRead.model_validate(r) for r in rows]


@router.post(
    "/reports",
    response_model=ReportDefinitionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bi.report.write"))],
)
async def create_report(
    payload: ReportDefinitionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> ReportDefinitionRead:
    """Create a report definition, optionally pinned to a project.

    Args:
        payload: The report to create. A ``project_id`` pins it to one
            project; omitting it leaves the report company-wide.
        user_id: The authenticated caller.
        session: Database session, used for the project access check.
        service: Module service.

    Returns:
        The created report definition.
    """
    await _verify_optional_project(payload.project_id, user_id, session)
    row = await service.create_report(
        payload,
        owner_user_id=_user_uuid(user_id),
    )
    return ReportDefinitionRead.model_validate(row)


@router.post(
    "/reports/{report_id}/run",
    response_model=ReportRunResponse,
    dependencies=[Depends(RequirePermission("bi.report.run"))],
)
async def run_report(
    report_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> ReportRunResponse:
    await _ensure_report_owner(report_id, user_id, session)
    result = await service.run_report(report_id)
    if result is None:
        raise _not_found("Report not found")
    return result


# ── Schedules ─────────────────────────────────────────────────────────


@router.get(
    "/report-schedules",
    response_model=list[ReportScheduleRead],
    dependencies=[Depends(RequirePermission("bi.report.read"))],
)
async def list_schedules(
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
    project_id: uuid.UUID | None = Query(default=None),
) -> list[ReportScheduleRead]:
    """List every schedule attached to a report the caller can see.

    Ownership is inherited from the parent report (own + shared
    global/role), matching ``GET /reports``. Until this endpoint existed
    the Schedules tab could only render fabricated "On demand / -" rows;
    now it shows real frequency, next-run and recipient counts.

    Args:
        user_id: The authenticated caller.
        session: Database session, used for the project access check.
        service: Module service.
        project_id: The project named in the address bar. Both the parent
            reports and the schedules themselves are narrowed to it plus
            the company-wide ones.

    Returns:
        The schedules the caller may see.
    """
    await _verify_optional_project(project_id, user_id, session)
    rows = await service.list_schedules_visible_to(
        owner_user_id=_user_uuid(user_id),
        project_id=project_id,
    )
    return [ReportScheduleRead.model_validate(r) for r in rows]


@router.post(
    "/report-schedules",
    response_model=ReportScheduleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bi.report.schedule"))],
)
async def create_schedule(
    payload: ReportScheduleCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> ReportScheduleRead:
    """Create a schedule for a report, optionally pinned to a project.

    Args:
        payload: The schedule to create. A ``project_id`` narrows the
            schedule to one project, which is how a company-wide report
            gets a cadence only one project asked for.
        user_id: The authenticated caller.
        session: Database session, used for the access checks.
        service: Module service.

    Returns:
        The created schedule.
    """
    await _ensure_report_owner(payload.report_definition_id, user_id, session)
    await _verify_optional_project(payload.project_id, user_id, session)
    row = await service.create_schedule(payload)
    if row is None:
        raise _not_found("Report definition not found")
    return ReportScheduleRead.model_validate(row)


@router.patch(
    "/report-schedules/{schedule_id}",
    response_model=ReportScheduleRead,
    dependencies=[Depends(RequirePermission("bi.report.schedule"))],
)
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: ReportScheduleUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> ReportScheduleRead:
    """Update a schedule, including the project it is pinned to.

    The project the payload names is access-checked for the same reason the
    dashboard update checks it: owning the schedule says nothing about being
    able to reach the project it would be moved to.

    Args:
        schedule_id: The schedule to update.
        payload: The fields to change. A ``project_id`` moves the schedule to
            that project. The update is ``exclude_unset``, so omitting the
            field leaves the pin alone while sending it as null clears it.
        user_id: The authenticated caller.
        session: Database session, used for the ownership and project checks.
        service: Module service.

    Returns:
        The updated schedule.
    """
    await _ensure_schedule_owner(schedule_id, user_id, session)
    await _verify_optional_project(payload.project_id, user_id, session)
    row = await service.update_schedule(schedule_id, payload)
    if row is None:
        raise _not_found("Schedule not found")
    return ReportScheduleRead.model_validate(row)


@router.post(
    "/report-schedules/{schedule_id}/run-now",
    response_model=ReportRunResponse,
    dependencies=[Depends(RequirePermission("bi.report.run"))],
)
async def run_schedule_now(
    schedule_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> ReportRunResponse:
    await _ensure_schedule_owner(schedule_id, user_id, session)
    result = await service.run_scheduled_report(schedule_id)
    if result is None:
        raise _not_found("Schedule not found")
    return result


# ── Alerts ────────────────────────────────────────────────────────────


@router.get(
    "/alerts",
    response_model=list[AlertRuleRead],
    dependencies=[Depends(RequirePermission("bi.alert.read"))],
)
async def list_alerts(
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> list[AlertRuleRead]:
    # Tenant-wide alerts (scope_project_id IS NULL) are visible to any
    # caller with bi.alert.read. Project-scoped alerts are data about one
    # project, so only return those whose project the caller can access -
    # mirrors ``_ensure_alert_access`` used on toggle and the per-caller
    # filtering dashboards/reports already do. Without this, every tenant's
    # project-scoped rule names / thresholds leak cross-tenant.
    rows = await service.repo.list_alerts()
    admin = await _is_admin(user_id, session)
    if admin:
        return [AlertRuleRead.model_validate(r) for r in rows]

    # Resolve project access once per distinct scope_project_id.
    access_cache: dict[uuid.UUID, bool] = {}
    visible: list[AlertRule] = []
    for row in rows:
        scope_pid = row.scope_project_id
        if scope_pid is None:
            visible.append(row)
            continue
        allowed = access_cache.get(scope_pid)
        if allowed is None:
            try:
                await verify_project_access(scope_pid, user_id, session)
                allowed = True
            except HTTPException:
                allowed = False
            access_cache[scope_pid] = allowed
        if allowed:
            visible.append(row)
    return [AlertRuleRead.model_validate(r) for r in visible]


@router.post(
    "/alerts",
    response_model=AlertRuleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bi.alert.write"))],
)
async def create_alert(
    payload: AlertRuleCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> AlertRuleRead:
    # AlertRule may carry a scope_project_id - if so, gate against it.
    scope_pid = getattr(payload, "scope_project_id", None)
    if scope_pid is not None:
        await verify_project_access(scope_pid, user_id, session)
    try:
        row = await service.create_alert(payload)
    except AlertExpressionError as exc:
        # The composite expression is checked now rather than when the
        # rule runs, so the author hears about it while they are still
        # looking at what they wrote. The message names the path into the
        # tree that was refused.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "invalid_alert_expression", "message": str(exc)},
        ) from exc
    return AlertRuleRead.model_validate(row)


@router.patch(
    "/alerts/{alert_id}/toggle",
    response_model=AlertRuleRead,
    dependencies=[Depends(RequirePermission("bi.alert.write"))],
)
async def toggle_alert(
    alert_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    enabled: bool = Query(...),
    service: BIDashboardsService = Depends(_service),
) -> AlertRuleRead:
    # IDOR guard: a project-scoped alert is data about one project - only
    # a caller with access to that project may flip it on/off.
    await _ensure_alert_access(alert_id, user_id, session)
    row = await service.toggle_alert(alert_id, enabled=enabled)
    if row is None:
        raise _not_found("Alert not found")
    return AlertRuleRead.model_validate(row)


@router.post(
    "/alerts/evaluate-now",
    dependencies=[Depends(RequirePermission("bi.alert.write"))],
)
async def evaluate_alerts_now(
    user_id: CurrentUserId,  # noqa: ARG001
    service: BIDashboardsService = Depends(_service),
) -> dict[str, Any]:
    fired = await service.evaluate_alerts()
    return {"fired": fired}


# ── Saved Filters ─────────────────────────────────────────────────────


@router.get(
    "/saved-filters",
    response_model=list[SavedFilterRead],
    dependencies=[Depends(RequirePermission("bi.filter.read"))],
)
async def list_filters(
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
    module: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
) -> list[SavedFilterRead]:
    """List the saved filters the caller can see.

    Args:
        user_id: The authenticated caller.
        session: Database session, used for the project access check.
        service: Module service.
        module: Restrict to filters saved for one UI module.
        project_id: The project named in the address bar. The answer is
            then that project's own filters plus the company-wide ones,
            shared filters included.

    Returns:
        The saved filters the caller may see.
    """
    await _verify_optional_project(project_id, user_id, session)
    rows = await service.list_filters(
        owner_user_id=_user_uuid(user_id),
        module=module,
        project_id=project_id,
    )
    return [SavedFilterRead.model_validate(r) for r in rows]


@router.post(
    "/saved-filters",
    response_model=SavedFilterRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bi.filter.write"))],
)
async def create_filter(
    payload: SavedFilterCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
) -> SavedFilterRead:
    """Create a saved filter, optionally pinned to a project.

    Args:
        payload: The filter to create. A ``project_id`` pins it to one
            project; omitting it leaves the filter company-wide.
        user_id: The authenticated caller.
        session: Database session, used for the project access check.
        service: Module service.

    Returns:
        The created saved filter.
    """
    await _verify_optional_project(payload.project_id, user_id, session)
    row = await service.create_filter(
        payload,
        owner_user_id=_user_uuid(user_id),
    )
    return SavedFilterRead.model_validate(row)


@router.post(
    "/saved-filters/{filter_id}/share",
    response_model=SavedFilterRead,
    dependencies=[Depends(RequirePermission("bi.filter.write"))],
)
async def share_filter(
    filter_id: uuid.UUID,
    payload: SavedFilterShareRequest,
    user_id: CurrentUserId,
    service: BIDashboardsService = Depends(_service),
) -> SavedFilterRead:
    """Share a saved filter with one or more users.

    The caller must own the filter (404 leaked instead of 403 to avoid
    information disclosure across tenants).
    """
    row = await service.share_filter(
        filter_id,
        owner_user_id=_user_uuid(user_id),
        user_ids=payload.user_ids,
    )
    return SavedFilterRead.model_validate(row)


# ── Report runs (file download) ─────────────────────────────────────────


@router.get(
    "/report-runs/{run_id}/file",
    dependencies=[Depends(RequirePermission("bi.report.read"))],
)
async def download_report_file(
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BIDashboardsService = Depends(_service),
):
    """Stream the rendered report file for a :class:`ReportRun`.

    Ownership is checked against the parent ReportDefinition.
    """
    run = await service.get_report_run(run_id)
    if run is None or not run.file_path:
        raise _not_found("Report file not found")
    # Ownership check via report
    await _ensure_report_owner(run.report_definition_id, user_id, session)
    import os

    if not os.path.exists(run.file_path):
        raise _not_found("Report file missing on disk")

    # Path traversal guard. ``run.file_path`` is written by our own
    # report-builder so it should already point inside the reports
    # directory, but if a future bug or direct DB tamper plants
    # ``/etc/passwd`` here we refuse rather than serve it. Also drops
    # the file if it's a symlink - defence against a malicious local
    # actor swapping the on-disk artefact between write and read.
    from pathlib import Path as _Path

    from app.modules.bi_dashboards.report_builder import _reports_dir

    resolved = _Path(run.file_path).resolve()
    base = _Path(_reports_dir()).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise _not_found("Report file not accessible") from exc
    if resolved.is_symlink():
        raise _not_found("Report file not accessible")

    media_type = {
        "pdf": "application/pdf",
        "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "csv": "text/csv",
    }.get(run.output_format, "application/octet-stream")
    return FileResponse(
        str(resolved),
        media_type=media_type,
        filename=os.path.basename(run.file_path),
    )


# ── Widget export ───────────────────────────────────────────────────────


@router.get(
    "/widgets/{widget_id}/export",
    dependencies=[Depends(RequirePermission("bi.dashboard.read"))],
)
async def export_widget(
    widget_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    format: str = Query(default="csv", description="csv | svg"),
    service: BIDashboardsService = Depends(_service),
):
    """Export a widget's value + history as CSV or SVG chart."""
    await _ensure_widget_owner(widget_id, user_id, session)
    out = await service.export_widget(widget_id, format=format)
    if out is None:
        raise _not_found("Widget not found")
    path, _size = out
    import os
    from pathlib import Path as _Path

    from app.modules.bi_dashboards.report_builder import _reports_dir

    # Same containment check as ``download_report_file``: ``path`` is
    # constructed by the widget exporter so it should sit inside the
    # reports directory, but we refuse anything outside in case of
    # a future bug or hostile DB row.
    resolved = _Path(path).resolve()
    base = _Path(_reports_dir()).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise _not_found("Widget export not accessible") from exc
    if resolved.is_symlink():
        raise _not_found("Widget export not accessible")

    media_type = "image/svg+xml" if format.lower() == "svg" else "text/csv"
    return FileResponse(
        str(resolved),
        media_type=media_type,
        filename=os.path.basename(path),
    )


__all__ = ["router"]
