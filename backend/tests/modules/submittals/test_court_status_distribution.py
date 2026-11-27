"""Ball in court reassignment, status after approval and distribution list over the API."""

from __future__ import annotations

import uuid

import pytest

from app.modules.submittals.models import Submittal
from tests.modules.submittals.test_submittal_register_api import (
    _client,
    _create,
    _make_project,
    _make_user,
    db_session,  # noqa: F401
)


async def _submitted(client, project: str, **fields) -> dict:
    created = await _create(client, project, **fields)
    r = await client.post(f"/v1/submittals/{created['id']}/submit/")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_ball_in_court_can_be_reassigned_and_persists(db_session) -> None:  # noqa: F811
    owner = await _make_user(db_session)
    other = await _make_user(db_session)
    project = await _make_project(db_session, owner)
    async with _client(db_session, owner) as client:
        sub = await _submitted(client, project, reviewer_id=owner)
        r = await client.patch(f"/v1/submittals/{sub['id']}", json={"ball_in_court": other})
        assert r.status_code == 200, r.text
        assert r.json()["ball_in_court"] == other
        listed = (await client.get("/v1/submittals/", params={"project_id": project})).json()
        row = next(x for x in listed if x["id"] == sub["id"])
        assert row["ball_in_court"] == other
        assert row["ball_in_court_name"]
        # A value that is not a user id is a clean 422, never a 500.
        bad = await client.patch(f"/v1/submittals/{sub['id']}", json={"ball_in_court": "not-a-user"})
        assert bad.status_code == 422, bad.text
        # Clearing hands the item to nobody.
        cleared = await client.patch(f"/v1/submittals/{sub['id']}", json={"ball_in_court": None})
        assert cleared.status_code == 200 and cleared.json()["ball_in_court"] is None


@pytest.mark.asyncio
async def test_status_after_approval_is_approved_in_response_and_list(db_session) -> None:  # noqa: F811
    owner = await _make_user(db_session)
    project = await _make_project(db_session, owner)
    async with _client(db_session, owner) as client:
        sub = await _submitted(client, project)
        r = await client.post(f"/v1/submittals/{sub['id']}/approve/", json={"notes": "ok", "code": "A"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "approved"
        assert body["ball_in_court"] is None
        assert body["review_outcome"] == "approved"
        listed = (await client.get("/v1/submittals/", params={"project_id": project, "status": "approved"})).json()
        assert [x["id"] for x in listed] == [sub["id"]]
        got = (await client.get(f"/v1/submittals/{sub['id']}")).json()
        assert got["status"] == "approved"
        # Closing is the last step: it needs its own action, a plain PATCH is refused.
        refused = await client.patch(f"/v1/submittals/{sub['id']}", json={"status": "closed"})
        assert refused.status_code == 403, refused.text
        closed = await client.post(f"/v1/submittals/{sub['id']}/close/")
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"
        assert closed.json()["review_outcome"] == "approved"
        again = await client.post(f"/v1/submittals/{sub['id']}/close/")
        assert again.status_code == 200 and again.json()["status"] == "closed"


@pytest.mark.asyncio
async def test_a_submittal_not_yet_decided_cannot_be_closed(db_session) -> None:  # noqa: F811
    owner = await _make_user(db_session)
    project = await _make_project(db_session, owner)
    async with _client(db_session, owner) as client:
        sub = await _submitted(client, project)
        r = await client.post(f"/v1/submittals/{sub['id']}/close/")
        assert r.status_code == 400, r.text


async def _join(session, project: str, user: str) -> None:
    from app.modules.teams.models import Team, TeamMembership

    team = Team(project_id=uuid.UUID(project), name="site team")
    session.add(team)
    await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=uuid.UUID(user), role="member"))
    await session.flush()


@pytest.mark.asyncio
async def test_distribution_list_is_saved_and_listed(db_session) -> None:  # noqa: F811
    owner = await _make_user(db_session)
    other = await _make_user(db_session)
    project = await _make_project(db_session, owner)
    await _join(db_session, project, other)
    async with _client(db_session, owner) as client:
        created = await _create(client, project, distribution_list=[owner, other, owner])
        assert created["distribution_list"] == [owner, other]
        r = await client.patch(f"/v1/submittals/{created['id']}", json={"distribution_list": [other]})
        assert r.status_code == 200, r.text
        assert r.json()["distribution_list"] == [other]
        listed = (await client.get("/v1/submittals/", params={"project_id": project})).json()
        assert listed[0]["distribution_list"] == [other]
        bad = await client.patch(f"/v1/submittals/{created['id']}", json={"distribution_list": [str(uuid.uuid4())[:5]]})
        assert bad.status_code == 422, bad.text


@pytest.mark.asyncio
async def test_validation_reports_people_who_cannot_open_the_project(db_session) -> None:  # noqa: F811
    from app.core.validation.rules import register_builtin_rules
    from app.modules.submittals.rules import register_submittal_register_rules
    from app.modules.submittals.service import SubmittalService

    register_builtin_rules()
    register_submittal_register_rules()
    owner = await _make_user(db_session)
    stranger = await _make_user(db_session)
    project = await _make_project(db_session, owner)
    async with _client(db_session, owner) as client:
        sub = await _submitted(client, project, reviewer_id=owner)
        ok = await SubmittalService(db_session).validate_submittal(uuid.UUID(sub["id"]))
        rows = {r["rule_id"]: r for r in ok["results"]}
        assert (
            rows["submittal.people_have_project_access"]["severity"]
            and rows["submittal.people_have_project_access"]["passed"]
        )
        assert not rows["submittal.distribution_present"]["passed"]
        # A row written before the guard existed: set it directly, the API now refuses it.
        row = await db_session.get(Submittal, uuid.UUID(sub["id"]))
        row.ball_in_court = stranger
        row.distribution_list = [owner, stranger]
        await db_session.flush()
        bad = await SubmittalService(db_session).validate_submittal(uuid.UUID(sub["id"]))
        rows = {r["rule_id"]: r for r in bad["results"]}
        assert not rows["submittal.people_have_project_access"]["passed"]
        assert rows["submittal.ball_in_court_assigned"]["passed"]
        assert rows["submittal.distribution_present"]["passed"]


@pytest.mark.asyncio
async def test_a_user_without_project_access_is_refused_on_the_distribution_list(db_session) -> None:  # noqa: F811
    owner = await _make_user(db_session)
    stranger = await _make_user(db_session)
    project = await _make_project(db_session, owner)
    async with _client(db_session, owner) as client:
        refused = await client.post(
            "/v1/submittals/",
            json={
                "project_id": project,
                "title": "Rebar",
                "submittal_type": "shop_drawing",
                "distribution_list": [stranger],
            },
        )
        assert refused.status_code == 422, refused.text
        assert "project" in refused.json()["detail"].lower()
        created = await _create(client, project)
        patched = await client.patch(f"/v1/submittals/{created['id']}", json={"distribution_list": [owner, stranger]})
        assert patched.status_code == 422, patched.text

        # A legacy draft that already lists the stranger cannot be submitted either.
        row = await db_session.get(Submittal, uuid.UUID(created["id"]))
        row.distribution_list = [stranger]
        await db_session.flush()
        submit = await client.post(f"/v1/submittals/{created['id']}/submit/")
        assert submit.status_code == 422, submit.text
