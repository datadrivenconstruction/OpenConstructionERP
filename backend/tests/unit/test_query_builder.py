# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the CWICR Qdrant query builder.

Pins the pure helpers (``unit_dim_for``, ``department_code_for``,
``extract_resource_hints``) and the end-to-end ``build_query`` so the
3-channel split (CORE / filters / resources) can't drift.
"""

from __future__ import annotations

import pytest

from app.core.match_service.envelope import ElementEnvelope
from app.modules.costs.query_builder import (
    QueryPayload,
    SearchPlan,
    build_query,
    build_search_plan,
    department_code_for,
    extract_resource_hints,
    unit_dim_for,
    unit_type_for,
)

# ── unit_dim_for ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("unit", "dim"),
    [
        ("m3", "volume"),
        ("m³", "volume"),
        ("CBM", "volume"),
        ("m2", "area"),
        ("m²", "area"),
        ("sqm", "area"),
        ("m", "length"),
        ("lm", "length"),
        ("kg", "mass"),
        ("t", "mass"),
        ("pcs", "count"),
        ("Stck", "count"),
        ("ea", "count"),
        ("h", "time"),
    ],
)
def test_unit_dim_known_units(unit: str, dim: str) -> None:
    assert unit_dim_for(unit) == dim


@pytest.mark.parametrize("unit", ["", None, "ls", "psch", "lsum", "weird-unit"])
def test_unit_dim_drops_when_unknown_or_lumpsum(unit: str | None) -> None:
    assert unit_dim_for(unit) is None


def test_unit_dim_strips_and_lowercases() -> None:
    assert unit_dim_for("  M3 ") == "volume"
    assert unit_dim_for("M2") == "area"


# ── unit_type_for (v3 DDC snapshot vocabulary, capitalised) ──────────────


@pytest.mark.parametrize(
    ("unit", "bucket"),
    [
        ("m3", "Volume"),
        ("m³", "Volume"),
        ("CBM", "Volume"),
        ("m2", "Area"),
        ("m²", "Area"),
        ("sqm", "Area"),
        ("sf", "Area"),
        ("m", "Linear"),
        ("lm", "Linear"),
        ("ft", "Linear"),
        ("kg", "Mass"),
        ("t", "Mass"),
        ("tonne", "Mass"),
        ("pcs", "Count"),
        ("Stck", "Count"),
        ("ea", "Count"),
        ("h", "Time"),
    ],
)
def test_unit_type_known_units(unit: str, bucket: str) -> None:
    """``unit_type_for`` returns the snapshot's capitalised bucket name."""
    assert unit_type_for(unit) == bucket


@pytest.mark.parametrize("unit", ["", None, "ls", "psch", "lsum", "weird-unit"])
def test_unit_type_drops_when_unknown_or_lumpsum(unit: str | None) -> None:
    assert unit_type_for(unit) is None


def test_unit_type_strips_and_lowercases_input_keeping_output_capitalised() -> None:
    assert unit_type_for("  M3 ") == "Volume"
    assert unit_type_for("M2") == "Area"


# ── department_code_for ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("330", "33"),
        ("334", "33"),
        ("350", "35"),
        ("440", "44"),
        ("330.10", "33"),
        ("044", "04"),
        ("33", "33"),
    ],
)
def test_department_code_collapses_to_2digit_prefix(hint: str, expected: str) -> None:
    assert department_code_for(hint) == expected


@pytest.mark.parametrize("hint", ["", None, "abc", "X33", "trade-architectural"])
def test_department_code_returns_none_for_non_numeric(hint: str | None) -> None:
    assert department_code_for(hint) is None


# ── extract_resource_hints ───────────────────────────────────────────────


def _envelope_with(description: str, properties: dict | None = None) -> ElementEnvelope:
    return ElementEnvelope(
        source="bim",
        category="wall",
        description=description,
        properties=properties or {},
    )


def test_resource_hints_concrete_grade() -> None:
    env = _envelope_with("Stahlbetonwand C30/37, 240mm")
    assert "C30/37" in extract_resource_hints(env)


def test_resource_hints_rebar_grade() -> None:
    env = _envelope_with("Bewehrung B500B, 12mm")
    assert "B500B" in extract_resource_hints(env)


def test_resource_hints_pipe_nominal() -> None:
    env = _envelope_with("Heizungsleitung DN200")
    assert "DN200" in extract_resource_hints(env)


def test_resource_hints_steel_profile() -> None:
    env = _envelope_with("Stahlträger HEB200")
    assert "HEB200" in extract_resource_hints(env)


def test_resource_hints_bolt_size() -> None:
    env = _envelope_with("Verbindung mit M16x60")
    assert "M16X60" in extract_resource_hints(env)


