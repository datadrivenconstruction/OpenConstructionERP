"""NCR lifecycle, project scoping and input-validation tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.modules.ncr.schemas import NCRCreate, NCRUpdate

BASE = "/api/v1/ncr/"


def _body(project_id: str, **over):
    body = {
        "project_id": project_id,
        "title": "Honeycombing in slab",
        "description": "Voids visible on level 2 soffit",
        "ncr_type": "workmanship",
        "severity": "major",
    }
    body.update(over)
    return body


async def _create(client: AsyncClient, header, project_id: str, **over) -> dict:
    resp = await client.post(BASE, json=_body(project_id, **over), headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _patch(client: AsyncClient, header, ncr_id: str, **fields):
    return await client.patch(f"{BASE}{ncr_id}", json=fields, headers=header)


@pytest.mark.asyncio
async def test_create_defaults_and_number(client, admin_auth, project_id):
    _, header = admin_auth
    a = await _create(client, header, project_id)
    b = await _create(client, header, project_id)
    assert a["status"] == "identified"
    assert a["ncr_number"] and a["ncr_number"] != b["ncr_number"]


@pytest.mark.asyncio
async def test_full_happy_path_to_closed(client, admin_auth, project_id):
    _, header = admin_auth
    ncr = await _create(client, header, project_id)
    for nxt in ("under_review", "corrective_action", "verification"):
        r = await _patch(
            client, header, ncr["id"], status=nxt, corrective_action="Grout and re-inspect", root_cause="Poor vibration"
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == nxt
    closed = await client.post(f"{BASE}{ncr['id']}/close/", headers=header)
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["verified_by"] and closed.json()["verified_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start_path", "target"),
    [
        ([], "closed"),
        ([], "verification"),
        ([], "corrective_action"),
        (["under_review"], "closed"),
        (["under_review"], "verification"),
    ],
)
async def test_illegal_transitions_rejected(client, admin_auth, project_id, start_path, target):
    _, header = admin_auth
    ncr = await _create(client, header, project_id)
    for step in start_path:
        assert (await _patch(client, header, ncr["id"], status=step)).status_code == 200
    r = await _patch(client, header, ncr["id"], status=target)
    assert r.status_code == 400, r.text
    assert "Cannot transition" in r.json()["detail"]


@pytest.mark.asyncio
async def test_close_requires_verification_and_corrective_action(client, admin_auth, project_id):
    _, header = admin_auth
    ncr = await _create(client, header, project_id)
    early = await client.post(f"{BASE}{ncr['id']}/close/", headers=header)
    assert early.status_code == 400
    assert "verification" in early.json()["detail"]

    for nxt in ("under_review", "corrective_action", "verification"):
        assert (await _patch(client, header, ncr["id"], status=nxt)).status_code == 200
    no_action = await client.post(f"{BASE}{ncr['id']}/close/", headers=header)
    assert no_action.status_code == 400
    assert "corrective action" in no_action.json()["detail"]


@pytest.mark.asyncio
async def test_void_is_terminal_and_blocks_edit_and_delete(client, admin_auth, project_id):
    _, header = admin_auth
    ncr = await _create(client, header, project_id)
    assert (await _patch(client, header, ncr["id"], status="void")).status_code == 200
    assert (await _patch(client, header, ncr["id"], title="x")).status_code == 400
    assert (await client.post(f"{BASE}{ncr['id']}/close/", headers=header)).status_code == 400
    assert (await client.delete(f"{BASE}{ncr['id']}", headers=header)).status_code == 409


@pytest.mark.asyncio
async def test_delete_open_ncr(client, admin_auth, project_id):
    _, header = admin_auth
    ncr = await _create(client, header, project_id)
    assert (await client.delete(f"{BASE}{ncr['id']}", headers=header)).status_code == 204
    assert (await client.get(f"{BASE}{ncr['id']}", headers=header)).status_code == 404


@pytest.mark.asyncio
async def test_list_is_scoped_and_filtered(client, admin_auth, project_id, other_project_id):
    _, header = admin_auth
    await _create(client, header, project_id, severity="critical")
    resp = await client.get(BASE, params={"project_id": project_id, "severity": "critical"}, headers=header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(i["project_id"] == project_id and i["severity"] == "critical" for i in data["items"])


@pytest.mark.asyncio
async def test_other_users_project_is_404(client, admin_auth, other_user_auth, project_id, other_project_id):
    _, owner = admin_auth
    _, stranger = other_user_auth
    ncr = await _create(client, owner, project_id)

    assert (await client.get(f"{BASE}{ncr['id']}", headers=stranger)).status_code == 404
    assert (await _patch(client, stranger, ncr["id"], title="hijack")).status_code == 404
    assert (await client.delete(f"{BASE}{ncr['id']}", headers=stranger)).status_code == 404
    assert (await client.post(f"{BASE}{ncr['id']}/close/", headers=stranger)).status_code == 404
    assert (await client.get(BASE, params={"project_id": project_id}, headers=stranger)).status_code == 404
    created = await client.post(BASE, json=_body(project_id), headers=stranger)
    assert created.status_code == 404


@pytest.mark.asyncio
async def test_change_order_not_in_project_rejected(client, admin_auth, project_id):
    _, header = admin_auth
    r = await client.post(
        BASE,
        json=_body(project_id, change_order_id="00000000-0000-0000-0000-000000000001"),
        headers=header,
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "over",
    [
        {"ncr_type": "bogus"},
        {"severity": "huge"},
        {"status": "reopened"},
        {"title": ""},
        {"schedule_impact_days": -1},
        {"location_lat": 10.0},
        {"location_lat": 91.0, "location_lon": 10.0},
        {"location_lat": 10.0, "location_lon": 181.0},
        {"location_accuracy_m": 5.0},
    ],
)
async def test_invalid_payload_is_422(client, admin_auth, project_id, over):
    _, header = admin_auth
    r = await client.post(BASE, json=_body(project_id, **over), headers=header)
    assert r.status_code == 422, r.text


def test_schema_rejects_non_finite_coordinates():
    base = {
        "project_id": "00000000-0000-0000-0000-000000000001",
        "title": "t",
        "description": "d",
        "ncr_type": "material",
        "severity": "minor",
    }
    for bad in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValidationError):
            NCRCreate(**base, location_lat=bad, location_lon="10")
        with pytest.raises(ValidationError):
            NCRCreate(**base, location_lat="10", location_lon=bad)
        with pytest.raises(ValidationError):
            NCRCreate(**base, location_lat="10", location_lon="10", location_accuracy_m=bad)
        with pytest.raises(ValidationError):
            NCRUpdate(location_accuracy_m=bad)
