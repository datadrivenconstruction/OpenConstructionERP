# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Revit built-in category ids, as the RVT converter stores them, to names.

The stored graph carries ``category_id`` (a negative ``BuiltInCategory`` value),
never a name. The ``OST_`` name is what the platform's classification rules key
on; the display name is the one Revit shows in its own UI. Every id that occurs
in the sample models was checked against the name the DDC RVT converter writes
into its IFC export (``Revit_Identity.CategoryName``); the few others follow the
Revit API. An id not listed is labelled with its number, never guessed.
"""

from __future__ import annotations

#: ``category_id -> (OST_ name, display name)``.
REVIT_CATEGORIES: dict[int, tuple[str, str]] = {
    -2000011: ("OST_Walls", "Walls"),
    -2000014: ("OST_Windows", "Windows"),
    -2000023: ("OST_Doors", "Doors"),
    -2000032: ("OST_Floors", "Floors"),
    -2000035: ("OST_Roofs", "Roofs"),
    -2000038: ("OST_Ceilings", "Ceilings"),
    -2000080: ("OST_Furniture", "Furniture"),
    -2000100: ("OST_Columns", "Columns"),
    -2000120: ("OST_Stairs", "Stairs"),
    -2000123: ("OST_StairsStringerCarriage", "Stairs Supports"),
    -2000126: ("OST_StairsRailing", "Railings"),
    -2000127: ("OST_StairsRailingBaluster", "Balusters"),
    -2000151: ("OST_GenericModel", "Generic Models"),
    -2000160: ("OST_Rooms", "Rooms"),
    -2000170: ("OST_CurtainWallPanels", "Curtain Panels"),
    -2000171: ("OST_CurtainWallMullions", "Curtain Wall Mullions"),
    -2000180: ("OST_Ramps", "Ramps"),
    -2000181: ("OST_Cornices", "Wall Sweeps"),
    -2000220: ("OST_Grids", "Grids"),
    -2000240: ("OST_Levels", "Levels"),
    -2000269: ("OST_Parts", "Parts"),
    -2000919: ("OST_StairsRuns", "Stairs Runs"),
    -2000920: ("OST_StairsLandings", "Stairs Landings"),
    -2001000: ("OST_Casework", "Casework"),
    -2001040: ("OST_ElectricalEquipment", "Electrical Equipment"),
    -2001060: ("OST_ElectricalFixtures", "Electrical Fixtures"),
    -2001120: ("OST_LightingFixtures", "Lighting Fixtures"),
    -2001140: ("OST_MechanicalEquipment", "Mechanical Equipment"),
    -2001160: ("OST_PlumbingFixtures", "Plumbing Fixtures"),
    -2001180: ("OST_Parking", "Parking"),
    -2001263: ("OST_BuildingPad", "Building Pads"),
    -2001300: ("OST_StructuralFoundation", "Structural Foundations"),
    -2001320: ("OST_StructuralFraming", "Structural Framing"),
    -2001330: ("OST_StructuralColumns", "Structural Columns"),
    -2001340: ("OST_Topography", "Topography"),
    -2001350: ("OST_SpecialityEquipment", "Specialty Equipment"),
    -2001360: ("OST_Planting", "Planting"),
    -2001370: ("OST_Entourage", "Entourage"),
    -2001392: ("OST_EdgeSlab", "Slab Edges"),
    -2003400: ("OST_Mass", "Mass"),
    -2003600: ("OST_MEPSpaces", "MEP Spaces"),
    -2008000: ("OST_DuctCurves", "Ducts"),
    -2008010: ("OST_DuctFitting", "Duct Fittings"),
    -2008013: ("OST_DuctTerminal", "Air Terminals"),
    -2008016: ("OST_DuctAccessory", "Duct Accessories"),
    -2008020: ("OST_FlexDuctCurves", "Flex Ducts"),
    -2008044: ("OST_PipeCurves", "Pipes"),
    -2008049: ("OST_PipeFitting", "Pipe Fittings"),
    -2008050: ("OST_FlexPipeCurves", "Flex Pipes"),
    -2008055: ("OST_PipeAccessory", "Pipe Accessories"),
    -2008087: ("OST_LightingDevices", "Lighting Devices"),
    -2008099: ("OST_Sprinklers", "Sprinklers"),
    -2008126: ("OST_CableTrayFitting", "Cable Tray Fittings"),
    -2008128: ("OST_ConduitFitting", "Conduit Fittings"),
    -2008130: ("OST_CableTray", "Cable Trays"),
    -2008132: ("OST_Conduit", "Conduits"),
    -2009000: ("OST_Rebar", "Structural Rebar"),
}


def revit_category_name(category_id: int | None) -> str:
    """``OST_`` name of a category id; an unknown id is labelled with its number."""
    if category_id is None:
        return "OST_Unknown"
    known = REVIT_CATEGORIES.get(category_id)
    return known[0] if known else f"OST_Category{abs(category_id)}"


def revit_category_label(category_id: int | None) -> str:
    """Revit's display name of a category id; an unknown id reads ``Category <id>``."""
    if category_id is None:
        return "Unknown"
    known = REVIT_CATEGORIES.get(category_id)
    return known[1] if known else f"Category {category_id}"
