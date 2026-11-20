# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A failed stake is followed up: SET-003, automatic and bulk NCR drafts, accepted deviations.

Numbers come from ``demo/riverside/expected.json`` lessons 3 and 5 (C-03 off by 15 mm against 10 mm).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.validation.engine import ValidationContext
from app.modules.setting_out.validators import FailureResolvedRule

BASE = "/api/v1/setting-out"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "setting_out" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["setting_out"]
L3, L5 = EXPECTED["lesson_3"], EXPECTED["lesson_5"]


def _row(**kw: object) -> dict:
    return {"request": "SO-001", "point_id": "C-03", "measured": True, "verdict": "fail", **kw}


@pytest.mark.parametrize(
    ("row", "fires"),
    [
        (_row(), True),
        (_row(ncr_id="n-1"), False),
        (_row(deviation_accepted=True), False),
        (_row(verdict="pass"), False),
        (_row(measured=False, verdict="open"), False),
    ],
)
async def test_set_003(row: dict, fires: bool) -> None:
    results = await FailureResolvedRule().validate(ValidationContext(data={"stakes": [row]}, metadata={"locale": "en"}))
    assert (not results[0].passed) is fires
    if fires:
        assert results[0].message == L5["finding"]
        assert results[0].element_ref == "SO-001/C-03"


async def _demo(client: AsyncClient, header: dict, project_id: str) -> dict:
    response = await client.post(f"{BASE}/projects/{project_id}/demo/riverside", headers=header)
    assert response.status_code == 200, response.text
    return response.json()


async def _fail_c03(client: AsyncClient, header: dict, detail: dict) -> dict:
    stake = next(s for s in detail["stakes"] if s["point_id"] == L3["point"])
    m = L3["measured"]
    response = await client.post(
        f"{BASE}/stakes/{stake['id']}/records",
        json={"measured_e": m["e"], "measured_n": m["n"], "measured_z": m["z"]},
        headers=header,
    )
    assert response.status_code == 201, response.text
    rec = response.json()
    assert (rec["d_mm"], rec["verdict"]) == (L3["d_mm"], "fail")
    return rec


async def _rules(client: AsyncClient, header: dict, project_id: str) -> list[str]:
    report = (await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)).json()
    return [f["rule_id"] for f in report["findings"]]


async def _ncr(client: AsyncClient, header: dict, project_id: str, ncr_id: str) -> dict | None:
    quality = await client.get(f"/api/v1/ncr/?project_id={project_id}", headers=header)
    if quality.status_code != 200:
        return None
    body = quality.json()
    items = body if isinstance(body, list) else body.get("items", [])
    return next(i for i in items if i["id"] == ncr_id)


async def test_settings_default_off_and_validated(client: AsyncClient, header: dict, project_id: str) -> None:
    settings = (await client.get(f"{BASE}/projects/{project_id}/settings", headers=header)).json()
    assert settings == {"default_tolerance_key": "", "auto_ncr": L5["auto_ncr_default"]}
    bad = await client.put(
        f"{BASE}/projects/{project_id}/settings", json={"default_tolerance_key": "pack:nope"}, headers=header
    )
    assert bad.status_code == 422
    ok = await client.put(
        f"{BASE}/projects/{project_id}/settings",
        json={"default_tolerance_key": "demo", "auto_ncr": True},
        headers=header,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"default_tolerance_key": "demo", "auto_ncr": True}


async def test_auto_ncr_opens_the_draft_with_deviation_tolerance_and_source(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    detail = await _demo(client, header, project_id)
    put = await client.put(f"{BASE}/projects/{project_id}/settings", json={"auto_ncr": True}, headers=header)
    assert put.status_code == 200
    rec = await _fail_c03(client, header, detail)
    assert rec["ncr_id"], "the failed stake opened its NCR draft on its own"
    assert await _rules(client, header, project_id) == [L3["rule"]]
    ncr = await _ncr(client, header, project_id, rec["ncr_id"])
    if ncr is not None:
        for quote in L5["ncr_quotes"]:
            assert quote in ncr["description"]
        assert ncr["metadata"]["tolerance_reference"] == "Demo values, not a standard"


async def test_bulk_ncr_then_set_003_clears(client: AsyncClient, header: dict, project_id: str) -> None:
    detail = await _demo(client, header, project_id)
    await _fail_c03(client, header, detail)
    assert await _rules(client, header, project_id) == [L3["rule"], L5["rule"]]
    bulk = await client.post(f"{BASE}/projects/{project_id}/ncr-drafts", headers=header)
    assert bulk.status_code == 200, bulk.text
    assert (len(bulk.json()["created"]), bulk.json()["skipped"]) == (L5["bulk_ncr_created"], 0)
    again = (await client.post(f"{BASE}/projects/{project_id}/ncr-drafts", headers=header)).json()
    assert (again["created"], again["skipped"]) == ([], 1)
    assert await _rules(client, header, project_id) == [L3["rule"]]


async def test_accepted_deviation_clears_set_003_and_blocks_the_ncr(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    detail = await _demo(client, header, project_id)
    rec = await _fail_c03(client, header, detail)
    empty = await client.post(f"{BASE}/records/{rec['id']}/accept-deviation", json={"note": ""}, headers=header)
    assert empty.status_code == 422
    done = await client.post(
        f"{BASE}/records/{rec['id']}/accept-deviation", json={"note": "Engineer accepts 15 mm"}, headers=header
    )
    assert done.status_code == 200, done.text
    assert done.json()["deviation_accepted_at"] and done.json()["deviation_note"] == "Engineer accepts 15 mm"
    assert L5["accepted_deviation_clears_rule"] is True
    assert await _rules(client, header, project_id) == [L3["rule"]]
    assert (await client.post(f"{BASE}/records/{rec['id']}/ncr", headers=header)).status_code == 409
    twice = await client.post(f"{BASE}/records/{rec['id']}/accept-deviation", json={"note": "x"}, headers=header)
    assert twice.status_code == 409


async def test_request_keeps_the_tolerance_source(client: AsyncClient, header: dict, project_id: str) -> None:
    detail = await _demo(client, header, project_id)
    assert detail["tolerance_reference"] == "Demo values, not a standard"
    profiles = (await client.get(f"{BASE}/projects/{project_id}/profiles", headers=header)).json()["items"]
    demo = next(p for p in profiles if p["key"] == "demo")
    assert demo["items"]["default"] == {"h_mm": 10.0, "v_mm": 10.0, "clause": "", "status": ""}
