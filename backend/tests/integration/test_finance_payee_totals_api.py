"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Supplier payments of a legal entity over a year, as the T5018 needs them.

An Ontario entity pays a steel subcontractor on two projects and a small
supplier once, and pays the steel subcontractor again in January of the next
year. The report must add up the first year per payee with the payee's
business number and address, name the T5018 with its due date, mark the payee
under the 500 dollar threshold, count a reportable payee without a business
number, come out as CSV, and show nothing to a user who cannot open the
projects.

Run:
    cd backend
    python -m pytest tests/integration/test_finance_payee_totals_api.py -v
"""

import asyncio
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = __import__("pytest").mark.asyncio

URL = "/api/v1/finance/payee-totals/"
YEAR = {"date_from": "2025-01-01", "date_to": "2025-12-31"}


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _login(client: AsyncClient, *, admin: bool) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email, password = f"t5018-{unique}@test.io", f"Payees{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Payees"}
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
    tag = uuid.uuid4().hex[:6].upper()
    ids: dict[str, str] = {}
    entity = await _ok(
        await client.post(
            "/api/v1/legal-entities/entities/",
            json={
                "code": f"T{tag}",
                "name": "Lakeshore Developments Inc.",
                "country_code": "CA",
                "subdivision_code": "CA-ON",
                "functional_currency": "CAD",
                "tax_id": "123456789RT0001",
            },
            headers=admin,
        ),
        201,
    )
    ids["entity"] = entity["id"]
    for key in ("one", "two"):
        project = await _ok(
            await client.post(
                "/api/v1/projects/", json={"name": f"T5018 {key} {tag}", "currency": "CAD"}, headers=admin
            ),
            201,
        )
        await _ok(
            await client.put(
                f"/api/v1/legal-entities/projects/{project['id']}/entity",
                json={"legal_entity_id": entity["id"]},
                headers=admin,
            )
        )
        ids[key] = project["id"]
    for key, extra in (
        (
            "steel",
            {
                "vat_number": "987654321RT0001",
                "address": {"street": "1 King St W", "postal_code": "M5H 1A1", "city": "Toronto"},
            },
        ),
        ("small", {"vat_number": "111222333RT0001"}),
        ("nobn", {}),
    ):
        contact = await _ok(
            await client.post(
                "/api/v1/contacts/",
                json={
                    "contact_type": "subcontractor",
                    "company_name": f"{key.title()} Works {tag}",
                    "primary_email": f"{key}-{tag.lower()}@test.io",
                    "country_code": "CA",
                    **extra,
                },
                headers=admin,
            ),
            201,
        )
        ids[key] = contact["id"]

    async def paid(project: str, contact: str, total: str, payments: list[tuple[str, str]]) -> None:
        inv = await _ok(
            await client.post(
                "/api/v1/finance/",
                json={
                    "project_id": ids[project],
                    "contact_id": ids[contact],
                    "invoice_direction": "payable",
                    "invoice_date": payments[0][0],
                    "currency_code": "CAD",
                    "amount_subtotal": total,
                    "amount_total": total,
                },
                headers=admin,
            ),
            201,
        )
        await _ok(await client.post(f"/api/v1/finance/{inv['id']}/approve/", headers=admin))
        for on, amount in payments:
            await _ok(
                await client.post(
                    "/api/v1/finance/payments/",
                    json={"invoice_id": inv["id"], "payment_date": on, "amount": amount, "currency_code": "CAD"},
                    headers=admin,
                ),
                201,
            )

    await paid("one", "steel", "10000.00", [("2025-03-10", "6000.00"), ("2026-01-15", "4000.00")])
    await paid("two", "steel", "2500.00", [("2025-11-30", "2500.00")])
    await paid("one", "small", "300.00", [("2025-06-01", "300.00")])
    await paid("two", "nobn", "900.00", [("2025-07-01", "900.00")])
    return ids


async def test_payees_are_added_up_for_the_year_with_their_business_numbers(
    client: AsyncClient, admin: dict[str, str], world: dict[str, str]
) -> None:
    report = await _ok(await client.get(URL, params={"legal_entity_id": world["entity"], **YEAR}, headers=admin))
    assert report["payee_return"]["form"] == "T5018"
    assert report["payee_return"]["due_on"] == "2026-06-30"
    assert report["legal_entity_tax_id"] == "123456789RT0001"
    by_payee = {item["contact_id"]: item for item in report["items"]}
    steel = by_payee[world["steel"]]
    assert steel["total"] == "8500.00"  # 6000 in March and 2500 in November; January 2026 is next year
    assert (steel["payment_count"], steel["project_count"]) == (2, 2)
    assert steel["payee_tax_id"] == "987654321RT0001"
    assert steel["payee_address"] == "1 King St W, M5H 1A1, Toronto"
    assert by_payee[world["small"]]["below_threshold"] is True
    assert by_payee[world["nobn"]]["below_threshold"] is False
    assert (report["reportable_count"], report["missing_tax_id"]) == (2, 1)


async def test_csv(client: AsyncClient, admin: dict[str, str], world: dict[str, str]) -> None:
    resp = await client.get(URL, params={"legal_entity_id": world["entity"], "format": "csv", **YEAR}, headers=admin)
    assert resp.status_code == 200, resp.text
    rows = resp.content.decode("utf-8-sig").splitlines()
    assert rows[0] == "payee,tax_id,address,country,currency,total,paid,refunded,payments,reportable"
    assert any(row.startswith("Steel Works") and ",8500.00," in row and row.endswith(",yes") for row in rows)
    assert "T5018" in resp.headers["content-disposition"]


async def test_a_reversed_period_and_an_unknown_entity_are_refused(
    client: AsyncClient, admin: dict[str, str], world: dict[str, str]
) -> None:
    reversed_period = {"date_from": "2025-12-31", "date_to": "2025-01-01"}
    resp = await client.get(URL, params={"legal_entity_id": world["entity"], **reversed_period}, headers=admin)
    assert resp.status_code == 422
    resp = await client.get(URL, params={"legal_entity_id": str(uuid.uuid4()), **YEAR}, headers=admin)
    assert resp.status_code == 404


async def test_a_user_without_access_sees_no_payee(client: AsyncClient, world: dict[str, str]) -> None:
    outsider = await _login(client, admin=False)
    resp = await client.get(URL, params={"legal_entity_id": world["entity"], **YEAR}, headers=outsider)
    if resp.status_code == 403:
        return
    assert (await _ok(resp))["items"] == []
