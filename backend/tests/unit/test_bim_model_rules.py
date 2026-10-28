"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Model-level BIM rules - duplicate ids, completeness, units, georeference.

Pure, DB-free tests over ``SimpleNamespace`` elements and hand-built
``BIMModelContext`` objects. Each rule gets a happy path, the failing case it
catches, and a sparse / missing-data case proving it never raises.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.modules.validation.rules.bim_model_rule import (
    BIM_MODEL_RULES,
    DEFAULT_EXPECTED_CATEGORIES,
    BIMModelContext,
    ClassificationCoverageRule,
    DisciplineCoverageRule,
    DuplicateIdentifierRule,
    GeoreferenceSanityRule,
    ModelCompletenessRule,
    SpatialStructureRule,
    UniqueMarksPerCategoryRule,
    UnitConsistencyRule,
    get_model_rules_by_ids,
)


def el(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": "e1",
        "stable_id": "g1",
        "element_type": "wall",
        "name": "El",
        "properties": {},
        "quantities": {},
    }
    base.update(kw)
    return SimpleNamespace(**base)


def ctx(**kw: Any) -> BIMModelContext:
    return BIMModelContext(**kw)


# ── Registry --------------------------------------------------------------


def test_registry_ids_unique_and_filterable() -> None:
    ids = [r.rule_id for r in BIM_MODEL_RULES]
    assert ids == [
        "bim.model.duplicate_identifier",
        "bim.model.expected_categories_present",
        "bim.model.unit_consistency",
        "bim.model.georeference",
        "bim.model.unique_marks_per_category",
        "bim.model.classification_coverage",
        "bim.model.spatial_structure",
        "bim.model.discipline_coverage",
    ]
    assert len(ids) == len(set(ids))  # no duplicate ids
    assert len(get_model_rules_by_ids(None)) == 8
    only = get_model_rules_by_ids(["bim.model.duplicate_identifier"])
    assert len(only) == 1 and only[0].rule_id == "bim.model.duplicate_identifier"


def test_empty_model_skips_every_rule() -> None:
    for rule in BIM_MODEL_RULES:
        assert rule.applies([], ctx()) is False


# ── 7. Duplicate identifier -----------------------------------------------


class TestDuplicateIdentifier:
    rule = DuplicateIdentifierRule()

    def test_unique_ids_pass(self) -> None:
        elements = [el(id="a", stable_id="g1"), el(id="b", stable_id="g2")]
        assert self.rule.evaluate(elements, ctx()) == []

    def test_duplicate_id_flagged_once(self) -> None:
        elements = [el(id="a", stable_id="dup"), el(id="b", stable_id="dup"), el(id="c", stable_id="ok")]
        results = self.rule.evaluate(elements, ctx())
        assert len(results) == 1
        assert results[0].severity == "error"
        assert results[0].element_ref == "dup"
        assert results[0].details["count"] == 2
        assert set(results[0].details["element_ids"]) == {"a", "b"}

    def test_guid_property_fallback(self) -> None:
        elements = [
            el(id="a", stable_id=None, properties={"guid": "G"}),
            el(id="b", stable_id=None, properties={"guid": "G"}),
        ]
        assert len(self.rule.evaluate(elements, ctx())) == 1

    def test_missing_ids_do_not_crash(self) -> None:
        elements = [el(id="a", stable_id=None, properties={}), el(id="b", stable_id="", properties=None)]
        assert self.rule.evaluate(elements, ctx()) == []


# ── 8. Model completeness -------------------------------------------------


class TestModelCompleteness:
    rule = ModelCompletenessRule()

    def _full_model(self) -> list[SimpleNamespace]:
        return [
            el(element_type="IfcWall"),
            el(element_type="Slab"),
            el(element_type="Column"),
            el(element_type="Door"),
            el(element_type="Window"),
            el(element_type="Space"),
        ]

    def test_full_model_passes(self) -> None:
        assert self.rule.evaluate(self._full_model(), ctx()) == []

    def test_missing_categories_flagged(self) -> None:
        results = self.rule.evaluate([el(element_type="wall")], ctx())
        # every expected category except walls is missing
        assert len(results) == len(DEFAULT_EXPECTED_CATEGORIES) - 1
        assert all(r.severity == "warning" for r in results)
        missing = {r.details["missing_category"] for r in results}
        assert "doors" in missing and "spaces" in missing

    def test_beam_covers_columns_or_beams(self) -> None:
        results = self.rule.evaluate(self._full_model()[:2] + [el(element_type="Beam")], ctx())
        labels = {r.details["missing_category"] for r in results}
        assert "columns or beams" not in labels

    def test_sparse_types_do_not_crash(self) -> None:
        results = self.rule.evaluate([el(element_type=None), el(element_type="")], ctx())
        assert len(results) == len(DEFAULT_EXPECTED_CATEGORIES)


# ── 9. Unit consistency ---------------------------------------------------


