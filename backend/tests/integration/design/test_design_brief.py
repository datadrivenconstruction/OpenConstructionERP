"""R4: brief per project — versioned saves, If-Match, confirmations, link tokens read only."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest

from .conftest import LINK, make_project, make_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/design"
EXAMPLE = {
    "schema": "ddc-brief/1",
    "brief_id": str(uuid.uuid4()),
    "project_id": str(uuid.uuid4()),
    "version": 1,
    "country": "DE",
    "locale": "de",
    "depth_level": "D2",
    "use": {"category": "residential_multi"},
    "site": {
        "plot": {
            "type": "Polygon",
            "coordinates": [
                [[12.37, 51.34], [12.370575, 51.34], [12.370575, 51.340162], [12.37, 51.340162], [12.37, 51.34]]
            ],
        }
    },
    "massing": {"floors_above": 5, "floor_height_m": 3.0},
    "programme": {"units": [{"name": "2-Zimmer", "count": 10, "rooms": [{"kind": "living"}, {"kind": "bath"}]}]},
    "provenance": {
        "/massing/floors_above": {"status": "proposed", "sources": [{"kind": "user"}]},
        "/site/plot": {"status": "proposed", "sources": [{"kind": "map"}]},
    },
    "questions": [{"id": "q1", "pointer": "/massing/floors_above", "text": "Floors?", "options": [4, 5]}],
}


def _vendored_schema() -> dict:
    from app.modules.design import schema_check

    return json.loads((Path(schema_check.__file__).parent / "schemas" / "brief.schema.json").read_text("utf-8"))


async def _token(client, headers, project_id) -> dict:
    r = await client.post(f"{BASE}/link/code", json={"project_id": str(project_id), "action": "new"}, headers=headers)
    x = await client.post(f"{BASE}/link/exchange", json={"code": r.json()["code"]}, headers=LINK)
    return {"Authorization": f"Bearer {x.json()['token']}", **LINK}


async def test_save_versions_and_if_match(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    url = f"{BASE}/projects/{pid}/brief"
    assert (await client.get(url, headers=h)).status_code == 404

    first = await client.put(url, json=EXAMPLE, headers=h)
    assert first.status_code == 200, first.text
    doc = first.json()
    assert doc["version"] == 1 and doc["project_id"] == str(pid) and doc["brief_id"] != EXAMPLE["brief_id"]
    assert first.headers["ETag"] == '"1"'

    # Once a brief exists a save must name the version it was based on.
    assert (await client.put(url, json=doc, headers=h)).status_code == 428
    doc["massing"]["floors_above"] = 6
    second = await client.put(url, json=doc, headers={**h, "If-Match": '"1"'})
    assert second.status_code == 200 and second.json()["version"] == 2
    stale = await client.put(url, json=doc, headers={**h, "If-Match": "1"})
    assert stale.status_code == 409

    got = await client.get(url, headers=h)
    assert got.json()["massing"]["floors_above"] == 6 and got.headers["ETag"] == '"2"'
    old = await client.get(url, params={"version": 1}, headers=h)
    assert old.json()["massing"]["floors_above"] == 5 and old.json()["brief_id"] == doc["brief_id"]
    versions = (await client.get(f"{url}/versions", headers=h)).json()
    assert [v["version"] for v in versions] == [2, 1] and versions[0]["saved_by"] == str(uid)


async def test_invalid_brief_is_rejected_with_pointers(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    bad = copy.deepcopy(EXAMPLE)
    bad["massing"]["floors_above"] = 0
    bad["site"]["plot"]["coordinates"] = [[[0, 0], [1, 0], [0, 0]]]
    r = await client.put(f"{BASE}/projects/{pid}/brief", json=bad, headers=h)
    assert r.status_code == 422, r.text
    pointers = {e["pointer"] for e in r.json()["detail"]["errors"]}
    assert pointers == {"/massing/floors_above", "/site/plot/coordinates/0"}

    forged = copy.deepcopy(EXAMPLE)
    forged["provenance"]["/massing/floors_above"] = {"status": "confirmed", "confirmed_by": str(uid)}
    r = await client.put(f"{BASE}/projects/{pid}/brief", json=forged, headers=h)
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["pointer"] == "/provenance/~1massing~1floors_above"


async def test_confirm_records_person_and_survives_until_value_changes(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    url = f"{BASE}/projects/{pid}/brief"
    await client.put(url, json=EXAMPLE, headers=h)

    c = await client.post(
        f"{url}/confirm", json={"pointers": ["/massing/floors_above", "/site/plot"]}, headers={**h, "If-Match": "1"}
    )
    assert c.status_code == 200, c.text
    doc = c.json()
    entry = doc["provenance"]["/massing/floors_above"]
    assert doc["version"] == 2 and entry["status"] == "confirmed" and entry["confirmed_by"] == str(uid)
    assert entry["sources"] == [{"kind": "user"}] and doc["questions"] == []
    assert (await client.post(f"{url}/confirm", json={"pointers": ["/site/address"]}, headers=h)).status_code == 422
    assert (
        await client.post(f"{url}/confirm", json={"pointers": ["/site/plot"]}, headers={**h, "If-Match": "1"})
    ).status_code == 409

    doc["name"] = "Wohnhaus"  # unrelated edit keeps both confirmations
    kept = (await client.put(url, json=doc, headers={**h, "If-Match": "2"})).json()
    assert kept["provenance"]["/site/plot"]["confirmed_by"] == str(uid)
    kept["site"]["plot"]["coordinates"][0][1][0] = 12.3706
    moved = (await client.put(url, json=kept, headers={**h, "If-Match": "3"})).json()
    assert moved["provenance"]["/site/plot"]["status"] == "proposed"
    assert moved["provenance"]["/massing/floors_above"]["status"] == "confirmed"

    from app.modules.design.schema_check import validate

    assert validate(moved, _vendored_schema()) == []


async def test_link_token_reads_brief_but_cannot_write(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    url = f"{BASE}/projects/{pid}/brief"
    assert (await client.get(f"{BASE}/projects/{pid}/context", headers=tok)).json()["brief"] is None
    assert (await client.put(url, json=EXAMPLE, headers=tok)).status_code == 403
    await client.put(url, json=EXAMPLE, headers=h)
    assert (await client.post(f"{url}/confirm", json={"pointers": ["/site/plot"]}, headers=tok)).status_code == 403
    read = await client.get(url, headers=tok)
    assert read.status_code == 200 and read.json()["version"] == 1
    ctx = (await client.get(f"{BASE}/projects/{pid}/context", headers=tok)).json()
    assert ctx["brief"]["schema"] == "ddc-brief/1" and ctx["brief"]["version"] == 1


async def test_brief_is_scoped_to_project_access(client):
    owner, h_owner = await make_user(client)
    _, h_other = await make_user(client)
    pid = await make_project(owner)
    url = f"{BASE}/projects/{pid}/brief"
    await client.put(url, json=EXAMPLE, headers=h_owner)
    assert (await client.get(url, headers=h_other)).status_code == 404
    assert (await client.put(url, json=EXAMPLE, headers=h_other)).status_code == 404
    other_pid = await make_project(owner, name="Other")
    tok = await _token(client, h_owner, other_pid)
    assert (await client.get(url, headers=tok)).status_code == 404


async def test_draft_save_accepts_missing_required_values_only(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    url = f"{BASE}/projects/{pid}/brief"
    incomplete = copy.deepcopy(EXAMPLE)
    del incomplete["massing"]["floors_above"]
    incomplete.pop("questions")
    incomplete["provenance"].pop("/massing/floors_above")
    # Without the flag a missing required value is still refused.
    r = await client.put(url, json=incomplete, headers=h)
    assert r.status_code == 422 and {e["pointer"] for e in r.json()["detail"]["errors"]} == {"/massing/floors_above"}
    r = await client.put(url, params={"draft": "true"}, json=incomplete, headers=h)
    assert r.status_code == 200 and "floors_above" not in r.json()["massing"]
    # A draft is not a way around any other rule.
    bad = copy.deepcopy(incomplete)
    bad["massing"]["floor_height_m"] = -1
    r = await client.put(url, params={"draft": "true"}, json=bad, headers={**h, "If-Match": '"1"'})
    assert r.status_code == 422


async def test_values_of_a_draft_can_be_confirmed(client):
    """The start page saves what a template proposes (a draft: floors still missing), then confirms it."""
    uid, h = await make_user(client)
    pid = await make_project(uid)
    url = f"{BASE}/projects/{pid}/brief"
    incomplete = copy.deepcopy(EXAMPLE)
    del incomplete["massing"]["floors_above"]
    incomplete.pop("questions")
    incomplete["provenance"].pop("/massing/floors_above")
    assert (await client.put(url, params={"draft": "true"}, json=incomplete, headers=h)).status_code == 200
    r = await client.post(
        f"{url}/confirm", json={"pointers": ["/massing/floor_height_m"]}, headers={**h, "If-Match": '"1"'}
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert (
        doc["provenance"]["/massing/floor_height_m"]["status"] == "confirmed" and "floors_above" not in doc["massing"]
    )


def test_prepare_save_draft_drops_only_the_required_gap():
    from app.modules.design.brief_doc import BriefError, prepare_save

    doc = copy.deepcopy(EXAMPLE)
    del doc["massing"]["floors_above"]
    doc.pop("questions")
    doc["provenance"].pop("/massing/floors_above")
    ids = {"project_id": uuid.uuid4(), "brief_id": uuid.uuid4(), "version": 1}
    with pytest.raises(BriefError):
        prepare_save(doc, None, **ids)
    stored, _ = prepare_save(doc, None, **ids, draft=True)
    assert "floors_above" not in stored["massing"]
    doc["massing"]["floor_height_m"] = -1
    with pytest.raises(BriefError):
        prepare_save(doc, None, **ids, draft=True)
