# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the AI Estimate Builder service-layer logic.

These are pure unit tests (no DB, no HTTP, no AI key, no Qdrant). They pin the
load-bearing pure-logic invariants of the new ``oe_ai_estimator`` module:

    * Money / quantity helpers are Decimal-end-to-end and never round through
      float, including the CWICR ``"100 m3"`` unit-multiplier unwind.
    * Confidence is a real [0,1] float or None - never a fabricated 0.5
      placeholder; the band derives deterministically from the real score.
    * Deterministic grouping primitives (signature derivation, canonical
      quantity picking, trade taxonomy) work with no AI key.
    * Source normalisation turns rows / text into source-agnostic envelopes
      and refuses to promote a synthetic label into a Qdrant hard filter.
    * The grounded-rate envelope carries the project currency hard filter.

The stateful FSM walk + grouping + matching + FX rollup + apply are exercised
end-to-end (with the real ``expire_all``-driven re-read path and a greenlet
context) in ``tests/integration/test_ai_estimator_api.py``; these unit tests
own the deterministic building blocks those flows compose.

Run:
    cd backend
    python -m pytest tests/unit/ai_estimator/test_ai_estimator_service.py -q
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.ai_estimator import service as svc
from app.modules.ai_estimator.service import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    AiEstimatorService,
    _confidence_band,
    _dec,
    _pick_unit,
    _quantity_for_unit,
    _split_unit_multiplier,
)
from app.modules.ai_estimator.taxonomy import TRADE_ORDER, classify_trade

# ── Money / quantity helpers (Decimal end-to-end) ────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("185.00", Decimal("185.00")),
        (185, Decimal("185")),
        (1.5, Decimal("1.5")),
        (Decimal("12.34"), Decimal("12.34")),
        (None, Decimal("0")),
        ("not-a-number", Decimal("0")),
        ("", Decimal("0")),
        (float("inf"), Decimal("0")),
        (float("nan"), Decimal("0")),
    ],
)
def test_dec_coerces_without_raising(value, expected):
    """``_dec`` coerces anything to a finite Decimal, defaulting junk to 0."""
    assert _dec(value) == expected


def test_quantity_for_unit_maps_canonical_dimensions():
    qty = {"volume_m3": 9.0, "area_m2": 37.5, "length_m": 12.0, "mass_kg": 2000.0, "count": 3.0}
    assert _quantity_for_unit(qty, "m3") == 9.0
    assert _quantity_for_unit(qty, "m2") == 37.5
    assert _quantity_for_unit(qty, "m") == 12.0
    assert _quantity_for_unit(qty, "kg") == 2000.0
    # tonnes derived from kg.
    assert _quantity_for_unit(qty, "t") == pytest.approx(2.0)
    assert _quantity_for_unit(qty, "pcs") == 3.0
    # Unknown unit falls back to count.
    assert _quantity_for_unit(qty, "lump") == 3.0


def test_pick_unit_prefers_most_specific_nonzero_dimension():
    assert _pick_unit({"volume_m3": 9.0, "area_m2": 37.5}) == "m3"
    assert _pick_unit({"area_m2": 37.5}) == "m2"
    assert _pick_unit({"length_m": 5.0}) == "m"
    assert _pick_unit({"mass_kg": 100.0}) == "kg"
    assert _pick_unit({"count": 4.0}) == "pcs"
    # Empty / all-zero -> pcs (a countable default).
    assert _pick_unit({}) == "pcs"
    assert _pick_unit({"volume_m3": 0.0}) == "pcs"


@pytest.mark.parametrize(
    ("unit", "mult", "base_unit"),
    [
        ("100 m3", Decimal("100"), "m3"),
        ("10 pcs", Decimal("10"), "pcs"),
        ("m2", Decimal("1"), "m2"),
        ("", Decimal("1"), ""),
        (None, Decimal("1"), ""),
        # A bare unit with no leading number stays as-is, mult 1.
        ("kg", Decimal("1"), "kg"),
    ],
)
def test_split_unit_multiplier(unit, mult, base_unit):
    """CWICR ``"100 m3"`` multiplier is peeled so per-base-unit rates are right."""
    assert _split_unit_multiplier(unit) == (mult, base_unit)


def test_candidate_unit_rate_divides_by_multiplier():
    """A "100 m3 @ 18500" rate becomes 185.00 per m3 - never 100x off."""

    class _Cand:
        unit_rate = "18500.00"
        unit = "100 m3"

    assert _dec(AiEstimatorService._candidate_unit_rate(_Cand())) == Decimal("185")


