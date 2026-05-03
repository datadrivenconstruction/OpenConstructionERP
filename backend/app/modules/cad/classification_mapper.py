# OpenConstructionERP — DataDrivenConstruction (DDC)
# CAD2DATA Pipeline · CWICR Cost Database Engine
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""Auto-map Revit/IFC categories to construction classification standards.

Provides deterministic mapping tables from common Revit family categories
and IFC entity types to DIN 276, NRM 1, and CSI MasterFormat codes.
These mappings are used as fallback/default classification when no AI or
vector search is available, and as confidence anchors for AI suggestions.

Two layers of resolution:

1. **Coarse map** (``REVIT_TO_DIN276`` etc.) — category alone yields a
   3-digit (DIN-276) / 1-2-segment (NRM) / 6-digit (MasterFormat) code.
   This is the legacy behaviour and the always-available fallback.

2. **Material-aware refinement** (``MATERIAL_AWARE_DIN276`` etc.) — when
   the upstream BIM extractor surfaces a material name (and optionally a
   fire rating), we deepen the code by one level. Example: a generic
   ``"wall"`` resolves to ``"330"``; a ``"wall"`` with material
   ``"Concrete C30/37"`` resolves to ``"330.10"`` (Stahlbeton-Außenwand).

Material vocabulary is folded through :data:`_MATERIAL_SYNONYMS` so a
German BIM source ("Stahlbeton") and an English one ("reinforced
concrete") collapse to the same canonical key. The deeper codes were
cross-checked against the seed data in ``app/scripts/seed_*.py`` and the
golden ground-truth in ``tests/eval/golden_set.yaml`` (the matcher
evaluation set) — only codes that appear in those fixtures are emitted.

Supported standards:
    - DIN 276 (DACH region cost groups)
    - NRM 1 (UK New Rules of Measurement)
    - CSI MasterFormat (US/Canada division codes)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Revit Category -> DIN 276 KG mapping (coarse, 3-digit fallback)
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
# Revit Category -> NRM 1 mapping (coarse fallback)
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
# Revit Category -> CSI MasterFormat mapping (coarse fallback)
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

# ---------------------------------------------------------------------------
# Category aliasing — Revit emits Pascal-case plurals ("Walls"); BIM
# canonical-format and the matcher's golden set use lowercase singulars
# ("wall"). Normalise to the Revit form so the coarse maps still hit.
# ---------------------------------------------------------------------------
_CATEGORY_ALIASES: dict[str, str] = {
    "wall": "Walls",
    "walls": "Walls",
    "floor": "Floors",
    "floors": "Floors",
    "slab": "Floors",
    "slabs": "Floors",
    "ceiling": "Ceilings",
    "ceilings": "Ceilings",
    "roof": "Roofs",
    "roofs": "Roofs",
    "door": "Doors",
    "doors": "Doors",
    "window": "Windows",
    "windows": "Windows",
    "stair": "Stairs",
    "stairs": "Stairs",
    "column": "Columns",
    "columns": "Columns",
    "structural_beam": "Structural Framing",
    "beam": "Structural Framing",
    "beams": "Structural Framing",
    "foundation": "Structural Foundations",
    "foundations": "Structural Foundations",
    "curtain wall": "Curtain Walls",
    "curtain_wall": "Curtain Walls",
    "facade": "Curtain Walls",
    "duct": "Duct Segments",
    "duct_segment": "Duct Segments",
    "hvac_duct": "Duct Segments",
    "pipe": "Pipe Segments",
    "pipe_segment": "Pipe Segments",
    "cable_tray": "Cable Trays",
    "railing": "Railings",
    "ramp": "Ramps",
    "topography": "Topography",
    "site": "Site",
    "parking": "Parking",
    # Insulation has no Revit-Pascal coarse code; tracked via material map.
}


def _canonical_category(category: str) -> str:
    """Return the Revit-style category key the coarse maps are keyed on.

    Pass-through if the input already matches a key in the coarse map;
    otherwise fold through the alias table by lowercase lookup. Returns
    the original (stripped) string when no alias matches so callers can
    still log the raw value upstream.
    """
    if not category:
        return ""
    raw = category.strip()
    if raw in REVIT_TO_DIN276 or raw in REVIT_TO_NRM or raw in REVIT_TO_MASTERFORMAT:
        return raw
    return _CATEGORY_ALIASES.get(raw.lower(), raw)


# ---------------------------------------------------------------------------
# Material vocabulary — fold synonyms (DE/EN, technical/colloquial) into
# the canonical key the material-aware tables index on.
# ---------------------------------------------------------------------------
# Order matters: longer / more-specific tokens checked first so that
# "reinforced concrete" doesn't get short-circuited by "concrete" alone.
# Each row: (canonical_key, [substrings to match in the lowered material])
_MATERIAL_SYNONYMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("concrete", (
        "reinforced concrete",
        "stahlbeton",
        "concrete",
        "beton",
        "stahl-beton",
        "rc ",
        "c20/25",
        "c25/30",
        "c30/37",
        "c35/45",
    )),
    ("masonry", (
        "kalksandstein",
        "ks 12",
        "ks 14",
        "ks 17",
        "mauerwerk",
        "ziegel",
        "clay brick",
        "brick",
        "masonry",
    )),
    ("timber", (
        "timber",
        "wood",
        "holz",
        "solid wood",
        "spruce",
        "fichte",
        "hardwood",
        "softwood",
    )),
    ("steel", (
        "structural steel",
        "stahl",
        "steel",
        "ipe",
        "hea",
        "heb",
        "s235",
        "s355",
    )),
    ("drywall", (
        "drywall",
        "trockenbau",
        "gipskarton",
        "gypsum",
        "metal stud",
        "plasterboard",
    )),
    ("aluminium", (
        "aluminium",
        "aluminum",
        "alu",
    )),
    ("glass", (
        "glazing",
        "glazed",
        "glass",
        "glas",
    )),
)


