"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The BOQ editor's import button refuses a broken spreadsheet with a reason, not a 500.

``/import/smart/`` is what the Import button in the BOQ editor posts to. A file
named ``.xlsx`` that is not a readable workbook (renamed, truncated, corrupt)
fell through the structured parser to a raw text fallback that opened the
workbook unguarded, so ``zipfile.BadZipFile`` escaped as a 500 and the editor
showed "Import failed, Internal server error". An empty upload was refused, but
in an English string the editor could not translate.

Both now come back as a 400 with a coded ``detail`` (``code``, ``params``,
``message``), which the editor words in the reader's language through
``boq.import_error.<code>``. Nothing is written to the bill either way.

Run::

    cd backend
    python -m pytest tests/integration/test_boq_smart_import_refuses_a_broken_file_in_words.py -v
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    email = f"boqbroken-{unique}@test.io"
    password = f"BoqBroken{unique}9"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Broken File Tester", "role": "admin"},
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
        json={"name": f"Broken import {uuid.uuid4().hex[:6]}", "region": "Germany", "currency": "EUR"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": resp.json()["id"], "name": "Broken import", "description": ""},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _positions(client: AsyncClient, auth: dict[str, str], boq_id: str) -> list:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()["positions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        # A zip header with nothing a workbook needs behind it.
        b"PK\x03\x04 this is not really a workbook " + b"x" * 500,
        # A real zip archive that holds no workbook parts.
        b"PK\x05\x06" + b"\x00" * 18,
    ],
    ids=["zip-header-only", "empty-zip"],
)
async def test_a_file_that_is_not_a_workbook_is_a_coded_400(
    shared_client: AsyncClient, shared_auth: dict[str, str], content: bytes
) -> None:
    # Plain text renamed to .xlsx is not in this list on purpose: it is read as
    # the CSV it is, which is the more useful answer.
    boq_id = await _create_boq(shared_client, shared_auth)

    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/smart/",
        files={"file": ("estimate.xlsx", content, _XLSX)},
        headers=shared_auth,
    )

    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "spreadsheet_unreadable", detail
    assert detail["params"] == {}
    assert "save it again as .xlsx" in detail["message"]
    assert await _positions(shared_client, shared_auth, boq_id) == []


@pytest.mark.asyncio
async def test_an_empty_upload_is_a_coded_400(shared_client: AsyncClient, shared_auth: dict[str, str]) -> None:
    boq_id = await _create_boq(shared_client, shared_auth)

    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/smart/",
        files={"file": ("estimate.xlsx", b"", _XLSX)},
        headers=shared_auth,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "spreadsheet_empty_file"
    assert await _positions(shared_client, shared_auth, boq_id) == []
