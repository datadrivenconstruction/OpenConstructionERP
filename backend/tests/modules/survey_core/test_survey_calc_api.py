# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The course path through the API: demo field book, least squares, report, diary and document links."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["survey_calc"]
BASE = "/api/v1/survey-core"


async def test_demo_loads_and_computes_the_course_numbers(client: AsyncClient, header: dict) -> None:
    demo = (await client.get(f"{BASE}/calc/demo", headers=header)).json()
    tr = (await client.post(f"{BASE}/calc/field-traverse", json=demo["traverse"], headers=header)).json()
    exp = EXPECTED["traverse"]
    assert tr["angular_misclosure_sec"] == exp["angular_misclosure_sec"]
    assert tr["angular_allowed_sec"] == exp["angular_allowed_sec"]
    assert tr["angular_verdict"] == "pass"
    assert tr["ratio"] == exp["ratio"]
    assert tr["linear_verdict"] == "pass"
    lsq = tr["lsq"]
    assert tr["method"] == "lsq"
    assert lsq["sigma0"] == pytest.approx(exp["lsq"]["sigma0"], abs=6e-4)
    assert lsq["chi2_pass"] is True
    assert [s["station_id"] for s in lsq["stations"]] == ["T1", "T2", "T3", "T4"]
    assert not [f for f in tr["findings"] if f["rule_id"] in ("SRV-051", "SRV-052")]

    book = (await client.post(f"{BASE}/calc/level-book", json=demo["level_book"], headers=header)).json()
    assert book["misclosure_mm"] == EXPECTED["level_book"]["misclosure_mm"]
    assert book["allowed_mm"] == EXPECTED["level_book"]["allowed_mm"]
    assert book["verdict"] == "pass"


async def test_tight_weights_raise_the_global_test_finding(client: AsyncClient, header: dict) -> None:
    demo = (await client.get(f"{BASE}/calc/demo", headers=header)).json()
    body = {
        **demo["traverse"],
        "instrument_key": "ts_1",
        "angle_sd_sec": None,
        "dist_sd_mm": None,
        "dist_ppm": None,
        "centering_sd_mm": None,
    }
    tr = (await client.post(f"{BASE}/calc/field-traverse", json=body, headers=header)).json()
    assert tr["lsq"]["chi2_pass"] is False
    ids = {f["rule_id"] for f in tr["findings"]}
    assert {"SRV-051", "SRV-052"} <= ids


async def test_tight_level_class_raises_srv_011(client: AsyncClient, header: dict) -> None:
    demo = (await client.get(f"{BASE}/calc/demo", headers=header)).json()
    book = (await client.post(f"{BASE}/calc/level-book", json={**demo["level_book"], "k_mm": 4}, headers=header)).json()
    assert book["verdict"] == "fail"
    assert "SRV-011" in {f["rule_id"] for f in book["findings"]}


async def test_report_is_a_pdf(client: AsyncClient, header: dict) -> None:
    demo = (await client.get(f"{BASE}/calc/demo", headers=header)).json()
    res = await client.post(
        f"{BASE}/calc/field-traverse/report",
        json={"traverse": demo["traverse"], "title": "Bericht", "labels": {"station": "Punkt"}},
        headers=header,
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF")


async def test_saved_traverse_links_to_the_diary_and_a_document(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    demo = (await client.get(f"{BASE}/calc/demo", headers=header)).json()
    saved = await client.post(
        f"{BASE}/projects/{project_id}/field-traverses", json={**demo["traverse"], "save_points": True}, headers=header
    )
    assert saved.status_code == 201, saved.text
    traverse_id = saved.json()["traverse"]["id"]
    assert saved.json()["traverse"]["method"] == "field_lsq"

    link = await client.post(
        f"{BASE}/projects/{project_id}/survey-links/traverse/{traverse_id}/diary",
        json={
            "diary_date": "2026-10-14",
            "title": "Site control loop",
            "crew": "A. Field, B. Rod",
            "instrument": 'TS 5"',
            "weather": "Overcast 9 C",
        },
        headers=header,
    )
    assert link.status_code == 201, link.text
    diary_id = link.json()["diary_id"]

    # The diary side shows the entry with its source.
    entries = (await client.get(f"/api/v1/daily-diary/diaries/{diary_id}/entries", headers=header)).json()["items"]
    mine = [e for e in entries if e.get("source_module") == "survey_core"]
    assert mine and mine[0]["source_ref"] == traverse_id

    ref = await client.post(
        "/api/v1/file-references/",
        json={
            "project_id": project_id,
            "file_kind": "document",
            "file_id": "00000000-0000-0000-0000-000000000001",
            "target_type": "survey_traverse",
            "target_id": traverse_id,
            "target_label": "Site control loop",
        },
        headers=header,
    )
    assert ref.status_code == 201, ref.text

    links = (
        await client.get(f"{BASE}/projects/{project_id}/survey-links/traverse/{traverse_id}", headers=header)
    ).json()
    assert [d["crew"] for d in links["diary"]] == ["A. Field, B. Rod"]
    assert links["diary"][0]["diary_date"] == "2026-10-14"
    assert [d["file_kind"] for d in links["documents"]] == ["document"]


async def test_links_refuse_a_record_of_another_project(client: AsyncClient, header: dict, project_id: str) -> None:
    res = await client.get(
        f"{BASE}/projects/{project_id}/survey-links/traverse/00000000-0000-0000-0000-000000000009", headers=header
    )
    assert res.status_code == 404
