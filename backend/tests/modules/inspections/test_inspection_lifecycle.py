"""Inspection lifecycle, project scoping and checklist-validation tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

BASE = "/api/v1/inspections/"


def _body(project_id: str, **over):
    body = {"project_id": project_id, "inspection_type": "concrete_pour", "title": "Level 2 pour"}
    body.update(over)
    return body


async def _create(client: AsyncClient, header, project_id: str, **over) -> dict:
    resp = await client.post(BASE, json=_body(project_id, **over), headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _patch(client: AsyncClient, header, insp_id: str, **fields):
    return await client.patch(f"{BASE}{insp_id}", json=fields, headers=header)


@pytest.mark.asyncio
async def test_create_defaults_and_number(client, admin_auth, project_id):
    _, header = admin_auth
    a = await _create(client, header, project_id)
    b = await _create(client, header, project_id)
    assert a["status"] == "scheduled"
    assert a["inspection_number"] and a["inspection_number"] != b["inspection_number"]


@pytest.mark.asyncio
async def test_walk_scheduled_to_completed(client, admin_auth, project_id):
    uid, header = admin_auth
    insp = await _create(client, header, project_id, inspector_id=uid)
    r = await _patch(client, header, insp["id"], status="in_progress")
    assert r.status_code == 200, r.text
    done = await client.post(f"{BASE}{insp['id']}/complete/", json={"result": "pass"}, headers=header)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    assert done.json()["result"] == "pass"


@pytest.mark.asyncio
async def test_completed_is_terminal(client, admin_auth, project_id):
    uid, header = admin_auth
    insp = await _create(client, header, project_id, inspector_id=uid)
    assert (
        await client.post(f"{BASE}{insp['id']}/complete/", json={"result": "pass"}, headers=header)
    ).status_code == 200
    assert (await _patch(client, header, insp["id"], title="edit")).status_code == 400
    again = await client.post(f"{BASE}{insp['id']}/complete/", json={"result": "fail"}, headers=header)
    assert again.status_code == 400
    assert (await client.delete(f"{BASE}{insp['id']}", headers=header)).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "target"),
    [
        ([], "completed"),
        ([], "failed"),
        (["cancelled"], "in_progress"),
        (["cancelled"], "completed"),
        (["in_progress", "failed"], "completed"),
    ],
)
async def test_illegal_transitions_rejected(client, admin_auth, project_id, path, target):
    _, header = admin_auth
    insp = await _create(client, header, project_id)
    for step in path:
        assert (await _patch(client, header, insp["id"], status=step)).status_code == 200
    r = await _patch(client, header, insp["id"], status=target)
    assert r.status_code == 400, r.text
    assert "Cannot transition" in r.json()["detail"]


@pytest.mark.asyncio
async def test_failed_and_cancelled_can_be_rescheduled(client, admin_auth, project_id):
    _, header = admin_auth
    insp = await _create(client, header, project_id)
    for step in ("in_progress", "failed", "scheduled", "cancelled", "scheduled"):
        r = await _patch(client, header, insp["id"], status=step)
        assert r.status_code == 200, (step, r.text)


@pytest.mark.asyncio
async def test_complete_rejects_bad_result_and_wrong_state(client, admin_auth, project_id):
    _, header = admin_auth
    insp = await _create(client, header, project_id)
    bad = await client.post(f"{BASE}{insp['id']}/complete/", json={"result": "maybe"}, headers=header)
    assert bad.status_code == 422
    assert (await _patch(client, header, insp["id"], status="cancelled")).status_code == 200
    r = await client.post(f"{BASE}{insp['id']}/complete/", json={"result": "pass"}, headers=header)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_other_users_project_is_404(client, admin_auth, other_user_auth, project_id, other_project_id):
    _, owner = admin_auth
    _, stranger = other_user_auth
    insp = await _create(client, owner, project_id)

    assert (await client.get(f"{BASE}{insp['id']}", headers=stranger)).status_code == 404
    assert (await _patch(client, stranger, insp["id"], title="hijack")).status_code == 404
    assert (await client.delete(f"{BASE}{insp['id']}", headers=stranger)).status_code == 404
    done = await client.post(f"{BASE}{insp['id']}/complete/", json={"result": "pass"}, headers=stranger)
    assert done.status_code == 404
    assert (await client.get(BASE, params={"project_id": project_id}, headers=stranger)).status_code == 404
    assert (await client.post(BASE, json=_body(project_id), headers=stranger)).status_code == 404


@pytest.mark.asyncio
async def test_list_filters_by_project(client, admin_auth, project_id):
    _, header = admin_auth
    await _create(client, header, project_id, title="Listed")
    resp = await client.get(BASE, params={"project_id": project_id}, headers=header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(i["project_id"] == project_id for i in data["items"])


@pytest.mark.asyncio
async def test_checklist_validation(client, admin_auth, project_id):
    _, header = admin_auth
    ok = await _create(
        client,
        header,
        project_id,
        checklist_data=[{"question": "Rebar cover checked?", "response_type": "pass_fail"}],
    )
    assert ok["checklist_data"][0]["question"] == "Rebar cover checked?"

    empty_q = await client.post(BASE, json=_body(project_id, checklist_data=[{"question": ""}]), headers=header)
    assert empty_q.status_code == 422
    bad_type = await client.post(
        BASE,
        json=_body(project_id, checklist_data=[{"question": "q", "response_type": "telepathy"}]),
        headers=header,
    )
    assert bad_type.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "over",
    [
        {"inspection_type": "bogus"},
        {"status": "reopened"},
        {"result": "great"},
        {"title": ""},
        {"inspection_date": "04/11/2026"},
    ],
)
async def test_invalid_payload_is_422(client, admin_auth, project_id, over):
    _, header = admin_auth
    r = await client.post(BASE, json=_body(project_id, **over), headers=header)
    assert r.status_code == 422, r.text
