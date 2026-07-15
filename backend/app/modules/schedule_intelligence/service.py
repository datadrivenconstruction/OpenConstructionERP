"""Schedule Intelligence service — governance business logic (Phase 0).

Stateless functions that accept an ``AsyncSession`` plus domain primitives,
orchestrate repository calls, and raise :class:`fastapi.HTTPException` for
caller-visible failures. Two governance workflows live here:

    * **Locked figures (E5.2)** — lock / unlock / list, and a dry-run verify of
      a batch of proposed writes against the active locks. Locking is
      idempotent (re-locking the identical value is a no-op) and monotonic (you
      cannot re-lock a path to a *different* value without unlocking first).
    * **Confidence config (E5.3)** — resolve the active policy for a project
      (project row → global row → built-in default, never silent about which)
      and upsert a new versioned policy.

Apply/decision flows (Phases 2–4) will reuse the existing ``app/core`` approval
gate + audit; this module adds no gate of its own.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.schedule.models import Activity
from app.modules.schedule_advanced.models import Constraint, LookAheadPlan, MasterSchedule
from app.modules.schedule_advanced.repository import ConstraintRepository
from app.modules.schedule_intelligence.confidence import (
    ConfidencePolicy,
    ConfidenceResult,
    compute_confidence,
)
from app.modules.schedule_intelligence.locked_guard import (
    LockedFigureGuard,
    LockedFigureViolation,
    canonical_value,
    value_hash,
)
from app.modules.schedule_intelligence.models import (
    ConfidenceConfig,
    LockedFigure,
    ReadinessResult,
)
from app.modules.schedule_intelligence.readiness_engine import (
    ActivityInput,
    ConstraintInput,
    evaluate_look_ahead,
    run_digest,
)
from app.modules.schedule_intelligence.repository import (
    ConfidenceConfigRepository,
    LockedFigureRepository,
    ReadinessResultRepository,
)
from app.modules.schedule_intelligence.schemas import (
    ConfidenceConfigUpsert,
    ConfidencePreviewRequest,
    LockFigureRequest,
    VerifyWritesRequest,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ─────────────────────────────────────────────────────────────────────────────
# E5.2 — Locked figures
# ─────────────────────────────────────────────────────────────────────────────
async def lock_figure(
    session: AsyncSession,
    project_id: uuid.UUID,
    payload: LockFigureRequest,
    user_id: uuid.UUID | None,
) -> LockedFigure:
    """Lock a commercial figure at ``payload.path``.

    Idempotent: re-locking the identical canonical value returns the existing
    lock. Monotonic: attempting to lock a path that already holds a *different*
    active value is a conflict (409) — the figure must be explicitly unlocked
    first, so a lock can never be silently overwritten.
    """
    canonical = canonical_value(payload.value)
    repo = LockedFigureRepository(session)

    existing = await repo.get_active_by_path(project_id, payload.path)
    if existing is not None:
        if existing.value == canonical:
            return existing  # idempotent re-lock of the same value
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Path {payload.path!r} is already locked to a different value; unlock it before re-locking."),
        )

    row = LockedFigure(
        project_id=project_id,
        path=payload.path,
        figure_type=payload.figure_type.value,
        value=canonical,
        value_hash=value_hash(canonical),
        source_ref=payload.source_ref,
        reason=payload.reason,
        active=True,
        locked_by=user_id,
        locked_at=_utcnow(),
    )
    row = await repo.add(row)
    _publish(
        "schedule_intelligence.figure.locked",
        {
            "id": str(row.id),
            "project_id": str(project_id),
            "path": row.path,
            "figure_type": row.figure_type,
        },
    )
    return row


async def unlock_figure(
    session: AsyncSession,
    project_id: uuid.UUID,
    figure_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> LockedFigure:
    """Release an active lock (kept as an inactive row for audit)."""
    repo = LockedFigureRepository(session)
    row = await repo.get_by_id(figure_id)
    # 404 (not 403) when the row belongs to another project — same IDOR policy
    # as verify_project_access: never confirm the existence of a foreign id.
    if row is None or row.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Locked figure not found")
    if not row.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Figure is already unlocked")

    row.active = False
    row.unlocked_by = user_id
    row.unlocked_at = _utcnow()
    await session.flush()
    _publish(
        "schedule_intelligence.figure.unlocked",
        {"id": str(row.id), "project_id": str(project_id), "path": row.path},
    )
    return row


async def list_locked_figures(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    include_inactive: bool = False,
) -> list[LockedFigure]:
    repo = LockedFigureRepository(session)
    return await repo.list_for_project(project_id, include_inactive=include_inactive)


async def build_guard(session: AsyncSession, project_id: uuid.UUID) -> LockedFigureGuard:
    """Load the project's active locks into a :class:`LockedFigureGuard`.

    Every write flow in later phases builds a guard from here and gates its
    payload through it before persisting.
    """
    repo = LockedFigureRepository(session)
    rows = await repo.list_active_for_project(project_id)
    return LockedFigureGuard.from_rows(rows)


async def verify_writes(
    session: AsyncSession,
    project_id: uuid.UUID,
    payload: VerifyWritesRequest,
) -> list[LockedFigureViolation]:
    """Dry-run proposed writes against active locks; return any violations.

    Read-only. Persists nothing — this is the preview an apply screen calls
    before committing, so the user sees exactly what would be blocked.
    """
    guard = await build_guard(session, project_id)
    violations: list[LockedFigureViolation] = []
    for path in sorted(payload.writes):
        try:
            guard.assert_writable(path, payload.writes[path])
        except LockedFigureViolation as exc:
            violations.append(exc)
    return violations


# ─────────────────────────────────────────────────────────────────────────────
# E5.3 — Confidence configuration + preview
# ─────────────────────────────────────────────────────────────────────────────
async def resolve_policy(session: AsyncSession, project_id: uuid.UUID) -> tuple[ConfidencePolicy, str]:
    """Resolve the active confidence policy and its source.

    Precedence: project override → deployment-wide default row → built-in
    fallback. Returns ``(policy, source)`` where ``source`` is one of
    ``"project" | "global" | "default"`` so callers never have to guess which
    policy priced an insight.
    """
    repo = ConfidenceConfigRepository(session)

    project_row = await repo.get_active_for_project(project_id)
    if project_row is not None:
        return ConfidencePolicy.from_config(project_row), "project"

    global_row = await repo.get_active_global()
    if global_row is not None:
        return ConfidencePolicy.from_config(global_row), "global"

    return ConfidencePolicy.default(), "default"


async def upsert_confidence_config(
    session: AsyncSession,
    project_id: uuid.UUID,
    payload: ConfidenceConfigUpsert,
    user_id: uuid.UUID | None,
) -> ConfidenceConfig:
    """Create a new active confidence-config version for a project.

    Deactivates any currently-active project rows and inserts a fresh version
    (``max(version)+1``). Omitted maps inherit the built-in default facet, so a
    partial config is still valid.
    """
    repo = ConfidenceConfigRepository(session)
    default = ConfidencePolicy.default()

    for stale in await repo.list_active_for_project(project_id):
        stale.active = False

    next_version = await repo.max_version_for_project(project_id) + 1
    row = ConfidenceConfig(
        project_id=project_id,
        version=next_version,
        active=True,
        description=payload.description,
        band_thresholds=payload.band_thresholds
        if payload.band_thresholds is not None
        else dict(default.band_thresholds),
        schedule_quality_caps=payload.schedule_quality_caps
        if payload.schedule_quality_caps is not None
        else dict(default.schedule_quality_caps),
        feed_coverage_caps=payload.feed_coverage_caps
        if payload.feed_coverage_caps is not None
        else dict(default.feed_coverage_caps),
        corroboration_bonuses=payload.corroboration_bonuses
        if payload.corroboration_bonuses is not None
        else dict(default.corroboration_bonuses),
        created_by=user_id,
    )
    row = await repo.add(row)
    _publish(
        "schedule_intelligence.confidence_config.updated",
        {
            "id": str(row.id),
            "project_id": str(project_id),
            "version": next_version,
        },
    )
    return row


async def preview_confidence(
    session: AsyncSession,
    project_id: uuid.UUID,
    payload: ConfidencePreviewRequest,
) -> ConfidenceResult:
    """Compute a uniform confidence result under the project's active policy."""
    policy, _source = await resolve_policy(session, project_id)
    return compute_confidence(
        payload.base_score,
        schedule_quality=payload.schedule_quality,
        feed_coverage=payload.feed_coverage,
        corroboration=payload.corroboration,
        policy=policy,
    )


