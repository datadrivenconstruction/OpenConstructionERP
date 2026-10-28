"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Per-element BIM rules added to deepen the model-review check set.

Covers, for each new rule, a happy path, the failing case it catches, and a
sparse / missing-data case proving it never raises. Mirrors the element shape
(``SimpleNamespace``) used by ``test_bim_element_rule_hardening``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.validation.rules.bim_element_rule import (
    BIMElementRule,
    _has_classification_code,
    _has_host_reference,
    _match_category,
)
from app.modules.validation.rules.bim_universal import (
    ASSET_HAS_MARK_TAG,
    ASSET_HAS_TYPE_IDENTIFIER,
    BIM_UNIVERSAL_RULES,
    CATEGORY_REQUIRED_PROPERTY,
    CIRCULATION_HAS_DIMENSIONS,
    DOOR_MIN_CLEAR_WIDTH,
    ELEMENT_HAS_CLASSIFICATION,
    ELEMENT_HAS_PHASE,
    ELEMENT_HAS_TYPE_NAME,
    HOSTED_HAS_HOST,
    MEP_HAS_SIZE,
    MIN_DOOR_CLEAR_WIDTH_M,
    QUANTITY_NON_NEGATIVE,
    SPACE_HAS_IDENTITY,
)


def _elem(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": "e1",
        "name": "El",
        "element_type": "wall",
        "properties": {},
        "quantities": {},
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ── Registry wiring --------------------------------------------------------


def test_new_rules_registered_once() -> None:
    ids = [r.rule_id for r in BIM_UNIVERSAL_RULES]
    assert len(ids) == len(set(ids))  # no duplicate ids
    for rid in (
        "bim.category.required_property",
        "bim.element.has_classification",
        "bim.asset.has_type_identifier",
        "bim.asset.has_mark_tag",
        "bim.space.identity",
        "bim.hosted.has_host",
        "bim.door.min_clear_width",
    ):
        assert rid in ids


# ── 1. Category-required-property -----------------------------------------


class TestCategoryRequiredProperty:
    def test_wall_with_material_passes(self) -> None:
        wall = _elem(element_type="wall", properties={"material": "concrete"})
        assert CATEGORY_REQUIRED_PROPERTY.evaluate(wall) == []

    def test_wall_without_material_fails(self) -> None:
        wall = _elem(element_type="IfcWallStandardCase", properties={"fire_rating": "F90"})
        results = CATEGORY_REQUIRED_PROPERTY.evaluate(wall)
        assert len(results) == 1
        assert results[0].severity == "warning"

    def test_space_requires_function_not_material(self) -> None:
        ok = _elem(element_type="space", properties={"occupancy": "office"})
        missing = _elem(element_type="space", properties={"material": "air"})
        assert CATEGORY_REQUIRED_PROPERTY.evaluate(ok) == []
        assert len(CATEGORY_REQUIRED_PROPERTY.evaluate(missing)) == 1

    def test_unmapped_category_out_of_scope(self) -> None:
        # A furniture element is not in the map -> the rule does not apply.
        furniture = _elem(element_type="furniture", properties={})
        assert CATEGORY_REQUIRED_PROPERTY.matches(furniture) is False
        assert CATEGORY_REQUIRED_PROPERTY.matches(_elem(element_type="wall")) is True

    def test_sparse_element_does_not_crash(self) -> None:
        sparse = _elem(element_type=None, properties=None, quantities=None)
        assert CATEGORY_REQUIRED_PROPERTY.matches(sparse) is False
        assert CATEGORY_REQUIRED_PROPERTY.evaluate(sparse) == []

    def test_match_category_prefix(self) -> None:
        mapping = {"wall": ["material"]}
        assert _match_category(mapping, _elem(element_type="IfcWall")) == ("wall", ["material"])
        assert _match_category(mapping, _elem(element_type="door")) is None


# ── 2. Classification-code-present ----------------------------------------


class TestHasClassification:
    def test_classification_in_properties_passes(self) -> None:
        el = _elem(properties={"classification": {"din276": "330"}})
        assert ELEMENT_HAS_CLASSIFICATION.evaluate(el) == []

    def test_classification_direct_attribute_passes(self) -> None:
        el = _elem(classification={"uniclass": "Ss_25_10"})
        assert ELEMENT_HAS_CLASSIFICATION.evaluate(el) == []

    def test_missing_classification_fails(self) -> None:
        results = ELEMENT_HAS_CLASSIFICATION.evaluate(_elem(properties={"foo": "bar"}))
        assert len(results) == 1
        assert results[0].severity == "warning"

    def test_empty_classification_dict_fails(self) -> None:
        el = _elem(properties={"classification": {"din276": ""}})
        assert len(ELEMENT_HAS_CLASSIFICATION.evaluate(el)) == 1

    def test_sparse_element_does_not_crash(self) -> None:
        assert len(ELEMENT_HAS_CLASSIFICATION.evaluate(_elem(properties=None))) == 1

    def test_reader_helper(self) -> None:
        assert _has_classification_code(_elem(), {"classification": {"nrm": "2.6"}}) is True
        assert _has_classification_code(_elem(), {}) is False


# ── 3. Handover / asset completeness --------------------------------------


class TestAssetHandover:
    def test_type_identifier_present_passes(self) -> None:
        door = _elem(element_type="door", properties={"type_name": "D-90"})
        assert ASSET_HAS_TYPE_IDENTIFIER.evaluate(door) == []

    def test_type_identifier_missing_fails_info(self) -> None:
        door = _elem(element_type="door", properties={})
        results = ASSET_HAS_TYPE_IDENTIFIER.evaluate(door)
        assert len(results) == 1
        assert results[0].severity == "info"

    def test_mark_tag_present_passes(self) -> None:
        pump = _elem(element_type="MechanicalEquipment", properties={"mark": "P-01"})
        assert ASSET_HAS_MARK_TAG.evaluate(pump) == []

    def test_mark_tag_missing_fails_info(self) -> None:
        pump = _elem(element_type="mechanicalequipment", properties={})
        results = ASSET_HAS_MARK_TAG.evaluate(pump)
        assert len(results) == 1
        assert results[0].severity == "info"

    def test_non_asset_out_of_scope(self) -> None:
        wall = _elem(element_type="wall")
        assert ASSET_HAS_TYPE_IDENTIFIER.matches(wall) is False
        assert ASSET_HAS_MARK_TAG.matches(wall) is False

    def test_sparse_asset_does_not_crash(self) -> None:
        door = _elem(element_type="door", properties=None)
        assert len(ASSET_HAS_TYPE_IDENTIFIER.evaluate(door)) == 1
        assert len(ASSET_HAS_MARK_TAG.evaluate(door)) == 1


# ── 4. Space sanity -------------------------------------------------------


class TestSpaceIdentity:
    def test_complete_space_passes(self) -> None:
        space = _elem(
            element_type="space",
            name="Office 101",
            properties={"number": "101"},
            quantities={"area_m2": 15.0},
        )
        assert SPACE_HAS_IDENTITY.evaluate(space) == []

    def test_zero_area_fails(self) -> None:
        space = _elem(
            element_type="ifcspace",
            name="Office 101",
            properties={"number": "101"},
            quantities={"area_m2": 0},
        )
        assert len(SPACE_HAS_IDENTITY.evaluate(space)) == 1

    def test_missing_number_fails(self) -> None:
        space = _elem(
            element_type="room",
            name="Office",
            properties={},
            quantities={"area_m2": 12.0},
        )
        assert len(SPACE_HAS_IDENTITY.evaluate(space)) == 1

    def test_sparse_space_flags_all_but_does_not_crash(self) -> None:
        space = _elem(element_type="space", name=None, properties=None, quantities=None)
        results = SPACE_HAS_IDENTITY.evaluate(space)
        # name + number + positive-area all fail, but nothing raises.
        assert len(results) == 3

    def test_non_space_out_of_scope(self) -> None:
        assert SPACE_HAS_IDENTITY.matches(_elem(element_type="wall")) is False


# ── 5. Hosted / connected -------------------------------------------------


class TestHostedHasHost:
    def test_flat_host_key_passes(self) -> None:
        door = _elem(element_type="door", properties={"host_id": "wall-7"})
        assert HOSTED_HAS_HOST.evaluate(door) == []

    def test_relations_dict_passes(self) -> None:
        window = _elem(element_type="window", properties={"relations": {"host": "wall-3"}})
        assert HOSTED_HAS_HOST.evaluate(window) == []

    def test_missing_host_fails(self) -> None:
        door = _elem(element_type="door", properties={"width": 0.9})
        results = HOSTED_HAS_HOST.evaluate(door)
        assert len(results) == 1
        assert results[0].severity == "warning"

    def test_non_hosted_out_of_scope(self) -> None:
        assert HOSTED_HAS_HOST.matches(_elem(element_type="wall")) is False

    def test_sparse_does_not_crash(self) -> None:
        assert len(HOSTED_HAS_HOST.evaluate(_elem(element_type="door", properties=None))) == 1

    def test_reader_helper(self) -> None:
        assert _has_host_reference(_elem(), {"parent_id": "x"}) is True
        assert _has_host_reference(_elem(relations={"host": "x"}), {}) is True
        assert _has_host_reference(_elem(), {"foo": "bar"}) is False


# ── 6. Door clear width ---------------------------------------------------


class TestDoorMinClearWidth:
    def test_wide_door_passes(self) -> None:
        door = _elem(element_type="door", quantities={"width_m": 0.9})
        assert DOOR_MIN_CLEAR_WIDTH.evaluate(door) == []

    def test_narrow_door_fails(self) -> None:
        door = _elem(element_type="door", quantities={"width_m": 0.7})
        results = DOOR_MIN_CLEAR_WIDTH.evaluate(door)
        assert len(results) == 1
        assert results[0].severity == "warning"
        assert results[0].details["min"] == MIN_DOOR_CLEAR_WIDTH_M

    def test_missing_width_not_flagged(self) -> None:
        # A missing width is owned by the door-dimensions rule, not this one.
        door = _elem(element_type="door", quantities={})
        assert DOOR_MIN_CLEAR_WIDTH.evaluate(door) == []

    def test_locale_string_width(self) -> None:
        # '0,70' coerces to 0.70 -> below the minimum -> flagged.
        door = _elem(element_type="door", quantities={"width_m": "0,70"})
        assert len(DOOR_MIN_CLEAR_WIDTH.evaluate(door)) == 1

    def test_width_from_properties_fallback(self) -> None:
        door = _elem(element_type="door", quantities={}, properties={"clear_width": 0.6})
        assert len(DOOR_MIN_CLEAR_WIDTH.evaluate(door)) == 1


# ── min_when_present DSL primitive ----------------------------------------


class TestMinWhenPresentPrimitive:
    @pytest.mark.parametrize(
        ("value", "expect_fail"),
        [(0.5, True), (1.0, False), (None, False), ("abc", False)],
    )
    def test_only_present_below_min_fails(self, value: Any, expect_fail: bool) -> None:
        rule = BIMElementRule(
            rule_id="r",
            name="R",
            severity="warning",
            min_when_present={"paths": ["w"], "min": 0.85, "label": "Width"},
        )
        quants = {} if value is None else {"w": value}
        results = rule.evaluate(_elem(quantities=quants))
        assert bool(results) is expect_fail


# ── Model-review deepening rules registered -------------------------------


def test_deepening_element_rules_registered() -> None:
    ids = [r.rule_id for r in BIM_UNIVERSAL_RULES]
    assert len(ids) == len(set(ids))  # no duplicate ids
    for rid in (
        "bim.quantity.non_negative",
        "bim.mep.has_size",
        "bim.circulation.has_dimensions",
        "bim.element.has_type_name",
        "bim.element.has_phase",
    ):
        assert rid in ids


# ── 7. Non-negative dimensional quantities --------------------------------


class TestQuantityNonNegative:
    def test_positive_quantities_pass(self) -> None:
        el = _elem(quantities={"area_m2": 12.0, "volume_m3": 3.0, "count": 4})
        assert QUANTITY_NON_NEGATIVE.evaluate(el) == []

    def test_no_quantities_pass(self) -> None:
        assert QUANTITY_NON_NEGATIVE.evaluate(_elem(quantities={})) == []

    def test_negative_area_fails_error(self) -> None:
        results = QUANTITY_NON_NEGATIVE.evaluate(_elem(quantities={"area_m2": -5.0}))
        assert len(results) == 1
        assert results[0].severity == "error"
        assert results[0].details == {"quantity": "area_m2", "value": -5.0}

    def test_one_failure_per_offending_key(self) -> None:
        results = QUANTITY_NON_NEGATIVE.evaluate(
            _elem(quantities={"area_m2": -1.0, "length_m": -2.0, "height_m": 3.0}),
        )
        offenders = {r.details["quantity"] for r in results}
        assert offenders == {"area_m2", "length_m"}

    def test_negative_elevation_or_z_not_flagged(self) -> None:
        # Directional values can be negative (basements) - not in the curated set.
        el = _elem(quantities={"elevation": -3.0, "z": -12.5, "offset": -1.0})
        assert QUANTITY_NON_NEGATIVE.evaluate(el) == []

    def test_locale_string_negative_flagged(self) -> None:
        # '-0,24' coerces to -0.24 -> below zero -> flagged.
        assert len(QUANTITY_NON_NEGATIVE.evaluate(_elem(quantities={"thickness_m": "-0,24"}))) == 1

    def test_sparse_does_not_crash(self) -> None:
        assert QUANTITY_NON_NEGATIVE.evaluate(_elem(quantities=None)) == []


# ── 8. MEP / distribution size --------------------------------------------


class TestMepHasSize:
    def test_duct_with_diameter_passes(self) -> None:
        duct = _elem(element_type="duct", properties={"diameter": 200})
        assert MEP_HAS_SIZE.evaluate(duct) == []

    def test_pipe_without_size_fails_warning(self) -> None:
        pipe = _elem(element_type="ifcpipe", properties={"material": "steel"})
        results = MEP_HAS_SIZE.evaluate(pipe)
        assert len(results) == 1
        assert results[0].severity == "warning"

    def test_non_distribution_out_of_scope(self) -> None:
        assert MEP_HAS_SIZE.matches(_elem(element_type="wall")) is False

    def test_sparse_does_not_crash(self) -> None:
        assert len(MEP_HAS_SIZE.evaluate(_elem(element_type="duct", properties=None))) == 1


# ── 9. Circulation (stairs / ramps) dimensions ----------------------------


class TestCirculationHasDimensions:
    def test_stair_with_width_passes(self) -> None:
        stair = _elem(element_type="stair", properties={"width": 1.2})
        assert CIRCULATION_HAS_DIMENSIONS.evaluate(stair) == []

    def test_ramp_without_width_fails_warning(self) -> None:
        ramp = _elem(element_type="ifcramp", properties={"material": "concrete"})
        results = CIRCULATION_HAS_DIMENSIONS.evaluate(ramp)
        assert len(results) == 1
        assert results[0].severity == "warning"

    def test_non_circulation_out_of_scope(self) -> None:
        assert CIRCULATION_HAS_DIMENSIONS.matches(_elem(element_type="wall")) is False

    def test_sparse_does_not_crash(self) -> None:
        assert len(CIRCULATION_HAS_DIMENSIONS.evaluate(_elem(element_type="stair", properties=None))) == 1


# ── 10. Physical element type / family name -------------------------------


class TestElementHasTypeName:
    def test_wall_with_type_name_passes(self) -> None:
        wall = _elem(element_type="wall", properties={"type_name": "WA-200"})
        assert ELEMENT_HAS_TYPE_NAME.evaluate(wall) == []

    def test_column_without_type_fails_info(self) -> None:
        col = _elem(element_type="column", properties={"material": "steel"})
        results = ELEMENT_HAS_TYPE_NAME.evaluate(col)
        assert len(results) == 1
        assert results[0].severity == "info"

    def test_non_physical_out_of_scope(self) -> None:
        assert ELEMENT_HAS_TYPE_NAME.matches(_elem(element_type="furniture")) is False

    def test_sparse_does_not_crash(self) -> None:
        assert len(ELEMENT_HAS_TYPE_NAME.evaluate(_elem(element_type="wall", properties=None))) == 1


# ── 11. Element phase / status --------------------------------------------


class TestElementHasPhase:
    def test_phase_present_passes(self) -> None:
        assert ELEMENT_HAS_PHASE.evaluate(_elem(properties={"phase": "New Construction"})) == []

    def test_status_alias_passes(self) -> None:
        assert ELEMENT_HAS_PHASE.evaluate(_elem(properties={"status": "existing"})) == []

    def test_missing_phase_fails_info(self) -> None:
        results = ELEMENT_HAS_PHASE.evaluate(_elem(properties={"foo": "bar"}))
        assert len(results) == 1
        assert results[0].severity == "info"

    def test_sparse_does_not_crash(self) -> None:
        assert len(ELEMENT_HAS_PHASE.evaluate(_elem(properties=None))) == 1
