"""Quick massing over HTTP: login required, project scope enforced, unsourced values refused, findings in validation."""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from .conftest import LINK, make_project, make_user
from .test_design_brief import EXAMPLE

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/design"
OFFICE = {"building_type": "office", "gfa_m2": 2400, "storeys": 4, "country": "DE", "quality": "standard"}


async def test_quick_needs_login_and_returns_worked_numbers(client):
    assert (await client.post(f"{BASE}/quick", json=OFFICE, headers=LINK)).status_code == 401
    _, h = await make_user(client)
    r = await client.post(f"{BASE}/quick", json=OFFICE, headers={**h, **LINK})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"]["footprint"] == {"width_m": 43.48, "depth_m": 13.8, "area_m2": 600.0}
    assert Decimal(body["cost"]["total"]) == Decimal("7440000")
    assert body["schedule"]["reason"] == "rate_missing"
    types = (await client.get(f"{BASE}/quick/types", headers={**h, **LINK})).json()["types"]
    assert {"id": "warehouse", "generator": False, "priced": False} in types


async def test_type_without_sourced_defaults_is_refused_until_the_brief_gives_them(client):
    _, h = await make_user(client)
    brief = {"building_type": "hotel", "gfa_m2": 6000, "storeys": 6, "country": "DE"}
    r = (await client.post(f"{BASE}/quick", json=brief, headers={**h, **LINK})).json()
    assert r["model"] is None
    assert {(i["code"], i["field"]) for i in r["issues"]} == {
        ("source_missing", "floor_height_m"),
        ("source_missing", "depth_m"),
    }
    ok = await client.post(f"{BASE}/quick", json={**brief, "floor_height_m": 3.2, "depth_m": 16}, headers={**h, **LINK})
    assert ok.json()["model"]["footprint"]["area_m2"] == 1000.0


async def test_project_quick_uses_project_currency_and_is_tenant_scoped(client):
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    owner, h = await make_user(client)
    pid = await make_project(owner)
    async with async_session_factory() as s:
        p = await s.get(Project, pid)
        p.currency, p.fx_rates = "USD", [{"code": "EUR", "rate": "1.10"}]
        await s.commit()
    r = await client.post(f"{BASE}/projects/{pid}/quick", json=OFFICE, headers={**h, **LINK})
    assert r.status_code == 200, r.text
    cost = r.json()["cost"]
    assert cost["currency"] == "USD" and Decimal(cost["total"]) == Decimal("8184000.00")
    assert cost["fx_source"] == "project.fx_rates[EUR]"

    _, other = await make_user(client)
    denied = await client.post(f"{BASE}/projects/{pid}/quick", json=OFFICE, headers={**other, **LINK})
    assert denied.status_code in (403, 404)


async def test_brief_findings_show_in_project_validation(client):
    owner, h = await make_user(client)
    pid = await make_project(owner)
    doc = copy.deepcopy(EXAMPLE)
    # 5 storeys x 3.0 m = 15 m against a 12 m limit; GFA from the footprint 12 x 30 x 5
    doc["massing"] = {"floors_above": 5, "floor_height_m": 3.0, "footprint": {"width_m": 30, "depth_m": 12}}
    doc["site"]["max_height_m"] = 12
    put = await client.put(f"{BASE}/projects/{pid}/brief", json=doc, headers=h)
    assert put.status_code == 200, put.text
    r = await client.get(f"{BASE}/projects/{pid}/validation", headers={**h, **LINK})
    assert r.status_code == 200, r.text
    found = [f for f in r.json()["findings"] if f["rule_id"] == "design.brief_plausible"]
    assert [f["ref"] for f in found] == ["storeys"]
    assert "15.0" in found[0]["message"] and "12" in found[0]["message"]


@pytest.mark.parametrize(
    "patch",
    [{"depth_m": 0}, {"floor_height_m": -3}, {"gfa_m2": 0}, {"storeys": 0}, {"fx_rate": "-1"}, {"wwr": 2}],
)
async def test_out_of_range_values_are_refused_with_422(client, patch):
    _, h = await make_user(client)
    r = await client.post(f"{BASE}/quick", json={**OFFICE, **patch}, headers={**h, **LINK})
    assert r.status_code == 422, r.text


async def test_us_project_gets_no_german_prices(client):
    _, h = await make_user(client)
    r = await client.post(
        f"{BASE}/quick", json={**OFFICE, "country": "US", "currency": "USD", "fx_rate": "1.1"}, headers={**h, **LINK}
    )
    assert r.status_code == 200, r.text
    assert r.json()["cost"]["reason"] == "no_band" and r.json()["cost"]["total"] is None
