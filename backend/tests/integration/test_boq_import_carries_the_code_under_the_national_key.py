"""An imported bill's codes satisfy the project's national code rule.

An Indian bill of quantities carries the CPWD DSR item number of every line
in its code column. The importer filed it under ``code`` and the rule
``cpwd.code_required`` reads ``cpwd``, so every line of a correctly coded
bill failed it. A Romanian project is imported beside it to hold the other
side: its code column is the national norm code, and it must not be copied
under ``din276``.

Run::

    cd backend
    python -m pytest tests/integration/test_boq_import_carries_the_code_under_the_national_key.py -v
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

_INDIAN_BILL = (
    b"Item No.,DSR Code,Description,Unit,Quantity,Rate\n"
    b"A,,EARTH WORK,,,\n"
    b"1,2.8.1,Earth work in excavation by mechanical means,cum,120.5,215.40\n"
    b"2,13.1.1,Cement plaster 12 mm thick in single coat,sqm,340,268.15\n"
)

_ROMANIAN_BILL = (
    "Nr. crt.,Simbol,Denumire,U.M.,Cantitate,Preț unitar\n"
    "1,CA01A1,Beton simplu în fundații,mc,12.5,450.00\n"
    "2,TSA02D1,Săpătură manuală în spații limitate,mc,40,85.50\n"
).encode()


@pytest_asyncio.fixture(scope="module")
async def shared_client():
    app = create_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def shared_auth(shared_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"boqcodekey-{unique}@test.io"
    password = f"BoqCodeKey{unique}9"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Code Key Tester", "role": "admin"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from ._auth_helpers import promote_to_admin

    await promote_to_admin(email)

    token = ""
    data: dict = {}
    for attempt in range(3):
        resp = await shared_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


async def _create_boq(client: AsyncClient, auth: dict[str, str], *, country: str, currency: str) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Code key {country} {uuid.uuid4().hex[:6]}",
            "description": "Project for the national code key import test",
            "region": country,
            "country_code": country,
            "currency": currency,
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": resp.json()["id"], "name": "Bill", "description": "Imported bill"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _import(client: AsyncClient, auth: dict[str, str], boq_id: str, route: str, content: bytes) -> dict:
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/{route}/",
        files={"file": ("bill.csv", content, "text/csv")},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _lines(client: AsyncClient, auth: dict[str, str], boq_id: str) -> list[dict]:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return [p for p in resp.json()["positions"] if p["unit"] not in ("", "section")]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["auto", "excel"])
async def test_an_indian_bill_carries_its_dsr_codes_under_cpwd(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
    route: str,
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth, country="IN", currency="INR")
    body = await _import(shared_client, shared_auth, boq_id, route, _INDIAN_BILL)
    assert body["errors"] == []

    lines = await _lines(shared_client, shared_auth, boq_id)
    assert sorted((p["classification"] or {}).get("cpwd") for p in lines) == ["13.1.1", "2.8.1"]

    report = body.get("validation_report")
    if report:
        failed = [
            r
            for r in report.get("results", [])
            if r.get("rule_id") == "cpwd.code_required" and not r.get("passed", True)
        ]
        assert failed == []


@pytest.mark.asyncio
async def test_a_romanian_bill_keeps_its_norm_code_out_of_din276(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth, country="RO", currency="RON")
    body = await _import(shared_client, shared_auth, boq_id, "auto", _ROMANIAN_BILL)
    assert body["errors"] == []

    lines = await _lines(shared_client, shared_auth, boq_id)
    classifications = [p["classification"] or {} for p in lines]
    assert sorted(c.get("code") for c in classifications) == ["CA01A1", "TSA02D1"]
    assert [c for c in classifications if "din276" in c] == []
