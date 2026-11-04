# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Risk register rule set on real PostgreSQL through the API."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.modules.risk.permissions import register_risk_permissions
from app.modules.risk.router import router as risk_router
from app.modules.risk.validators import register_risk_validation_rules
from tests._pg import transactional_session
from tests.modules._control_pg import build_app, http, make_project, rule_ids

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_risk_permissions()
    register_risk_validation_rules()
    async with transactional_session() as s:
        yield s


async def _create(c, project_id, **kw):
    return await c.post("/v1/risk/", json={"project_id": str(project_id), "title": "Crane lift over live road", **kw})


async def test_valid_risk_passes_without_findings(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(risk_router, "/v1/risk", db_session, uid)) as c:
        r = await _create(
            c,
            pid,
            impact_severity="high",
            status="mitigating",
            mitigation_strategy="Road closure and certified lift plan",
            owner_name="Site manager",
            impact_cost=50000,
            response_cost=4000,
        )
    assert r.status_code == 201, r.text
    assert r.json()["validation_warnings"] == []


async def test_a_newly_identified_high_risk_is_not_flagged(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(risk_router, "/v1/risk", db_session, uid)) as c:
        r = await _create(c, pid, impact_severity="critical", status="identified")
    assert r.status_code == 201, r.text
    assert r.json()["validation_warnings"] == []


async def test_mitigating_without_a_mitigation_is_refused_with_its_code(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(risk_router, "/v1/risk", db_session, uid)) as c:
        r = await _create(c, pid, status="mitigating")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "risk.mitigation_defined"


async def test_marking_mitigated_on_update_needs_a_mitigation(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(risk_router, "/v1/risk", db_session, uid)) as c:
        made = (await _create(c, pid)).json()
        blocked = await c.patch(f"/v1/risk/{made['id']}", json={"status": "mitigated"})
        ok = await c.patch(
            f"/v1/risk/{made['id']}", json={"status": "mitigated", "mitigation_strategy": "Dewatering wells installed"}
        )
    assert blocked.status_code == 422 and blocked.json()["detail"]["code"] == "risk.mitigation_defined"
    assert ok.status_code == 200, ok.text


async def test_assessed_high_risk_without_owner_warns(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(risk_router, "/v1/risk", db_session, uid)) as c:
        r = await _create(c, pid, impact_severity="high", status="assessed")
    assert r.status_code == 201, r.text
    assert rule_ids(r.json()["validation_warnings"]) == {"risk.owner_named"}


async def test_response_dearer_than_the_loss_warns(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(risk_router, "/v1/risk", db_session, uid)) as c:
        r = await _create(c, pid, impact_cost=1000, response_cost=5000)
    assert r.status_code == 201, r.text
    assert rule_ids(r.json()["validation_warnings"]) == {"risk.response_within_exposure"}


async def test_closing_a_high_risk_straight_from_identified_warns(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(risk_router, "/v1/risk", db_session, uid)) as c:
        made = (await _create(c, pid, impact_severity="high", status="identified")).json()
        r = await c.patch(f"/v1/risk/{made['id']}", json={"status": "closed"})
        low = (await _create(c, pid, impact_severity="low", status="identified")).json()
        low_closed = await c.patch(f"/v1/risk/{low['id']}", json={"status": "closed"})
    assert r.status_code == 200, r.text
    assert rule_ids(r.json()["validation_warnings"]) == {"risk.closed_with_cause"}
    assert low_closed.json()["validation_warnings"] == []
