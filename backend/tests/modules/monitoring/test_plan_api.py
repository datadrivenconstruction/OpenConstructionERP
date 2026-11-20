# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Monitoring on the plan: points without E/N are listed, positions come from readings or a register mark."""

from __future__ import annotations

from httpx import AsyncClient

BASE = "/api/v1/monitoring"


async def test_pins_read_in_z_are_off_the_plan_until_placed(client: AsyncClient, header: dict, project_id: str) -> None:
    r = await client.post(f"{BASE}/projects/{project_id}/demo/riverside?epochs=4", headers=header)
    assert r.status_code == 200, r.text
    plan = (await client.get(f"{BASE}/projects/{project_id}/plan", headers=header)).json()
    assert plan["off_plan"] == 2
    assert {p["code"] for p in plan["items"] if p["e"] is None} == {"MP-01", "MP-02"}
    placed = await client.post(f"{BASE}/projects/{project_id}/demo/riverside/positions", headers=header)
    assert placed.status_code == 200, placed.text
    body = placed.json()
    assert body["off_plan"] == 0
    mp1 = next(p for p in body["items"] if p["code"] == "MP-01")
    assert (mp1["e"], mp1["n"], mp1["position_source"]) == (389130.5, 5819020.25, "mark")
    assert mp1["level"] == "action"
    assert mp1["displacement_mm"] == -23.0
    # Placing again moves the same mark, it does not add a second one.
    moved = await client.put(
        f"{BASE}/points/{mp1['id']}/position", json={"e": 389131.0, "n": 5819020.0}, headers=header
    )
    assert moved.status_code == 200, moved.text
    again = (await client.get(f"{BASE}/projects/{project_id}/plan", headers=header)).json()
    assert next(p for p in again["items"] if p["code"] == "MP-01")["e"] == 389131.0


async def test_a_prism_read_in_plan_takes_its_newest_reading(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    text = "point,date,e,n,z\nPR-1,2026-10-01,389100.000,5819000.000,35.000\nPR-1,2026-10-08,389100.004,5818999.997,35.000\n"
    r = await client.post(
        f"{BASE}/projects/{project_id}/readings", json={"text": text, "filename": "p.csv"}, headers=header
    )
    assert r.status_code in (200, 201), r.text
    plan = (await client.get(f"{BASE}/projects/{project_id}/plan", headers=header)).json()
    pr = next(p for p in plan["items"] if p["code"] == "PR-1")
    assert pr["position_source"] == "reading"
    assert (pr["e"], pr["n"]) == (389100.004, 5818999.997)
    assert (pr["de_mm"], pr["dn_mm"]) == (4.0, -3.0)
