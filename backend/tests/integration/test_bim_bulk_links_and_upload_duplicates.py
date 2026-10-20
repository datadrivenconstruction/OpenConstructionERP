"""Bulk BOQ linking and same-file upload detection in the BIM hub.

* ``POST /bim_hub/links/bulk/`` links a whole selection to one BOQ position in
  one request (it used to take one request per element), skips elements that
  are already linked, and syncs the position quantity once.
* ``GET /bim_hub/upload-duplicates/`` finds models uploaded from a file with
  the same name and size, so the upload dialog can offer "new version of"
  instead of silently creating a duplicate model.

Run:
    cd backend
    python -m pytest tests/integration/test_bim_bulk_links_and_upload_duplicates.py -q
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncClient:
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"bulklink-{unique}@test.io"
    password = f"BulkLink{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Bulk Link Tester"},
    )
    assert reg.status_code == 201, reg.text

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/", json={"name": f"Bulk {uuid.uuid4().hex[:6]}", "currency": "EUR"}, headers=auth
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _model(client: AsyncClient, auth: dict[str, str], project_id: str, elements: list[dict]) -> tuple[str, list]:
    m = await client.post(
        "/api/v1/bim_hub/",
        json={"project_id": project_id, "name": "Frame", "version": "1", "status": "ready"},
        headers=auth,
    )
    assert m.status_code == 201, m.text
    model_id = m.json()["id"]
    e = await client.post(f"/api/v1/bim_hub/models/{model_id}/elements/", json={"elements": elements}, headers=auth)
    assert e.status_code == 201, e.text
    return model_id, e.json()["items"]


async def _position(client: AsyncClient, auth: dict[str, str], project_id: str, unit: str) -> tuple[str, str]:
    boq = await client.post(
        "/api/v1/boq/boqs/", json={"project_id": project_id, "name": f"BOQ {uuid.uuid4().hex[:6]}"}, headers=auth
    )
    assert boq.status_code == 201, boq.text
    boq_id = boq.json()["id"]
    pos = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={"boq_id": boq_id, "ordinal": "01.001", "description": "Beams", "unit": unit, "quantity": 0.0},
        headers=auth,
    )
    assert pos.status_code == 201, pos.text
    return boq_id, pos.json()["id"]


async def _position_row(client: AsyncClient, auth: dict[str, str], boq_id: str, pos_id: str) -> dict:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return next(p for p in resp.json()["positions"] if p["id"] == pos_id)


@pytest.mark.asyncio
async def test_bulk_link_creates_all_links_in_one_call_and_sums_length(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    project_id = await _project(client, auth)
    _model_id, elems = await _model(
        client,
        auth,
        project_id,
        [
            {"stable_id": f"B{i}", "element_type": "Structural Framing", "quantities": {"Length": 2.5}}
            for i in range(40)
        ],
    )
    boq_id, pos_id = await _position(client, auth, project_id, "m")
    ids = [e["id"] for e in elems]

    resp = await client.post(
        "/api/v1/bim_hub/links/bulk/",
        json={"boq_position_id": pos_id, "bim_element_ids": ids, "confidence": "high"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["created"] == 40
    assert resp.json()["skipped"] == 0

    links = await client.get(f"/api/v1/bim_hub/links/?boq_position_id={pos_id}", headers=auth)
    assert links.json()["total"] == 40
    row = await _position_row(client, auth, boq_id, pos_id)
    assert float(row["quantity"]) == pytest.approx(100.0)
    assert len(row["cad_element_ids"]) == 40


@pytest.mark.asyncio
async def test_bulk_link_skips_elements_already_linked(client: AsyncClient, auth: dict[str, str]) -> None:
    project_id = await _project(client, auth)
    _model_id, elems = await _model(
        client, auth, project_id, [{"stable_id": f"C{i}", "element_type": "Column"} for i in range(5)]
    )
    _boq_id, pos_id = await _position(client, auth, project_id, "pcs")
    ids = [e["id"] for e in elems]

    first = await client.post(
        "/api/v1/bim_hub/links/bulk/", json={"boq_position_id": pos_id, "bim_element_ids": ids[:3]}, headers=auth
    )
    assert first.json()["created"] == 3
    second = await client.post(
        "/api/v1/bim_hub/links/bulk/", json={"boq_position_id": pos_id, "bim_element_ids": ids}, headers=auth
    )
    assert second.status_code == 201, second.text
    assert second.json() == {"boq_position_id": pos_id, "created": 2, "skipped": 3}


@pytest.mark.asyncio
async def test_bulk_link_rejects_unknown_element(client: AsyncClient, auth: dict[str, str]) -> None:
    project_id = await _project(client, auth)
    _model_id, elems = await _model(client, auth, project_id, [{"stable_id": "D1", "element_type": "Wall"}])
    _boq_id, pos_id = await _position(client, auth, project_id, "pcs")

    resp = await client.post(
        "/api/v1/bim_hub/links/bulk/",
        json={"boq_position_id": pos_id, "bim_element_ids": [elems[0]["id"], str(uuid.uuid4())]},
        headers=auth,
    )
    assert resp.status_code == 404
    links = await client.get(f"/api/v1/bim_hub/links/?boq_position_id={pos_id}", headers=auth)
    assert links.json()["total"] == 0


@pytest.mark.asyncio
async def test_upload_duplicates_matches_name_and_size(client: AsyncClient, auth: dict[str, str]) -> None:
    from app.database import async_session_factory
    from app.modules.documents.models import Document

    project_id = await _project(client, auth)
    model_id, _ = await _model(client, auth, project_id, [{"stable_id": "E1", "element_type": "Wall"}])
    async with async_session_factory() as session:
        session.add(
            Document(
                project_id=uuid.UUID(project_id),
                name="tower.rvt",
                description="BIM model: tower",
                category="drawing",
                file_size=17_125_376,
                mime_type="application/rvt",
                file_path="bim/x/tower.rvt",
                version=1,
                uploaded_by="",
                tags=["bim"],
                metadata_={"source_module": "bim_hub", "source_id": model_id},
            )
        )
        await session.commit()

    base = f"/api/v1/bim_hub/upload-duplicates/?project_id={project_id}"
    hit = await client.get(f"{base}&file_name=tower.rvt&file_size=17125376", headers=auth)
    assert hit.status_code == 200, hit.text
    assert [i["model_id"] for i in hit.json()["items"]] == [model_id]

    other_size = await client.get(f"{base}&file_name=tower.rvt&file_size=17125377", headers=auth)
    assert other_size.json()["items"] == []
    other_name = await client.get(f"{base}&file_name=tower2.rvt&file_size=17125376", headers=auth)
    assert other_name.json()["items"] == []

    deleted = await client.delete(f"/api/v1/bim_hub/{model_id}", headers=auth)
    assert deleted.status_code == 204, deleted.text
    after_delete = await client.get(f"{base}&file_name=tower.rvt&file_size=17125376", headers=auth)
    assert after_delete.json()["items"] == []
