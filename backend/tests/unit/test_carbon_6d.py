# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the 6D carbon BIM-enrichment pure helpers.

All DB-free: only the pure helpers in ``carbon.service`` and the coverage
``ValidationRule`` are exercised. No AsyncSession, no fixtures, no database.

Money/quantities are Decimal end to end - assertions use Decimal equality so a
float regression in unit normalisation would fail here first.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.carbon.service import (
    UnitMismatchError,
    _best_factor_for_element,
    _carbon_from_quantity,
    _element_density,
    extract_element_material,
    material_match_score,
    select_quantity_for_unit,
)
from app.modules.carbon.validators import Carbon6DCoverageRule, _coverage_counts

# ── _carbon_from_quantity (delegates to the BOQ-assign conversion) ─────────


def test_carbon_identity_kg() -> None:
    result = _carbon_from_quantity(Decimal("10"), "kg", Decimal("2.5"), "kg")
    assert result == Decimal("25")
    assert isinstance(result, Decimal)


def test_carbon_volume_with_density() -> None:
    # 2 m3 concrete x 2400 kg/m3 = 4800 kg x 0.13 kgCO2e/kg = 624 kgCO2e
    result = _carbon_from_quantity(
        Decimal("2"),
        "m3",
        Decimal("0.13"),
        "kg",
        density=Decimal("2400"),
    )
    assert result == Decimal("624.00")


def test_carbon_area_m2() -> None:
    result = _carbon_from_quantity(Decimal("5"), "m2", Decimal("30"), "m2")
    assert result == Decimal("150")


def test_carbon_tonne_to_kg() -> None:
    # 1 t -> 1000 kg x 2 kgCO2e/kg = 2000 kgCO2e
    result = _carbon_from_quantity(Decimal("1"), "t", Decimal("2"), "kg")
    assert result == Decimal("2000")


def test_carbon_small_factor_no_float_drift() -> None:
    result = _carbon_from_quantity(Decimal("1000"), "kg", Decimal("0.00012"), "kg")
    assert result == Decimal("0.12000")


def test_carbon_volume_to_mass_needs_density() -> None:
    with pytest.raises(UnitMismatchError):
        _carbon_from_quantity(Decimal("3"), "m3", Decimal("0.13"), "kg")


# ── select_quantity_for_unit ───────────────────────────────────────────────


def test_select_mass_unit_uses_volume() -> None:
    picked = select_quantity_for_unit({"volume_m3": "9", "area_m2": "37.5"}, "kg")
    assert picked == (Decimal("9"), "m3")


def test_select_volume_prefers_net_volume() -> None:
    picked = select_quantity_for_unit({"net_volume": "8", "volume_m3": "9"}, "m3")
    assert picked == (Decimal("8"), "m3")


def test_select_area_unit() -> None:
    assert select_quantity_for_unit({"area_m2": "37.5"}, "m2") == (Decimal("37.5"), "m2")


def test_select_length_unit() -> None:
    assert select_quantity_for_unit({"length_m": "12.5"}, "m") == (Decimal("12.5"), "m")


def test_select_pcs_defaults_to_one() -> None:
    assert select_quantity_for_unit({}, "pcs") == (Decimal("1"), "pcs")
    assert select_quantity_for_unit({"count": "4"}, "pcs") == (Decimal("4"), "pcs")


def test_select_skips_zero_and_negative() -> None:
    picked = select_quantity_for_unit({"area_m2": "0", "area": "5"}, "m2")
    assert picked == (Decimal("5"), "m2")


def test_select_none_when_dimension_missing() -> None:
    assert select_quantity_for_unit({"length_m": "12.5"}, "m2") is None
    assert select_quantity_for_unit({}, "kg") is None
    assert select_quantity_for_unit(None, "m2") is None


# ── extract_element_material / _element_density ────────────────────────────


def test_extract_material_canonical_key() -> None:
    assert extract_element_material({"material": "Concrete C30/37"}) == "Concrete C30/37"


def test_extract_material_capitalised_key() -> None:
    assert extract_element_material({"Material": "Steel"}) == "Steel"


def test_extract_material_layered_dict() -> None:
    assert extract_element_material({"material": {"name": "Brick"}}) == "Brick"


def test_extract_material_absent() -> None:
    assert extract_element_material({}) == ""
    assert extract_element_material(None) == ""


def test_element_density() -> None:
    assert _element_density({"density_kg_per_m3": "2400"}) == Decimal("2400")
    assert _element_density({"density": "7850"}) == Decimal("7850")
    assert _element_density({}) is None
    assert _element_density({"density": "0"}) is None


