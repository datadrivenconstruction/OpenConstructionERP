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

import re

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


#: Further ``category_id -> OST_ name`` pairs, read off the same elements in the
#: 18.x converter's output. Their display name is the OST name split into words.
REVIT_OST_NAMES: dict[int, str] = {
    -2000045: "OST_SketchLines",
    -2000051: "OST_Lines",
    -2000066: "OST_RoomSeparationLines",
    -2000067: "OST_StairsSketchBoundaryLines",
    -2000068: "OST_StairsSketchRiserLines",
    -2000069: "OST_StairsSketchRunLines",
    -2000070: "OST_StairsSketchLandingCenterLines",
    -2000079: "OST_AreaSchemeLines",
    -2000091: "OST_IOSArrays",
    -2000095: "OST_IOSModelGroups",
    -2000096: "OST_IOSDetailGroups",
    -2000110: "OST_IOS_GeoLocations",
    -2000111: "OST_IOS_GeoSite",
    -2000112: "OST_Phases",
    -2000150: "OST_GenericAnnotation",
    -2000182: "OST_Reveals",
    -2000193: "OST_Matchline",
    -2000264: "OST_SpotCoordinates",
    -2000278: "OST_Views",
    -2000279: "OST_Views",
    -2000291: "OST_Divisions",
    -2000301: "OST_SectionBox",
    -2000320: "OST_CurtainGridsRoof",
    -2000321: "OST_CurtainGridsWall",
    -2000340: "OST_CurtaSystem",
    -2000400: "OST_SectionHeads",
    -2000460: "OST_DoorTags",
    -2000485: "OST_MEPSpaceTags",
    -2000530: "OST_CLines",
    -2000535: "OST_Elev",
    -2000538: "OST_CalloutHeads",
    -2000550: "OST_ColorFillLegends",
    -2000560: "OST_RasterImages",
    -2000570: "OST_ScheduleGraphics",
    -2000573: "OST_Schedules",
    -2000575: "OST_LegendComponents",
    -2000576: "OST_PreviewLegendComponents",
    -2000700: "OST_Materials",
    -2000710: "OST_ReferencePoints",
    -2000831: "OST_MEPSpaceSeparationLines",
    -2000921: "OST_StairsTrisers",
    -2000930: "OST_StairsCutMarks",
    -2000938: "OST_StairsPaths",
    -2000946: "OST_RailingTopRail",
    -2000947: "OST_RailingHandRail",
    -2000948: "OST_RailingSupport",
    -2000970: "OST_MultiReferenceAnnotations",
    -2000977: "OST_CoordinateSystem",
    -2000980: "OST_MultistoryStairs",
    -2000985: "OST_MechanicalEquipmentSet",
    -2000996: "OST_ShaftOpening",
    -2000997: "OST_SWallRectOpening",
    -2001265: "OST_SiteProperty",
    -2001268: "OST_SitePropertyLineSegment",
    -2001269: "OST_SitePropertyLineSegmentTags",
    -2001271: "OST_ProjectBasePoint",
    -2001272: "OST_SharedBasePoint",
    -2001327: "OST_StructuralFramingSystem",
    -2001342: "OST_TopographyContours",
    -2001352: "OST_RvtLinks",
    -2001390: "OST_Fascia",
    -2001391: "OST_Gutter",
    -2001393: "OST_RoofSoffit",
    -2002000: "OST_DetailComponents",
    -2003000: "OST_ProfileFamilies",
    -2003100: "OST_Sheets",
    -2003101: "OST_ProjectInformation",
    -2003200: "OST_Areas",
    -2003201: "OST_AreaSchemes",
    -2003331: "OST_TilePatterns",
    -2003403: "OST_MassFloor",
    -2003404: "OST_MassForm",
    -2003414: "OST_MassRoof",
    -2003417: "OST_MassOpening",
    -2003418: "OST_MassShade",
    -2003421: "OST_MassWallsAll",
    -2003422: "OST_MassFloorsAll",
    -2003423: "OST_MassGlazingAll",
    -2003500: "OST_StackedWalls",
    -2005009: "OST_MechanicalEquipmentTags",
    -2005020: "OST_AreaTags",
    -2005027: "OST_MaterialTags",
    -2005029: "OST_KeynoteTags",
    -2005100: "OST_SpotElevSymbols",
    -2005202: "OST_LineLoads",
    -2005203: "OST_AreaLoads",
    -2005301: "OST_BoundaryConditions",
    -2006020: "OST_LevelHeads",
    -2006040: "OST_GridHeads",
    -2006045: "OST_ElevationMarks",
    -2006060: "OST_RevisionClouds",
    -2006070: "OST_Revisions",
    -2006080: "OST_RevisionCloudTags",
    -2006112: "OST_DesignOptionSets",
    -2006114: "OST_DesignOptions",
    -2008001: "OST_DuctCurves",
    -2008003: "OST_DuctTags",
    -2008004: "OST_FlexDuctTags",
    -2008014: "OST_DuctTerminalTags",
    -2008015: "OST_DuctSystem",
    -2008021: "OST_FlexDuctCurves",
    -2008037: "OST_ElectricalCircuit",
    -2008039: "OST_Wire",
    -2008040: "OST_ElectricalVoltage",
    -2008041: "OST_ElecDistributionSys",
    -2008043: "OST_PipingSystem",
    -2008045: "OST_PipeCurves",
    -2008047: "OST_PipeTags",
    -2008066: "OST_DuctFitting",
    -2008072: "OST_PipeFitting",
    -2008102: "OST_EAConstructions",
    -2008103: "OST_PipeConnections",
    -2008104: "OST_PipeMaterials",
    -2008105: "OST_PipeSchedules",
    -2008106: "OST_Fluids",
    -2008107: "OST_HVAC_Zones",
    -2008111: "OST_WireMaterials",
    -2008112: "OST_WireInsulations",
    -2008113: "OST_WireTemperatureRatings",
    -2008119: "OST_HVAC_Load_Space_Types",
    -2008120: "OST_HVAC_Load_Building_Types",
    -2008121: "OST_HVAC_Load_Schedules",
    -2008122: "OST_PipeInsulations",
    -2008123: "OST_DuctInsulations",
    -2008124: "OST_DuctLinings",
    -2008139: "OST_Conduit",
    -2008141: "OST_ConduitFitting",
    -2008142: "OST_ElectricalDemandFactorDefinitions",
    -2008143: "OST_ElectricalLoadClassifications",
    -2008144: "OST_ConduitStandards",
    -2008145: "OST_BranchPanelScheduleTemplates",
    -2008146: "OST_SwitchboardScheduleTemplates",
    -2008147: "OST_DataPanelScheduleTemplates",
    -2008148: "OST_ParamElemElectricalLoadClassification",
    -2008149: "OST_ConduitRun",
    -2008163: "OST_PipeSegments",
    -2008165: "OST_DivisionProfile",
    -2008190: "OST_DivisionRules",
    -2009003: "OST_AreaRein",
    -2009014: "OST_CoverType",
    -2009016: "OST_FabricReinforcement",
    -2009017: "OST_FabricAreas",
    -2009609: "OST_SunStudy",
    -2009630: "OST_BeamAnalytical",
    -2009636: "OST_ColumnAnalytical",
    -2009639: "OST_FloorAnalytical",
    -2009640: "OST_WallAnalytical",
    -2009641: "OST_IsolatedFoundationAnalytical",
    -2009642: "OST_WallFoundationAnalytical",
}


def revit_category_name(category_id: int | None, display_name: str | None = None) -> str:
    """``OST_`` name of a category id.

    An id outside the table falls back to the converter's display name, then to
    the signed number; never to an invented ``OST_`` name.
    """
    known = REVIT_CATEGORIES.get(category_id) if category_id is not None else None
    if known:
        return known[0]
    ost = REVIT_OST_NAMES.get(category_id) if category_id is not None else None
    if ost:
        return ost
    if display_name:
        return display_name
    return "OST_Unknown" if category_id is None else f"Category {category_id}"


def revit_category_label(category_id: int | None) -> str:
    """Revit's display name of a category id; an unknown id reads ``Category <id>``."""
    if category_id is None:
        return "Unknown"
    known = REVIT_CATEGORIES.get(category_id)
    if known:
        return known[1]
    ost = REVIT_OST_NAMES.get(category_id)
    if ost is None:
        return f"Category {category_id}"
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", ost[4:])
    return re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", words).replace("_", " ").strip()
