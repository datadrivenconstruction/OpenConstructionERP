"""NCR -> variation edge paths: idempotence, refusals, currency read from the cost text."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

BASE = "/api/v1/ncr/"


async def _project(client: AsyncClient, header, currency: str) -> str:
    resp = await client.post(
        "/api/v1/projects/", json={"name": f"NCRP {uuid.uuid4().hex[:6]}", "currency": currency}, headers=header
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _ncr(client: AsyncClient, header, project_id: str, **over) -> dict:
    body = {
        "project_id": project_id,
        "title": "Rebar cover short",
        "description": "Cover below spec on grid B",
        "ncr_type": "workmanship",
        "severity": "major",
    }
    body.update(over)
    resp = await client.post(BASE, json=body, headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_no_cost_impact_has_no_variation(client, admin_auth):
    _, header = admin_auth
    ncr = await _ncr(client, header, await _project(client, header, "EUR"))
    resp = await client.post(f"{BASE}{ncr['id']}/create-variation/", headers=header)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_void_ncr_does_not_become_a_variation(client, admin_auth):
    _, header = admin_auth
    ncr = await _ncr(client, header, await _project(client, header, "EUR"), cost_impact="800")
    assert (await client.patch(f"{BASE}{ncr['id']}", json={"status": "void"}, headers=header)).status_code == 200
    resp = await client.post(f"{BASE}{ncr['id']}/create-variation/", headers=header)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_repeat_call_returns_the_same_change_order(client, admin_auth):
    _, header = admin_auth
    ncr = await _ncr(
        client,
        header,
        await _project(client, header, "EUR"),
        cost_impact="2500",
        corrective_action="Re-pour",
        root_cause="Spacers missing",
    )
    first = await client.post(f"{BASE}{ncr['id']}/create-variation/", headers=header)
    second = await client.post(f"{BASE}{ncr['id']}/create-variation/", headers=header)
    assert first.status_code == second.status_code == 201
    assert first.json()["change_order_id"] == second.json()["change_order_id"]
    co = (await client.get(f"/api/v1/changeorders/{first.json()['change_order_id']}", headers=header)).json()
    assert "Corrective Action:" in co["description"] and "Root Cause:" in co["description"]
    assert (await client.get(f"{BASE}{ncr['id']}", headers=header)).json()["change_order_id"] == co["id"]


@pytest.mark.asyncio
async def test_currency_in_the_text_wins_over_the_project(client, admin_auth):
    _, header = admin_auth
    ncr = await _ncr(client, header, await _project(client, header, "EUR"), cost_impact="BRL 12.000,50")
    resp = await client.post(f"{BASE}{ncr['id']}/create-variation/", headers=header)
    assert resp.status_code == 201, resp.text
    co = (await client.get(f"/api/v1/changeorders/{resp.json()['change_order_id']}", headers=header)).json()
    assert co["currency"] == "BRL"
    assert float(co["cost_impact"]) == 12000.5


@pytest.mark.asyncio
async def test_unreadable_cost_text_is_flagged_for_review(client, admin_auth):
    _, header = admin_auth
    ncr = await _ncr(client, header, await _project(client, header, "EUR"), cost_impact="between 100 and 200")
    resp = await client.post(f"{BASE}{ncr['id']}/create-variation/", headers=header)
    assert resp.status_code == 201, resp.text
    co = (await client.get(f"/api/v1/changeorders/{resp.json()['change_order_id']}", headers=header)).json()
    assert float(co["cost_impact"]) == 0.0
    assert co["metadata"].get("amount_needs_review")


@pytest.mark.asyncio
async def test_absurd_amount_is_refused(client, admin_auth):
    _, header = admin_auth
    ncr = await _ncr(client, header, await _project(client, header, "EUR"), cost_impact="EUR 9999999999999999")
    resp = await client.post(f"{BASE}{ncr['id']}/create-variation/", headers=header)
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_list_filters_and_paging(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header, "EUR")
    await _ncr(client, header, pid, severity="critical", ncr_type="design")
    await _ncr(client, header, pid, severity="minor", ncr_type="workmanship")
    await _ncr(client, header, pid, severity="minor", ncr_type="workmanship")
    both = (await client.get(BASE, params={"project_id": pid, "limit": 2}, headers=header)).json()
    assert both["total"] == 3 and len(both["items"]) == 2 and both["limit"] == 2
    by_type = (await client.get(BASE, params={"project_id": pid, "type": "design"}, headers=header)).json()
    assert by_type["total"] == 1
    by_status = (await client.get(BASE, params={"project_id": pid, "status": "closed"}, headers=header)).json()
    assert by_status["total"] == 0
    assert (await client.get(f"{BASE}{uuid.uuid4()}", headers=header)).status_code == 404