# ── Confidence (real score or None, never a placeholder) ─────────────────────


def test_confidence_band_derives_from_real_score():
    assert _confidence_band(None) == "none"
    assert _confidence_band(CONFIDENCE_HIGH_THRESHOLD) == "high"
    assert _confidence_band(CONFIDENCE_HIGH_THRESHOLD + 0.05) == "high"
    assert _confidence_band(CONFIDENCE_MEDIUM_THRESHOLD) == "medium"
    assert _confidence_band(CONFIDENCE_MEDIUM_THRESHOLD - 0.01) == "low"
    assert _confidence_band(0.0) == "low"


def test_thresholds_match_api_contract():
    """The contract pins high>=0.78, medium>=0.62; the UI reads them off the API."""
    assert pytest.approx(0.78) == CONFIDENCE_HIGH_THRESHOLD
    assert pytest.approx(0.62) == CONFIDENCE_MEDIUM_THRESHOLD


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.83, 0.83),
        (0.0, 0.0),
        (1.0, 1.0),
        (1.5, None),  # out of [0,1] -> None, never clamped to a fake value
        (-0.2, None),
        ("not-a-number", None),
        (None, None),
    ],
)
def test_real_confidence_rejects_out_of_range_and_junk(value, expected):
    out = AiEstimatorService._real_confidence(value)
    if expected is None:
        assert out is None
    else:
        assert out == pytest.approx(expected)


def test_candidate_out_serialises_grounded_only_fields():
    """A serialised candidate carries only grounded fields, money as a string."""

    class _Cand:
        id = "cand-1"
        code = "WALL-001"
        description = "Reinforced concrete wall"
        unit = "m3"
        unit_rate = "185.00"
        currency = "EUR"
        score = 0.834567
        confidence_band = "high"

    out = AiEstimatorService._candidate_out(_Cand())
    assert out["candidate_id"] == "cand-1"
    assert out["code"] == "WALL-001"
    assert out["unit_rate"] == "185.00"  # decimal string, not float
    assert out["currency"] == "EUR"
    assert out["score"] == pytest.approx(0.8346, abs=1e-4)  # rounded to 4 dp
    assert out["confidence_band"] == "high"


# ── Trade taxonomy (deterministic, works with no AI) ─────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Reinforced concrete wall C30/37", "structure"),
        ("Excavation and backfill of trench", "earthworks"),
        ("Strip foundation footing", "foundations"),
        ("Clay brick masonry wall", "masonry"),
        ("Facade cladding panels", "envelope"),
        ("Aluminium window double glazing", "openings"),
        ("Cement screed floor finish", "finishes"),
        ("HVAC ductwork and ventilation", "mep_mechanical"),
        ("Sanitary drainage pipework", "mep_plumbing"),
        ("Electrical wiring and lighting", "mep_electrical"),
        ("Landscaping and external paving", "sitework"),
        ("Demolition and strip out", "demolition"),
        ("Some entirely generic line item", "other"),
        ("", "other"),
    ],
)
def test_classify_trade_buckets(text, expected):
    assert classify_trade(text) == expected


def test_classify_trade_is_multilingual_and_uses_all_parts():
    # German + Russian stems classify without a translation hop.
    assert classify_trade("Stahlbetonwand") == "structure"
    assert classify_trade("Земляные работы") == "earthworks"
    # Joins all supplied parts (description, category, ifc_class).
    assert classify_trade("generic", "walls", "IfcWall concrete") == "structure"


def test_every_trade_key_has_a_stable_order_slot():
    # 'other' is always present so the per-category summary never misses a bucket.
    assert "other" in TRADE_ORDER
    assert classify_trade("nonsense") in TRADE_ORDER


# ── Source normalisation (rows + text -> envelopes; no AI) ────────────────────


def test_normalise_rows_into_envelopes():
    service = AiEstimatorService.__new__(AiEstimatorService)  # no DB needed
    envelopes = service._normalise_sources(
        {
            "rows": [
                {"description": "Concrete wall", "qty": 10.0, "unit": "m3", "category": "walls", "code": "C-001"},
                {"description": "", "qty": 5.0, "unit": "m2"},  # blank desc -> skipped
                {"name": "Slab", "quantity": 80.0, "unit": "m2"},  # 'name' + 'quantity' aliases
            ]
        }
    )
    # The blank-description row is dropped.
    assert len(envelopes) == 2
    wall = envelopes[0]
    assert wall["description"] == "Concrete wall"
    assert wall["unit_hint"] == "m3"
    assert wall["quantities"] == {"volume_m3": 10.0}
    # A real-looking catalogue code is promoted as exact_code.
    assert wall["exact_code"] == "C-001"
    slab = envelopes[1]
    assert slab["quantities"] == {"area_m2": 80.0}


