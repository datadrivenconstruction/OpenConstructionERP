# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project Intelligence API routes.

Endpoints:
    GET  /score/?project_id=X          - Project score with gaps and achievements
    GET  /state/?project_id=X          - Full project state snapshot
    GET  /summary/?project_id=X        - Combined state + score
    POST /recommendations/             - AI recommendations (or rule-based fallback)
    POST /chat/                        - Ask a question about the project
    POST /explain-gap/                 - Explain a specific gap
    POST /actions/{action_id}/         - Execute an action
    GET  /actions/?project_id=X        - List available actions
"""

import logging
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.project_intelligence.actions import (
    execute_action,
    get_available_actions,
)
from app.modules.project_intelligence.advisor import (
    answer_question as ai_answer_question,
)
from app.modules.project_intelligence.advisor import (
    explain_gap as ai_explain_gap,
)
from app.modules.project_intelligence.advisor import (
    generate_recommendations,
)
from app.modules.project_intelligence.collector import collect_project_state
from app.modules.project_intelligence.schemas import (
    AchievementResponse,
    ActionDefinitionResponse,
    ActionResponse,
    ChatRequest,
    CostForecastResponse,
    CostOverrunRiskResponse,
    CriticalGapResponse,
    ExplainGapRequest,
    ForecastAlertRow,
    ForecastSnapshotPoint,
    ForecastsResponse,
    LatestForecast,
    ProjectForecastResponse,
    ProjectScoreResponse,
    ProjectStateResponse,
    ProjectSummaryResponse,
    RecommendationRequest,
    ScheduleSlipResponse,
    ScopeBaselineResponse,
    SnoozeForecastRequest,
)
from app.modules.project_intelligence.scorer import compute_score
from app.modules.project_intelligence.service import ForecastService

router = APIRouter(tags=["Project Intelligence"])
logger = logging.getLogger(__name__)


# ── IDOR protection ───────────────────────────────────────────────────────


async def _verify_project_access(
    session: AsyncSession,
    project_id: uuid.UUID | str,
    user_id: str | None,
) -> None:
    """Verify the caller may access the referenced project (owner / team / admin).

    Every project_intelligence endpoint must call this before touching
    collector / scorer / advisor - those helpers trust the project_id
    and will happily return cross-tenant data otherwise.

    Delegates to the shared :func:`app.dependencies.verify_project_access`
    so this module uses the exact same access policy as the rest of the
    platform: owner OR project team-member access, admin bypass, and a
    404 (not 403) on both "missing" and "denied" so a caller cannot use
    the status code to probe which project UUIDs exist.
    """
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project_id",
        )

    await verify_project_access(pid, user_id, session)


# ── Bounded in-memory cache (keyed by user + project to avoid leakage) ────
# RFC 25 - reduced from 300 s to 60 s so the Estimation Dashboard reflects
# sibling-module edits within one minute of a save.
# v4.2.2 - wrapped in an LRU bound so a long-lived process cannot leak
# memory by accumulating per-(user, project) keys for ever.

from collections import OrderedDict  # noqa: E402

CACHE_TTL_SECONDS = 60
STATE_CACHE_MAX_ENTRIES = 512
_state_cache: "OrderedDict[tuple[str, str], tuple[float, Any]]" = OrderedDict()


def _cache_key(user_id: str | None, project_id: str) -> tuple[str, str]:
    """Per-user cache key - prevents cross-user state leaks."""
    return (str(user_id or "anon"), project_id)


def _get_cached_state(user_id: str | None, project_id: str) -> Any | None:
    """Return cached state if still valid."""
    key = _cache_key(user_id, project_id)
    entry = _state_cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL_SECONDS:
        _state_cache.move_to_end(key)
        return entry[1]
    if entry:
        # Expired - drop it so the LRU is honest about freshness.
        _state_cache.pop(key, None)
    return None


def _set_cached_state(user_id: str | None, project_id: str, state: Any) -> None:
    """Cache a project state for the given user (bounded LRU)."""
    key = _cache_key(user_id, project_id)
    _state_cache[key] = (time.time(), state)
    _state_cache.move_to_end(key)
    while len(_state_cache) > STATE_CACHE_MAX_ENTRIES:
        _state_cache.popitem(last=False)


def _invalidate_cache(user_id: str | None, project_id: str) -> None:
    """Remove a project from cache for the given user."""
    _state_cache.pop(_cache_key(user_id, project_id), None)


# ── Helper to collect + optionally cache ──────────────────────────────────


async def _get_state(
    session: SessionDep,
    user_id: str | None,
    project_id: str,
    refresh: bool = False,
) -> Any:
    """Get project state, using cache unless refresh is requested."""
    if not refresh:
        cached = _get_cached_state(user_id, project_id)
        if cached is not None:
            return cached

    state = await collect_project_state(session, project_id)
    _set_cached_state(user_id, project_id, state)
    return state


# ── GET /score/ ───────────────────────────────────────────────────────────


@router.get(
    "/score/",
    response_model=ProjectScoreResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def get_score(
    project_id: uuid.UUID = Query(...),
    refresh: bool = Query(False),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ProjectScoreResponse:
    """Compute and return the project intelligence score."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id), refresh=refresh)
    score = compute_score(state)

    return ProjectScoreResponse(
        overall=score.overall,
        overall_grade=score.overall_grade,
        domain_scores=score.domain_scores,
        critical_gaps=[CriticalGapResponse(**asdict(g)) for g in score.critical_gaps],
        achievements=[AchievementResponse(**asdict(a)) for a in score.achievements],
    )


