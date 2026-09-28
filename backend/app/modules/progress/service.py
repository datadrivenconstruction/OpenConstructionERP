# OpenConstructionERP - DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""Progress tracking service - business logic.

Handles:
- Percent-complete recording (append-only entries)
- percent_complete range enforcement [0, 100]
- Per-period delta calculation from the cumulative series
- S-curve: actual vs planned per period
- Geo-tagging validation (lat ∈ [-90, 90], lon ∈ [-180, 180])

Latest wins
───────────
Progress entries are append-only: a mistake is corrected by recording a new
entry. So wherever several readings compete - two readings for one position
inside one period, or a position's whole history - the LATEST one is the
answer, never the largest. A foreman who corrects 90 % down to 30 % sees
30 %, and ``/progress`` reports the same number ``/contracts`` bills against.
The ordering and its tiebreakers live in
:func:`app.modules.progress.repository._latest_first`.

Rollups
───────
:func:`weighted_rollup` is the module's only rollup implementation. Both
callers hand it a quantity-weighted denominator over LEAF positions, and
both keep unmeasured leaves in that denominator at 0 %.

* Project headline (:meth:`ProgressService._project_pct_by_period`) rolls
  up every leaf BOQ position in the project, so one line item at 90 % cannot
  speak for a four-hundred-line project.
* Parent drill-down (:meth:`ProgressService.get_position_summary`) rolls up
  every leaf descendant of the parent, so ten children with one at 100 %
  report about 10 %, not 100 %.

Leaves only, in both cases: readings live on leaves, so weighting an
intermediate node would charge its full quantity against a reading it can
never have.

Both degrade to the unweighted mean over the same id set when the BOQ
carries no quantities.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress.models import ProgressEntry
from app.modules.progress.quantity_variance import (
    PositionQuantityInput,
    QuantityVarianceReport,
    build_report,
    to_decimal,
)
from app.modules.progress.repository import ProgressRepository
from app.modules.progress.schemas import (
    CumulativeProgressResponse,
    PeriodProgress,
    PositionProgressSummary,
    PositionQuantityVarianceItem,
    ProgressEntryCreate,
    ProgressPlanCreate,
    QuantityVarianceResponse,
    QuantityVarianceRollupResponse,
    SCurvePoint,
    SCurveResponse,
)

logger = logging.getLogger(__name__)


def _validate_geo(lat: float | None, lon: float | None) -> None:
    """Raise 422 if lat/lon are out of WGS84 range (belt+braces on top of Pydantic)."""
    if lat is not None and not (-90.0 <= lat <= 90.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"geo_lat {lat} is outside [-90, 90]",
        )
    if lon is not None and not (-180.0 <= lon <= 180.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"geo_lon {lon} is outside [-180, 180]",
        )


def weighted_rollup(
    pct_by_id: Mapping[uuid.UUID, float],
    weight_by_id: Mapping[uuid.UUID, Decimal],
) -> float | None:
    """Roll percent-complete readings up to a quantity-weighted average.

    This is the single rollup implementation in the module. Both the BOQ
    parent summary and the project headline call it; they differ only in
    which ids they hand over, never in the arithmetic.

    Contract, and the whole point of the function:

    * ``weight_by_id`` **is** the denominator. Every id in it is rolled up.
    * An id absent from ``pct_by_id`` contributes 0 to the numerator while
      still contributing its full weight to the denominator - unmeasured
      work is not evidence of completed work.
    * When every weight is zero the result degrades to the unweighted mean
      over the same id set, so a rollup still reports something when the
      BOQ carries no quantities.

    Args:
        pct_by_id: Latest percent-complete [0, 100] per position id. Ids not
            present in ``weight_by_id`` are ignored - the caller decides the
            denominator, this function does not widen it.
        weight_by_id: Design quantity per position id, the rollup weight.

    Returns:
        The rolled-up percentage rounded to 3 decimals, or None when
        ``weight_by_id`` is empty (nothing to roll up).
    """
    if not weight_by_id:
        return None

    weighted_sum = Decimal("0")
    weight_total = Decimal("0")
    for pos_id, weight in weight_by_id.items():
        weighted_sum += weight * Decimal(str(pct_by_id.get(pos_id, 0.0)))
        weight_total += weight

    if weight_total > 0:
        return round(float(weighted_sum / weight_total), 3)

    # No quantities anywhere: fall back to the unweighted mean over the same
    # denominator, so an unmeasured id still counts as 0 rather than vanishing.
    plain_sum = sum(pct_by_id.get(pos_id, 0.0) for pos_id in weight_by_id)
    return round(plain_sum / len(weight_by_id), 3)