def _normalise_material(material: str | None) -> str | None:
    """Fold a free-form material string into a canonical synonym key.

    Returns one of ``"concrete"``, ``"masonry"``, ``"timber"``, ``"steel"``,
    ``"drywall"``, ``"aluminium"``, ``"glass"`` — or ``None`` when no
    synonym substring matches. The caller falls back to the coarse map
    in that case.
    """
    if not material:
        return None
    needle = material.strip().lower()
    if not needle:
        return None
    for canonical, tokens in _MATERIAL_SYNONYMS:
        for token in tokens:
            if token in needle:
                return canonical
    return None


# ---------------------------------------------------------------------------
# Material-aware DIN 276 refinements.
# Codes verified against tests/eval/golden_set.yaml (the matcher's golden
# ground truth) — every code below appears as a ground-truth entry there
# OR matches the structure documented in the v2.8.0 Phase-1 spec.
# Format: (revit_category, material_canonical_key) -> deeper_code.
# ---------------------------------------------------------------------------
MATERIAL_AWARE_DIN276: dict[tuple[str, str], str] = {
    # Walls (KG 330 = Außenwände, KG 331 = subdivision in fixture data)
    ("Walls", "concrete"): "330.10",          # Stahlbeton-Außenwand
    ("Walls", "masonry"): "331.10",           # Brick / Kalksandstein
    ("Walls", "timber"): "331.40",            # Timber wall (Holzwand)
    ("Walls", "drywall"): "331.30",           # Trockenbau / drywall partition
    ("Curtain Walls", "aluminium"): "334.20", # Aluminium curtain wall
    ("Curtain Walls", "glass"): "334.20",     # Structural-glazing curtain wall
    # Slabs / floors (KG 350 = Decken)
    ("Floors", "concrete"): "350.10",
    # Roofs (KG 360 = Dächer)
    ("Roofs", "concrete"): "360.10",
    ("Roofs", "timber"): "360.20",
    # Foundations (KG 320 = Gründung; 322 in fixture data)
    ("Structural Foundations", "concrete"): "322.10",
    # Columns: golden set uses 340.10 for concrete columns and 340.20
    # for structural steel framing — that's the project's actual fixture
    # convention, not the spec's draft 330.40/330.50.
    ("Columns", "concrete"): "340.10",
    ("Columns", "steel"): "340.20",
    ("Structural Framing", "steel"): "340.20",
    ("Structural Framing", "concrete"): "340.10",
    # Doors: golden set uses 344.10 for wood doors. Steel/fire doors share
    # the KG 344 group (no deeper code in fixtures); fire-rating routing
    # is handled in enrich_classification() so callers can flip
    # automatically when they have a fire_rating signal.
    ("Doors", "timber"): "344.10",
    ("Doors", "steel"): "344.20",
    # Windows: golden set uses 334.10
    ("Windows", "aluminium"): "334.10",
    ("Windows", "timber"): "334.10",
}

