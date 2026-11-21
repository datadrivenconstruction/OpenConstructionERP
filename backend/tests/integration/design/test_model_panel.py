"""Model panel: generator values with their ranges, new brief version, R13 job (fake ddc here)."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from .conftest import LINK, make_project, make_user
from .test_generation import BASE, _project_with_brief, _settle, _until, fake  # noqa: F401
from .test_mcp import _mcp_on  # noqa: F401

EXAMPLE = json.loads(
    (Path(__file__).resolve().parent / "contract" / "examples" / "brief.de-residential.json").read_text("utf-8")
)
AT = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
U1 = "00000000-0000-4000-8000-000000000001"


def _mp():
    from app.modules.design import model_params

    return model_params


# ── pure ────────────────────────────────────────────────────────────────────


def test_view_lists_only_generator_inputs_with_code_ranges():
    v = _mp().view(EXAMPLE)
    assert v["typology"] == "apartment_section" and v["brief_version"] == EXAMPLE["version"]
    by = {p["id"]: p for p in v["params"]}
    assert set(by) == {"floors", "floor_height", "width", "depth", "grid", "lift", "foundation", "roof", "roof_slope"}
    assert (by["floors"]["min"], by["floors"]["max"], by["floors"]["value"]) == (1, 200, 5)
    assert (by["floor_height"]["min"], by["floor_height"]["max"]) == (2.7, 6.0)
    assert (by["width"]["min"], by["width"]["max"], by["width"]["unit"]) == (6.0, 200.0, "m")
    assert (by["depth"]["min"], by["depth"]["max"]) == (7.6, 128.0)  # 2*3+1.6 .. 6.4+1.6+120
    assert by["foundation"]["options"] == ["raft", "strip", None] and by["foundation"]["value"] == "raft"
    assert by["grid"]["value"] is None and by["grid"]["default"] == 7.2
    assert [u["per_floor"] for u in v["units"]] == [2, 2] and v["max_units_per_floor"] == 12
    floor_up = next(p for p in v["presets"] if p["id"] == "floor_up")["values"]
    assert floor_up == {"/massing/floors_above": 6, "/programme/units/0/count": 12, "/programme/units/1/count": 12}


def test_house_and_unknown_use():
    house = copy.deepcopy(EXAMPLE)
    house["generator"] = {"template": "house"}
    v = _mp().view(house)
    assert next(p for p in v["params"] if p["id"] == "floors")["max"] == 3
    assert not any(p["id"] == "floor_up" for p in v["presets"])  # 5 floors is already past a house
    other = copy.deepcopy(EXAMPLE)
    other.pop("generator")
    other["use"] = {"category": "warehouse"}
    assert _mp().view(other)["typology"] is None and _mp().view(other)["params"] == []


def test_site_limit_preset_from_max_height():
    doc = copy.deepcopy(EXAMPLE)
    doc["site"].pop("max_floors")  # the example caps at 5 = today
    doc["site"]["max_height_m"] = 22.0  # 22 // 3.0 = 7 storeys
    p = next(p for p in _mp().view(doc)["presets"] if p["id"] == "site_limit")
    assert p["values"]["/massing/floors_above"] == 7 and p["values"]["/programme/units/0/count"] == 14


def test_apply_sets_confirms_and_refuses_out_of_range():
    mp = _mp()
    out, changed = mp.apply(
        EXAMPLE,
        {"/massing/floors_above": 6, "/structure/grid_m": 6.0, "/structure/foundation": "raft"},
        user_id=U1,
        at=AT,
    )
    assert changed == ["/massing/floors_above", "/structure/grid_m"]  # raft was already set
    assert out["massing"]["floors_above"] == 6 and out["structure"]["grid_m"] == 6.0
    assert out["provenance"]["/structure/grid_m"]["status"] == "confirmed"
    assert out["provenance"]["/massing/floors_above"]["confirmed_by"] == U1
    assert EXAMPLE["massing"]["floors_above"] == 5  # input untouched
    none, _ = mp.apply(EXAMPLE, {"/structure/foundation": None}, user_id=U1, at=AT)
    assert "foundation" not in none["structure"] and "/structure/foundation" not in none["provenance"]
    with pytest.raises(mp.BriefError) as e:
        mp.apply(
            EXAMPLE,
            {
                "/massing/floors_above": 201,
                "/massing/floor_height_m": 2.5,
                "/structure/foundation": "piles",
                "/site/max_floors": 3,
                "/massing/lift": "yes",
            },
            user_id=U1,
            at=AT,
        )
    assert {x["pointer"] for x in e.value.errors} == {
        "/massing/floors_above",
        "/massing/floor_height_m",
        "/structure/foundation",
        "/site/max_floors",
        "/massing/lift",
    }


def test_apply_checks_units_per_floor_and_spec_overrides():
    mp = _mp()
    with pytest.raises(mp.BriefError) as e:  # 30/5 + 40/5 = 14 flats on one floor
        mp.apply(EXAMPLE, {"/programme/units/0/count": 30, "/programme/units/1/count": 40}, user_id=U1, at=AT)
    assert e.value.errors[0]["pointer"] == "/programme/units"
    doc = copy.deepcopy(EXAMPLE)
    doc["generator"]["spec_overrides"] = {"floors": 3}
    assert next(p for p in mp.view(doc)["params"] if p["id"] == "floors")["overridden"] is True
    with pytest.raises(mp.BriefError):
        mp.apply(doc, {"/massing/floors_above": 4}, user_id=U1, at=AT)


# ── routes ──────────────────────────────────────────────────────────────────

pytest_asyncio_mark = pytest.mark.asyncio


@pytest_asyncio_mark
async def test_model_generate_writes_a_version_and_runs_the_job(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    v = (await client.get(f"{BASE}/projects/{pid}/model", headers=h)).json()
    assert v["brief_version"] == version
    fake.project_id = str(pid)
    r = await client.post(
        f"{BASE}/projects/{pid}/model/generate",
        headers=h,
        json={"brief_version": version, "values": {"/massing/floors_above": 6}},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["brief_version"] == version + 1 and body["changed"] == ["/massing/floors_above"]
    j = await _until(client, h, body["job_id"], {"done", "failed"})
    await _settle(fake)
    assert j["status"] == "done", j
    brief = (await client.get(f"{BASE}/projects/{pid}/brief", headers=h)).json()
    assert brief["version"] == version + 1 and brief["massing"]["floors_above"] == 6
    assert [p.argv[1] for p in fake.procs] == ["gen", "publish"]
    versions = (await client.get(f"{BASE}/projects/{pid}/brief/versions", headers=h)).json()["items"]
    assert versions[0]["action"] == "model"
    revs = (await client.get(f"{BASE}/projects/{pid}/revisions", headers=h)).json()["items"]
    assert revs[0]["revision_id"] == j["revision_id"]  # brief_version in the package: real ddc, tools/e2e test_95


@pytest_asyncio_mark
async def test_model_generate_without_changes_builds_the_confirmed_brief(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    fake.project_id = str(pid)
    r = await client.post(
        f"{BASE}/projects/{pid}/model/generate", headers=h, json={"brief_version": version, "values": {}}
    )
    assert r.status_code == 202, r.text
    assert r.json()["brief_version"] == version and not r.json()["changed"]
    j = await _until(client, h, r.json()["job_id"], {"done", "failed"})
    await _settle(fake)
    assert j["status"] == "done", j
    assert (await client.get(f"{BASE}/projects/{pid}/brief", headers=h)).json()["version"] == version


@pytest_asyncio_mark
async def test_model_generate_gates(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    url = f"{BASE}/projects/{pid}/model/generate"
    ok = {"brief_version": version, "values": {"/massing/floors_above": 6}}
    r = await client.post(url, headers=h, json={**ok, "values": {"/massing/floors_above": 999}})
    assert r.status_code == 422 and r.json()["detail"]["errors"][0]["pointer"] == "/massing/floors_above"
    assert (await client.post(url, headers=h, json={**ok, "brief_version": version + 5})).status_code == 409
    viewer, hv = await make_user(client, role="viewer")
    assert (await client.post(url, headers=hv, json=ok)).status_code in (403, 404)
    # an open editor holds the lock: 409, and no brief version is written
    code = await client.post(f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers={**h, **LINK})
    tok = (await client.post(f"{BASE}/link/exchange", json={"code": code.json()["code"]}, headers=LINK)).json()
    lh = {"Authorization": f"Bearer {tok['token']}", **LINK}
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=lh)).status_code == 200
    r = await client.post(url, headers=h, json=ok)
    assert r.status_code == 409 and "being edited" in r.text
    assert (await client.post(url, headers=lh, json=ok)).status_code == 403  # link tokens never start it
    assert (await client.get(f"{BASE}/projects/{pid}/brief", headers=h)).json()["version"] == version
    assert fake.procs == []


@pytest_asyncio_mark
async def test_model_generate_no_worker_writes_no_brief_version(client, fake, monkeypatch):
    from app.modules.design import worker_guard

    uid, h, pid, version = await _project_with_brief(client)
    monkeypatch.setattr(worker_guard, "_worker_state", lambda: "none")
    r = await client.post(
        f"{BASE}/projects/{pid}/model/generate",
        headers=h,
        json={"brief_version": version, "values": {"/massing/floors_above": 6}},
    )
    assert r.status_code == 503 and r.json()["detail"]["code"] == worker_guard.NO_WORKER
    assert (await client.get(f"{BASE}/projects/{pid}/brief", headers=h)).json()["version"] == version
    assert fake.procs == []


@pytest_asyncio_mark
async def test_model_preview_is_the_generate_brief_and_stores_nothing(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    url = f"{BASE}/projects/{pid}/model/preview"
    r = await client.post(url, headers=h, json={"brief_version": version, "values": {"/massing/floors_above": 6}})
    assert r.status_code == 200, r.text
    doc = r.json()["brief"]
    assert doc["massing"]["floors_above"] == 6
    assert doc["provenance"]["/massing/floors_above"]["status"] == "confirmed"
    same = (await client.post(url, headers=h, json={"brief_version": version})).json()["brief"]
    head = (await client.get(f"{BASE}/projects/{pid}/brief", headers=h)).json()
    assert head["version"] == version and head["massing"]["floors_above"] == same["massing"]["floors_above"]
    r = await client.post(url, headers=h, json={"brief_version": version, "values": {"/massing/floors_above": 999}})
    assert r.status_code == 422
    assert (await client.post(url, headers=h, json={"brief_version": version + 1})).status_code == 409
    versions = (await client.get(f"{BASE}/projects/{pid}/brief/versions", headers=h)).json()["items"]
    assert all(v["action"] != "model" for v in versions) and fake.procs == []


@pytest_asyncio_mark
async def test_model_preview_of_an_unconfirmed_brief_says_why(client, fake):
    uid, h, pid, version = await _project_with_brief(client, confirm=False)
    r = await client.post(f"{BASE}/projects/{pid}/model/preview", headers=h, json={"brief_version": version})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["brief"] is None and body["problems"]["unconfirmed"] and fake.procs == []


@pytest_asyncio_mark
async def test_model_view_without_brief(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    assert (await client.get(f"{BASE}/projects/{pid}/model", headers=h)).status_code == 404


def test_units_per_floor_follow_the_width():
    mp = _mp()
    narrow = copy.deepcopy(EXAMPLE)
    narrow["massing"]["footprint"]["width_m"] = 15.0  # 2 x floor(15 / 5) = 6 flats a floor
    assert mp.view(narrow)["max_units_per_floor"] == 6
    with pytest.raises(mp.BriefError):  # 20/5 + 20/5 = 8 > 6
        mp.apply(narrow, {"/programme/units/0/count": 20, "/programme/units/1/count": 20}, user_id=U1, at=AT)
    # widening in the same step lifts the limit: 60 m holds 24
    out, _ = mp.apply(
        EXAMPLE,
        {"/massing/footprint/width_m": 60.0, "/programme/units/0/count": 50, "/programme/units/1/count": 50},
        user_id=U1,
        at=AT,
    )
    assert mp.view(out)["max_units_per_floor"] == 24
