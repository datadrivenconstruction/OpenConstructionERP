"""Full EVM data access layer.

All database queries for EVM forecast entities live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.full_evm.models import EVMForecast


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

    async def create(self, forecast: EVMForecast) -> EVMForecast:
        """Insert a new EVM forecast."""
        self.session.add(forecast)
        await self.session.flush()
        return forecast