def test_resource_hints_dedupes_across_description_and_properties() -> None:
    env = _envelope_with(
        "Stahlbetonwand C30/37",
        properties={"concrete_grade": "C30/37", "rebar_grade": "B500B"},
    )
    hints = extract_resource_hints(env)
    assert hints.count("C30/37") == 1
    assert "B500B" in hints


def test_resource_hints_empty_envelope() -> None:
    assert extract_resource_hints(_envelope_with("")) == []


def test_resource_hints_no_signal() -> None:
    """An envelope with no rare tokens should produce zero hints — the
    resources named vector then drops out of the RRF fusion."""
    env = _envelope_with("Internal partition wall")
    assert extract_resource_hints(env) == []


# ── build_query end-to-end ───────────────────────────────────────────────


def test_build_query_dense_concrete_wall_has_full_payload() -> None:
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall, Stahlbetonwand, Beton C30/37, thickness 240mm, fire F90",
        unit_hint="m3",
        classifier_hint={"din276": "330"},
    )
    payload = build_query(env)

    assert isinstance(payload, QueryPayload)
    assert "Stahlbetonwand" in payload.core_query
    assert "C30/37" in payload.core_query  # CORE keeps the verbatim grade for sparse
    # v3 emits the capitalised ``unit_type`` (DDC snapshot vocabulary),
    # NOT the legacy lowercase ``unit_dim``.
    assert payload.filters == {
        "is_abstract": False,
        "department_code": "33",
        "unit_type": "Volume",
    }
    assert payload.resources_query is not None
    assert "C30/37" in payload.resources_query


def test_build_query_no_classifier_drops_department() -> None:
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Generic wall",
        unit_hint="m2",
    )
    payload = build_query(env)
    assert "department_code" not in payload.filters
    assert payload.filters["unit_type"] == "Area"


def test_build_query_lump_sum_drops_unit_filter() -> None:
    env = ElementEnvelope(
        source="bim",
        category="general",
        description="Site mobilisation",
        unit_hint="lsum",
    )
    payload = build_query(env)
    assert "unit_type" not in payload.filters
    assert "unit_dim" not in payload.filters


def test_build_query_no_resources_when_envelope_lacks_rare_tokens() -> None:
    env = ElementEnvelope(
        source="bim",
        category="finish",
        description="Painted gypsum board ceiling",
        unit_hint="m2",
    )
    payload = build_query(env)
    assert payload.resources_query is None


def test_build_query_disabled_resources_returns_none_even_with_hints() -> None:
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall C30/37 240mm",
        unit_hint="m3",
    )
    payload = build_query(env, include_resources=False)
    assert payload.resources_query is None


def test_build_query_disabled_filters_returns_minimal_filter_dict() -> None:
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        unit_hint="m3",
        classifier_hint={"din276": "330"},
    )
    payload = build_query(
        env,
        include_unit_filter=False,
        include_department_filter=False,
        drop_abstract=False,
    )
    assert payload.filters == {}


def test_build_query_search_kwargs_are_splat_friendly() -> None:
    env = ElementEnvelope(source="bim", category="wall", description="Wall, m3", unit_hint="m3")
    payload = build_query(env)
    kwargs = payload.search_kwargs
    assert set(kwargs) == {"core_query", "filters", "resources_query"}
    # Caller passes country separately — must NOT leak into search_kwargs
    assert "country" not in kwargs


def test_build_query_infers_unit_from_quantities_when_hint_missing() -> None:
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        quantities={"volume_m3": 9.0, "area_m2": 37.5, "length_m": 12.5},
    )
    payload = build_query(env)
    # volume_m3 wins — first non-zero key in priority order. v3 emits
    # the capitalised ``unit_type`` (Volume), not the legacy
    # lowercase ``unit_dim`` (volume).
    assert payload.filters.get("unit_type") == "Volume"


def test_build_query_truncates_long_descriptions() -> None:
    long_desc = "Wall " * 200  # 1000 chars
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description=long_desc,
    )
    payload = build_query(env)
    assert len(payload.core_query) <= 512


# ── build_search_plan (v3) ───────────────────────────────────────────────


def test_search_plan_has_dense_and_sparse_query() -> None:
    """v3 SearchPlan exposes the same text on both channels — BGE-M3
    emits dense + sparse from one forward pass."""
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall, Stahlbeton C30/37, thickness 240mm",
        unit_hint="m3",
    )
    plan = build_search_plan(env)
    assert isinstance(plan, SearchPlan)
    assert plan.dense_query == plan.sparse_query
    assert "Stahlbeton" in plan.dense_query


