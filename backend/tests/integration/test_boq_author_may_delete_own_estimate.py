# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A viewer can delete the estimate they started, and only that one.

``boq.create`` is open to viewers (issue #101) while ``boq.delete`` needs an
editor, so a viewer could start an estimate and never remove it again. A BOQ
now records who started it, and its author may delete it whatever their role.
Everybody else still needs ``boq.delete``: a viewer cannot delete a colleague's
estimate, and an editor's rights are unchanged.

All users here are members of one project, so the project access guard passes
and the role and authorship rules are what is under test.
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

    email = f"{tag}-{uuid.uuid4().hex[:8]}@boq-author.io"
    password = f"BoqAuthor{uuid.uuid4().hex[:6]}9"
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
    other_viewer_id, other_viewer = await _user(client, "viewer2", "viewer")
    editor_id, editor = await _user(client, "editor", "editor")
    project = await client.post("/api/v1/projects/", json={"name": "Author rule", "currency": "EUR"}, headers=admin)
    assert project.status_code in (200, 201), project.text
    project_id = project.json()["id"]
    for member_id, role in ((viewer_id, "viewer"), (other_viewer_id, "viewer"), (editor_id, "member")):
        added = await client.post(
            f"/api/v1/projects/{project_id}/members/", json={"user_id": member_id, "role": role}, headers=admin
        )
        assert added.status_code in (200, 201), added.text
    return {
        "project_id": project_id,
        "admin": admin,
        "viewer": viewer,
        "viewer_id": viewer_id,
        "other_viewer": other_viewer,
        "editor": editor,
    }


async def _new_boq(client: AsyncClient, team: dict, who: str) -> dict:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": team["project_id"], "name": f"Estimate {uuid.uuid4().hex[:6]}"},
        headers=team[who],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_a_viewer_can_still_start_an_estimate_and_is_recorded_as_its_author(client, team) -> None:
    boq = await _new_boq(client, team, "viewer")
    assert boq["created_by"] == team["viewer_id"]


async def test_a_viewer_deletes_the_estimate_they_started(client, team) -> None:
    boq = await _new_boq(client, team, "viewer")
    resp = await client.delete(f"/api/v1/boq/boqs/{boq['id']}", headers=team["viewer"])
    assert resp.status_code == 204, resp.text
    gone = await client.get(f"/api/v1/boq/boqs/{boq['id']}", headers=team["admin"])
    assert gone.status_code == 404


async def test_a_viewer_cannot_delete_someone_elses_estimate(client, team) -> None:
    by_admin = await _new_boq(client, team, "admin")
    by_colleague = await _new_boq(client, team, "other_viewer")
    for boq in (by_admin, by_colleague):
        resp = await client.delete(f"/api/v1/boq/boqs/{boq['id']}", headers=team["viewer"])
        assert resp.status_code == 403, resp.text


async def test_an_editor_deletes_any_estimate_as_before(client, team) -> None:
    boq = await _new_boq(client, team, "other_viewer")
    resp = await client.delete(f"/api/v1/boq/boqs/{boq['id']}", headers=team["editor"])
    assert resp.status_code == 204, resp.text


async def test_a_duplicate_belongs_to_whoever_made_it(client, team) -> None:
    source = await _new_boq(client, team, "admin")
    copy = await client.post(f"/api/v1/boq/boqs/{source['id']}/duplicate/", headers=team["viewer"])
    assert copy.status_code == 201, copy.text
    assert copy.json()["created_by"] == team["viewer_id"]
    resp = await client.delete(f"/api/v1/boq/boqs/{copy.json()['id']}", headers=team["viewer"])
    assert resp.status_code == 204, resp.text
