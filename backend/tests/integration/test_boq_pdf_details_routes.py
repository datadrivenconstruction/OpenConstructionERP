# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GET and PUT /boq/projects/{id}/pdf-details/: round trip, access and unknown project.

The details are stored in project metadata, so the other keys there must survive
a PUT. Reading needs ``boq.read`` (a viewer has it), writing needs ``boq.update``
(a viewer does not), and a user outside the project reaches neither.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.teams.models  # noqa: F401
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
async def client(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
        yield ac


async def _user(client: AsyncClient, tag: str, role: str) -> tuple[str, dict[str, str]]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"{tag}-{uuid.uuid4().hex[:8]}@boq-pdf.io"
    password = f"BoqPdf{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": tag}
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return reg.json()["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def team(client):
    admin_id, admin = await _user(client, "owner", "admin")
    viewer_id, viewer = await _user(client, "viewer", "viewer")
    editor_id, editor = await _user(client, "editor", "editor")
    _, outsider = await _user(client, "outsider", "editor")
    project = await client.post("/api/v1/projects/", json={"name": "PDF details", "currency": "EUR"}, headers=admin)
    assert project.status_code in (200, 201), project.text
    project_id = project.json()["id"]
    for member_id, role in ((viewer_id, "viewer"), (editor_id, "member")):
        added = await client.post(
            f"/api/v1/projects/{project_id}/members/", json={"user_id": member_id, "role": role}, headers=admin
        )
        assert added.status_code in (200, 201), added.text
    return {"project_id": project_id, "admin": admin, "viewer": viewer, "editor": editor, "outsider": outsider}


def _url(project_id: str) -> str:
    return f"/api/v1/boq/projects/{project_id}/pdf-details/"


async def test_an_untouched_project_returns_empty_details(client, team) -> None:
    resp = await client.get(_url(team["project_id"]), headers=team["admin"])
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "client_name": "",
        "client_address": "",
        "project_number": "",
        "site_address": "",
        "payment_terms": "",
        "hidden_columns": [],
    }


async def test_put_then_get_round_trips_cleaned_values(client, team) -> None:
    body = {
        "client_name": "  Acme   Build\x00 GmbH ",
        "client_address": "Main St 1\r\n10115 Berlin",
        "project_number": "P-2026-07",
        "site_address": "Plot 4",
        "payment_terms": "30 days net\n2% discount in 10 days",
        "hidden_columns": ["rate", "bogus", "rate", "qty_unit"],
    }
    put = await client.put(_url(team["project_id"]), json=body, headers=team["editor"])
    assert put.status_code == 200, put.text
    expected = {
        **body,
        "client_name": "Acme Build GmbH",
        "client_address": "Main St 1\n10115 Berlin",
        "hidden_columns": ["rate", "qty_unit"],
    }
    assert put.json() == expected
    got = await client.get(_url(team["project_id"]), headers=team["viewer"])
    assert got.status_code == 200, got.text
    assert got.json() == expected


async def test_put_keeps_the_other_project_metadata(client, team) -> None:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    pid = uuid.UUID(team["project_id"])
    async with async_session_factory() as s:
        project = (await s.execute(select(Project).where(Project.id == pid))).scalar_one()
        project.metadata_ = {**(project.metadata_ or {}), "other_key": "kept"}
        await s.commit()
    put = await client.put(_url(team["project_id"]), json={"client_name": "Second"}, headers=team["admin"])
    assert put.status_code == 200, put.text
    async with async_session_factory() as s:
        project = (await s.execute(select(Project).where(Project.id == pid))).scalar_one()
        assert project.metadata_["other_key"] == "kept"
        assert project.metadata_["boq_pdf"]["client_name"] == "Second"


async def test_a_viewer_reads_but_cannot_write(client, team) -> None:
    before = await client.get(_url(team["project_id"]), headers=team["viewer"])
    assert before.status_code == 200
    put = await client.put(_url(team["project_id"]), json={"client_name": "Viewer"}, headers=team["viewer"])
    assert put.status_code == 403, put.text
    after = await client.get(_url(team["project_id"]), headers=team["viewer"])
    assert after.json() == before.json()


async def test_a_user_outside_the_project_reaches_neither_route(client, team) -> None:
    got = await client.get(_url(team["project_id"]), headers=team["outsider"])
    put = await client.put(_url(team["project_id"]), json={"client_name": "X"}, headers=team["outsider"])
    assert got.status_code == 404, got.text
    assert put.status_code == 404, put.text


async def test_an_unknown_project_is_404(client, team) -> None:
    missing = str(uuid.uuid4())
    got = await client.get(_url(missing), headers=team["admin"])
    put = await client.put(_url(missing), json={}, headers=team["admin"])
    assert got.status_code == 404, got.text
    assert put.status_code == 404, put.text


async def test_a_request_without_a_token_is_rejected(client, team) -> None:
    assert (await client.get(_url(team["project_id"]))).status_code in (401, 403)
