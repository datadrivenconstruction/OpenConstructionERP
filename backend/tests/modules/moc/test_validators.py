# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Management-of-change rule set on real PostgreSQL through the API."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.modules.moc.permissions import register_moc_permissions
from app.modules.moc.router import router as moc_router
from app.modules.moc.validators import register_moc_validation_rules
from tests._pg import transactional_session
from tests.modules._control_pg import build_app, http, make_project, rule_ids

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_moc_permissions()
    register_moc_validation_rules()
    async with transactional_session() as s:
        yield s


async def _create(c, project_id, **kw):
    return await c.post("/v1/moc/", json={"project_id": str(project_id), "title": "Reroute duct", **kw})


async def _review(c, entry_id):
    r = await c.post(f"/v1/moc/{entry_id}/review", json={})
    assert r.status_code == 200, r.text


async def test_valid_entry_passes_without_findings(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(moc_router, "/v1/moc", db_session, uid)) as c:
        r = await _create(c, pid, cost_impact="1000", currency="EUR", schedule_delta_days=5)
    assert r.status_code == 201, r.text
    assert r.json()["validation_warnings"] == []


async def test_implausible_schedule_delta_is_refused_with_its_code(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(moc_router, "/v1/moc", db_session, uid)) as c:
        r = await _create(c, pid, schedule_delta_days=99999)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "moc.schedule_days_sane"


async def test_cost_without_currency_warns_and_is_saved(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(moc_router, "/v1/moc", db_session, uid)) as c:
        r = await _create(c, pid, cost_impact="1000")
    assert r.status_code == 201, r.text
    assert rule_ids(r.json()["validation_warnings"]) == {"moc.currency_stated"}


async def test_entry_cost_that_differs_from_its_impact_lines_warns(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(moc_router, "/v1/moc", db_session, uid)) as c:
        entry = (await _create(c, pid, cost_impact="1000", currency="EUR")).json()
        line = await c.post(
            f"/v1/moc/{entry['id']}/impacts", json={"impact_area": "cost", "cost_impact": "400", "currency": "EUR"}
        )
    assert line.status_code == 201, line.text
    assert rule_ids(line.json()["validation_warnings"]) == {"moc.cost_matches_impacts"}


async def test_matching_impact_lines_do_not_warn(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(moc_router, "/v1/moc", db_session, uid)) as c:
        entry = (await _create(c, pid, cost_impact="1000", currency="EUR")).json()
        line = await c.post(
            f"/v1/moc/{entry['id']}/impacts", json={"impact_area": "cost", "cost_impact": "1000", "currency": "EUR"}
        )
    assert line.json()["validation_warnings"] == []


async def test_accepting_a_high_risk_change_needs_a_mitigation(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(moc_router, "/v1/moc", db_session, uid)) as c:
        entry = (await _create(c, pid, risk_level="high")).json()
        await _review(c, entry["id"])
        blocked = await c.post(f"/v1/moc/{entry['id']}/accept", json={})
        await c.post(
            f"/v1/moc/{entry['id']}/impacts",
            json={"impact_area": "safety", "severity": "high", "mitigation": "Exclusion zone and spotter"},
        )
        accepted = await c.post(f"/v1/moc/{entry['id']}/accept", json={})
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["detail"]["code"] == "moc.high_risk_mitigated"
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"


async def test_a_medium_risk_change_is_accepted_without_impact_lines(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(moc_router, "/v1/moc", db_session, uid)) as c:
        entry = (await _create(c, pid, risk_level="medium")).json()
        await _review(c, entry["id"])
        accepted = await c.post(f"/v1/moc/{entry['id']}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["validation_warnings"] == []


async def test_declining_needs_a_reason(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(moc_router, "/v1/moc", db_session, uid)) as c:
        entry = (await _create(c, pid)).json()
        await _review(c, entry["id"])
        blocked = await c.post(f"/v1/moc/{entry['id']}/decline", json={})
        declined = await c.post(f"/v1/moc/{entry['id']}/decline", json={"notes": "Clashes with the fire strategy"})
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["detail"]["code"] == "moc.decline_reason_recorded"
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "declined"