def _compute_deltas(
    period_rows: list[tuple[str, float]],
    entry_counts: Mapping[str, int] | None = None,
) -> list[PeriodProgress]:
    """Convert (period_label, cumulative_pct) rows into PeriodProgress with deltas.

    ``cumulative_pct`` is the completion percentage at the end of that period.

    delta_pct = cumulative_pct[i] - cumulative_pct[i-1]

    Deltas may be NEGATIVE. Under the old "highest reading in the window"
    rule a downward move was an anomaly worth flattening to 0. Under
    latest-wins a correction downward is the intended case, so clamping made
    the column contradict the cumulative figure beside it: a foreman who
    corrects 90 % to 30 % saw the cumulative fall by 60 while the delta read
    0, which reads as a broken page rather than as a deliberate floor.

    Args:
        period_rows: ``(period_label, cumulative_pct)`` sorted by period.
        entry_counts: ``{period_label: entries recorded}``. A period missing
            from the mapping reports 0 entries.

    Returns:
        One :class:`PeriodProgress` per input row, in the same order.
    """
    counts = entry_counts or {}
    results: list[PeriodProgress] = []
    prev_cumulative = 0.0
    for label, cum_pct in period_rows:
        delta = round(cum_pct - prev_cumulative, 3)
        results.append(
            PeriodProgress(
                period_label=label,
                delta_pct=delta,
                cumulative_pct=round(cum_pct, 3),
                entry_count=counts.get(label, 0),
            )
        )
        prev_cumulative = cum_pct
    return results


