"""Every spreadsheet import route reads a national bill the same way.

Three routes take a spreadsheet into a BOQ: ``/import/auto/`` (the import
dialog and project creation), ``/import/smart/`` (the BOQ editor's import
button) and the deprecated ``/import/excel/``. The last two used to keep their
own English and German header list, so a Croatian troskovnik the auto route
reads was sent to the AI path by the editor button, and when its headers were
English the smart path created every heading, section total, recap line and
tax line as a priced "pcs" position.

Each route here imports the same trimmed troskovnik into a fresh BOQ and is
held to one result: the section headings, the priced lines adding up to the
net total the file states, the running metre stored as ``lm``, and no total,
tax or recap line among the positions.

Run::

    cd backend
    python -m pytest tests/integration/test_boq_every_import_route_reads_a_national_bill.py -v
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.unit.test_boq_import_reads_a_national_bill_with_its_totals import (
    _NET_TOTAL,
    _SECTIONS,
    _troskovnik,
)


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
    email = f"boqnational-{unique}@test.io"
    password = f"BoqNational{unique}9"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "National Bill Tester", "role": "admin"},
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


async def _create_boq(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Troskovnik {uuid.uuid4().hex[:6]}",
            "description": "Project for the national bill import test",
            "region": "Croatia",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": resp.json()["id"], "name": "Troskovnik", "description": "Imported troskovnik"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["auto", "smart", "excel"])
async def test_the_troskovnik_imports_as_its_sections_and_priced_lines(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
    route: str,
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)

    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/{route}/",
        files={
            "file": (
                "troskovnik.xlsx",
                _troskovnik(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=shared_auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["errors"] == []
    assert not [w for w in body.get("warnings", []) if "file median" in str(w.get("message", ""))]
    assert any(w.get("code") == "summary_row_skipped" for w in body.get("warnings", []))

    resp = await shared_client.get(f"/api/v1/boq/boqs/{boq_id}", headers=shared_auth)
    assert resp.status_code == 200, resp.text
    positions = resp.json()["positions"]
    sections = [p for p in positions if p["unit"] in ("", "section")]
    items = [p for p in positions if p["unit"] not in ("", "section")]

    assert sorted(p["ordinal"] for p in sections) == sorted(ordinal for ordinal, _, _ in _SECTIONS)
    assert sorted(p["ordinal"] for p in items) == sorted(line[0] for _, _, lines in _SECTIONS for line in lines)
    total = sum(float(p["quantity"]) * float(p["unit_rate"]) for p in items)
    assert total == pytest.approx(_NET_TOTAL)
    assert {p["unit"] for p in items if p["ordinal"] == "3.1"} == {"lm"}
