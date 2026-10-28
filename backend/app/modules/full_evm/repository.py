# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Full EVM data access layer.

All database queries for EVM forecast, baseline and measurement entities live
here. No business logic - pure data access.

Loading strategy note: ``EVMBaseline.measures`` is declared ``raise_on_sql``
because a project accumulates measurements for its whole life. Any repository
method that returns a baseline whose measurements the caller will touch orders
them eagerly with an explicit ``selectinload``; every other read leaves them
unloaded and the relationship raises rather than firing a silent query from an
async context.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.full_evm.models import (
    EVMBaseline,
    EVMBaselinePeriod,
    EVMForecast,
    EVMMeasure,
)


class EVMForecastRepository:
    """Data access for EVMForecast model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, forecast_id: uuid.UUID) -> EVMForecast | None:
        """Get forecast by ID."""
        return await self.session.get(EVMForecast, forecast_id)

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EVMForecast], int]:
        """List forecasts with optional project filter."""
        base = select(EVMForecast)
        if project_id is not None:
            base = base.where(EVMForecast.project_id == project_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(EVMForecast.forecast_date.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_latest(self, project_id: uuid.UUID) -> EVMForecast | None:
        """Return the most recent forecast for a project, or None.

        Ordered by ``forecast_date`` (an ISO ``YYYY-MM-DD`` string, so
        lexical order == chronological order) then by ``created_at`` as a
        tie-break when several forecasts share the same date.
        """
        stmt = (
            select(EVMForecast)
            .where(EVMForecast.project_id == project_id)
            .order_by(EVMForecast.forecast_date.desc(), EVMForecast.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_active_alerts(self, project_id: uuid.UUID) -> list[EVMForecast]:  # noqa: A003
        """Return forecasts whose alert is still actionable for a project.

        "Active" means ``alert_status`` is ``triggered`` or ``snoozed`` -
        ``acknowledged`` rows are resolved and ``NULL`` rows never alerted.
        Snoozed rows are included so the UI can show a countdown; the
        router decides whether a snooze has lapsed.
        """
        stmt = (
            select(EVMForecast)
            .where(EVMForecast.project_id == project_id)
            .where(EVMForecast.alert_status.in_(("triggered", "snoozed")))
            .order_by(EVMForecast.triggered_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(self, forecast: EVMForecast) -> EVMForecast:
        """Insert a new EVM forecast."""
        self.session.add(forecast)
        await self.session.flush()
        return forecast


class EVMBaselineRepository:
    """Data access for :class:`EVMBaseline` and its planned-value curve."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, baseline_id: uuid.UUID) -> EVMBaseline | None:
        """Get a baseline with its periods, or ``None``.

        The periods come along automatically (``lazy="selectin"``): a baseline
        without its curve cannot answer any question about planned value.
        """
        return await self.session.get(EVMBaseline, baseline_id)

    async def get_with_measures(self, baseline_id: uuid.UUID) -> EVMBaseline | None:
        """Get a baseline with both its periods and every measurement loaded.

        The only read that eagerly loads the measurement history; used by the
        plan-versus-actual curve, which genuinely needs all of it.
        """
        stmt = select(EVMBaseline).where(EVMBaseline.id == baseline_id).options(selectinload(EVMBaseline.measures))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        project_id: uuid.UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EVMBaseline], int]:
        """List a project's baselines, newest first, with an optional status filter."""
        base = select(EVMBaseline).where(EVMBaseline.project_id == project_id)
        if status is not None:
            base = base.where(EVMBaseline.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(EVMBaseline.created_at.desc()).offset(offset).limit(limit)
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, total

    async def get_approved(self, project_id: uuid.UUID) -> EVMBaseline | None:
        """Return the project's currently approved baseline, or ``None``.

        At most one baseline per project is ``approved`` at a time; the service
        supersedes the previous one when a new baseline is approved.
        """
        stmt = (
            select(EVMBaseline)
            .where(EVMBaseline.project_id == project_id)
            .where(EVMBaseline.status == "approved")
            .order_by(EVMBaseline.approved_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def find_by_name(self, project_id: uuid.UUID, name: str) -> EVMBaseline | None:
        """Return the project's baseline with this exact name, or ``None``."""
        stmt = select(EVMBaseline).where(EVMBaseline.project_id == project_id).where(EVMBaseline.name == name).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, baseline: EVMBaseline) -> EVMBaseline:
        """Insert a new baseline and flush so its id is available."""
        self.session.add(baseline)
        await self.session.flush()
        return baseline

    async def delete(self, baseline: EVMBaseline) -> None:
        """Delete a baseline; periods and measurements cascade with it."""
        await self.session.delete(baseline)
        await self.session.flush()

    async def replace_periods(
        self,
        baseline_id: uuid.UUID,
        periods: list[EVMBaselinePeriod],
    ) -> list[EVMBaselinePeriod]:
        """Replace a baseline's whole curve in one write.

        Deletes the existing rows with a bulk statement rather than through the
        collection, so a caller that never loaded the curve does not have to.
        The new rows arrive already carrying their ``ordinal``.

        Args:
            baseline_id: Baseline whose curve is being replaced.
            periods: The new curve, in order.

        Returns:
            The inserted period rows.
        """
        await self.session.execute(
            delete(EVMBaselinePeriod).where(EVMBaselinePeriod.baseline_id == baseline_id),
        )
        for period in periods:
            period.baseline_id = baseline_id
            self.session.add(period)
        await self.session.flush()
        return periods

    async def list_periods(self, baseline_id: uuid.UUID) -> list[EVMBaselinePeriod]:
        """Return a baseline's curve in order, without loading the baseline."""
        stmt = (
            select(EVMBaselinePeriod)
            .where(EVMBaselinePeriod.baseline_id == baseline_id)
            .order_by(EVMBaselinePeriod.ordinal)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class EVMMeasureRepository:
    """Data access for :class:`EVMMeasure`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, measure_id: uuid.UUID) -> EVMMeasure | None:
        """Get a measurement by id."""
        return await self.session.get(EVMMeasure, measure_id)

    async def get_by_date(self, baseline_id: uuid.UUID, data_date: object) -> EVMMeasure | None:
        """Return the measurement for a baseline at an exact data date, or ``None``.

        Used to make recording idempotent: re-measuring the same cutoff updates
        the row in place rather than creating a second, contradictory truth for
        one date.
        """
        stmt = (
            select(EVMMeasure)
            .where(EVMMeasure.baseline_id == baseline_id)
            .where(EVMMeasure.data_date == data_date)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        baseline_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EVMMeasure], int]:
        """List measurements oldest first, filtered by baseline and/or project."""
        base = select(EVMMeasure)
        if baseline_id is not None:
            base = base.where(EVMMeasure.baseline_id == baseline_id)
        if project_id is not None:
            base = base.where(EVMMeasure.project_id == project_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(EVMMeasure.data_date.asc()).offset(offset).limit(limit)
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, total

    async def get_latest(self, baseline_id: uuid.UUID) -> EVMMeasure | None:
        """Return the most recent measurement for a baseline, or ``None``."""
        stmt = (
            select(EVMMeasure)
            .where(EVMMeasure.baseline_id == baseline_id)
            .order_by(EVMMeasure.data_date.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, measure: EVMMeasure) -> EVMMeasure:
        """Insert a new measurement and flush so its id is available."""
        self.session.add(measure)
        await self.session.flush()
        return measure

    async def delete(self, measure: EVMMeasure) -> None:
        """Delete a measurement."""
        await self.session.delete(measure)
        await self.session.flush()


__all__ = [
    "EVMBaselineRepository",
    "EVMForecastRepository",
    "EVMMeasureRepository",
]
