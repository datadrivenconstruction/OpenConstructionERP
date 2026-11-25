"""R11: material take-off by type from the revision's element table into the ERP's tendering module."""

from __future__ import annotations

import copy
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from .conftest import make_user
from .ddcrev import example_rows, package
from .test_design_revisions import BASE, DOOR, WALL, _linked_project, _upload
from .test_estimate_rules import SLAB, _set_quantity

pytestmark = pytest.mark.asyncio
WALL_1OG = "b1/s01/wall-ext-N/0"
SLAB_1OG = "b1/s01/slab/0"
D = Decimal


def _rows_upper():
    """R2: the ground-floor wall and slab repeated on the first floor."""
    rows = example_rows()
    for src, key in ((WALL, WALL_1OG), (SLAB, SLAB_1OG)):
        r = copy.deepcopy(next(x for x in rows if x["element_key"] == src))
        r.update(
            id=key,
            stable_id=key,
            element_key=key,
            storey="1.OG",
            bbox_min_z=3.0,
            bbox_max_z=5.8,
            geometry_hash="aa11bb22cc33dd44" if key == WALL_1OG else "bb22cc33dd44ee55",
        )
        rows.append(r)
    return rows


def _el(key, cls, type_key, **q):
    return SimpleNamespace(key=key, ifc_class=cls, type_key=type_key, quantities=q)


# ── grouping and basis: no app needed ───────────────────────────────────────


async def test_basis_table_uses_existing_quantity_keys_only():
    from app.modules.design import procurement as prc

    t = prc.basis_table()
    assert (
        set(t["by_ifc_class"].values()) | {t["default"]}
        <= set(prc.BASES)
        == {"length_m", "area_m2", "volume_m3", "weight_kg", "count"}
    )
    assert prc.default_basis("IfcWall") == "area_m2" and prc.default_basis("IfcSlab") == "volume_m3"
    assert prc.default_basis("IfcSomethingNew") == "count"  # unlisted class: counted, never guessed from geometry


async def test_grouping_sums_the_basis_and_never_fills_a_gap():
    from app.modules.design import procurement as prc

    els = [
        _el("a", "IfcWall", "wall/a", area_m2=10.0, volume_m3=2.0),
        _el("b", "IfcWall", "wall/a", area_m2=5.5),
        _el("c", "IfcWall", "wall/b", volume_m3=1.0),
        _el("s", "IfcSpace", "space/x", area_m2=99.0),  # a room is not bought
        _el("d", "IfcDoor", "", count=1),
    ]
    by_type = prc.group_elements(els, "type_key")
    assert set(by_type) == {"wall/a", "wall/b", "IfcDoor/_untyped"}
    q, flags = prc.measure(by_type["wall/a"], "area_m2")
    assert q == D("15.5") and flags == []
    q, flags = prc.measure(by_type["wall/a"], "volume_m3")
    assert q == D(2) and flags == ["partial_quantity"]  # one of two elements has no volume: said, not filled
    q, flags = prc.measure(by_type["wall/b"], "area_m2")
    assert q == 0 and flags == ["no_quantity"]
    q, flags = prc.measure(None, "area_m2")
    assert q == 0 and flags == ["no_match"]
    by_class = prc.group_elements(els, "ifc_class")
    assert set(by_class) == {"IfcWall", "IfcDoor"} and len(by_class["IfcWall"].elements) == 3


# ── with the ERP ────────────────────────────────────────────────────────────


async def _packages(project_id):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.tendering.models import TenderPackage

    async with async_session_factory() as s:
        rows = (
            (
                await s.execute(
                    select(TenderPackage)
                    .where(TenderPackage.project_id == uuid.UUID(str(project_id)))
                    .order_by(TenderPackage.name)
                )
            )
            .scalars()
            .all()
        )
        return [SimpleNamespace(id=p.id, name=p.name, status=p.status, boq_id=p.boq_id, meta=p.metadata_) for p in rows]


async def _set_package_status(package_id, new_status):
    from app.database import async_session_factory
    from app.modules.tendering.schemas import PackageUpdate
    from app.modules.tendering.service import TenderingService

    async with async_session_factory() as s:
        await TenderingService(s).update_package(package_id, PackageUpdate(status=new_status))
        await s.commit()


