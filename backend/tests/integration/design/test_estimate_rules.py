"""R6: estimate rules, recompute on accept, overrides, impact, benchmark range."""

from __future__ import annotations

import copy
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from .ddcrev import example_rows, package
from .test_design_revisions import BASE, DOOR, WALL, _linked_project, _upload

pytestmark = pytest.mark.asyncio

SLAB = "b1/s00/slab/0"


def D(v) -> Decimal:
    return Decimal(str(v))


# ── rules and benchmarks: no app needed ─────────────────────────────────────


async def test_starter_set_is_valid_and_honest():
    from app.modules.design import rules

    doc = rules.starter_set("DE")
    assert doc is not None and rules.starter_set("FR") is None  # no set for a country without sources
    assert {r["kind"] for r in doc["rules"]} == {"model", "derived"}
    for r in doc["rules"]:
        if r["kind"] == "derived":
            rate = r.get("rate")
            # a derived rule names its benchmark, or says why it has no rate; never a bare number
            assert (rate is None and r["missing"]) or "benchmark" in rate or rate["source"]["url"]
    for name, a in doc["aggregates"].items():
        assert a["assumption"], name


def _el(key, ifc, type_key, volume):
    from app.modules.design import rules

    return rules.Element(key, None, None, {"ifc_class": ifc, "type_key": type_key}, {"volume_m3": volume})


async def test_foundation_rule_takes_strip_footings_and_a_raft_slab_but_not_floor_slabs():
    from app.modules.design import rules

    rule = next(r for r in rules.starter_set("DE")["rules"] if r["id"] == "foundation")
    strip = _el("b1/found/strip/0", "IfcFooting", "footing/strip-60", 12)
    raft = _el("b1/found/raft", "IfcSlab", "slab/foundation-raft", 80)
    floor = _el("b1/s00/slab/0", "IfcSlab", "slab/gen-floor-200", 40)
    roof = _el("b1/roof", "IfcSlab", "slab/roof-flat", 30)
    got = {e.key for e in rules.select([strip, raft, floor, roof], rule["select"])}
    assert got == {strip.key, raft.key}
    # the floor-slab rule is the complement: it must not count the raft again
    slab = next(r for r in rules.starter_set("DE")["rules"] if r["id"] == "slab")
    assert {e.key for e in rules.select([strip, raft, floor, roof], slab["select"])} == {floor.key}


async def test_any_of_must_be_a_non_empty_list_of_valid_selectors():
    from app.modules.design import rules

    for bad in ({"any_of": []}, {"any_of": [{}]}, {"any_of": [{"nope": ["x"]}]}, {"any_of": "IfcSlab"}):
        with pytest.raises(rules.RulesError):
            rules._check_select(bad, "t")


def _drop(rule_id, key):
    return lambda d: next(r for r in d["rules"] if r["id"] == rule_id).pop(key)


def _upd(rule_id, **kw):
    return lambda d: next(r for r in d["rules"] if r["id"] == rule_id).update(**kw)


@pytest.mark.parametrize(
    "mutate",
    [
        _upd("foundation", kind="other"),
        _upd("foundation", cost_group="33"),
        lambda d: d["rules"][0]["select"].update(colour="red"),
        lambda d: d["rules"][0]["quantity"].update(field="price"),
        lambda d: d["rules"][0]["quantity"].update(formula="area_m2"),
        _drop("services", "missing"),
        _upd("finishes", rate={"value": 12, "source": {}}),
        lambda d: next(r for r in d["rules"] if r["id"] == "reinforcement")["inputs"]["reinforcement_kg_per_m3"].update(
            value=100
        ),
        _upd("services", formula="unknown_aggregate * 2"),
        lambda d: d["rules"].append(copy.deepcopy(d["rules"][0])),
    ],
    ids=[
        "kind",
        "cost group",
        "selector",
        "field",
        "field and formula",
        "no reason",
        "rate no source",
        "input no source",
        "unknown name",
        "duplicate id",
    ],
)
async def test_bad_rules_are_refused(mutate):
    from app.modules.design import rules

    doc = copy.deepcopy(rules.starter_set("DE"))
    mutate(doc)
    with pytest.raises(rules.RulesError):
        rules.validate_document(doc)


