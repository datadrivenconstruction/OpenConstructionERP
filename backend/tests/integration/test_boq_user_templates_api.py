"""Editable BOQ templates through the HTTP API.

Covers: a built-in template cannot be edited in place but can be copied, the copy
is editable and returns warnings, another user cannot see or touch it, a bill
becomes a template (keep/clear numbers, project data stripped, empty sections
dropped) and a template becomes a bill again.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

BASE = "/api/v1/boq"


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncClient:
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _register(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"tpl-{unique}@test.io"
    password = f"Tpl{unique}9!x"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Template Tester"},
    )
    assert reg.status_code == 201, reg.text

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(is_active=True))
        await session.commit()
    resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = resp.json().get("access_token", "")
    assert token, resp.text
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def owner(client: AsyncClient) -> dict[str, str]:
    return await _register(client)


@pytest_asyncio.fixture(scope="module")
async def other(client: AsyncClient) -> dict[str, str]:
    return await _register(client)


async def _bill(client: AsyncClient, h: dict[str, str]) -> tuple[str, str]:
    proj = await client.post(
        "/api/v1/projects/", json={"name": f"P {uuid.uuid4().hex[:6]}", "currency": "EUR"}, headers=h
    )
    assert proj.status_code == 201, proj.text
    pid = proj.json()["id"]
    boq = await client.post(f"{BASE}/boqs/", json={"project_id": pid, "name": "Source bill"}, headers=h)
    assert boq.status_code == 201, boq.text
    bid = boq.json()["id"]
    sec = await client.post(
        f"{BASE}/boqs/{bid}/positions/",
        json={
            "boq_id": bid,
            "ordinal": "A",
            "description": "Earthwork",
            "unit": "section",
            "quantity": 0,
            "unit_rate": 0,
        },
        headers=h,
    )
    assert sec.status_code == 201, sec.text
    for ordinal, desc, unit, qty, rate in (("A.1", "Excavation", "m3", 120.5, 12.5), ("A.2", "Backfill", "m3", 40, 9)):
        r = await client.post(
            f"{BASE}/boqs/{bid}/positions/",
            json={
                "boq_id": bid,
                "parent_id": sec.json()["id"],
                "ordinal": ordinal,
                "description": desc,
                "unit": unit,
                "quantity": qty,
                "unit_rate": rate,
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
    empty = await client.post(
        f"{BASE}/boqs/{bid}/positions/",
        json={
            "boq_id": bid,
            "ordinal": "B",
            "description": "Empty group",
            "unit": "section",
            "quantity": 0,
            "unit_rate": 0,
        },
        headers=h,
    )
    assert empty.status_code == 201, empty.text
    return pid, bid


async def test_builtin_is_read_only_and_duplicate_gives_an_editable_copy(client, owner):
    listed = (await client.get(f"{BASE}/boqs/templates/", headers=owner)).json()
    builtin = next(t for t in listed if t["id"] == "residential")
    assert builtin["builtin"] is True

    put = await client.put(f"{BASE}/boqs/templates/residential/", json={"name": "x"}, headers=owner)
    assert put.status_code == 403
    assert (await client.delete(f"{BASE}/boqs/templates/residential/", headers=owner)).status_code == 403

    copy = await client.post(f"{BASE}/boqs/templates/residential/duplicate/", headers=owner)
    assert copy.status_code == 201, copy.text
    body = copy.json()
    assert body["builtin"] is False and body["copied_from"] == "residential" and body["origin"] == "copy"
    assert body["sections"] and body["warnings"] == []

    body["name"] = "My residential"
    body["sections"][0]["positions"][0]["unit"] = ""
    saved = await client.put(f"{BASE}/boqs/templates/{body['id']}/", json=body, headers=owner)
    assert saved.status_code == 200, saved.text
    assert saved.json()["name"] == "My residential"
    assert [w["rule_id"] for w in saved.json()["warnings"]] == ["boq.template.position_has_unit"]

    # the built-in is untouched
    assert (await client.get(f"{BASE}/boqs/templates/residential/", headers=owner)).json()["builtin"] is True
    assert any(t["id"] == body["id"] for t in (await client.get(f"{BASE}/boqs/templates/", headers=owner)).json())


async def test_templates_are_private_to_their_owner(client, owner, other):
    created = await client.post(f"{BASE}/boqs/templates/", json={"name": "Mine"}, headers=owner)
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    assert (await client.get(f"{BASE}/boqs/templates/{tid}/", headers=other)).status_code == 404
    assert (await client.put(f"{BASE}/boqs/templates/{tid}/", json={"name": "x"}, headers=other)).status_code == 404
    assert (await client.delete(f"{BASE}/boqs/templates/{tid}/", headers=other)).status_code == 404
    assert all(t["id"] != tid for t in (await client.get(f"{BASE}/boqs/templates/", headers=other)).json())
    assert (await client.delete(f"{BASE}/boqs/templates/{tid}/", headers=owner)).status_code == 204


async def test_validate_endpoint_returns_warnings_without_saving(client, owner):
    resp = await client.post(
        f"{BASE}/boqs/templates/validate/",
        json={"name": "T", "sections": [{"ordinal": "1", "description": "S", "positions": []}]},
        headers=owner,
    )
    assert resp.status_code == 200
    assert [i["rule_id"] for i in resp.json()] == ["boq.template.section_not_empty"]


async def test_template_from_estimate_and_back(client, owner, other):
    pid, bid = await _bill(client, owner)

    req = {"boq_id": bid, "name": "Earthwork kit", "keep_quantities": False, "keep_rates": True}
    made = await client.post(f"{BASE}/boqs/templates/from-boq/", json=req, headers=owner)
    assert made.status_code == 201, made.text
    tpl = made.json()
    assert tpl["origin"] == "boq" and tpl["name"] == "Earthwork kit"
    assert [s["description"] for s in tpl["sections"]] == ["Earthwork"]  # empty group dropped
    positions = tpl["sections"][0]["positions"]
    assert [p["ordinal"] for p in positions] == ["01.0010", "01.0020"]
    assert [p["quantity"] for p in positions] == [None, None]
    assert [p["rate"] for p in positions] == ["12.5", "9"]
    assert "project" not in str(tpl).lower()

    # the other user cannot copy someone else's bill
    denied = await client.post(f"{BASE}/boqs/templates/from-boq/", json={"boq_id": bid}, headers=other)
    assert denied.status_code == 404

    kept = await client.post(
        f"{BASE}/boqs/templates/from-boq/", json={"boq_id": bid, "keep_quantities": True}, headers=owner
    )
    assert [p["quantity"] for p in kept.json()["sections"][0]["positions"]] == ["120.5", "40"]

    # a bill from the template: no area needed, blank quantities become zero
    bill = await client.post(
        f"{BASE}/boqs/from-template/", json={"template_id": tpl["id"], "project_id": pid}, headers=owner
    )
    assert bill.status_code == 201, bill.text
    # a bill from a built-in still needs an area
    no_area = await client.post(
        f"{BASE}/boqs/from-template/", json={"template_id": "residential", "project_id": pid}, headers=owner
    )
    assert no_area.status_code == 422
