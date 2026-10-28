"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A held-back payment cannot be recorded through the cash-only route.

``POST /finance/payments/`` used to accept ``withholding_amount`` and
``withholding_release_date`` and drop both, so the payment was stored as if
nothing had been held back and the retention ledger never saw it. It now
refuses them and points to ``/invoices/{id}/record-payment/``, which splits and
checks the withholding against the invoice; a plain cash payment still goes
through.

Run:
    cd backend
    python -m pytest tests/integration/test_finance_payment_withholding_route.py -v
"""

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = __import__("pytest").mark.asyncio

TODAY = date.today().isoformat()


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def admin(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email, password = f"wh-{unique}@test.io", f"Withhold{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Withholding"}
    )
    assert reg.status_code == 201, reg.text
    from ._auth_helpers import promote_to_admin

    await promote_to_admin(email)
    data: dict = {}
    for attempt in range(3):
        data = (await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})).json()
        if data.get("access_token"):
            return {"Authorization": f"Bearer {data['access_token']}"}
        await asyncio.sleep(5 * (attempt + 1))
    raise AssertionError(f"login failed: {data}")


@pytest_asyncio.fixture(scope="module")
async def invoice_id(client: AsyncClient, admin: dict[str, str]) -> str:
    project = await client.post(
        "/api/v1/projects/", json={"name": f"Withholding {uuid.uuid4().hex[:6]}", "currency": "CAD"}, headers=admin
    )
    assert project.status_code == 201, project.text
    inv = await client.post(
        "/api/v1/finance/",
        json={
            "project_id": project.json()["id"],
            "invoice_direction": "payable",
            "invoice_date": TODAY,
            "currency_code": "CAD",
            "amount_subtotal": "1000.00",
            "amount_total": "1000.00",
            "retention_amount": "100.00",
        },
        headers=admin,
    )
    assert inv.status_code == 201, inv.text
    return inv.json()["id"]


def _payment(invoice_id: str, **extra: object) -> dict[str, object]:
    return {"invoice_id": invoice_id, "payment_date": TODAY, "amount": "450.00", "currency_code": "CAD", **extra}


async def test_a_withholding_is_refused_and_points_to_record_payment(
    client: AsyncClient, admin: dict[str, str], invoice_id: str
) -> None:
    resp = await client.post(
        "/api/v1/finance/payments/", json=_payment(invoice_id, withholding_amount="50.00"), headers=admin
    )
    assert resp.status_code == 422, resp.text
    assert f"/invoices/{invoice_id}/record-payment/" in resp.json()["detail"]


async def test_a_release_date_alone_is_refused_too(client: AsyncClient, admin: dict[str, str], invoice_id: str) -> None:
    resp = await client.post(
        "/api/v1/finance/payments/", json=_payment(invoice_id, withholding_release_date=TODAY), headers=admin
    )
    assert resp.status_code == 422, resp.text


async def test_a_foreign_claim_link_is_refused(client: AsyncClient, admin: dict[str, str], invoice_id: str) -> None:
    resp = await client.post(
        "/api/v1/finance/payments/", json=_payment(invoice_id, source_claim_id=str(uuid.uuid4())), headers=admin
    )
    assert resp.status_code == 422, resp.text


async def test_cash_still_goes_through_and_nothing_was_written_before(
    client: AsyncClient, admin: dict[str, str], invoice_id: str
) -> None:
    resp = await client.post("/api/v1/finance/payments/", json=_payment(invoice_id), headers=admin)
    assert resp.status_code == 201, resp.text
    listed = (await client.get("/api/v1/finance/payments/", params={"invoice_id": invoice_id}, headers=admin)).json()
    (payment,) = listed["items"]  # the refused attempts wrote nothing
    assert Decimal(payment["amount"]) == Decimal("450.00")
    assert Decimal(str(payment.get("withholding_amount") or "0")) == Decimal("0")