async def _accepted_project(client, *, mode=None, group_by="type_key"):
    """R1 accepted and the take-off set up; R2 (wall and slab repeated on the first floor) shared."""
    uid, h, pid, tok = await _linked_project(client)
    if mode:
        assert (
            await client.put(f"{BASE}/projects/{pid}/change-orders/settings", json={"mode": mode}, headers=h)
        ).status_code == 200
    rows1 = example_rows()
    d1, m1 = package(pid, rows1)
    r1 = (await _upload(client, pid, tok, d1)).json()["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{r1}/accept", headers=h)).status_code == 200
    s = await client.post(f"{BASE}/projects/{pid}/procurement/setup", json={"group_by": group_by}, headers=h)
    assert s.status_code == 201, s.text
    d2, _ = package(pid, _rows_upper(), parent_id=m1["revision_id"], parent_rows=rows1)
    r2 = (await _upload(client, pid, tok, d2)).json()["revision_id"]
    return uid, h, pid, tok, r1, r2, s.json()


def _line(summary, group_key):
    return next(r for r in summary["lines"] if r["group_key"] == group_key)


async def test_setup_raises_one_tender_package_per_ifc_class(client):
    uid, h, pid, tok, r1, r2, sm = await _accepted_project(client)
    assert sm["procurement"] is True and sm["group_by"] == "type_key" and sm["follow"] is True
    wall, slab, door = (_line(sm, k) for k in ("wall/ext-masonry-365", "slab/concrete-200", "door/entry-1010x2135"))
    assert (wall["basis"], wall["unit"], D(wall["quantity"])) == ("area_m2", "m2", D("82.5"))
    assert (slab["basis"], slab["unit"], D(slab["quantity"])) == ("volume_m3", "m3", D("80.24"))
    assert (door["basis"], door["unit"], D(door["quantity"])) == ("count", "pcs", 1)
    assert not any(r["group_key"].startswith("space/") for r in sm["lines"])  # the room is not procured
    # nothing priced, nothing assumed about delivery: flagged, empty
    for r in sm["lines"]:
        assert {"unpriced", "lead_time_missing"} <= set(r["flags"]) and r["basis_by_person"] is False
    assert slab["available"]["area_m2"]["sum"] == "401.2000"  # the other bases are there to switch to

    pkgs = await _packages(pid)
    assert [p.name for p in pkgs] == [
        "design_takeoff:IfcDoor",
        "design_takeoff:IfcSlab",
        "design_takeoff:IfcWall",
    ]
    assert {p.status for p in pkgs} == {"draft"} and len({p.boq_id for p in pkgs}) == 1
    wall_pkg = pkgs[2]
    [item] = wall_pkg.meta["line_item_template"]  # the ERP's own line-item template, read by its comparison screens
    assert item["position_id"] == wall["position_id"] and D(item["quantity"]) == D("82.5")
    assert D(item["unit_rate"]) == 0 and D(item["total"]) == 0
    d = wall_pkg.meta["design_takeoff"]
    assert d["price"] is None and d["lead_time_days"] is None and d["flags"] == ["unpriced", "lead_time_missing"]
    assert {p["ifc_class"]: p["status"] for p in sm["packages"]} == {
        "IfcDoor": "draft",
        "IfcSlab": "draft",
        "IfcWall": "draft",
    }
    assert "convention" in sm["basis_note"] and "No prices" in sm["price_note"]
    # the tendering register itself can read the scope of the package
    scope = await client.get(f"/api/v1/tendering/packages/{wall_pkg.id}/scope", headers=h)
    assert scope.status_code == 200 and scope.json()["included_position_count"] == 1


async def test_setup_rules(client):
    uid, h, pid, tok = await _linked_project(client)
    url = f"{BASE}/projects/{pid}/procurement"
    assert (await client.get(url, headers=h)).json() == {"procurement": False}
    assert (await client.post(f"{url}/setup", headers=h)).status_code == 409  # no accepted revision yet
    d1, _ = package(pid, example_rows())
    r1 = (await _upload(client, pid, tok, d1)).json()["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{r1}/accept", headers=h)).status_code == 200
    assert (await client.post(f"{url}/setup", headers=tok)).status_code == 403  # the editor does not manage it
    _, other = await make_user(client)
    assert (await client.post(f"{url}/setup", headers=other)).status_code in (403, 404)
    assert (await client.post(f"{url}/setup", json={"group_by": "nonsense"}, headers=h)).status_code == 422
    ok = await client.post(f"{url}/setup", json={"group_by": "ifc_class"}, headers=h)
    assert ok.status_code == 201 and {r["group_key"] for r in ok.json()["lines"]} == {"IfcWall", "IfcSlab", "IfcDoor"}
    assert (await client.post(f"{url}/setup", headers=h)).status_code == 409
    assert (await client.get(url, headers=tok)).status_code == 200  # the editor may read
    imp = (await client.get(f"{BASE}/revisions/{r1}/procurement-impact", headers=tok)).json()
    assert imp["procurement"] is True and imp["group_by"] == "ifc_class"


