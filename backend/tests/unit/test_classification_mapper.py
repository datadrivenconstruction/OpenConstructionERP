# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for ``app.modules.cad.classification_mapper``.

Covers Phase-1 of the v2.8.0 vector match feature:

* Coarse fallback when no material is supplied
* Material-aware refinement (concrete / masonry / timber / drywall / steel)
* Synonym folding across DE/EN material strings
* Fire-rated doors prefer the steel variant
* Unknown category → ``None``; unknown material with known category falls
  back to the coarse code.
* All three standards (DIN 276, NRM 1, MasterFormat) exercised.
* ``map_elements_to_classification`` keeps emitting coarse codes for
  elements that lack material — no behaviour regression.
"""

from __future__ import annotations

import pytest

from app.modules.cad.classification_mapper import (
    MATERIAL_AWARE_DIN276,
    MATERIAL_AWARE_MASTERFORMAT,
    MATERIAL_AWARE_NRM,
    REVIT_TO_DIN276,
    REVIT_TO_MASTERFORMAT,
    REVIT_TO_NRM,
    enrich_classification,
    enrich_elements_classification,
    get_mapping_table,
    get_supported_standards,
    map_category_to_standard,
    map_elements_to_classification,
)

# ── Coarse fallback (legacy contract) ─────────────────────────────────────


class TestCoarseFallback:
    """Legacy ``map_category_to_standard`` contract still holds."""

    def test_revit_pascal_walls_resolves_to_330(self) -> None:
        assert map_category_to_standard("Walls", "din276") == "330"

    def test_lowercase_singular_wall_resolves_via_alias(self) -> None:
        # The BIM canonical format and golden_set use lowercase singular
        # — alias should fold to "Walls" → "330".
        assert map_category_to_standard("wall", "din276") == "330"

    def test_unknown_category_returns_none(self) -> None:
        assert map_category_to_standard("Unobtanium", "din276") is None

    def test_unknown_standard_returns_none(self) -> None:
        assert map_category_to_standard("Walls", "klingonformat") is None

    def test_all_three_standards_have_walls_entry(self) -> None:
        assert map_category_to_standard("Walls", "din276") == "330"
        assert map_category_to_standard("Walls", "nrm") == "2.5"
        assert map_category_to_standard("Walls", "masterformat") == "04 00 00"


class TestEnrichCoarseFallback:
    """``enrich_classification`` must replicate the coarse map when no
    material/refinement is available."""

    def test_no_material_returns_coarse(self) -> None:
        assert enrich_classification("Walls") == "330"
        assert enrich_classification("Walls", standard="nrm") == "2.5"
        assert (
            enrich_classification("Walls", standard="masterformat")
            == "04 00 00"
        )

    def test_unknown_category_returns_none(self) -> None:
        assert enrich_classification("Unobtanium", material="concrete") is None

    def test_unknown_material_with_known_category_falls_back_to_coarse(self) -> None:
        # Material string completely outside the synonym vocabulary —
        # extracted code must still be the coarse 3-digit fallback.
        result = enrich_classification(
            "Walls", material="Unobtanium DXG-7 alloy",
        )
        assert result == "330"

    def test_empty_category_returns_none(self) -> None:
        assert enrich_classification("") is None
        assert enrich_classification("", material="concrete") is None


# ── Material-aware refinement (DIN 276) ───────────────────────────────────


class TestMaterialAwareDin276:
    """Deeper DIN-276 codes when both category + material are known."""

    @pytest.mark.parametrize(
        ("category", "material", "expected"),
        [
            ("Walls", "Concrete C30/37", "330.10"),
            ("Walls", "Stahlbeton C30/37", "330.10"),
            ("Walls", "Reinforced concrete", "330.10"),
            ("wall", "Beton C25/30", "330.10"),  # alias + DE synonym
            ("Walls", "Mauerwerk Kalksandstein", "331.10"),
            ("Walls", "Brick masonry NF", "331.10"),
            ("Walls", "Ziegel", "331.10"),
            ("Walls", "Solid wood timber wall", "331.40"),
            ("Walls", "Drywall metal stud, 100mm", "331.30"),
            ("Walls", "Trockenbau Gipskarton", "331.30"),
            ("Floors", "Reinforced concrete C25/30", "350.10"),
            ("slab", "Concrete C30/37", "350.10"),  # alias
            ("Roofs", "Concrete C25/30", "360.10"),
            ("Roofs", "Timber rafters", "360.20"),
            ("Structural Foundations", "Concrete C20/25", "322.10"),
            ("foundation", "Strip foundation, concrete C20/25", "322.10"),
            # Columns: golden_set uses 340.10 for concrete columns
            ("Columns", "Reinforced concrete column C30/37", "340.10"),
            ("column", "Concrete", "340.10"),  # alias
            ("Columns", "Structural steel S235JR", "340.20"),
            ("Curtain Walls", "Aluminium curtain wall, structural glazing", "334.20"),
            ("Curtain Walls", "Glass", "334.20"),
        ],
    )
    def test_refinement(self, category: str, material: str, expected: str) -> None:
        assert (
            enrich_classification(category, material=material) == expected
        )


# ── Synonym folding ───────────────────────────────────────────────────────


class TestSynonymFolding:
    """German + English material vocabularies collapse to the same key."""

    def test_concrete_synonyms_all_map_to_330_10(self) -> None:
        for material in (
            "concrete",
            "Beton",
            "Stahlbeton",
            "reinforced concrete",
            "Concrete C30/37",
            "Stahlbeton C25/30",
        ):
            assert (
                enrich_classification("Walls", material=material) == "330.10"
            ), f"failed for material={material!r}"

    def test_masonry_synonyms_all_map_to_331_10(self) -> None:
        for material in (
            "Brick",
            "Brick masonry NF",
            "Mauerwerk",
            "Kalksandstein KS 12-1.4",
            "Ziegel",
        ):
            assert (
                enrich_classification("Walls", material=material) == "331.10"
            ), f"failed for material={material!r}"

    def test_timber_synonyms_all_map_to_331_40(self) -> None:
        for material in ("timber", "Holz", "wood", "Solid wood"):
            assert (
                enrich_classification("Walls", material=material) == "331.40"
            ), f"failed for material={material!r}"

    def test_steel_synonyms_all_map_to_340_20_for_columns(self) -> None:
        for material in ("steel", "Stahl", "Structural steel S235", "IPE240"):
            assert (
                enrich_classification("Columns", material=material) == "340.20"
            ), f"failed for material={material!r}"

    def test_drywall_synonyms_all_map_to_331_30(self) -> None:
        for material in (
            "Drywall",
            "Trockenbau",
            "Gipskarton",
            "Plasterboard",
            "metal stud",
        ):
            assert (
                enrich_classification("Walls", material=material) == "331.30"
            ), f"failed for material={material!r}"


# ── Fire-rated doors prefer steel ─────────────────────────────────────────


class TestFireRatedDoors:
    """Doors with a real fire rating bypass the timber/steel material
    decision and route to the steel/fire-rated variant."""

    def test_wood_door_no_fire_rating_uses_timber_variant(self) -> None:
        assert (
            enrich_classification(
                "Doors", material="Solid wood interior door",
            )
            == "344.10"
        )

    def test_wood_door_with_f90_routes_to_steel_variant(self) -> None:
        assert (
            enrich_classification(
                "Doors",
                material="Solid wood interior door",
                fire_rating="F90",
            )
            == "344.20"
        )

    def test_steel_door_with_fire_rating_unchanged(self) -> None:
        assert (
            enrich_classification(
                "Doors",
                material="Steel door",
                fire_rating="F90",
            )
            == "344.20"
        )

    def test_fire_rating_f0_does_not_trigger_steel(self) -> None:
        # F0 is a well-known sentinel for "no rating" — must stay timber.
        assert (
            enrich_classification(
                "Doors",
                material="Solid wood interior door",
                fire_rating="F0",
            )
            == "344.10"
        )

    def test_fire_rating_none_string_does_not_trigger_steel(self) -> None:
        assert (
            enrich_classification(
                "Doors",
                material="Solid wood",
                fire_rating="none",
            )
            == "344.10"
        )


# ── NRM 1 refinement ──────────────────────────────────────────────────────


class TestMaterialAwareNrm:
    """NRM 1 deeper codes — smaller scope, but symmetric coverage."""

    def test_concrete_wall_resolves_to_2_5_1(self) -> None:
        assert (
            enrich_classification(
                "Walls", material="Concrete", standard="nrm",
            )
            == "2.5.1"
        )

    def test_masonry_wall_resolves_to_2_5_2(self) -> None:
        assert (
            enrich_classification(
                "Walls", material="Brick", standard="nrm",
            )
            == "2.5.2"
        )

    def test_drywall_resolves_to_internal_partitions_2_7_1(self) -> None:
        assert (
            enrich_classification(
                "Walls", material="Drywall", standard="nrm",
            )
            == "2.7.1"
        )

    def test_unknown_material_falls_back_to_coarse_2_5(self) -> None:
        assert (
            enrich_classification(
                "Walls", material="Unobtanium", standard="nrm",
            )
            == "2.5"
        )

    def test_concrete_foundation_resolves_to_substructure_1_1_1(self) -> None:
        assert (
            enrich_classification(
                "Structural Foundations",
                material="Concrete",
                standard="nrm",
            )
            == "1.1.1"
        )


# ── MasterFormat refinement ───────────────────────────────────────────────


class TestMaterialAwareMasterFormat:
    """MasterFormat 2020 6-digit deeper codes."""

    def test_concrete_wall_resolves_to_03_30_00(self) -> None:
        assert (
            enrich_classification(
                "Walls", material="Concrete", standard="masterformat",
            )
            == "03 30 00"
        )

    def test_brick_masonry_wall_resolves_to_04_22_00(self) -> None:
        assert (
            enrich_classification(
                "Walls", material="Brick", standard="masterformat",
            )
            == "04 22 00"
        )

    def test_drywall_resolves_to_09_21_00(self) -> None:
        assert (
            enrich_classification(
                "Walls", material="Drywall", standard="masterformat",
            )
            == "09 21 00"
        )

    def test_steel_columns_resolves_to_05_12_00(self) -> None:
        assert (
            enrich_classification(
                "Columns", material="Steel", standard="masterformat",
            )
            == "05 12 00"
        )

    def test_wood_doors_resolves_to_08_14_00(self) -> None:
        assert (
            enrich_classification(
                "Doors", material="Wood", standard="masterformat",
            )
            == "08 14 00"
        )

    def test_unknown_material_falls_back_to_coarse(self) -> None:
        assert (
            enrich_classification(
                "Walls", material="Unobtanium", standard="masterformat",
            )
            == "04 00 00"
        )


# ── map_elements_to_classification (mutates list in place) ────────────────


class TestMapElementsToClassification:
    """Existing list-mutation contract still works, now with material
    refinement when a ``properties.material`` field is present."""

    def test_coarse_when_no_material(self) -> None:
        elements = [{"id": "e1", "category": "Walls"}]
        result = map_elements_to_classification(elements, standard="din276")
        assert result is elements  # in-place mutation
        assert elements[0]["classification"] == {"din276": "330"}

    def test_deep_when_material_present(self) -> None:
        elements = [{
            "id": "e1",
            "category": "Walls",
            "properties": {"material": "Stahlbeton C30/37"},
        }]
        map_elements_to_classification(elements, standard="din276")
        assert elements[0]["classification"]["din276"] == "330.10"

    def test_preserves_existing_other_standard_classifications(self) -> None:
        elements = [{
            "id": "e1",
            "category": "Walls",
            "classification": {"masterformat": "04 00 00"},
        }]
        map_elements_to_classification(elements, standard="din276")
        assert elements[0]["classification"]["din276"] == "330"
        assert elements[0]["classification"]["masterformat"] == "04 00 00"

    def test_unknown_category_leaves_classification_unchanged(self) -> None:
        elements = [{"id": "e1", "category": "Unobtanium"}]
        map_elements_to_classification(elements, standard="din276")
        # No "classification" key added because no code resolved.
        assert "classification" not in elements[0]

    def test_fire_rating_routes_to_steel_door(self) -> None:
        elements = [{
            "id": "e1",
            "category": "Doors",
            "properties": {
                "material": "Solid wood interior door",
                "fire_rating": "F90",
            },
        }]
        map_elements_to_classification(elements, standard="din276")
        assert elements[0]["classification"]["din276"] == "344.20"

    def test_alias_function_enrich_elements_classification(self) -> None:
        """``enrich_elements_classification`` is an alias of ``map_…``."""
        elements = [{"id": "e1", "category": "Walls",
                     "properties": {"material": "Concrete"}}]
        result = enrich_elements_classification(elements, "din276")
        assert result[0]["classification"]["din276"] == "330.10"


# ── Module surface ────────────────────────────────────────────────────────


class TestModuleSurface:
    """Sanity: exported tables and helpers stay accessible to callers."""

    def test_get_supported_standards_returns_three(self) -> None:
        assert sorted(get_supported_standards()) == sorted(
            ["din276", "nrm", "masterformat"],
        )

    def test_get_mapping_table_returns_independent_dict(self) -> None:
        table = get_mapping_table("din276")
        assert table["Walls"] == "330"
        # Mutating the returned dict must not affect the module constant.
        table["Walls"] = "999"
        assert REVIT_TO_DIN276["Walls"] == "330"

    def test_get_mapping_table_unknown_returns_empty(self) -> None:
        assert get_mapping_table("klingonformat") == {}

    def test_material_aware_tables_exposed(self) -> None:
        # The Phase-2 reranker / debugging UI may want to introspect.
        assert ("Walls", "concrete") in MATERIAL_AWARE_DIN276
        assert ("Walls", "concrete") in MATERIAL_AWARE_NRM
        assert ("Walls", "concrete") in MATERIAL_AWARE_MASTERFORMAT
        # Coarse tables are still exported.
        assert REVIT_TO_NRM["Walls"] == "2.5"
        assert REVIT_TO_MASTERFORMAT["Walls"] == "04 00 00"
