"""Model -> BOQ -> totals in a non-EUR project: quantities follow revisions, money stays in one currency."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from .ddcrev import example_rows, package
from .test_design_revisions import BASE, _linked_project, _upload
from .test_estimate_rules import _by_rule, _rows2, _set_quantity

pytestmark = pytest.mark.asyncio


def D(v) -> Decimal:
    return Decimal(str(v))


async def _set_currency(pid: str, code: str) -> None:
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        (await s.get(Project, uuid.UUID(str(pid)))).currency = code
        await s.commit()


async def _price(client, est, h, pos, rate):
    body = {"unit_rate": rate, "source_url": "https://example.org/rates", "price_date": "2026-01-15", "currency": "CHF"}
    r = await client.post(f"{est}/positions/{pos}/price", headers=h, json=body)
    assert r.status_code == 204, r.text


async def test_revision_moves_priced_quantities_keeps_overrides_and_currency(client):
    uid, h, pid, tok = await _linked_project(client)
    await _set_currency(pid, "CHF")
    est = f"{BASE}/projects/{pid}/estimate"
    rows1 = example_rows()
    d1, m1 = package(pid, rows1)
    rev1 = (await _upload(client, pid, tok, d1)).json()
    assert (await client.post(f"{BASE}/revisions/{rev1['revision_id']}/accept", headers=h)).status_code == 200
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    s1 = (await client.get(est, headers=h)).json()
    p1 = _by_rule(s1)
    assert s1["currency"] == "CHF"
    # an EUR benchmark is never written as a CHF rate
    assert D(p1["site_works"]["unit_rate"]) == 0 and "rate_missing" in p1["site_works"]["flags"]
    assert p1["site_works"]["provenance"]["missing_code"] == "currency_mismatch"
    assert s1["inside_range"] is None and s1["inside_range_note_code"] == "currency_mismatch"

    slab, wall = p1["slab"]["position_id"], p1["wall_ext"]["position_id"]
    await _price(client, est, h, slab, "120")
    await _price(client, est, h, wall, "10")
    await _set_quantity(wall, "90")  # a person's quantity
    boq_id = s1["boq_id"]
    mk = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/markups/",
        headers=h,
        json={"name": "Overhead", "category": "overhead", "percentage": 10, "apply_to": "direct_cost"},
    )
    assert mk.status_code in (200, 201), mk.text

    s1b = (await client.get(est, headers=h)).json()
    # 401.2 m2 x 120 + 90 m2 x 10 = 48144 + 900
    assert D(s1b["total"]) == D("49044")
    assert D(s1b["boq"]["direct_cost"]) == D("49044")
    assert D(s1b["boq"]["markups_total"]) == D("4904.40")
    assert D(s1b["boq"]["grand_total"]) == D("53948.40") and s1b["boq"]["currency"] == "CHF"

    d2, m2 = package(pid, _rows2(), parent_id=m1["revision_id"], parent_rows=rows1)
    rev2 = (await _upload(client, pid, tok, d2)).json()
    assert (await client.post(f"{BASE}/revisions/{rev2['revision_id']}/accept", headers=h)).status_code == 200
    s2 = (await client.get(est, headers=h)).json()
    p2 = _by_rule(s2)
    assert D(p2["slab"]["quantity"]) == 405 and D(p2["slab"]["total"]) == D("48600")
    assert D(p2["wall_ext"]["quantity"]) == 90 and p2["wall_ext"]["override"]  # not overwritten
    assert D(s2["total"]) == D("49500")
    assert D(s2["boq"]["grand_total"]) == D("54450.00")

    # the cost history of the revision: before and after the accept, in the project currency
    co = (await client.get(f"{BASE}/revisions/{rev2['revision_id']}/change-order", headers=h)).json()
    assert co["cost"]["before"] == "49044.00" and co["cost"]["after"] == "49500.00"
    assert co["cost"]["delta"] == "456.00" and co["cost"]["currency"] == "CHF"

    # with change orders off the next revision still keeps its before/after totals
    off = await client.put(f"{BASE}/projects/{pid}/change-orders/settings", json={"mode": "off"}, headers=h)
    assert off.status_code == 200, off.text
    rows3 = _rows2()
    next(r for r in rows3 if r["element_key"] == "b1/s00/slab/0").update(
        area_m2=410.0, geometry_hash="0badc0de0badc0de"
    )
    d3, _ = package(pid, rows3, parent_id=m2["revision_id"], parent_rows=_rows2())
    rev3 = (await _upload(client, pid, tok, d3)).json()
    assert (await client.post(f"{BASE}/revisions/{rev3['revision_id']}/accept", headers=h)).status_code == 200
    co3 = (await client.get(f"{BASE}/revisions/{rev3['revision_id']}/change-order", headers=h)).json()
    assert co3["snapshot"] is False and co3["change_order"] is None
    assert co3["cost"]["before"] == "49500.00" and co3["cost"]["after"] == "50100.00"