def test_normalise_text_one_envelope_per_line():
    service = AiEstimatorService.__new__(AiEstimatorService)
    envelopes = service._normalise_sources({"text_input": "Brick wall, 24cm\n\nx\nReinforced concrete wall\n"})
    # Blank line + the too-short "x" (< 3 chars) are dropped.
    descriptions = [e["description"] for e in envelopes]
    assert descriptions == ["Brick wall, 24cm", "Reinforced concrete wall"]
    # Text envelopes carry no measured quantity (the grouping pass never invents).
    assert all(e["quantities"] == {} for e in envelopes)
    assert all(e["source"] == "text" for e in envelopes)


def test_text_clause_split_treats_dimension_comma_as_spec_continuation():
    """A comma followed by a bare dimension spec (number + cm/mm/m, no trailing
    descriptive word) is a spec continuation, NOT a list separator. So
    'Brick wall, 24cm' stays ONE line item while
    '2 steel doors, 30 m3 concrete foundation' still splits into two."""
    from app.modules.ai_estimator.extractors import parse_text_scope

    # Spec-continuation comma: the 24cm is the wall thickness, one line item.
    one = [e["description"] for e in parse_text_scope("Brick wall, 24cm")]
    assert one == ["Brick wall, 24cm"]

    # Real list separator: the dimension introduces a new descriptive item.
    two = [e["description"] for e in parse_text_scope("2 steel doors, 30 m3 concrete foundation")]
    assert two == ["2 steel doors", "30 m3 concrete foundation"]

    # Mixed across one and two on separate lines.
    mixed = [e["description"] for e in parse_text_scope("Brick wall, 24cm\n30 m3 concrete foundation")]
    assert mixed == ["Brick wall, 24cm", "30 m3 concrete foundation"]

    # A chained dimension ("200 x 50 mm") and a thousands-separated dimension
    # ("1,200 mm") are both single spec continuations, never split.
    assert [e["description"] for e in parse_text_scope("Slab, 200 x 50 mm")] == ["Slab, 200 x 50 mm"]
    assert [e["description"] for e in parse_text_scope("Concrete wall, 1,200 mm")] == ["Concrete wall, 1,200 mm"]


def test_quantities_from_row_maps_unit_to_canonical_key():
    f = AiEstimatorService._quantities_from_row
    assert f("m3", 9.0) == {"volume_m3": 9.0}
    assert f("m2", 37.5) == {"area_m2": 37.5}
    assert f("m", 5.0) == {"length_m": 5.0}
    assert f("kg", 100.0) == {"mass_kg": 100.0}
    # Unknown unit -> count.
    assert f("lump", 2.0) == {"count": 2.0}
    # Zero / negative / junk -> no quantity (honest, never a fabricated number).
    assert f("m3", 0) == {}
    assert f("m3", -3) == {}
    assert f("m3", "abc") == {}


# ── WorkGroup source standardisation (design 3.1 / 4.1) ──────────────────────


@pytest.mark.parametrize(
    ("envelope_source", "expected"),
    [
        ("bim", "cad"),
        ("dwg", "cad"),
        ("pdf", "file"),
        ("boq", "file"),
        ("text", "file"),
        ("photo", "photo"),
        ("image", "photo"),
        # A measured group never carries dialogue; unknown / blank -> file.
        ("dialogue", "file"),
        ("", "file"),
        (None, "file"),
    ],
)
def test_workgroup_source_maps_envelope_to_standard_source(envelope_source, expected):
    """Every measured envelope source maps to one of cad / file / photo."""
    assert svc._workgroup_source(envelope_source) == expected


def test_group_envelope_carries_project_currency_hard_filter():
    """The matcher envelope must carry the project currency so a USD project
    never gets EUR rates (the never-blend currency hard filter)."""

    class _Run:
        currency = "usd"
        region = "US_BOSTON"
        construction_stage = "06_Superstructure"

    env = AiEstimatorService._group_envelope(
        [{"description": "Concrete wall", "category": "walls", "exact_code": "C-1"}],
        "Concrete wall",
        "m3",
        _Run(),
    )
    assert env["project_currency"] == "USD"  # upper-cased
    assert env["project_region"] == "US_BOSTON"
    assert env["unit_hint"] == "m3"
    # Single envelope -> the exact_code short-circuit is preserved.
    assert env["exact_code"] == "C-1"


