"""Field reports <-> the accepted revision's elements and BOQ positions, through the report's own metadata."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from .conftest import make_user
from .test_design_revisions import BASE, WALL
from .test_integration import _all_linked, _db
from .test_schedule import WALL_1OG

pytestmark = pytest.mark.asyncio


async def _report(pid, status="draft", text="Wall poured"):
    from app.modules.fieldreports.models import FieldReport

    async def make(s):
        r = FieldReport(
            project_id=uuid.UUID(str(pid)),
            report_date=date(2027, 3, 4),
            report_type="daily",
            work_performed=text,
            status=status,
        )
        s.add(r)
        await s.flush()
        rid = str(r.id)
        await s.commit()
        return rid

    return await _db(make)


async def test_report_is_linked_to_elements_and_found_from_the_element_and_back(client):
    uid, h, pid, tok, r2, est = await _all_linked(client)
    wall_pos = next(p for p in est["positions"] if p["rule"] == "wall_ext")["position_id"]
    rid = await _report(pid)
    other = await _report(pid, text="Unrelated")
    url = f"{BASE}/projects/{pid}/field-reports"
    assert (await client.get(url, params={"keys": [WALL_1OG]}, headers=h)).json()["items"] == []
    r = await client.put(f"{url}/{rid}/links", json={"keys": [WALL_1OG], "position_ids": [wall_pos]}, headers=h)
    assert r.status_code == 200, r.text
    # element -> reports: named directly, and through the position the element feeds
    hit = (await client.get(url, params={"keys": [WALL_1OG]}, headers=h)).json()["items"]
    assert [x["id"] for x in hit] == [rid] and hit[0]["matched_keys"] == [WALL_1OG]
    via = (await client.get(url, params={"keys": [WALL]}, headers=h)).json()["items"]  # same position, other element
    assert (
        [x["id"] for x in via] == [rid] and via[0]["matched_keys"] == [] and via[0]["matched_positions"] == [wall_pos]
    )
    assert {x["id"] for x in (await client.get(url, headers=h)).json()["items"]} >= {rid, other}
    # report -> elements: ids to isolate in the viewer, keys for the editor, the position
    e = (await client.get(f"{url}/{rid}/elements", headers=h)).json()
    assert e["keys"] == [WALL_1OG] and len(e["element_ids"]) == 1 and e["isolate"] == e["element_ids"] and e["model_id"]
    assert [p["position_id"] for p in e["positions"]] == [wall_pos]

    # the link sits in the report's own metadata field
    from app.modules.fieldreports.models import FieldReport

    async def meta(s):
        return (await s.get(FieldReport, uuid.UUID(rid))).metadata_

    assert (await _db(meta))["design"]["element_keys"] == [WALL_1OG]
    # empty lists remove the link
    assert (await client.put(f"{url}/{rid}/links", json={"keys": [], "position_ids": []}, headers=h)).status_code == 200
    assert (await client.get(url, params={"keys": [WALL_1OG]}, headers=h)).json()["items"] == []


async def test_only_elements_and_positions_of_the_accepted_revision_and_open_reports(client):
    uid, h, pid, tok, r2, est = await _all_linked(client)
    url = f"{BASE}/projects/{pid}/field-reports"
    rid = await _report(pid)
    assert (await client.put(f"{url}/{rid}/links", json={"keys": ["no/such/key"]}, headers=h)).status_code == 422
    assert (
        await client.put(f"{url}/{rid}/links", json={"position_ids": [str(uuid.uuid4())]}, headers=h)
    ).status_code == 422
    approved = await _report(pid, status="approved")
    assert (await client.put(f"{url}/{approved}/links", json={"keys": [WALL]}, headers=h)).status_code == 409
    assert (await client.put(f"{url}/{uuid.uuid4()}/links", json={"keys": [WALL]}, headers=h)).status_code == 404
    _, stranger = await make_user(client)
    assert (await client.put(f"{url}/{rid}/links", json={"keys": [WALL]}, headers=stranger)).status_code in (403, 404)
    assert (await client.get(url, headers=stranger)).status_code in (403, 404)
