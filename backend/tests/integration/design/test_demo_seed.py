"""Demo design seed: a confirmed brief from the project record, the converter model as revision 1, re-run safe."""

from __future__ import annotations

import types
import uuid
from datetime import UTC, datetime

import pytest

from .conftest import make_user
from .test_imported_revisions import _converter_model

BASE = "/api/v1/design"


def _project(**kw):
    base = {
        "id": uuid.uuid4(),
        "name": "Wohnanlage Berlin-Mitte",
        "country_code": "DE",
        "locale": "de",
        "currency": "EUR",
        "address": {"lat": 52.5316, "lng": 13.3766, "city": "Berlin", "street": "Chausseestrasse 45"},
        "gross_floor_area": None,
        "budget_estimate": None,
        "contract_value": None,
        "metadata_": {"demo_id": "residential-berlin", "storeys": 6, "gfa_m2": 7800, "units": 48},
    }
    base.update(kw)
    return types.SimpleNamespace(**base)


def _confirmed(project) -> dict:
    from app.modules.design.brief_doc import apply_confirm, prepare_save
    from app.modules.design.seed import _provenance, brief_for

    body, source = brief_for(project)
    body["provenance"] = _provenance(source)
    saved, _ = prepare_save(body, None, project_id=project.id, brief_id=uuid.uuid4(), version=1)
    return apply_confirm(saved, sorted(source), user_id=uuid.uuid4(), at=datetime.now(UTC), version=2)


def _generator_problems(doc: dict) -> list:
    from app.modules.design import model_params as mp
    from app.modules.design.jobs import brief_problems

    view = mp.view(doc)
    assert view["typology"], view["reason"]
    params = {p.id: p for p in mp.params_for(doc, view["typology"])}
    out = [(p["id"], mp._check(params[p["id"]], p["value"])) for p in view["params"]]
    out = [x for x in out if x[1]]
    cap = view.get("max_units_per_floor")
    out += [("units", u) for u in view["units"] if cap and u["per_floor"] > cap]
    if brief_problems(doc):
        out.append(("brief", brief_problems(doc)))
    return out


# ── the worked examples: record values in, a brief the preview builds from out ──


def test_residential_record_becomes_a_confirmed_apartment_block():
    doc = _confirmed(_project())
    assert doc["use"]["category"] == "residential_multi" and doc["generator"]["template"] == "apartment_section"
    m = doc["massing"]
    assert (m["floors_above"], m["floors_below"], m["gross_floor_area_m2"]) == (6, 0, 7800.0)
    assert doc["programme"]["units"][0]["count"] == 48
    # 7800 m2 over 6 storeys at 14.4 m depth: a 90.3 m slab
    assert m["footprint"] == {"width_m": 90.3, "depth_m": 14.4}
    assert doc["site"]["address"] == "Chausseestrasse 45, Berlin" and doc["site"]["plot"]["type"] == "Polygon"
    assert all(e["status"] == "confirmed" and e["confirmed_by"] for e in doc["provenance"].values())
    assert doc["version"] == 2 and doc["country"] == "DE" and doc["locale"] == "de"
    assert _generator_problems(doc) == []


@pytest.mark.parametrize(
    ("meta", "category", "template", "above", "below"),
    [
        (
            {"demo_id": "mixed-use-x", "storeys": "2 basements, ground and 15 upper floors", "flats": 120},
            "mixed_use",
            "apartment_section",
            16,
            2,
        ),
        ({"demo_id": "govt-building-x", "storeys": "G+5 with one basement", "gfa_m2": 7800}, "office", "office", 6, 1),
        (
            {"demo_id": "office-x", "storeys": "(32 above grade, 3 basements)", "gfa_m2": 86000},
            "office",
            "office",
            32,
            3,
        ),
        ({"demo_id": "warehouse-x", "gfa_m2": 45000, "clear_height_m": 12}, "warehouse", "office", 1, 0),
        ({"demo_id": "school-x", "storeys": 9, "pupil_places": 825}, "school", "school", 5, 0),
        ({"demo_id": "flagship-house"}, "residential_single", "house", 2, 0),
    ],
)
def test_record_phrases_and_limits(meta, category, template, above, below):
    doc = _confirmed(_project(name="Test building", metadata_=meta, address=None))
    assert doc["use"]["category"] == category and doc["generator"]["template"] == template
    assert (doc["massing"]["floors_above"], doc["massing"]["floors_below"]) == (above, below)
    assert "site" not in doc
    assert _generator_problems(doc) == []


def test_no_country_no_brief():
    from app.modules.design.seed import brief_for

    assert brief_for(_project(country_code=None)) is None


# ── the step on a database ──


