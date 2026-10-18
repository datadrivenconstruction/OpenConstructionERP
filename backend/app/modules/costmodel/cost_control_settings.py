# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read a project's forecast settings and the methods its lines were set to.

A project with no settings row reads the defaults, and a line with no choice
follows the project. Kept apart from the services so the report and the
forecast documentation read the same values the same way.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.cost_control import FORECAST_METHODS, METHOD_BEST_AVAILABLE
from app.modules.costmodel.forecast_docs import DEFAULT_THRESHOLD_PCT, EvidenceThreshold, money
from app.modules.costmodel.models import CostControlSettings, CostForecastMethodChoice


@dataclass(frozen=True, slots=True)
class ForecastSettings:
    """A project's forecast method and evidence threshold, defaults filled in."""

    project_id: uuid.UUID
    forecast_method: str = METHOD_BEST_AVAILABLE
    threshold_amount: Decimal = Decimal("0")
    threshold_pct: Decimal | None = DEFAULT_THRESHOLD_PCT
    is_default: bool = True
    updated_by: str | None = None
    updated_at: datetime | None = None

    @property
    def threshold(self) -> EvidenceThreshold:
        return EvidenceThreshold(self.threshold_amount, self.threshold_pct)

    def meta(self) -> dict[str, str]:
        """The values a snapshot keeps, as strings, so its documentation reads the rules it was taken under."""
        return {
            "forecast_method": self.forecast_method,
            "threshold_amount": str(self.threshold_amount),
            "threshold_pct": "" if self.threshold_pct is None else str(self.threshold_pct),
        }


def settings_from_meta(project_id: uuid.UUID, meta: object) -> ForecastSettings:
    """The settings a snapshot was taken under; the defaults for a snapshot older than settings."""
    if not isinstance(meta, dict) or not meta:
        return ForecastSettings(project_id)
    method = str(meta.get("forecast_method") or METHOD_BEST_AVAILABLE)
    raw_pct = meta.get("threshold_pct", str(DEFAULT_THRESHOLD_PCT))
    return ForecastSettings(
        project_id=project_id,
        forecast_method=method if method in FORECAST_METHODS else METHOD_BEST_AVAILABLE,
        threshold_amount=money(meta.get("threshold_amount")),
        threshold_pct=None if raw_pct in (None, "") else money(raw_pct),
        is_default=False,
    )


async def settings_row(session: AsyncSession, project_id: uuid.UUID) -> CostControlSettings | None:
    stmt = select(CostControlSettings).where(CostControlSettings.project_id == project_id)
    return (await session.execute(stmt)).scalars().first()


async def load_settings(session: AsyncSession, project_id: uuid.UUID) -> ForecastSettings:
    """The project's settings, or the defaults when it never stored any."""
    row = await settings_row(session, project_id)
    if row is None:
        return ForecastSettings(project_id)
    method = row.forecast_method if row.forecast_method in FORECAST_METHODS else METHOD_BEST_AVAILABLE
    return ForecastSettings(
        project_id=project_id,
        forecast_method=method,
        threshold_amount=money(row.evidence_threshold_amount),
        threshold_pct=None if row.evidence_threshold_pct is None else money(row.evidence_threshold_pct),
        is_default=False,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


async def load_choices(session: AsyncSession, project_id: uuid.UUID) -> dict[str, CostForecastMethodChoice]:
    """The method each line was set to, by cost line id."""
    stmt = select(CostForecastMethodChoice).where(CostForecastMethodChoice.project_id == project_id)
    return {str(row.cost_line_id): row for row in (await session.execute(stmt)).scalars().all()}