async def test_benchmark_bands_come_from_the_data():
    from app.modules.design import benchmarks

    rows = json.loads((benchmarks.DATA / "de_residential_multi.json").read_text(encoding="utf-8"))["rows"]
    full = [
        r
        for r in rows
        if r["cost_group"] == "300+400" and r["basis"] == "WFL" and r["low"] is not None and r["high"] is not None
    ]
    newest = max(full, key=lambda r: r["price_level_year"])
    b = benchmarks.band("DE", "residential_multi", "300+400", "WFL")
    assert (b.low, b.mid, b.high, b.source_url) == (
        D(newest["low"]),
        D(newest["mid"]),
        D(newest["high"]),
        newest["source_url"],
    )
    assert benchmarks.band("DE", "residential_multi", "300+400", "BGF") is None
    assert benchmarks.band("DE", "residential_multi", "100", "WFL") is None
    assert benchmarks.band("FR", "residential_multi", "200", "WFL") is None
    assert benchmarks.group_for_din276("331") == "300+400" and benchmarks.group_for_din276("610") is None


def _item(group, rate, total, flags=()):
    pos = SimpleNamespace(unit_rate=str(rate), total=str(total))
    return (pos, SimpleNamespace(flags=list(flags)), SimpleNamespace(body={"cost_group": group}, kind="model"))


async def test_priced_positions_replace_the_benchmark_only_from_d3():
    from app.modules.design import benchmarks
    from app.modules.design.estimate import range_report

    est = SimpleNamespace(country="DE", use="residential_multi", aggregate_values={"living_area_m2": "100"})
    items = [
        _item("500", 10, 1000),
        _item("200", 5, 500),
        _item("700", 7, 700),
        _item("330", 3, 3000),
        _item("400", 4, 400),
    ]
    d2 = range_report(est, items, "D2")
    assert d2["currency"] == "EUR"
    # sources that no group reads are listed with a reason code, not dropped
    unused = {u["publisher"]: u["reasons"] for u in d2["sources_not_used"]}
    assert unused == {
        "Statistisches Bundesamt (Destatis)": ["other_basis", "no_range"],
        "Thüringer Landesamt für Statistik": ["no_range"],
    }
    assert all(g["source"] == "benchmark" for g in d2["groups"].values())
    b500 = benchmarks.band("DE", "residential_multi", "500", "WFL")
    assert D(d2["groups"]["500"]["mid"]) == b500.mid * 100
    d3 = range_report(est, items, "D3")
    g500 = d3["groups"]["500"]
    assert g500["source"] == "positions" and [D(g500[k]) for k in ("low", "mid", "high")] == [1000] * 3
    assert d3["groups"]["300+400"]["source"] == "positions" and D(d3["groups"]["300+400"]["mid"]) == 3400
    # one unpriced position keeps its whole group on the benchmark
    flagged = items[:3] + [_item("330", 3, 3000), _item("400", 0, 0, ["rate_missing"])]
    assert range_report(est, flagged, "D4")["groups"]["300+400"]["source"] == "benchmark"
    assert d3["not_in_range"] == ["100", "600"]
    # without a living area there is no range, and the report says which groups are missing
    none = range_report(SimpleNamespace(country="DE", use="residential_multi", aggregate_values={}), items, "D2")
    assert none["missing_groups"] == ["200", "300+400", "500", "700"] and none["total"]["complete"] is False


# ── the whole chain over HTTP ───────────────────────────────────────────────