# ── GET /state/ ───────────────────────────────────────────────────────────


@router.get(
    "/state/",
    response_model=ProjectStateResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def get_state(
    project_id: uuid.UUID = Query(...),
    refresh: bool = Query(False),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ProjectStateResponse:
    """Return full project state snapshot."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id), refresh=refresh)
    return ProjectStateResponse(**asdict(state))


# ── GET /summary/ ─────────────────────────────────────────────────────────


@router.get(
    "/summary/",
    response_model=ProjectSummaryResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def get_summary(
    project_id: uuid.UUID = Query(...),
    refresh: bool = Query(False),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ProjectSummaryResponse:
    """Return combined state + score for the project."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id), refresh=refresh)
    score = compute_score(state)

    return ProjectSummaryResponse(
        state=ProjectStateResponse(**asdict(state)),
        score=ProjectScoreResponse(
            overall=score.overall,
            overall_grade=score.overall_grade,
            domain_scores=score.domain_scores,
            critical_gaps=[CriticalGapResponse(**asdict(g)) for g in score.critical_gaps],
            achievements=[AchievementResponse(**asdict(a)) for a in score.achievements],
        ),
    )


# ── POST /recommendations/ ───────────────────────────────────────────────


@router.post(
    "/recommendations/",
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def get_recommendations(
    body: RecommendationRequest,
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Generate AI recommendations for the project."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id))
    score = compute_score(state)

    text = await generate_recommendations(
        session=session,
        state=state,
        score=score,
        role=body.role,
        language=body.language,
    )

    return {"text": text, "role": body.role, "language": body.language}


# ── POST /chat/ ───────────────────────────────────────────────────────────


@router.post(
    "/chat/",
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def chat(
    body: ChatRequest,
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Answer a question about the project."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id))
    score = compute_score(state)

    text = await ai_answer_question(
        session=session,
        state=state,
        score=score,
        question=body.question,
        role=body.role,
        language=body.language,
        user_id=user_id,
    )

    return {"text": text, "question": body.question}


# ── POST /explain-gap/ ───────────────────────────────────────────────────


@router.post(
    "/explain-gap/",
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def explain_gap(
    body: ExplainGapRequest,
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Explain a specific gap in detail."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id))
    score = compute_score(state)

    # Find the gap by ID
    target_gap = None
    for gap in score.critical_gaps:
        if gap.id == body.gap_id:
            target_gap = gap
            break

    if not target_gap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gap '{body.gap_id}' not found for this project",
        )

    text = await ai_explain_gap(
        session=session,
        gap=target_gap,
        state=state,
        language=body.language,
    )

    return {"text": text, "gap_id": body.gap_id}


# ── POST /actions/{action_id}/ ───────────────────────────────────────────


@router.post(
    "/actions/{action_id}/",
    response_model=ActionResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.create"))],
)
async def run_action(
    action_id: str,
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ActionResponse:
    """Execute a project intelligence action."""
    await _verify_project_access(session, project_id, user_id)
    result = await execute_action(session, action_id, str(project_id))

    # Invalidate cache after action
    _invalidate_cache(user_id, str(project_id))

    return ActionResponse(
        success=result.success,
        message=result.message,
        redirect_url=result.redirect_url,
        data=result.data,
    )


# ── POST /scope-baseline/ ─────────────────────────────────────────────────
#
# Capture the current BOQ scope (leaf-position count) as this project's scope
# baseline. The scope-coverage metric on the Estimation Dashboard then reads
# current-vs-baseline to surface scope drift (creep or de-scoping). The
# baseline is persisted into the project's metadata JSONB (no migration: the
# column already exists with a {} default) so it survives restarts and is the
# authoritative source the collector prefers over snapshot-derived baselines.


@router.post(
    "/scope-baseline/",
    response_model=ScopeBaselineResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.create"))],
)
async def set_scope_baseline(
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ScopeBaselineResponse:
    """Freeze the current BOQ leaf-position count as the scope baseline."""
    await _verify_project_access(session, project_id, user_id)

    # Recompute the live state (forced refresh) so the captured number is the
    # current truth, not a 60s-stale cache value.
    state = await _get_state(session, user_id, str(project_id), refresh=True)
    current = int(getattr(state.boq, "position_count", 0) or 0)
    if current <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No priced BOQ positions to baseline yet. Add line items first.",
        )

    from app.modules.projects.repository import ProjectRepository

    repo = ProjectRepository(session)
    project = await repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Merge into the project metadata JSONB. Re-assign the dict so SQLAlchemy's
    # change tracking flushes it (in-place mutation of a JSON column is not
    # always detected by the ORM).
    meta = dict(getattr(project, "metadata_", None) or {})
    pi_meta = dict(meta.get("project_intelligence") or {})
    captured_at = datetime.now(UTC).isoformat()
    pi_meta["scope_baseline_positions"] = current
    pi_meta["scope_baseline_captured_at"] = captured_at
    pi_meta["scope_baseline_captured_by"] = str(user_id) if user_id else None
    meta["project_intelligence"] = pi_meta
    project.metadata_ = meta
    await session.commit()

    # The baseline changed, so the cached state is stale for this user.
    _invalidate_cache(user_id, str(project_id))

    return ScopeBaselineResponse(
        project_id=str(project_id),
        baseline_position_count=current,
        captured_at=captured_at,
    )


# ── GET /actions/ ─────────────────────────────────────────────────────────


@router.get(
    "/actions/",
    response_model=list[ActionDefinitionResponse],
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def list_actions(
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> list[ActionDefinitionResponse]:
    """List available actions for this project's current gaps."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id))
    score = compute_score(state)

    action_ids = [g.action_id for g in score.critical_gaps if g.action_id]
    actions_data = get_available_actions(action_ids)

    return [ActionDefinitionResponse(**a) for a in actions_data]


# ── Predictive forecast alerts (TOP-30 #19) ───────────────────────────────
#
# These endpoints surface the EVM forecast + threshold-based alerts on the
# Estimation Dashboard's Forecasts tab. The forecast computation + alert
# evaluation live in the full_evm module's EVMService; this router is the
# project-scoped, IDOR-guarded read/acknowledge/snooze surface for the UI.


def _to_float(value: object, default: float = 0.0) -> float:
    """Best-effort string→float for the sparkline points (never raises)."""
    if value is None:
        return default
    try:
        return float(str(value))
    except (ValueError, TypeError):
        return default


def _breach_summary(forecast: object) -> tuple[str, str]:
    """Pull (severity, human summary) out of a forecast's alert metadata."""
    meta = getattr(forecast, "metadata_", None) or {}
    severity = "warning"
    summary = ""
    breaches = meta.get("alert_breaches") if isinstance(meta, dict) else None
    if isinstance(breaches, list) and breaches:
        first = breaches[0]
        if isinstance(first, dict):
            severity = str(first.get("severity") or severity)
            kpi = str(first.get("kpi_code") or "").upper()
            observed = first.get("observed")
            threshold = first.get("threshold")
            extra = f" (+{len(breaches) - 1})" if len(breaches) > 1 else ""
            summary = f"{kpi} {observed} vs threshold {threshold}{extra}".strip()
    return severity, summary


@router.get(
    "/forecasts/",
    response_model=ForecastsResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def get_forecasts(
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ForecastsResponse:
    """Return the latest forecast, active alerts, and sparkline series.

    Drives the Forecasts tab: SPI/CPI chips with a small history sparkline,
    the Forecast-to-Completion card (EAC vs BAC), and the Active Alerts table.
    """
    await _verify_project_access(session, project_id, user_id)

    from app.modules.full_evm.repository import EVMForecastRepository
    from app.modules.full_evm.service import EVMService

    repo = EVMForecastRepository(session)
    service = EVMService(session)

    latest = await repo.get_latest(project_id)
    latest_payload: LatestForecast | None = None
    if latest is not None:
        meta = latest.metadata_ or {}
        bac = _to_float(meta.get("bac"))
        eac_f = _to_float(latest.eac)
        latest_payload = LatestForecast(
            forecast_id=str(latest.id),
            forecast_date=latest.forecast_date,
            method=latest.forecast_method,
            etc=latest.etc_,
            eac=latest.eac,
            vac=latest.vac,
            tcpi=latest.tcpi,
            bac=str(meta.get("bac", "0")),
            spi=str(meta.get("spi", "0")),
            cpi=str(meta.get("cpi", "0")),
            eac_over_bac=round(eac_f / bac, 4) if bac else 0.0,
            alert_status=latest.alert_status,
        )

    alert_rows = await repo.list_active_alerts(project_id)
    active_alerts: list[ForecastAlertRow] = []
    for row in alert_rows:
        severity, summary = _breach_summary(row)
        meta = row.metadata_ or {}
        active_alerts.append(
            ForecastAlertRow(
                forecast_id=str(row.id),
                forecast_date=row.forecast_date,
                alert_status=row.alert_status or "triggered",
                triggered_at=row.triggered_at.isoformat() if row.triggered_at else None,
                snoozed_until=meta.get("snoozed_until") if isinstance(meta, dict) else None,
                severity=severity,
                eac=row.eac,
                vac=row.vac,
                tcpi=row.tcpi,
                summary=summary,
            )
        )

    # Sparkline: the EVM snapshot history (oldest→newest) for SPI/CPI/EAC.
    s_curve = await service.get_s_curve_data(project_id)

    sparkline: list[ForecastSnapshotPoint] = []
    for snap in s_curve.get("snapshots", []):
        ev = _to_float(snap.get("ev"))
        ac = _to_float(snap.get("ac"))
        bac = _to_float(snap.get("bac"))
        pv = _to_float(snap.get("pv"))
        cpi = (ev / ac) if ac else 0.0
        spi = (ev / pv) if pv else 0.0
        eac = (ac + (bac - ev) / cpi) if cpi else bac
        sparkline.append(
            ForecastSnapshotPoint(
                date=str(snap.get("date") or ""),
                spi=round(spi, 4),
                cpi=round(cpi, 4),
                eac=round(eac, 2),
                ev=round(ev, 2),
                ac=round(ac, 2),
            )
        )

    currency = ""
    try:
        state = await _get_state(session, user_id, str(project_id))
        currency = getattr(state, "currency", "") or ""
    except Exception:  # noqa: BLE001 - currency is cosmetic
        currency = ""

    return ForecastsResponse(
        project_id=str(project_id),
        currency=currency,
        latest_forecast=latest_payload,
        active_alerts=active_alerts,
        sparkline=sparkline,
    )


async def _load_forecast_for_write(
    session: AsyncSession,
    forecast_id: uuid.UUID,
    user_id: str | None,
) -> Any:
    """Load a forecast, verifying the caller owns its project (IDOR guard).

    Returns the forecast row. Raises 404 when absent so a cross-tenant probe
    cannot distinguish "not found" from "not yours".
    """
    from app.modules.full_evm.repository import EVMForecastRepository

    repo = EVMForecastRepository(session)
    forecast = await repo.get(forecast_id)
    if forecast is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Forecast {forecast_id} not found",
        )
    await _verify_project_access(session, forecast.project_id, user_id)
    return forecast


@router.post(
    "/forecasts/{forecast_id}/acknowledge/",
    response_model=ForecastAlertRow,
    dependencies=[Depends(RequirePermission("project_intelligence.create"))],
)
async def acknowledge_forecast_alert(
    forecast_id: uuid.UUID,
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ForecastAlertRow:
    """Acknowledge a forecast alert - removes it from the active list."""
    forecast = await _load_forecast_for_write(session, forecast_id, user_id)

    from app.modules.full_evm.service import EVMService

    service = EVMService(session)
    updated = await service.acknowledge_alert(forecast_id)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Forecast {forecast_id} not found",
        )
    _invalidate_cache(user_id, str(forecast.project_id))
    severity, summary = _breach_summary(updated)
    return ForecastAlertRow(
        forecast_id=str(updated.id),
        forecast_date=updated.forecast_date,
        alert_status=updated.alert_status or "acknowledged",
        triggered_at=updated.triggered_at.isoformat() if updated.triggered_at else None,
        severity=severity,
        eac=updated.eac,
        vac=updated.vac,
        tcpi=updated.tcpi,
        summary=summary,
    )


@router.post(
    "/forecasts/{forecast_id}/snooze/",
    response_model=ForecastAlertRow,
    dependencies=[Depends(RequirePermission("project_intelligence.create"))],
)
async def snooze_forecast_alert(
    forecast_id: uuid.UUID,
    body: SnoozeForecastRequest | None = None,
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ForecastAlertRow:
    """Snooze a forecast alert for N hours (default 24)."""
    forecast = await _load_forecast_for_write(session, forecast_id, user_id)
    hours = body.hours if body is not None else 24

    from app.modules.full_evm.service import EVMService

    service = EVMService(session)
    updated = await service.snooze_alert(forecast_id, hours)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Forecast {forecast_id} not found",
        )
    _invalidate_cache(user_id, str(forecast.project_id))
    severity, summary = _breach_summary(updated)
    meta = updated.metadata_ or {}
    return ForecastAlertRow(
        forecast_id=str(updated.id),
        forecast_date=updated.forecast_date,
        alert_status=updated.alert_status or "snoozed",
        triggered_at=updated.triggered_at.isoformat() if updated.triggered_at else None,
        snoozed_until=meta.get("snoozed_until") if isinstance(meta, dict) else None,
        severity=severity,
        eac=updated.eac,
        vac=updated.vac,
        tcpi=updated.tcpi,
        summary=summary,
    )


# ── GET /{project_id}/forecast (TOP-30 #19) ───────────────────────────────
#
# Live, READ-ONLY predictive analytics: recomputes the canonical Earned-Value
# forecast from the latest EVM snapshot, projects the schedule finish-date
# variance, and scores the cost-overrun risk deterministically. Distinct from
# the persisted-forecast alert surface (/forecasts/) above: nothing is written.
# The two-segment path never collides with the single-segment /forecasts/.


@router.get(
    "/{project_id}/forecast",
    response_model=ProjectForecastResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def get_project_forecast(
    project_id: uuid.UUID,
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ProjectForecastResponse:
    """Return live predictive cost + schedule + risk analytics for a project.

    Cost forecast (CPI/SPI/EAC/ETC/VAC/TCPI) is recomputed from the latest EVM
    snapshot; when none exists the cost section degrades gracefully with a
    reason. The schedule slip projects a finish-date variance and at-risk task
    count; the deterministic risk score carries a confidence and a rationale.
    This is a forecast - human review is required; no action is taken.
    """
    await _verify_project_access(session, project_id, user_id)
    forecast = await ForecastService(session).get_project_forecast(project_id)
    return ProjectForecastResponse(
        project_id=forecast.project_id,
        project_name=forecast.project_name,
        currency=forecast.currency,
        generated_at=forecast.generated_at,
        cost=CostForecastResponse(**asdict(forecast.cost)),
        schedule=ScheduleSlipResponse(**asdict(forecast.schedule)),
        risk=CostOverrunRiskResponse(**asdict(forecast.risk)),
        review_required=forecast.review_required,
    )
