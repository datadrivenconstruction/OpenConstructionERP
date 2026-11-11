"""NCR cross-module subscribers that need no database."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.ncr import events


class _Bus:
    def __init__(self, fail_on: str | None = None):
        self.published: list[tuple[str, dict]] = []
        self.subscribed: list[str] = []
        self.fail_on = fail_on

    def publish_detached(self, name, data, source_module=""):
        if name == self.fail_on:
            raise RuntimeError("bus down")
        self.published.append((name, data))

    def subscribe_once(self, name, handler):
        self.subscribed.append(name)


@pytest.fixture
def bus(monkeypatch):
    fake = _Bus()
    monkeypatch.setattr(events, "event_bus", fake)
    return fake


def _event(**data):
    return SimpleNamespace(data=data)


@pytest.mark.asyncio
async def test_closed_with_cost_fans_out_to_moc_and_bi(bus):
    pid, nid = uuid.uuid4(), uuid.uuid4()
    await events._on_ncr_closed_with_cost_impact(
        _event(ncr_id=nid, project_id=pid, ncr_number="NCR-001", title="Crack", cost_impact="900")
    )
    names = [n for n, _ in bus.published]
    assert names == ["moc.candidate_from_ncr", "bi_dashboards.kpi_recompute"]
    moc = bus.published[0][1]
    assert moc["ncr_id"] == str(nid) and moc["project_id"] == str(pid)
    assert moc["cost_impact"] == "900"
    assert moc["schedule_impact_days"] == 0
    assert "scope_creep_value" in bus.published[1][1]["kpi_codes"]


@pytest.mark.asyncio
async def test_closed_with_cost_needs_ids(bus):
    await events._on_ncr_closed_with_cost_impact(_event(ncr_id=str(uuid.uuid4())))
    await events._on_ncr_closed_with_cost_impact(SimpleNamespace(data=None))
    assert bus.published == []


@pytest.mark.asyncio
async def test_bus_failure_never_propagates(monkeypatch):
    monkeypatch.setattr(events, "event_bus", _Bus(fail_on="moc.candidate_from_ncr"))
    await events._on_ncr_closed_with_cost_impact(_event(ncr_id="n", project_id="p"))
    fake = _Bus(fail_on="bi_dashboards.kpi_recompute")
    monkeypatch.setattr(events, "event_bus", fake)
    await events._on_ncr_closed_with_cost_impact(_event(ncr_id="n", project_id="p"))
    assert [n for n, _ in fake.published] == ["moc.candidate_from_ncr"]


def test_register_subscribes_four_handlers(bus):
    events.register_subscribers()
    assert sorted(bus.subscribed) == sorted(
        [
            "qms.audit.finding_raised",
            "clash.high_severity.detected",
            "validation.results.errors_found",
            "ncr.closed_with_cost_impact",
        ]
    )


@pytest.mark.asyncio
async def test_isolated_session_gate_follows_dialect(monkeypatch):
    def factory(dialect):
        class _Ctx:
            async def __aenter__(self):
                return SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name=dialect)))

            async def __aexit__(self, *a):
                return False

        return lambda: _Ctx()

    monkeypatch.setattr(events, "async_session_factory", factory("postgresql"))
    assert await events._can_open_isolated_session() is True
    monkeypatch.setattr(events, "async_session_factory", factory("sqlite"))
    assert await events._can_open_isolated_session() is False

    def broken():
        raise RuntimeError("no engine")

    monkeypatch.setattr(events, "async_session_factory", broken)
    assert await events._can_open_isolated_session() is False
