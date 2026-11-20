"""R16: converter-imported BIM models as revisions: wrap, rules, impact, accept, chain, migration up/down."""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from .conftest import make_project, make_user
from .ddcrev import example_rows, package
from .test_design_revisions import BASE, _linked_project, _upload

pytestmark = pytest.mark.asyncio

SCHEMAS = Path(__file__).parent / "contract" / "schemas"
GLB = b"glTF-converter-geometry" * 64
GID = "2O2Fr$t4X7Zf8NOew3FLOH"
ODD = "Wall 200 mm #3"  # outside the key grammar: counted as mapped


def _valid(schema: str, doc) -> list[str]:
    """The ERP venv has no jsonschema (full validation runs in contract/tests on the same example shape);
    here: exact top-level keys, and an import record's keys, as the schema names them."""
    s = json.loads((SCHEMAS / schema).read_text("utf-8"))
    errors = [f"keys {sorted(set(doc) ^ set(s['properties']))}"] if set(doc) != set(s["properties"]) else []
    man = doc.get("manifest") or {}
    if schema == "revision-view.schema.json" and man.get("schema") == "ddc-import/1":
        rec = s["$defs"]["importRecord"]
        if set(man) != set(rec["properties"]):
            errors.append(f"manifest keys {sorted(set(man) ^ set(rec['properties']))}")
        if doc["source_kind"] != "imported" or doc["brief_version"] is not None:
            errors.append("import record on a non-imported view")
        if not (isinstance(doc["package_sha256"], str) and len(doc["package_sha256"]) == 64):
            errors.append("package_sha256")
    elif schema == "revision-view.schema.json" and doc.get("depth_level") is None:
        errors.append("depth_level null outside an import record")
    return errors


async def _converter_model(
    project_id: uuid.UUID,
    *,
    name="Haus.ifc",
    parent: uuid.UUID | None = None,
    geometry: bool = True,
    meta: dict | None = None,
) -> uuid.UUID:
    """A model as a converter leaves it: IFC entity in element_type, no ifc_class property, Z-up GLB."""
    from app.database import async_session_factory
    from app.modules.bim_hub import file_storage
    from app.modules.bim_hub.models import BIMElement, BIMModel

    mid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            BIMModel(
                id=mid,
                project_id=project_id,
                name=name,
                model_format="ifc",
                status="ready",
                element_count=3,
                parent_model_id=parent,
                metadata_=dict(meta or {"source": "converter"}),
            )
        )
        await s.flush()
        for sid, cls, storey, qty in (
            (GID, "IfcSlab", "EG", {"area_m2": 120.0}),
            ("140056", "IfcSlab", "OG1", {"area_m2": 80.5}),
            (ODD, "IfcDoor", "EG", {"count": 1}),
        ):
            s.add(
                BIMElement(
                    model_id=mid,
                    stable_id=sid,
                    mesh_ref=sid,
                    element_type=cls,
                    name=sid,
                    storey=storey,
                    properties={"category": cls},
                    quantities=qty,
                )
            )
        await s.commit()
    if geometry:
        await file_storage.save_geometry(project_id, mid, ".glb", GLB)
    return mid


async def _model(mid: uuid.UUID):
    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel

    async with async_session_factory() as s:
        m = await s.get(BIMModel, mid)
        n = (await s.execute(select(func.count()).select_from(BIMElement).where(BIMElement.model_id == mid))).scalar()
        return m.parent_model_id, dict(m.metadata_ or {}), n


