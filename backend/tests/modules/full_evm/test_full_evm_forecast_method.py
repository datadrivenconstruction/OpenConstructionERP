# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Forecast-method provenance on the legacy snapshot-derived surface.

``EVMService.calculate_forecast`` used to accept any string as a method and
quietly treat everything it did not recognise as the cost-trend formula. It
also fell back to remaining-as-planned whenever CPI was zero - the normal state
of a project that has earned nothing yet - while still recording the requested
method on the row. The number was therefore produced by one formula and
labelled with another, and the standard EAC formulas disagree by design.

These tests pin the two halves of the fix: an unknown method is rejected, and
whenever a fallback happens the row says so.

Driven through a stub session in the style of ``tests/unit/test_full_evm_service.py``
so the arithmetic under test is not hidden behind database setup.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.full_evm.service import EVMService


class _StubSession:
    """Minimal AsyncSession stub: ``calculate_forecast`` issues one query."""

    def __init__(self, snapshot: Any | None) -> None:
        self._snapshot = snapshot

    async def execute(self, _stmt: Any) -> Any:
        snap = self._snapshot

        class _Result:
            def scalar_one_or_none(self_inner) -> Any:  # noqa: N805
                return snap

        return _Result()


class _StubForecastRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def create(self, forecast: Any) -> Any:
        if getattr(forecast, "id", None) is None:
            forecast.id = uuid.uuid4()
        self.rows.append(forecast)
        return forecast


def _make_service(snapshot: Any | None) -> EVMService:
    service = EVMService.__new__(EVMService)
    service.session = _StubSession(snapshot)  # type: ignore[assignment]
    service.forecasts = _StubForecastRepo()  # type: ignore[assignment]
    return service


def _snapshot(*, cpi: str = "0.9615", spi: str = "0.95") -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        snapshot_date="2026-04-01",
        bac="1000000",
        pv="550000",
        ev="500000",
        ac="520000",
        cpi=cpi,
        spi=spi,
    )


# ── Method vocabulary ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unknown_method_is_rejected_with_422() -> None:
    """Guessing which formula the caller meant is how a project is misreported."""
    service = _make_service(_snapshot())

    with pytest.raises(HTTPException) as exc:
        await service.calculate_forecast(uuid.uuid4(), forecast_method="banana")

    assert exc.value.status_code == 422
    assert "Unknown forecast method" in exc.value.detail


@pytest.mark.asyncio
async def test_the_legacy_spi_cpi_name_still_works_and_records_the_canonical_one() -> None:
    """``spi_cpi`` is this module's old name for ``combined``; both are accepted."""
    service = _make_service(_snapshot())

    forecast = await service.calculate_forecast(uuid.uuid4(), forecast_method="spi_cpi")

    assert forecast.forecast_method == "spi_cpi"
    assert forecast.metadata_["requested_method"] == "combined"
    assert forecast.metadata_["effective_method"] == "combined"


@pytest.mark.asyncio
async def test_method_names_are_case_and_whitespace_tolerant() -> None:
    """A saved job payload with stray whitespace must not 422."""
    service = _make_service(_snapshot())

    forecast = await service.calculate_forecast(uuid.uuid4(), forecast_method="  CPI ")

    assert forecast.metadata_["requested_method"] == "cpi"


# ── Provenance when a formula cannot run ─────────────────────────────────────


@pytest.mark.asyncio
async def test_a_zero_cpi_records_the_fallback_instead_of_claiming_the_cost_trend() -> None:
    """Nothing earned yet means no cost trend, so remaining-as-planned runs.

    The regression: the row previously said ``cpi`` while the number came from
    ``remaining``, and the two give different answers.
    """
    service = _make_service(_snapshot(cpi="0", spi="0"))

    forecast = await service.calculate_forecast(uuid.uuid4(), forecast_method="cpi")

    assert forecast.metadata_["requested_method"] == "cpi"
    assert forecast.metadata_["effective_method"] == "remaining"
    assert "requested 'cpi'" in forecast.notes
    # Arithmetic is unchanged: ETC = BAC - EV = 500000, EAC = AC + ETC.
    assert Decimal(forecast.etc_) == Decimal("500000")
    assert Decimal(forecast.eac) == Decimal("1020000")


@pytest.mark.asyncio
async def test_a_zero_spi_degrades_combined_to_the_cost_trend_not_to_remaining() -> None:
    """The walk goes down one rung at a time, never past a formula that can run."""
    service = _make_service(_snapshot(cpi="0.9615", spi="0"))

    forecast = await service.calculate_forecast(uuid.uuid4(), forecast_method="combined")

    assert forecast.metadata_["effective_method"] == "cpi"


@pytest.mark.asyncio
async def test_requesting_remaining_never_silently_upgrades_to_a_trend_formula() -> None:
    """Asking for remaining-as-planned means exactly that, even when CPI exists."""
    service = _make_service(_snapshot())

    forecast = await service.calculate_forecast(uuid.uuid4(), forecast_method="remaining")

    assert forecast.metadata_["effective_method"] == "remaining"
    assert Decimal(forecast.etc_) == Decimal("500000")


@pytest.mark.asyncio
async def test_auto_picks_the_richest_formula_that_can_run() -> None:
    """With both indices present ``auto`` resolves to the combined formula."""
    service = _make_service(_snapshot())

    forecast = await service.calculate_forecast(uuid.uuid4(), forecast_method="auto")

    assert forecast.metadata_["effective_method"] == "combined"


@pytest.mark.asyncio
async def test_a_forecast_that_used_the_requested_formula_says_nothing_extra() -> None:
    """The note only mentions a substitution when one actually happened."""
    service = _make_service(_snapshot())

    forecast = await service.calculate_forecast(uuid.uuid4(), forecast_method="cpi")

    assert forecast.metadata_["effective_method"] == "cpi"
    assert "requested" not in forecast.notes
