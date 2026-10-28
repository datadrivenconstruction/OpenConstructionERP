# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Full EVM API routes.

Forecast surface (derived from finance EVM snapshots)::

    GET    /forecasts/                     - list EVM forecasts
    POST   /forecasts/calculate/           - recompute from the latest snapshot
    GET    /forecasts/alerts/              - forecasts with an actionable alert
    POST   /forecasts/{id}/acknowledge/    - resolve an alert
    POST   /forecasts/{id}/snooze/         - defer an alert
    GET    /s-curve-data/                  - snapshots + forecasts for charting

Register surface (baselines and measurements owned by this module)::

    GET    /baselines/                     - list a project's baselines
    POST   /baselines/                     - create a baseline (+ its curve)
    GET    /baselines/{id}/                - read a baseline with its curve
    PATCH  /baselines/{id}/                - patch a draft baseline
    DELETE /baselines/{id}/                - delete a non-approved baseline
    PUT    /baselines/{id}/periods/        - replace the planned-value curve
    POST   /baselines/{id}/validate/       - re-run the full_evm rule set
    POST   /baselines/{id}/approve/        - approve, superseding the previous
    GET    /baselines/{id}/s-curve/        - plan versus actual for charting
    GET    /baselines/{id}/measures/       - list measurements
    POST   /baselines/{id}/measures/       - record (or re-record) a measurement
    GET    /measures/{id}/                 - read one measurement
    DELETE /measures/{id}/                 - delete a measurement
    GET    /glossary/                      - plain-language EVM vocabulary

Every project-scoped path resolves the row first and then checks access
against *that row's* project, so an id belonging to another tenant is a 404
before any data is read back.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import ValidationReport
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.full_evm.models import EVMBaseline, EVMMeasure
from app.modules.full_evm.schemas import (
    BaselineCreate,
    BaselineListResponse,
    BaselinePeriodsReplace,
    BaselineResponse,
    BaselineSCurveResponse,
    BaselineUpdate,
    EVMCalculateRequest,
    EVMForecastListResponse,
    EVMForecastResponse,
    ForecastSnoozeRequest,
    MeasureCreate,
    MeasureListResponse,
    MeasureResponse,
    MetricGlossaryResponse,
    SCurveDataResponse,
    ValidationFinding,
    ValidationReportResponse,
)
from app.modules.full_evm.service import (
    EVMBaselineService,
    EVMService,
    metric_glossary,
)