def _variance_report_to_response(
    project_id: uuid.UUID,
    report: QuantityVarianceReport,
) -> QuantityVarianceResponse:
    """Map the pure-helper dataclasses to the Pydantic response (Decimal -> str)."""
    positions = [
        PositionQuantityVarianceItem(
            boq_position_id=uuid.UUID(row.boq_position_id),
            ordinal=row.ordinal,
            description=row.description,
            unit=row.unit,
            design_quantity=str(row.design_quantity),
            earned_quantity=str(row.earned_quantity),
            percent_complete=str(row.percent_complete),
            variance=str(row.variance),
            variance_percent=(None if row.variance_percent is None else str(row.variance_percent)),
            status=row.status,
            is_over_run=row.is_over_run,
            is_under_run=row.is_under_run,
        )
        for row in report.positions
    ]
    rollup = report.rollup
    return QuantityVarianceResponse(
        project_id=project_id,
        positions=positions,
        rollup=QuantityVarianceRollupResponse(
            position_count=rollup.position_count,
            over_run_count=rollup.over_run_count,
            under_run_count=rollup.under_run_count,
            on_target_count=rollup.on_target_count,
            design_quantity_total=str(rollup.design_quantity_total),
            earned_quantity_total=str(rollup.earned_quantity_total),
            variance_total=str(rollup.variance_total),
            variance_percent=(None if rollup.variance_percent is None else str(rollup.variance_percent)),
        ),
    )


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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
            # The earned-value write flushes without committing; refresh the
            # just-created entry so the response carries the values that write
            # settled on without a lazy load, which raises MissingGreenlet.
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
        1. Build the cumulative series. For ONE position that is its own
           readings per period; for the PROJECT it is the quantity-weighted
           rollup of the positions (see :meth:`_project_pct_by_period`).
        2. Compute delta_pct = cum_pct[i] - cum_pct[i-1], which may be negative
           when a correction lowered the reading.
        3. The last entry's cumulative_pct is the current overall completion.

        Args:
            project_id: Project to summarise.
            boq_position_id: Restrict to a single position's own series.

        Returns:
            Per-period rows plus the project's (or position's) current
            cumulative percentage.
        """
        entry_counts = await self.repo.entry_counts_by_period(project_id, boq_position_id=boq_position_id)
        if boq_position_id is not None:
            period_rows = await self.repo.pct_by_period_for_position(project_id, boq_position_id)
        else:
            period_rows = await self._project_pct_by_period(project_id)
        periods = _compute_deltas(period_rows, entry_counts)
        current = periods[-1].cumulative_pct if periods else 0.0
        return CumulativeProgressResponse(
            project_id=project_id,
            boq_position_id=boq_position_id,
            periods=periods,
            current_cumulative_pct=current,
        )

    # ── Project rollup ────────────────────────────────────────────────────

    async def _project_pct_by_period(self, project_id: uuid.UUID) -> list[tuple[str, float]]:
        """Return the project's cumulative completion per period.

        The project percentage is the QUANTITY-WEIGHTED rollup of the latest
        per-position reading as of the end of each period, weighted by the
        BOQ design quantity of every leaf position in the project.

        Untracked positions count as 0 and stay in the denominator. That is
        the only reading of "percent complete" a client-facing report can
        defend: excluding them would let one measured line out of four
        hundred present itself as the whole project, which is the defect
        this method exists to remove.

        Falls back to the project-level manual readings
        (``boq_position_id IS NULL``) when there is no usable weighted
        denominator - no position readings at all, no readable BOQ, or
        readings that no longer match any position in the project's BOQs.

        Args:
            project_id: Project to roll up.

        Returns:
            ``(period_label, cumulative_pct)`` sorted by period label.
        """
        position_rows = await self.repo.position_pct_by_period(project_id)
        if not position_rows:
            return await self.repo.project_level_pct_by_period(project_id)

        weights = await self._fetch_position_weights(project_id)
        if weights is None:
            # The BOQ read failed. Rolling up against the measured positions
            # alone would silently restore the optimistic number, so use the
            # documented fallback series instead.
            logger.warning(
                "Project %s: BOQ positions unreadable - project progress falls back to "
                "project-level entries instead of the position rollup",
                project_id,
            )
            return await self.repo.project_level_pct_by_period(project_id)

        measured_ids = {pos_id for _label, pos_id, _pct in position_rows}
        orphan_ids = measured_ids - set(weights)
        if orphan_ids:
            logger.warning(
                "Project %s: %d progress position(s) are not in the project's BOQs and are excluded from the rollup",
                project_id,
                len(orphan_ids),
            )
        if not measured_ids - orphan_ids:
            # Readings exist but none of them lands on a live BOQ position,
            # so there is nothing to weight.
            return await self.repo.project_level_pct_by_period(project_id)

        # Group readings per period, then walk periods oldest-first carrying
        # each position's last known reading forward: a position measured in
        # W21 and not touched in W22 still counts in W22.
        readings_by_period: dict[str, dict[uuid.UUID, float]] = {}
        for label, pos_id, pct in position_rows:
            if pos_id in orphan_ids:
                continue
            readings_by_period.setdefault(label, {})[pos_id] = pct

        # The axis is every period the project has an observation in, NOT just
        # the periods that contribute to the rollup. A period holding only a
        # project-level reading, or only readings against positions outside
        # the BOQ, still happened: it keeps its row and its entry count, and
        # reports the rollup carried forward from the last measured period.
        # Dropping it would silently delete a week the user recorded work in.
        series: list[tuple[str, float]] = []
        carried: dict[uuid.UUID, float] = {}
        for label in await self.repo.period_labels(project_id):
            carried.update(readings_by_period.get(label, {}))
            rolled = weighted_rollup(carried, weights)
            series.append((label, rolled if rolled is not None else 0.0))
        return series

    async def _fetch_position_weights(self, project_id: uuid.UUID) -> dict[uuid.UUID, Decimal] | None:
        """Return ``{leaf_position_id: design_quantity}`` for the project's BOQs.

        Only LEAF positions carry weight. A parent's quantity, where it has
        one, restates work already counted in its children, so weighting
        both would count that work twice.

        ``Position.quantity`` is stored as a String; an unparseable, missing
        or non-finite value becomes ``Decimal("0")`` (no weight) rather than
        poisoning the whole rollup.

        Args:
            project_id: Project whose BOQ positions are wanted.

        Returns:
            Leaf position ids mapped to their design quantity, or None when
            the lookup itself failed - the caller must not treat that as
            "the project has no positions".
        """
        try:
            from sqlalchemy import select as sa_select

            from app.modules.boq.models import BOQ, Position

            stmt = (
                sa_select(Position.id, Position.parent_id, Position.quantity)
                .join(BOQ, Position.boq_id == BOQ.id)
                .where(BOQ.project_id == project_id)
            )
            rows = (await self.session.execute(stmt)).all()
        except Exception:
            logger.debug("Could not read BOQ positions for project %s", project_id, exc_info=True)
            return None

        parent_ids = {parent_id for _pos_id, parent_id, _quantity in rows if parent_id is not None}
        weights: dict[uuid.UUID, Decimal] = {}
        for pos_id, _parent_id, quantity in rows:
            if pos_id in parent_ids:
                continue
            try:
                weight = Decimal(str(quantity)) if quantity is not None else Decimal("0")
            except (ArithmeticError, ValueError):
                weight = Decimal("0")
            weights[pos_id] = weight if weight.is_finite() else Decimal("0")
        return weights

    # ── Position summary (with parent rollup) ─────────────────────────────

    async def get_position_summary(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID,
    ) -> PositionProgressSummary:
        """Compute current progress for a BOQ position.

        Parent rollup: if this position has descendants in the BOQ
        hierarchy, ``current_pct`` is the **quantity-weighted average** of
        the latest percent_completes of its LEAF descendants, weighting each
        by its BOQ ``quantity``. A leaf nobody has measured counts as 0 and
        keeps its weight, so the number reports on the whole subtree rather
        than only the observed part of it. When the leaves carry no quantity
        (weights sum to zero) it falls back to the unweighted mean over the
        same leaves. The ``is_rollup`` flag signals a rolled-up value.
        """
        # Fetch leaf descendants (id -> quantity) from BOQ
        # (lazy import to avoid circular dep)
        child_quantities = await self._fetch_leaf_descendant_weights(project_id, boq_position_id)

        if child_quantities:
            # Parent rollup path
            child_ids = list(child_quantities)
            child_pcts = await self.repo.latest_pct_for_positions(project_id, child_ids)
            # Denominator: EVERY leaf beneath this parent, exactly as the
            # project headline does. A child nobody has measured counts as 0
            # and keeps its weight, so a parent with ten children and one of
            # them at 100 % reports about 10 %, not 100 %. See the module
            # docstring.
            rolled = weighted_rollup(child_pcts, child_quantities)
            current_pct = 0.0 if rolled is None else rolled

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

    async def _fetch_leaf_descendant_weights(
        self,
        project_id: uuid.UUID,
        parent_id: uuid.UUID,
    ) -> dict[uuid.UUID, Decimal]:
        """Return ``{leaf_descendant_id: quantity}`` beneath a BOQ parent.

        LEAF descendants, not direct children. Readings live on leaves, so an
        intermediate node carries a quantity but never a percentage of its
        own. Weighting direct children would hand an intermediate node its
        full weight against a 0 % reading and drag the parent's rollup toward
        zero even when every grandchild underneath it is finished. For a flat
        parent - one level of children, no grandchildren - this returns
        exactly the direct children, so the common case is unchanged.

        This mirrors the project headline, which is also leaf-only; see
        :meth:`_fetch_position_weights` and the module docstring.

        ``Position.quantity`` is stored as a String, so it is coerced to
        Decimal here; an unparseable, missing or non-finite value becomes
        ``Decimal("0")`` (i.e. it contributes no weight).
        """
        try:
            from sqlalchemy import select as sa_select

            from app.modules.boq.models import BOQ, Position

            # Every position in the project, so the subtree can be walked
            # without one query per level.
            stmt = (
                sa_select(Position.id, Position.parent_id, Position.quantity)
                .join(BOQ, Position.boq_id == BOQ.id)
                .where(BOQ.project_id == project_id)
            )
            rows = (await self.session.execute(stmt)).all()
        except Exception:
            logger.debug(
                "Could not fetch BOQ children for position %s - treating as leaf",
                parent_id,
            )
            return {}

        children_of: dict[uuid.UUID, list[uuid.UUID]] = {}
        quantity_of: dict[uuid.UUID, object] = {}
        for pos_id, pos_parent_id, quantity in rows:
            quantity_of[pos_id] = quantity
            if pos_parent_id is not None:
                children_of.setdefault(pos_parent_id, []).append(pos_id)

        weights: dict[uuid.UUID, Decimal] = {}
        stack = list(children_of.get(parent_id, []))
        seen: set[uuid.UUID] = set()
        while stack:
            node = stack.pop()
            if node in seen:  # a malformed cycle must not hang the request
                continue
            seen.add(node)
            grandchildren = children_of.get(node)
            if grandchildren:
                stack.extend(grandchildren)
                continue
            quantity = quantity_of.get(node)
            try:
                weight = Decimal(str(quantity)) if quantity is not None else Decimal("0")
            except (ArithmeticError, ValueError):
                weight = Decimal("0")
            weights[node] = weight if weight.is_finite() else Decimal("0")
        return weights

    # --- Quantity variance (design vs earned quantity) --------------------

    async def get_quantity_variance(self, project_id: uuid.UUID) -> QuantityVarianceResponse:
        """Build the design-vs-earned quantity variance report for a project.

        For every BOQ position that has at least one recorded progress
        observation, the earned (installed-to-date) quantity is derived from
        the position's latest percent-complete and its design quantity
        (``earned = design * percent / 100``) and compared against the design
        quantity. Positions never measured are omitted so the report reflects
        work actually observed on site. Results roll up to project counts and
        totals. All quantities stay Decimal and are serialised as strings.
        """
        positions_meta = await self._fetch_project_positions(project_id)
        if not positions_meta:
            return QuantityVarianceResponse(project_id=project_id)

        latest_pct = await self.repo.latest_pct_for_positions(project_id, list(positions_meta))
        inputs: list[PositionQuantityInput] = []
        for pos_id, pct in latest_pct.items():
            meta = positions_meta.get(pos_id)
            if meta is None:
                # Progress row references a position outside this project's BOQs.
                continue
            ordinal, description, unit, quantity = meta
            inputs.append(
                PositionQuantityInput(
                    boq_position_id=str(pos_id),
                    design_quantity=to_decimal(quantity),
                    percent_complete=to_decimal(pct),
                    ordinal=ordinal,
                    description=description,
                    unit=unit,
                )
            )

        report = build_report(inputs)
        return _variance_report_to_response(project_id, report)

    async def _fetch_project_positions(
        self,
        project_id: uuid.UUID,
    ) -> dict[uuid.UUID, tuple[str | None, str | None, str | None, str | None]]:
        """Return ``{position_id: (ordinal, description, unit, quantity)}`` for a project.

        Reads the BOQ positions belonging to the project's BOQs. ``quantity``
        is the stored design quantity (a string, coerced to Decimal by the
        caller). On any lookup failure an empty mapping is returned so the
        variance report degrades to empty rather than raising.
        """
        try:
            from sqlalchemy import select as sa_select

            from app.modules.boq.models import BOQ, Position

            stmt = (
                sa_select(
                    Position.id,
                    Position.ordinal,
                    Position.description,
                    Position.unit,
                    Position.quantity,
                )
                .join(BOQ, Position.boq_id == BOQ.id)
                .where(BOQ.project_id == project_id)
            )
            rows = (await self.session.execute(stmt)).all()
            result: dict[uuid.UUID, tuple[str | None, str | None, str | None, str | None]] = {}
            for pos_id, ordinal, description, unit, quantity in rows:
                result[pos_id] = (ordinal, description, unit, quantity)
            return result
        except Exception:
            logger.debug("Could not fetch BOQ positions for project %s", project_id)
            return {}

    # ── S-curve ───────────────────────────────────────────────────────────

    async def get_s_curve(self, project_id: uuid.UUID) -> SCurveResponse:
        """Build actual vs planned S-curve for a project.

        1. Fetch the actual per-period cumulative % - the same quantity-weighted
           project rollup the headline uses, so the curve and the headline can
           never disagree.
        2. Fetch planned data points.
        3. Merge on period_label; gaps in either series are filled with None
           (planned) or carry-forward (actual).

        Args:
            project_id: Project to chart.

        Returns:
            One point per period present in either series.
        """
        # Actual data
        actual_rows = await self._project_pct_by_period(project_id)
        actual_by_period: dict[str, float] = {label: round(pct, 3) for label, pct in actual_rows}

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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