async def test_impact_equals_take_off_after_accept_and_overrides_survive(client):
    uid, h, pid, tok, r1, r2, sm = await _accepted_project(client)
    wall = _line(sm, "wall/ext-masonry-365")
    await _set_quantity(wall["position_id"], "90")  # a person measured on site
    imp = (await client.get(f"{BASE}/revisions/{r2}/procurement-impact", headers=h)).json()
    assert imp["schema"] == "ddc-procurement-impact/1" and imp["procurement"] is True
    rows = {r["group_key"]: r for r in imp["rows"]}
    assert imp["rows"][0]["group_key"] == "wall/ext-masonry-365"  # overrides come first
    w, s, dr = rows["wall/ext-masonry-365"], rows["slab/concrete-200"], rows["door/entry-1010x2135"]
    assert w["override"] and D(w["override_quantity"]) == 90 and D(w["model_quantity_new"]) == D("165.0")
    assert D(w["new_quantity"]) == 90 and D(w["quantity_delta"]) == 0 and "override" in w["flags"]
    assert not s["override"] and D(s["new_quantity"]) == D("160.48") and D(s["quantity_delta"]) == D("80.24")
    assert D(dr["quantity_delta"]) == 0 and s["package"]["status"] == "draft"
    t = imp["totals"]
    assert (t["lines_changed"], t["lines_added"], t["overrides_kept"], t["packages_affected"]) == (1, 0, 1, 1)
    assert t["issued_packages_affected"] == 0

    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    after = (await client.get(f"{BASE}/projects/{pid}/procurement", headers=h)).json()
    assert after["revision_id"] == r2
    aw, asl = _line(after, "wall/ext-masonry-365"), _line(after, "slab/concrete-200")
    assert D(aw["quantity"]) == 90 and aw["override"] and D(aw["model_quantity"]) == D("165.0") and aw["elements"] == 2
    assert D(asl["quantity"]) == D("160.48") and not asl["override"]
    pk = {p.name: p for p in await _packages(pid)}
    assert D(pk["design_takeoff:IfcWall"].meta["line_item_template"][0]["quantity"]) == 90  # the package follows
    assert D(pk["design_takeoff:IfcSlab"].meta["line_item_template"][0]["quantity"]) == D("160.48")
    again = (await client.get(f"{BASE}/revisions/{r2}/procurement-impact", headers=h)).json()
    assert again["totals"]["lines_changed"] == 0 and again["totals"]["overrides_kept"] == 1


async def test_issued_package_follows_and_records_each_change(client):
    uid, h, pid, tok, r1, r2, sm = await _accepted_project(client)
    slab_pkg = next(p for p in await _packages(pid) if p.name.endswith("IfcSlab"))
    await _set_package_status(slab_pkg.id, "issued")
    imp = (await client.get(f"{BASE}/revisions/{r2}/procurement-impact", headers=h)).json()
    assert imp["totals"]["issued_packages_affected"] == 1
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    after = (await client.get(f"{BASE}/projects/{pid}/procurement", headers=h)).json()
    asl = _line(after, "slab/concrete-200")
    assert "changed_after_issue" in asl["flags"] and D(asl["quantity"]) == D("160.48")
    pk = next(p for p in after["packages"] if p["ifc_class"] == "IfcSlab")
    assert pk["status"] == "issued"
    [chg] = pk["changes_after_issue"]
    assert (chg["from"], chg["to"], chg["revision_id"], chg["package_status"]) == ("80.2400", "160.4800", r2, "issued")
    assert next(p for p in after["packages"] if p["ifc_class"] == "IfcWall")["changes_after_issue"] == []
    # an addendum DRAFT is prepared for the issued package; nothing is published or sent behind a person's back
    from app.database import async_session_factory
    from app.modules.tendering.service import TenderingService

    async with async_session_factory() as sess:
        svc = TenderingService(sess)
        [add] = await svc.list_addenda(slab_pkg.id)
        assert await svc.list_addenda(next(p for p in await _packages(pid) if p.name.endswith("IfcWall")).id) == []
    assert add.published_at is None and add.revision_no == 1
    rev_no = (await client.get(f"{BASE}/revisions/{r2}", headers=h)).json()["number"]
    assert add.title == f"Design revision {rev_no}: quantity changes"
    [bc] = add.boq_changes
    assert (bc["op"], bc["quantity_before"], bc["quantity_after"], bc["unit"]) == (
        "change",
        "80.2400",
        "160.4800",
        "m3",
    )
    assert bc["position_id"] == asl["position_id"] and "elements 1 -> 2" in add.body
    [st] = pk["addenda"]
    assert (st["state"], st["revision_id"], st["addendum_id"], st["lines"], st["elements"]) == (
        "draft",
        r2,
        add.id,
        1,
        2,
    )
    meta = next(p for p in await _packages(pid) if p.id == slab_pkg.id).meta
    line = meta["design_takeoff"]["addenda"][r2]["lines"][0]
    assert len(line["element_keys"]) == 2 and all(k.startswith("b1/") for k in line["element_keys"])
    assert "element_keys" not in meta["design_takeoff"]["changes_after_issue"][0]  # history stays small


