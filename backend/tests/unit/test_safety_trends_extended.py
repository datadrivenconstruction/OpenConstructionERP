"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the LTIFR/TRIR extended-trend analytics (item 13).

Scope:
    Pure-logic coverage of :meth:`SafetyService.get_trends_extended`,
    :meth:`SafetyService.get_threshold_alert`, the ``_compute_trend_direction``
    slope heuristic, the ``_rate_status`` banding, and the man-hours/recordable
    helpers. The session is a tiny in-order stub so these stay fast and
    loop-safe (no app/lifespan, no real DB).

Test matrix (from the design doc):
    * happy path 12 months -> 12 entries, rolling avg non-null
    * rolling avg arithmetic
    * trend improving / declining / stable / unknown
    * threshold green / yellow / red / unknown
    * zero / negative / non-numeric man-hours ignored
    * custom baseline respected
    * threshold event emitted only when non-green
    * get_stats unchanged (no regression on the shared helpers)
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.safety.schemas import SafetyTrendEntryExtended
from app.modules.safety.service import (
    SafetyService,
    _compute_trend_direction,
    _incident_man_hours,
    _is_recordable,
    _rate_status,
)

PROJECT_ID = uuid.uuid4()


# ── Session stub ──────────────────────────────────────────────────────────


class _SeqSession:
    """Returns preloaded payloads in the order ``execute`` is called.

    Both ``get_trends_extended`` and ``get_stats`` issue two selects
    (incidents, then observations); this hands them back in turn.
    """

    def __init__(self, incidents: list, observations: list) -> None:
        self._payloads = [incidents, observations]
        self._i = 0

    async def execute(self, _stmt: Any) -> Any:
        payload = self._payloads[self._i] if self._i < len(self._payloads) else []
        self._i += 1
        return SimpleNamespace(scalars=lambda p=payload: SimpleNamespace(all=lambda: p))


def _make_service(incidents: list, observations: list | None = None) -> SafetyService:
    svc = SafetyService.__new__(SafetyService)
    svc.session = _SeqSession(incidents, observations or [])
    return svc


def _inc(
    incident_date: str,
    *,
    man_hours: Any = None,
    days_lost: int = 0,
    treatment_type: str | None = None,
    osha_recordable: bool = False,
) -> SimpleNamespace:
    metadata: dict[str, Any] = {}
    if man_hours is not None:
        metadata["man_hours_total"] = man_hours
    return SimpleNamespace(
        id=uuid.uuid4(),
        incident_number="INC-001",
        incident_date=incident_date,
        incident_type="injury",
        status="reported",
        treatment_type=treatment_type,
        days_lost=days_lost,
        osha_recordable=osha_recordable,
        corrective_actions=[],
        metadata_=metadata,
    )


def _obs(created_at: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        risk_score=4,
        created_at=created_at,
    )


# ── Helper-level tests ──────────────────────────────────────────────────────


def test_incident_man_hours_parses_and_guards() -> None:
    assert _incident_man_hours(_inc("2026-01-01", man_hours=50000)) == 50000.0
    assert _incident_man_hours(_inc("2026-01-01", man_hours="40000")) == 40000.0
    # Missing / non-numeric / non-positive -> 0.0 (never corrupts denominator)
    assert _incident_man_hours(_inc("2026-01-01")) == 0.0
    assert _incident_man_hours(_inc("2026-01-01", man_hours="abc")) == 0.0
    assert _incident_man_hours(_inc("2026-01-01", man_hours=-100)) == 0.0
    assert _incident_man_hours(_inc("2026-01-01", man_hours=0)) == 0.0


def test_is_recordable_flag_and_heuristic() -> None:
    assert _is_recordable(_inc("2026-01-01", osha_recordable=True)) is True
    assert _is_recordable(_inc("2026-01-01", treatment_type="hospital")) is True
    assert _is_recordable(_inc("2026-01-01", treatment_type="medical")) is True
    assert _is_recordable(_inc("2026-01-01", treatment_type="first_aid")) is False
    assert _is_recordable(_inc("2026-01-01")) is False


def test_rate_status_bands() -> None:
    # green: at or below baseline
    assert _rate_status(2.0, 2.5) == "green"
    assert _rate_status(2.5, 2.5) == "green"
    # yellow: above baseline, within 150%
    assert _rate_status(3.1, 2.5) == "yellow"  # 124%
    assert _rate_status(3.75, 2.5) == "yellow"  # exactly 150%
    # red: above 150%
    assert _rate_status(3.9, 2.5) == "red"  # 156%
    # unknown denominator
    assert _rate_status(None, 2.5) == "unknown"
    # degenerate zero baseline
    assert _rate_status(0.0, 0.0) == "green"
    assert _rate_status(0.1, 0.0) == "red"