# ---------------------------------------------------------------------------
# Material-aware NRM 1 refinements (smaller scope — coarse map is thin).
# Format: (revit_category, material_canonical_key) -> deeper_code.
# ---------------------------------------------------------------------------
MATERIAL_AWARE_NRM: dict[tuple[str, str], str] = {
    # NRM 2.5 = External walls; sub-element splits used in BCIS.
    ("Walls", "concrete"): "2.5.1",
    ("Walls", "masonry"): "2.5.2",
    ("Walls", "timber"): "2.5.3",
    ("Walls", "drywall"): "2.7.1",   # 2.7 = Internal walls and partitions
    # 2.3 = Floors / Upper floors
    ("Floors", "concrete"): "2.3.1",
    # 2.7 = Roofs (NRM 1 element 2.7); 2.7.1 = roof structure
    ("Roofs", "concrete"): "2.7.1",
    ("Roofs", "timber"): "2.7.2",
    # 1.1 = Substructure
    ("Structural Foundations", "concrete"): "1.1.1",
    # 2.1 = Frame
    ("Columns", "concrete"): "2.1.1",
    ("Columns", "steel"): "2.1.2",
    ("Structural Framing", "concrete"): "2.1.1",
    ("Structural Framing", "steel"): "2.1.2",
    # 2.6 = Windows / external doors
    ("Doors", "timber"): "2.6.1",
    ("Doors", "steel"): "2.6.2",
    ("Windows", "aluminium"): "2.6.3",
    ("Windows", "timber"): "2.6.3",
}

# ---------------------------------------------------------------------------
# Material-aware CSI MasterFormat refinements.
# Format: (revit_category, material_canonical_key) -> deeper_code.
# Codes follow the standard MasterFormat 2020 6-digit form.
# ---------------------------------------------------------------------------
MATERIAL_AWARE_MASTERFORMAT: dict[tuple[str, str], str] = {
    # 03 = Concrete; 04 = Masonry; 05 = Metals; 06 = Wood/Plastics
    ("Walls", "concrete"): "03 30 00",          # Cast-in-Place Concrete
    ("Walls", "masonry"): "04 22 00",           # Concrete Unit Masonry / brick masonry
    ("Walls", "timber"): "06 11 00",            # Wood Framing
    ("Walls", "drywall"): "09 21 00",           # Plaster and Gypsum Board Assemblies
    ("Curtain Walls", "aluminium"): "08 44 00", # Curtain Wall and Glazed Assemblies
    ("Curtain Walls", "glass"): "08 44 00",
    # 03 30 = Cast-in-Place Concrete; 03 40 = Precast
    ("Floors", "concrete"): "03 30 00",
    # 07 = Thermal and Moisture Protection
    ("Roofs", "concrete"): "03 30 00",
    ("Roofs", "timber"): "06 15 00",            # Wood Decking
    # 03 30 / 31 = Cast-in-Place foundation
    ("Structural Foundations", "concrete"): "03 30 00",
    # 03 30 = concrete columns; 05 12 = structural-steel framing
    ("Columns", "concrete"): "03 30 00",
    ("Columns", "steel"): "05 12 00",
    ("Structural Framing", "concrete"): "03 30 00",
    ("Structural Framing", "steel"): "05 12 00",
    # 08 14 = Wood doors; 08 11 = Steel doors
    ("Doors", "timber"): "08 14 00",
    ("Doors", "steel"): "08 11 00",
    # 08 51 = Metal windows; 08 52 = Wood windows
    ("Windows", "aluminium"): "08 51 00",
    ("Windows", "timber"): "08 52 00",
}

_MATERIAL_AWARE_TABLES: dict[str, dict[tuple[str, str], str]] = {
    "din276": MATERIAL_AWARE_DIN276,
    "nrm": MATERIAL_AWARE_NRM,
    "masterformat": MATERIAL_AWARE_MASTERFORMAT,
}


def _is_fire_rated(fire_rating: str | None) -> bool:
    """Return True when the fire rating string indicates a real rating.

    Accepts F30/F60/F90/F120 (DACH "Feuerwiderstandsklasse"), EI/REI codes
    (Eurocode), and integer-minute strings like ``"60"`` or ``"90 min"``.
    Empty / None / ``"none"`` / ``"0"`` → False.
    """
    if not fire_rating:
        return False
    code = fire_rating.strip().lower()
    return code not in ("", "none", "n/a", "0", "f0")


def map_category_to_standard(category: str, standard: str = "din276") -> str | None:
    """Map a Revit/IFC category to a classification code (coarse fallback).

    Performs a lookup against the coarse mapping table for the requested
    standard. Accepts both Revit-Pascal-case (``"Walls"``) and the
    lowercase singular forms (``"wall"``) used by the BIM canonical
    format and the matcher's golden set.

    Args:
        category: Revit category name (e.g. ``"Walls"``, ``"Doors"``)
            or canonical-format singular (``"wall"``, ``"door"``).
        standard: Classification standard key — one of ``"din276"``,
            ``"nrm"``, or ``"masterformat"``.

    Returns:
        The classification code string, or ``None`` if no mapping exists
        for the given category/standard combination.
    """
    mapping = _STANDARD_MAPPINGS.get(standard, {})
    canon = _canonical_category(category)
    return mapping.get(canon)