router = APIRouter(tags=["full_evm"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> EVMService:
    return EVMService(session)


def _get_baseline_service(session: SessionDep) -> EVMBaselineService:
    return EVMBaselineService(session)


# ── IDOR protection ───────────────────────────────────────────────────────


async def _verify_project_access(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    user_id: str | None,
) -> None:
    """Verify the user owns (or is admin on) the referenced project.

    Every project-scoped EVM endpoint must call this - the service layer
    trusts the project_id and will gladly return cross-tenant data
    otherwise. Mirrors ``finance.router._require_project_access``.
    ``None`` project_id is a no-op (for the list endpoint which may
    choose to aggregate across the caller's own projects).
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
        except Exception:  # noqa: BLE001 - best-effort admin check
            pass

        if str(getattr(project, "owner_id", "")) != str(user_id):
            # Return 404 (not 403) for cross-project denials to match the R7
            # standard used by the finance module: a 403 here would confirm the
            # project UUID exists, enabling project enumeration.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Full EVM project access check failed for %s: %s", project_id, exc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )


async def _load_baseline(
    service: EVMBaselineService,
    session: AsyncSession,
    baseline_id: uuid.UUID,
    user_id: str | None,
) -> EVMBaseline:
    """Load a baseline and check the caller may see its project.

    Raises:
        HTTPException: 404 when the baseline does not exist or belongs to a
            project the caller cannot reach. The two cases are deliberately
            indistinguishable so a baseline id cannot be probed.
    """
    baseline = await service.get_baseline(baseline_id)
    if baseline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Baseline {baseline_id} not found",
        )
    await _verify_project_access(session, baseline.project_id, user_id)
    return baseline


async def _load_measure(
    service: EVMBaselineService,
    session: AsyncSession,
    measure_id: uuid.UUID,
    user_id: str | None,
) -> EVMMeasure:
    """Load a measurement and check the caller may see its project."""
    measure = await service.get_measure(measure_id)
    if measure is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Measurement {measure_id} not found",
        )
    await _verify_project_access(session, measure.project_id, user_id)
    return measure


def _report_response(report: ValidationReport) -> ValidationReportResponse:
    """Render a validation outcome for the API.

    Only failing, non-engine results are returned: the report is a to-do list,
    and ``score`` stays ``None`` when nothing was actually checked rather than
    defaulting to a flattering 1.0.
    """
    return ValidationReportResponse(
        status=report.status.value,
        score=report.score,
        findings=[
            ValidationFinding(
                rule_id=result.rule_id,
                severity=result.severity.value,
                message=result.message,
                element_ref=result.element_ref,
                suggestion=result.suggestion,
                details=dict(result.details or {}),
            )
            for result in report.results
            if not result.passed and not result.is_engine_error
        ],
    )


# ── Forecasts ─────────────────────────────────────────────────────────────


@router.get(
    "/forecasts/",
    response_model=EVMForecastListResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def list_forecasts(
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    project_id: uuid.UUID | None = Query(default=None),
    service: EVMService = Depends(_get_service),
) -> EVMForecastListResponse:
    """List EVM forecasts with optional project filter.

    When ``project_id`` is provided we verify ownership before returning
    data. When omitted the list is intentionally empty for non-admin
    callers until an explicit project scope is supplied - preventing
    cross-tenant enumeration.
    """
    if project_id is None:
        # Omitted scope: refuse to dump all forecasts across tenants.
        # Admins can pass an explicit project_id if they need a scoped list.
        return EVMForecastListResponse(items=[], total=0)
    await _verify_project_access(session, project_id, user_id)
    items, total = await service.list_forecasts(project_id=project_id)
    return EVMForecastListResponse(
        items=[EVMForecastResponse.model_validate(f) for f in items],
        total=total,
    )


@router.post(
    "/forecasts/calculate/",
    response_model=EVMForecastResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("full_evm.create"))],
)
async def calculate_forecast(
    data: EVMCalculateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMService = Depends(_get_service),
) -> EVMForecastResponse:
    """Calculate an EVM forecast from the latest finance EVM snapshot.

    The response records both the requested formula (``forecast_method``) and
    the one that could actually be evaluated (``metadata.effective_method``).
    They differ whenever the requested formula's divisor was zero, which is the
    normal state of a project that has not earned anything yet.
    """
    await _verify_project_access(session, data.project_id, user_id)
    forecast = await service.calculate_forecast(
        project_id=data.project_id,
        forecast_method=data.forecast_method,
    )
    return EVMForecastResponse.model_validate(forecast)


@router.get(
    "/forecasts/alerts/",
    response_model=EVMForecastListResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def list_forecast_alerts(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: EVMService = Depends(_get_service),
) -> EVMForecastListResponse:
    """List forecasts whose predictive alert is still actionable.

    Actionable means ``triggered`` or ``snoozed``; acknowledged rows are
    resolved and rows that never breached a rule are not alerts at all.
    """
    await _verify_project_access(session, project_id, user_id)
    items = await service.forecasts.list_active_alerts(project_id)
    return EVMForecastListResponse(
        items=[EVMForecastResponse.model_validate(f) for f in items],
        total=len(items),
    )


@router.post(
    "/forecasts/{forecast_id}/acknowledge/",
    response_model=EVMForecastResponse,
    dependencies=[Depends(RequirePermission("full_evm.update"))],
)
async def acknowledge_forecast_alert(
    forecast_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMService = Depends(_get_service),
) -> EVMForecastResponse:
    """Resolve a triggered or snoozed forecast alert."""
    existing = await service.forecasts.get(forecast_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Forecast {forecast_id} not found",
        )
    await _verify_project_access(session, existing.project_id, user_id)
    forecast = await service.acknowledge_alert(forecast_id)
    if forecast is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Forecast {forecast_id} not found",
        )
    return EVMForecastResponse.model_validate(forecast)


@router.post(
    "/forecasts/{forecast_id}/snooze/",
    response_model=EVMForecastResponse,
    dependencies=[Depends(RequirePermission("full_evm.update"))],
)
async def snooze_forecast_alert(
    forecast_id: uuid.UUID,
    data: ForecastSnoozeRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMService = Depends(_get_service),
) -> EVMForecastResponse:
    """Defer a forecast alert for a number of hours.

    The next batch run re-triggers on the same condition, so a snooze quietens
    the alert without pretending the underlying breach went away.
    """
    existing = await service.forecasts.get(forecast_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Forecast {forecast_id} not found",
        )
    await _verify_project_access(session, existing.project_id, user_id)
    forecast = await service.snooze_alert(forecast_id, data.hours)
    if forecast is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Forecast {forecast_id} not found",
        )
    return EVMForecastResponse.model_validate(forecast)


@router.get(
    "/s-curve-data/",
    response_model=SCurveDataResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def get_s_curve_data(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: EVMService = Depends(_get_service),
) -> SCurveDataResponse:
    """Get S-curve data combining EVM snapshots and forecasts for charting."""
    await _verify_project_access(session, project_id, user_id)
    data = await service.get_s_curve_data(project_id)
    return SCurveDataResponse(**data)


# ── Baselines ─────────────────────────────────────────────────────────────


@router.get(
    "/baselines/",
    response_model=BaselineListResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def list_baselines(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    baseline_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> BaselineListResponse:
    """List a project's performance measurement baselines, newest first."""
    await _verify_project_access(session, project_id, user_id)
    items, total = await service.list_baselines(
        project_id=project_id,
        status_filter=baseline_status,
        limit=limit,
        offset=offset,
    )
    return BaselineListResponse(
        items=[BaselineResponse.model_validate(b) for b in items],
        total=total,
    )


@router.post(
    "/baselines/",
    response_model=BaselineResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("full_evm.create"))],
)
async def create_baseline(
    data: BaselineCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> BaselineResponse:
    """Create a baseline, optionally with its whole planned-value curve.

    The ``full_evm`` rule set runs immediately, so the returned row already
    carries a real ``validation_status`` rather than an unchecked "pending".
    """
    await _verify_project_access(session, data.project_id, user_id)
    baseline = await service.create_baseline(data)
    return BaselineResponse.model_validate(baseline)


@router.get(
    "/baselines/{baseline_id}/",
    response_model=BaselineResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def get_baseline(
    baseline_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> BaselineResponse:
    """Read one baseline together with its planned-value curve."""
    baseline = await _load_baseline(service, session, baseline_id, user_id)
    return BaselineResponse.model_validate(baseline)


@router.patch(
    "/baselines/{baseline_id}/",
    response_model=BaselineResponse,
    dependencies=[Depends(RequirePermission("full_evm.update"))],
)
async def update_baseline(
    baseline_id: uuid.UUID,
    data: BaselineUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> BaselineResponse:
    """Patch a draft baseline. An approved baseline is superseded, not edited."""
    baseline = await _load_baseline(service, session, baseline_id, user_id)
    updated = await service.update_baseline(baseline, data)
    return BaselineResponse.model_validate(updated)


@router.delete(
    "/baselines/{baseline_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("full_evm.delete"))],
)
async def delete_baseline(
    baseline_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> None:
    """Delete a non-approved baseline with its curve and measurements."""
    baseline = await _load_baseline(service, session, baseline_id, user_id)
    await service.delete_baseline(baseline)


@router.put(
    "/baselines/{baseline_id}/periods/",
    response_model=BaselineResponse,
    dependencies=[Depends(RequirePermission("full_evm.update"))],
)
async def replace_baseline_periods(
    baseline_id: uuid.UUID,
    data: BaselinePeriodsReplace,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> BaselineResponse:
    """Replace the whole cumulative planned-value curve in one write.

    Whole-curve replacement rather than per-row edits: the curve's invariants
    (rising, ending at the budget) are properties of the set, so a row-by-row
    path would spend most of its life in a state the rules correctly reject.
    """
    baseline = await _load_baseline(service, session, baseline_id, user_id)
    updated = await service.replace_periods(baseline, data.periods)
    return BaselineResponse.model_validate(updated)


@router.post(
    "/baselines/{baseline_id}/validate/",
    response_model=ValidationReportResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def validate_baseline(
    baseline_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> ValidationReportResponse:
    """Re-run the ``full_evm`` rule set over a baseline and store the outcome."""
    baseline = await _load_baseline(service, session, baseline_id, user_id)
    report = await service.validate_baseline(baseline)
    return _report_response(report)


@router.post(
    "/baselines/{baseline_id}/approve/",
    response_model=BaselineResponse,
    dependencies=[Depends(RequirePermission("full_evm.approve"))],
)
async def approve_baseline(
    baseline_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> BaselineResponse:
    """Approve a baseline, superseding the project's previous approved one.

    Refused with 409 while the baseline has blocking validation errors: once a
    curve is the divisor of every future schedule index, an error in it is no
    longer a work-in-progress state.
    """
    baseline = await _load_baseline(service, session, baseline_id, user_id)
    approver: uuid.UUID | None = None
    if user_id is not None:
        try:
            approver = uuid.UUID(str(user_id))
        except ValueError:
            approver = None
    approved = await service.approve_baseline(baseline, approved_by=approver)
    return BaselineResponse.model_validate(approved)


@router.get(
    "/baselines/{baseline_id}/s-curve/",
    response_model=BaselineSCurveResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def get_baseline_s_curve(
    baseline_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> BaselineSCurveResponse:
    """Plan-versus-actual curve for one baseline.

    Periods with no measurement yet carry ``null`` rather than zero, so an
    unreported month reads as unreported instead of as no progress.
    """
    await _load_baseline(service, session, baseline_id, user_id)
    data = await service.build_s_curve(baseline_id)
    return BaselineSCurveResponse(**data)


# ── Measurements ──────────────────────────────────────────────────────────


@router.get(
    "/baselines/{baseline_id}/measures/",
    response_model=MeasureListResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def list_measures(
    baseline_id: uuid.UUID,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> MeasureListResponse:
    """List a baseline's measurements, oldest first."""
    await _load_baseline(service, session, baseline_id, user_id)
    items, total = await service.list_measures(baseline_id=baseline_id, limit=limit, offset=offset)
    return MeasureListResponse(
        items=[MeasureResponse.model_validate(m) for m in items],
        total=total,
    )


@router.post(
    "/baselines/{baseline_id}/measures/",
    response_model=MeasureResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("full_evm.create"))],
)
async def record_measure(
    baseline_id: uuid.UUID,
    data: MeasureCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> MeasureResponse:
    """Record (or re-record) an EVM measurement for one data date.

    Omit ``pv`` to read the planned value straight off the baseline curve,
    which is the reason the curve is stored. Supplying it is an explicit
    override and is reported by ``full_evm.measure_pv_follows_baseline``.
    """
    baseline = await _load_baseline(service, session, baseline_id, user_id)
    measure = await service.record_measure(baseline, data)
    return MeasureResponse.model_validate(measure)


@router.get(
    "/measures/{measure_id}/",
    response_model=MeasureResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def get_measure(
    measure_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> MeasureResponse:
    """Read one measurement with its full derived metric set."""
    measure = await _load_measure(service, session, measure_id, user_id)
    return MeasureResponse.model_validate(measure)


@router.delete(
    "/measures/{measure_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("full_evm.delete"))],
)
async def delete_measure(
    measure_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: EVMBaselineService = Depends(_get_baseline_service),
) -> None:
    """Delete a measurement."""
    measure = await _load_measure(service, session, measure_id, user_id)
    await service.delete_measure(measure)


# ── Glossary ──────────────────────────────────────────────────────────────


@router.get(
    "/glossary/",
    response_model=MetricGlossaryResponse,
    dependencies=[Depends(RequirePermission("full_evm.read"))],
)
async def get_metric_glossary() -> MetricGlossaryResponse:
    """Plain-language meaning of every EVM code and EAC formula.

    Not project-scoped and carries no data, so it needs no ownership check.
    It exists because CPI, TCPI and VAC mean nothing to a reader seeing them
    for the first time, and a number nobody can interpret is not information.
    """
    return MetricGlossaryResponse(**metric_glossary())
