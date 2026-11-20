"""Unit rates come from the ERP cost database of the project region; no match stays empty and flagged; a rate a
person set or picked survives later revisions."""

from __future__ import annotations

import copy
import uuid

import pytest

from .ddcrev import example_rows
from .test_design_revisions import BASE, _linked_project
from .test_estimate_edges import _publish, _summary
from .test_estimate_rules import D

pytestmark = pytest.mark.asyncio


async def _seed(region, token, *, unit="m2", currency="EUR", rate="123.45"):
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as s:
        item = CostItem(
            code=f"DSG-{uuid.uuid4().hex[:8]}",
            description=f"{token} Außenwand",
            unit=unit,
            rate=rate,
            currency=currency,
            source="custom",
            region=region,
            is_active=True,
        )
        s.add(item)
        await s.flush()
        iid = str(item.id)
        await s.commit()
    return iid


async def _install(client, h, pid, token):
    from app.modules.design import rules

    doc = copy.deepcopy(rules.starter_set("DE"))
    for r in doc["rules"]:
        if r["id"] == "wall_ext":
            r["cost_query"] = {"de": token}
    est = f"{BASE}/projects/{pid}/estimate"
    assert (await client.post(f"{est}/rules", json=doc, headers=h)).status_code == 201
    return est


async def _set_project_region(pid, region):
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        (await s.get(Project, pid)).region = region
        await s.commit()


async def _set_rate(position_id, rate):
    from app.database import async_session_factory
    from app.modules.boq.repository import PositionRepository

    async with async_session_factory() as s:
        repo = PositionRepository(s)
        pos = await repo.get_by_id(uuid.UUID(position_id))
        await repo.update_fields(pos.id, unit_rate=rate, total=str(D(rate) * D(pos.quantity)))
        await s.commit()


async def test_seeded_cost_item_prices_the_position_with_its_source(client):
    uid, h, pid, tok = await _linked_project(client)
    region, token = f"DE_T{uuid.uuid4().hex[:6]}", f"zq{uuid.uuid4().hex[:8]}"
    await _set_project_region(pid, region)
    item_id = await _seed(region, token)
    await _seed(region, token, unit="m3", rate="9")  # wrong unit: never taken
    await _seed(region, token, currency="USD", rate="7")  # wrong currency: never taken
    await _publish(client, h, tok, pid, example_rows())
    est = await _install(client, h, pid, token)
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    s = await _summary(client, h, pid)
    w = s["wall_ext"]
    assert D(w["unit_rate"]) == D("123.45") and D(w["total"]) == D("123.45") * D(w["quantity"])
    ci = w["provenance"]["cost_item"]
    assert ci["cost_item_id"] == item_id and ci["region"] == region and ci["database"] == f"custom:{region}"
    assert ci["auto"] is True and "cost_auto" in w["flags"] and "unpriced" not in w["flags"]
    # nothing in the database for the others: empty and flagged, never a guess
    d = s["door"]
    assert D(d["unit_rate"]) == 0 and {"unpriced", "cost_no_match"} <= set(d["flags"])


async def test_no_match_stays_empty_and_flagged(client):
    uid, h, pid, tok = await _linked_project(client)
    await _publish(client, h, tok, pid, example_rows())
    est = await _install(client, h, pid, f"zq{uuid.uuid4().hex[:10]}")
    await client.post(f"{est}/run", headers=h)
    w = (await _summary(client, h, pid))["wall_ext"]
    assert D(w["unit_rate"]) == 0 and "cost_no_match" in w["flags"] and "unpriced" in w["flags"]
    assert "cost_item" not in w["provenance"]


async def test_hand_rate_and_picked_item_survive_a_new_revision(client):
    uid, h, pid, tok = await _linked_project(client)
    region, token = f"DE_T{uuid.uuid4().hex[:6]}", f"zq{uuid.uuid4().hex[:8]}"
    await _set_project_region(pid, region)
    await _seed(region, token)
    other = await _seed(region, f"{token}b", rate="200")
    rows1 = example_rows()
    rid1, _ = await _publish(client, h, tok, pid, rows1)
    est = await _install(client, h, pid, token)
    await client.post(f"{est}/run", headers=h)
    pos = (await _summary(client, h, pid))["wall_ext"]["position_id"]
    assert "rate_override" not in (await _summary(client, h, pid))["wall_ext"]["flags"]

    await _set_rate(pos, "99")
    w = (await _summary(client, h, pid))["wall_ext"]
    assert D(w["unit_rate"]) == 99 and "rate_override" in w["flags"]
    rows2 = copy.deepcopy(rows1)
    next(r for r in rows2 if r["element_key"].endswith("wall-ext/0") or r["ifc_class"] == "IfcWall").update(
        area_m2=88.1, geometry_hash="9f2c4a1e0b7d3c66"
    )
    rid2, _ = await _publish(client, h, tok, pid, rows2, parent=rid1, parent_rows=rows1)
    w = (await _summary(client, h, pid))["wall_ext"]
    assert D(w["unit_rate"]) == 99 and "rate_override" in w["flags"] and "cost_auto" not in w["flags"]

    # a person picks another cost item in the picker: it replaces the hand rate and carries its own source
    r = await client.post(f"{est}/positions/{pos}/price", json={"cost_item_id": other}, headers=h)
    assert r.status_code == 204, r.text
    w = (await _summary(client, h, pid))["wall_ext"]
    assert D(w["unit_rate"]) == 200 and "rate_override" not in w["flags"]
    rows3 = copy.deepcopy(rows2)
    next(r for r in rows3 if r["ifc_class"] == "IfcWall").update(area_m2=90.0, geometry_hash="a1a1a1a1a1a1a1a1")
    await _publish(client, h, tok, pid, rows3, parent=rid2, parent_rows=rows2)
    w = (await _summary(client, h, pid))["wall_ext"]
    assert D(w["unit_rate"]) == 200 and w["provenance"]["cost_item"]["cost_item_id"] == other
    assert w["provenance"]["cost_item"]["auto"] is False and "cost_auto" not in w["flags"]
