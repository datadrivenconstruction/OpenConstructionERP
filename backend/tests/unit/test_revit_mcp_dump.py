# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the revit-mcp dump → BIM Hub element converter.

No DB, no session, no MCP process - plain dict in, dict out. The dump
shape under test is what ``mcp-server-for-revit`` 1.0.0 actually emits;
the fixture documents which parts are verbatim and which are invented.

The instance tier is exercised from inline dicts rather than the fixture
because its per-element field spellings are *inferred*: every real dump
seen so far was taken with a DrawingSheet active, which yields an empty
element list. The converter therefore probes several plausible key
spellings, and these tests pin that tolerance so a future real sample
either passes or fails loudly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.modules.bim_hub.revit_mcp_dump import (
    SOURCE,
    UNITS_IMPERIAL,
    UNITS_RAW,
    build_bulk_import_payload,
    convert_dump,
    infer_discipline,
    is_annotation_category,
)
from app.modules.bim_hub.schemas import BIMElementBulkImport

FIXTURE = Path(__file__).parents[1] / "fixtures" / "revit_mcp" / "sheet_view_dump.json"


@pytest.fixture
def dump() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _by_tier(elements: list[dict[str, Any]], tier: str) -> list[dict[str, Any]]:
    return [e for e in elements if e["metadata"]["tier"] == tier]