async def _set_quantity(position_id: str, quantity: str) -> None:
    from app.database import async_session_factory
    from app.modules.boq.repository import PositionRepository

    async with async_session_factory() as s:
        repo = PositionRepository(s)
        pos = await repo.get_by_id(uuid.UUID(position_id))
        # A person's edit goes through the ERP service, which keeps total = quantity * rate.
        await repo.update_fields(pos.id, quantity=quantity, total=str(D(quantity) * D(pos.unit_rate)))
        await s.commit()


async def _link_of(position_id: str):
    from app.database import async_session_factory
    from app.modules.boq.repository import QuantityLinkRepository

    async with async_session_factory() as s:
        links = await QuantityLinkRepository(s).list_for_position(uuid.UUID(position_id))
        return [(link.status, list(link.element_stable_ids)) for link in links]


def _by_rule(summary):
    return {p["rule"]: p for p in summary["positions"]}


def _rows2():
    rows = [r for r in example_rows() if r["element_key"] != DOOR]
    next(r for r in rows if r["element_key"] == WALL).update(area_m2=88.1, geometry_hash="9f2c4a1e0b7d3c66")
    next(r for r in rows if r["element_key"] == SLAB).update(area_m2=405.0, geometry_hash="17aa03be55c0e999")
    new = dict(next(r for r in example_rows() if r["element_key"] == DOOR))
    key = "b1/s01/u2A/door-entry/1"
    new.update(id=key, stable_id=key, element_key=key, geometry_hash="c3d4e5f60718293b")
    rows.append(new)
    return rows


