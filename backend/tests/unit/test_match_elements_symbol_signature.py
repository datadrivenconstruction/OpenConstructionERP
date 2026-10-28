# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the deterministic symbol-signature recogniser (item #18).

Coverage:
    * Signature computation: dimension extraction (SI + bare keys + mm),
      ratio derivation, property fingerprint, determinism.
    * Ranking: a clean door/window/column/beam/wall/pipe descriptor ranks
      its own archetype first; confidence is monotone in signal strength;
      ties break deterministically by symbol id; empty library and unknown
      category degrade gracefully.
    * Confidence semantics: scores stay in [0, 1]; bands map correctly.
    * The stored-group descriptor helper + a DB-backed pass that reads a
      real MatchGroup row back through a transactional session and ranks
      it (exercises the stored-elements path).

None of this is computer vision - the recogniser only consumes structured
descriptors. Raster CV detection is the separate cv-pipeline service.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.match_elements.models import MatchGroup, MatchSession
from app.modules.match_elements.signature_match_service import (
    SignatureMatchService,
    descriptor_from_group_row,
    get_signature_service,
)
from app.modules.match_elements.symbol_signature import (
    RatioRange,
    SymbolArchetype,
    compute_signature,
    extract_dimensions,
    seed_library,
)
from app.modules.projects.models import Project
from tests._pg import transactional_session

# ── Descriptor fixtures (clean archetype shapes, in metres) ───────────────

DOOR = {
    "category": "door",
    "quantities": {"height_m": 2.1, "width_m": 0.9},
    "properties": {"ifc_class": "IfcDoor"},
}
WINDOW = {
    "category": "window",
    "quantities": {"height_m": 1.2, "width_m": 1.5},
    "properties": {"ifc_class": "IfcWindow", "is_external": True},
}
COLUMN = {
    "category": "column",
    "quantities": {"height_m": 3.0, "width_m": 0.3, "length_m": 0.3},
    "properties": {"ifc_class": "IfcColumn", "is_loadbearing": True},
}
BEAM = {
    "category": "beam",
    "quantities": {"length_m": 6.0, "height_m": 0.4, "width_m": 0.3},
    "properties": {"ifc_class": "IfcBeam", "is_structural": True},
}
WALL = {
    "category": "wall",
    "quantities": {
        "length_m": 8.0,
        "height_m": 3.0,
        "width_m": 0.24,
        "area_m2": 24.0,
        "volume_m3": 5.76,
    },
    "properties": {"ifc_class": "IfcWall", "is_loadbearing": True},
}
PIPE = {
    "category": "pipe",
    "quantities": {"length_m": 12.0, "diameter_m": 0.1},
    "properties": {"system_type": "pipe", "ifc_class": "IfcPipeSegment"},
}


# ── Dimension extraction ──────────────────────────────────────────────────


def test_extract_dimensions_si_keys() -> None:
    dims = extract_dimensions({"length_m": 8.0, "area_m2": 24.0, "volume_m3": 5.76})
    assert dims == {"length": 8.0, "area": 24.0, "volume": 5.76}


def test_extract_dimensions_bare_and_thickness_alias() -> None:
    dims = extract_dimensions({"length": 5, "thickness": 0.2, "height": 3})
    assert dims["length"] == 5.0
    assert dims["width"] == 0.2  # thickness aliases width
    assert dims["height"] == 3.0


def test_extract_dimensions_mm_scaled_to_metres() -> None:
    dims = extract_dimensions({"nominal_size_mm": 240})
    assert dims["diameter"] == pytest.approx(0.24)


def test_extract_dimensions_drops_zero_and_none() -> None:
    dims = extract_dimensions({"length_m": 0.0, "width_m": None, "height_m": 2.5})
    assert "length" not in dims
    assert "width" not in dims
    assert dims["height"] == 2.5


def test_extract_dimensions_numeric_string_prefix() -> None:
    dims = extract_dimensions({"width": "240 mm"})  # honoured as 240
    assert dims["width"] == 240.0


def test_extract_dimensions_empty_and_none() -> None:
    assert extract_dimensions(None) == {}
    assert extract_dimensions({}) == {}


# ── Signature computation ─────────────────────────────────────────────────


def test_compute_signature_door_ratios() -> None:
    sig = compute_signature(DOOR)
    assert sig.category == "door"
    # 2.1 / 0.9 -> aspect ~2.33; height/plan(0.9) -> slenderness ~2.33.
    assert sig.ratios["aspect"] == pytest.approx(2.3333, abs=1e-3)
    assert sig.ratios["slenderness"] == pytest.approx(2.3333, abs=1e-3)
    assert "ifc_class=ifcdoor" in sig.property_fingerprint


def test_compute_signature_is_deterministic() -> None:
    assert compute_signature(WALL) == compute_signature(dict(WALL))


def test_compute_signature_diameter_sets_roundness_flag() -> None:
    sig = compute_signature(PIPE)
    assert sig.ratios.get("roundness") == 1.0


