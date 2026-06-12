# OpenConstructionERP - DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""Progress tracking service - business logic.

Handles:
- Percent-complete recording (append-only entries)
- percent_complete range enforcement [0, 100]
- Per-period delta calculation from the cumulative series
- S-curve: actual vs planned per period
- Parent rollup: a BOQ parent's current_pct is the weighted average
  of its direct children's latest percent_completes
- Geo-tagging validation (lat ∈ [-90, 90], lon ∈ [-180, 180])
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress.models import ProgressEntry
from app.modules.progress.repository import ProgressRepository
from app.modules.progress.schemas import (
    CumulativeProgressResponse,
    PeriodProgress,
    PositionProgressSummary,
    ProgressEntryCreate,
    ProgressPlanCreate,
    SCurvePoint,
    SCurveResponse,
)

logger = logging.getLogger(__name__)


def _validate_geo(lat: float | None, lon: float | None) -> None:
    """Raise 422 if lat/lon are out of WGS84 range (belt+braces on top of Pydantic)."""
    if lat is not None and not (-90.0 <= lat <= 90.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"geo_lat {lat} is outside [-90, 90]",
        )
    if lon is not None and not (-180.0 <= lon <= 180.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"geo_lon {lon} is outside [-180, 180]",
        )


def _compute_deltas(period_rows: list[tuple[str, float]]) -> list[PeriodProgress]:
    """Convert (period_label, max_pct_in_period) rows into PeriodProgress with deltas.

    ``max_pct_in_period`` is treated as the *cumulative* percentage at the
    end of that period (i.e. the highest reading recorded during the period).

    delta_pct = cumulative_pct[i] - cumulative_pct[i-1]

    Deltas are clamped to 0 when cumulative_pct decreases (correction entries
    can lower the recorded value - we don't want negative deltas on the
    S-curve chart).
    """
    results: list[PeriodProgress] = []
    prev_cumulative = 0.0
    for label, cum_pct in period_rows:
        delta = max(0.0, round(cum_pct - prev_cumulative, 3))
        results.append(
            PeriodProgress(
                period_label=label,
                delta_pct=delta,
                cumulative_pct=round(cum_pct, 3),
                entry_count=1,  # aggregated at the repo level
            )
        )
        prev_cumulative = cum_pct
    return results


