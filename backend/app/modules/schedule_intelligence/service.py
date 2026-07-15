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
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
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
from app.modules.schedule_intelligence.models import ConfidenceConfig, LockedFigure
from app.modules.schedule_intelligence.repository import (
    ConfidenceConfigRepository,
    LockedFigureRepository,
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


def _publish(topic: str, data: dict[str, str | int]) -> None:
    """Best-effort event publish — a bus hiccup must not fail the request."""
    try:
        event_bus.publish_detached(topic, data, source_module="oe_schedule_intelligence")
    except Exception:  # noqa: BLE001 — event bus is best-effort
        pass
