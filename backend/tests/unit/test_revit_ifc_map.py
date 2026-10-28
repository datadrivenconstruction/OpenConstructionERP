# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Revit OST → IFC class crosswalk.

These exercise :func:`normalize_to_ifc_class` in isolation — no DB, no
session, plain ``assert``. The crosswalk is what lets a Revit (RVT) model
inherit the same label / standards-hint / Qdrant-filter behaviour an IFC
model gets, so the mapping correctness here is load-bearing for match
quality on Revit imports.
"""

from __future__ import annotations

from app.modules.match_elements.revit_ifc_map import (
    OST_TO_IFC,
    normalize_to_ifc_class,
)


def test_key_architectural_categories_map() -> None:
    assert normalize_to_ifc_class("Walls") == "IfcWall"
    assert normalize_to_ifc_class("Basic Wall") == "IfcWall"
    assert normalize_to_ifc_class("Stacked Wall") == "IfcWall"
    assert normalize_to_ifc_class("Curtain Wall") == "IfcCurtainWall"
    assert normalize_to_ifc_class("Curtain Systems") == "IfcCurtainWall"
    assert normalize_to_ifc_class("Floors") == "IfcSlab"
    assert normalize_to_ifc_class("Mass Floors") == "IfcSlab"
    assert normalize_to_ifc_class("Roofs") == "IfcRoof"
    assert normalize_to_ifc_class("Ceilings") == "IfcCovering"
    assert normalize_to_ifc_class("Doors") == "IfcDoor"
    assert normalize_to_ifc_class("Windows") == "IfcWindow"
    assert normalize_to_ifc_class("Stairs") == "IfcStair"
    assert normalize_to_ifc_class("Railings") == "IfcRailing"
    assert normalize_to_ifc_class("Ramps") == "IfcRamp"


def test_key_structural_categories_map() -> None:
    assert normalize_to_ifc_class("Structural Columns") == "IfcColumn"
    assert normalize_to_ifc_class("Columns") == "IfcColumn"
    assert normalize_to_ifc_class("Structural Framing") == "IfcBeam"
    assert normalize_to_ifc_class("Beams") == "IfcBeam"
    assert normalize_to_ifc_class("Structural Foundations") == "IfcFooting"
    assert normalize_to_ifc_class("Foundation") == "IfcFooting"


def test_key_mep_categories_map() -> None:
    assert normalize_to_ifc_class("Pipes") == "IfcPipeSegment"
    assert normalize_to_ifc_class("Ducts") == "IfcDuctSegment"
    assert normalize_to_ifc_class("Cable Trays") == "IfcCableCarrierSegment"
    assert normalize_to_ifc_class("Conduits") == "IfcCableCarrierSegment"
    assert normalize_to_ifc_class("Lighting Fixtures") == "IfcLightFixture"
    assert normalize_to_ifc_class("Plumbing Fixtures") == "IfcSanitaryTerminal"
    assert normalize_to_ifc_class("Mechanical Equipment") == "IfcUnitaryEquipment"


def test_spatial_and_generic_categories_map() -> None:
    assert normalize_to_ifc_class("Furniture") == "IfcFurniture"
    assert normalize_to_ifc_class("Casework") == "IfcFurniture"
    assert normalize_to_ifc_class("Generic Models") == "IfcBuildingElementProxy"
    assert normalize_to_ifc_class("Topography") == "IfcSite"
    assert normalize_to_ifc_class("Parking") == "IfcSpace"
    assert normalize_to_ifc_class("Rooms") == "IfcSpace"
    assert normalize_to_ifc_class("Areas") == "IfcSpace"


def test_unknown_category_returns_none() -> None:
    # Never guess for a category outside the crosswalk.
    assert normalize_to_ifc_class("Hyperloop Tube") is None
    assert normalize_to_ifc_class("Schedules/Quantities") is None
    assert normalize_to_ifc_class("") is None
    assert normalize_to_ifc_class("   ") is None
    assert normalize_to_ifc_class(None) is None


def test_genuine_ifc_class_is_idempotent() -> None:
    # A value already in IFC spelling must pass through untouched and must
    # never be double-mapped.
    assert normalize_to_ifc_class("IfcWall") == "IfcWall"
    assert normalize_to_ifc_class("IfcSlab") == "IfcSlab"
    assert normalize_to_ifc_class("IfcWallStandardCase") == "IfcWallStandardCase"
    # Case-insensitive prefix detection — still returns the input verbatim.
    assert normalize_to_ifc_class("ifcWall") == "ifcWall"


def test_ost_prefix_is_stripped() -> None:
    assert normalize_to_ifc_class("OST_Walls") == "IfcWall"
    assert normalize_to_ifc_class("OST_StructuralColumns") == "IfcColumn"
    # Lower-case prefix tolerated too.
    assert normalize_to_ifc_class("ost_Floors") == "IfcSlab"


def test_case_and_plural_tolerance() -> None:
    # Case-insensitive matching.
    assert normalize_to_ifc_class("WALLS") == "IfcWall"
    assert normalize_to_ifc_class("walls") == "IfcWall"
    # Whitespace tolerance.
    assert normalize_to_ifc_class("  Walls  ") == "IfcWall"
    # Singular/plural fallback for a spelling the table did not list
    # explicitly resolves through the s-suffix probe.
    assert normalize_to_ifc_class("Door") == "IfcDoor"


def test_keyword_fallback_for_subcategories() -> None:
    # Custom family categories and sub-categories the exact table cannot
    # enumerate resolve through the ordered keyword heuristic. More specific
    # rules win over broader ones (a "Curtain Grids Wall" is a curtain wall,
    # not a plain wall; a "Stairs Railing Baluster" is a railing, not a stair).
    assert normalize_to_ifc_class("Curtain Grids Wall") == "IfcCurtainWall"
    assert normalize_to_ifc_class("Stairs Railing Baluster") == "IfcRailing"
    assert normalize_to_ifc_class("Wall Sweeps") == "IfcWall"
    assert normalize_to_ifc_class("Structural Framing - Joist") == "IfcBeam"
    assert normalize_to_ifc_class("Foundation Slab") == "IfcFooting"
    assert normalize_to_ifc_class("Floor Edges") == "IfcSlab"
    assert normalize_to_ifc_class("Roof Soffits") == "IfcRoof"
    assert normalize_to_ifc_class("Lighting Devices") == "IfcLightFixture"


def test_keyword_fallback_does_not_override_exact_table() -> None:
    # The exact table and plural/singular alias must always win before the
    # keyword heuristic runs, so a precise mapping is never weakened.
    assert normalize_to_ifc_class("Ceilings") == "IfcCovering"
    assert normalize_to_ifc_class("Structural Foundations") == "IfcFooting"


def test_keyword_fallback_returns_none_for_truly_unmappable() -> None:
    # No keyword present → still None, never a guess.
    assert normalize_to_ifc_class("Wire Insulations") is None
    assert normalize_to_ifc_class("Generic Annotations") is None
    assert normalize_to_ifc_class("Color Fill Legends") is None


def test_mapping_table_targets_are_all_ifc() -> None:
    # Defensive: every crosswalk target is a real IFC spelling so the
    # downstream ``ifc_labels.lookup`` / Qdrant filter always receives a
    # canonical class.
    assert OST_TO_IFC, "crosswalk must not be empty"
    for raw, ifc in OST_TO_IFC.items():
        assert ifc.startswith("Ifc"), f"{raw!r} maps to non-IFC {ifc!r}"
