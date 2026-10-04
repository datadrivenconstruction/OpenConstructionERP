# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The PDF route is the BOQ editor's PDF now, so it has to answer what the editor asks.

The editor's button downloads ``/export/pdf/?measurement_system=...&
include_resources=true``. Through the real route, against a euro project that
carries a dollar line:

* the dollar line prints in euro, and the lines of the section add up to the
  subtotal printed under them (printed raw they made 1500 under 1400);
* the resources under a line print only when asked, scaled to the line;
* the response says which language its labels are in, the project's.
"""

from __future__ import annotations

import asyncio
import io
import uuid

import pypdf
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"pdfeditor-{unique}@test.io"
    password = f"PdfEditor{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "PDF Editor Tester", "role": "admin"},
    )
    assert reg.status_code == 201, reg.text

    from ._auth_helpers import promote_to_admin

    await promote_to_admin(email)

    token = ""
    data: dict = {}
    for attempt in range(3):
        resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
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


async def _bill(client: AsyncClient, auth: dict[str, str], *, locale: str = "en") -> str:
    """A euro project in Ireland with one euro line and one dollar line, in one section."""
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"PDF editor {uuid.uuid4().hex[:6]}",
            "description": "",
            "region": "Ireland",
            "country_code": "IE",
            "classification_standard": "nrm",
            "currency": "EUR",
            "locale": locale,
            "fx_rates": [{"code": "USD", "rate": "0.90"}],
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]

    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": "Editor BOQ", "description": ""},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    boq_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01",
            "description": "Structure",
            "unit": "section",
            "quantity": 0,
            "unit_rate": 0,
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    section_id = resp.json()["id"]

    lines = [
        {"ordinal": "01.001", "description": "Formwork", "quantity": 10, "unit_rate": 50, "metadata": {}},
        {
            "ordinal": "01.002",
            "description": "Imported anchors",
            "quantity": 10,
            "unit_rate": 100,
            "metadata": {"currency": "USD"},
        },
    ]
    for line in lines:
        resp = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/",
            json={"boq_id": boq_id, "parent_id": section_id, "unit": "m3", **line},
            headers=auth,
        )
        assert resp.status_code == 201, resp.text
    return boq_id


async def _pdf(client: AsyncClient, auth: dict[str, str], boq_id: str, query: str = "") -> tuple[str, str]:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}/export/pdf/{query}", headers=auth)
    assert resp.status_code == 200, resp.text[:300]
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(resp.content)).pages)
    return text, resp.headers.get("content-language", "")


@pytest.mark.asyncio
async def test_a_dollar_line_prints_in_euro_and_the_section_adds_up(client: AsyncClient, auth: dict[str, str]) -> None:
    boq_id = await _bill(client, auth)

    structured = (await client.get(f"/api/v1/boq/boqs/{boq_id}/structured/", headers=auth)).json()
    assert float(structured["direct_cost"]) == pytest.approx(1400.0)

    text, language = await _pdf(client, auth, boq_id)

    assert "900.00" in text, "the dollar line is not printed in euro"
    assert "90.00" in text, "the dollar rate is not printed in euro"
    assert "1,000.00" not in text, "the dollar line printed its own figure under a euro heading"
    assert "1,400.00" in text
    assert language == "en"


@pytest.mark.asyncio
async def test_the_editor_query_is_honoured(client: AsyncClient, auth: dict[str, str]) -> None:
    boq_id = await _bill(client, auth, locale="de")

    text, language = await _pdf(client, auth, boq_id, "?measurement_system=imperial&include_resources=true")

    # The labels are German, and the response says so.
    assert "Freigegeben von:" in text
    assert language == "de"
    # m3 lines in cubic feet: 10 m3 is 353.15 ft3.
    assert "353.15" in text


@pytest.mark.asyncio
async def test_an_unknown_measurement_system_is_refused(client: AsyncClient, auth: dict[str, str]) -> None:
    boq_id = await _bill(client, auth)
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}/export/pdf/?measurement_system=cubits", headers=auth)
    assert resp.status_code == 422