def test_group_envelope_drops_exact_code_for_multi_element_group():
    """A multi-element group must NOT inherit one element's exact_code (that
    would short-circuit retrieval to a single row for the whole group)."""

    class _Run:
        currency = "EUR"
        region = ""
        construction_stage = None

    env = AiEstimatorService._group_envelope(
        [{"description": "Wall A", "exact_code": "C-1"}, {"description": "Wall B", "exact_code": "C-2"}],
        "Walls",
        "m3",
        _Run(),
    )
    assert env["exact_code"] is None


def test_sum_quantities_resums_honestly_from_envelopes():
    envelopes = {
        "a": {"quantities": {"volume_m3": 6.0}},
        "b": {"quantities": {"volume_m3": 4.0}},
        "c": {"quantities": {"area_m2": 20.0}},
    }
    # Summing a + b sums only the shared dimension.
    assert AiEstimatorService._sum_quantities(["a", "b"], envelopes) == {"volume_m3": 10.0}
    # A missing id contributes nothing (no fabricated quantity).
    assert AiEstimatorService._sum_quantities(["a", "missing"], envelopes) == {"volume_m3": 6.0}
    # Mixed dimensions are kept separate.
    assert AiEstimatorService._sum_quantities(["a", "c"], envelopes) == {"volume_m3": 6.0, "area_m2": 20.0}


def test_group_by_values_reads_unit_alias_and_properties():
    f = AiEstimatorService._group_by_values
    env = {"category": "walls", "unit_hint": "m3", "properties": {"material": "concrete"}}
    vals = f(env, ["category", "unit", "material"])
    assert vals["category"] == "walls"
    assert vals["unit"] == "m3"  # 'unit' resolves from unit_hint
    assert vals["material"] == "concrete"  # nested property lookup


def test_preview_resources_scale_by_factor_times_parent_qty():
    service = AiEstimatorService.__new__(AiEstimatorService)
    rows = service._preview_resources(
        [
            {"name": "Concrete", "factor": 1.0, "unit": "m3", "unit_rate": "120.00", "type": "material"},
            {"name": "Labour", "factor": 0.8, "unit": "h", "unit_rate": "55.00", "type": "labor"},
            "junk-not-a-dict",
        ],
        parent_qty=10.0,
    )
    assert len(rows) == 2
    assert rows[0].quantity == pytest.approx(10.0)  # 1.0 x 10
    assert rows[1].quantity == pytest.approx(8.0)  # 0.8 x 10
    assert rows[0].unit_rate == Decimal("120.00")


def test_section_path_uses_trade_bucket():
    class _Grp:
        trade = "structure"

    assert AiEstimatorService._section_path(_Grp()) == ["structure"]

    class _GrpNoTrade:
        trade = None

    assert AiEstimatorService._section_path(_GrpNoTrade()) == ["other"]


def test_source_digest_is_compact_and_fenceable():
    service = AiEstimatorService.__new__(AiEstimatorService)
    envelopes = [
        {"description": "Concrete wall", "category": "walls", "unit_hint": "m3"},
        {"description": "Floor slab", "category": "floors", "unit_hint": "m2"},
    ]
    digest = service._source_digest(envelopes)
    assert "element_count=2" in digest
    assert "Concrete wall" in digest
    assert "[walls|m3]" in digest


def test_stage_order_constant_matches_four_pipeline_stages():
    assert svc._STAGE_ORDER == ("source", "grouping", "matching", "assembly")
    assert set(svc._STAGE_TITLES) == set(svc._STAGE_ORDER)


# ── Meta endpoint payload (UI-facing constants, single source of truth) ───────


