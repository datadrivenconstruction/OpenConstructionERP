# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The RFQ creation dialog creates an RFQ, and bad input answers 4xx, never 500.

Drives ``POST /api/v1/rfq-bidding/`` with exactly the body the create dialog
sends, then the BOQ-resource mode of the same dialog: the picked resources
become scope lines, an empty pick and a resource from another project's BOQ
are refused with a clear 4xx.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.rfq_bidding.models  # noqa: F401
import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()

    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def owner(http_client):
    email = f"rfq-{uuid.uuid4().hex[:8]}@rfq-authz.io"
    password = f"RfqAuthz{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "RFQ Owner"},
    )
    assert reg.status_code in (200, 201), reg.text

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role="admin"))
        await s.commit()

    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"RFQ {uuid.uuid4().hex[:6]}",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_the_dialog_body_creates_a_draft_rfq(http_client, owner) -> None:
    project_id = await _project(http_client, owner)
    body = {
        "project_id": project_id,
        "title": "Fourniture béton bloc A",
        "description": "Béton C30/37",
        "submission_deadline": "2026-12-15",
    }
    resp = await http_client.post("/api/v1/rfq-bidding/", json=body, headers=owner)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "draft"
    assert data["rfq_number"] == "RFQ-001"
    assert data["lines"] == []
    assert data["bids"] == []

    second = await http_client.post("/api/v1/rfq-bidding/", json=body, headers=owner)
    assert second.status_code == 201, second.text
    assert second.json()["rfq_number"] == "RFQ-002"


@pytest.mark.asyncio
async def test_the_dialog_body_without_optional_fields_creates_an_rfq(http_client, owner) -> None:
    project_id = await _project(http_client, owner)
    resp = await http_client.post(
        "/api/v1/rfq-bidding/",
        json={"project_id": project_id, "title": "Ductwork"},
        headers=owner,
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_an_unknown_project_answers_404_not_500(http_client, owner) -> None:
    resp = await http_client.post(
        "/api/v1/rfq-bidding/",
        json={"project_id": str(uuid.uuid4()), "title": "Ductwork"},
        headers=owner,
    )
    assert resp.status_code == 404, resp.text


async def _boq_with_resources(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": "Main BOQ", "description": ""},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    boq_id = resp.json()["id"]

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    rows = [
        (
            "01.001",
            "Wall C30/37",
            "m3",
            "10",
            [("Concrete C30/37", "material", "m3", "1"), ("Mason", "labor", "h", "2")],
        ),
        (
            "01.002",
            "Slab C30/37",
            "m3",
            "5",
            [("Concrete C30/37", "material", "m3", "1"), ("Crane", "machinery", "h", "0.5")],
        ),
    ]
    for ordinal, description, unit, quantity, resources in rows:
        resp = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/",
            json={"boq_id": boq_id, "ordinal": ordinal, "description": description, "unit": unit, "quantity": quantity},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        meta = {
            "resources": [
                {"name": n, "type": kind, "unit": u, "quantity": q, "unit_rate": "1"} for n, kind, u, q in resources
            ]
        }
        async with async_session_factory() as s:
            await s.execute(update(Position).where(Position.id == uuid.UUID(resp.json()["id"])).values(metadata_=meta))
            await s.commit()
    return boq_id


@pytest.mark.asyncio
async def test_picked_boq_resources_become_scope_lines(http_client, owner) -> None:
    project_id = await _project(http_client, owner)
    boq_id = await _boq_with_resources(http_client, owner, project_id)

    resp = await http_client.get(f"/api/v1/rfq-bidding/boq-resources/?boq_id={boq_id}", headers=owner)
    assert resp.status_code == 200, resp.text
    items = {i["name"]: i for i in resp.json()["items"]}
    assert set(items) == {"Concrete C30/37", "Mason", "Crane"}
    assert items["Concrete C30/37"]["quantity"] == "15.0000"
    assert items["Concrete C30/37"]["position_count"] == 2
    assert items["Crane"]["category"] == "machinery"

    picked = [items["Concrete C30/37"]["key"], items["Crane"]["key"]]
    resp = await http_client.post(
        "/api/v1/rfq-bidding/",
        json={"project_id": project_id, "title": "Concrete and crane", "boq_id": boq_id, "boq_resource_keys": picked},
        headers=owner,
    )
    assert resp.status_code == 201, resp.text
    lines = resp.json()["lines"]
    assert [(ln["line_no"], ln["description"], ln["unit"]) for ln in lines] == [
        (1, "Concrete C30/37", "m3"),
        (2, "Crane", "h"),
    ]
    assert lines[0]["quantity"] == "15.0000"
    assert lines[1]["quantity"] == "2.5000"


@pytest.mark.asyncio
async def test_an_empty_pick_is_refused_with_a_clear_message(http_client, owner) -> None:
    project_id = await _project(http_client, owner)
    boq_id = await _boq_with_resources(http_client, owner, project_id)
    resp = await http_client.post(
        "/api/v1/rfq-bidding/",
        json={"project_id": project_id, "title": "Nothing", "boq_id": boq_id, "boq_resource_keys": []},
        headers=owner,
    )
    assert resp.status_code == 422, resp.text
    assert "at least one BOQ resource" in resp.text


@pytest.mark.asyncio
async def test_resources_of_another_projects_boq_are_refused(http_client, owner) -> None:
    project_a = await _project(http_client, owner)
    project_b = await _project(http_client, owner)
    boq_b = await _boq_with_resources(http_client, owner, project_b)
    key = (await http_client.get(f"/api/v1/rfq-bidding/boq-resources/?boq_id={boq_b}", headers=owner)).json()["items"][
        0
    ]["key"]

    resp = await http_client.post(
        "/api/v1/rfq-bidding/",
        json={"project_id": project_a, "title": "Cross", "boq_id": boq_b, "boq_resource_keys": [key]},
        headers=owner,
    )
    assert resp.status_code == 422, resp.text
    assert "does not belong to this project" in resp.text

    resp = await http_client.post(
        "/api/v1/rfq-bidding/",
        json={"project_id": project_b, "title": "Stale", "boq_id": boq_b, "boq_resource_keys": ["0" * 20]},
        headers=owner,
    )
    assert resp.status_code == 422, resp.text