async def test_imported_model_becomes_a_revision_rules_accept_and_chain(client):
    uid, h, pid, tok = await _linked_project(client)
    rows = example_rows()
    rev1 = (await _upload(client, pid, tok, package(pid, rows)[0])).json()
    assert (await client.post(f"{BASE}/revisions/{rev1['revision_id']}/accept", headers=h)).status_code == 200
    est = f"{BASE}/projects/{pid}/estimate"
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    proc = f"{BASE}/projects/{pid}/procurement"
    assert (await client.post(f"{proc}/setup", json={"group_by": "ifc_class"}, headers=h)).status_code == 201
    mid = await _converter_model(pid)
    bare = await _converter_model(pid, name="Leer.ifc", geometry=False)

    listed = (await client.get(f"{BASE}/projects/{pid}/imported-models", headers=h)).json()
    assert [m["bim_model_id"] for m in listed] == [str(mid), str(bare)], "the editor's own model is no candidate"
    body = {"bim_model_id": str(mid)}
    # nothing joins the chain while the editor holds the lock; never through a link token
    assert (await client.post(f"{BASE}/projects/{pid}/revisions/import", json=body, headers=h)).status_code == 409
    assert (await client.post(f"{BASE}/projects/{pid}/revisions/import", json=body, headers=tok)).status_code == 403
    assert (await client.delete(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 204
    no_geo = await client.post(f"{BASE}/projects/{pid}/revisions/import", json={"bim_model_id": str(bare)}, headers=h)
    assert no_geo.status_code == 409 and "geometry" in no_geo.text

    r = await client.post(f"{BASE}/projects/{pid}/revisions/import", json=body, headers=h)
    assert r.status_code == 201, r.text
    view = r.json()
    assert _valid("revision-view.schema.json", view) == []
    assert view["source_kind"] == "imported" and view["status"] == "shared" and view["number"] == 2
    assert view["parent_revision_id"] == rev1["revision_id"] and view["bim_model_id"] == str(mid)
    assert view["depth_level"] is None and view["brief_version"] is None
    assert view["package_sha256"] == hashlib.sha256(GLB).hexdigest() and view["package_bytes"] == len(GLB)
    man = view["manifest"]
    assert man["schema"] == "ddc-import/1" and man["files"] == [] and man["source"]["model_format"] == "ifc"
    assert man["counts"] == {"elements": 3, "storeys": 2} and man["keys"] == {"verbatim": 2, "mapped": 1}
    assert man["restore"] == {"parent_model_id": None, "metadata": {}}
    rid = view["revision_id"]
    again = await client.post(f"{BASE}/projects/{pid}/revisions/import", json=body, headers=h)
    assert again.status_code == 409
    assert [
        m["bim_model_id"] for m in (await client.get(f"{BASE}/projects/{pid}/imported-models", headers=h)).json()
    ] == [str(bare)]
    assert (await client.get(f"{BASE}/revisions/{rid}/files/model.ddc", headers=h)).status_code == 404

    # rules see the converter elements (IFC entity from element_type) before and after acceptance
    imp = await client.get(f"{BASE}/revisions/{rid}/impact", headers=h)
    assert imp.status_code == 200 and imp.json()["estimate"] is True
    slab = next(x for x in imp.json()["rows"] if x["rule"] == "slab")
    assert Decimal(slab["model_quantity_new"]) == Decimal("200.5")
    # R11 take-off groups the converter elements by their IFC entity too, and follows the accept
    pimp = await client.get(f"{BASE}/revisions/{rid}/procurement-impact", headers=h)
    assert pimp.status_code == 200, pimp.text
    assert {"IfcSlab", "IfcDoor"} <= {x["ifc_class"] for x in pimp.json()["rows"]}
    assert (await client.post(f"{BASE}/revisions/{rid}/accept", headers=h)).status_code == 200
    after = await client.get(proc, headers=h)
    assert after.status_code == 200 and "IfcDoor" in after.text
    s = (await client.get(est, headers=h)).json()
    pos = {p["rule"]: p for p in s["positions"]}
    assert Decimal(pos["slab"]["quantity"]) == Decimal("200.5") and pos["door"]["elements"] == 1
    assert s["depth_level"] is None, "an unrated import is never treated as priced (D3+)"
    parent, meta, n = await _model(mid)
    assert str(parent) == rev1["bim_model_id"] and meta["design_status"] == "published" and n == 3

    # an import has no element table to diff against: the next design starts without a parent and replaces it
    lock = await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)
    assert lock.status_code == 200, lock.text
    on_import = await _upload(client, pid, tok, package(pid, rows, parent_id=rid, parent_rows=rows)[0])
    assert on_import.status_code == 409 and "imported model" in on_import.text
    nxt = await _upload(client, pid, tok, package(pid, rows)[0])
    assert nxt.status_code == 201, nxt.text
    assert nxt.json()["parent_revision_id"] is None and nxt.json()["number"] == 3
    assert (await client.delete(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 204
    assert (await client.post(f"{BASE}/revisions/{nxt.json()['revision_id']}/accept", headers=h)).status_code == 200


async def test_stated_depth_level_is_kept(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    mid = await _converter_model(pid)
    r = await client.post(
        f"{BASE}/projects/{pid}/revisions/import", headers=h, json={"bim_model_id": str(mid), "depth_level": "D3"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["depth_level"] == "D3" and r.json()["parent_revision_id"] is None
    assert (
        await client.post(
            f"{BASE}/projects/{pid}/revisions/import", headers=h, json={"bim_model_id": str(uuid.uuid4())}
        )
    ).status_code == 404


async def test_migration_wraps_existing_models_and_down_restores_them(client):
    from app.database import async_session_factory
    from app.modules.design.migrations import r16_imported_revisions as mig

    uid, h = await make_user(client)
    pid = await make_project(uid)
    first = await _converter_model(pid, name="v1.ifc")
    second = await _converter_model(
        pid, name="v2.ifc", parent=first, meta={"source": "converter", "design_status": "x"}
    )
    before = {m: await _model(m) for m in (first, second)}

    up = await mig.upgrade(async_session_factory, pid)
    assert [w["bim_model_id"] for w in up["wrapped"]] == [str(first), str(second)] and up["skipped"] == []
    revs = (await client.get(f"{BASE}/projects/{pid}/revisions", headers=h)).json()
    assert [(r["number"], r["source_kind"]) for r in revs] == [(2, "imported"), (1, "imported")]
    assert revs[0]["parent_revision_id"] == revs[1]["revision_id"]
    assert all(_valid("revision-view.schema.json", r) == [] for r in revs)
    assert (await mig.upgrade(async_session_factory, pid))["wrapped"] == [], "up is idempotent"

    down = await mig.downgrade(async_session_factory, pid)
    assert len(down["unwrapped"]) == 2 and down["kept"] == []
    assert (await client.get(f"{BASE}/projects/{pid}/revisions", headers=h)).json() == []
    assert {m: await _model(m) for m in (first, second)} == before, "parent, metadata and elements as before"

    # a decision is a person's act: down keeps an accepted wrapper and what it builds on
    await mig.upgrade(async_session_factory, pid)
    revs = (await client.get(f"{BASE}/projects/{pid}/revisions", headers=h)).json()
    oldest = revs[-1]["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{oldest}/accept", headers=h)).status_code == 200
    down = await mig.downgrade(async_session_factory, pid)
    assert [u["revision_id"] for u in down["unwrapped"]] == [revs[0]["revision_id"]]
    assert down["kept"] == [{"revision_id": oldest, "reason": "decided (published)"}]
    assert (await _model(second)) == before[second]


async def test_migration_reports_a_conflicting_write_and_goes_on(client, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.database import async_session_factory
    from app.modules.design import imported
    from app.modules.design.migrations import r16_imported_revisions as mig

    uid, _ = await make_user(client)
    raced, fine = await make_project(uid), await make_project(uid)
    a, b = await _converter_model(raced), await _converter_model(fine)
    real = imported.wrap

    async def wrap(session, model, **kw):
        if model.id == a:  # a parallel upload took the number first
            raise IntegrityError("insert", {}, Exception("duplicate key (project_id, number)"))
        return await real(session, model, **kw)

    monkeypatch.setattr(imported, "wrap", wrap)
    up = await mig.upgrade(async_session_factory)
    assert {"bim_model_id": str(a), "reason": mig._RACE} in up["skipped"]
    assert str(b) in [w["bim_model_id"] for w in up["wrapped"]]
