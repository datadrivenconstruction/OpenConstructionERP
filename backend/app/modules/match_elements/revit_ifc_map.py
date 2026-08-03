# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RVT OST category to canonical IFC class crosswalk.

DDC cad2data extracts RVT elements with their native RVT
*OmniClass / Object Style Type* (OST) category name, e.g. ``"Walls"``,
``"Floors"``, ``"Structural Columns"`` - not an IFC entity. The
match-elements pipeline keys all of its label / standards / trade
metadata (:mod:`app.modules.match_elements.ifc_labels`) and its Qdrant
``ifc_class`` hard filter off the canonical IFC class name
(``"IfcWall"`` / ``"IfcSlab"`` ...).

Without a crosswalk, an RVT model never resolves to an IFC class:
``ifc_labels.lookup("Walls")`` falls through to the bare ``Ifc``-strip
fallback (no din276 / masterformat / nrm hint), and the envelope's
``ifc_class`` is never forwarded (it does not start with ``"Ifc"``). The
result is low-quality matches for walls and *zero* candidates for floors
/ roofs / ceilings.

This module is the single source of truth for that mapping. It is pure
Python with no DB import so it can be used from the source adapter, the
label lookup and the envelope builder alike.

The mapping is intentionally conservative: :func:`normalize_to_ifc_class`
returns ``None`` for an unknown category rather than guessing, so the
caller keeps the raw category and degrades gracefully instead of pinning
the Qdrant filter to a wrong class.
"""

from __future__ import annotations

import re

# Canonical RVT OST category (as DDC cad2data surfaces it) → IFC class.
#
# Keys are stored in their normalized form (see ``_normalize_key``):
# lower-case, ``"OST_"`` prefix stripped, trailing whitespace removed.
# Both the plural RVT category ("Walls") and the singular family-tier
# spelling ("Wall", "Basic Wall") are listed so we never depend on the
# extractor's pluralisation. Lookups also try a singular/plural fallback
# (see :func:`normalize_to_ifc_class`).
OST_TO_IFC: dict[str, str] = {
    # ── Architectural envelope ───────────────────────────────────────
    "walls": "IfcWall",
    "wall": "IfcWall",
    "basic wall": "IfcWall",
    "stacked wall": "IfcWall",
    "curtain wall": "IfcCurtainWall",
    "curtain walls": "IfcCurtainWall",
    "curtain panel": "IfcCurtainWall",
    "curtain panels": "IfcCurtainWall",
    "curtain wall panels": "IfcCurtainWall",
    "curtain system": "IfcCurtainWall",
    "curtain systems": "IfcCurtainWall",
    "curtain wall mullions": "IfcCurtainWall",
    "floors": "IfcSlab",
    "floor": "IfcSlab",
    "mass floors": "IfcSlab",
    "mass floor": "IfcSlab",
    "structural floors": "IfcSlab",
    "roofs": "IfcRoof",
    "roof": "IfcRoof",
    "ceilings": "IfcCovering",
    "ceiling": "IfcCovering",
    "doors": "IfcDoor",
    "door": "IfcDoor",
    "windows": "IfcWindow",
    "window": "IfcWindow",
    "stairs": "IfcStair",
    "stair": "IfcStair",
    "railings": "IfcRailing",
    "railing": "IfcRailing",
    "ramps": "IfcRamp",
    "ramp": "IfcRamp",
    # ── Structural ───────────────────────────────────────────────────
    "structural columns": "IfcColumn",
    "structural column": "IfcColumn",
    "columns": "IfcColumn",
    "column": "IfcColumn",
    "structural framing": "IfcBeam",
    "framing": "IfcBeam",
    "beams": "IfcBeam",
    "beam": "IfcBeam",
    "structural foundations": "IfcFooting",
    "structural foundation": "IfcFooting",
    "foundations": "IfcFooting",
    "foundation": "IfcFooting",
    # ── MEP - plumbing / piping ──────────────────────────────────────
    "pipes": "IfcPipeSegment",
    "pipe": "IfcPipeSegment",
    "pipe segments": "IfcPipeSegment",
    "plumbing fixtures": "IfcSanitaryTerminal",
    "plumbing fixture": "IfcSanitaryTerminal",
    # ── MEP - HVAC / ducting ─────────────────────────────────────────
    "ducts": "IfcDuctSegment",
    "duct": "IfcDuctSegment",
    "duct segments": "IfcDuctSegment",
    "mechanical equipment": "IfcUnitaryEquipment",
    # ── MEP - electrical ─────────────────────────────────────────────
    "cable trays": "IfcCableCarrierSegment",
    "cable tray": "IfcCableCarrierSegment",
    "conduits": "IfcCableCarrierSegment",
    "conduit": "IfcCableCarrierSegment",
    "lighting fixtures": "IfcLightFixture",
    "lighting fixture": "IfcLightFixture",
    "electrical fixtures": "IfcElectricAppliance",
    "electrical fixture": "IfcElectricAppliance",
    "electrical equipment": "IfcDistributionElement",
    "lighting devices": "IfcLightFixture",
    "lighting device": "IfcLightFixture",
    # Revit splits detection/notification hardware out of "Electrical
    # Fixtures" into its own discipline categories. ifc_labels already
    # carries IfcAlarm (mep / DIN276 474) and IfcCommunicationsAppliance
    # (mep / 445); without these keys an electrical model's fire-alarm and
    # comms devices resolved to None and lost their trade + cost hints.
    "fire alarm devices": "IfcAlarm",
    "fire alarm device": "IfcAlarm",
    "communication devices": "IfcCommunicationsAppliance",
    "communication device": "IfcCommunicationsAppliance",
    "data devices": "IfcCommunicationsAppliance",
    "data device": "IfcCommunicationsAppliance",
    "telephone devices": "IfcCommunicationsAppliance",
    "telephone device": "IfcCommunicationsAppliance",
    "nurse call devices": "IfcCommunicationsAppliance",
    "nurse call device": "IfcCommunicationsAppliance",
    # NOTE: Revit "Security Devices" is deliberately NOT mapped. The
    # category mixes cameras (IfcAudioVisualAppliance), door contacts
    # (IfcSensor) and panic buttons (IfcAlarm), so any single class would
    # be wrong for most of its instances. Callers keep the raw category.
    # ── Furniture / casework / generic ───────────────────────────────
    "furniture": "IfcFurniture",
    "casework": "IfcFurniture",
    "generic models": "IfcBuildingElementProxy",
    "generic model": "IfcBuildingElementProxy",
    # ── Spatial / site ───────────────────────────────────────────────
    "topography": "IfcSite",
    "parking": "IfcSpace",
    "rooms": "IfcSpace",
    "room": "IfcSpace",
    # MEP "Spaces" are the analytical twin of architectural Rooms and map
    # to the same IFC entity.
    "spaces": "IfcSpace",
    "space": "IfcSpace",
    "areas": "IfcSpace",
    "area": "IfcSpace",
}


# Splits CamelCase boundaries: "StructuralColumns" -> "Structural Columns",
# while leaving runs of capitals/digits ("DN", "C30") joined.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _normalize_key(raw: str) -> str:
    """Canonicalise a raw category string for :data:`OST_TO_IFC` lookup.

    Strips a leading ``"OST_"`` RVT prefix (case-insensitive), splits
    CamelCase identifiers into words, collapses internal
    whitespace/underscores to single spaces and lower-cases the result so
    ``"OST_StructuralColumns"`` and ``"Structural Columns"`` resolve
    identically.
    """
    s = raw.strip()
    if s[:4].lower() == "ost_":
        s = s[4:]
    # RVT enum-style OST identifiers are CamelCase with no separators
    # ("OST_StructuralColumns"); cad2data category labels use spaces. Split
    # CamelCase so both shapes normalise to the same spaced key.
    s = _CAMEL_BOUNDARY.sub(" ", s)
    s = s.replace("_", " ")
    s = " ".join(s.split())
    return s.lower()


# Ordered keyword fallback for RVT categories NOT in OST_TO_IFC - custom
# family categories and sub-categories such as "Curtain Grids Wall", "Stairs
# Railing Baluster" or "Structural Framing - Joist". Checked top to bottom on
# the spaced, lower-cased key; the FIRST rule whose keyword appears wins, so
# more specific rules (curtain wall, railing, foundation) sit above broader
# ones (wall, slab). Returns None when nothing matches, so a genuinely
# unmappable category stays un-normalized rather than being mis-mapped.
_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("curtain",), "IfcCurtainWall"),
    (("railing", "baluster", "handrail", "guardrail"), "IfcRailing"),
    (("stair",), "IfcStair"),
    (("ramp",), "IfcRamp"),
    (("door",), "IfcDoor"),
    (("window",), "IfcWindow"),
    (("roof",), "IfcRoof"),
    (("ceiling", "soffit"), "IfcCovering"),
    (("foundation", "footing", "pile cap", "pilecap"), "IfcFooting"),
    (("floor", "slab", "decking"), "IfcSlab"),
    (("column", "pier"), "IfcColumn"),
    (("beam", "framing", "joist", "truss", "girder", "purlin"), "IfcBeam"),
    (("wall",), "IfcWall"),
    (("duct",), "IfcDuctSegment"),
    (("pipe", "plumbing", "sprinkler"), "IfcPipeSegment"),
    (("conduit", "cable tray", "cabletray", "cable carrier"), "IfcCableCarrierSegment"),
    (("lighting", "luminaire", "light fixture"), "IfcLightFixture"),
    (("furniture", "casework", "furnishing", "millwork"), "IfcFurniture"),
]


def _keyword_fallback(key: str) -> str | None:
    """Best-effort keyword match for categories missing from :data:`OST_TO_IFC`.

    ``key`` is the spaced, lower-cased output of :func:`_normalize_key`. Used
    only after the exact table and the plural/singular alias both miss.
    """
    for keywords, ifc in _KEYWORD_RULES:
        if any(kw in key for kw in keywords):
            return ifc
    return None


def normalize_to_ifc_class(raw: str | None) -> str | None:
    """Map a raw RVT OST category to its canonical IFC class.

    Args:
        raw: An RVT category / object-style name as surfaced by the DDC
            cad2data extractor (e.g. ``"Walls"``, ``"Structural
            Columns"``, ``"OST_Walls"``). May already be an IFC class
            name (``"IfcWall"``).

    Returns:
        The canonical ``IfcXxx`` class name, or ``None`` when the
        category is unknown. Never guesses.

    The function is idempotent for genuine IFC inputs: a value that
    already starts with ``"Ifc"`` is returned unchanged so an IFC model
    is never re-mapped.
    """
    if not raw:
        return None
    raw_stripped = raw.strip()
    if not raw_stripped:
        return None
    # Genuine IFC class - pass through unchanged (idempotent).
    if raw_stripped[:3].lower() == "ifc":
        return raw_stripped
    key = _normalize_key(raw_stripped)
    if not key:
        return None
    mapped = OST_TO_IFC.get(key)
    if mapped is not None:
        return mapped
    # Tolerate a plural/singular spelling the table didn't list.
    if key.endswith("s"):
        alt = OST_TO_IFC.get(key[:-1])
        if alt is not None:
            return alt
    else:
        alt = OST_TO_IFC.get(key + "s")
        if alt is not None:
            return alt
    # Last resort: keyword heuristic for the RVT long tail (custom and
    # sub-category names the exact table cannot enumerate).
    return _keyword_fallback(key)
