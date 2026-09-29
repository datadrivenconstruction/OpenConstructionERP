# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Value-realized API routes (auto-mounted at /api/v1/value).

One read surface that composes figures the rest of the platform already
computes - approved-change exposure managed, cost recovered, admin hours given
back and a documented dispute-risk proxy - into a project and portfolio
"value realized" view, plus an adoption-vs-non-adoption benchmark on the firm's
own projects.

Access control mirrors every other project-scoped router: the project-scoped
endpoints require an authenticated caller who passes :func:`verify_project_access`
for the requested project (404 on both missing and denied, so project existence
never leaks). The portfolio and benchmark endpoints scope to the caller's
accessible projects via :func:`accessible_project_ids` (admins see all).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.dependencies import (
    CurrentTenantId,
    CurrentUserId,
    RequirePermission,
    RequireRole,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)
from app.modules.value.adoption_service import build_adoption_checklist
from app.modules.value.schemas import (
    AdoptionBenchmarkOut,
    AdoptionChecklistOut,
    AdoptionStepOut,
    CohortComparisonOut,
    CurrencyValueOut,
    HoursSavedBucketOut,
    HoursSavedOut,
    ProjectScoreOut,
    TimeFactorOut,
    TimeFactorsOut,
    TimeFactorsUpdate,
    ValueSummaryOut,
)
from app.modules.value.service import (
    build_adoption_benchmark,
    build_hours_saved,
    build_portfolio_summary,
    build_value_summary,
)
from app.modules.value.time_factors_service import (
    FactorRow,
    list_factors,
    resolve_effective_factors,
    set_factors,
)
from app.modules.value.time_saved import (
    BY_FEATURE,
    BY_PERIOD,
    BY_PROJECT,
    BY_USER,
    PERIOD_MONTH,
    PERIOD_WEEK,
)
from app.modules.value.value_math import ValueSummary

router = APIRouter(tags=["Value"])

# Accepted grouping axes / period granularities for the hours-saved endpoint,
# validated explicitly so an unknown value yields a 422 rather than reaching the
# engine (which would raise). BY_PERIOD needs a period granularity.
_HOURS_AXES = frozenset({BY_USER, BY_PROJECT, BY_FEATURE, BY_PERIOD})
_HOURS_PERIODS = frozenset({PERIOD_WEEK, PERIOD_MONTH})


def _rate_str(value) -> str | None:  # type: ignore[no-untyped-def]
    """Render a Decimal rate / proxy as a string, preserving ``None``."""
    return None if value is None else str(value)


def _summary_out(summary: ValueSummary, *, project_id: str | None) -> ValueSummaryOut:
    """Build the wire model for a value summary, money + rates as strings."""
    return ValueSummaryOut(
        project_id=project_id,
        by_currency=[
            CurrencyValueOut(
                currency=row.currency,
                overrun_exposure_managed=str(row.overrun_exposure_managed),
                chargeable_total=str(row.chargeable_total),
                recovered_total=str(row.recovered_total),
                absorbed_total=str(row.absorbed_total),
                recovery_rate=_rate_str(row.recovery_rate),
                schedule_days_managed=str(row.schedule_days_managed),
                impact_count=row.impact_count,
                recovery_item_count=row.recovery_item_count,
            )
            for row in summary.by_currency
        ],
        primary_currency=summary.primary_currency,
        estimated_hours_saved=str(summary.estimated_hours_saved),
        dispute_risk_reduction=_rate_str(summary.dispute_risk_reduction),
        exposure_confidence=summary.exposure_confidence,
        recovery_confidence=summary.recovery_confidence,
        hours_confidence=summary.hours_confidence,
        risk_confidence=summary.risk_confidence,
        cost_position_percentile=summary.cost_position_percentile,
        impact_count=summary.impact_count,
        recovery_item_count=summary.recovery_item_count,
        hours_sample=summary.hours_sample,
        activity_count=summary.activity_count,
    )


@router.get(
    "/projects/{project_id}/summary",
    response_model=ValueSummaryOut,
    dependencies=[Depends(RequirePermission("value.read"))],
)
async def get_value_summary(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    tenant_id: CurrentTenantId = None,
) -> ValueSummaryOut:
    """One project's composed value-realized summary (per currency + headlines).

    The hours-saved headline honours the tenant's admin-tuned minute factors
    (falling back to the documented defaults for any pair left unset).
    """
    await verify_project_access(project_id, user_id or "", session)
    factors = await resolve_effective_factors(session, tenant_id)
    summary = await build_value_summary(session, project_id, factors=factors)
    return _summary_out(summary, project_id=str(project_id))


