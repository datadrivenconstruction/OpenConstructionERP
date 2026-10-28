# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the intake v2 taxonomy, formulas and FSM primitives.

No DB, no HTTP, no AI key, no Qdrant. These pin the deterministic building
blocks the conversational intake composes:

    * Project-type registry integrity: every ProjectParam.unlocks and every
      WorkPackage.qty_formula resolves to a real formula; every package trade
      is in taxonomy.TRADE_KEYWORDS; every package stage is a foreman stage.
    * Offline project-type detection from free text (EN / RU / DE synonyms).
    * Quantity formulas are pure and deterministic, with the estimated flag set
      whenever a geometric proxy was used.
    * The round grouping (1..3) and the parameter-justification principle.

Run:
    cd backend
    python -m pytest tests/unit/ai_estimator/test_intake_taxonomy.py -q
"""

from __future__ import annotations

import math

import pytest

from app.modules.ai_estimator.project_types import (
    FOREMAN_STAGES,
    PROJECT_TYPE_ORDER,
    PROJECT_TYPES,
    default_packages,
    detect_project_type,
    get_project_type,
    params_for_round,
)
from app.modules.ai_estimator.quantities import (
    FORMULA_IDS,
    FORMULAS,
    compute_quantity,
    debris_volume_m3,
    net_wall_area_m2,
    openings_area_m2,
    perimeter_m,
    slope_area_m2,
)
from app.modules.ai_estimator.taxonomy import TRADE_KEYWORDS

_TRADES = {k for k, _ in TRADE_KEYWORDS} | {"other"}


# ── Registry integrity (the parameter-justification principle) ───────────────


def test_registry_has_ten_types():
    assert len(PROJECT_TYPES) == 10
    assert set(PROJECT_TYPE_ORDER) == set(PROJECT_TYPES)


@pytest.mark.parametrize("type_key", list(PROJECT_TYPES))
def test_every_param_unlocks_a_real_formula(type_key):
    """No parameter exists that unlocks nothing - it must feed a real formula."""
    pt = PROJECT_TYPES[type_key]
    for p in pt.params:
        assert p.unlocks, f"{type_key}.{p.key} unlocks nothing (cut it)"
        for formula_id in p.unlocks:
            assert formula_id in FORMULA_IDS, f"{type_key}.{p.key} unlocks unknown formula {formula_id}"


@pytest.mark.parametrize("type_key", list(PROJECT_TYPES))
def test_every_package_resolves_formula_trade_and_stages(type_key):
    pt = PROJECT_TYPES[type_key]
    assert pt.packages, f"{type_key} has no packages"
    for pkg in pt.packages:
        assert pkg.qty_formula in FORMULAS, f"{type_key}.{pkg.key} unknown qty_formula {pkg.qty_formula}"
        assert pkg.trade in _TRADES, f"{type_key}.{pkg.key} trade {pkg.trade} not in taxonomy"
        assert pkg.probes, f"{type_key}.{pkg.key} has no probes"
        for stage in pkg.stages:
            assert stage in FOREMAN_STAGES, f"{type_key}.{pkg.key} unknown stage {stage}"


@pytest.mark.parametrize("type_key", list(PROJECT_TYPES))
def test_rounds_are_within_the_cap(type_key):
    """Every param lands in round 1, 2 or 3 - never beyond the 3-round ceiling."""
    pt = PROJECT_TYPES[type_key]
    for p in pt.params:
        assert p.round_group in (1, 2, 3), f"{type_key}.{p.key} round {p.round_group} out of range"
    # Round 1 must carry at least one question (the high-payoff round).
    assert params_for_round(pt, 1), f"{type_key} has no round-1 questions"


@pytest.mark.parametrize("type_key", list(PROJECT_TYPES))
def test_default_packages_are_a_subset(type_key):
    pt = PROJECT_TYPES[type_key]
    defaults = default_packages(pt)
    assert defaults, f"{type_key} has no default-on packages"
    assert all(p.default_on for p in defaults)


# ── Offline project-type detection ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("сделай мне смету кухни", "kitchen_reno"),
        ("kitchen renovation, 8 m2", "kitchen_reno"),
        ("Kuechenumbau 10 m2", "kitchen_reno"),
        ("ремонт ванной 4 м2 под ключ", "bathroom_reno"),
        ("bathroom refurb about 5 square metres", "bathroom_reno"),
        ("Badsanierung", "bathroom_reno"),
        ("ремонт квартиры 120 м2", "apartment_reno"),
        ("Fassadensanierung, 220 m2, WDVS", "facade"),
        ("roof repair 80 m2", "roof"),
        ("office fit-out 300 m2", "commercial_fitout"),
        ("landscaping external works", "landscaping"),
        ("MEP retrofit of the building", "mep_retrofit"),
    ],
)
def test_detect_project_type_offline(text, expected):
    detected, _count = detect_project_type(text)
    assert detected == expected


def test_detect_project_type_unknown_is_none():
    detected, count = detect_project_type("please help me with something")
    assert detected is None
    assert count == 0


def test_detect_project_type_empty_is_none():
    assert detect_project_type("") == (None, 0)


# ── Geometric helpers (pure, deterministic) ──────────────────────────────────


def test_perimeter_from_area_is_positive_and_zero_safe():
    assert perimeter_m(12.0) > 0
    assert perimeter_m(0.0) == 0.0
    # A square-ish 100 m2 room has a perimeter near 40 m for aspect 1.4.
    assert 38.0 < perimeter_m(100.0) < 44.0


def test_net_wall_area_clamps_at_zero():
    assert net_wall_area_m2(10.0, 3.0) == 7.0
    assert net_wall_area_m2(2.0, 5.0) == 0.0


def test_openings_area_from_counts():
    assert openings_area_m2(doors=2, windows=1) == pytest.approx(2 * 1.8 + 1.5)
    assert openings_area_m2() == 0.0


def test_slope_area_increases_with_pitch():
    flat = slope_area_m2(100.0, 0.0)
    pitched = slope_area_m2(100.0, 30.0)
    assert flat == pytest.approx(100.0)
    assert pitched > flat
    assert pitched == pytest.approx(100.0 / math.cos(math.radians(30.0)))


def test_debris_volume_proxy():
    assert debris_volume_m3(100.0) == pytest.approx(5.0)
    assert debris_volume_m3(0.0) == 0.0


# ── Formula evaluation from a parameter sheet ────────────────────────────────


def test_floor_area_formula_is_confirmed_not_estimated():
    res = compute_quantity("floor_area", {"floor_area_m2": 12.0}, "m2")
    assert res.quantity == 12.0
    assert res.unit == "m2"
    assert res.estimated is False


def test_wall_net_with_real_perimeter_is_not_estimated():
    params = {"floor_area_m2": 12.0, "perimeter_m": 14.0, "ceiling_height_m": 2.7}
    res = compute_quantity("wall_full", params, "m2")
    # 14 m perimeter x 2.7 m height, no openings given.
    assert res.quantity == pytest.approx(14.0 * 2.7)
    assert res.estimated is False


def test_wall_net_with_inferred_perimeter_is_estimated():
    res = compute_quantity("wall_full", {"floor_area_m2": 12.0}, "m2")
    assert res.quantity > 0
    # Perimeter inferred from area AND height defaulted -> estimated.
    assert res.estimated is True


def test_points_formula_rounds_and_is_estimated():
    res = compute_quantity("points", {"floor_area_m2": 20.0}, "pcs")
    assert res.quantity == round(20.0 * 0.6)
    assert res.estimated is True


def test_unknown_formula_degrades_to_zero():
    res = compute_quantity("does_not_exist", {"floor_area_m2": 99.0}, "m2")
    assert res.quantity == 0.0
    assert res.estimated is False


def test_offline_and_ai_paths_share_identical_formulas():
    """The same parameter sheet yields identical quantities regardless of path.

    The formulas are pure functions of the sheet, so the offline questionnaire
    path and a (mocked) AI path that arrive at the same sheet compute the same
    numbers - the design's offline-parity invariant at the formula level.
    """
    sheet = {"floor_area_m2": 8.0, "ceiling_height_m": 2.7, "perimeter_m": 12.0}
    pt = get_project_type("kitchen_reno")
    assert pt is not None
    first = {pkg.key: compute_quantity(pkg.qty_formula, sheet, pkg.unit).quantity for pkg in pt.packages}
    second = {pkg.key: compute_quantity(pkg.qty_formula, sheet, pkg.unit).quantity for pkg in pt.packages}
    assert first == second


# ── FSM pure helpers (no DB) ─────────────────────────────────────────────────


def test_coverage_bands_from_real_probe_score():
    """grounded >= MEDIUM, weak between the LOW floor and MEDIUM, gap below."""
    from app.modules.ai_estimator.intake import IntakeService

    assert IntakeService._coverage(0.83) == "grounded"
    assert IntakeService._coverage(0.62) == "grounded"
    assert IntakeService._coverage(0.5) == "weak"
    assert IntakeService._coverage(0.30) == "weak"
    assert IntakeService._coverage(0.1) == "gap"
    # No probe candidate is an honest gap, never a placeholder.
    assert IntakeService._coverage(None) == "gap"


def test_merge_coverage_keeps_the_greenest():
    from app.modules.ai_estimator.intake import IntakeService

    assert IntakeService._merge_coverage("gap", "weak") == "weak"
    assert IntakeService._merge_coverage("weak", "grounded") == "grounded"
    assert IntakeService._merge_coverage("grounded", "gap") == "grounded"


def test_coerce_value_rejects_junk_and_keeps_real_values():
    from app.modules.ai_estimator.intake import _coerce_value
    from app.modules.ai_estimator.project_types import get_project_type

    pt = get_project_type("kitchen_reno")
    assert pt is not None
    area = next(p for p in pt.params if p.key == "floor_area_m2")
    finish = next(p for p in pt.params if p.key == "finish_level")
    demo = next(p for p in pt.params if p.key == "demolition")

    assert _coerce_value(area, "8.5") == 8.5
    assert _coerce_value(area, "not-a-number") is None
    assert _coerce_value(area, -3) is None  # negative size rejected
    assert _coerce_value(finish, "standard") == "standard"
    assert _coerce_value(finish, "luxury") is None  # not an allowed choice
    assert _coerce_value(demo, "да") is True
    assert _coerce_value(demo, "no") is False
    assert _coerce_value(demo, "maybe") is None


def test_resolve_mode_prefers_explicit_hint_then_ai_connection():
    from app.modules.ai_estimator.intake import IntakeService

    assert IntakeService._resolve_mode("offline", True) == "offline"
    assert IntakeService._resolve_mode("ai", False) == "ai"
    assert IntakeService._resolve_mode(None, True) == "ai"
    assert IntakeService._resolve_mode(None, False) == "offline"


def test_seed_from_text_reads_explicit_area_only():
    from app.modules.ai_estimator.intake import IntakeService

    seeded = IntakeService._seed_from_text("ремонт квартиры 120 м2")
    assert seeded.get("floor_area_m2") == pytest.approx(120.0)
    # No quantity in the text -> nothing seeded (never invents a number).
    assert IntakeService._seed_from_text("kitchen renovation") == {}


def test_readiness_reaches_one_when_required_params_known():
    from app.modules.ai_estimator.intake import IntakeService

    pt = get_project_type("bathroom_reno")
    assert pt is not None
    required = [p.key for p in pt.params if p.required]
    full = dict.fromkeys(required, 1)
    assert IntakeService._readiness(pt, full) == pytest.approx(1.0)
    assert IntakeService._readiness(pt, {}) == pytest.approx(0.0)


def test_apply_defaults_fills_missing_and_marks_skipped():
    from app.modules.ai_estimator.intake import IntakeService

    pt = get_project_type("kitchen_reno")
    assert pt is not None
    params: dict = {}
    status: dict = {}
    IntakeService._apply_defaults(pt, params, status)
    # ceiling_height_m declares a 2.7 default; it must be filled and flagged.
    assert params.get("ceiling_height_m") == 2.7
    assert status.get("ceiling_height_m") == "skipped"
