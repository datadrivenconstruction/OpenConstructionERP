"""Unit tests for :class:`EVMService` (full_evm module).

Scope:
    Baseline smoke coverage for the advanced EVM forecast calculation
    (ETC / EAC / VAC / TCPI) including the zero-denominator edge case
    on TCPI that previously produced a misleading 0.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.full_evm.service import EVMService


class _StubSession:
    """Minimal AsyncSession stub: only ``execute`` is called by
    ``calculate_forecast``, and the single query returns one snapshot."""

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

    async def list(
        self, *, project_id: uuid.UUID | None = None
    ) -> tuple[list[Any], int]:
        return self.rows, len(self.rows)


def _make_service(snapshot: Any | None) -> EVMService:
    service = EVMService.__new__(EVMService)
    service.session = _StubSession(snapshot)  # type: ignore[assignment]
    service.forecasts = _StubForecastRepo()  # type: ignore[assignment]
    return service


def _make_snapshot(
    *,
    bac: str = "1000000",
    ev: str = "500000",
    ac: str = "520000",
    cpi: str = "0.9615",
    spi: str = "0.9500",
) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        snapshot_date="2026-04-01",
        bac=bac,
        pv="550000",
        ev=ev,
        ac=ac,
        cpi=cpi,
        spi=spi,
    )


# ── Happy path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calculate_forecast_returns_etc_eac_vac_tcpi() -> None:
    service = _make_service(_make_snapshot())
    forecast = await service.calculate_forecast(uuid.uuid4())

    # Every required field is populated with a numeric string.
    for field in ("etc_", "eac", "vac", "tcpi"):
        value = getattr(forecast, field)
        assert value, f"{field} empty"
        # Each should be either a decimal string or the "inf" sentinel.
        assert value == "inf" or _is_decimal_str(value), (
            f"{field}={value!r} not decimal"
        )

    # Sanity: EAC = AC + ETC (derived identity).
    from decimal import Decimal

    assert Decimal(forecast.eac) == Decimal(forecast.etc_) + Decimal("520000")


@pytest.mark.asyncio
async def test_calculate_forecast_cpi_zero_uses_raw_remaining() -> None:
    """When CPI == 0 the service falls back to ETC = remaining budget
    (no divide-by-zero). Tests the defensive branch in
    ``calculate_forecast``."""
    service = _make_service(
        _make_snapshot(bac="100000", ev="0", ac="0", cpi="0", spi="0")
    )
    forecast = await service.calculate_forecast(uuid.uuid4())

    from decimal import Decimal

    # remaining = bac - ev = 100000, cpi==0 → etc = remaining
    assert Decimal(forecast.etc_) == Decimal("100000")
    # EAC = AC + ETC = 0 + 100000
    assert Decimal(forecast.eac) == Decimal("100000")


# ── TCPI denominator-zero edge case ───────────────────────────────────────


@pytest.mark.asyncio
async def test_calculate_forecast_tcpi_zero_denominator_returns_inf_sentinel() -> None:
    """Regression: when BAC == AC (budget fully consumed) but work
    remains, TCPI is mathematically infinite. The previous code
    returned 0, which falsely implied "no effort needed". The new code
    stores the "inf" sentinel so the UI can surface it as
    ``Not Achievable``."""
    service = _make_service(
        _make_snapshot(
            bac="1000000",
            ev="600000",
            ac="1000000",  # BAC == AC — denominator is zero
            cpi="0.6",
            spi="0.9",
        )
    )
    forecast = await service.calculate_forecast(uuid.uuid4())

    # Key assertion: TCPI must NOT be the misleading "0" the old code produced.
    assert forecast.tcpi != "0"
    assert forecast.tcpi == "inf"


@pytest.mark.asyncio
async def test_calculate_forecast_bac_equals_ac_no_remaining_tcpi_zero() -> None:
    """Degenerate case: BAC == AC AND EV == BAC (project complete).
    TCPI numerator (BAC - EV) is also zero, so 0 is the correct answer,
    not the "inf" sentinel."""
    service = _make_service(
        _make_snapshot(
            bac="1000000",
            ev="1000000",
            ac="1000000",
            cpi="1.0",
            spi="1.0",
        )
    )
    forecast = await service.calculate_forecast(uuid.uuid4())

    # Numerator zero → tcpi is plain 0, not "inf".
    assert forecast.tcpi != "inf"
    from decimal import Decimal

    assert Decimal(forecast.tcpi) == Decimal("0")


# ── Helpers ───────────────────────────────────────────────────────────────


def _is_decimal_str(value: str) -> bool:
    from decimal import Decimal, InvalidOperation

    try:
        Decimal(value)
    except (InvalidOperation, ValueError):
        return False
    return True
