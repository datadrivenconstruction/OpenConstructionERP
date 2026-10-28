"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠AR / AP ageing through the API, per legal entity.

Two projects belong to two legal entities. The report must age each invoice
on its open balance (a partial payment counts), keep holdback out of what is
due, split by entity, and never show a project the caller cannot read, even
when the caller filters by the entity that owns it.

Run:
    cd backend
    python -m pytest tests/integration/test_finance_ageing_api.py -v
"""

import asyncio
import uuid
from datetime import date, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = __import__("pytest").mark.asyncio

TODAY = date.today()


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
    email, password = f"ageing-{unique}@test.io", f"Ageing{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Ageing"}
    )
    assert reg.status_code == 201, reg.text
    if admin:
        from ._auth_helpers import promote_to_admin

        await promote_to_admin(email)
    for attempt in range(3):
        data = (await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})).json()
        if data.get("access_token"):
            return {"Authorization": f"Bearer {data['access_token']}"}
        await asyncio.sleep(5 * (attempt + 1))
    raise AssertionError(f"login failed: {data}")


@pytest_asyncio.fixture(scope="module")
async def admin(client: AsyncClient) -> dict[str, str]:
    return await _login(client, admin=True)


async def _ok(resp, code: int = 200):
    assert resp.status_code == code, resp.text
    return resp.json()


@pytest_asyncio.fixture(scope="module")
async def world(client: AsyncClient, admin: dict[str, str]) -> dict[str, str]:
    """Two entities, one project each, invoices in several states."""
    tag = uuid.uuid4().hex[:6].upper()
    ids: dict[str, str] = {}
    for key in ("north", "south"):
        project = await _ok(
            await client.post(
                "/api/v1/projects/", json={"name": f"Ageing {key} {tag}", "currency": "CAD"}, headers=admin
            ),
            201,
        )
        entity = await _ok(
            await client.post(
                "/api/v1/legal-entities/entities/",
                json={
                    "code": f"{key[:1].upper()}{tag}",
                    "name": f"{key.title()} Developments Inc.",
                    "country_code": "CA",
                    "subdivision_code": "CA-ON",
                    "functional_currency": "CAD",
                },
                headers=admin,
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
        ids[f"{key}_project"], ids[f"{key}_entity"] = project["id"], entity["id"]

    async def invoice(
        project: str, direction: str, total: str, due: int, retention: str = "0", approve: bool = True
    ) -> str:
        body = {
            "project_id": ids[project],
            "invoice_direction": direction,
            "invoice_date": _d(due - 30),
            "due_date": _d(due),
            "currency_code": "CAD",
            "amount_subtotal": total,
            "amount_total": total,
            "retention_amount": retention,
        }
        inv = await _ok(await client.post("/api/v1/finance/", json=body, headers=admin), 201)
        if approve:
            await _ok(await client.post(f"/api/v1/finance/{inv['id']}/approve/", headers=admin))
        return inv["id"]

    # North AP: 1000 due 45 days ago, 400 of it paid; 2000 not due yet with 200 holdback.
    ids["late"] = await invoice("north_project", "payable", "1000.00", -45)
    await _ok(
        await client.post(
            "/api/v1/finance/payments/",
            json={"invoice_id": ids["late"], "payment_date": _d(-10), "amount": "400.00", "currency_code": "CAD"},
            headers=admin,
        ),
        201,
    )
    ids["holdback"] = await invoice("north_project", "payable", "2000.00", 20, retention="200.00")
    await invoice("north_project", "payable", "999.00", -5, approve=False)  # a draft
    # South AR: 500 due 100 days ago.
    ids["ar"] = await invoice("south_project", "receivable", "500.00", -100)
    return ids


async def test_open_balances_are_aged_per_entity(
    client: AsyncClient, admin: dict[str, str], world: dict[str, str]
) -> None:
    report = await _ok(
        await client.get("/api/v1/finance/ageing/", params={"legal_entity_id": world["north_entity"]}, headers=admin)
    )
    assert report["buckets"] == ["current", "1_30", "31_60", "61_90", "over_90"]
    (total,) = report["totals"]
    assert total["legal_entity_id"] == world["north_entity"]
    assert total["legal_entity_name"].endswith("North Developments Inc.")
    assert total["direction"] == "payable"
    assert total["buckets"]["31_60"] == "600.00"  # 1000 less the 400 paid
    assert total["buckets"]["current"] == "1800.00"  # 2000 less its 200 holdback
    assert total["total_due"] == "2400.00"
    assert total["retention_held"] == "200.00"
    assert report["drafts_excluded"] == 1
    lines = {line["invoice_id"]: line for group in report["groups"] for line in group["invoices"]}
    assert lines[world["late"]]["paid"] == "400.00"
    assert lines[world["late"]]["days_past_due"] == 45


async def test_direction_and_entity_filters_do_not_leak(
    client: AsyncClient, admin: dict[str, str], world: dict[str, str]
) -> None:
    ar = await _ok(
        await client.get(
            "/api/v1/finance/ageing/",
            params={"direction": "receivable", "legal_entity_id": world["south_entity"]},
            headers=admin,
        )
    )
    (total,) = ar["totals"]
    assert total["buckets"]["over_90"] == "500.00"
    assert {g["direction"] for g in ar["groups"]} == {"receivable"}


async def test_a_user_without_access_sees_nothing_even_by_entity(client: AsyncClient, world: dict[str, str]) -> None:
    outsider = await _login(client, admin=False)
    resp = await client.get(
        "/api/v1/finance/ageing/", params={"legal_entity_id": world["north_entity"]}, headers=outsider
    )
    if resp.status_code == 403:
        return  # no finance.read at all is also a correct answer
    report = await _ok(resp)
    assert report["groups"] == [] and report["totals"] == []


async def test_the_invoice_list_narrows_to_one_legal_entity(
    client: AsyncClient, admin: dict[str, str], world: dict[str, str]
) -> None:
    north = await _ok(
        await client.get(
            "/api/v1/finance/", params={"legal_entity_id": world["north_entity"], "limit": 100}, headers=admin
        )
    )
    assert {i["project_id"] for i in north["items"]} == {world["north_project"]}
    assert north["total"] == 3  # two approved and the draft
    named = await _ok(
        await client.get(
            "/api/v1/finance/",
            params={"legal_entity_id": world["south_entity"], "project_id": world["north_project"]},
            headers=admin,
        )
    )
    assert named == {"items": [], "total": 0, "offset": 0, "limit": 50}


async def test_the_entity_filter_never_widens_what_a_user_can_see(client: AsyncClient, world: dict[str, str]) -> None:
    outsider = await _login(client, admin=False)
    resp = await client.get("/api/v1/finance/", params={"legal_entity_id": world["north_entity"]}, headers=outsider)
    if resp.status_code == 403:
        return
    assert (await _ok(resp))["items"] == []


async def test_a_bad_cutoff_is_refused(client: AsyncClient, admin: dict[str, str]) -> None:
    resp = await client.get("/api/v1/finance/ageing/", params={"as_of": "15/10/2026"}, headers=admin)
    assert resp.status_code == 422


async def test_a_project_without_an_entity_ages_under_the_default_one(
    client: AsyncClient, admin: dict[str, str]
) -> None:
    # The legal entities module answers "the default entity" for a project
    # that names none; ageing and payment runs must read it the same way.
    listed = (await client.get("/api/v1/legal-entities/entities/", headers=admin)).json()["items"]
    previous = next((e["id"] for e in listed if e["is_default"]), None)
    tag = uuid.uuid4().hex[:6].upper()
    default = await _ok(
        await client.post(
            "/api/v1/legal-entities/entities/",
            json={
                "code": f"D{tag}",
                "name": "Default Holdings Inc.",
                "country_code": "CA",
                "subdivision_code": "CA-ON",
                "functional_currency": "CAD",
                "is_default": True,
            },
            headers=admin,
        ),
        201,
    )
    try:
        project = await _ok(
            await client.post(
                "/api/v1/projects/", json={"name": f"Unassigned {tag}", "currency": "CAD"}, headers=admin
            ),
            201,
        )
        body = {
            "project_id": project["id"],
            "invoice_direction": "payable",
            "invoice_date": _d(-40),
            "due_date": _d(-10),
            "currency_code": "CAD",
            "amount_subtotal": "250.00",
            "amount_total": "250.00",
        }
        inv = await _ok(await client.post("/api/v1/finance/", json=body, headers=admin), 201)
        await _ok(await client.post(f"/api/v1/finance/{inv['id']}/approve/", headers=admin))

        report = await _ok(
            await client.get("/api/v1/finance/ageing/", params={"project_id": project["id"]}, headers=admin)
        )
        (total,) = report["totals"]
        assert total["legal_entity_id"] == default["id"]
        by_entity = await _ok(
            await client.get("/api/v1/finance/ageing/", params={"legal_entity_id": default["id"]}, headers=admin)
        )
        lines = {line["invoice_id"] for g in by_entity["groups"] for line in g["invoices"]}
        assert inv["id"] in lines
    finally:
        if previous:
            await client.patch(f"/api/v1/legal-entities/entities/{previous}", json={"is_default": True}, headers=admin)
        else:
            await client.patch(
                f"/api/v1/legal-entities/entities/{default['id']}", json={"is_default": False}, headers=admin
            )