async def test_group_leaving_the_model_is_kept_at_zero(client):
    uid, h, pid, tok, r1, r2, sm = await _accepted_project(client)
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    rows3 = [r for r in _rows_upper() if r["element_key"] != DOOR]
    d3, _ = package(pid, rows3, parent_id=r2, parent_rows=_rows_upper())
    r3 = (await _upload(client, pid, tok, d3)).json()["revision_id"]
    imp = (await client.get(f"{BASE}/revisions/{r3}/procurement-impact", headers=h)).json()
    row = next(r for r in imp["rows"] if r["group_key"].startswith("door/"))
    assert D(row["new_quantity"]) == 0 and "no_match" in row["flags"] and imp["totals"]["lines_removed"] == 1
    assert (await client.post(f"{BASE}/revisions/{r3}/accept", headers=h)).status_code == 200
    after = (await client.get(f"{BASE}/projects/{pid}/procurement", headers=h)).json()
    door = _line(after, "door/entry-1010x2135")
    assert D(door["quantity"]) == 0 and "no_match" in door["flags"]  # kept, never deleted
    assert len(await _packages(pid)) == 3
    # R4 brings the door back: the same position counts again
    d4, _ = package(pid, _rows_upper(), parent_id=r3, parent_rows=rows3)
    r4 = (await _upload(client, pid, tok, d4)).json()["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{r4}/accept", headers=h)).status_code == 200
    back = _line((await client.get(f"{BASE}/projects/{pid}/procurement", headers=h)).json(), "door/entry-1010x2135")
    assert back["position_id"] == door["position_id"] and D(back["quantity"]) == 1 and "no_match" not in back["flags"]


async def test_new_type_extends_its_package_and_a_new_class_gets_one(client):
    uid, h, pid, tok, r1, r2, sm = await _accepted_project(client)
    rows = _rows_upper()
    col = copy.deepcopy(next(r for r in rows if r["element_key"] == WALL))
    col.update(
        id="b1/s00/col/0",
        stable_id="b1/s00/col/0",
        element_key="b1/s00/col/0",
        ifc_class="IfcColumn",
        type_key="column/rc-300",
        length_m=2.8,
        area_m2=None,
        volume_m3=0.25,
        geometry_hash="cc33dd44ee55ff66",
    )
    wall2 = copy.deepcopy(next(r for r in rows if r["element_key"] == WALL))
    wall2.update(
        id="b1/s00/wall-int/0",
        stable_id="b1/s00/wall-int/0",
        element_key="b1/s00/wall-int/0",
        type_key="wall/int-masonry-115",
        area_m2=20.0,
        geometry_hash="dd44ee55ff66aa77",
    )
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    d3, _ = package(pid, [*rows, col, wall2], parent_id=r2, parent_rows=rows)
    r3 = (await _upload(client, pid, tok, d3)).json()["revision_id"]
    imp = (await client.get(f"{BASE}/revisions/{r3}/procurement-impact", headers=h)).json()
    assert imp["totals"]["lines_added"] == 2 and imp["totals"]["packages_new"] == 1
    assert (await client.post(f"{BASE}/revisions/{r3}/accept", headers=h)).status_code == 200
    after = (await client.get(f"{BASE}/projects/{pid}/procurement", headers=h)).json()
    assert _line(after, "column/rc-300")["unit"] == "m" and D(_line(after, "column/rc-300")["quantity"]) == D("2.8")
    pk = {p.name: p for p in await _packages(pid)}
    assert set(pk) == {f"design_takeoff:{c}" for c in ("IfcDoor", "IfcSlab", "IfcWall", "IfcColumn")}
    assert len(pk["design_takeoff:IfcWall"].meta["line_item_template"]) == 2  # the new wall type joined its package