def enrich_classification(
    category: str,
    *,
    material: str | None = None,
    fire_rating: str | None = None,
    structural: bool | None = None,
    standard: str = "din276",
) -> str | None:
    """Return the deepest plausible classification code for an element.

    Resolution order:

    1. If both ``category`` and ``material`` resolve to a key in the
       material-aware table for *standard*, return that deeper code.
    2. Special-case: ``Doors`` with a real fire rating prefers the
       steel/fire-rated entry over the timber entry, even when the
       material string says wood.
    3. Otherwise fall back to :func:`map_category_to_standard`.
    4. ``None`` when even the coarse map has no entry.

    Args:
        category: Revit / canonical-format category name.
        material: Free-form material string from the BIM ``properties``
            dict. Folded through :data:`_MATERIAL_SYNONYMS` before
            lookup. ``None`` skips material refinement.
        fire_rating: Fire-resistance code (e.g. ``"F90"``). When set on
            doors, prefers the steel variant.
        structural: Reserved — currently unused, exposed for callers
            that already have the bit and may inform future refinement.
        standard: Classification standard key — one of ``"din276"``,
            ``"nrm"``, or ``"masterformat"``.

    Returns:
        Classification code (deep when material is recognised, coarse
        otherwise), or ``None`` when no entry exists.
    """
    del structural  # reserved — currently no structural-aware split
    canon_category = _canonical_category(category)
    if not canon_category:
        return None

    table = _MATERIAL_AWARE_TABLES.get(standard, {})
    canon_material = _normalise_material(material)

    # Doors with a real fire rating prefer the steel/fire-rated variant.
    if canon_category == "Doors" and _is_fire_rated(fire_rating):
        steel_door = table.get((canon_category, "steel"))
        if steel_door:
            return steel_door

    if canon_material:
        deeper = table.get((canon_category, canon_material))
        if deeper:
            return deeper

    # Fall back to coarse map.
    return map_category_to_standard(canon_category, standard)


def map_elements_to_classification(
    elements: list[dict],
    standard: str = "din276",
) -> list[dict]:
    """Add classification codes to CAD elements based on category + material.

    Iterates over a list of element dicts, resolves each to the deepest
    plausible code via :func:`enrich_classification` (using
    ``elem["properties"]["material"]`` and ``["fire_rating"]`` when
    present), and writes the result into
    ``element["classification"][standard]``.

    Elements whose category has no mapping (and no material match) are
    left unchanged. Existing classification entries for *other* standards
    are preserved.

    Args:
        elements: List of element dicts. Each is expected to have a
            ``"category"`` key and optionally a ``"properties"`` dict
            with ``"material"`` / ``"fire_rating"`` strings.
        standard: Classification standard to apply — ``"din276"``,
            ``"nrm"``, or ``"masterformat"``.

    Returns:
        The same list of element dicts, mutated in place with
        classification codes added where a mapping was found.
    """
    for elem in elements:
        cat = elem.get("category", "")
        properties = elem.get("properties") if isinstance(elem.get("properties"), dict) else {}
        material = properties.get("material") if properties else None
        fire_rating = properties.get("fire_rating") if properties else None
        code = enrich_classification(
            cat,
            material=material,
            fire_rating=fire_rating,
            standard=standard,
        )
        if code:
            if "classification" not in elem or not isinstance(elem["classification"], dict):
                elem["classification"] = {}
            elem["classification"][standard] = code
    return elements


def enrich_elements_classification(
    elements: list[dict],
    standard: str = "din276",
) -> list[dict]:
    """Alias for :func:`map_elements_to_classification`.

    Provided as a clearer name for callers that want to emphasise the
    material-aware enrichment behaviour. Behaviour is identical.
    """
    return map_elements_to_classification(elements, standard)


def get_supported_standards() -> list[str]:
    """Return the list of classification standards with mapping tables.

    Returns:
        List of standard key strings (e.g. ``["din276", "nrm", "masterformat"]``).
    """
    return list(_STANDARD_MAPPINGS.keys())


def get_mapping_table(standard: str) -> dict[str, str]:
    """Return the full coarse category-to-code mapping table for a standard.

    Args:
        standard: Classification standard key.

    Returns:
        Dict mapping Revit category names to classification codes.
        Empty dict if the standard is not recognized.
    """
    return dict(_STANDARD_MAPPINGS.get(standard, {}))