async def _demo_project(owner: uuid.UUID, meta: dict, *, name="Wohnanlage Test", country="DE") -> uuid.UUID:
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            Project(
                id=pid,
                name=name,
                owner_id=owner,
                status="active",
                currency="EUR",
                country_code=country,
                locale="de",
                metadata_=meta,
            )
        )
        await s.commit()
    return pid


async def _run(pids: list[uuid.UUID]) -> dict:
    from app.database import async_session_factory
    from app.modules.design.seed import seed_design_demo

    async with async_session_factory() as s:
        counts = await seed_design_demo(s, pids)
        await s.commit()
    return counts


async def _state(pid: uuid.UUID) -> tuple[int, int, int]:
    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.design.brief_models import DesignBrief, DesignBriefVersion
    from app.modules.design.models import DesignEstimate, DesignRevision

    async with async_session_factory() as s:

        async def n(q):
            return (await s.execute(q)).scalar_one()

        return (
            await n(select(func.count()).select_from(DesignRevision).where(DesignRevision.project_id == pid)),
            await n(
                select(func.count())
                .select_from(DesignBriefVersion)
                .join(DesignBrief, DesignBrief.id == DesignBriefVersion.brief_id)
                .where(DesignBrief.project_id == pid)
            ),
            await n(select(func.count()).select_from(DesignEstimate).where(DesignEstimate.project_id == pid)),
        )


async def test_seed_writes_brief_and_revision_once(client):
    uid, h = await make_user(client, role="admin")
    meta = {"demo_id": "residential-test", "storeys": 4, "gfa_m2": 2400, "apartments": 16}
    pid = await _demo_project(uid, meta)
    mid = await _converter_model(pid)
    plain = await _demo_project(uid, {}, name="Real project")

    first = await _run([pid, plain])
    assert first["briefs"] == 1 and first["revisions"] == 1

    brief = (await client.get(f"{BASE}/projects/{pid}/brief", headers=h)).json()
    assert brief["version"] == 2 and brief["massing"]["floors_above"] == 4
    assert all(e["status"] == "confirmed" for e in brief["provenance"].values())
    assert _generator_problems(brief) == []
    revs = (await client.get(f"{BASE}/projects/{pid}/revisions", headers=h)).json()["items"]
    assert [(r["number"], r["source_kind"], r["bim_model_id"]) for r in revs] == [(1, "imported", str(mid))]
    assert (await client.get(f"{BASE}/projects/{plain}/brief", headers=h)).status_code == 404

    before = await _state(pid)
    assert before == (1, 2, 1), "DE residential: the starter rules are installed and run on revision 1"
    again = await _run([pid, plain])
    assert again == {"briefs": 0, "revisions": 0, "estimate_positions": 0}
    assert await _state(pid) == before


async def test_seed_brief_without_a_model_and_no_estimate_for_other_uses(client):
    uid, h = await make_user(client, role="admin")
    pid = await _demo_project(uid, {"demo_id": "retail-market-test", "gfa_m2": 2840}, name="Lebensmittelmarkt Test")
    counts = await _run([pid])
    assert counts["briefs"] == 1 and counts["revisions"] == 0
    assert await _state(pid) == (0, 2, 0)
    editor = (await client.get(f"{BASE}/projects/{pid}/model", headers=h)).json()
    assert editor["typology"] == "office"


async def test_shared_sample_model_is_never_the_design_of_a_tower(client):
    uid, _ = await make_user(client, role="admin")
    low = await _demo_project(uid, {"demo_id": "low-test", "storeys": 4, "gfa_m2": 2400, "apartments": 16})
    towers = [
        await _demo_project(uid, {"demo_id": f"tower-{i}", "storeys": 30, "gfa_m2": 60000}, name=f"Tower {i}")
        for i in range(2)
    ]
    for pid in [low, *towers]:
        await _converter_model(pid)  # the same sample model in three projects

    counts = await _run([low, *towers])
    assert counts["briefs"] == 3 and counts["revisions"] == 1
    assert (await _state(low))[0] == 1
    assert [(await _state(t))[0] for t in towers] == [0, 0]


# ── who may edit: an administrator does, a viewer does not ──


async def test_admin_edits_the_design_viewer_looks(client):
    owner, _ = await make_user(client)
    pid = await _demo_project(owner, {"demo_id": "rights-test"})
    _, admin = await make_user(client, role="admin")
    rights = (await client.get(f"{BASE}/projects/{pid}/design-rights", headers=admin)).json()
    assert rights == {"edit": "members", "can_edit": True, "can_accept": True}
    # the public demo signs its accounts in as viewers: they look, even on a project they own
    viewer_id, viewer = await make_user(client, role="viewer")
    own = await _demo_project(viewer_id, {"demo_id": "rights-test-2"})
    rights = (await client.get(f"{BASE}/projects/{own}/design-rights", headers=viewer)).json()
    assert rights == {"edit": "members", "can_edit": False, "can_accept": False}