def test_meta_payload_sources_every_value_from_one_definition():
    """The /meta payload mirrors the API contract and reuses the single existing
    definition for each value (thresholds, stage enum, group cap) - no
    duplicated magic numbers."""
    from app.modules.ai_estimator import benchmarks, schemas

    meta = schemas.MetaResponse(
        score_thresholds=schemas.ScoreThresholds(
            high=svc.CONFIDENCE_HIGH_THRESHOLD,
            low=svc.CONFIDENCE_MEDIUM_THRESHOLD,
        ),
        construction_stages=list(schemas.CONSTRUCTION_STAGES),
        match_group_cap=schemas.DEFAULT_MATCH_GROUP_CAP,
        rate_sanity_band_factor=benchmarks.DEFAULT_BAND_FACTOR,
    )
    # Thresholds come straight off the service constants (the contract: ~0.78 / ~0.62).
    assert meta.score_thresholds.high == pytest.approx(0.78)
    assert meta.score_thresholds.low == pytest.approx(0.62)
    assert meta.score_thresholds.high == svc.CONFIDENCE_HIGH_THRESHOLD
    assert meta.score_thresholds.low == svc.CONFIDENCE_MEDIUM_THRESHOLD
    # Construction stages are exactly the closed ConstructionStage enum values.
    from typing import get_args

    assert meta.construction_stages == list(get_args(schemas.ConstructionStage))
    assert "06_Superstructure" in meta.construction_stages
    assert len(meta.construction_stages) == 12
    # The group cap is the one DEFAULT_MATCH_GROUP_CAP definition (the request
    # schema default reads the same constant).
    assert meta.match_group_cap == 25
    assert meta.match_group_cap == schemas.DEFAULT_MATCH_GROUP_CAP
    assert schemas.RunMatchRequest().max_groups == schemas.DEFAULT_MATCH_GROUP_CAP


def test_stage_confirm_rejects_unknown_construction_stage():
    """The free-form ``edits`` dict validates ``construction_stage`` against the
    closed taxonomy: null/absent/valid pass, an unknown value raises (422)."""
    import pydantic

    from app.modules.ai_estimator import schemas

    # Absent -> fine.
    assert schemas.StageConfirmRequest(stage="source").edits == {}
    # Explicit null -> fine.
    assert schemas.StageConfirmRequest(stage="source", edits={"construction_stage": None}).edits == {
        "construction_stage": None
    }
    # A valid enum value -> fine.
    ok = schemas.StageConfirmRequest(stage="source", edits={"construction_stage": "06_Superstructure"})
    assert ok.edits["construction_stage"] == "06_Superstructure"
    # An unknown value -> validation error (surfaces as 422 at the API).
    with pytest.raises(pydantic.ValidationError):
        schemas.StageConfirmRequest(stage="source", edits={"construction_stage": "nonsense"})


def test_run_create_rejects_unknown_construction_stage():
    """``RunCreate.construction_stage`` is the closed Literal, so an unknown
    value is rejected at parse time (the create-run 422 path)."""
    import uuid

    import pydantic

    from app.modules.ai_estimator import schemas

    # Valid enum value parses.
    ok = schemas.RunCreate(project_id=uuid.uuid4(), construction_stage="09_MEP")
    assert ok.construction_stage == "09_MEP"
    # Unknown value rejected.
    with pytest.raises(pydantic.ValidationError):
        schemas.RunCreate(project_id=uuid.uuid4(), construction_stage="nonsense")


# ── Multi-pass mapping pipeline (semantic -> unit/scale -> rate sanity) ───────
#
# These pin the two NEW deterministic passes (pass 1 needs the live ranker, so
# it is exercised end-to-end in the integration suite). A fake candidate mirrors
# the load-bearing surface of ``MatchCandidate``: a reassignable ``score`` and
# ``confidence_band`` (both declared fields on the real model) plus ``unit`` /
# ``unit_rate`` for the per-base-unit rate. The passes only ever read/reassign
# those declared fields - never an arbitrary attribute - so this fake is faithful.


class _FakeCandidate:
    """Stand-in for MatchCandidate with the fields the passes touch."""

    def __init__(self, code, unit, unit_rate, score, confidence_band="high"):
        self.id = code
        self.code = code
        self.description = code
        self.unit = unit
        self.unit_rate = unit_rate
        self.currency = "EUR"
        self.score = score
        self.confidence_band = confidence_band
        self.classification = {}


def _grp(trade="finishes", chosen_unit="m2"):
    """A minimal group-like object carrying only what the passes read."""

    class _G:
        pass

    g = _G()
    g.trade = trade
    g.chosen_unit = chosen_unit
    g.group_key = f"{trade}|{chosen_unit}"
    return g


