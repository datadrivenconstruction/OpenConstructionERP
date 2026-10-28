# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ESG Site Performance service - business logic.

Stateless service layer. Handles:
- listing the code-defined metric catalogue;
- CRUD for period readings, with first-class validation (metric key in the
  catalogue; value / target >= 0; percentage metrics in 0..100) enforced up
  front so the caller gets a clear 400;
- a per-metric summary (latest reading, target, direction-aware "on track"
  flag and a short trend) grouped by ESG pillar.
"""

import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.json_merge import merge_metadata
from app.modules.esg import guard
from app.modules.esg.catalogue import (
    CATEGORY_ORDER,
    METRIC_DEFINITIONS,
    MetricDirection,
)
from app.modules.esg.models import EsgEntry
from app.modules.esg.repository import EsgEntryRepository
from app.modules.esg.schemas import (
    EsgEntryCreate,
    EsgEntryUpdate,
    EsgMetricSummary,
    EsgSummaryResponse,
    EsgTrendPoint,
    MetricDefinitionResponse,
)

logger = logging.getLogger(__name__)

# Default number of trailing periods shown in a metric's trend.
DEFAULT_TREND_PERIODS = 6


def _evaluate_against_target(
    direction: MetricDirection,
    value: Decimal | None,
    target: Decimal | None,
) -> tuple[bool | None, float | None]:
    """Compare a latest reading with its target using the metric's direction.

    Returns ``(on_track, delta_pct)``:

    * ``on_track`` - ``True`` when the reading meets the target given the
      direction (``<=`` for lower-is-better, ``>=`` for higher-is-better);
      ``None`` when there is no reading or no target.
    * ``delta_pct`` - the signed percentage difference of the reading from the
      target; ``None`` when it cannot be computed (no reading/target, or a zero
      target). Never NaN or infinity.
    """
    if value is None or target is None:
        return None, None

    if direction == MetricDirection.HIGHER_BETTER:
        on_track = value >= target
    else:
        on_track = value <= target

    delta_pct: float | None = None
    if target != 0:
        delta_pct = float(round((value - target) / target * Decimal(100), 2))

    return on_track, delta_pct


class EsgService:
    """Business logic for ESG Site Performance operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EsgEntryRepository(session)

    # ── Catalogue ─────────────────────────────────────────────────────────────

    @staticmethod
    def list_metric_definitions() -> list[MetricDefinitionResponse]:
        """Return the fixed catalogue of ESG metric definitions."""
        return [
            MetricDefinitionResponse(
                key=definition.key,
                category=definition.category.value,
                label=definition.label,
                unit=definition.unit,
                direction=definition.direction.value,
                description=definition.description,
            )
            for definition in METRIC_DEFINITIONS
        ]

    # ── Entry CRUD ────────────────────────────────────────────────────────────

    async def create_entry(self, data: EsgEntryCreate, user_id: str | None = None) -> EsgEntry:
        """Create a new ESG reading.

        Validates the metric key and the value/target ranges (400 on failure)
        and enforces one reading per (project, metric, period) (409 on a
        duplicate).
        """
        try:
            metric_key = guard.validate_entry(data.metric_key, data.value, data.target)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        existing = await self.repo.get_by_project_metric_period(
            data.project_id,
            metric_key,
            data.period,
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"A reading for '{metric_key}' in period {data.period} already exists "
                    "for this project. Edit the existing entry instead."
                ),
            )

        entry = EsgEntry(
            project_id=data.project_id,
            metric_key=metric_key,
            period=data.period,
            value=data.value,
            target=data.target,
            note=data.note,
            created_by=user_id,
            metadata_=data.metadata,
        )
        entry = await self.repo.create(entry)
        logger.info(
            "ESG entry created: %s %s=%s (project %s)",
            metric_key,
            data.period,
            data.value,
            data.project_id,
        )

        event_bus.publish_detached(
            "esg.entry.recorded",
            data={
                "project_id": str(data.project_id),
                "entry_id": str(entry.id),
                "metric_key": metric_key,
                "period": data.period,
                "value": str(data.value),
                "user_id": user_id,
            },
            source_module="esg",
        )
        return entry

    async def get_entry(self, entry_id: uuid.UUID) -> EsgEntry:
        """Get an entry by ID. Raises 404 if not found."""
        entry = await self.repo.get_by_id(entry_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ESG entry not found",
            )
        return entry

    async def list_entries(
        self,
        project_id: uuid.UUID,
        *,
        metric_key: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[EsgEntry], int]:
        """List readings for a project, optionally filtered to one metric."""
        return await self.repo.list_for_project(
            project_id,
            metric_key=metric_key,
            offset=offset,
            limit=limit,
        )

    async def update_entry(self, entry_id: uuid.UUID, data: EsgEntryUpdate) -> EsgEntry:
        """Update a reading's value / target / note.

        Re-validates the value and target ranges against the entry's metric so a
        percentage can never be pushed out of 0..100, nor a value below zero.
        """
        entry = await self.get_entry(entry_id)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(entry, "metadata_", None), incoming) if isinstance(incoming, dict) else incoming
            )

        if not fields:
            return entry

        try:
            if "value" in fields:
                if fields["value"] is None:
                    raise ValueError("value cannot be set to null; provide a number >= 0.")
                guard.validate_reading(entry.metric_key, "value", fields["value"])
            if fields.get("target") is not None:
                guard.validate_reading(entry.metric_key, "target", fields["target"])
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        await self.repo.update_fields(entry_id, **fields)
        await self.session.refresh(entry)
        logger.info("ESG entry updated: %s (fields=%s)", entry_id, list(fields.keys()))
        return entry

    async def delete_entry(self, entry_id: uuid.UUID) -> None:
        """Delete a reading. Raises 404 if it does not exist."""
        entry = await self.get_entry(entry_id)
        await self.repo.delete(entry_id)
        logger.info("ESG entry deleted: %s (%s %s)", entry_id, entry.metric_key, entry.period)
        event_bus.publish_detached(
            "esg.entry.deleted",
            data={
                "project_id": str(entry.project_id),
                "entry_id": str(entry_id),
                "metric_key": entry.metric_key,
                "period": entry.period,
            },
            source_module="esg",
        )

    # ── Summary ───────────────────────────────────────────────────────────────

    async def get_summary(
        self,
        project_id: uuid.UUID,
        *,
        trend_periods: int = DEFAULT_TREND_PERIODS,
    ) -> EsgSummaryResponse:
        """Build the project ESG dashboard: every metric with its KPI and trend.

        Every catalogue metric is included (with an empty trend when it has no
        readings) and grouped by pillar, so the dashboard renders a complete,
        stable set of cards. For each metric the latest reading, its target, a
        direction-aware ``on_track`` flag and the trailing ``trend_periods`` of
        history are returned.
        """
        entries = await self.repo.list_all_for_project(project_id)

        # Group readings by metric, keeping the ascending-period order the
        # repository query already imposes (last item per metric is the latest).
        by_metric: dict[str, list[EsgEntry]] = {}
        for entry in entries:
            by_metric.setdefault(entry.metric_key, []).append(entry)

        grouped: dict[str, list[EsgMetricSummary]] = {value: [] for value in CATEGORY_ORDER}
        latest_period_overall: str | None = None

        for definition in METRIC_DEFINITIONS:
            metric_entries = by_metric.get(definition.key, [])
            trailing = metric_entries[-trend_periods:] if trend_periods > 0 else metric_entries
            trend = [EsgTrendPoint(period=e.period, value=e.value) for e in trailing]

            latest = metric_entries[-1] if metric_entries else None
            latest_value = latest.value if latest is not None else None
            latest_period = latest.period if latest is not None else None
            target = latest.target if latest is not None else None
            on_track, delta_pct = _evaluate_against_target(
                definition.direction,
                latest_value,
                target,
            )

            grouped[definition.category.value].append(
                EsgMetricSummary(
                    metric_key=definition.key,
                    category=definition.category.value,
                    label=definition.label,
                    unit=definition.unit,
                    direction=definition.direction.value,
                    latest_period=latest_period,
                    latest_value=latest_value,
                    target=target,
                    on_track=on_track,
                    delta_pct=delta_pct,
                    entry_count=len(metric_entries),
                    trend=trend,
                ),
            )

            if latest_period is not None and (latest_period_overall is None or latest_period > latest_period_overall):
                latest_period_overall = latest_period

        return EsgSummaryResponse(
            project_id=project_id,
            trend_periods=trend_periods,
            latest_period=latest_period_overall,
            by_category=grouped,
        )
