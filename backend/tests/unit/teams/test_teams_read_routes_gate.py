"""Every teams and roster read route checks project access at the route.

The service has always refused a stranger on these reads, and
``test_reading_a_project_you_are_not_on_answers_404`` pins that. What this
file adds is the route layer: each read now calls ``verify_project_access``
(or ``_gate_team_admin`` for a team id) before it reaches the service, so the
check survives a later service refactor. The third case switches the service
gates off and expects the same 404, which is the only way to tell the route
gate apart from the service gate over HTTP.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.teams.roster_service import RosterService
from app.modules.teams.service import TeamService
from tests.unit.teams.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_membership,
    make_project,
    make_restriction,
    make_team,
    make_user,
)

pytestmark = pytest.mark.asyncio


def _read_paths(project_id: uuid.UUID, team_id: uuid.UUID, entity_id: str) -> list[str]:
    return [
        f"{API_PREFIX}/?project_id={project_id}",
        f"{API_PREFIX}/project/{project_id}",
        f"{API_PREFIX}/project/{project_id}/access-matrix",
        f"{API_PREFIX}/project/{project_id}/restricted",
        f"{API_PREFIX}/project/{project_id}/validate",
        f"{API_PREFIX}/project/{project_id}/visibility/document/{entity_id}",
        f"{API_PREFIX}/{team_id}/members",
        f"{API_PREFIX}/{team_id}/visibility",
        f"{API_PREFIX}/project/{project_id}/roster",
        f"{API_PREFIX}/project/{project_id}/roster/summary",
        f"{API_PREFIX}/project/{project_id}/roster/candidates",
    ]


async def _arrange(session):
    owner = await make_user(session)
    member = await make_user(session)
    stranger = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site crew")
    await make_membership(session, team.id, member.id)
    entity_id = str(uuid.uuid4())
    await make_restriction(session, team.id, entity_id=entity_id)
    return member, stranger, _read_paths(project.id, team.id, entity_id)


async def test_a_stranger_gets_404_on_every_read(session) -> None:
    _member, stranger, paths = await _arrange(session)
    async with http_client(build_app(session, caller_id=stranger.id)) as client:
        for path in paths:
            resp = await client.get(path)
            assert resp.status_code == 404, (path, resp.status_code, resp.text)


async def test_a_plain_member_still_reads_every_route(session) -> None:
    member, _stranger, paths = await _arrange(session)
    async with http_client(build_app(session, caller_id=member.id)) as client:
        for path in paths:
            resp = await client.get(path)
            assert resp.status_code == 200, (path, resp.status_code, resp.text)


async def test_the_route_refuses_a_stranger_with_the_service_gates_off(session, monkeypatch) -> None:
    """Without the service gates the route gate alone must still answer 404."""

    async def _no_gate(self, project_id, actor_id) -> None:
        return None

    monkeypatch.setattr(TeamService, "_assert_project_access", _no_gate)
    monkeypatch.setattr(RosterService, "_assert_project_access", _no_gate)

    _member, stranger, paths = await _arrange(session)
    async with http_client(build_app(session, caller_id=stranger.id)) as client:
        for path in paths:
            resp = await client.get(path)
            assert resp.status_code == 404, (path, resp.status_code, resp.text)
