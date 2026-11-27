"""Ball in court reassignment, status after approval and distribution list over the API."""

from __future__ import annotations

import uuid

import pytest

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


@pytest.mark.asyncio
async def test_distribution_list_is_saved_and_listed(db_session) -> None:  # noqa: F811
    owner = await _make_user(db_session)
    other = await _make_user(db_session)
    project = await _make_project(db_session, owner)
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