@router.post(
    "/projects/{project_id}/report",
    response_model=ValueSummaryOut,
    dependencies=[Depends(RequirePermission("value.read"))],
)
async def generate_value_report(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    tenant_id: CurrentTenantId = None,
) -> ValueSummaryOut:
    """Generate a project's value report and record that it was generated.

    Returns the same composed value summary the dashboard shows, and writes a
    single ``value`` / ``report_generated`` activity-log row so generating the
    value case counts toward guided adoption and lands in the audit trail. The
    action carries no saved-minute factor, so it never inflates the hours-saved
    figure. Access is gated exactly like the summary (404 on missing or denied).
    """
    await verify_project_access(project_id, user_id or "", session)
    factors = await resolve_effective_factors(session, tenant_id)
    summary = await build_value_summary(session, project_id, factors=factors)
    await log_activity(
        session,
        actor_id=user_id or None,
        entity_type="value.report",
        entity_id=str(project_id),
        action="report_generated",
        module="value",
        parent_entity_type="project",
        parent_entity_id=str(project_id),
    )
    return _summary_out(summary, project_id=str(project_id))


@router.get(
    "/portfolio/summary",
    response_model=ValueSummaryOut,
    dependencies=[Depends(RequirePermission("value.read"))],
)
async def get_portfolio_summary(
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    tenant_id: CurrentTenantId = None,
) -> ValueSummaryOut:
    """Portfolio-wide value summary across every project the caller may access.

    Non-admins are scoped to projects they own or are a team member of; an admin
    sees all. An empty accessible set yields an empty summary rather than an
    error - the safe default for a caller with no projects. The hours figure uses
    the tenant's admin-tuned minute factors.
    """
    # A portfolio rollup: deleted (archived) projects are not part of it.
    ids = await accessible_project_ids(session, user_id, live_only=True)
    project_ids = await _resolve_project_ids(session, ids)
    factors = await resolve_effective_factors(session, tenant_id)
    summary = await build_portfolio_summary(session, project_ids, factors=factors)
    return _summary_out(summary, project_id=None)


@router.get(
    "/projects/{project_id}/hours-saved",
    response_model=HoursSavedOut,
    dependencies=[Depends(RequirePermission("value.read"))],
)
async def get_hours_saved(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    tenant_id: CurrentTenantId = None,
    by: str = Query(BY_FEATURE, description="Grouping axis: user / project / feature / period"),
    period: str | None = Query(None, description="Period granularity when by=period: week / month"),
) -> HoursSavedOut:
    """A project's estimated admin hours saved, grouped on one axis.

    ``by`` defaults to ``feature`` (``module/action``). When ``by=period`` a
    ``period`` of ``week`` or ``month`` is required. An unrecognised axis or
    period yields a 422 before the engine is reached. The minutes/hours honour
    the tenant's admin-tuned factors.
    """
    await verify_project_access(project_id, user_id or "", session)

    axis = by if by in _HOURS_AXES else BY_FEATURE
    effective_period: str | None = None
    if axis == BY_PERIOD:
        effective_period = period if period in _HOURS_PERIODS else PERIOD_WEEK

    factors = await resolve_effective_factors(session, tenant_id)
    buckets, total, event_count = await build_hours_saved(
        session,
        project_id,
        by=axis,
        period=effective_period,
        factors=factors,
    )
    return HoursSavedOut(
        project_id=str(project_id),
        by=axis,
        total_hours=str(total),
        event_count=event_count,
        buckets=[
            HoursSavedBucketOut(
                key=b.key,
                event_count=b.event_count,
                unit_count=b.unit_count,
                minutes=str(b.minutes),
                hours=str(b.hours),
            )
            for b in buckets
        ],
    )


