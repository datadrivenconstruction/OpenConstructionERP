# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stockpile course, lessons 1-5, through the API on PostgreSQL, on the installed Riverside Yard demo."""

from __future__ import annotations

import json
from pathlib import Path

from httpx import AsyncClient

from tests.modules.survey_core.conftest import (  # noqa: F401
    app_instance,
    client,
    header,
    login,
    project_id,
    viewer,
)

BASE = "/api/v1/stockpiles"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["stockpiles"]


async def _demo(client: AsyncClient, header: dict) -> tuple[str, dict]:
    # A fresh pile per test: a confirmed adjustment in one lesson would zero the next one's variance.
    installed = await client.post("/api/demo/install/survey-riverside-yard", params={"force": True}, headers=header)
    assert installed.status_code in (200, 201), installed.text
    pid = installed.json()["project_id"]
    [pile] = (await client.get(f"{BASE}/projects/{pid}/stockpiles", headers=header)).json()["items"]
    return pid, pile


async def _survey(client: AsyncClient, header: dict, pile_id: str, density: float, source: str) -> dict:
    r = await client.post(
        f"{BASE}/stockpiles/{pile_id}/surveys",
        json={
            "surveyed_on": EXPECTED["surveyed_on"],
            "pile_text": (DEMO / EXPECTED["survey_file"]).read_text(encoding="utf-8"),
            "pile_filename": EXPECTED["survey_file"],
            "density_t_m3": density,
            "density_source": source,
        },
        headers=header,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_demo_seeds_the_stockpile_and_lesson_1(client: AsyncClient, header: dict) -> None:
    _, pile = await _demo(client, header)
    assert pile["code"] == EXPECTED["code"]
    assert pile["name"] == EXPECTED["name"]
    assert pile["material"] == EXPECTED["material"]
    assert pile["book_tonnes"] == EXPECTED["lesson_1"]["book_tonnes"]
    assert pile["survey_count"] == 0


async def test_lessons_2_to_4_survey_variance_and_confirmed_adjustment(client: AsyncClient, header: dict) -> None:
    pid, pile = await _demo(client, header)

    l2 = EXPECTED["lesson_2"]
    s = await _survey(client, header, pile["id"], l2["density_t_m3"], l2["density_source"])
    assert s["volume_m3"] == l2["volume_m3"]
    assert s["cell_size_m"] == l2["cell_size_m"]
    assert s["coverage_pct"] == l2["coverage_pct"]
    assert s["tonnes"] == l2["tonnes"]
    assert (s["variance_t"], s["variance_pct"]) == (l2["variance_t"], l2["variance_pct"])
    assert l2["finding"] in {f["rule_id"] for f in s["findings"]}

    l3 = EXPECTED["lesson_3"]
    fixed = await client.patch(
        f"{BASE}/surveys/{s['id']}",
        json={"density_t_m3": l3["density_t_m3"], "density_source": l3["density_source"]},
        headers=header,
    )
    assert fixed.status_code == 200, fixed.text
    s = fixed.json()
    assert (s["tonnes"], s["variance_t"], s["variance_pct"]) == (l3["tonnes"], l3["variance_t"], l3["variance_pct"])
    rules = {f["rule_id"] for f in s["findings"]}
    assert l3["finding"] in rules
    assert l2["finding"] not in rules

    l4 = EXPECTED["lesson_4"]
    proposed = await client.post(f"{BASE}/surveys/{s['id']}/propose-adjustment", headers=header)
    assert proposed.status_code in (200, 201), proposed.text
    adj = proposed.json()
    assert adj["status"] == "proposed"
    assert adj["delta_t"] == l4["signed_t"]
    before = (await client.get(f"/api/v1/site-inventory/projects/{pid}/movements", headers=header)).json()

    confirmed = await client.post(f"{BASE}/adjustments/{adj['id']}/confirm", headers=header)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "booked"
    assert confirmed.json()["adjustment"]["status"] == "confirmed"
    assert confirmed.json()["adjustment"]["confirmed_by_name"]
    after = (await client.get(f"/api/v1/site-inventory/projects/{pid}/movements", headers=header)).json()
    booked = confirmed.json()["adjustment"]["movement_id"]
    assert booked not in {m["id"] for m in before}
    [move] = [m for m in after if m["id"] == booked]
    assert move["movement_type"] == l4["movement"]
    assert float(move["quantity"]) == l4["quantity_t"]

    detail = (await client.get(f"{BASE}/stockpiles/{pile['id']}", headers=header)).json()
    assert detail["book_tonnes"] == l4["book_after_t"]
    again = await client.post(f"{BASE}/adjustments/{adj['id']}/confirm", headers=header)
    assert again.status_code == 409


async def test_lesson_5_report_is_a_pdf_and_the_summary_follows(client: AsyncClient, header: dict) -> None:
    _, pile = await _demo(client, header)
    l3 = EXPECTED["lesson_3"]
    s = await _survey(client, header, pile["id"], l3["density_t_m3"], l3["density_source"])
    pdf = await client.get(f"{BASE}/surveys/{s['id']}/report.pdf", headers=header)
    assert pdf.status_code == 200
    assert pdf.content[:5] == b"%PDF-"
    summary = (await client.get(f"{BASE}/projects/{pile['project_id']}/summary", headers=header)).json()
    assert summary["stockpiles"] == 1
    assert summary["surveyed_tonnes"] == l3["tonnes"]
    assert summary["variance_pct"] == l3["variance_pct"]


async def test_a_viewer_reads_but_cannot_confirm(client: AsyncClient, header: dict, viewer: dict) -> None:
    pid, pile = await _demo(client, header)
    me = await client.get("/api/v1/users/me", headers=viewer)
    added = await client.post(
        f"/api/v1/projects/{pid}/members", json={"user_id": me.json()["id"], "role": "member"}, headers=header
    )
    assert added.status_code in (200, 201), added.text
    assert (await client.get(f"{BASE}/projects/{pid}/stockpiles", headers=viewer)).status_code == 200
    r = await client.post(f"{BASE}/stockpiles/{pile['id']}/surveys", json={"density_t_m3": 1.6}, headers=viewer)
    assert r.status_code == 403