async def test_person_can_switch_the_basis_and_pause_following(client):
    uid, h, pid, tok, r1, r2, sm = await _accepted_project(client)
    wall = _line(sm, "wall/ext-masonry-365")
    url = f"{BASE}/projects/{pid}/procurement"
    assert (
        await client.put(f"{url}/lines/{wall['line_id']}/basis", json={"basis": "volume_m3"}, headers=tok)
    ).status_code == 403
    assert (
        await client.put(f"{url}/lines/{wall['line_id']}/basis", json={"basis": "weight"}, headers=h)
    ).status_code == 422
    sw = (await client.put(f"{url}/lines/{wall['line_id']}/basis", json={"basis": "volume_m3"}, headers=h)).json()
    w = _line(sw, "wall/ext-masonry-365")
    assert (w["basis"], w["unit"], w["basis_by_person"]) == ("volume_m3", "m3", True) and D(w["quantity"]) == D("30.11")
    assert not w["override"]
    # a basis with no value in the model is zero and says so
    nv = (await client.put(f"{url}/lines/{wall['line_id']}/basis", json={"basis": "weight_kg"}, headers=h)).json()
    assert (
        D(_line(nv, "wall/ext-masonry-365")["quantity"]) == 0
        and "no_quantity" in _line(nv, "wall/ext-masonry-365")["flags"]
    )
    assert (await client.put(f"{url}/settings", json={"follow": False}, headers=h)).json()["follow"] is False
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    held = (await client.get(url, headers=h)).json()
    assert D(_line(held, "slab/concrete-200")["quantity"]) == D("80.24") and held["revision_id"] != r2


async def test_change_order_carries_the_take_off_delta(client):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.changeorders.models import ChangeOrder

    uid, h, pid, tok, r1, r2, sm = await _accepted_project(client, mode="always")
    imp = (await client.get(f"{BASE}/revisions/{r2}/procurement-impact", headers=h)).json()
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    async with async_session_factory() as s:
        order = (
            await s.execute(
                select(ChangeOrder).where(ChangeOrder.project_id == pid, ChangeOrder.title.like("Design revision R2%"))
            )
        ).scalar_one()
    meta = order.metadata_["design"]["procurement"]
    t = imp["totals"]
    assert meta == {
        k: t[k]
        for k in (
            "lines_changed",
            "lines_added",
            "lines_removed",
            "overrides_kept",
            "packages_affected",
            "issued_packages_affected",
        )
    }
    assert meta["lines_changed"] == 2 and "Procurement: 2 take-off line(s) change" in order.description


async def test_a_package_a_person_deleted_is_not_recreated(client):
    from app.database import async_session_factory
    from app.modules.tendering.service import TenderingService

    uid, h, pid, tok, r1, r2, sm = await _accepted_project(client)
    door_pkg = next(p for p in await _packages(pid) if p.name.endswith("IfcDoor"))
    async with async_session_factory() as s:
        await TenderingService(s).repo.delete_package(door_pkg.id)
        await s.commit()
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    assert len(await _packages(pid)) == 2
    after = (await client.get(f"{BASE}/projects/{pid}/procurement", headers=h)).json()
    assert next(p for p in after["packages"] if p["ifc_class"] == "IfcDoor")["missing"] is True


async def test_no_take_off_means_no_delta(client):
    uid, h, pid, tok = await _linked_project(client)
    d1, _ = package(pid, example_rows())
    r1 = (await _upload(client, pid, tok, d1)).json()["revision_id"]
    imp = (await client.get(f"{BASE}/revisions/{r1}/procurement-impact", headers=h)).json()
    assert imp == {"schema": "ddc-procurement-impact/1", "revision_id": r1, "procurement": False}
    assert json.dumps(imp)  # plain data


async def test_a_position_or_section_a_person_deleted_does_not_block_acceptance(client):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.boq.repository import PositionRepository
    from app.modules.design.procurement_models import DesignTakeoffSection

    uid, h, pid, tok, r1, r2, sm = await _accepted_project(client)
    cur = (await client.get(f"{BASE}/projects/{pid}/procurement", headers=h)).json()
    door = _line(cur, "door/entry-1010x2135")
    async with async_session_factory() as s:
        sec = (
            await s.execute(
                select(DesignTakeoffSection).where(
                    DesignTakeoffSection.project_id == uuid.UUID(str(pid)), DesignTakeoffSection.ifc_class == "IfcWall"
                )
            )
        ).scalar_one()
        repo = PositionRepository(s)
        await repo.delete(uuid.UUID(door["position_id"]))
        await repo.delete(sec.position_id)
        await s.commit()
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    after = (await client.get(f"{BASE}/projects/{pid}/procurement", headers=h)).json()
    assert "position_deleted" in _line(after, "door/entry-1010x2135")["flags"]
    async with async_session_factory() as s:
        assert await PositionRepository(s).get_by_id(uuid.UUID(door["position_id"])) is None  # never recreated
