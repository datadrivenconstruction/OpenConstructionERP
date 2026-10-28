# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Value-realized service - the thin database layer over the pure value engines.

This module owns no records of its own. It gathers figures that other services
have ALREADY computed and feeds them to the pure :mod:`app.modules.value`
engines, composing a single "value realized" view a dashboard can show without
re-deriving anything:

* approved-change committed cost + schedule  -> ``change_intelligence`` impact
  gathering (:func:`gather_approved_changes`), mapped onto
  :class:`value_math.ImpactInput`.
* recovery ledger (chargeable / recovered / absorbed per currency)  -> the
  ``cost_recovery`` back-charge engine via
  :func:`compute_recovery_performance`, mapped onto
  :class:`value_math.RecoveryInput`.
* admin hours given back  -> ``oe_activity_log`` rows scoped to the project the
  same way the timeline does (``parent_entity_id`` / ``entity_id`` == project),
  mapped onto :class:`time_saved.ActivityEvent` and summed with the documented
  default minute factors.
* cohort adoption benchmark  -> per project a :class:`adoption_benchmark.ProjectAdoption`
  assembled from activity volume, change volume, the traceable-change share
  (a change with a recorded ball-in-court owner), the recovery rate and the
  average open-change cycle days.

Every read is scoped exactly like the other project-scoped services; the
request-scoped session dependency owns the commit, and this layer only ever
queries, so it never writes.

Honest gaps (passed as ``None``; the engines handle ``None`` with low-n
confidence): a single project's cost-position percentile vs its own portfolio is
not cheaply available without recomputing every project's BOQ rollup, so the
per-project benchmark percentile is ``None`` here; ``overrun_pct`` for the
adoption benchmark needs a budget baseline this layer does not have, so it is
also ``None``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Mapping

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import ActivityLog
from app.modules.change_intelligence.service import (
    gather_approved_changes,
    gather_change_items,
)
from app.modules.cost_recovery.recovery_analytics import (
    RecoveryItem,
    RecoveryPerformance,
    compute_recovery_performance,
)
from app.modules.cost_recovery.service import list_back_charges, to_back_charge_item
from app.modules.value.adoption_benchmark import (
    AdoptionBenchmark,
    ProjectAdoption,
    compute_adoption_benchmark,
)
from app.modules.value.time_saved import (
    DEFAULT_FACTORS,
    ActivityEvent,
    SavedBucket,
    aggregate_hours,
    estimate_saved_minutes,
    total_hours,
)
from app.modules.value.value_math import (
    ActivityInput,
    BenchmarkInput,
    HoursSavedInput,
    ImpactInput,
    RecoveryInput,
    ValueSummary,
    compose_portfolio_summary,
    compose_value_summary,
)


def _project_scope(project_id: uuid.UUID):
    """Predicate selecting activity-log rows that belong to a project.

    Identical scope to :mod:`app.modules.timeline.service`: a row is in scope
    when its ``parent_entity_id`` is the project (module events rolled up to
    their umbrella project) or its ``entity_id`` is the project (events logged
    directly against the project row). Activity is the natural home of the
    hours-saved signal because every assisted action already lands a row there.
    """
    pid = str(project_id)
    return or_(ActivityLog.parent_entity_id == pid, ActivityLog.entity_id == pid)


async def _gather_activity_events(session: AsyncSession, project_id: uuid.UUID) -> list[ActivityEvent]:
    """Read a project's activity-log rows as engine :class:`ActivityEvent` items.

    Only the columns the hours engine needs are selected. ``project_id`` is set
    to the known project on every event (the query is already project-scoped),
    so a per-project aggregation never has to re-resolve it. A row with no
    ``module`` simply maps to an empty module string, which the engine treats as
    an unrecognised action that saves nothing.
    """
    stmt = select(
        ActivityLog.action,
        ActivityLog.module,
        ActivityLog.created_at,
        ActivityLog.actor_id,
    ).where(_project_scope(project_id))
    events: list[ActivityEvent] = []
    for row in (await session.execute(stmt)).all():
        events.append(
            ActivityEvent(
                action=row.action or "",
                module=row.module or "",
                at=row.created_at,
                actor_id=str(row.actor_id) if row.actor_id is not None else None,
                project_id=str(project_id),
            )
        )
    return events


def _impact_inputs(approved_changes) -> list[ImpactInput]:  # type: ignore[no-untyped-def]
    """Map gathered approved changes onto the value engine's impact inputs.

    Only the committed (approved / agreed) changes the change-intelligence
    gathering already filtered to are passed; this layer does not re-judge
    approval. Schedule days are carried as a Decimal beside the money, never
    folded into it.
    """
    return [
        ImpactInput(
            kind=change.kind,
            currency=change.currency,
            committed_cost=change.cost_impact,
            schedule_days=Decimal(change.schedule_impact_days),
        )
        for change in approved_changes
    ]