def _named(elements: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [e for e in elements if e["name"] == name]
    assert matches, f"no element named {name!r} among {[e['name'] for e in elements]}"
    return matches[0]


# ── Tier extraction ──────────────────────────────────────────────────────────


def test_sheet_dump_yields_type_and_material_tiers(dump: dict[str, Any]) -> None:
    result = convert_dump(dump)

    # 4 non-annotation categories expose types: Lighting Fixtures (2),
    # Fire Alarm (1), Communication (1), Security (1) = 5 type rows.
    assert len(_by_tier(result.elements, "type")) == 5
    assert len(_by_tier(result.elements, "material")) == 3
    # A DrawingSheet active view can never yield model instances.
    assert _by_tier(result.elements, "instance") == []
    assert len(result.elements) == 8


def test_empty_view_elements_warns_with_view_name(dump: dict[str, Any]) -> None:
    result = convert_dump(dump)

    warning = next(w for w in result.warnings if "get_current_view_elements" in w)
    assert "SAMPLE SHEET - LIGHTING LAYOUT" in warning
    assert "DrawingSheet" in warning


def test_missing_tools_degrade_instead_of_raising() -> None:
    result = convert_dump({"get_current_view_info": {"Name": "X", "ViewType": "ThreeD"}})

    assert result.elements == []
    assert any("no elements produced" in w for w in result.warnings)


def test_non_dict_dump_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be a dict"):
        convert_dump([])  # type: ignore[arg-type]


def test_unknown_units_is_rejected(dump: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="units must be"):
        convert_dump(dump, units="metric")


# ── IFC crosswalk + discipline ───────────────────────────────────────────────


def test_electrical_categories_resolve_to_ifc_classes(dump: dict[str, Any]) -> None:
    types = _by_tier(convert_dump(dump).elements, "type")

    assert _named(types, "HIGHBAY 120W")["element_type"] == "IfcLightFixture"
    # Both added to the crosswalk for this importer: ifc_labels already
    # carried the classes, only the RVT category keys were missing.
    assert _named(types, "SMOKE")["element_type"] == "IfcAlarm"
    assert _named(types, "CEILING SPEAKER")["element_type"] == "IfcCommunicationsAppliance"


def test_ambiguous_category_keeps_raw_name_not_a_guess(dump: dict[str, Any]) -> None:
    types = _by_tier(convert_dump(dump).elements, "type")

    # "Security Devices" mixes cameras / contacts / panic buttons, so the
    # crosswalk deliberately declines it. The raw category survives.
    card_reader = _named(types, "CARD READER")
    assert card_reader["element_type"] == "Security Devices"
    assert card_reader["properties"]["revit_category"] == "Security Devices"


def test_discipline_inference_prefers_specific_trades() -> None:
    assert infer_discipline("Lighting Fixtures") == "electrical"
    assert infer_discipline("Cable Tray Fittings") == "electrical"
    assert infer_discipline("Fire Alarm Devices") == "electrical"
    assert infer_discipline("Ducts") == "mechanical"
    assert infer_discipline("Structural Columns") == "structural"
    assert infer_discipline("Walls") == "architectural"
    assert infer_discipline("Topography") == "civil"
    # No keyword match must not become a default.
    assert infer_discipline("Mystery Category") is None
    assert infer_discipline(None) is None


def test_type_rows_carry_family_type_and_instance_count(dump: dict[str, Any]) -> None:
    highbay = _named(_by_tier(convert_dump(dump).elements, "type"), "HIGHBAY 120W")

    assert highbay["discipline"] == "electrical"
    assert highbay["quantities"] == {"instance_count": 20}
    assert highbay["properties"]["revit_family"] == "SAMPLE_HIGHBAY"
    assert highbay["properties"]["source"] == SOURCE
    assert highbay["storey"] is None


# ── Annotation filter ────────────────────────────────────────────────────────


def test_annotation_categories_are_dropped_by_default(dump: dict[str, Any]) -> None:
    result = convert_dump(dump)

    names = {e["name"] for e in result.elements}
    assert "SAMPLE_TAG" not in names
    assert any("annotation/view category" in w for w in result.warnings)


def test_include_annotation_keeps_them(dump: dict[str, Any]) -> None:
    result = convert_dump(dump, include_annotation=True)

    tag = _named(_by_tier(result.elements, "type"), "SAMPLE_TAG")
    assert tag["properties"]["revit_category"] == "Generic Annotations"
    assert len(result.elements) == 9


def test_annotation_classification_is_conservative() -> None:
    assert is_annotation_category("Room Tags")
    assert is_annotation_category("Lighting Fixture Tags")
    assert is_annotation_category("Title Blocks")
    assert is_annotation_category("Detail Items")
    assert is_annotation_category("Sheets")
    # Physical categories must never be filtered out.
    assert not is_annotation_category("Lighting Fixtures")
    assert not is_annotation_category("Cable Trays")
    assert not is_annotation_category("Walls")
    # Unknown categories are treated as real elements, not dropped.
    assert not is_annotation_category("Mystery Category")
    assert not is_annotation_category(None)


# ── Units contract ───────────────────────────────────────────────────────────


def test_raw_units_keep_numbers_verbatim_and_flag_them(dump: dict[str, Any]) -> None:
    glass = _named(_by_tier(convert_dump(dump, units=UNITS_RAW).elements, "material"), "Sample Glass")

    assert glass["quantities"]["area_raw"] == 100.0
    assert glass["quantities"]["volume_raw"] == 10.0
    assert "area_m2" not in glass["quantities"]
    assert glass["metadata"]["units"] == "unverified"


def test_imperial_units_convert_to_metric(dump: dict[str, Any]) -> None:
    glass = _named(_by_tier(convert_dump(dump, units=UNITS_IMPERIAL).elements, "material"), "Sample Glass")

    assert glass["quantities"]["area_m2"] == pytest.approx(100.0 * 0.09290304)
    assert glass["quantities"]["volume_m3"] == pytest.approx(10.0 * 0.028316846592)
    assert "area_raw" not in glass["quantities"]
    assert "ft2/ft3" in glass["metadata"]["units"]


def test_zero_quantities_are_kept_not_dropped(dump: dict[str, Any]) -> None:
    materials = _by_tier(convert_dump(dump).elements, "material")
    zero = _named(materials, "Sample Zero-Geometry")

    # 0.0 is a real measurement (annotation-only material), not missing data.
    assert zero["quantities"]["area_raw"] == 0.0
    assert zero["quantities"]["volume_raw"] == 0.0


def test_material_rows_keep_the_element_id_backlink(dump: dict[str, Any]) -> None:
    glass = _named(_by_tier(convert_dump(dump).elements, "material"), "Sample Glass")

    assert glass["element_type"] == "IfcMaterial"
    assert glass["properties"]["revit_element_ids"] == [900001, 900002, 900003]
    assert glass["quantities"]["element_count"] == 3


# ── Instance tier (inferred field spellings) ─────────────────────────────────


def _instance_dump(elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "get_current_view_elements": {
            "result": {
                "ViewId": 1,
                "ViewName": "3D VIEW",
                "TotalElementsInView": len(elements),
                "FilteredElementCount": len(elements),
                "Truncated": False,
                "Elements": elements,
            },
        },
    }


def test_instance_rows_map_pascal_case_fields() -> None:
    result = convert_dump(
        _instance_dump(
            [
                {
                    "Id": 643643,
                    "Name": "HIGHBAY 120W NRML",
                    "Category": "Lighting Fixtures",
                    "FamilyName": "SAMPLE_HIGHBAY",
                    "TypeName": "HIGHBAY 120W NRML",
                    "Level": "GROUND FLOOR",
                },
            ],
        ),
    )

    (row,) = result.elements
    assert row["stable_id"] == "rvt:643643"
    assert row["element_type"] == "IfcLightFixture"
    assert row["discipline"] == "electrical"
    assert row["storey"] == "GROUND FLOOR"
    assert row["properties"]["revit_element_id"] == 643643
    assert row["metadata"]["tier"] == "instance"


def test_instance_rows_map_camel_case_fields() -> None:
    result = convert_dump(
        _instance_dump([{"elementId": 700001, "categoryName": "Cable Trays", "levelName": "1st FLOOR"}]),
    )

    (row,) = result.elements
    assert row["element_type"] == "IfcCableCarrierSegment"
    assert row["storey"] == "1st FLOOR"


def test_instance_rows_without_an_id_are_skipped_and_reported() -> None:
    result = convert_dump(_instance_dump([{"Category": "Walls"}, {"Id": 1, "Category": "Walls"}]))

    assert len(result.elements) == 1
    assert any("no recognisable element id" in w for w in result.warnings)


def test_truncated_view_is_reported() -> None:
    payload = _instance_dump([{"Id": 1, "Category": "Walls"}])
    payload["get_current_view_elements"]["result"]["Truncated"] = True

    assert any("Truncated=true" in w for w in convert_dump(payload).warnings)


def test_instance_annotation_rows_are_dropped_by_default() -> None:
    payload = _instance_dump(
        [{"Id": 1, "Category": "Room Tags"}, {"Id": 2, "Category": "Lighting Fixtures"}],
    )

    kept = convert_dump(payload).elements
    assert [e["properties"]["revit_category"] for e in kept] == ["Lighting Fixtures"]
    assert len(convert_dump(payload, include_annotation=True).elements) == 2


# ── Identity + schema conformance ────────────────────────────────────────────


def test_stable_ids_are_unique_and_deduped() -> None:
    payload = _instance_dump([{"Id": 5, "Category": "Walls"}, {"Id": 5, "Category": "Walls"}])
    result = convert_dump(payload)

    assert len(result.elements) == 1
    assert any("duplicate stable_id" in w for w in result.warnings)


def test_long_identifiers_are_hashed_within_the_column_width() -> None:
    long_name = "X" * 400
    payload = {
        "analyze_model_statistics": {
            "categories": [
                {
                    "categoryName": "Lighting Fixtures",
                    "types": [
                        {"typeName": long_name, "familyName": long_name, "instanceCount": 1},
                        {"typeName": long_name + "Y", "familyName": long_name, "instanceCount": 1},
                    ],
                },
            ],
        },
    }
    result = convert_dump(payload)

    stable_ids = [e["stable_id"] for e in result.elements]
    assert all(len(sid) <= 255 for sid in stable_ids)
    # Truncation must not collapse two distinct types into one row.
    assert len(set(stable_ids)) == 2
    assert len(result.elements) == 2
    assert all(len(e["name"] or "") <= 500 for e in result.elements)


def test_output_validates_against_the_bulk_import_schema(dump: dict[str, Any]) -> None:
    payload = build_bulk_import_payload(dump, units=UNITS_IMPERIAL)

    validated = BIMElementBulkImport.model_validate(payload)
    assert len(validated.elements) == len(payload["elements"])


# ── Model summary ────────────────────────────────────────────────────────────


def test_model_summary_reports_project_levels_and_totals(dump: dict[str, Any]) -> None:
    model = convert_dump(dump).model

    assert model["name"] == "SAMPLE-ELECTRICAL-UTILITY"
    assert model["model_format"] == "rvt"
    assert model["storey_count"] == 2
    assert model["element_count"] == 8
    assert model["metadata"]["revit_totals"]["totalElements"] == 1000
    assert model["metadata"]["revit_active_view"]["view_type"] == "DrawingSheet"
    assert [lvl["name"] for lvl in model["metadata"]["revit_levels"]] == [
        "GROUND FLOOR",
        "1st FLOOR",
    ]


def test_single_discipline_model_claims_it(dump: dict[str, Any]) -> None:
    # Every non-annotation category in the fixture is electrical.
    assert convert_dump(dump).model["discipline"] == "electrical"


def test_mixed_discipline_model_claims_none() -> None:
    payload = {
        "analyze_model_statistics": {
            "categories": [
                {"categoryName": "Lighting Fixtures", "types": [{"typeName": "A", "instanceCount": 1}]},
                {"categoryName": "Walls", "types": [{"typeName": "B", "instanceCount": 1}]},
            ],
        },
    }
    model = convert_dump(payload).model

    # A single column cannot describe a mixed model; the detail is kept.
    assert model["discipline"] is None
    assert model["metadata"]["disciplines_detected"] == ["architectural", "electrical"]
