"""Risk register and safety defects found in the deep review (no database needed)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.modules.risk import router as risk_router
from app.modules.risk.repository import RiskRepository, _order_clause
from app.modules.risk.schemas import RiskCreate, RiskUpdate
from app.modules.safety.schemas import IncidentCreate, IncidentUpdate

PID = uuid.uuid4()


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _stmt):
        return _FakeResult(self._rows)


@pytest.mark.asyncio
async def test_next_code_does_not_reuse_a_code_after_a_delete():
    # R-002 was deleted: count+1 would hand out R-003 again.
    repo = RiskRepository(_FakeSession(["R-001", "R-003"]))
    assert await repo.next_code(PID) == "R-004"


@pytest.mark.asyncio
async def test_next_code_ignores_non_standard_codes_and_starts_at_one():
    assert await RiskRepository(_FakeSession([])).next_code(PID) == "R-001"
    assert await RiskRepository(_FakeSession(["IMPORT-9", ""])).next_code(PID) == "R-001"


def _sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect())).lower()


def test_sort_by_unknown_attribute_falls_back_instead_of_raising():
    # getattr(RiskItem, "registry") used to be accepted and blew up as a 500.
    assert "created_at" in _sql(_order_clause("registry", "asc"))
    assert "created_at" in _sql(_order_clause("metadata_", "desc"))


def test_sort_by_score_is_numeric_not_lexicographic():
    sql = _sql(_order_clause("risk_score", "desc"))
    assert "cast" in sql and "float" in sql


@pytest.mark.asyncio
async def test_create_risk_checks_project_access(monkeypatch):
    calls = []

    async def deny(project_id, user_id, session):
        calls.append(project_id)
        raise risk_router.HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(risk_router, "verify_project_access", deny)
    service = SimpleNamespace(create_risk=None)
    data = RiskCreate(project_id=PID, title="Crane failure")
    with pytest.raises(risk_router.HTTPException) as exc:
        await risk_router.create_risk(data, "u1", object(), None, service)
    assert exc.value.status_code == 404
    assert calls == [PID]


@pytest.mark.parametrize("model", [RiskCreate, RiskUpdate])
def test_schedule_days_has_an_upper_bound(model):
    base = {"project_id": PID, "title": "x"} if model is RiskCreate else {}
    with pytest.raises(ValidationError):
        model(**base, impact_schedule_days=3_000_000_000)


def _incident_base(model, **extra):
    if model is IncidentUpdate:
        return dict(extra)
    return {
        "project_id": PID,
        "incident_date": "2026-01-02",
        "incident_type": "injury",
        "severity": "minor",
        "description": "d",
        **extra,
    }


@pytest.mark.parametrize("model", [IncidentCreate, IncidentUpdate])
def test_days_lost_has_an_upper_bound(model):
    base = _incident_base(model)
    with pytest.raises(ValidationError):
        model(**base, days_lost=3_000_000_000)


@pytest.mark.parametrize("model", [IncidentCreate, IncidentUpdate])
def test_incident_date_must_be_a_real_date(model):
    base = _incident_base(model)
    base.pop("incident_date", None)
    with pytest.raises(ValidationError):
        model(**base, incident_date="2026-13-45")
    assert model(**base, incident_date="2026-02-28").incident_date == "2026-02-28"