async def _recovery_performance(session: AsyncSession, project_id: uuid.UUID) -> RecoveryPerformance:
    """Recovery performance for a project, computed once and reused.

    Reuses the ``cost_recovery`` projection of stored back-charge rows and runs
    them through :func:`compute_recovery_performance`, which yields a
    chargeable / recovered / absorbed total and a recovery rate per currency
    (band-independent at the currency level, so the absorbed figure is honest
    even though back-charge rows carry no evidence band). A blank evidence band
    is normalised by the engine to its conservative default; only the currency
    totals are surfaced upstream, never the cohort breakdowns.
    """
    rows = await list_back_charges(session, project_id)
    items = [
        RecoveryItem(
            chargeable=bc.chargeable_amount,
            recovered=bc.recovered_amount,
            currency=bc.currency,
            traceability_band="",
            status=bc.status,
        )
        for bc in (to_back_charge_item(row) for row in rows)
    ]
    return compute_recovery_performance(items)


def _recovery_inputs(performance: RecoveryPerformance) -> list[RecoveryInput]:
    """Map a recovery performance projection onto per-currency engine inputs.

    One :class:`RecoveryInput` per currency, carrying the chargeable / recovered
    / absorbed totals; money is never blended across currency codes.
    """
    return [
        RecoveryInput(
            currency=cur.currency,
            chargeable=cur.chargeable_total,
            recovered=cur.recovered_total,
            absorbed=cur.absorbed_total,
        )
        for cur in performance.by_currency
    ]


def _hours_input(
    events: list[ActivityEvent],
    factors: Mapping[tuple[str, str], Decimal] = DEFAULT_FACTORS,
) -> HoursSavedInput:
    """Total the hours saved across activity events + count saving-bearing rows.

    The figure is the engine's :func:`total_hours` over the effective minute
    factors (the tenant's admin overrides layered on the seed defaults). The
    sample backing its confidence is the number of rows that actually map to a
    non-zero saving (an action the platform genuinely performs in place of a
    person), so an honest denominator drives the confidence rather than the raw
    row count.
    """
    saving_rows = sum(
        1 for ev in events if estimate_saved_minutes(ev.action, ev.module, ev.units, factors) > Decimal("0")
    )
    return HoursSavedInput(hours=total_hours(events, factors), sample=saving_rows)


async def build_value_summary(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    factors: Mapping[tuple[str, str], Decimal] | None = None,
) -> ValueSummary:
    """Compose one project's value-realized summary from already-computed inputs.

    Gathers approved-change impacts, the recovery ledger per currency, the admin
    hours given back and the activity volume, then composes them with the pure
    :func:`compose_value_summary`. The cost-position percentile is passed as
    ``None`` (a single project's percentile vs its own portfolio is not cheaply
    available without recomputing BOQ rollups), so the dispute-risk proxy here
    rests on the recovery rate alone - the engine handles that honestly.

    ``factors`` is the effective minute-factor map (admin overrides over the seed
    defaults) used for the hours-saved figure; when ``None`` the documented
    :data:`DEFAULT_FACTORS` are used, so a caller that has not resolved the
    tenant's overrides still gets the honest default behaviour.
    """
    effective = DEFAULT_FACTORS if factors is None else factors
    approved_changes = await gather_approved_changes(session, project_id)
    impacts = _impact_inputs(approved_changes)

    performance = await _recovery_performance(session, project_id)
    recoveries = _recovery_inputs(performance)

    events = await _gather_activity_events(session, project_id)
    hours = _hours_input(events, effective)
    activity = ActivityInput(count=len(events))

    benchmark = BenchmarkInput(percentile=None)

    return compose_value_summary(
        impacts=impacts,
        recoveries=recoveries,
        hours=hours,
        benchmark=benchmark,
        activity=activity,
    )


async def build_hours_saved(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    by: str,
    period: str | None = None,
    factors: Mapping[tuple[str, str], Decimal] | None = None,
) -> tuple[tuple[SavedBucket, ...], Decimal, int]:
    """Aggregate a project's hours saved on one axis + the total and row count.

    Returns ``(buckets, total_hours, event_count)``: the per-bucket breakdown
    from :func:`aggregate_hours`, the single headline total (which reconciles
    with the sum of the per-bucket minutes), and how many activity rows the
    figure rests on. ``factors`` is the effective minute-factor map (admin
    overrides over the seed defaults); ``None`` falls back to
    :data:`DEFAULT_FACTORS`. Read-only; the caller has already authorised the
    project.
    """
    effective = DEFAULT_FACTORS if factors is None else factors
    events = await _gather_activity_events(session, project_id)
    buckets = aggregate_hours(events, by=by, factors=effective, period=period)
    return buckets, total_hours(events, effective), len(events)


