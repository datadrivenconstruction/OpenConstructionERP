# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project created by picking its region gets that country's separators in its PDF.

The create form posts ``region`` and leaves ``country_code`` empty unless a
geocoded address or an active country pack fills it. The PDF export used to
read ``country_code`` alone, so an Irish project picked from the region list
reached the generator with no country and was written in the euro's fallback
style, which is German: ``12.345,00 EUR`` on an Irish bill. The export now
settles the country from the region when the project has none.

The DACH project is the control: a macro region names no single country, so
its euro bill keeps the German style it always had.
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
    email = f"pdfregion-{unique}@test.io"
    password = f"PdfRegion{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "PDF Region Tester", "role": "admin"},
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


async def _pdf_for(
    client: AsyncClient,
    auth: dict[str, str],
    region: str,
    *,
    currency: str = "EUR",
    country_code: str | None = None,
) -> tuple[str, dict]:
    """Create a one-line project in ``region`` and return its PDF text and the project."""
    body = {
        "name": f"PDF region {region} {uuid.uuid4().hex[:6]}",
        "description": "PDF country test",
        "region": region,
        "classification_standard": "nrm",
        "currency": currency,
        "locale": "en",
    }
    if country_code is not None:
        body["country_code"] = country_code
    resp = await client.post("/api/v1/projects/", json=body, headers=auth)
    assert resp.status_code == 201, resp.text
    project = resp.json()

    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project["id"], "name": "Region BOQ", "description": ""},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    boq_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Blockwork",
            "unit": "m2",
            "quantity": 100.0,
            "unit_rate": 123.45,
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text

    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}/export/pdf", headers=auth)
    assert resp.status_code == 200, resp.text[:300]
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(resp.content)).pages)
    return text, project


@pytest.mark.asyncio
async def test_an_irish_project_picked_by_region_is_written_irish(client: AsyncClient, auth: dict[str, str]) -> None:
    text, project = await _pdf_for(client, auth, "Ireland")
    if (project.get("country_code") or "").upper() not in ("", "IE"):
        pytest.skip(f"an active country pack stamped {project['country_code']!r}; the region is not consulted then")
    assert "12,345.00" in text
    assert "12.345,00" not in text


@pytest.mark.asyncio
async def test_a_dach_project_keeps_the_german_style(client: AsyncClient, auth: dict[str, str]) -> None:
    text, project = await _pdf_for(client, auth, "DACH")
    if (project.get("country_code") or "").upper() not in ("", "DE", "AT"):
        pytest.skip(f"an active country pack stamped {project['country_code']!r}")
    assert "12.345,00" in text


@pytest.mark.asyncio
async def test_a_legacy_german_default_does_not_make_an_american_bill_german(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """A row written before v3319 holds ``DE`` whether or not anybody chose Germany.

    Stored here through the API as ``DE``, which is byte for byte what the old
    column default left on a US project created with no country. Before the
    export read the country, the dollar decided and the bill printed
    ``12,345.00 USD``; reading the stored ``DE`` at face value printed
    ``12.345,00 USD``. The region names the United States, so the bill is
    American again.
    """
    text, project = await _pdf_for(client, auth, "US", currency="USD", country_code="DE")
    assert (project.get("country_code") or "").upper() == "DE", "the legacy shape this test needs was not stored"
    assert "12,345.00" in text
    assert "12.345,00" not in text


@pytest.mark.asyncio
async def test_a_german_euro_project_stays_german(client: AsyncClient, auth: dict[str, str]) -> None:
    """The control for the test above: a ``DE`` nothing contradicts is believed."""
    text, project = await _pdf_for(client, auth, "DACH", currency="EUR", country_code="DE")
    assert (project.get("country_code") or "").upper() == "DE"
    assert "12.345,00" in text
