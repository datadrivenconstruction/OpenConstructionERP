# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Capital plan HTTP surface: status codes, response shapes, role gates, the workbook download.

The router is mounted on a bare app with the database session and the caller's token
swapped, so the real permission gate runs with a viewer or a manager token.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.dependencies import get_current_user_payload, get_session
from app.modules.capital_plan.permissions import register_capital_plan_permissions
from app.modules.capital_plan.router import router
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    register_capital_plan_permissions()
    async with transactional_session() as session:
        user = User(email=f"capapi-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x")
        session.add(user)
        await session.flush()
        role = {"value": "manager"}
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/capital_plan")

        async def _session():
            yield session

        async def _payload():
            return {"sub": str(user.id), "role": role["value"], "permissions": []}

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_current_user_payload] = _payload
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t/api/v1/capital_plan") as client:
            yield client, role


async def _plan(client) -> dict:
    res = await client.post("/plans/", json={"name": "P", "currency": "eur", "start_year": 2030, "horizon_years": 3})
    assert res.status_code == 201, res.text
    return res.json()


async def test_the_whole_what_if_loop_over_http(world) -> None:
    client, _ = world
    plan = await _plan(client)
    assert plan["currency"] == "EUR" and plan["metadata"] == {}
    pid = plan["id"]
    (base,) = (await client.get(f"/plans/{pid}/scenarios/")).json()["items"]
    assert base["is_baseline"]

    env = {"envelopes": [{"year": 2030, "amount": "100", "label": "Bond"}]}
    assert (await client.put(f"/plans/{pid}/envelopes/", json=env)).status_code == 200
    item = (
        await client.post(
            f"/scenarios/{base['id']}/items/",
            json={"title": "Road", "start_year": 2030, "total_cost": "150", "priority": 2, "duration_years": 1},
        )
    ).json()
    assert item["phasing"] == [] and item["status"] == "proposed"
    page = (await client.get(f"/scenarios/{base['id']}/items/", params={"limit": 1, "offset": 1})).json()
    assert page["items"] == [] and page["total"] == 1

    summary = (await client.get(f"/scenarios/{base['id']}/summary/")).json()
    assert summary["rows"][0]["gap"] == "-50.00"
    assert summary["unfunded"] == [item["id"]]
    assert any(f["rule_id"] == "cp.year_over_envelope" for f in summary["findings"])

    clone = (await client.post(f"/plans/{pid}/scenarios/{base['id']}/clone/", json={"name": "Delay"})).json()
    (copy,) = (await client.get(f"/scenarios/{clone['id']}/items/")).json()["items"]
    assert (await client.patch(f"/items/{copy['id']}/", json={"start_year": 2031})).json()["start_year"] == 2031
    assert (await client.get(f"/scenarios/{base['id']}/items/")).json()["items"][0]["start_year"] == 2030

    cmp = (await client.get(f"/plans/{pid}/compare/", params={"a": base["id"], "b": clone["id"]})).json()
    assert cmp["changed_items"][0]["start_year_b"] == 2031

    suggestion = (await client.post(f"/scenarios/{base['id']}/autofund/")).json()
    assert suggestion["items"][0]["reason"] == "exceeds envelope in 2030"
    assert (await client.get(f"/scenarios/{base['id']}/items/")).json()["items"][0]["status"] == "proposed"

    sheet = await client.get(f"/scenarios/{base['id']}/export/")
    assert sheet.status_code == 200 and sheet.content[:2] == b"PK"


async def test_a_viewer_reads_but_every_change_is_403(world) -> None:
    client, role = world
    plan = await _plan(client)
    role["value"] = "viewer"
    assert (await client.get("/plans/")).status_code == 200
    assert (await client.get(f"/plans/{plan['id']}/scenarios/")).status_code == 200
    assert (await client.post("/plans/", json={"name": "x", "currency": "EUR", "start_year": 2030})).status_code == 403
    assert (await client.patch(f"/plans/{plan['id']}/", json={"name": "y"})).status_code == 403
    assert (await client.put(f"/plans/{plan['id']}/envelopes/", json={"envelopes": []})).status_code == 403
    assert (await client.delete(f"/plans/{plan['id']}/")).status_code == 403


async def test_bad_input_is_rejected(world) -> None:
    client, _ = world
    plan = await _plan(client)
    assert (
        await client.post("/plans/", json={"name": "x", "currency": "EUR", "start_year": 2030, "horizon_years": 40})
    ).status_code == 422
    (base,) = (await client.get(f"/plans/{plan['id']}/scenarios/")).json()["items"]
    bad = {"title": "t", "start_year": 2030, "priority": 9}
    assert (await client.post(f"/scenarios/{base['id']}/items/", json=bad)).status_code == 422
    assert (await client.get(f"/scenarios/{uuid.uuid4()}/summary/")).status_code == 404