def test_compute_trend_direction() -> None:
    def entries(*vals: float | None) -> list[SafetyTrendEntryExtended]:
        return [SafetyTrendEntryExtended(period=f"2026-{i:02d}", ltifr=v) for i, v in enumerate(vals, 1)]

    assert _compute_trend_direction(entries(5.0, 3.0, 1.0)) == "improving"
    assert _compute_trend_direction(entries(1.0, 3.0, 5.0)) == "declining"
    assert _compute_trend_direction(entries(2.5, 2.5, 2.5)) == "stable"
    # fewer than 3 usable rates -> unknown
    assert _compute_trend_direction(entries(2.5)) == "unknown"
    assert _compute_trend_direction(entries(2.5, None, 2.5)) == "unknown"
    # only the last 3 usable rates count; gaps are skipped
    assert _compute_trend_direction(entries(0.0, None, 5.0, 3.0, 1.0)) == "improving"


# ── get_trends_extended ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trends_extended_happy_path_12_months() -> None:
    incidents = [
        _inc(f"2025-{m:02d}-15", man_hours=50000, days_lost=2, treatment_type="hospital") for m in range(1, 13)
    ]
    svc = _make_service(incidents)
    resp = await svc.get_trends_extended(PROJECT_ID, period="monthly")

    assert resp.period_type == "monthly"
    assert len(resp.entries) == 12
    # Each month: 1 LTI, 50k hours -> LTIFR = 1*1e6/50000 = 20.0; TRIR = 1*2e5/50000 = 4.0
    for e in resp.entries:
        assert e.ltifr == 20.0
        assert e.trir == 4.0
        assert e.lost_time_incidents == 1
        assert e.recordable_incidents == 1
        assert e.man_hours_total == 50000.0
    assert resp.rolling_12_month_ltifr == 20.0
    assert resp.rolling_12_month_trir == 4.0
    assert resp.current_period_ltifr == 20.0
    assert resp.trend_direction == "stable"


@pytest.mark.asyncio
async def test_trends_extended_per_period_rate_differs() -> None:
    """Design example: Dec 2025 -> LTIFR 50.0; Jan 2026 -> LTIFR 20.0."""
    incidents = [
        _inc("2025-12-01", man_hours=20000, days_lost=1, treatment_type="hospital"),
        _inc("2025-12-20", man_hours=20000, days_lost=1, treatment_type="hospital"),
        _inc("2026-01-10", man_hours=50000, days_lost=1, treatment_type="hospital"),
    ]
    svc = _make_service(incidents)
    resp = await svc.get_trends_extended(PROJECT_ID, period="monthly")

    by_period = {e.period: e for e in resp.entries}
    # Dec: 2 LTI, 40k hours -> 2*1e6/40000 = 50.0
    assert by_period["2025-12"].ltifr == 50.0
    # Jan: 1 LTI, 50k hours -> 20.0
    assert by_period["2026-01"].ltifr == 20.0
    # current period is the latest sorted = Jan
    assert resp.current_period_ltifr == 20.0
    # rolling avg over both = (50 + 20) / 2 = 35.0
    assert resp.rolling_12_month_ltifr == 35.0


@pytest.mark.asyncio
async def test_trends_extended_rolling_avg_arithmetic() -> None:
    """Rolling avg ignores no-man-hours gaps, never dragged toward zero."""
    incidents = [
        _inc("2026-01-15", man_hours=1_000_000, days_lost=1),  # LTIFR 1.0
        _inc("2026-02-15", man_hours=500_000, days_lost=1),  # LTIFR 2.0
        _inc("2026-03-15", man_hours=333_333, days_lost=3, treatment_type="medical"),  # 1 LTI / 333,333 h -> LTIFR 3.0
        _inc("2026-04-15"),  # no man-hours -> LTIFR None (gap)
    ]
    svc = _make_service(incidents)
    resp = await svc.get_trends_extended(PROJECT_ID, period="monthly")

    apr = next(e for e in resp.entries if e.period == "2026-04")
    assert apr.ltifr is None
    # mean of (1.0, 2.0, 3.0) = 2.0, the None month excluded
    assert resp.rolling_12_month_ltifr == 2.0
    # current period (Apr) has no rate
    assert resp.current_period_ltifr is None