async def test_rules_follow_revisions_and_keep_overrides(client):
    uid, h, pid, tok = await _linked_project(client)
    est = f"{BASE}/projects/{pid}/estimate"
    rows1 = example_rows()
    d1, m1 = package(pid, rows1)
    rev1 = (await _upload(client, pid, tok, d1)).json()
    assert (await client.post(f"{BASE}/revisions/{rev1['revision_id']}/accept", headers=h)).status_code == 200

    # no estimate yet: the impact endpoint says so, nothing is created on accept
    none = await client.get(f"{BASE}/revisions/{rev1['revision_id']}/impact", headers=tok)
    assert none.status_code == 200 and none.json()["estimate"] is False
    assert (await client.get(est, headers=h)).json() == {"estimate": False}

    # the editor cannot manage the estimate; there is no starter set for a country without sources
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=tok)).status_code == 403
    assert (await client.post(f"{est}/rules/starter", json={"country": "FR"}, headers=h)).status_code == 404
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    ran = await client.post(f"{est}/run", headers=h)
    assert ran.status_code == 200, ran.text
    s1 = (await client.get(est, headers=h)).json()
    p1 = _by_rule(s1)
    assert len(p1) == 14
    assert D(p1["wall_ext"]["quantity"]) == D("82.5") and p1["wall_ext"]["elements"] == 1
    assert D(p1["slab"]["quantity"]) == D("401.2") and D(p1["door"]["quantity"]) == 1
    assert D(p1["wall_int"]["quantity"]) == 0 and "no_match" in p1["wall_int"]["flags"]
    assert "no_match" in p1["roof"]["flags"] and p1["roof"]["ordinal"].startswith("360.")
    # nothing is priced without a source; each missing input says why
    assert "unpriced" in p1["wall_ext"]["flags"]
    assert "rate_missing" in p1["services"]["flags"] and p1["services"]["provenance"]["missing"]
    assert p1["services"]["provenance"]["missing_code"] == "rate_missing"
    assert p1["reinforcement"]["provenance"]["missing_code"] == "input_missing"
    assert p1["wall_ext"]["description"] == "Außenwände"
    assert "input_missing" in p1["reinforcement"]["flags"] and D(p1["reinforcement"]["quantity"]) == 0
    # a derived rule with a sourced benchmark prices per living area and shows formula, basis and source
    assert D(p1["site_works"]["quantity"]) == D("28.4")
    bm = p1["site_works"]["provenance"]["benchmark"]
    assert D(p1["site_works"]["unit_rate"]) == D(bm["mid"]) and bm["source_url"].startswith("https://")
    assert p1["site_works"]["provenance"]["formula"] == "living_area_m2"
    assert "WoFlV" in p1["site_works"]["provenance"]["aggregates"]["living_area_m2"]["assumption"]
    # the position is bound through the ERP quantity link
    assert (await _link_of(p1["wall_ext"]["position_id"])) == [("active", [WALL])]

    # range per group and in total, each with its source; the priced total is not comparable yet
    rng = s1["range"]
    assert rng["currency"] == "EUR"
    assert rng["total"]["complete"] and set(rng["groups"]) == {"200", "300+400", "500", "700"}
    g = rng["groups"]["500"]
    assert g["source"] == "benchmark" and D(g["mid"]) == D(bm["mid"]) * D("28.4")
    assert D(rng["total"]["low"]) < D(rng["total"]["mid"]) < D(rng["total"]["high"])
    assert s1["inside_range"] is None and s1["inside_range_note"]
    assert s1["inside_range_note_code"] == "unpriced_or_unsourced"

    # a person prices a position (a source is required) and overrides a quantity
    wall_pos = p1["wall_ext"]["position_id"]
    bad = await client.post(f"{est}/positions/{wall_pos}/price", json={"unit_rate": "10"}, headers=h)
    assert bad.status_code == 422
    ok = await client.post(
        f"{est}/positions/{wall_pos}/price",
        headers=h,
        json={"unit_rate": "10", "source_url": "https://example.org/rates", "price_date": "2026-01-15"},
    )
    assert ok.status_code == 204, ok.text
    await _set_quantity(wall_pos, "90")
    assert (
        await client.put(f"{est}/positions/{wall_pos}/override-reason", headers=h, json={"reason": "surveyed on site"})
    ).status_code == 204

    # revision 2 changes the wall (overridden) and the slab, and swaps the door
    rows2 = _rows2()
    d2, m2 = package(pid, rows2, parent_id=m1["revision_id"], parent_rows=rows1)
    rev2 = (await _upload(client, pid, tok, d2)).json()
    imp = (await client.get(f"{BASE}/revisions/{rev2['revision_id']}/impact", headers=h)).json()
    by = {r["rule"]: r for r in imp["rows"]}
    assert imp["rows"][0]["rule"] == "wall_ext"  # overrides come first
    w = by["wall_ext"]
    assert w["override"] and D(w["override_quantity"]) == 90 and D(w["model_quantity_new"]) == D("88.1")
    assert D(w["quantity_delta"]) == 0 and D(w["cost_delta"]) == 0
    assert D(by["slab"]["quantity_delta"]) == D("3.8") and by["slab"]["override"] is False
    assert by["door"]["elements"]["added"] == ["b1/s01/u2A/door-entry/1"]
    assert by["door"]["elements"]["removed"] == [DOOR] and D(by["door"]["quantity_delta"]) == 0
    assert imp["totals"]["unpriced_positions"] > 0
    # the impact is a dry run
    assert _by_rule((await client.get(est, headers=h)).json())["slab"]["quantity"] == p1["slab"]["quantity"]

    assert (await client.post(f"{BASE}/revisions/{rev2['revision_id']}/accept", headers=h)).status_code == 200
    p2 = _by_rule((await client.get(est, headers=h)).json())
    assert D(p2["wall_ext"]["quantity"]) == 90 and p2["wall_ext"]["override"]
    assert D(p2["wall_ext"]["model_quantity"]) == D("88.1") and p2["wall_ext"]["override_reason"] == "surveyed on site"
    assert D(p2["wall_ext"]["total"]) == 900 and D(p2["wall_ext"]["unit_rate"]) == 10
    assert D(p2["slab"]["quantity"]) == 405 and not p2["slab"]["override"]
    assert D(p2["door"]["quantity"]) == 1 and p2["door"]["elements"] == 1
    assert (await _link_of(p2["door"]["position_id"])) == [("active", ["b1/s01/u2A/door-entry/1"])]
    assert p2["slab"]["position_id"] == p1["slab"]["position_id"]  # same position, not a new one

    # revision 3: no doors -> flagged, quantity zero, position kept; the wall now equals the override
    rows3 = [r for r in _rows2() if "door" not in r["element_key"]]
    next(r for r in rows3 if r["element_key"] == WALL).update(area_m2=90.0, geometry_hash="aa11bb22cc33dd44")
    d3, m3 = package(pid, rows3, parent_id=m2["revision_id"], parent_rows=rows2)
    rev3 = (await _upload(client, pid, tok, d3)).json()
    assert (await client.post(f"{BASE}/revisions/{rev3['revision_id']}/accept", headers=h)).status_code == 200
    p3 = _by_rule((await client.get(est, headers=h)).json())
    assert p3["door"]["position_id"] == p1["door"]["position_id"]
    assert D(p3["door"]["quantity"]) == 0 and "no_match" in p3["door"]["flags"]
    assert not p3["wall_ext"]["override"] and D(p3["wall_ext"]["quantity"]) == 90

    # a rejected revision changes nothing
    rows4 = _rows2()
    next(r for r in rows4 if r["element_key"] == SLAB).update(area_m2=999.0, geometry_hash="deadbeefdeadbeef")
    d4, _ = package(pid, rows4, parent_id=m3["revision_id"], parent_rows=rows3)
    rev4 = (await _upload(client, pid, tok, d4)).json()
    rej = await client.post(f"{BASE}/revisions/{rev4['revision_id']}/reject", headers=h, json={"comment": "no"})
    assert rej.status_code == 200
    p4 = _by_rule((await client.get(est, headers=h)).json())
    assert D(p4["slab"]["quantity"]) == 405


