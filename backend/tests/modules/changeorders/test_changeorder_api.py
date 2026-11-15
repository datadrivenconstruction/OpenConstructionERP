"""Change order API flow on PostgreSQL: CRUD, items, approval paths, chain, simulator, exports."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.modules.changeorders.conftest import _register_user

BASE = "/api/v1/changeorders/"


async def _project(client: AsyncClient, header, currency: str = "EUR") -> str:
    resp = await client.post(
        "/api/v1/projects/", json={"name": f"CO {uuid.uuid4().hex[:6]}", "currency": currency}, headers=header
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _co(client: AsyncClient, header, pid: str, **over) -> dict:
    body = {"project_id": pid, "title": "Extra footing", "reason_category": "client_request"}
    body.update(over)
    resp = await client.post(BASE, json=body, headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _item(client: AsyncClient, header, order_id: str, **over) -> dict:
    body = {
        "description": "Footing concrete",
        "change_type": "added",
        "new_quantity": "10",
        "new_rate": "120",
        "unit": "m3",
    }
    body.update(over)
    resp = await client.post(f"{BASE}{order_id}/items/", json=body, headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_items_drive_the_order_cost(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header)
    co = await _co(client, header, pid)
    assert co["status"] == "draft"
    a = await _item(client, header, co["id"])
    b = await _item(client, header, co["id"], description="Formwork", new_quantity="4", new_rate="50", unit="m2")
    full = (await client.get(f"{BASE}{co['id']}", headers=header)).json()
    assert len(full["items"]) == 2
    assert float(full["cost_impact"]) == 10 * 120 + 4 * 50
    upd = await client.patch(f"{BASE}{co['id']}/items/{b['id']}", json={"new_quantity": "6"}, headers=header)
    assert upd.status_code == 200, upd.text
    assert float((await client.get(f"{BASE}{co['id']}", headers=header)).json()["cost_impact"]) == 1200 + 300
    assert (await client.delete(f"{BASE}{co['id']}/items/{a['id']}", headers=header)).status_code == 204
    assert float((await client.get(f"{BASE}{co['id']}", headers=header)).json()["cost_impact"]) == 300


@pytest.mark.asyncio
async def test_update_delete_and_missing(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header)
    co = await _co(client, header, pid)
    patched = await client.patch(
        f"{BASE}{co['id']}", json={"title": "Renamed", "schedule_impact_days": 4}, headers=header
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "Renamed" and patched.json()["schedule_impact_days"] == 4
    assert (await client.delete(f"{BASE}{co['id']}", headers=header)).status_code == 204
    assert (await client.get(f"{BASE}{co['id']}", headers=header)).status_code == 404
    assert (await client.get(f"{BASE}{uuid.uuid4()}", headers=header)).status_code == 404


@pytest.mark.asyncio
async def test_list_filter_summary_and_preflight(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header)
    a = await _co(client, header, pid, title="One")
    await _co(client, header, pid, title="Two")
    await _item(client, header, a["id"])
    assert (await client.post(f"{BASE}{a['id']}/submit/", headers=header)).status_code == 200
    all_rows = (await client.get(BASE, params={"project_id": pid}, headers=header)).json()
    assert len(all_rows) == 2
    submitted = (await client.get(BASE, params={"project_id": pid, "status": "submitted"}, headers=header)).json()
    assert [r["id"] for r in submitted] == [a["id"]]
    owned = (await client.get(BASE, headers=header)).json()
    assert {a["id"]} <= {r["id"] for r in owned}
    summary = await client.get(f"{BASE}summary/", params={"project_id": pid}, headers=header)
    assert summary.status_code == 200, summary.text
    pre = await client.get(f"{BASE}standalone-preflight", params={"project_id": pid}, headers=header)
    assert pre.status_code == 200 and "items" in pre.json()


@pytest.mark.asyncio
async def test_submit_approve_execute_and_freeze(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header)
    co = await _co(client, header, pid)
    await _item(client, header, co["id"])
    assert (await client.post(f"{BASE}{co['id']}/approve/", headers=header)).status_code in (400, 409)
    assert (await client.post(f"{BASE}{co['id']}/submit/", headers=header)).json()["status"] == "submitted"
    assert (await client.post(f"{BASE}{co['id']}/approve/", headers=header)).status_code == 403
    _, _, approver = await _register_user(client, role="admin")
    approved = await client.post(f"{BASE}{co['id']}/approve/", headers=approver)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert (await client.patch(f"{BASE}{co['id']}", json={"title": "late"}, headers=header)).status_code in (400, 409)
    assert (await client.delete(f"{BASE}{co['id']}", headers=header)).status_code in (400, 409)
    done = await client.post(f"{BASE}{co['id']}/execute/", headers=header)
    assert done.status_code == 200 and done.json()["status"] == "executed"
    assert (await client.post(f"{BASE}{co['id']}/reject/", headers=approver)).status_code in (400, 409)


@pytest.mark.asyncio
async def test_reject_after_submit(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header)
    co = await _co(client, header, pid)
    await _item(client, header, co["id"])
    await client.post(f"{BASE}{co['id']}/submit/", headers=header)
    assert (await client.post(f"{BASE}{co['id']}/reject/", headers=header)).status_code == 403
    _, _, approver = await _register_user(client, role="admin")
    rejected = await client.post(f"{BASE}{co['id']}/reject/", headers=approver)
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_approval_chain_runs_step_by_step(client, admin_auth):
    _, header = admin_auth
    first_id, _e1, first = await _register_user(client, role="admin", tag=f"ap1-{uuid.uuid4().hex[:6]}")
    second_id, _e2, second = await _register_user(client, role="admin", tag=f"ap2-{uuid.uuid4().hex[:6]}")
    pid = await _project(client, header)
    co = await _co(client, header, pid)
    await _item(client, header, co["id"])
    chain = {"approver_user_ids": [first_id, second_id]}
    early = await client.post(f"{BASE}{co['id']}/approval-chain", json=chain, headers=header)
    assert early.status_code in (400, 409)
    await client.post(f"{BASE}{co['id']}/submit/", headers=header)
    started = await client.post(f"{BASE}{co['id']}/approval-chain", json=chain, headers=header)
    assert started.status_code == 201, started.text
    assert [r["step_order"] for r in started.json()] == [1, 2]
    wrong = await client.post(f"{BASE}{co['id']}/advance-approval", json={"decision": "approved"}, headers=second)
    assert wrong.status_code == 403
    one = await client.post(f"{BASE}{co['id']}/advance-approval", json={"decision": "approved"}, headers=first)
    assert one.status_code == 200, one.text
    assert (await client.get(f"{BASE}{co['id']}", headers=header)).json()["status"] == "submitted"
    two = await client.post(
        f"{BASE}{co['id']}/advance-approval", json={"decision": "approved", "comments": "ok"}, headers=second
    )
    assert two.status_code == 200, two.text
    assert (await client.get(f"{BASE}{co['id']}", headers=header)).json()["status"] == "approved"
    rows = (await client.get(f"{BASE}{co['id']}/approvals", headers=header)).json()
    assert [r["decision"] for r in rows] == ["approved", "approved"]


@pytest.mark.asyncio
async def test_a_rejecting_approver_rejects_the_order(client, admin_auth):
    _, header = admin_auth
    approver_id, _e, approver = await _register_user(client, role="admin", tag=f"ap3-{uuid.uuid4().hex[:6]}")
    pid = await _project(client, header)
    co = await _co(client, header, pid)
    await _item(client, header, co["id"])
    await client.post(f"{BASE}{co['id']}/submit/", headers=header)
    started = await client.post(
        f"{BASE}{co['id']}/approval-chain", json={"approver_user_ids": [approver_id]}, headers=header
    )
    assert started.status_code == 201, started.text
    res = await client.post(f"{BASE}{co['id']}/advance-approval", json={"decision": "rejected"}, headers=approver)
    assert res.status_code == 200, res.text
    assert (await client.get(f"{BASE}{co['id']}", headers=header)).json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_simulator_changes_nothing_and_publish_keeps_the_snapshot(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header)
    co = await _co(client, header, pid)
    await _item(client, header, co["id"])
    base = await client.post(f"{BASE}{co['id']}/simulate-impact/", headers=header)
    assert base.status_code == 200, base.text
    what_if = await client.post(
        f"{BASE}{co['id']}/simulate-impact/", json={"cost_impact": "9000", "schedule_impact_days": 12}, headers=header
    )
    assert what_if.status_code == 200 and what_if.json() != base.json()
    assert float((await client.get(f"{BASE}{co['id']}", headers=header)).json()["cost_impact"]) == 1200
    pub = await client.post(f"{BASE}{co['id']}/publish-scenario/", json={"cost_impact": "9000"}, headers=header)
    assert pub.status_code == 200, pub.text
    assert pub.json()["metadata"]
    assert float(pub.json()["cost_impact"]) == 1200


@pytest.mark.asyncio
async def test_ai_draft_is_a_proposal_that_is_never_saved(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header)
    resp = await client.post(
        f"{BASE}ai-draft/",
        json={
            "project_id": pid,
            "source_text": "Client asked to add a retaining wall. Extra cost EUR 4500 and 5 days delay.",
        },
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"]
    assert (await client.get(BASE, params={"project_id": pid}, headers=header)).json() == []


@pytest.mark.asyncio
async def test_register_and_form_exports(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header)
    co = await _co(client, header, pid)
    await _item(client, header, co["id"])
    xlsx = await client.get(f"{BASE}export/", params={"project_id": pid}, headers=header)
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    pdf = await client.get(f"{BASE}export/", params={"project_id": pid, "format": "pdf"}, headers=header)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    form = await client.get(f"{BASE}{co['id']}/export/pdf/", params={"locale": "de"}, headers=header)
    assert form.status_code == 200 and form.content[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_other_tenant_cannot_touch_the_order(client, admin_auth, other_user_auth):
    _, header = admin_auth
    _, stranger = other_user_auth
    pid = await _project(client, header)
    co = await _co(client, header, pid)
    assert (await client.get(f"{BASE}{co['id']}", headers=stranger)).status_code in (403, 404)
    assert (await client.get(BASE, params={"project_id": pid}, headers=stranger)).status_code in (403, 404)
    for path in ("submit", "approve", "reject", "execute"):
        assert (await client.post(f"{BASE}{co['id']}/{path}/", headers=stranger)).status_code in (403, 404), path