@router.get(
    "/adoption-benchmark",
    response_model=AdoptionBenchmarkOut,
    dependencies=[Depends(RequirePermission("value.read"))],
)
async def get_adoption_benchmark(
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> AdoptionBenchmarkOut:
    """High-vs-low adoption benchmark across the caller's accessible projects.

    Scores each project's adoption of the change discipline and contrasts the
    high- and low-adoption cohorts on recovery rate, overrun and cycle time, with
    honest low-n confidence. Scoped to the caller's accessible projects.
    """
    # A portfolio rollup: deleted (archived) projects are not part of it.
    ids = await accessible_project_ids(session, user_id, live_only=True)
    project_ids = await _resolve_project_ids(session, ids)
    benchmark = await build_adoption_benchmark(session, project_ids)
    return AdoptionBenchmarkOut(
        project_scores=[
            ProjectScoreOut(project_id=s.project_id, adoption=s.adoption, cohort=s.cohort)
            for s in benchmark.project_scores
        ],
        comparisons=[
            CohortComparisonOut(
                metric=c.metric,
                high_mean=c.high_mean,
                low_mean=c.low_mean,
                delta=c.delta,
                high_n=c.high_n,
                low_n=c.low_n,
                higher_is_better=c.higher_is_better,
                favours_high=c.favours_high,
                confidence=c.confidence,
            )
            for c in benchmark.comparisons
        ],
        confidence=benchmark.confidence,
        high_count=benchmark.high_count,
        low_count=benchmark.low_count,
    )


@router.get(
    "/projects/{project_id}/adoption-checklist",
    response_model=AdoptionChecklistOut,
    dependencies=[Depends(RequirePermission("value.read"))],
)
async def get_adoption_checklist(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    role: str = Query("manager", description="Role lens: manager / estimator / field / reviewer"),
) -> AdoptionChecklistOut:
    """One project's guided adoption checklist for a role.

    Shows which first-value steps the project has reached - a BOQ imported, a
    takeoff run, an approval routed, a change logged, an AI run and its verdict,
    an evidence pack assembled - and the next few to nudge, scored as a weighted
    percent of the steps that apply to the role. Detection reads the project's
    present state, so the picture reflects what was actually done rather than
    whether an event happened to be logged. Read-only; requires access to the
    project (404 on missing or denied, so existence never leaks).
    """
    await verify_project_access(project_id, user_id or "", session)
    checklist = await build_adoption_checklist(session, project_id, role)
    return AdoptionChecklistOut(
        project_id=str(project_id),
        role=checklist.role,
        adoption_score=checklist.adoption_score,
        steps=[
            AdoptionStepOut(key=s.step.key, label=s.step.label, module=s.step.module, done=s.done)
            for s in checklist.steps
        ],
        next_actions=[
            AdoptionStepOut(key=a.key, label=a.label, module=a.module, done=False) for a in checklist.next_actions
        ],
    )


# --- Admin: editable hours-saved minute factors ----------------------------
#
# The hours-saved figure rests on a small "minutes one assisted action displaces"
# lookup. The seed defaults are conservative; an operator who has measured their
# own baseline can tune any factor here, per tenant. These endpoints are
# admin-only (RequireRole) because the factor directly drives a headline figure
# shown across the firm, and they are NOT project-scoped - the factors apply to
# every project in the tenant.


def _factor_out(row: FactorRow) -> TimeFactorOut:
    """Render an editable factor row for the wire (minutes as strings, not money)."""
    return TimeFactorOut(
        module=row.module,
        action=row.action,
        minutes=str(row.minutes),
        default_minutes=None if row.default_minutes is None else str(row.default_minutes),
        is_override=row.is_override,
    )


@router.get("/admin/time-factors", response_model=TimeFactorsOut)
async def get_time_factors(
    session: SessionDep,
    _: None = Depends(RequireRole("admin")),
    tenant_id: CurrentTenantId = None,
) -> TimeFactorsOut:
    """List the tenant's editable hours-saved minute factors (admin only).

    Returns every seed-default pair plus any tenant-only overrides, each marked
    with its current minutes, the seed default, and whether it is a tuned
    override. The values are minutes of saved effort - there is no money on this
    surface.
    """
    rows = await list_factors(session, tenant_id)
    return TimeFactorsOut(factors=[_factor_out(r) for r in rows])


@router.put("/admin/time-factors", response_model=TimeFactorsOut)
async def put_time_factors(
    payload: TimeFactorsUpdate,
    session: SessionDep,
    _: None = Depends(RequireRole("admin")),
    tenant_id: CurrentTenantId = None,
) -> TimeFactorsOut:
    """Update the tenant's hours-saved minute factors (admin only).

    Applies a batch of ``(module, action, minutes)`` overrides for the caller's
    tenant. A value equal to the seed default clears the override (the pair
    reverts to inheriting the default). Minutes are validated as finite, non
    -negative and capped; an invalid value rejects the whole batch with a 422 and
    writes nothing. Returns the full factor surface after the change.
    """
    if tenant_id is None:
        # An admin whose tenant cannot be resolved has nowhere to scope the
        # write; refuse rather than persist an unscoped (null-tenant) override.
        raise HTTPException(status_code=400, detail="Tenant could not be resolved for the current user")
    try:
        rows = await set_factors(
            session,
            tenant_id,
            [(f.module, f.action, f.minutes) for f in payload.factors],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TimeFactorsOut(factors=[_factor_out(r) for r in rows])


async def _resolve_project_ids(
    session: AsyncSession,
    accessible: set[uuid.UUID] | None,
) -> list[uuid.UUID]:
    """Turn the accessible-project sentinel into a concrete id list.

    ``accessible_project_ids`` returns ``None`` for an admin (meaning "do not
    filter" - every project). Here we need a concrete list to roll up, so an
    admin is expanded to all project ids; a non-admin uses their own set (which
    may be empty, yielding an empty roll-up).
    """
    if accessible is not None:
        return sorted(accessible)

    from app.modules.projects.models import Project

    rows = (await session.execute(select(Project.id))).scalars().all()
    return [r if isinstance(r, uuid.UUID) else uuid.UUID(str(r)) for r in rows]