def _imp(ifc, props):
    from app.modules.design import rules

    return rules.Element("k/" + ifc, ifc, None, {"category": ifc, **props}, {"area_m2": 10})


async def test_imported_ifc_walls_get_type_key_from_is_external_only():
    from app.modules.design import rules

    ext_rule = next(r for r in rules.starter_set("DE")["rules"] if r["id"] == "wall_ext")
    int_rule = next(r for r in rules.starter_set("DE")["rules"] if r["id"] == "wall_int")
    flat = _imp("IfcWall", {"IsExternal": True})
    nested = _imp("IfcWall", {"Pset_WallCommon": {"IsExternal": "TRUE"}})
    inner = _imp("IfcWall", {"Pset_WallCommon": {"IsExternal": False}})
    unknown = _imp("IfcWall", {"FireRating": "F90"})
    els = [flat, nested, inner, unknown]
    assert (flat.type_key, nested.type_key, inner.type_key, unknown.type_key) == (
        "wall/ext",
        "wall/ext",
        "wall/int",
        "",
    )
    assert {e.key for e in rules.select(els, ext_rule["select"])} == {flat.key, nested.key}
    # an unknown wall stays out of wall_ext; an explicit type_key is never overridden
    assert unknown not in rules.select(els, ext_rule["select"])
    given = rules.Element("g", None, None, {"ifc_class": "IfcWall", "type_key": "wall/gen-x", "IsExternal": True}, {})
    assert given.type_key == "wall/gen-x"


async def test_imported_slab_predefined_type_and_unknowns():
    base = _imp("IfcSlab", {"PredefinedType": "BASESLAB"})
    roof = _imp("IfcSlab", {"PredefinedType": ".ROOF."})
    floor = _imp("IfcSlab", {"PredefinedType": "FLOOR"})
    assert (base.type_key, roof.type_key, floor.type_key) == ("slab/foundation", "slab/roof", "")
    assert _imp("IfcDoor", {"IsExternal": True}).type_key == ""