def test_compute_signature_planarity_from_area_volume() -> None:
    sig = compute_signature(WALL)
    # 24 / 5.76 -> ~4.17 (a thin plate-like wall).
    assert sig.ratios["planarity"] == pytest.approx(4.1667, abs=1e-3)


def test_compute_signature_property_fingerprint_sorted_and_normalised() -> None:
    sig = compute_signature(
        {
            "category": "wall",
            "properties": {"material": "Stahlbeton C30/37", "is_external": True},
        },
    )
    # Sorted, lower-cased, accent-folded tokens.
    assert sig.property_fingerprint == (
        "is_external=true",
        "material=stahlbeton c30/37",
    )


def test_compute_signature_ignores_noise_properties() -> None:
    sig = compute_signature(
        {"category": "door", "properties": {"guid": "abc-123", "created_at": "2026"}},
    )
    assert sig.property_fingerprint == ()


# ── Ranking: each archetype ranks itself first ────────────────────────────


@pytest.mark.parametrize(
    ("descriptor", "expected"),
    [
        (DOOR, "door"),
        (WINDOW, "window"),
        (COLUMN, "column"),
        (BEAM, "beam"),
        (WALL, "wall"),
        (PIPE, "pipe"),
    ],
)
def test_clean_descriptor_ranks_own_archetype_first(
    descriptor: dict,
    expected: str,
) -> None:
    svc = SignatureMatchService()
    result = svc.suggest(descriptor)
    assert result.suggestions, "expected at least one suggestion"
    assert result.suggestions[0].symbol == expected
    assert result.suggestions[0].rank == 0
    # A clean, category-matching descriptor should be high confidence.
    assert result.suggestions[0].confidence_band == "high"


def test_suggestions_ranked_descending_confidence() -> None:
    svc = SignatureMatchService()
    result = svc.suggest(DOOR)
    confidences = [s.confidence for s in result.suggestions]
    assert confidences == sorted(confidences, reverse=True)
    # ranks are contiguous from 0.
    assert [s.rank for s in result.suggestions] == list(range(len(result.suggestions)))


def test_confidence_within_unit_interval() -> None:
    svc = SignatureMatchService()
    for descriptor in (DOOR, WINDOW, COLUMN, BEAM, WALL, PIPE):
        for s in svc.suggest(descriptor, top_k=20).suggestions:
            assert 0.0 <= s.confidence <= 1.0


def test_confidence_monotonic_in_signal_strength() -> None:
    """More agreeing signals -> higher confidence for the same archetype."""
    svc = SignatureMatchService()

    def conf_for(descriptor: dict, symbol: str) -> float:
        for s in svc.suggest(descriptor, top_k=20).suggestions:
            if s.symbol == symbol:
                return s.confidence
        return 0.0

    # 1. category only (no geometry, no keyword hints).
    cat_only = {"category": "door"}
    # 2. category + door-shaped geometry.
    cat_geom = {"category": "door", "quantities": {"height_m": 2.1, "width_m": 0.9}}
    # 3. category + geometry + matching property hint.
    cat_geom_kw = dict(DOOR)

    c1 = conf_for(cat_only, "door")
    c2 = conf_for(cat_geom, "door")
    c3 = conf_for(cat_geom_kw, "door")
    assert c1 < c2 < c3


def test_top_k_limits_results() -> None:
    svc = SignatureMatchService()
    result = svc.suggest(DOOR, top_k=2)
    assert len(result.suggestions) == 2


def test_min_confidence_filters_low_scorers() -> None:
    svc = SignatureMatchService()
    full = svc.suggest(DOOR, top_k=20)
    filtered = svc.suggest(DOOR, top_k=20, min_confidence=0.5)
    assert len(filtered.suggestions) <= len(full.suggestions)
    assert all(s.confidence >= 0.5 for s in filtered.suggestions)
    # ranks remain contiguous after filtering (no holes).
    assert [s.rank for s in filtered.suggestions] == list(
        range(len(filtered.suggestions)),
    )


# ── Tie-breaking, empty library, unknown category ────────────────────────


def test_tie_break_is_deterministic_by_symbol_id() -> None:
    """Two archetypes that score identically order by symbol id ascending."""
    # Build a library where two archetypes are indistinguishable for a
    # category-less, geometry-less descriptor (both score exactly 0).
    lib = (
        SymbolArchetype(symbol="zeta", categories=frozenset({"zeta"})),
        SymbolArchetype(symbol="alpha", categories=frozenset({"alpha"})),
    )
    svc = SignatureMatchService(library=lib)
    result = svc.suggest({"category": "unknownthing"})
    symbols = [s.symbol for s in result.suggestions]
    # Equal (zero) confidence -> ascending symbol id.
    assert symbols == ["alpha", "zeta"]


def test_empty_library_returns_no_suggestions() -> None:
    svc = SignatureMatchService(library=())
    result = svc.suggest(DOOR)
    assert result.suggestions == []
    # Signature is still computed and echoed back.
    assert result.signature.category == "door"


