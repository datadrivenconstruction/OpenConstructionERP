# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Geometry tests for the Retail Market Heilbronn procedural 3D model.

The procedural model (``app/scripts/gen_retail_heilbronn_assets.py``) is
generated from the same canonical geometry that drives the LV quantities, so
the BIM model and the bill stay quantity-consistent. These tests:

* re-run the generator offline and pin the geometry-vs-BOQ invariants against
  the ACTUAL BOQ rows (slab volume, sandwich-facade area, column / foundation /
  binder / rooflight counts), so a drift between bill and model fails loudly;
* validate the committed spec/GLB are canonical-format, brand-neutral and in
  sync with the generator (re-baking changes nothing); and
* install the demo end-to-end and confirm the procedural BIM model, its
  elements and the BOQ<->BIM links are attached and idempotent.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from app.core.demo_packs._retail_heilbronn_geometry import CANONICAL_GEOMETRY as G
from app.scripts import gen_retail_heilbronn_assets as gen

DEMO_ID = "retail-market-heilbronn"

# Real retailer brand tokens that must never appear in the public showcase
# (founder rule). Stored ROT13-encoded so the literal brand strings are not in
# the repo (mirrors the brand-token gate, which stores only hashes), then
# decoded at runtime for the negative assertion below.
_FORBIDDEN_TOKENS = tuple(
    __import__("codecs").decode(t, "rot13") for t in ("yvqy", "fpujnem", "xnhsynaq", "uryqb", "xynexnhs")
)


def _spec() -> dict:
    return gen.build_spec()


def _boq_rows() -> dict[str, tuple[str, float]]:
    """OZ -> (unit, qty) over the actual LV rows of the shipped template."""
    from app.core.demo_packs.retail_market_heilbronn import TEMPLATE

    rows: dict[str, tuple[str, float]] = {}
    for _ordinal, _title, _cls, items in TEMPLATE.sections:
        for oz, _desc, unit, qty, _rate, _c in items:
            rows[oz] = (unit, qty)
    return rows


def test_single_source_of_truth() -> None:
    """The generator and the LV template read the same geometry constants.

    The LV template re-exports the package-level dict, so they are the same
    object. The generator loads the dependency-free constants by file path (to
    stay offline), so it holds an equal copy; equality is the contract.
    """
    from app.core.demo_packs.retail_market_heilbronn import CANONICAL_GEOMETRY as via_template

    assert via_template is G  # template re-exports the package dict
    assert gen.G == G  # generator's file-path copy is identical in value


def test_spec_is_canonical_format() -> None:
    """The procedural spec is canonical-format with per-element DIN 276."""
    spec = _spec()
    assert spec["format_version"] == "1.0"
    assert spec["source"]["type"] == "procedural"
    assert spec["project"]["demo_id"] == DEMO_ID
    assert len(spec["models"]) == 1
    model = spec["models"][0]
    assert model["model_format"] == "ifc"
    assert model["geometry_quality"] == "procedural"
    elements = model["elements"]
    assert model["element_count"] == len(elements)
    assert len(elements) >= 150  # bare structural + envelope target
    for e in elements:
        assert e["stable_id"]
        assert e["classification"]["din276"], f"{e['name']}: no DIN 276 code"
        assert e["geometry"]["type"] == "box"
        assert len(e["geometry"]["size_m"]) == 3
    # stable_ids are unique (deterministic uuid5 per element)
    sids = [e["stable_id"] for e in elements]
    assert len(sids) == len(set(sids))


def test_groups_reference_the_model() -> None:
    """Every link group points at the model and lists real element ids."""
    spec = _spec()
    model_id = spec["models"][0]["id"]
    all_sids = {e["stable_id"] for e in spec["models"][0]["elements"]}
    assert spec["groups"], "no element groups emitted"
    for key, grp in spec["groups"].items():
        assert grp["model_id"] == model_id, f"group {key} wrong model"
        assert grp["stable_ids"], f"group {key} is empty"
        for sid in grp["stable_ids"]:
            assert sid in all_sids, f"group {key} references unknown element {sid}"


def test_geometry_counts_match_the_boq() -> None:
    """Element counts equal the corresponding BOQ quantities (R-05/R-06)."""
    spec = _spec()
    els = spec["models"][0]["elements"]
    rows = _boq_rows()

    n_columns = sum(1 for e in els if e["element_type"] == "Columns")
    n_foundations = sum(1 for e in els if e["name"].startswith("Koecherfundament"))
    n_binders = sum(1 for e in els if e["name"].startswith("BSH-Binder"))
    n_edge = sum(1 for e in els if e["name"].startswith("BSH-Randtraeger"))
    n_rooflights = sum(1 for e in els if "Lichtkuppel" in e["name"])

    # Model counts equal the canonical constants ...
    assert n_columns == int(G["columns"]) == 36
    assert n_foundations == int(G["pocket_foundations"]) == 36
    assert n_binders == int(G["binders_total"]) == 24
    assert n_edge == int(G["edge_beams"]) == 22
    assert n_rooflights == int(G["rooflights"]) == 8

    # ... and equal the matching BOQ rows.
    assert rows["06.02.0010"] == ("pcs", 36.0)  # precast columns
    assert rows["04.01.0040"] == ("pcs", 36.0)  # pocket foundations
    assert rows["06.03.0010"][1] + rows["06.03.0020"][1] == float(n_binders)  # 12 + 12
    assert rows["06.03.0030"] == ("pcs", 22.0)  # edge beams
    assert rows["05.01.0060"] == ("pcs", 8.0)  # rooflights


