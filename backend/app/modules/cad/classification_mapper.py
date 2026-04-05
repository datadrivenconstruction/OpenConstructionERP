# OpenConstructionERP — DataDrivenConstruction (DDC)
# CAD2DATA Pipeline · CWICR Cost Database Engine
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""Auto-map Revit/IFC categories to construction classification standards.

Provides deterministic mapping tables from common Revit family categories
and IFC entity types to DIN 276, NRM 1, and CSI MasterFormat codes.
These mappings are used as fallback/default classification when no AI or
vector search is available, and as confidence anchors for AI suggestions.

Supported standards:
    - DIN 276 (DACH region cost groups)
    - NRM 1 (UK New Rules of Measurement)
    - CSI MasterFormat (US/Canada division codes)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Revit Category -> DIN 276 KG mapping
# ---------------------------------------------------------------------------
REVIT_TO_DIN276: dict[str, str] = {
    "Walls": "330",
    "Floors": "350",
    "Roofs": "360",
    "Ceilings": "350",
    "Doors": "340",
    "Windows": "340",
    "Stairs": "340",
    "Columns": "330",
    "Structural Framing": "330",
    "Structural Foundations": "320",
    "Curtain Walls": "340",
    "Curtain Panels": "340",
    "Mechanical Equipment": "420",
    "Plumbing Fixtures": "410",
    "Electrical Equipment": "440",
    "Electrical Fixtures": "440",
    "Pipe Segments": "410",
    "Duct Segments": "420",
    "Cable Trays": "440",
    "Fire Protection": "450",
    "Railings": "340",
    "Ramps": "340",
    "Generic Models": "390",
    "Site": "200",
    "Topography": "210",
    "Parking": "250",
}

# ---------------------------------------------------------------------------
# Revit Category -> NRM 1 mapping
# ---------------------------------------------------------------------------
REVIT_TO_NRM: dict[str, str] = {
    "Walls": "2.5",
    "Floors": "2.3",
    "Roofs": "2.7",
    "Doors": "2.6",
    "Windows": "2.6",
    "Stairs": "2.4",
    "Columns": "2.1",
    "Structural Framing": "2.1",
    "Structural Foundations": "1.1",
    "Mechanical Equipment": "5.4",
    "Plumbing Fixtures": "5.3",
    "Electrical Equipment": "5.8",
}

# ---------------------------------------------------------------------------
# Revit Category -> CSI MasterFormat mapping
# ---------------------------------------------------------------------------
REVIT_TO_MASTERFORMAT: dict[str, str] = {
    "Walls": "04 00 00",
    "Floors": "03 30 00",
    "Roofs": "07 00 00",
    "Doors": "08 10 00",
    "Windows": "08 50 00",
    "Stairs": "03 40 00",
    "Columns": "03 30 00",
    "Structural Framing": "05 10 00",
    "Structural Foundations": "03 10 00",
    "Mechanical Equipment": "23 00 00",
    "Plumbing Fixtures": "22 40 00",
    "Electrical Equipment": "26 00 00",
}

# Unified lookup: standard name -> mapping table
_STANDARD_MAPPINGS: dict[str, dict[str, str]] = {
    "din276": REVIT_TO_DIN276,
    "nrm": REVIT_TO_NRM,
    "masterformat": REVIT_TO_MASTERFORMAT,
}


def map_category_to_standard(category: str, standard: str = "din276") -> str | None:
    """Map a Revit/IFC category to a classification code.

    Performs a case-sensitive lookup against the mapping table for the
    requested standard.

    Args:
        category: Revit category name (e.g. ``"Walls"``, ``"Doors"``).
        standard: Classification standard key — one of ``"din276"``,
            ``"nrm"``, or ``"masterformat"``.

    Returns:
        The classification code string, or ``None`` if no mapping exists
        for the given category/standard combination.
    """
    mapping = _STANDARD_MAPPINGS.get(standard, {})
    return mapping.get(category)


def map_elements_to_classification(
    elements: list[dict],
    standard: str = "din276",
) -> list[dict]:
    """Add classification codes to CAD elements based on their category.

    Iterates over a list of element dicts, looks up each element's
    ``"category"`` value in the mapping table for *standard*, and writes
    the resulting code into ``element["classification"][standard]``.

    Elements whose category has no mapping are left unchanged.
    Existing classification entries for *other* standards are preserved.

    Args:
        elements: List of element dicts, each expected to have a
            ``"category"`` key (e.g. ``"Walls"``).
        standard: Classification standard to apply — ``"din276"``,
            ``"nrm"``, or ``"masterformat"``.

    Returns:
        The same list of element dicts, mutated in place with
        classification codes added where a mapping was found.
    """
    for elem in elements:
        cat = elem.get("category", "")
        code = map_category_to_standard(cat, standard)
        if code:
            if "classification" not in elem:
                elem["classification"] = {}
            elem["classification"][standard] = code
    return elements


def get_supported_standards() -> list[str]:
    """Return the list of classification standards with mapping tables.

    Returns:
        List of standard key strings (e.g. ``["din276", "nrm", "masterformat"]``).
    """
    return list(_STANDARD_MAPPINGS.keys())


def get_mapping_table(standard: str) -> dict[str, str]:
    """Return the full category-to-code mapping table for a standard.

    Args:
        standard: Classification standard key.

    Returns:
        Dict mapping Revit category names to classification codes.
        Empty dict if the standard is not recognized.
    """
    return dict(_STANDARD_MAPPINGS.get(standard, {}))