def test_search_plan_routes_ifc_class_to_hard_filters() -> None:
    """``ifc_class`` from the BIM extractor lands in hard_filters —
    BIM is authoritative per §4.2.1."""
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        unit_hint="m3",
        ifc_class="IfcWall",
        ifc_predefined_type="PARTITIONING",
    )
    plan = build_search_plan(env)
    assert plan.hard_filters.get("ifc_class") == "IfcWall"
    assert plan.hard_filters.get("ifc_predefined_type") == "PARTITIONING"


def test_search_plan_routes_pset_booleans_to_hard_filters_only_when_true() -> None:
    """``is_external=True`` from a Pset is hard. ``is_external=False``
    or ``None`` are not forwarded — most CWICR rates don't carry a
    "definitely not external" flag, so a False predicate would
    over-narrow."""
    env_t = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        unit_hint="m3",
        is_external=True,
        is_loadbearing=True,
        is_structural=True,
    )
    plan = build_search_plan(env_t)
    assert plan.hard_filters.get("is_external") is True
    assert plan.hard_filters.get("is_loadbearing") is True
    assert plan.hard_filters.get("is_structural") is True

    env_f = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        unit_hint="m3",
        is_external=False,
        is_loadbearing=False,
        is_structural=False,
    )
    plan_f = build_search_plan(env_f)
    assert "is_external" not in plan_f.hard_filters
    assert "is_loadbearing" not in plan_f.hard_filters
    assert "is_structural" not in plan_f.hard_filters

    env_n = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        unit_hint="m3",
    )
    plan_n = build_search_plan(env_n)
    assert "is_external" not in plan_n.hard_filters


def test_search_plan_routes_construction_stage_to_hard_filters() -> None:
    """User-picked ``construction_stage_hint`` is hard — when the user
    explicitly narrowed the search in the UI, we trust it."""
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        unit_hint="m3",
        construction_stage_hint="05_Structure",
    )
    plan = build_search_plan(env)
    assert plan.hard_filters.get("construction_stage") == "05_Structure"


def test_search_plan_routes_ost_category_to_soft_boosts() -> None:
    """``ost_category`` is heuristic — Revit family naming
    occasionally mislabels category vs ifc_class. Soft boost only."""
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        unit_hint="m3",
        ost_category="OST_Walls",
    )
    plan = build_search_plan(env)
    assert "ost_category" not in plan.hard_filters
    assert any(b[0] == "ost_category" and b[1] == "OST_Walls" for b in plan.soft_boosts)


def test_search_plan_routes_material_class_and_size_to_soft_boosts() -> None:
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        unit_hint="m3",
        material_class="concrete",
        nominal_size_mm=240,
    )
    plan = build_search_plan(env)
    assert "material_class" not in plan.hard_filters
    assert "nominal_size_mm" not in plan.hard_filters
    fields = {b[0]: b[1] for b in plan.soft_boosts}
    assert fields.get("material_class") == "concrete"
    assert fields.get("nominal_size_mm") == 240


def test_search_plan_empty_envelope_has_no_v3_fields() -> None:
    """Envelopes that don't populate v3 fields (legacy / PDF / DWG)
    produce a plan with no v3 hard/soft entries — only the Phase-1
    ``is_abstract`` / ``unit_dim`` predicates remain."""
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        unit_hint="m3",
    )
    plan = build_search_plan(env)
    assert "ifc_class" not in plan.hard_filters
    assert "is_external" not in plan.hard_filters
    assert "construction_stage" not in plan.hard_filters
    assert plan.soft_boosts == []


def test_build_query_back_compat_still_works() -> None:
    """The pre-v3 ``build_query`` path returns ``QueryPayload`` and
    skips the v3 fields entirely so the smoke endpoint and eval
    harness keep their bit-for-bit contract."""
    env = ElementEnvelope(
        source="bim",
        category="wall",
        description="Wall",
        unit_hint="m3",
        ifc_class="IfcWall",  # would be hard in SearchPlan
        ost_category="OST_Walls",  # would be soft in SearchPlan
    )
    payload = build_query(env)
    assert isinstance(payload, QueryPayload)
    # QueryPayload exposes ``filters`` only, not ``soft_boosts`` —
    # but build_query NOW delegates through build_search_plan so
    # ifc_class IS forwarded to ``filters``. ost_category isn't.
    assert payload.filters.get("ifc_class") == "IfcWall"
    assert "ost_category" not in payload.filters


def test_search_plan_search_kwargs_match_qdrant_adapter_contract() -> None:
    """``plan.search_kwargs`` splats into ``qdrant_adapter.search`` —
    must contain ``core_query`` / ``filters`` / ``resources_query``
    and nothing else."""
    env = ElementEnvelope(source="bim", category="wall", description="Wall", unit_hint="m3")
    plan = build_search_plan(env)
    kwargs = plan.search_kwargs
    assert set(kwargs) == {"core_query", "filters", "resources_query"}