def test_reconcile_units_demotes_dimension_mismatch_to_below_correct():
    """A volume (m3) rate for an area (m2) group is DEMOTED, not dropped: the
    dimensionally-correct candidate rises to top-1 while the m3 row survives."""
    service = AiEstimatorService.__new__(AiEstimatorService)
    # The m3 candidate has the HIGHER raw score; after demotion the m2 one wins.
    m3 = _FakeCandidate("VOL", "m3", "120.00", score=0.90)
    m2 = _FakeCandidate("AREA", "m2", "45.00", score=0.70)
    candidates = [m3, m2]
    passes: list[dict] = []

    service._reconcile_units(_grp(trade="finishes", chosen_unit="m2"), candidates, passes)

    # The dimensionally-correct m2 candidate is now top-1; the m3 one survives
    # (never dropped) but sank below it.
    assert candidates[0].code == "AREA"
    assert candidates[1].code == "VOL"
    assert len(candidates) == 2  # nothing dropped
    pass_entry = passes[0]
    assert pass_entry["pass"] == "unit_scale"
    assert pass_entry["dropped"] == 1
    assert pass_entry["kept"] == 2


def test_reconcile_units_keeps_compatible_and_unknown_dimensions():
    """Same-dimension candidates and unmapped/lump-sum units are never demoted
    (we never guess a dimension we cannot read)."""
    service = AiEstimatorService.__new__(AiEstimatorService)
    a = _FakeCandidate("A", "m2", "40.00", score=0.80)
    b = _FakeCandidate("B", "100 m2", "4000.00", score=0.75)  # multiplier, still area
    c = _FakeCandidate("C", "lsum", "9000.00", score=0.60)  # unknown dim -> never demoted
    candidates = [a, b, c]
    passes: list[dict] = []

    service._reconcile_units(_grp(trade="finishes", chosen_unit="m2"), candidates, passes)

    assert passes[0]["dropped"] == 0
    # Order preserved (all scores unchanged, stable sort).
    assert [x.code for x in candidates] == ["A", "B", "C"]


def test_rate_sanity_flags_outlier_caps_band_and_keeps_real_rate():
    """An injected ~100x outlier is flagged, capped at LOW band, and kept - the
    real DB rate is never dropped and never invented."""
    service = AiEstimatorService.__new__(AiEstimatorService)
    # Cluster around 50; one gross 100x outlier at 6000 (median ~ 50, 8x band).
    normal1 = _FakeCandidate("N1", "m2", "48.00", score=0.85)
    normal2 = _FakeCandidate("N2", "m2", "52.00", score=0.80)
    outlier = _FakeCandidate("OUT", "m2", "6000.00", score=0.90, confidence_band="high")
    candidates = [normal1, normal2, outlier]
    passes: list[dict] = []

    flagged = service._rate_sanity(_grp(trade="finishes", chosen_unit="m2"), candidates, passes)

    # Index 2 (the 6000 outlier) is flagged; the two normal rows are not.
    assert flagged == {2}
    # The outlier is capped at LOW band but still present (never dropped).
    assert outlier.confidence_band == "low"
    assert len(candidates) == 3
    pe = passes[0]
    assert pe["pass"] == "rate_sanity"
    assert pe["benchmark"]["outliers"] == 1
    assert pe["benchmark"]["trade"] == "finishes"
    assert pe["benchmark"]["unit"] == "m2"
    # The band bounds are real (median-relative), not None, when there is a median.
    assert pe["benchmark"]["band_low"] is not None
    assert pe["benchmark"]["band_high"] is not None


def test_rate_sanity_single_candidate_is_never_an_outlier():
    """A lone candidate is its own median, so it can never be flagged."""
    service = AiEstimatorService.__new__(AiEstimatorService)
    only = _FakeCandidate("ONLY", "m2", "999999.00", score=0.80)
    passes: list[dict] = []
    flagged = service._rate_sanity(_grp(chosen_unit="m2"), [only], passes)
    assert flagged == set()
    assert passes[0]["benchmark"]["outliers"] == 0


def test_first_non_outlier_skips_flagged_then_falls_back_to_zero():
    service = AiEstimatorService
    cands = [object(), object(), object()]
    # Index 0 flagged -> pick the first clean one (1).
    assert service._first_non_outlier(cands, {0}) == 1
    # Nothing flagged -> top-1.
    assert service._first_non_outlier(cands, set()) == 0
    # Every candidate flagged -> fall back to 0 (a real, if suspect, rate).
    assert service._first_non_outlier(cands, {0, 1, 2}) == 0
    # Empty list -> 0.
    assert service._first_non_outlier([], set()) == 0


def test_candidate_out_carries_rate_outlier_flag():
    """The serialised candidate exposes the pass-3 rate_outlier marker."""
    cand = _FakeCandidate("X", "m2", "45.00", score=0.83)
    clean = AiEstimatorService._candidate_out(cand)
    assert clean["rate_outlier"] is False
    flagged = AiEstimatorService._candidate_out(cand, rate_outlier=True)
    assert flagged["rate_outlier"] is True