# ── material_match_score ────────────────────────────────────────────────────


def test_match_score_exact() -> None:
    assert material_match_score("concrete", "wall", "concrete") == 1.0


def test_match_score_containment() -> None:
    assert material_match_score("reinforced concrete", "wall", "concrete") == 0.85


def test_match_score_no_overlap() -> None:
    assert material_match_score("timber", "wall", "concrete") == 0.0


# ── _best_factor_for_element ────────────────────────────────────────────────


def _cand(material_class: str, region: str = "") -> dict[str, object]:
    return {
        "material_class": material_class,
        "region": region,
        "declared_unit": "kg",
        "factor_value": Decimal("0.13"),
        "factor_id": None,
        "epd_id": "epd-x",
    }


def test_best_factor_exact_no_region_is_high() -> None:
    match = _best_factor_for_element("concrete", "wall", "", [_cand("concrete", "DE")])
    assert match is not None
    candidate, confidence = match
    assert candidate["material_class"] == "concrete"
    assert confidence == "high"


def test_best_factor_prefers_region_match() -> None:
    candidates = [_cand("concrete", "DE"), _cand("concrete", "GB")]
    match = _best_factor_for_element("concrete", "wall", "GB", candidates)
    assert match is not None
    candidate, confidence = match
    assert candidate["region"] == "GB"
    assert confidence == "high"


def test_best_factor_region_mismatch_downgrades() -> None:
    match = _best_factor_for_element("concrete", "wall", "GB", [_cand("concrete", "DE")])
    assert match is not None
    _candidate, confidence = match
    assert confidence == "medium"


def test_best_factor_partial_is_medium() -> None:
    match = _best_factor_for_element("reinforced concrete", "wall", "", [_cand("concrete")])
    assert match is not None
    _candidate, confidence = match
    assert confidence == "medium"


def test_best_factor_token_only_is_low() -> None:
    # 2 of 3 tokens overlap (no substring containment) -> ~0.4 score -> low.
    match = _best_factor_for_element("steel beam frame", "wall", "", [_cand("steel beam plate")])
    assert match is not None
    _candidate, confidence = match
    assert confidence == "low"


def test_best_factor_no_match() -> None:
    assert _best_factor_for_element("timber", "wall", "", [_cand("concrete")]) is None
    assert _best_factor_for_element("concrete", "wall", "", []) is None


# ── _coverage_counts + Carbon6DCoverageRule ────────────────────────────────


def test_coverage_counts_explicit() -> None:
    assert _coverage_counts({"bim_element_count": 10, "linked_carbon_element_count": 3}) == (10, 3)


def test_coverage_counts_from_lists_distinct_elements() -> None:
    data = {
        "bim_elements": [1, 2, 3],
        "embodied_entries": [
            {"element_id": "a"},
            {"element_id": "a"},
            {"element_id": "b"},
            {"element_id": None},
        ],
    }
    assert _coverage_counts(data) == (3, 2)


def test_coverage_counts_not_applicable() -> None:
    assert _coverage_counts(["not", "a", "dict"]) is None
    assert _coverage_counts({"embodied_entries": []}) is None


async def _run_rule(data: object) -> list:
    rule = Carbon6DCoverageRule()
    return await rule.validate(ValidationContext(data=data))


async def test_rule_zero_coverage_warns() -> None:
    results = await _run_rule({"bim_element_count": 10, "linked_carbon_element_count": 0})
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert results[0].passed is False


async def test_rule_low_coverage_warns() -> None:
    results = await _run_rule({"bim_element_count": 10, "linked_carbon_element_count": 4})
    assert results[0].severity == Severity.WARNING
    assert results[0].passed is False


async def test_rule_partial_coverage_info() -> None:
    results = await _run_rule({"bim_element_count": 10, "linked_carbon_element_count": 7})
    assert results[0].severity == Severity.INFO
    assert results[0].passed is False


async def test_rule_good_coverage_passes() -> None:
    results = await _run_rule({"bim_element_count": 10, "linked_carbon_element_count": 9})
    assert results[0].severity == Severity.INFO
    assert results[0].passed is True


async def test_rule_no_bim_elements_passes() -> None:
    results = await _run_rule({"bim_element_count": 0, "linked_carbon_element_count": 0})
    assert results[0].passed is True


async def test_rule_not_applicable_returns_empty() -> None:
    assert await _run_rule("not-a-dict") == []
