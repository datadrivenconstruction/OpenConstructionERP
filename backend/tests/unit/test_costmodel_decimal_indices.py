"""SPI / CPI auto-computation is exact Decimal arithmetic rounded to 4 places."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.costmodel.schemas import SnapshotCreate
from tests.unit.test_costmodel_service import _make_service


async def _indices(planned: str, earned: str, actual: str) -> tuple[float, float]:
    service = _make_service()
    snap = await service.create_snapshot(
        SnapshotCreate(
            project_id=uuid.uuid4(),
            period="2026-05",
            planned_cost=Decimal(planned),
            earned_value=Decimal(earned),
            actual_cost=Decimal(actual),
        )
    )
    return float(snap.spi), float(snap.cpi)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "planned,earned,actual,spi,cpi",
    [
        ("100000", "80000", "90000", 0.8, 0.8889),
        ("3", "1", "3", 0.3333, 0.3333),
        ("32", "1", "32", 0.0312, 0.0312),  # exact tie: half-even
        ("9999999999999.99", "9999999999999.99", "19999999999999.98", 1.0, 0.5),
        ("0", "5", "0", 0.0, 0.0),
    ],
)
async def test_indices(planned: str, earned: str, actual: str, spi: float, cpi: float) -> None:
    assert await _indices(planned, earned, actual) == (spi, cpi)
