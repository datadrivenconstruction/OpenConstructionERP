"""Unit tests for :class:`SafetyService`.

Scope:
    Covers incident CRUD, observation CRUD with risk score computation,
    severity categories, observation type handling, risk tier derivation,
    update with recomputed risk score, and list with filters.
    Repositories and event bus are stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.safety.schemas import (
    CorrectiveActionEntry,
    IncidentCreate,
    IncidentUpdate,
    ObservationCreate,
    ObservationUpdate,
)
from app.modules.safety.service import SafetyService, _compute_risk_tier

# ── Helpers / stubs ───────────────────────────────────────────────────────

PROJECT_ID = uuid.uuid4()


def _make_service() -> SafetyService:
    service = SafetyService.__new__(SafetyService)
    service.session = _StubSession()
    service.incident_repo = _StubIncidentRepo()
    service.observation_repo = _StubObservationRepo()
    return service


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: None, scalars=lambda: _EmptyScalars())


class _EmptyScalars:
    def all(self) -> list:
        return []


class _StubIncidentRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, incident: Any) -> Any:
        if getattr(incident, "id", None) is None:
            incident.id = uuid.uuid4()
        now = datetime.now(UTC)
        incident.created_at = now
        incident.updated_at = now
        self.rows[incident.id] = incident
        return incident

    async def get_by_id(self, incident_id: uuid.UUID) -> Any:
        return self.rows.get(incident_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        incident_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if incident_type:
            rows = [r for r in rows if r.incident_type == incident_type]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, incident_id: uuid.UUID, **kwargs: Any) -> None:
        inc = self.rows.get(incident_id)
        if inc:
            for k, v in kwargs.items():
                setattr(inc, k, v)
            inc.updated_at = datetime.now(UTC)

    async def delete(self, incident_id: uuid.UUID) -> None:
        self.rows.pop(incident_id, None)

    async def next_incident_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"INC-{self._counter:04d}"


class _StubObservationRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, obs: Any) -> Any:
        if getattr(obs, "id", None) is None:
            obs.id = uuid.uuid4()
        now = datetime.now(UTC)
        obs.created_at = now
        obs.updated_at = now
        self.rows[obs.id] = obs
        return obs

    async def get_by_id(self, obs_id: uuid.UUID) -> Any:
        return self.rows.get(obs_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        observation_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if observation_type:
            rows = [r for r in rows if r.observation_type == observation_type]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, obs_id: uuid.UUID, **kwargs: Any) -> None:
        obs = self.rows.get(obs_id)
        if obs:
            for k, v in kwargs.items():
                setattr(obs, k, v)
            obs.updated_at = datetime.now(UTC)

    async def delete(self, obs_id: uuid.UUID) -> None:
        self.rows.pop(obs_id, None)

    async def next_observation_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"OBS-{self._counter:04d}"


def _incident_data(**overrides: Any) -> IncidentCreate:
    defaults = {
        "project_id": PROJECT_ID,
        "title": "Worker fall from scaffolding",
        "incident_date": "2026-04-10",
        "incident_type": "injury",
        "severity": "major",
        "description": "Worker fell 3m from scaffolding level 2",
    }
    defaults.update(overrides)
    return IncidentCreate(**defaults)


def _observation_data(**overrides: Any) -> ObservationCreate:
    defaults = {
        "project_id": PROJECT_ID,
        "observation_type": "unsafe_condition",
        "description": "Missing guardrail on scaffolding level 3",
        "severity": 4,
        "likelihood": 3,
    }
    defaults.update(overrides)
    return ObservationCreate(**defaults)


# ── Tests: risk tier computation ─────────────────────────────────────────


def test_risk_tier_low() -> None:
    assert _compute_risk_tier(1) == "low"
    assert _compute_risk_tier(5) == "low"


def test_risk_tier_medium() -> None:
    assert _compute_risk_tier(6) == "medium"
    assert _compute_risk_tier(10) == "medium"


def test_risk_tier_high() -> None:
    assert _compute_risk_tier(11) == "high"
    assert _compute_risk_tier(15) == "high"


def test_risk_tier_critical() -> None:
    assert _compute_risk_tier(16) == "critical"
    assert _compute_risk_tier(25) == "critical"


# ── Tests: incidents ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_incident() -> None:
    svc = _make_service()
    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        incident = await svc.create_incident(_incident_data(), user_id="safety-mgr")

    assert incident.id is not None
    assert incident.incident_number == "INC-0001"
    assert incident.incident_type == "injury"
    assert incident.severity == "major"
    assert incident.status == "reported"
    assert incident.created_by == "safety-mgr"


@pytest.mark.asyncio
async def test_create_incident_with_corrective_actions() -> None:
    svc = _make_service()
    actions = [
        CorrectiveActionEntry(description="Install guardrails", status="open"),
        CorrectiveActionEntry(description="Re-train workers", status="open"),
    ]
    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        incident = await svc.create_incident(
            _incident_data(corrective_actions=actions),
            user_id="u1",
        )
    assert len(incident.corrective_actions) == 2
    assert incident.corrective_actions[0]["description"] == "Install guardrails"


@pytest.mark.asyncio
async def test_get_incident_not_found() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_incident(uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_incidents_with_type_filter() -> None:
    svc = _make_service()
    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        await svc.create_incident(_incident_data(incident_type="injury"), user_id="u1")
        await svc.create_incident(_incident_data(incident_type="near_miss"), user_id="u1")

    rows, total = await svc.list_incidents(PROJECT_ID, incident_type="near_miss")
    assert total == 1
    assert rows[0].incident_type == "near_miss"


@pytest.mark.asyncio
async def test_update_incident() -> None:
    svc = _make_service()
    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        incident = await svc.create_incident(_incident_data(), user_id="u1")

    updated = await svc.update_incident(
        incident.id,
        IncidentUpdate(root_cause="Scaffolding not properly secured", status="investigating"),
    )
    assert updated.root_cause == "Scaffolding not properly secured"
    assert updated.status == "investigating"


@pytest.mark.asyncio
async def test_delete_incident() -> None:
    svc = _make_service()
    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        incident = await svc.create_incident(_incident_data(), user_id="u1")
    await svc.delete_incident(incident.id)

    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.get_incident(incident.id)


# ── Tests: observations ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_observation_risk_score() -> None:
    """risk_score = severity * likelihood."""
    svc = _make_service()
    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        obs = await svc.create_observation(
            _observation_data(severity=4, likelihood=3),
            user_id="u1",
        )
    assert obs.risk_score == 12  # 4 * 3


@pytest.mark.asyncio
async def test_create_observation_high_risk_event() -> None:
    """Observations with risk_score > 15 should trigger high_risk event."""
    svc = _make_service()
    mock_publish = AsyncMock()
    with patch("app.modules.safety.service.event_bus.publish", mock_publish):
        await svc.create_observation(
            _observation_data(severity=5, likelihood=4),  # risk = 20
            user_id="u1",
        )

    # Check that the high_risk event was published
    event_names = [call.args[0] for call in mock_publish.call_args_list]
    assert "safety.observation.high_risk" in event_names


@pytest.mark.asyncio
async def test_update_observation_recomputes_risk() -> None:
    """Changing severity or likelihood should recompute risk_score."""
    svc = _make_service()
    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        obs = await svc.create_observation(
            _observation_data(severity=2, likelihood=2),
            user_id="u1",
        )
    assert obs.risk_score == 4

    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        updated = await svc.update_observation(
            obs.id,
            ObservationUpdate(severity=5),
        )
    # New risk = 5 * 2 (original likelihood) = 10
    assert updated.risk_score == 10


@pytest.mark.asyncio
async def test_list_observations_with_type_filter() -> None:
    svc = _make_service()
    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        await svc.create_observation(
            _observation_data(observation_type="unsafe_condition"),
            user_id="u1",
        )
        await svc.create_observation(
            _observation_data(observation_type="positive"),
            user_id="u1",
        )

    rows, total = await svc.list_observations(PROJECT_ID, observation_type="positive")
    assert total == 1
    assert rows[0].observation_type == "positive"


@pytest.mark.asyncio
async def test_delete_observation() -> None:
    svc = _make_service()
    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        obs = await svc.create_observation(_observation_data(), user_id="u1")
    await svc.delete_observation(obs.id)

    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.get_observation(obs.id)


# ── Tests: incident-date robustness (safety-reporting integrity) ──────────


def test_parse_incident_date_iso_and_fallbacks() -> None:
    from datetime import date

    from app.modules.safety._dateutil import parse_incident_date

    assert parse_incident_date("2026-04-10") == date(2026, 4, 10)
    assert parse_incident_date("2026-04-10T08:15:00+00:00") == date(2026, 4, 10)
    assert parse_incident_date("10.04.2026") == date(2026, 4, 10)  # DACH dotted
    assert parse_incident_date("2026/04/10") == date(2026, 4, 10)
    assert parse_incident_date("20260410") == date(2026, 4, 10)
    # Empty / unparseable / ambiguous → None (cannot confirm, never guessed)
    assert parse_incident_date("") is None
    assert parse_incident_date(None) is None
    assert parse_incident_date("not-a-date") is None
    assert parse_incident_date("9999-99-99") is None


def test_canonicalize_incident_date_normalises_and_preserves_bad() -> None:
    from app.modules.safety._dateutil import canonicalize_incident_date

    assert canonicalize_incident_date("10.04.2026") == "2026-04-10"
    assert canonicalize_incident_date("2026-04-10") == "2026-04-10"
    # Unparseable is preserved (trimmed), NOT silently erased — the
    # integrity failure must remain visible downstream.
    assert canonicalize_incident_date("  garbage  ") == "garbage"


@pytest.mark.asyncio
async def test_create_incident_canonicalizes_date() -> None:
    """Write path must store a clean ISO YYYY-MM-DD string.

    The API schema enforces the pattern, but a direct service caller may
    pass a non-canonical (yet parseable) form; it must be normalised so the
    downstream "days without incident / LTI" billboard never has to guess.
    """
    svc = _make_service()
    with patch("app.modules.safety.service.event_bus.publish", new_callable=AsyncMock):
        # IncidentCreate enforces the pattern, so build the model then mutate
        # the field to simulate a non-canonical direct-service input.
        data = _incident_data()
        data.incident_date = "10.04.2026"
        incident = await svc.create_incident(data, user_id="u1")
    assert incident.incident_date == "2026-04-10"


class _StatsSession:
    """Session stub whose .execute returns preloaded incidents/observations.

    get_stats issues two ``select`` statements (incidents, then
    observations); this returns them in order.
    """

    def __init__(self, incidents: list, observations: list) -> None:
        self._payloads = [incidents, observations]
        self._i = 0

    async def execute(self, _stmt: Any) -> Any:
        payload = self._payloads[self._i] if self._i < len(self._payloads) else []
        self._i += 1
        return SimpleNamespace(scalars=lambda p=payload: SimpleNamespace(all=lambda: p))


def _incident_row(incident_date: str, *, days_lost: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        incident_number="INC-0001",
        incident_date=incident_date,
        incident_type="injury",
        status="reported",
        treatment_type="hospital",
        days_lost=days_lost,
        corrective_actions=[],
    )


@pytest.mark.asyncio
async def test_get_stats_lti_with_valid_date_reduces_days_without() -> None:
    """A valid recent LTI date yields a small, correct 'days without' value."""
    from datetime import UTC, datetime

    svc = _make_service()
    today = datetime.now(UTC).date()
    iso = f"{today.year:04d}-{today.month:02d}-{today.day:02d}"
    svc.session = _StatsSession([_incident_row(iso)], [])

    stats = await svc.get_stats(PROJECT_ID)

    assert stats.total_incidents == 1
    assert stats.days_without_incident_status == "ok"
    assert stats.days_without_incident is not None
    # Same-day incident → 0; never a large reassuring number.
    assert 0 <= stats.days_without_incident <= 1
    assert stats.unparseable_incident_dates == 0


@pytest.mark.asyncio
async def test_get_stats_malformed_date_not_falsely_safe() -> None:
    """A malformed stored date for a real incident must NOT yield a
    falsely-reassuring large/blank 'all good' number.

    Regression pin for the HSE-Advanced finding: a non-ISO incident_date
    must be reported as 'unconfirmed', not silently dropped to look clean.
    """
    svc = _make_service()
    svc.session = _StatsSession([_incident_row("9999-99-99")], [])

    stats = await svc.get_stats(PROJECT_ID)

    assert stats.total_incidents == 1
    # NOT "none" (that would mean genuinely clean) and NOT a number.
    assert stats.days_without_incident_status == "unconfirmed"
    assert stats.days_without_incident is None
    assert stats.unparseable_incident_dates == 1


@pytest.mark.asyncio
async def test_get_stats_no_incidents_is_genuinely_clean() -> None:
    svc = _make_service()
    svc.session = _StatsSession([], [])

    stats = await svc.get_stats(PROJECT_ID)

    assert stats.total_incidents == 0
    assert stats.days_without_incident_status == "none"
    assert stats.days_without_incident is None


@pytest.mark.asyncio
async def test_get_stats_malformed_does_not_mask_valid_recent() -> None:
    """A garbage string must not win the 'latest' comparison and mask a
    real recent incident (raw string-max bug regression)."""
    from datetime import UTC, datetime

    svc = _make_service()
    today = datetime.now(UTC).date()
    iso = f"{today.year:04d}-{today.month:02d}-{today.day:02d}"
    svc.session = _StatsSession([_incident_row("zzzz-bad"), _incident_row(iso)], [])

    stats = await svc.get_stats(PROJECT_ID)

    # Valid recent date drives the metric; status is "ok" despite the bad row.
    assert stats.days_without_incident_status == "ok"
    assert stats.days_without_incident == 0
    assert stats.unparseable_incident_dates == 1