@pytest.mark.asyncio
async def test_trends_extended_zero_man_hours_yields_none() -> None:
    incidents = [_inc("2026-01-15", days_lost=2, treatment_type="hospital")]  # no man-hours
    svc = _make_service(incidents)
    resp = await svc.get_trends_extended(PROJECT_ID, period="monthly")

    assert len(resp.entries) == 1
    assert resp.entries[0].ltifr is None
    assert resp.entries[0].trir is None
    assert resp.entries[0].man_hours_total == 0.0
    assert resp.rolling_12_month_ltifr is None
    assert resp.trend_direction == "unknown"


@pytest.mark.asyncio
async def test_trends_extended_negative_and_nonnumeric_ignored() -> None:
    incidents = [
        _inc("2026-01-15", man_hours=-100, days_lost=1),
        _inc("2026-01-20", man_hours="not-a-number", days_lost=1),
        _inc("2026-01-25", man_hours=100000, days_lost=1, treatment_type="hospital"),
    ]
    svc = _make_service(incidents)
    resp = await svc.get_trends_extended(PROJECT_ID, period="monthly")

    jan = next(e for e in resp.entries if e.period == "2026-01")
    # Only the 100k-hour incident contributes to the denominator.
    assert jan.man_hours_total == 100000.0
    # 3 lost-time incidents over 100k hours -> 3*1e6/100000 = 30.0
    assert jan.ltifr == 30.0


@pytest.mark.asyncio
async def test_trends_extended_weekly_and_observations() -> None:
    incidents = [_inc("2026-01-05", man_hours=10000, days_lost=1, treatment_type="hospital")]
    observations = [_obs("2026-01-06T10:00:00+00:00")]
    svc = _make_service(incidents, observations)
    resp = await svc.get_trends_extended(PROJECT_ID, period="weekly")

    assert resp.period_type == "weekly"
    # 2026-01-05/06 is ISO week 2 of 2026
    keys = {e.period for e in resp.entries}
    assert any(k.startswith("2026-W") for k in keys)
    total_obs = sum(e.observation_count for e in resp.entries)
    assert total_obs == 1


@pytest.mark.asyncio
async def test_trends_extended_malformed_date_excluded_from_rolling() -> None:
    incidents = [
        _inc("9999-99-99", man_hours=50000, days_lost=1, treatment_type="hospital"),
        _inc("2026-03-15", man_hours=50000, days_lost=1, treatment_type="hospital"),
    ]
    svc = _make_service(incidents)
    resp = await svc.get_trends_extended(PROJECT_ID, period="monthly")

    # The malformed row buckets under "unknown" but does NOT pollute the
    # rolling average or the "current period" (which must be a dated period).
    assert resp.current_period_ltifr == 20.0
    assert resp.rolling_12_month_ltifr == 20.0


# ── get_threshold_alert ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_threshold_green() -> None:
    # 1 LTI over 500k hours -> LTIFR = 2.0 (<= baseline 2.5); 1 recordable -> TRIR 0.4
    incidents = [_inc("2026-01-15", man_hours=500_000, days_lost=1, treatment_type="hospital")]
    svc = _make_service(incidents)
    with patch("app.modules.safety.service.event_bus.publish_detached") as emit:
        resp = await svc.get_threshold_alert(PROJECT_ID)

    assert resp.current_ltifr == 2.0
    assert resp.ltifr_status == "green"
    assert resp.trir_status == "green"
    assert resp.ltifr_delta == round(2.0 - 2.5, 2)
    emit.assert_not_called()


@pytest.mark.asyncio
async def test_threshold_yellow_emits_event() -> None:
    # 1 LTI over ~322.6k hours -> LTIFR ~3.1 (124% of 2.5 baseline) -> yellow
    incidents = [_inc("2026-01-15", man_hours=322_580, days_lost=1, treatment_type="hospital")]
    svc = _make_service(incidents)
    with patch("app.modules.safety.service.event_bus.publish_detached") as emit:
        resp = await svc.get_threshold_alert(PROJECT_ID)

    assert resp.ltifr_status == "yellow"
    emit.assert_called_once()
    assert emit.call_args.args[0] == "safety.threshold_alert_triggered"