# --- Portfolio + adoption benchmark ----------------------------------------


async def build_portfolio_summary(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    factors: Mapping[tuple[str, str], Decimal] | None = None,
) -> ValueSummary:
    """Roll several projects' value summaries up into one portfolio summary.

    Builds a per-project :class:`ValueSummary` for each id (already filtered by
    the caller to the projects they may access) and aggregates with the pure
    :func:`compose_portfolio_summary`, which sums money per currency (never
    blending currency codes) and takes the more cautious confidence. ``factors``
    is the effective minute-factor map applied to every project's hours figure;
    ``None`` falls back to :data:`DEFAULT_FACTORS`. Empty input yields an empty
    summary.
    """
    summaries: list[ValueSummary] = []
    for pid in project_ids:
        summaries.append(await build_value_summary(session, pid, factors=factors))
    return compose_portfolio_summary(summaries)


def _recovery_rate_for_project(performance) -> Decimal | None:  # type: ignore[no-untyped-def]
    """The project's primary-currency recovery rate, or ``None``.

    A unitless fraction, so the adoption benchmark (which averages rates across
    projects) can use it directly. ``None`` when the project had nothing
    chargeable - an honest undefined ratio the benchmark excludes from the mean
    rather than counting as zero.
    """
    return performance.primary_rate


async def _project_adoption(session: AsyncSession, project_id: uuid.UUID) -> ProjectAdoption:
    """Assemble one project's adoption + outcome facts for the benchmark.

    * ``activity_count`` - the project's activity-log row count (assisted work).
    * ``change_count`` - the number of change-family records.
    * ``traceable_change_count`` - changes with a recorded ball-in-court owner; a
      clear current owner is the traceability signal the report ties to recovery.
    * ``recovery_rate`` - the primary-currency recovery rate, or ``None``.
    * ``overrun_pct`` - ``None``: an overrun fraction needs a budget baseline
      this layer does not have, so it is left undefined (excluded from the mean)
      rather than guessed.
    * ``avg_cycle_days`` - the mean age of the project's open changes, or
      ``None`` when there are none. Open-change age is the cycle-time signal the
      change-intelligence board already exposes.
    """
    change_items = await gather_change_items(session, project_id)
    change_count = len(change_items)
    traceable = sum(1 for it in change_items if (it.ball_in_court or "").strip())

    events = await _gather_activity_events(session, project_id)
    activity_count = len(events)

    # Recovery rate from the same per-currency recovery projection.
    performance = await _recovery_performance(session, project_id)
    recovery_rate = _recovery_rate_for_project(performance)

    avg_cycle_days = _avg_open_change_age_days(change_items)

    return ProjectAdoption(
        project_id=str(project_id),
        activity_count=activity_count,
        change_count=change_count,
        traceable_change_count=traceable,
        recovery_rate=recovery_rate,
        overrun_pct=None,
        avg_cycle_days=avg_cycle_days,
    )


def _avg_open_change_age_days(change_items) -> float | None:  # type: ignore[no-untyped-def]
    """Mean age in days of the open change records, or ``None`` when there are none.

    A lightweight cycle-time signal taken straight from the records' opened
    timestamps (the same ``opened_at`` the cycle-time board ages), without
    rebuilding the full board. Naive timestamps are read as UTC. Returns ``None``
    when no change is open, so the benchmark excludes the project from the
    cycle-time mean rather than counting it as zero days.
    """
    now = datetime.now(UTC)
    ages: list[float] = []
    for it in change_items:
        if not it.is_open:
            continue
        opened = it.opened_at
        if opened is None:
            continue
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=UTC)
        ages.append((now - opened).total_seconds() / 86400.0)
    if not ages:
        return None
    return sum(ages) / len(ages)


async def build_adoption_benchmark(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> AdoptionBenchmark:
    """Score adoption per project and compare the high / low cohorts.

    Assembles a :class:`ProjectAdoption` for each accessible project and runs the
    pure :func:`compute_adoption_benchmark`, which scores each project's adoption
    from its activity density and traceable-change share, splits the portfolio
    into a high- and low-adoption cohort, and compares them on recovery rate,
    overrun and cycle time with honest low-n confidence. Empty input yields no
    scores and an overall ``none`` confidence.
    """
    adoptions: list[ProjectAdoption] = []
    for pid in project_ids:
        adoptions.append(await _project_adoption(session, pid))
    return compute_adoption_benchmark(adoptions)
