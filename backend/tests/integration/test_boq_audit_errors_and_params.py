"""BOQ audit: localised errors, cost-breakdown reconciliation, line-items group."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    from ._auth_helpers import promote_to_admin

    email = f"boqaudit-{uuid.uuid4().hex[:8]}@test.io"
    password = f"BoqAudit{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "BOQ Audit"},
    )
    assert reg.status_code in (200, 201), reg.text
    await promote_to_admin(email)
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _boq(client: AsyncClient, auth: dict[str, str]) -> tuple[str, str]:
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Audit {uuid.uuid4().hex[:6]}",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert proj.status_code == 201, proj.text
    pid = proj.json()["id"]
    boq = await client.post("/api/v1/boq/boqs/", json={"project_id": pid, "name": "Audit BOQ"}, headers=auth)
    assert boq.status_code == 201, boq.text
    return pid, boq.json()["id"]


@pytest.mark.asyncio
async def test_errors_follow_accept_language(client, auth):
    _, boq_id = await _boq(client, auth)
    de = {**auth, "Accept-Language": "de"}

    # not found
    missing = await client.get(f"/api/v1/boq/boqs/{uuid.uuid4()}", headers=de)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Leistungsverzeichnis nicht gefunden"

    # not locked (unlock of an unlocked bill)
    unlock = await client.post(f"/api/v1/boq/boqs/{boq_id}/unlock/", headers=de)
    assert unlock.status_code == 400
    assert unlock.json()["detail"] == "Das Leistungsverzeichnis ist nicht gesperrt."

    # budget needs a lock
    budget = await client.post(f"/api/v1/boq/boqs/{boq_id}/create-budget/", headers=de)
    assert budget.status_code == 400
    assert "gesperrt" in budget.json()["detail"]

    # locked
    lock = await client.post(f"/api/v1/boq/boqs/{boq_id}/lock/", headers=de)
    assert lock.status_code == 200, lock.text
    again = await client.post(f"/api/v1/boq/boqs/{boq_id}/lock/", headers=de)
    assert again.status_code == 409
    assert again.json()["detail"] == "Das Leistungsverzeichnis ist bereits gesperrt."


@pytest.mark.asyncio
async def test_cost_breakdown_lines_reconcile_to_grand_total(client, auth):
    _, boq_id = await _boq(client, auth)
    for i, (qty, rate) in enumerate([(3, "0.335"), (7, "13.337")], start=1):
        r = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/",
            json={
                "boq_id": boq_id,
                "ordinal": f"{i:02d}.001",
                "description": f"Item {i}",
                "unit": "m",
                "quantity": qty,
                "unit_rate": rate,
            },
            headers=auth,
        )
        assert r.status_code == 201, r.text
    for name, pct in (("Overhead", "7.77"), ("Profit", "3.33")):
        m = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/markups/",
            json={
                "name": name,
                "markup_type": "percentage",
                "percentage": pct,
                "category": "overhead",
                "sort_order": 1,
            },
            headers=auth,
        )
        assert m.status_code in (200, 201), m.text
    cb = await client.get(f"/api/v1/boq/boqs/{boq_id}/cost-breakdown/", headers=auth)
    assert cb.status_code == 200, cb.text
    body = cb.json()
    from decimal import Decimal

    parts = Decimal(str(body["direct_cost"])) + sum((Decimal(str(m["amount"])) for m in body["markups"]), Decimal("0"))
    assert parts == Decimal(str(body["grand_total"]))


@pytest.mark.asyncio
async def test_line_items_group_only_accepts_cost(client, auth):
    pid, _ = await _boq(client, auth)
    ok = await client.get("/api/v1/boq/line-items/", params={"project_id": pid, "group": "cost"}, headers=auth)
    assert ok.status_code == 200, ok.text
    bad = await client.get("/api/v1/boq/line-items/", params={"project_id": pid, "group": "section"}, headers=auth)
    assert bad.status_code == 422
