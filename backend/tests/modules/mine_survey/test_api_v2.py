# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey v2 through the API: drive advance and profiles, blast patterns, viewer limits."""

from __future__ import annotations

from httpx import AsyncClient

from tests.modules.survey_core.conftest import (  # noqa: F401
    app_instance,
    client,
    header,
    login,
    project_id,
    viewer,
)

BASE = "/api/v1/mine-survey"


async def _period(client: AsyncClient, header: dict, pid: str, **extra: object) -> dict:
    r = await client.post(f"{BASE}/projects/{pid}/periods", json={"label": "2026-10", **extra}, headers=header)
    assert r.status_code == 201, r.text
    return r.json()


async def test_drive_advance_and_overbreak_from_the_worked_example(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    period = await _period(client, header, project_id, overbreak_tol_pct=10)
    unit = await client.post(
        f"{BASE}/projects/{project_id}/units",
        json={
            "name": "Decline D1",
            "unit_type": "drive",
            "density_t_m3": 2.75,
            "design_ch_from_m": 400,
            "design_ch_to_m": 440,
            "design_area_m2": 25.6,
        },
        headers=header,
    )
    assert unit.status_code == 201, unit.text
    uid = unit.json()["id"]
    for ch in (412.6, 432.6):
        r = await client.post(
            f"{BASE}/units/{uid}/faces", json={"chainage_m": ch, "period_id": period["id"]}, headers=header
        )
        assert r.status_code == 201, r.text
    for ch in (415, 420, 425, 430):
        r = await client.post(
            f"{BASE}/units/{uid}/profiles",
            json={"chainage_m": ch, "actual_area_m2": 28.4, "period_id": period["id"]},
            headers=header,
        )
        assert r.status_code == 201, r.text
    outside = await client.post(
        f"{BASE}/units/{uid}/profiles", json={"chainage_m": 455, "actual_area_m2": 28.4}, headers=header
    )
    assert outside.json()["inside_design"] is False

    d = (await client.get(f"{BASE}/units/{uid}/drive", params={"period_id": period["id"]}, headers=header)).json()
    s = d["summary"]
    assert s["advance_m"] == 20.0
    assert s["overbreak_pct"] == 10.94
    assert s["excess_m3"] == 56.0
    assert s["excess_t"] == 154.0
    assert "SRV-091" in {f["rule_id"] for f in d["findings"]}

    everything = (await client.get(f"{BASE}/units/{uid}/drive", headers=header)).json()
    assert "SRV-092" in {f["rule_id"] for f in everything["findings"]}


async def test_blast_pattern_judges_the_as_drilled_holes(client: AsyncClient, header: dict, project_id: str) -> None:
    design = "hole,e,n,z,depth\nH1,1000.00,2000.00,150.0,12.0\nH2,1003.50,2000.00,150.0,12.0\n"
    created = await client.post(
        f"{BASE}/projects/{project_id}/blast-patterns",
        json={"name": "Bench 150 shot 1", "collar_tol_m": 0.30, "depth_tol_m": 0.30, "design_text": design},
        headers=header,
    )
    assert created.status_code == 201, created.text
    p = created.json()
    assert (p["code"], p["holes"], p["drilled"]) == ("BP-001", 2, 0)
    assert p["findings"] == []

    stake = await client.get(f"{BASE}/blast-patterns/{p['id']}/stake-list.csv", headers=header)
    assert stake.status_code == 200
    assert stake.text.splitlines()[0].startswith("H1,2000.000,1000.000,150.000")

    drilled = "hole,e,n,z,depth\nH1,1000.32,2000.00,150.0,12.1\nH2,1003.50,2000.05,150.0,11.4\nH9,1,1,1,1\n"
    r = await client.post(f"{BASE}/blast-patterns/{p['id']}/as-drilled", json={"text": drilled}, headers=header)
    assert r.status_code == 200, r.text
    d = r.json()
    by = {h["hole_id"]: h for h in d["items"]}
    assert (by["H1"]["collar_ok"], by["H1"]["depth_ok"]) == (False, True)
    assert (by["H2"]["collar_ok"], by["H2"]["depth_ok"]) == (True, False)
    assert d["failed"] == 2
    assert [f["rule_id"] for f in d["findings"]] == ["SRV-093", "SRV-093"]
    assert any("H9" in x for x in d["problems"])


async def test_a_viewer_reads_patterns_but_cannot_create_them(
    client: AsyncClient, header: dict, viewer: dict, project_id: str
) -> None:
    denied = await client.post(f"{BASE}/projects/{project_id}/blast-patterns", json={"name": "x"}, headers=viewer)
    assert denied.status_code == 403