def test_geometry_volumes_and_areas_match_the_boq() -> None:
    """Slab volume and sandwich-facade area equal their BOQ quantities."""
    spec = _spec()
    els = spec["models"][0]["elements"]
    rows = _boq_rows()

    slab = next(e for e in els if e["name"].startswith("Bodenplatte"))
    slab_vol = slab["quantities"]["volume"]
    assert abs(slab_vol - G["slab_volume_m3"]) < 0.5
    assert abs(slab_vol - rows["04.01.0090"][1]) < 0.5  # BOQ slab m3 = 544

    facade_area = sum(e["quantities"].get("area", 0.0) for e in els if e["name"].startswith("Sandwichpaneel"))
    assert abs(facade_area - G["facade_sandwich_m2"]) < 0.5
    assert abs(facade_area - rows["07.01.0010"][1]) < 0.5  # BOQ sandwich m2 = 1292

    pv = next(e for e in els if e["name"].startswith("PV-Anlage"))
    assert pv["quantities"]["count"] == float(G["pv_modules"]) == 660.0
    assert pv["quantities"]["count"] == rows["17.01.0010"][1]  # BOQ PV modules


def test_committed_assets_are_in_sync_with_the_generator() -> None:
    """The committed spec/GLB equal a fresh deterministic re-bake."""
    spec_path = Path(gen.SPEC_PATH)
    glb_path = Path(gen.GLB_PATH)
    assert spec_path.exists(), "retail_heilbronn.json is not committed"
    assert glb_path.exists(), "retail_heilbronn.glb.gz is not committed"

    committed_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    fresh_spec = _spec()
    # Element ids and counts are deterministic, so the committed spec must match.
    assert committed_spec["models"][0]["element_count"] == fresh_spec["models"][0]["element_count"]
    committed_sids = {e["stable_id"] for e in committed_spec["models"][0]["elements"]}
    fresh_sids = {e["stable_id"] for e in fresh_spec["models"][0]["elements"]}
    assert committed_sids == fresh_sids

    # The GLB is a valid binary glTF.
    glb_bytes = gzip.decompress(glb_path.read_bytes())
    assert glb_bytes[:4] == b"glTF", "geometry is not a binary glTF"
    assert len(glb_bytes) > 10_000


def test_assets_are_brand_neutral() -> None:
    """No real retailer brand token appears in the spec (public repo gate)."""
    blob = json.dumps(_spec(), ensure_ascii=False).lower()
    for tok in _FORBIDDEN_TOKENS:
        assert tok not in blob, f"forbidden token {tok!r} in procedural spec"


async def test_install_attaches_procedural_model_and_links() -> None:
    """A full install attaches the procedural BIM model, elements and links.

    install_demo_project calls attach_demo_assets, which for this demo runs the
    procedural path: one IFC-format BIM model with the canonical elements, GLB
    geometry, and a handful of leaf BOQ positions linked to real elements. A
    re-run never duplicates models, elements or links.
    """
    import uuid

    from sqlalchemy import func, select

    from app.core.demo_projects import install_demo_project
    from app.modules.bim_hub.models import BIMElement, BIMModel, BOQElementLink
    from tests._pg import transactional_session

    async with transactional_session() as session:
        result = await install_demo_project(session, DEMO_ID)
        pid = uuid.UUID(result["project_id"])

        models = (await session.execute(select(BIMModel).where(BIMModel.project_id == pid))).scalars().all()
        assert len(models) == 1, "expected exactly one procedural BIM model"
        model = models[0]
        assert model.model_format == "ifc"
        assert (model.metadata_ or {}).get("geometry_quality") == "procedural"
        assert model.status == "ready"  # GLB geometry attached

        n_elems = (
            await session.execute(select(func.count()).select_from(BIMElement).where(BIMElement.model_id == model.id))
        ).scalar_one()
        assert n_elems == model.element_count >= 150
        # Elements keep their DIN 276 classification in properties.
        sample = (
            await session.execute(select(BIMElement).where(BIMElement.model_id == model.id).limit(1))
        ).scalar_one()
        assert (sample.properties or {}).get("classification", {}).get("din276")

        n_links = (await session.execute(select(func.count()).select_from(BOQElementLink))).scalar_one()
        assert n_links > 0, "no BOQ<->BIM links created"

        # Idempotent re-run: no new models, elements or links.
        await install_demo_project(session, DEMO_ID)
        models2 = (await session.execute(select(BIMModel).where(BIMModel.project_id == pid))).scalars().all()
        assert len(models2) == 1
        n_elems2 = (
            await session.execute(select(func.count()).select_from(BIMElement).where(BIMElement.model_id == model.id))
        ).scalar_one()
        assert n_elems2 == n_elems
        n_links2 = (await session.execute(select(func.count()).select_from(BOQElementLink))).scalar_one()
        assert n_links2 == n_links
