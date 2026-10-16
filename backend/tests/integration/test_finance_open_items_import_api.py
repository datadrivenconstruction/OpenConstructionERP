"""Open receivables and payables carried over from another system, through the API.

A company switching over brings what customers still owe it and what it still
owes its suppliers. The preview must match each row to a contact by tax number
or name and hand back control totals without writing. One bad row must keep
the whole file out. A clean import must leave the ageing showing exactly the
open amounts and the retention, and a second run of the same file must carry
nothing over twice.

Run:
    cd backend
    python -m pytest tests/integration/test_finance_open_items_import_api.py -v
"""

import asyncio
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = __import__("pytest").mark.asyncio

URL = "/api/v1/finance/open-items/import/"
CUTOVER = "2026-09-30"


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _login(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email, password = f"openitems-{unique}@test.io", f"Opening{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Opening"}
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


async def _ok(resp, code: int = 200):
    assert resp.status_code == code, resp.text
    return resp.json()


@pytest_asyncio.fixture(scope="module")
async def admin(client: AsyncClient) -> dict[str, str]:
    return await _login(client)


@pytest_asyncio.fixture(scope="module")
async def world(client: AsyncClient, admin: dict[str, str]) -> dict[str, str]:
    tag = uuid.uuid4().hex[:6].upper()
    ids: dict[str, str] = {"tag": tag}
    project = await _ok(
        await client.post("/api/v1/projects/", json={"name": f"Cut-over {tag}", "currency": "CAD"}, headers=admin),
        201,
    )
    ids["project"] = project["id"]
    for key, name, extra in (
        ("steel", f"Lakeshore Steel {tag}", {"vat_number": f"98765{tag}RT0001"}),
        ("homes", f"Lakeview Homes {tag}", {}),
        ("twin_a", f"Twin Trades {tag}", {}),
        ("twin_b", f"Twin Trades {tag}", {}),
    ):
        contact = await _ok(
            await client.post(
                "/api/v1/contacts/",
                json={
                    "contact_type": "subcontractor",
                    "company_name": name,
                    "primary_email": f"{key}-{tag.lower()}@test.io",
                    "country_code": "CA",
                    **extra,
                },
                headers=admin,
            ),
            201,
        )
        ids[key] = contact["id"]
    return ids


def _csv(world: dict[str, str], *rows: str) -> bytes:
    header = "direction,invoice_number,counterparty,tax_id,invoice_date,due_date,currency,total,tax,retention_held,open"
    return ("\n".join((header, *rows)) + "\n").encode("utf-8")


def _good_rows(world: dict[str, str]) -> tuple[str, ...]:
    tag = world["tag"]
    return (
        # A customer paid part of a progress claim; 1000 is held back as retention.
        f"AR,INV-{tag}-1,lakeview homes {tag},,2026-08-15,2026-09-14,CAD,11300.00,1300.00,1000.00,6300.00",
        # A supplier matched by tax number though the name is spelled differently.
        f"AP,LS-{tag}-1,Lakeshore Steel Ltd,98765 {tag} RT0001,2026-09-02,2026-10-02,CAD,8475.00,975.00,0,",
        # The same supplier by name, half paid.
        f"payable,LS-{tag}-2,Lakeshore Steel {tag},,2026-07-01,2026-07-31,,2000,0,0,1000",
    )


async def _post(client: AsyncClient, admin, world, body: bytes, *, dry_run: bool, cutover: str = CUTOVER):
    return await client.post(
        URL,
        params={"project_id": world["project"], "cutover_date": cutover, "dry_run": str(dry_run).lower()},
        files={"file": ("open_items.csv", body, "text/csv")},
        headers=admin,
    )


async def _invoices(client: AsyncClient, admin, world) -> list[dict]:
    data = await _ok(await client.get("/api/v1/finance/", params={"project_id": world["project"]}, headers=admin))
    return data["items"]


async def test_the_preview_matches_contacts_and_totals_without_writing(client, admin, world):
    data = await _ok(await _post(client, admin, world, _csv(world, *_good_rows(world)), dry_run=True))
    assert (data["ready"], data["errors"], data["imported"]) == (3, 0, 0)
    by_number = {r["invoice_number"]: r for r in data["rows"]}
    tag = world["tag"]
    assert by_number[f"INV-{tag}-1"]["contact_id"] == world["homes"]
    assert by_number[f"INV-{tag}-1"]["paid"] == "4000.00"
    assert by_number[f"LS-{tag}-1"]["contact_id"] == world["steel"]
    assert by_number[f"LS-{tag}-1"]["open"] == "8475.00"
    assert by_number[f"LS-{tag}-2"]["currency_code"] == "CAD"
    totals = {(t["direction"], t["currency_code"]): t for t in data["control_totals"]}
    assert totals[("payable", "CAD")]["count"] == 2
    assert totals[("payable", "CAD")]["open"] == "9475.00"
    assert totals[("receivable", "CAD")]["retention_held"] == "1000.00"
    assert await _invoices(client, admin, world) == []


