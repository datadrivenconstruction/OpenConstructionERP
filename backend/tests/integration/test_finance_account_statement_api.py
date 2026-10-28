"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Statement of account through the API.

A customer with two invoices on two projects and a partial payment. The
statement must list them in date order with a running balance, bring earlier
movements forward, leave other customers and other currencies out, agree with
the ageing below it, come out as CSV, and show nothing to a user who cannot
open the projects.

Run:
    cd backend
    python -m pytest tests/integration/test_finance_account_statement_api.py -v
"""

import asyncio
import uuid
from datetime import date, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = __import__("pytest").mark.asyncio

TODAY = date.today()
URL = "/api/v1/finance/statement-of-account/"


def _d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _login(client: AsyncClient, *, admin: bool) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email, password = f"soa-{unique}@test.io", f"Statement{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Statement"}
    )
    assert reg.status_code == 201, reg.text
    if admin:
        from ._auth_helpers import promote_to_admin

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


@pytest_asyncio.fixture(scope="module")
async def admin(client: AsyncClient) -> dict[str, str]:
    return await _login(client, admin=True)


@pytest_asyncio.fixture(scope="module")
async def world(client: AsyncClient, admin: dict[str, str]) -> dict[str, str]:
    tag = uuid.uuid4().hex[:6]
    ids: dict[str, str] = {}
    for key in ("customer", "other"):
        contact = await _ok(
            await client.post(
                "/api/v1/contacts/",
                json={
                    "contact_type": "client",
                    "company_name": f"{key.title()} Homes {tag}",
                    "primary_email": f"{key}-{tag}@test.io",
                    "country_code": "CA",
                },
                headers=admin,
            ),
            201,
        )
        ids[key] = contact["id"]
    for key in ("one", "two"):
        project = await _ok(
            await client.post("/api/v1/projects/", json={"name": f"SoA {key} {tag}", "currency": "CAD"}, headers=admin),
            201,
        )
        ids[key] = project["id"]

    async def invoice(project: str, contact: str, total: str, issued: int, currency: str = "CAD") -> str:
        body = {
            "project_id": ids[project],
            "contact_id": ids[contact],
            "invoice_direction": "receivable",
            "invoice_date": _d(issued),
            "due_date": _d(issued + 30),
            "currency_code": currency,
            "amount_subtotal": total,
            "amount_total": total,
        }
        inv = await _ok(await client.post("/api/v1/finance/", json=body, headers=admin), 201)
        await _ok(await client.post(f"/api/v1/finance/{inv['id']}/approve/", headers=admin))
        return inv["id"]

    ids["old"] = await invoice("one", "customer", "1000.00", -60)
    await _ok(
        await client.post(
            "/api/v1/finance/payments/",
            json={"invoice_id": ids["old"], "payment_date": _d(-40), "amount": "400.00", "currency_code": "CAD"},
            headers=admin,
        ),
        201,
    )
    ids["new"] = await invoice("two", "customer", "250.00", -10)
    await invoice("one", "other", "999.00", -10)  # another customer
    await invoice("one", "customer", "777.00", -10, currency="USD")  # another currency
    return ids


async def test_lines_balance_and_brought_forward(
    client: AsyncClient, admin: dict[str, str], world: dict[str, str]
) -> None:
    st = await _ok(
        await client.get(
            URL, params={"contact_id": world["customer"], "currency": "cad", "date_from": _d(-30)}, headers=admin
        )
    )
    assert st["counterparty_name"].startswith("Customer Homes")
    assert st["opening_balance"] == "600.00"  # 1000 invoiced, 400 paid before the period
    assert [(line["kind"], line["balance"]) for line in st["lines"]] == [("invoice", "850.00")]
    assert st["closing_balance"] == "850.00"
    (ageing,) = st["ageing"]
    assert ageing["total_due"] == "850.00"


async def test_the_whole_history_without_a_start_date(
    client: AsyncClient, admin: dict[str, str], world: dict[str, str]
) -> None:
    st = await _ok(await client.get(URL, params={"contact_id": world["customer"], "currency": "CAD"}, headers=admin))
    assert st["opening_balance"] == "0.00" or st["opening_balance"] == "0"
    assert [line["kind"] for line in st["lines"]] == ["invoice", "payment", "invoice"]
    assert [line["balance"] for line in st["lines"]] == ["1000.00", "600.00", "850.00"]


async def test_csv(client: AsyncClient, admin: dict[str, str], world: dict[str, str]) -> None:
    resp = await client.get(
        URL, params={"contact_id": world["customer"], "currency": "CAD", "format": "csv"}, headers=admin
    )
    assert resp.status_code == 200, resp.text
    rows = resp.content.decode("utf-8-sig").splitlines()
    assert rows[0] == "date,type,reference,charge,credit,balance,currency"
    assert rows[1].split(",")[1] == "opening_balance"
    assert rows[-1].split(",")[1] == "closing_balance" and rows[-1].split(",")[5] == "850.00"


async def test_a_user_without_access_sees_an_empty_statement(client: AsyncClient, world: dict[str, str]) -> None:
    outsider = await _login(client, admin=False)
    resp = await client.get(URL, params={"contact_id": world["customer"], "currency": "CAD"}, headers=outsider)
    if resp.status_code == 403:
        return
    st = await _ok(resp)
    assert st["lines"] == [] and st["closing_balance"] in ("0", "0.00")
