"""Failed inspection -> defect / NCR escalation, export, merge audit and list filters."""

from __future__ import annotations

import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

BASE = "/api/v1/inspections/"


async def _create(client: AsyncClient, header, project_id: str, **over) -> dict:
    body = {"project_id": project_id, "inspection_type": "concrete_pour", "title": "Level 3 pour"}
    body.update(over)
    resp = await client.post(BASE, json=body, headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _failed(**over) -> dict:
    over.setdefault("result", "fail")
    over.setdefault(
        "checklist_data",
        [
            {"id": "1", "question": "Cover ok?", "response": "no", "critical": True, "notes": "20 mm"},
            {"id": "2", "question": "Slump ok?", "response": "yes"},
        ],
    )
    return over


async def _punch_item(punch_item_id: str):
    from app.database import async_session_factory
    from app.modules.punchlist.models import PunchItem

    async with async_session_factory() as session:
        return (await session.execute(select(PunchItem).where(PunchItem.id == uuid.UUID(punch_item_id)))).scalar_one()


@pytest.mark.asyncio
async def test_passed_inspection_cannot_escalate(client, admin_auth, project_id):
    _, header = admin_auth
    insp = await _create(client, header, project_id, result="pass")
    for path in ("create-defect", "create-ncr"):
        resp = await client.post(f"{BASE}{insp['id']}/{path}/", headers=header)
        assert resp.status_code == 400, path


@pytest.mark.asyncio
async def test_failed_inspection_becomes_a_punch_item(client, admin_auth, project_id):
    _, header = admin_auth
    insp = await _create(client, header, project_id, location="Grid B", **_failed())
    resp = await client.post(f"{BASE}{insp['id']}/create-defect/", headers=header)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "Defect: Level 3 pour @ Grid B"
    item = await _punch_item(body["punch_item_id"])
    assert item.priority == "high"
    assert "Cover ok?" in item.description and "Slump ok?" not in item.description
    assert item.metadata_["inspection_id"] == insp["id"]


@pytest.mark.asyncio
async def test_partial_inspection_gets_medium_priority(client, admin_auth, project_id):
    _, header = admin_auth
    insp = await _create(client, header, project_id, **_failed(result="partial", checklist_data=[]))
    resp = await client.post(f"{BASE}{insp['id']}/create-defect/", headers=header)
    assert resp.status_code == 201, resp.text
    assert (await _punch_item(resp.json()["punch_item_id"])).priority == "medium"


@pytest.mark.asyncio
async def test_failed_inspection_raises_one_ncr_and_repeat_returns_it(client, admin_auth, project_id):
    _, header = admin_auth
    insp = await _create(client, header, project_id, **_failed())
    first = await client.post(f"{BASE}{insp['id']}/create-ncr/", headers=header)
    assert first.status_code == 201, first.text
    assert first.json()["created"] is True
    assert first.json()["severity"] == "critical" and first.json()["ncr_type"] == "workmanship"
    again = await client.post(f"{BASE}{insp['id']}/create-ncr/", headers=header)
    assert again.json()["created"] is False
    assert again.json()["ncr_id"] == first.json()["ncr_id"]
    ncr = (await client.get(f"/api/v1/ncr/{first.json()['ncr_id']}", headers=header)).json()
    assert ncr["linked_inspection_id"] == insp["id"]
    assert "Cover ok? (critical) - 20 mm" in ncr["description"]


@pytest.mark.asyncio
async def test_partial_without_critical_item_is_major_workmanship(client, admin_auth, project_id):
    _, header = admin_auth
    insp = await _create(
        client,
        header,
        project_id,
        inspection_type="structural",
        result="partial",
        checklist_data=[{"id": "1", "question": "Level?", "response": "no"}],
    )
    resp = await client.post(f"{BASE}{insp['id']}/create-ncr/", headers=header)
    assert resp.status_code == 201, resp.text
    assert resp.json()["severity"] == "major" and resp.json()["ncr_type"] == "workmanship"


@pytest.mark.asyncio
async def test_escalation_is_project_scoped(client, admin_auth, project_id, other_user_auth):
    _, header = admin_auth
    _, stranger = other_user_auth
    insp = await _create(client, header, project_id, **_failed())
    for path in ("create-defect", "create-ncr", "complete"):
        resp = await client.post(f"{BASE}{insp['id']}/{path}/", headers=stranger)
        assert resp.status_code in (403, 404), path


@pytest.mark.asyncio
async def test_export_is_a_workbook_with_checklist_counts(client, admin_auth, project_id):
    _, header = admin_auth
    await _create(client, header, project_id, title="Exported", **_failed())
    resp = await client.get(f"{BASE}export/", params={"project_id": project_id}, headers=header)
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(resp.content)).active
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    mine = [r for r in rows if "Exported" in r]
    assert mine and mine[0][-1] == "1/1"


@pytest.mark.asyncio
async def test_list_filters_total_and_missing_get(client, admin_auth):
    _, header = admin_auth
    pid = (
        await client.post("/api/v1/projects/", json={"name": f"INSP {uuid.uuid4().hex[:6]}"}, headers=header)
    ).json()["id"]
    await _create(client, header, pid, inspection_type="electrical")
    await _create(client, header, pid, inspection_type="plumbing")
    await _create(client, header, pid, inspection_type="plumbing")
    page = (await client.get(BASE, params={"project_id": pid, "limit": 2}, headers=header)).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    only = (await client.get(BASE, params={"project_id": pid, "type": "plumbing"}, headers=header)).json()
    assert only["total"] == 2
    none = (await client.get(BASE, params={"project_id": pid, "status": "completed"}, headers=header)).json()
    assert none["total"] == 0
    assert (await client.get(f"{BASE}{uuid.uuid4()}", headers=header)).status_code == 404


@pytest.mark.asyncio
async def test_merge_is_audited_and_refused_once_completed(client, admin_auth, project_id):
    _, header = admin_auth
    insp = await _create(client, header, project_id)
    merge = await client.post(
        f"{BASE}{insp['id']}/merge/",
        json={"base_version": insp["version"], "against_version": insp["version"], "fields": {"title": "Merged"}},
        headers=header,
    )
    assert merge.status_code == 200, merge.text
    assert merge.json()["item"]["title"] == "Merged"
    audit = await client.get(f"{BASE}{insp['id']}/merge-audit/", headers=header)
    assert audit.status_code == 200, audit.text
    done = await client.post(f"{BASE}{insp['id']}/complete/", json={"result": "pass"}, headers=header)
    assert done.status_code == 200
    late = await client.post(
        f"{BASE}{insp['id']}/merge/",
        json={"base_version": 1, "against_version": 1, "fields": {"title": "Late"}},
        headers=header,
    )
    assert late.status_code == 400