class ProgressService:
    """Business logic for progress tracking."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ProgressRepository(session)

    # ── Record progress ───────────────────────────────────────────────────

    async def record_entry(
        self,
        data: ProgressEntryCreate,
        *,
        user_id: str | None = None,
    ) -> ProgressEntry:
        """Append a new progress observation.

        Validates:
        - percent_complete in [0, 100] (Pydantic + service-layer double-check)
        - geo_lat/geo_lon within WGS84 bounds
        """
        # Double-check pct (Pydantic schema should have already caught it)
        if not (0.0 <= data.percent_complete <= 100.0):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"percent_complete {data.percent_complete} must be in [0, 100]",
            )

        # Geo validation
        _validate_geo(data.geo_lat, data.geo_lon)

        entry = ProgressEntry(
            project_id=data.project_id,
            boq_position_id=data.boq_position_id,
            period_label=data.period_label,
            percent_complete=data.percent_complete,
            notes=data.notes,
            recorded_by=user_id,
            geo_lat=data.geo_lat,
            geo_lon=data.geo_lon,
            photos=list(data.photos),
            metadata_=data.metadata,
        )
        entry = await self.repo.create_entry(entry)
        logger.info(
            "Progress recorded: position=%s period=%s pct=%.3f by=%s",
            data.boq_position_id,
            data.period_label,
            data.percent_complete,
            user_id,
        )

        # EVM bridge: the freshly recorded percent is the latest reading for
        # the position (entries are append-only, latest wins), so push it to
        # the costmodel budget line as earned value (BCWP) in the same
        # session / transaction. Skips silently when the position has no
        # budget line yet or the costmodel module is unavailable.
        if data.boq_position_id is not None:
            await self._sync_earned_value(
                data.project_id,
                data.boq_position_id,
                Decimal(str(data.percent_complete)),
            )
            # The earned-value write flushes and expire_all()s the session
            # (it does not commit), which still expires the just-created
            # entry; serializing the response would then lazy-load attributes
            # outside the async greenlet and crash. Refresh while we are
            # still inside the async context.
            await self.session.refresh(entry)
        return entry

    async def _sync_earned_value(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID,
        percent_complete: Decimal,
    ) -> None:
        """Push the latest progress percent to the costmodel budget line.

        Progress percent is EARNED VALUE (BCWP = position total x percent /
        100), not actual cost - actuals keep flowing from invoices. The
        write is synchronous on the same session so it commits (or rolls
        back) atomically with the progress entry. Re-recording progress
        overwrites the previous earned value (absolute set, never
        accumulated).

        Args:
            project_id: Project the entry belongs to.
            boq_position_id: Position the entry was recorded for.
            percent_complete: The just-recorded cumulative percent [0, 100].
        """
        try:
            from app.modules.costmodel.service import CostModelService
        except ImportError:
            logger.debug("costmodel module unavailable - earned value not synced")
            return

        line = await CostModelService(self.session).apply_progress_earned_value(
            project_id,
            boq_position_id,
            percent_complete,
        )
        if line is None:
            logger.debug(
                "Earned value skipped for position %s (no budget line yet)",
                boq_position_id,
            )

    # ── Get single entry ──────────────────────────────────────────────────

    async def get_entry(self, entry_id: uuid.UUID) -> ProgressEntry:
        entry = await self.repo.get_entry(entry_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Progress entry not found",
            )
        return entry

    # ── List entries ──────────────────────────────────────────────────────

    async def list_entries(
        self,
        project_id: uuid.UUID,
        *,
        boq_position_id: uuid.UUID | None = None,
        period_label: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ProgressEntry]:
        return await self.repo.list_entries_for_project(
            project_id,
            boq_position_id=boq_position_id,
            period_label=period_label,
            offset=offset,
            limit=limit,
        )

    # ── Cumulative progress breakdown ─────────────────────────────────────

    async def get_cumulative(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID | None = None,
    ) -> CumulativeProgressResponse:
        """Return per-period deltas and cumulative % for the project or a position.

        Algorithm
        ─────────
        1. Fetch (period_label, max_pct) pairs from the DB, sorted by period.
        2. Compute delta_pct = cum_pct[i] - cum_pct[i-1] (clamped to ≥ 0).
        3. The last entry's cumulative_pct is the current overall completion.
        """
        period_rows = await self.repo.entries_grouped_by_period(project_id, boq_position_id=boq_position_id)
        periods = _compute_deltas(period_rows)
        current = periods[-1].cumulative_pct if periods else 0.0
        return CumulativeProgressResponse(
            project_id=project_id,
            boq_position_id=boq_position_id,
            periods=periods,
            current_cumulative_pct=current,
        )

    # ── Position summary (with parent rollup) ─────────────────────────────

    async def get_position_summary(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID,
    ) -> PositionProgressSummary:
        """Compute current progress for a BOQ position.

        Parent rollup: if this position has child positions in the BOQ
        hierarchy, ``current_pct`` is the **unweighted average** of their
        latest percent_completes (weights would require BOQ quantity data
        which this module does not import to avoid circular dependency).
        The ``is_rollup`` flag signals this to the caller.
        """
        # Fetch child position IDs from BOQ (lazy import to avoid circular dep)
        child_ids = await self._fetch_child_ids(project_id, boq_position_id)

        if child_ids:
            # Parent rollup path
            child_pcts = await self.repo.latest_pct_for_positions(project_id, child_ids)
            if child_pcts:
                current_pct = round(sum(child_pcts.values()) / len(child_pcts), 3)
            else:
                current_pct = 0.0

            entries = await self.repo.list_entries_for_project(project_id, boq_position_id=boq_position_id, limit=1000)
            return PositionProgressSummary(
                boq_position_id=boq_position_id,
                current_pct=current_pct,
                entries_count=len(entries),
                last_recorded_at=entries[-1].recorded_at if entries else None,  # type: ignore[arg-type]
                last_period_label=entries[-1].period_label if entries else None,
                is_rollup=True,
            )

        # Leaf position path
        entries = await self.repo.list_entries_for_project(project_id, boq_position_id=boq_position_id, limit=1000)
        current_pct = float(entries[-1].percent_complete) if entries else 0.0
        return PositionProgressSummary(
            boq_position_id=boq_position_id,
            current_pct=current_pct,
            entries_count=len(entries),
            last_recorded_at=entries[-1].recorded_at if entries else None,  # type: ignore[arg-type]
            last_period_label=entries[-1].period_label if entries else None,
            is_rollup=False,
        )

    async def _fetch_child_ids(
        self,
        project_id: uuid.UUID,
        parent_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """Return direct child position IDs for the given parent in the BOQ."""
        try:
            from sqlalchemy import select as sa_select

            from app.modules.boq.models import Position

            stmt = sa_select(Position.id).where(
                Position.parent_id == parent_id,
            )
            rows = (await self.session.execute(stmt)).scalars().all()
            return list(rows)
        except Exception:
            logger.debug(
                "Could not fetch BOQ children for position %s - treating as leaf",
                parent_id,
            )
            return []

    # ── S-curve ───────────────────────────────────────────────────────────

    async def get_s_curve(self, project_id: uuid.UUID) -> SCurveResponse:
        """Build actual vs planned S-curve for a project.

        1. Fetch actual per-period cumulative % (max reading per period).
        2. Fetch planned data points.
        3. Merge on period_label; gaps in either series are filled with None
           (planned) or carry-forward (actual).
        """
        # Actual data
        actual_rows = await self.repo.entries_grouped_by_period(project_id)
        actual_by_period: dict[str, float] = {}
        prev = 0.0
        for label, max_pct in actual_rows:
            actual_by_period[label] = round(max_pct, 3)
            prev = max_pct

        # Planned data
        plan_rows = await self.repo.list_plan(project_id)
        planned_by_period: dict[str, float] = {p.period_label: round(float(p.planned_pct), 3) for p in plan_rows}

        # Union of all periods, sorted
        all_periods = sorted(set(actual_by_period) | set(planned_by_period))

        points: list[SCurvePoint] = []
        actual_cum = 0.0
        for period in all_periods:
            if period in actual_by_period:
                actual_cum = actual_by_period[period]
            points.append(
                SCurvePoint(
                    period_label=period,
                    actual_cumulative_pct=round(actual_cum, 3),
                    planned_cumulative_pct=planned_by_period.get(period),
                )
            )

        return SCurveResponse(project_id=project_id, points=points)

    # ── Plan management ───────────────────────────────────────────────────

    async def upsert_plan_point(self, data: ProgressPlanCreate) -> Any:
        """Create or update a planned S-curve point."""
        if not (0.0 <= data.planned_pct <= 100.0):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"planned_pct {data.planned_pct} must be in [0, 100]",
            )
        plan = await self.repo.upsert_plan(
            data.project_id,
            data.period_label,
            data.planned_pct,
            notes=data.notes,
        )
        return plan

    async def list_plan(self, project_id: uuid.UUID) -> list[Any]:
        return await self.repo.list_plan(project_id)