def test_unknown_category_does_not_crash() -> None:
    svc = SignatureMatchService()
    result = svc.suggest({"category": "spaceship", "quantities": {"length_m": 99.0}})
    # No archetype should claim high confidence for nonsense.
    assert all(s.confidence_band != "high" for s in result.suggestions)


def test_empty_descriptor_yields_low_confidence() -> None:
    svc = SignatureMatchService()
    result = svc.suggest({})
    assert result.signature.category == ""
    assert all(s.confidence_band == "low" for s in result.suggestions)


def test_result_note_is_honest_about_no_cv() -> None:
    result = SignatureMatchService().suggest(DOOR)
    assert "cv-pipeline" in result.note.lower()


def test_factors_explain_top_suggestion() -> None:
    result = SignatureMatchService().suggest(DOOR)
    top = result.suggestions[0]
    names = {f["name"] for f in top.factors}
    assert "category" in names
    assert any(n.startswith("ratio:") for n in names)
    assert any(n.startswith("keyword:") for n in names)


def test_get_signature_service_is_singleton() -> None:
    assert get_signature_service() is get_signature_service()


# ── RatioRange fit semantics ──────────────────────────────────────────────


def test_ratio_range_fit_inside_and_decay() -> None:
    rng = RatioRange("aspect", 2.0, 3.0, 1.0)
    assert rng.fit(2.5) == 1.0  # inside -> full
    assert rng.fit(3.5) == pytest.approx(0.5)  # half a tolerance past high
    assert rng.fit(5.0) == 0.0  # well past -> clamped to 0
    assert rng.fit(1.0) == 0.0  # a full tolerance below low -> 0


# ── descriptor_from_group_row helper ──────────────────────────────────────


def test_descriptor_from_group_key_parsing() -> None:
    desc = descriptor_from_group_row(
        "ifc_class:IfcWall|material:Stahlbeton|thickness:240",
        {"area_m2": 24.0, "volume_m3": 5.76},
        None,
    )
    assert desc["category"] == "IfcWall"
    assert desc["properties"]["material"] == "Stahlbeton"
    assert desc["properties"]["thickness"] == "240"
    assert desc["quantities"]["area_m2"] == 24.0


def test_descriptor_from_group_skips_empty_segments() -> None:
    desc = descriptor_from_group_row("ifc_class:IfcDoor|material:∅", {}, None)
    assert desc["category"] == "IfcDoor"
    assert "material" not in desc["properties"]


def test_descriptor_metadata_overrides_key() -> None:
    desc = descriptor_from_group_row(
        "ifc_class:IfcWall",
        {},
        {"category": "wall", "properties": {"is_loadbearing": True}},
    )
    # Metadata category beats the key-parsed one.
    assert desc["category"] == "wall"
    assert desc["properties"]["is_loadbearing"] is True


# ── DB-backed: rank a real stored MatchGroup row ──────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # The round-trip test seeds cross-module scaffolding rows (project ->
    # match session -> group) only to exercise the stored-group readback path;
    # FK integrity is not what is under test, so suppress the triggers.
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest.mark.asyncio
async def test_suggest_from_stored_group_round_trip(session: AsyncSession) -> None:
    """Persist a MatchGroup, read it back, build a descriptor, rank it.

    Exercises the stored-elements path the /suggest-symbols endpoint uses
    when a session_id + group_key reference an existing group.
    """
    owner_id = uuid.uuid4()
    project = Project(
        id=uuid.uuid4(),
        name="Symbol Signature Test Project",
        owner_id=owner_id,
    )
    match_session = MatchSession(
        id=uuid.uuid4(),
        project_id=project.id,
        source="bim",
        name="sig-test",
    )
    group = MatchGroup(
        id=uuid.uuid4(),
        session_id=match_session.id,
        group_key="ifc_class:IfcColumn|material:Concrete",
        element_ids=["e1", "e2"],
        element_count=2,
        quantities={"height_m": 3.0, "width_m": 0.3, "length_m": 0.3},
        metadata_={"properties": {"is_loadbearing": True}},
        status="unmatched",
    )
    session.add_all([project, match_session, group])
    await session.flush()

    # Read the row back through the session (the stored-elements path).
    row = (
        await session.execute(
            select(
                MatchGroup.group_key,
                MatchGroup.quantities,
                MatchGroup.metadata_,
            ).where(
                MatchGroup.session_id == match_session.id,
                MatchGroup.group_key == "ifc_class:IfcColumn|material:Concrete",
            ),
        )
    ).first()
    assert row is not None

    descriptor = descriptor_from_group_row(row[0], row[1], row[2])
    result = SignatureMatchService().suggest(descriptor)

    assert result.suggestions[0].symbol == "column"
    assert result.suggestions[0].confidence_band in ("high", "medium")
    # is_loadbearing keyword hint from metadata survives the round-trip.
    sig = compute_signature(descriptor)
    assert "is_loadbearing=true" in sig.property_fingerprint


@pytest.mark.asyncio
async def test_seed_library_covers_required_symbols() -> None:
    symbols = {a.symbol for a in seed_library()}
    assert {"door", "window", "column", "beam", "wall", "pipe", "duct", "fixture"} <= symbols