# ─────────────────────────────────────────────────────────────────────────────
# E1 — Readiness (Watch)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_iso_date(value: str | None) -> date | None:
    """Best-effort parse of an ISO date/datetime string's date part."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


async def _project_id_for_look_ahead(session: AsyncSession, look_ahead_id: uuid.UUID) -> uuid.UUID | None:
    """Resolve the owning project of a look-ahead via its master schedule.

    Returns ``None`` when the look-ahead does not exist. Used for the IDOR
    check: the caller's ``project_id`` must match this, else the look-ahead is
    treated as not found (never confirm a foreign id's existence).
    """
    stmt = (
        select(MasterSchedule.project_id)
        .join(LookAheadPlan, LookAheadPlan.master_schedule_id == MasterSchedule.id)
        .where(LookAheadPlan.id == look_ahead_id)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def _resolve_float(session: AsyncSession, task_ref: uuid.UUID) -> tuple[int | None, bool, date | None]:
    """Best-effort CPM enrichment for a constraint's ``task_ref``.

    Returns ``(total_float, is_critical, need_by_date)``. The ``task_ref ↔
    schedule-activity`` join is intentionally best-effort for the MVP: we look
    the activity up by id (some deployments carry the schedule-activity id as the
    task ref). When unresolved, float is ``None`` and confidence degrades — never
    silently assumed pristine (spec P5). This is the single swap-point when a
    richer task↔activity mapping lands.
    """
    activity = await session.get(Activity, task_ref)
    if activity is None:
        return None, False, None
    return activity.total_float, bool(activity.is_critical), _parse_iso_date(activity.start_date)


async def _build_activity_inputs(
    session: AsyncSession,
    project_id: uuid.UUID,
    constraints: list[Constraint],
    readiness_repo: ReadinessResultRepository,
) -> list[ActivityInput]:
    """Group raw constraints by ``task_ref`` and enrich each activity.

    One :class:`ActivityInput` per distinct task, carrying its raw constraints,
    best-effort CPM float/need-by, and the prior snapshot's float (for burn).
    """
    by_task: dict[str, list[Constraint]] = {}
    for c in constraints:
        by_task.setdefault(str(c.task_ref), []).append(c)

    inputs: list[ActivityInput] = []
    for task_key, task_constraints in by_task.items():
        task_ref = task_constraints[0].task_ref
        total_float, is_critical, need_by = await _resolve_float(session, task_ref)
        prior = await readiness_repo.get_prior_by_activity(project_id, task_key)
        inputs.append(
            ActivityInput(
                task_ref=task_key,
                constraints=tuple(
                    ConstraintInput(
                        ref=c.id,
                        status=c.status,
                        target_clear_date=c.target_clear_date,
                        constraint_type=c.constraint_type,
                        description=c.description,
                    )
                    for c in task_constraints
                ),
                need_by_date=need_by,
                planned_start_date=need_by,
                total_float=total_float,
                is_critical=is_critical,
                prior_float=prior.total_float_days if prior is not None else None,
            )
        )
    return inputs


async def evaluate_readiness(
    session: AsyncSession,
    project_id: uuid.UUID,
    look_ahead_id: uuid.UUID,
    *,
    today: date | None = None,
) -> tuple[str, list[ReadinessResult]]:
    """Evaluate & snapshot readiness for every activity in a look-ahead.

    Derives the look-ahead's project for the IDOR check (a look-ahead in another
    project is a 404). Pulls raw constraints from ``schedule_advanced``, resolves
    best-effort CPM float, runs the pure engine under the project's confidence
    policy, and persists one snapshot *run* stamped with a deterministic
    ``evaluation_run_id``. Re-running identical inputs is idempotent: the
    existing run is returned unchanged (E1.1-AC6).

    Returns ``(evaluation_run_id, rows)``.
    """
    owning_project = await _project_id_for_look_ahead(session, look_ahead_id)
    if owning_project is None or owning_project != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Look-ahead not found")

    today = today or _utcnow().date()
    constraint_repo = ConstraintRepository(session)
    readiness_repo = ReadinessResultRepository(session)

    constraints = await constraint_repo.list_for_look_ahead(look_ahead_id)
    activities = await _build_activity_inputs(session, project_id, constraints, readiness_repo)

    run_id = run_digest(activities, today)

    # Idempotent re-run: an identical-input run already persisted → return it.
    existing = await readiness_repo.list_by_run(project_id, run_id)
    if existing:
        return run_id, existing

    policy, _source = await resolve_policy(session, project_id)
    verdicts = evaluate_look_ahead(activities, today, policy=policy)

    look_ahead_ref = str(look_ahead_id)
    rows = [
        ReadinessResult(
            project_id=project_id,
            activity_ref=v.task_ref,
            look_ahead_ref=look_ahead_ref,
            classification=v.classification.value,
            binding_constraint_ref=v.binding_constraint_ref,
            need_by_date=_as_utc_datetime(v.need_by_date),
            planned_start_date=_as_utc_datetime(v.planned_start_date),
            total_float_days=v.total_float_days,
            float_burn_days=v.float_burn_days,
            drivers=v.drivers,
            confidence_score=Decimal(str(v.confidence.score)),
            confidence_band=v.confidence.band.value,
            confidence_rationale=v.confidence.rationale,
            evaluation_run_id=run_id,
        )
        for v in verdicts
    ]
    rows = await readiness_repo.bulk_add(rows)

    counts = {"ready": 0, "at_risk": 0, "blocked": 0}
    for v in verdicts:
        counts[v.classification.value] = counts.get(v.classification.value, 0) + 1
    _publish(
        "schedule_intelligence.readiness.evaluated",
        {
            "project_id": str(project_id),
            "look_ahead_id": look_ahead_ref,
            "evaluation_run_id": run_id,
            "activity_count": len(rows),
        },
    )
    return run_id, rows


async def list_readiness(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    look_ahead_id: uuid.UUID | None = None,
) -> tuple[str | None, list[ReadinessResult]]:
    """Return the latest readiness run for a project (optionally one look-ahead).

    Returns ``(evaluation_run_id, rows)`` — ``(None, [])`` when nothing has been
    evaluated yet.
    """
    repo = ReadinessResultRepository(session)
    look_ahead_ref = str(look_ahead_id) if look_ahead_id is not None else None
    run_id = await repo.latest_run_id(project_id, look_ahead_ref=look_ahead_ref)
    if run_id is None:
        return None, []
    rows = await repo.list_by_run(project_id, run_id)
    return run_id, rows


def _as_utc_datetime(value: date | None) -> datetime | None:
    """Store a plain date as a midnight-UTC datetime (the column is tz-aware)."""
    if value is None:
        return None
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _publish(topic: str, data: dict[str, str | int]) -> None:
    """Best-effort event publish — a bus hiccup must not fail the request."""
    try:
        event_bus.publish_detached(topic, data, source_module="oe_schedule_intelligence")
    except Exception:  # noqa: BLE001 — event bus is best-effort
        pass
