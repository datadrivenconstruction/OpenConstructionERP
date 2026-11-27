# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The invoice API names who sent an invoice for approval and who approved it.

One person codes a supplier invoice and sends it for approval, another
approves it. Reading the invoice, alone or in the list, shows both names and
when each step happened.

Run:
    cd backend
    python -m pytest tests/integration/test_finance_invoice_approval_trail_api.py -v
"""

import asyncio
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = __import__("pytest").mark.asyncio


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _login(client: AsyncClient, full_name: str) -> dict[str, str]:
    from ._auth_helpers import promote_to_admin

    unique = uuid.uuid4().hex[:8]
    email, password = f"trail-{unique}@test.io", f"Trail{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": full_name}
    )
    assert reg.status_code == 201, reg.text
    await promote_to_admin(email)
    data: dict = {}
    for attempt in range(3):
        data = (await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})).json()
        if data.get("access_token"):
            return {"Authorization": f"Bearer {data['access_token']}"}
        await asyncio.sleep(5 * (attempt + 1))
    raise AssertionError(f"login failed: {data}")


async def _ok(resp, code: int = 200):
    assert resp.status_code == code, resp.text
    return resp.json()


async def test_the_invoice_names_who_submitted_and_who_approved_it(client: AsyncClient) -> None:
    coder = await _login(client, "Project Engineer Trail")
    approver = await _login(client, "Senior Manager Trail")
    project = await _ok(
        await client.post("/api/v1/projects/", json={"name": "Approval trail", "currency": "USD"}, headers=coder), 201
    )
    invoice = await _ok(
        await client.post(
            "/api/v1/finance/",
            json={
                "project_id": project["id"],
                "invoice_direction": "payable",
                "invoice_number": f"S-{uuid.uuid4().hex[:6]}",
                "invoice_date": "2026-11-02",
                "currency_code": "USD",
                "amount_subtotal": "100.00",
                "tax_amount": "0",
            },
            headers=coder,
        ),
        201,
    )
    await _ok(await client.patch(f"/api/v1/finance/{invoice['id']}", json={"status": "pending"}, headers=coder))
    await _ok(await client.post(f"/api/v1/finance/{invoice['id']}/approve/", headers=approver))

    read = await _ok(await client.get(f"/api/v1/finance/{invoice['id']}", headers=approver))
    assert read["submitted_by_name"] == "Project Engineer Trail"
    assert read["approved_by_name"] == "Senior Manager Trail"
    assert read["submitted_at"] and read["approved_at"]
    assert read["released_at"] is None

    listed = await _ok(await client.get(f"/api/v1/finance/?project_id={project['id']}", headers=approver))
    [row] = [i for i in listed["items"] if i["id"] == invoice["id"]]
    assert (row["submitted_by_name"], row["approved_by_name"]) == ("Project Engineer Trail", "Senior Manager Trail")
