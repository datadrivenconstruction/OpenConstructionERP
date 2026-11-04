"""NCR -> change order goes through ChangeOrderService, so the changeorders rules run."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

BASE = "/api/v1/ncr/"


async def _project(client: AsyncClient, header, currency: str) -> str:
    resp = await client.post(
        "/api/v1/projects/", json={"name": f"NCRCO {currency or 'none'}", "currency": currency}, headers=header
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _ncr(client: AsyncClient, header, project_id: str, **over) -> dict:
    body = {
        "project_id": project_id,
        "title": "Honeycombing in slab",
        "description": "Voids visible on level 2 soffit",
        "ncr_type": "workmanship",
        "severity": "major",
        "cost_impact": "1500",
    }
    body.update(over)
    resp = await client.post(BASE, json=body, headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_variation_is_created_through_the_rules(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header, "EUR")
    ncr = await _ncr(client, header, pid)
    resp = await client.post(f"{BASE}{ncr['id']}/create-variation/", headers=header)
    assert resp.status_code == 201, resp.text
    co = (await client.get(f"/api/v1/changeorders/{resp.json()['change_order_id']}", headers=header)).json()
    assert co["currency"] == "EUR"
    assert float(co["cost_impact"]) == 1500.0
    assert co["metadata"]["source"] == "ncr"


@pytest.mark.asyncio
async def test_drifted_payload_is_refused_with_the_coded_422(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header, "EUR")
    ncr = await _ncr(client, header, pid, schedule_impact_days=9000)
    resp = await client.post(f"{BASE}{ncr['id']}/create-variation/", headers=header)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "money_rules_failed"
    assert "changeorders.values_in_range" in {e["rule_id"] for e in detail["errors"]}
    assert (await client.get(f"{BASE}{ncr['id']}", headers=header)).json()["change_order_id"] in (None, "")


@pytest.mark.asyncio
async def test_blank_project_currency_still_creates_a_flagged_order(client, admin_auth):
    _, header = admin_auth
    pid = await _project(client, header, "")
    ncr = await _ncr(client, header, pid)
    resp = await client.post(f"{BASE}{ncr['id']}/create-variation/", headers=header)
    assert resp.status_code == 201, resp.text
    co = (await client.get(f"/api/v1/changeorders/{resp.json()['change_order_id']}", headers=header)).json()
    assert float(co["cost_impact"]) == 0.0
    assert co["metadata"]["amount_needs_review"] is True
    assert co["metadata"]["currency_missing"] is True
    assert co["metadata"]["ncr_cost_impact_raw"] == "1500"