@pytest.mark.asyncio
async def test_threshold_red() -> None:
    # 1 LTI over 250k hours -> LTIFR = 4.0 (160% of 2.5) -> red
    incidents = [_inc("2026-01-15", man_hours=250_000, days_lost=1, treatment_type="hospital")]
    svc = _make_service(incidents)
    with patch("app.modules.safety.service.event_bus.publish_detached") as emit:
        resp = await svc.get_threshold_alert(PROJECT_ID)

    assert resp.ltifr_status == "red"
    assert "immediate action" in resp.message.lower()
    emit.assert_called_once()


@pytest.mark.asyncio
async def test_threshold_unknown_no_man_hours() -> None:
    incidents = [_inc("2026-01-15", days_lost=1, treatment_type="hospital")]  # no man-hours
    svc = _make_service(incidents)
    with patch("app.modules.safety.service.event_bus.publish_detached") as emit:
        resp = await svc.get_threshold_alert(PROJECT_ID)

    assert resp.current_ltifr is None
    assert resp.ltifr_status == "unknown"
    assert resp.trir_status == "unknown"
    assert resp.ltifr_delta is None
    emit.assert_not_called()


@pytest.mark.asyncio
async def test_threshold_custom_baseline_respected() -> None:
    # LTIFR 2.0; with a stricter baseline of 1.0 -> 200% -> red
    incidents = [_inc("2026-01-15", man_hours=500_000, days_lost=1, treatment_type="hospital")]
    svc = _make_service(incidents)
    with patch("app.modules.safety.service.event_bus.publish_detached"):
        resp = await svc.get_threshold_alert(PROJECT_ID, baseline_ltifr=1.0, baseline_trir=10.0)

    assert resp.baseline_ltifr == 1.0
    assert resp.ltifr_status == "red"
    # TRIR 0.4 well under the 10.0 baseline -> green
    assert resp.trir_status == "green"


# ── Regression: get_stats unchanged after the shared-helper refactor ─────────


@pytest.mark.asyncio
async def test_get_stats_rates_via_shared_helpers() -> None:
    """The man-hours/recordable refactor must not change get_stats output."""
    incidents = [
        _inc("2026-01-15", man_hours=500_000, days_lost=1, treatment_type="hospital"),
        _inc("2026-02-15", man_hours=500_000, days_lost=0, treatment_type="first_aid"),
    ]
    svc = _make_service(incidents)
    stats = await svc.get_stats(PROJECT_ID)

    # 1 lost-time over 1M hours -> LTIFR 1.0; 1 recordable (hospital) -> TRIR 0.2
    assert stats.ltifr == 1.0
    assert stats.trir == round(1 * 200_000 / 1_000_000, 2)
    assert stats.recordable_incidents == 1


@pytest.mark.asyncio
async def test_threshold_alert_matches_stats() -> None:
    """The alert's current rates must equal get_stats (single source of truth)."""
    incidents = [_inc("2026-01-15", man_hours=400_000, days_lost=1, treatment_type="hospital")]
    svc = _make_service(incidents)

    stats = await svc.get_stats(PROJECT_ID)
    # Rebuild the service (the stub session is single-use) for the alert call.
    svc2 = _make_service(incidents)
    with patch("app.modules.safety.service.event_bus.publish_detached"):
        alert = await svc2.get_threshold_alert(PROJECT_ID)

    assert alert.current_ltifr == stats.ltifr
    assert alert.current_trir == stats.trir


@pytest.mark.asyncio
async def test_create_incident_unaffected() -> None:
    """Smoke: the event-subscriber wiring does not break incident create."""
    from app.modules.safety.schemas import IncidentCreate

    svc = SafetyService.__new__(SafetyService)

    class _Repo:
        async def next_incident_number(self, _pid: uuid.UUID) -> str:
            return "INC-001"

        async def create(self, inc: Any) -> Any:
            # Mirror the real repository: the number is assigned inside
            # create(), not by a separate service call.
            inc.id = uuid.uuid4()
            inc.incident_number = await self.next_incident_number(inc.project_id)
            return inc

    class _Sess:
        async def execute(self, _stmt: Any) -> Any:
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    svc.session = _Sess()
    svc.incident_repo = _Repo()
    data = IncidentCreate(
        project_id=PROJECT_ID,
        incident_date="2026-04-10",
        incident_type="injury",
        description="test",
    )
    with patch("app.modules.safety.service.event_bus.publish_detached", new_callable=AsyncMock):
        inc = await svc.create_incident(data, user_id="u1")
    assert inc.incident_number == "INC-001"
