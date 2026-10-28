"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for predictive EVM forecast alerts (TOP-30 #19).

Scope:
    * ``EVMService.evaluate_forecast_against_rules`` — deterministic
      threshold evaluation of a forecast against project AlertRules
      (read via raw SQL from the bi_dashboards table).
    * ``EVMService.compute_project_forecasts_batch`` — recompute +
      evaluate + stamp + event-emit for several projects, including the
      no-snapshot skip path.

These tests use lightweight stubs (no real DB / no event loop broker) in
the same spirit as ``test_full_evm_service.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.full_evm.models import EVMForecast
from app.modules.full_evm.service import EVMService

# ── Stubs ───────────────────────────────────────────────────────────────────


class _Result:
    """Mimics the subset of SQLAlchemy Result the service touches."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _StubSession:
    """Routes raw-SQL queries by a substring of the statement text.

    ``alert_rule``  → alert-rule rows
    ``owner_id``    → project owner row
    ``evm_snapshot``→ the latest EVM snapshot (used by calculate_forecast)
    everything else → empty.
    """

    def __init__(
        self,
        *,
        alert_rows: list[Any] | None = None,
        owner_row: Any | None = None,
        snapshot: Any | None = None,
    ) -> None:
        self._alert_rows = alert_rows or []
        self._owner_row = owner_row
        self._snapshot = snapshot
        self.flushed = 0

    async def execute(self, stmt: Any, params: dict | None = None) -> _Result:  # noqa: ARG002
        sql = str(getattr(stmt, "text", stmt)).lower()
        if "alert_rule" in sql:
            return _Result(self._alert_rows)
        if "owner_id" in sql:
            return _Result([self._owner_row] if self._owner_row is not None else [])
        if "evm_snapshot" in sql or "snapshot" in sql:
            return _Result([self._snapshot] if self._snapshot is not None else [])
        return _Result([])

    async def flush(self) -> None:
        self.flushed += 1


class _StubForecastRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def create(self, forecast: Any) -> Any:
        if getattr(forecast, "id", None) is None:
            forecast.id = uuid.uuid4()
        self.rows.append(forecast)
        return forecast

    async def get(self, forecast_id: uuid.UUID) -> Any | None:
        for r in self.rows:
            if getattr(r, "id", None) == forecast_id:
                return r
        return None

    async def list(self, *, project_id: uuid.UUID | None = None) -> tuple[list[Any], int]:  # noqa: ARG002
        return self.rows, len(self.rows)


def _make_service(session: _StubSession) -> EVMService:
    service = EVMService.__new__(EVMService)
    service.session = session  # type: ignore[assignment]
    service.forecasts = _StubForecastRepo()  # type: ignore[assignment]
    return service


def _alert_row(
    *,
    kpi_code: str,
    condition: str,
    threshold: str,
    severity: str = "warning",
    recipients: list[str] | None = None,
    channels: list[str] | None = None,
) -> tuple:
    """Build a raw alert-rule row matching the SELECT column order."""
    return (
        str(uuid.uuid4()),  # id
        f"{kpi_code} {condition} {threshold}",  # name
        kpi_code,  # kpi_code
        condition,  # condition
        threshold,  # threshold_value
        severity,  # severity
        recipients or [],  # recipients_json
        channels or ["in_app"],  # channels_json
    )


def _make_forecast(
    *,
    eac: str = "1100000",
    vac: str = "-100000",
    etc: str = "600000",
    tcpi: str = "1.2",
    bac: str = "1000000",
    cpi: str = "0.857",
    spi: str = "0.95",
) -> EVMForecast:
    f = EVMForecast(
        project_id=uuid.uuid4(),
        forecast_date="2026-06-04",
        etc_=etc,
        eac=eac,
        vac=vac,
        tcpi=tcpi,
        forecast_method="cpi",
        metadata_={"bac": bac, "cpi": cpi, "spi": spi},
    )
    f.id = uuid.uuid4()
    return f


def _make_snapshot(
    *,
    bac: str = "1000000",
    ev: str = "600000",
    ac: str = "700000",  # cpi = ev/ac = 0.857
    cpi: str = "0.857",
    spi: str = "0.95",
) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        snapshot_date="2026-06-04",
        bac=bac,
        pv="630000",
        ev=ev,
        ac=ac,
        cpi=cpi,
        spi=spi,
    )


# ── evaluate_forecast_against_rules ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_forecast_against_rules_cpi_threshold() -> None:
    """A ``cpi below 0.95`` rule fires on a forecast whose CPI is 0.857."""
    session = _StubSession(alert_rows=[_alert_row(kpi_code="cpi", condition="below", threshold="0.95")])
    service = _make_service(session)
    forecast = _make_forecast(cpi="0.857")

    breaches = await service.evaluate_forecast_against_rules(forecast, forecast.project_id)

    assert len(breaches) == 1
    assert breaches[0].kpi_code == "cpi"
    assert breaches[0].observed == Decimal("0.857")
    assert breaches[0].threshold == Decimal("0.95")


@pytest.mark.asyncio
async def test_evaluate_forecast_against_rules_healthy_cpi_no_breach() -> None:
    """A healthy CPI (1.05) does not breach a ``cpi below 0.95`` rule."""
    session = _StubSession(alert_rows=[_alert_row(kpi_code="cpi", condition="below", threshold="0.95")])
    service = _make_service(session)
    forecast = _make_forecast(cpi="1.05")

    breaches = await service.evaluate_forecast_against_rules(forecast, forecast.project_id)

    assert breaches == []


@pytest.mark.asyncio
async def test_evaluate_forecast_against_rules_eac_over_bac_overrun() -> None:
    """An ``eac_over_bac above 1.0`` rule fires when EAC exceeds BAC."""
    session = _StubSession(
        alert_rows=[_alert_row(kpi_code="eac_over_bac", condition="above", threshold="1.0", severity="critical")]
    )
    service = _make_service(session)
    # EAC 1.1M vs BAC 1.0M → ratio 1.1
    forecast = _make_forecast(eac="1100000", bac="1000000")

    breaches = await service.evaluate_forecast_against_rules(forecast, forecast.project_id)

    assert len(breaches) == 1
    assert breaches[0].kpi_code == "eac_over_bac"
    assert breaches[0].severity == "critical"


@pytest.mark.asyncio
async def test_evaluate_forecast_ignores_non_forecast_kpi() -> None:
    """Rules targeting KPIs the forecast cannot speak to are ignored."""
    session = _StubSession(alert_rows=[_alert_row(kpi_code="safety_trir", condition="above", threshold="0.5")])
    service = _make_service(session)
    forecast = _make_forecast()

    breaches = await service.evaluate_forecast_against_rules(forecast, forecast.project_id)

    assert breaches == []


@pytest.mark.asyncio
async def test_evaluate_forecast_tcpi_inf_sentinel_fires_above_rule() -> None:
    """The ``tcpi == 'inf'`` sentinel maps to a large finite value so an
    ``above`` rule still fires (an unachievable to-complete index)."""
    session = _StubSession(alert_rows=[_alert_row(kpi_code="tcpi", condition="above", threshold="1.1")])
    service = _make_service(session)
    forecast = _make_forecast(tcpi="inf")

    breaches = await service.evaluate_forecast_against_rules(forecast, forecast.project_id)

    assert len(breaches) == 1
    assert breaches[0].kpi_code == "tcpi"


# ── compute_project_forecasts_batch ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_compute_project_forecasts_batch_alerts_and_stamps() -> None:
    """A batch run on one project with a breaching snapshot stamps the
    forecast and reports one alerted project."""
    session = _StubSession(
        alert_rows=[_alert_row(kpi_code="cpi", condition="below", threshold="0.95")],
        owner_row=(str(uuid.uuid4()),),
        snapshot=_make_snapshot(cpi="0.857"),
    )
    service = _make_service(session)
    # Swallow event emission + notification dispatch — both are best-effort
    # side effects whose plumbing is covered elsewhere.
    service._dispatch_alert_notifications = _noop_dispatch  # type: ignore[assignment]

    pid = uuid.uuid4()
    results = await service.compute_project_forecasts_batch([pid])

    assert len(results) == 1
    assert results[0]["status"] == "alerted"
    assert results[0]["alerts"] == 1
    # The created forecast row carries the trigger stamp.
    created = service.forecasts.rows[-1]  # type: ignore[attr-defined]
    assert created.alert_status == "triggered"
    assert created.triggered_at is not None
    assert "alert_breaches" in (created.metadata_ or {})


@pytest.mark.asyncio
async def test_compute_project_forecasts_batch_no_snapshot_skips() -> None:
    """A project without an EVM snapshot is skipped, not errored."""
    session = _StubSession(alert_rows=[], owner_row=None, snapshot=None)
    service = _make_service(session)

    pid = uuid.uuid4()
    results = await service.compute_project_forecasts_batch([pid])

    assert len(results) == 1
    assert results[0]["status"] == "no_snapshot"


@pytest.mark.asyncio
async def test_compute_project_forecasts_batch_healthy_no_alert() -> None:
    """A healthy snapshot (CPI 1.05) yields an ``ok`` result, no stamp."""
    session = _StubSession(
        alert_rows=[_alert_row(kpi_code="cpi", condition="below", threshold="0.95")],
        snapshot=_make_snapshot(ac="571000", cpi="1.05"),
    )
    service = _make_service(session)

    pid = uuid.uuid4()
    results = await service.compute_project_forecasts_batch([pid])

    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert results[0]["alerts"] == 0
    created = service.forecasts.rows[-1]  # type: ignore[attr-defined]
    assert created.alert_status is None


# ── acknowledge / snooze ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acknowledge_alert_sets_status() -> None:
    session = _StubSession()
    service = _make_service(session)
    forecast = _make_forecast()
    forecast.alert_status = "triggered"
    await service.forecasts.create(forecast)  # type: ignore[attr-defined]

    updated = await service.acknowledge_alert(forecast.id)

    assert updated is not None
    assert updated.alert_status == "acknowledged"


@pytest.mark.asyncio
async def test_snooze_alert_sets_status_and_until() -> None:
    session = _StubSession()
    service = _make_service(session)
    forecast = _make_forecast()
    forecast.alert_status = "triggered"
    await service.forecasts.create(forecast)  # type: ignore[attr-defined]

    updated = await service.snooze_alert(forecast.id, hours=12)

    assert updated is not None
    assert updated.alert_status == "snoozed"
    assert "snoozed_until" in (updated.metadata_ or {})


async def _noop_dispatch(*_args: Any, **_kwargs: Any) -> None:
    return None
