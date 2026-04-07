"""Full EVM service — advanced Earned Value Management with forecasting.

Stateless service layer.  Extends the basic EVM in the finance module
with ETC, EAC, VAC, TCPI calculations and S-curve data.
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.full_evm.models import EVMForecast
from app.modules.full_evm.repository import EVMForecastRepository
from app.modules.full_evm.schemas import EVMForecastCreate

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
QUANTIZE = Decimal("0.01")


def _dec(value: str) -> Decimal:
    """Safely convert string to Decimal."""
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return ZERO


class EVMService:
    """Business logic for advanced EVM forecasting."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.forecasts = EVMForecastRepository(session)

    async def list_forecasts(
        self,
        *,
        project_id: uuid.UUID | None = None,
    ) -> tuple[list[EVMForecast], int]:
        """List EVM forecasts for a project."""
        return await self.forecasts.list(project_id=project_id)

    async def create_forecast(self, data: EVMForecastCreate) -> EVMForecast:
        """Create an EVM forecast record manually."""
        forecast = EVMForecast(
            project_id=data.project_id,
            forecast_date=data.forecast_date,
            etc_=data.etc,
            eac=data.eac,
            vac=data.vac,
            tcpi=data.tcpi,
            forecast_method=data.forecast_method,
            confidence_range_low=data.confidence_range_low,
            confidence_range_high=data.confidence_range_high,
            notes=data.notes,
            metadata_=data.metadata,
        )
        forecast = await self.forecasts.create(forecast)
        logger.info("EVM forecast created: project=%s date=%s", data.project_id, data.forecast_date)
        return forecast

    async def calculate_forecast(
        self,
        project_id: uuid.UUID,
        forecast_method: str = "cpi",
    ) -> EVMForecast:
        """Calculate EVM forecast from latest finance EVM snapshot.

        Formulas:
            ETC (CPI method)     = (BAC - EV) / CPI
            ETC (SPI*CPI method) = (BAC - EV) / (SPI * CPI)
            EAC                  = AC + ETC
            VAC                  = BAC - EAC
            TCPI                 = (BAC - EV) / (BAC - AC)
        """
        # Get latest EVM snapshot from finance module
        from sqlalchemy import select

        from app.modules.finance.models import EVMSnapshot

        stmt = (
            select(EVMSnapshot)
            .where(EVMSnapshot.project_id == project_id)
            .order_by(EVMSnapshot.snapshot_date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        snapshot = result.scalar_one_or_none()

        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No EVM snapshots found for this project. Create a snapshot first.",
            )

        bac = _dec(snapshot.bac)
        ev = _dec(snapshot.ev)
        ac = _dec(snapshot.ac)
        cpi = _dec(snapshot.cpi)
        spi = _dec(snapshot.spi)

        # Calculate ETC based on method
        remaining = bac - ev
        if forecast_method == "spi_cpi" and spi != ZERO and cpi != ZERO:
            etc = (remaining / (spi * cpi)).quantize(QUANTIZE, rounding=ROUND_HALF_UP)
        elif cpi != ZERO:
            etc = (remaining / cpi).quantize(QUANTIZE, rounding=ROUND_HALF_UP)
        else:
            etc = remaining

        eac = (ac + etc).quantize(QUANTIZE, rounding=ROUND_HALF_UP)
        vac = (bac - eac).quantize(QUANTIZE, rounding=ROUND_HALF_UP)

        # TCPI = (BAC - EV) / (BAC - AC)
        denominator = bac - ac
        if denominator != ZERO:
            tcpi = (remaining / denominator).quantize(QUANTIZE, rounding=ROUND_HALF_UP)
        else:
            tcpi = ZERO

        # Confidence range: +/- 10% of EAC
        range_factor = Decimal("0.10")
        conf_low = (eac * (1 - range_factor)).quantize(QUANTIZE, rounding=ROUND_HALF_UP)
        conf_high = (eac * (1 + range_factor)).quantize(QUANTIZE, rounding=ROUND_HALF_UP)

        forecast = EVMForecast(
            project_id=project_id,
            forecast_date=datetime.now(UTC).strftime("%Y-%m-%d"),
            etc_=str(etc),
            eac=str(eac),
            vac=str(vac),
            tcpi=str(tcpi),
            forecast_method=forecast_method,
            confidence_range_low=str(conf_low),
            confidence_range_high=str(conf_high),
            notes=f"Auto-calculated from snapshot {snapshot.snapshot_date} using {forecast_method}",
            metadata_={
                "source_snapshot_id": str(snapshot.id),
                "source_snapshot_date": snapshot.snapshot_date,
                "bac": str(bac),
                "ev": str(ev),
                "ac": str(ac),
                "cpi": str(cpi),
                "spi": str(spi),
            },
        )
        forecast = await self.forecasts.create(forecast)
        logger.info(
            "EVM forecast calculated: project=%s method=%s EAC=%s",
            project_id,
            forecast_method,
            eac,
        )
        return forecast

    async def get_s_curve_data(
        self,
        project_id: uuid.UUID,
    ) -> dict:
        """Return S-curve data combining EVM snapshots and forecasts."""
        from sqlalchemy import select

        from app.modules.finance.models import EVMSnapshot

        # Fetch all snapshots ordered by date
        snap_stmt = (
            select(EVMSnapshot)
            .where(EVMSnapshot.project_id == project_id)
            .order_by(EVMSnapshot.snapshot_date.asc())
        )
        snap_result = await self.session.execute(snap_stmt)
        snapshots = list(snap_result.scalars().all())

        # Fetch all forecasts ordered by date
        forecasts, _ = await self.forecasts.list(project_id=project_id)

        return {
            "project_id": str(project_id),
            "snapshots": [
                {
                    "date": s.snapshot_date,
                    "pv": s.pv,
                    "ev": s.ev,
                    "ac": s.ac,
                    "bac": s.bac,
                }
                for s in snapshots
            ],
            "forecasts": [
                {
                    "date": f.forecast_date,
                    "eac": f.eac,
                    "etc": f.etc_,
                    "vac": f.vac,
                    "tcpi": f.tcpi,
                    "method": f.forecast_method,
                    "confidence_low": f.confidence_range_low,
                    "confidence_high": f.confidence_range_high,
                }
                for f in sorted(forecasts, key=lambda x: x.forecast_date)
            ],
        }