class TestUnitConsistency:
    rule = UnitConsistencyRule()

    def test_single_declared_system_passes(self) -> None:
        context = ctx(unit_system="metric", had_unit_assignment=True, units_declared=True)
        assert self.rule.applies([el()], context) is True
        assert self.rule.evaluate([el()], context) == []

    def test_explicit_mixed_flagged(self) -> None:
        context = ctx(unit_system="mixed", units_declared=True)
        results = self.rule.evaluate([el()], context)
        assert len(results) == 1
        assert results[0].severity == "warning"

    def test_two_element_systems_flagged(self) -> None:
        context = ctx(unit_system="metric", had_unit_assignment=True, units_declared=True)
        elements = [
            el(properties={"unit_system": "metric"}),
            el(properties={"unit_system": "imperial"}),
        ]
        results = self.rule.evaluate(elements, context)
        assert len(results) == 1
        assert set(results[0].details["declared_systems"]) == {"imperial", "metric"}

    def test_uncertain_declaration_flagged(self) -> None:
        context = ctx(unit_system="metric", had_unit_assignment=False, units_declared=True)
        results = self.rule.evaluate([el()], context)
        assert len(results) == 1
        assert results[0].details["had_assignment"] is False

    def test_no_unit_info_is_skipped(self) -> None:
        context = ctx(units_declared=False)
        assert self.rule.applies([el()], context) is False


# ── 10. Georeference sanity -----------------------------------------------


class TestGeoreferenceSanity:
    rule = GeoreferenceSanityRule()

    def test_plausible_placement_passes(self) -> None:
        context = ctx(georeference={"base_point": [1200.0, 3400.0, 0.0], "crs": "EPSG:25832"})
        assert self.rule.evaluate([el()], context) == []

    def test_crs_only_passes(self) -> None:
        context = ctx(georeference={"coordinate_system": "EPSG:2154"})
        assert self.rule.evaluate([el()], context) == []

    def test_missing_georeference_flagged_info(self) -> None:
        results = self.rule.evaluate([el()], ctx(georeference=None, bounding_box=None))
        assert len(results) == 1
        assert results[0].severity == "info"
        assert results[0].details["reason"] == "no_georeference"

    def test_origin_placement_flagged(self) -> None:
        context = ctx(georeference={"base_point": [0.0, 0.0, 0.0]})
        results = self.rule.evaluate([el()], context)
        assert len(results) == 1
        assert results[0].details["reason"] == "origin_placement"

    def test_implausible_coordinates_flagged(self) -> None:
        context = ctx(georeference={"survey_point": [9.9e9, 0.0, 0.0]})
        results = self.rule.evaluate([el()], context)
        assert any(r.details["reason"] == "implausible_coordinates" for r in results)

    def test_malformed_data_does_not_crash(self) -> None:
        context = ctx(georeference={"base_point": "not-a-coordinate"}, bounding_box="oops")  # type: ignore[arg-type]
        # georeference present (truthy) so no "missing" finding; no numeric
        # coordinates extracted -> no plausibility finding; nothing raised.
        assert self.rule.evaluate([el()], context) == []


# ── Context builder -------------------------------------------------------


class TestBIMModelContextFromModel:
    def test_reads_units_and_georeference(self) -> None:
        model = SimpleNamespace(
            id="m-1",
            name="Tower",
            metadata_={
                "units": {"unit_system": "imperial", "had_assignment": True},
                "coordinate_system": "EPSG:2154",
            },
            bounding_box={"min": [0, 0, 0], "max": [10, 10, 3]},
        )
        context = BIMModelContext.from_model(model)
        assert context.model_id == "m-1"
        assert context.unit_system == "imperial"
        assert context.had_unit_assignment is True
        assert context.units_declared is True
        assert context.georeference is not None
        assert "coordinate_system" in context.georeference
        assert context.bounding_box == {"min": [0, 0, 0], "max": [10, 10, 3]}

    def test_missing_metadata_is_fail_soft(self) -> None:
        model = SimpleNamespace(id="m-2", name="Empty", metadata_=None, bounding_box=None)
        context = BIMModelContext.from_model(model)
        assert context.unit_system is None
        assert context.units_declared is False
        assert context.georeference is None


# ── 11. Unique marks per category -----------------------------------------


