"""Party visibility in the interface register, over HTTP.

Every user in these cases is a member of the project, so plain project access
would show them every interface. A hidden interface therefore proves the party
filter removed it, on each read path the router exposes: list, register,
work-package health, actions, the record itself and writes under it.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.interface_management.permissions import register_interface_management_permissions
from app.modules.interface_management.router import router as interface_router
from app.modules.teams.party_schemas import ProjectPartyCreate
from app.modules.teams.party_service import PartyService
from tests.unit.teams.conftest import http_client, make_membership, make_project, make_team, make_user

pytestmark = pytest.mark.asyncio

PREFIX = "/v1/interface-management"


@pytest.fixture(scope="module", autouse=True)
def _permissions() -> None:
    register_interface_management_permissions()


def _app(session, caller_id) -> FastAPI:
    app = FastAPI()
    app.include_router(interface_router, prefix=PREFIX)

    async def _session_override():
        yield session

    async def _user_override() -> str:
        return str(caller_id)

    async def _payload_override() -> dict[str, Any]:
        return {"sub": str(caller_id), "role": "editor", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


def _client(session, user) -> AsyncClient:
    return http_client(_app(session, user.id))


async def _create(session, project_id, user, reference: str) -> dict:
    async with _client(session, user) as c:
        r = await c.post(
            f"{PREFIX}/projects/{project_id}/interfaces",
            json={"reference": reference, "title": f"Interface {reference}"},
        )
    assert r.status_code == 201, r.text
    return r.json()


async def _world(session) -> dict:
    owner = await make_user(session)
    internal = await make_user(session)
    sub_a = await make_user(session)
    sub_b = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, is_default=True)
    for user in (internal, sub_a, sub_b):
        await make_membership(session, team.id, user.id)
    service = PartyService(session)
    host = await service.create_party(project.id, ProjectPartyCreate(name="EPC", role="contractor"), actor_id=owner.id)
    party_a = await service.create_party(project.id, ProjectPartyCreate(name="Sub A"), actor_id=owner.id)
    party_b = await service.create_party(project.id, ProjectPartyCreate(name="Sub B"), actor_id=owner.id)
    await service.bind_member(project.id, owner.id, host.id, actor_id=owner.id)
    await service.bind_member(project.id, sub_a.id, party_a.id, actor_id=owner.id)
    await service.bind_member(project.id, sub_b.id, party_b.id, actor_id=owner.id)
    return {
        "owner": owner,
        "internal": internal,
        "sub_a": sub_a,
        "sub_b": sub_b,
        "project": project,
        "party_a": party_a,
    }


async def _list_refs(session, user, project_id) -> set[str]:
    async with _client(session, user) as c:
        r = await c.get(f"{PREFIX}/projects/{project_id}/interfaces")
    assert r.status_code == 200, r.text
    return {row["reference"] for row in r.json()}


async def test_sub_a_does_not_see_b_interface_on_any_read_path(session) -> None:
    w = await _world(session)
    pid = w["project"].id
    mine = await _create(session, pid, w["sub_a"], "IF-A")
    theirs = await _create(session, pid, w["sub_b"], "IF-B")
    async with _client(session, w["sub_b"]) as c:
        r = await c.post(
            f"{PREFIX}/projects/{pid}/interfaces/{theirs['id']}/actions",
            json={"description": "B's action"},
        )
        assert r.status_code == 201, r.text
        b_action = r.json()

    assert await _list_refs(session, w["sub_a"], pid) == {"IF-A"}

    async with _client(session, w["sub_a"]) as c:
        assert (await c.get(f"{PREFIX}/projects/{pid}/interfaces/{theirs['id']}")).status_code == 404
        assert (await c.get(f"{PREFIX}/projects/{pid}/interfaces/{mine['id']}")).status_code == 200
        r = await c.patch(f"{PREFIX}/projects/{pid}/interfaces/{theirs['id']}", json={"title": "x"})
        assert r.status_code == 404
        assert (await c.delete(f"{PREFIX}/projects/{pid}/interfaces/{theirs['id']}")).status_code == 404
        r = await c.post(
            f"{PREFIX}/projects/{pid}/interfaces/{theirs['id']}/actions",
            json={"description": "probe"},
        )
        assert r.status_code == 404
        r = await c.patch(f"{PREFIX}/projects/{pid}/actions/{b_action['id']}", json={"description": "probe"})
        assert r.status_code == 404

        actions = (await c.get(f"{PREFIX}/projects/{pid}/actions")).json()
        assert b_action["id"] not in {a["id"] for a in actions}
        r = await c.get(f"{PREFIX}/projects/{pid}/actions", params={"interface_id": theirs["id"]})
        assert r.status_code == 404

        register = (await c.get(f"{PREFIX}/projects/{pid}/register")).json()
        health = (await c.get(f"{PREFIX}/projects/{pid}/work-package-health")).json()
    assert register["total"] == 1
    assert health["total"] == 1


async def test_internal_member_and_owner_see_both(session) -> None:
    w = await _world(session)
    pid = w["project"].id
    await _create(session, pid, w["sub_a"], "IF-A")
    await _create(session, pid, w["sub_b"], "IF-B")
    await _create(session, pid, w["internal"], "IF-I")

    for user in (w["owner"], w["internal"]):
        assert await _list_refs(session, user, pid) == {"IF-A", "IF-B", "IF-I"}
        async with _client(session, user) as c:
            assert (await c.get(f"{PREFIX}/projects/{pid}/register")).json()["total"] == 3
    # An interface entered by an internal member is not visible to external parties.
    assert await _list_refs(session, w["sub_b"], pid) == {"IF-B"}


async def test_project_without_parties_is_unchanged(session) -> None:
    owner = await make_user(session)
    member = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, is_default=True)
    await make_membership(session, team.id, member.id)
    created = await _create(session, project.id, owner, "IF-1")

    assert await _list_refs(session, member, project.id) == {"IF-1"}
    async with _client(session, member) as c:
        assert (await c.get(f"{PREFIX}/projects/{project.id}/interfaces/{created['id']}")).status_code == 200
        r = await c.patch(f"{PREFIX}/projects/{project.id}/interfaces/{created['id']}", json={"title": "edited"})
        assert r.status_code == 200


async def test_view_share_allows_read_but_not_write(session) -> None:
    w = await _world(session)
    pid = w["project"].id
    theirs = await _create(session, pid, w["sub_b"], "IF-B")
    await PartyService(session).share_record(
        pid, "interface", uuid.UUID(theirs["id"]), w["party_a"].id, "view", actor_id=w["sub_b"].id
    )

    assert await _list_refs(session, w["sub_a"], pid) == {"IF-B"}
    async with _client(session, w["sub_a"]) as c:
        assert (await c.get(f"{PREFIX}/projects/{pid}/interfaces/{theirs['id']}")).status_code == 200
        r = await c.patch(f"{PREFIX}/projects/{pid}/interfaces/{theirs['id']}", json={"title": "x"})
        assert r.status_code == 403
        r = await c.post(
            f"{PREFIX}/projects/{pid}/interfaces/{theirs['id']}/actions",
            json={"description": "probe"},
        )
        assert r.status_code == 403
