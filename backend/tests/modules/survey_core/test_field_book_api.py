# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Field book API: the Riverside loop closes, a failing closure needs a reason, stations land in the register."""

from __future__ import annotations

from httpx import AsyncClient

BASE = "/api/v1/survey-core"


async def _book(client: AsyncClient, header: dict) -> dict:
    response = await client.get(f"{BASE}/calc/field-book/demo/riverside", headers=header)
    assert response.status_code == 200, response.text
    raw = response.json()
    return {
        "name": raw["name"],
        "shape": raw["shape"],
        "angle_unit": raw["angle_unit"],
        "angle_mode": raw["angle_mode"],
        "start": raw["start"],
        "backsight_id": raw["backsight_id"],
        "backsight_azimuth": raw["backsight_azimuth"],
        "closing_angle": raw["closing_angle"],
        "rows": [
            {
                **{k: r[k] for k in ("station", "bs", "fs", "face_l", "face_r", "dist_mode", "zenith", "note")},
                "distance": float(r["distance"]),
                "hi": float(r["hi"]),
                "ht": float(r["ht"]),
            }
            for r in raw["rows"]
        ],
        "angular_k_sec": 10,
        "min_ratio": 10000,
    }


async def test_riverside_book_closes_within_class(client: AsyncClient, header: dict) -> None:
    book = await _book(client, header)
    response = await client.post(f"{BASE}/calc/field-book", json=book, headers=header)
    assert response.status_code == 200, response.text
    body = response.json()
    trav = body["traverse"]
    assert round(trav["angular_misclosure_sec"]) == 13
    assert trav["angular_verdict"] == "pass"
    assert trav["linear_verdict"] == "pass"
    assert trav["ratio"] > 100_000
    assert [r["station"] for r in body["rows"]] == ["T1", "T2", "T3", "T4", "T5", "T6"]
    assert body["rows"][1]["face_diff_sec"] == -6.0
    assert body["fixed_end"]["station_id"] == "T1"
    assert len(body["unadjusted"]) == 6


async def test_failing_closure_needs_a_reason(client: AsyncClient, header: dict, project_id: str) -> None:
    book = await _book(client, header)
    book["angular_k_sec"] = 1
    refused = await client.post(f"{BASE}/projects/{project_id}/field-books", json=book, headers=header)
    assert refused.status_code == 422
    book["note"] = "Re-observed T4 next morning"
    book["save_points"] = True
    saved = await client.post(f"{BASE}/projects/{project_id}/field-books", json=book, headers=header)
    assert saved.status_code == 201, saved.text
    assert saved.json()["traverse"]["points_saved"] == 6


async def test_deflection_suffix_and_bad_angle(client: AsyncClient, header: dict) -> None:
    square = {
        "angle_unit": "deg",
        "angle_mode": "deflection",
        "start": {"station_id": "A", "e": 0, "n": 0},
        "backsight_azimuth": 0,
        "rows": [{"station": s, "face_l": "90L", "distance": 100} for s in "ABCD"],
        "angular_k_sec": 10,
    }
    ok = await client.post(f"{BASE}/calc/field-book", json=square, headers=header)
    assert ok.status_code == 200, ok.text
    assert ok.json()["traverse"]["misclosure_m"] < 1e-9
    square["rows"][1]["face_l"] = "ninety"
    bad = await client.post(f"{BASE}/calc/field-book", json=square, headers=header)
    assert bad.status_code == 422