class TestUniqueMarksPerCategory:
    rule = UniqueMarksPerCategoryRule()

    def test_unique_marks_pass(self) -> None:
        elements = [
            el(id="a", element_type="door", properties={"mark": "D-101"}),
            el(id="b", element_type="door", properties={"mark": "D-102"}),
        ]
        assert self.rule.evaluate(elements, ctx()) == []

    def test_duplicate_mark_in_category_flagged(self) -> None:
        elements = [
            el(id="a", element_type="door", properties={"mark": "D-101"}),
            el(id="b", element_type="IfcDoor", properties={"mark": "D-101"}),
            el(id="c", element_type="door", properties={"mark": "D-200"}),
        ]
        results = self.rule.evaluate(elements, ctx())
        assert len(results) == 1
        assert results[0].severity == "warning"
        assert results[0].element_ref == "D-101"
        assert results[0].details["category"] == "door"
        assert results[0].details["count"] == 2
        assert set(results[0].details["element_ids"]) == {"a", "b"}

    def test_same_mark_different_category_ok(self) -> None:
        # A door "1" and a window "1" do not collide - marks are per category.
        elements = [
            el(id="a", element_type="door", properties={"mark": "1"}),
            el(id="b", element_type="window", properties={"mark": "1"}),
        ]
        assert self.rule.evaluate(elements, ctx()) == []

    def test_tag_then_reference_fallback(self) -> None:
        elements = [
            el(id="a", element_type="pipe", properties={"tag": "P-1"}),
            el(id="b", element_type="pipe", properties={"reference": "P-1"}),
        ]
        results = self.rule.evaluate(elements, ctx())
        assert len(results) == 1
        assert results[0].details["mark"] == "P-1"

    def test_blank_and_missing_marks_ignored(self) -> None:
        elements = [
            el(id="a", element_type="door", properties={"mark": ""}),
            el(id="b", element_type="door", properties={}),
            el(id="c", element_type="door", properties=None),
        ]
        assert self.rule.evaluate(elements, ctx()) == []


# ── 12. Classification coverage -------------------------------------------


class TestClassificationCoverage:
    rule = ClassificationCoverageRule()

    def test_high_coverage_passes(self) -> None:
        # 2 of 3 = 67% >= 50%.
        elements = [
            el(properties={"classification": {"din276": "330"}}),
            el(properties={"classification": {"din276": "340"}}),
            el(properties={}),
        ]
        assert self.rule.evaluate(elements, ctx()) == []

    def test_exactly_half_passes(self) -> None:
        # 1 of 2 = 50% >= 50%.
        elements = [
            el(properties={"classification": {"nrm": "2.6"}}),
            el(properties={}),
        ]
        assert self.rule.evaluate(elements, ctx()) == []

    def test_low_coverage_flagged_info(self) -> None:
        # 1 of 3 = 33% < 50%.
        elements = [
            el(properties={"classification": {"din276": "330"}}),
            el(properties={}),
            el(properties={}),
        ]
        results = self.rule.evaluate(elements, ctx())
        assert len(results) == 1
        assert results[0].severity == "info"
        assert results[0].details == {"classified": 1, "total": 3, "coverage": 0.333}

    def test_classification_attribute_counts(self) -> None:
        # 1 of 2 = 50% via the direct classification attribute.
        elements = [el(classification={"uniclass": "Ss_25"}), el(properties={})]
        assert self.rule.evaluate(elements, ctx()) == []

    def test_sparse_props_do_not_crash(self) -> None:
        elements = [el(properties=None), el(properties="oops")]  # type: ignore[arg-type]
        results = self.rule.evaluate(elements, ctx())
        # 0 of 2 classified -> flagged, nothing raised.
        assert len(results) == 1


# ── 13. Spatial structure -------------------------------------------------


class TestSpatialStructure:
    rule = SpatialStructureRule()

    def test_element_storey_signal_passes(self) -> None:
        assert self.rule.evaluate([el(storey="Level 1"), el()], ctx()) == []

    def test_metadata_levels_signal_passes(self) -> None:
        context = ctx(metadata={"levels": ["L1", "L2"]})
        assert self.rule.evaluate([el()], context) == []

    def test_no_spatial_structure_flagged(self) -> None:
        results = self.rule.evaluate([el(), el()], ctx())
        assert len(results) == 1
        assert results[0].severity == "warning"
        assert results[0].details["reason"] == "no_spatial_structure"

    def test_sparse_does_not_crash(self) -> None:
        context = ctx(metadata=None)  # type: ignore[arg-type]
        results = self.rule.evaluate([el(storey=None), el(storey="")], context)
        assert len(results) == 1


# ── 14. Discipline coverage -----------------------------------------------


class TestDisciplineCoverage:
    rule = DisciplineCoverageRule()

    def test_discipline_present_passes(self) -> None:
        assert self.rule.evaluate([el(discipline="Architecture"), el()], ctx()) == []

    def test_no_discipline_flagged_info(self) -> None:
        results = self.rule.evaluate([el(), el()], ctx())
        assert len(results) == 1
        assert results[0].severity == "info"
        assert results[0].details["reason"] == "no_discipline"

    def test_blank_discipline_does_not_count(self) -> None:
        results = self.rule.evaluate([el(discipline=""), el(discipline=None)], ctx())
        assert len(results) == 1

    def test_sparse_does_not_crash(self) -> None:
        # Elements without a discipline attribute at all -> flagged, no raise.
        assert len(self.rule.evaluate([el()], ctx())) == 1