async def test_one_bad_row_keeps_the_whole_file_out(client, admin, world):
    tag = world["tag"]
    rows = (
        *_good_rows(world),
        f"AP,TW-{tag}-1,Twin Trades {tag},,2026-09-01,,CAD,500,0,0,",
        f"AP,NO-{tag}-1,Nobody {tag},,2026-09-01,,CAD,500,0,0,",
        f"AR,LATE-{tag}-1,Lakeview Homes {tag},,2026-10-05,,CAD,500,0,0,",
    )
    data = await _ok(await _post(client, admin, world, _csv(world, *rows), dry_run=False))
    assert (data["imported"], data["errors"]) == (0, 3)
    messages = {r["invoice_number"]: r["message"] for r in data["rows"] if r["status"] == "error"}
    assert "Several contacts" in messages[f"TW-{tag}-1"]
    assert "No contact named" in messages[f"NO-{tag}-1"]
    assert "after the cut-over" in messages[f"LATE-{tag}-1"]
    codes = {r["invoice_number"]: r["code"] for r in data["rows"] if r["status"] == "error"}
    assert codes == {
        f"TW-{tag}-1": "contact_name_ambiguous",
        f"NO-{tag}-1": "contact_name_unknown",
        f"LATE-{tag}-1": "after_cutover",
    }
    assert await _invoices(client, admin, world) == []


async def test_the_import_leaves_the_ageing_with_the_open_amounts(client, admin, world):
    data = await _ok(await _post(client, admin, world, _csv(world, *_good_rows(world)), dry_run=False))
    assert (data["imported"], data["errors"]) == (3, 0)
    invoices = await _invoices(client, admin, world)
    assert {i["status"] for i in invoices if i["invoice_direction"] == "payable"} == {"approved"}
    assert {i["status"] for i in invoices if i["invoice_direction"] == "receivable"} == {"sent"}

    ageing = await _ok(
        await client.get(
            "/api/v1/finance/ageing/",
            params={"project_id": world["project"], "as_of": CUTOVER},
            headers=admin,
        )
    )
    groups = {(g["direction"], g["contact_id"]): g for g in ageing["groups"]}
    homes = groups[("receivable", world["homes"])]
    assert (homes["total_due"], homes["retention_held"]) == ("6300.00", "1000.00")
    steel = groups[("payable", world["steel"])]
    assert (steel["total_due"], steel["invoice_count"]) == ("9475.00", 2)


async def test_a_second_run_carries_nothing_over_twice(client, admin, world):
    data = await _ok(await _post(client, admin, world, _csv(world, *_good_rows(world)), dry_run=False))
    assert (data["imported"], data["exists"], data["errors"]) == (0, 3, 0)
    assert len(await _invoices(client, admin, world)) == 3


async def test_a_number_already_in_use_is_refused(client, admin, world):
    tag = world["tag"]
    await _ok(
        await client.post(
            "/api/v1/finance/",
            json={
                "project_id": world["project"],
                "contact_id": world["steel"],
                "invoice_direction": "payable",
                "invoice_number": f"LIVE-{tag}",
                "invoice_date": "2026-09-10",
                "currency_code": "CAD",
                "amount_subtotal": "100",
            },
            headers=admin,
        ),
        201,
    )
    row = f"AP,live-{tag.lower()},Lakeshore Steel {tag},,2026-09-10,,CAD,100,0,0,"
    data = await _ok(await _post(client, admin, world, _csv(world, row), dry_run=True))
    assert data["rows"][0]["status"] == "error"
    assert "already used" in data["rows"][0]["message"]


async def test_the_file_and_the_cutover_are_checked(client, admin, world):
    data = await _ok(
        await _post(client, admin, world, b"invoice_number,total\nX-1,100\n", dry_run=True),
    )
    assert set(data["missing_columns"]) == {"direction", "counterparty", "invoice_date"}
    resp = await _post(client, admin, world, _csv(world, *_good_rows(world)), dry_run=True, cutover="2999-01-01")
    assert resp.status_code == 422, resp.text
    template = await client.get("/api/v1/finance/open-items/template/", headers=admin)
    assert template.status_code == 200
    assert template.content.decode("utf-8-sig").startswith("direction,invoice_number,counterparty")
