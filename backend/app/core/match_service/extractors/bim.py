# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍BIM element → envelope adapter (canonical format).

Input shape mirrors ``backend/app/modules/cad/`` canonical elements:

    {
        "id": "...", "category": "wall",
        "geometry": {"length_m": 12.5, "area_m2": 37.5, ...},
        "properties": {"material": "Concrete C30/37", "fire_rating": "F90"},
        "classification": {"din276": "330"},
        "language": "en"
    }

The extractor synthesises a description from category + material + fire
rating because the canonical block doesn't always carry a free-form
description (BIM tools name elements ``"Wall:Generic 200mm:1234"`` —
not useful for embedding).
"""

from __future__ import annotations

from typing import Any

from app.core.match_service.envelope import ElementEnvelope
from app.core.match_service.extractors._helpers import (
    build_envelope_base,
    extract_classifier_hint,
    extract_quantities,
)
from app.modules.cad.classification_mapper import (
    enrich_classification,
    get_supported_standards,
)


def _auto_classifier_hint(
    raw: dict[str, Any],
    properties: dict[str, Any],
) -> dict[str, str] | None:
    """‌⁠‍Build a ``{din276/nrm/masterformat}`` hint from category + material.

    Falls through to ``None`` when the category isn't recognised by any
    of the coarse maps. We always populate all three standards (when a
    code is available) so the matcher's classifier boost picks up the
    one selected via ``settings.classifier`` without re-running.
    """
    category = str(raw.get("category") or "").strip()
    if not category:
        return None
    material = properties.get("material")
    fire_rating = properties.get("fire_rating")
    out: dict[str, str] = {}
    for standard in get_supported_standards():
        code = enrich_classification(
            category,
            material=str(material) if material else None,
            fire_rating=str(fire_rating) if fire_rating else None,
            standard=standard,
        )
        if code:
            out[standard] = code
    return out or None


# IFC class → English noun map. Used to enrich the description string
# so the dense channel has English content even when the source name is
# a single foreign-language word (e.g., a Dutch IFC's ``"traphek"``).
# Without this, BGE-M3 must cross-lingual the Dutch word against an
# English catalogue with no English context whatsoever — recall collapses.
_IFC_CLASS_TO_ENGLISH: dict[str, str] = {
    "ifcwall": "wall",
    "ifcwallstandardcase": "wall",
    "ifccurtainwall": "curtain wall facade",
    "ifcslab": "slab floor",
    "ifcfloor": "floor",
    "ifcroof": "roof",
    "ifcdoor": "door",
    "ifcwindow": "window",
    "ifcstair": "stair",
    "ifcstairflight": "stair flight",
    "ifcramp": "ramp",
    "ifccolumn": "column",
    "ifcbeam": "beam",
    "ifcmember": "structural member framing",
    "ifcplate": "plate sheet",
    "ifcfooting": "foundation footing",
    "ifcpile": "pile foundation",
    "ifcrailing": "railing handrail balustrade",
    "ifcpipesegment": "pipe",
    "ifcductsegment": "duct",
    "ifcflowsegment": "pipe duct MEP",
    "ifcflowfitting": "pipe fitting",
    "ifcflowterminal": "plumbing fixture terminal",
    "ifccovering": "finish covering",
    "ifccovering.ceiling": "ceiling finish",
    "ifccovering.flooring": "floor covering",
    "ifccovering.cladding": "cladding facade",
    "ifcbuildingelementpart": "building element part",
    "ifcbuildingelementproxy": "generic element",
    "ifcvirtualelement": "virtual element",
    "ifcopeningelement": "opening void",
    "ifcdistributionelement": "MEP distribution",
    "ifcdistributionchamberelement": "chamber distribution",
    "ifclightfixture": "light fixture luminaire",
    "ifclamp": "lamp light",
    "ifcoutlet": "electrical outlet",
    "ifcswitchingdevice": "switch electrical",
    "ifcairterminal": "air terminal diffuser",
    "ifcfurniture": "furniture",
    "ifcfurnishingelement": "furnishing",
    "ifcspace": "space room zone",
    "ifctransportelement": "transport element",
}


# Junk-byte filter. IFC exports sometimes carry literal 0xFF or empty
# whitespace as a placeholder description; without this they bubble into
# the dense query as raw garbage that the encoder can't score.
_JUNK_NAMES: frozenset[str] = frozenset({"\xff", "?", "-", "n/a", "na", "none"})


def _is_meaningful(text: str) -> bool:
    """True if ``text`` looks like a real human-grade label."""
    s = text.strip()
    if not s or len(s) < 2:
        return False
    if s.lower() in _JUNK_NAMES:
        return False
    # All non-letters / non-digits → almost certainly junk
    if not any(c.isalnum() for c in s):
        return False
    return True


def _ifc_class_english(category: str) -> str:
    """Map an IFC entity-type to a short English noun phrase."""
    if not category:
        return ""
    key = category.strip().lower()
    return _IFC_CLASS_TO_ENGLISH.get(key, "")


def _synthesise_description(raw: dict[str, Any]) -> str:
    """‌⁠‍Compose a description string from canonical-format properties.

    The matcher embeds this string, so it must be human-readable and
    contain the discriminating signal (material, dimensions, ratings).

    Ordering: the strongest English signal first (IFC class English
    noun), then the source name only when it looks meaningful, then
    material + properties. The English IFC anchor is critical when the
    source name is foreign-language (Dutch "traphek", German "Wand") and
    the catalogue is English — without it BGE-M3 has no English seed at
    all and recall collapses.
    """
    parts: list[str] = []

    category = str(raw.get("category") or "").strip()
    properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    name = str(raw.get("name") or "").strip()
    description = str(raw.get("description") or "").strip()

    # English anchor from the IFC class — ALWAYS first so the dense
    # channel has something the catalogue can latch onto.
    english = _ifc_class_english(category)
    if english:
        parts.append(english)
    elif category:
        # Unknown IFC class — fall back to the raw value (still better
        # than nothing). Strip a leading "Ifc" prefix so the encoder
        # sees ``"Wall"`` instead of ``"IfcWall"`` (the latter is an
        # internal token that doesn't appear in catalogue descriptions).
        bare = category[3:] if category.lower().startswith("ifc") else category
        parts.append(bare.lower())

    # Free-form description / name — only when they pass the meaningful
    # check, so junk bytes like 0xFF don't poison the query.
    if description and description not in parts and _is_meaningful(description):
        parts.append(description)
    elif name and name not in parts and _is_meaningful(name):
        parts.append(name)

    material = str(properties.get("material") or "").strip()
    if material and _is_meaningful(material):
        parts.append(material)

    # Surface a few high-signal properties commonly used in CWICR
    # descriptions: thickness, fire rating, U-value.
    geometry = raw.get("geometry") if isinstance(raw.get("geometry"), dict) else {}
    thickness = geometry.get("thickness_m") or properties.get("thickness_m")
    if thickness:
        parts.append(f"thickness {thickness}m")
    fire = properties.get("fire_rating")
    if fire:
        parts.append(f"fire {fire}")
    u_value = properties.get("u_value")
    if u_value:
        parts.append(f"U={u_value}")

    return ", ".join(p for p in parts if p)


def _normalise_ifc_class(raw: dict[str, Any]) -> str | None:
    """Pick the canonical ``Ifc...`` class from the raw dict.

    Looks at ``raw["ifc_class"]`` first (some upstream pipelines set it
    directly), then falls back to ``raw["category"]`` when it starts
    with ``Ifc`` — the BIM canonical format puts the entity-type there
    verbatim. Normalises ``IfcWallStandardCase`` →
    ``IfcWallStandardCase`` (keep case-sensitive shape the catalogue
    payload uses), but discards values that don't have the ``Ifc``
    prefix so synthetic source labels (``"BoQ"`` / ``"Text"``) can't
    accidentally land here.

    Without this populated, the SearchPlan never emits an
    ``ifc_class`` hard filter even though the catalogue's payload index
    has ~28k rows tagged with it — recall on structural elements
    suffered as a result.
    """

    for key in ("ifc_class", "category"):
        v = str(raw.get(key) or "").strip()
        if v.startswith("Ifc") and len(v) > 3:
            return v
    return None


def _normalise_material_class(raw: dict[str, Any]) -> str | None:
    """Map the source material name onto the canonical ``material_class``.

    Reuses the synonym table from :mod:`classification_mapper` so DE
    "Stahlbeton" / EN "reinforced concrete" / cryptic "C30/37" all
    collapse onto ``"concrete"``. Drives the v3 soft boost on
    ``material_class`` against the catalogue payload.
    """

    from app.modules.cad.classification_mapper import _normalise_material

    properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    for src in (
        properties.get("material"),
        properties.get("Material"),
        raw.get("material"),
    ):
        if not src:
            continue
        canonical = _normalise_material(str(src))
        if canonical:
            return canonical
    return None


def extract(raw: dict[str, Any]) -> ElementEnvelope:
    """Build an :class:`ElementEnvelope` for a BIM canonical-format element.

    When the raw dict already carries a ``classification`` block (legacy
    BIM imports that ran through DDC's ``cad2data`` enricher), we honour
    it as-is. When it doesn't, we synthesise a hint from category +
    material via :func:`enrich_classification` so the matcher's
    classifier boost has something to anchor on for fresh imports.

    We also populate the v3 structured fields (``ifc_class``,
    ``ifc_predefined_type``, ``material_class``) from the raw payload
    so the SearchPlan's hard filters + soft boosts actually fire on
    IFC-sourced elements (catalogue collections like ``cwicr_en_v3``
    do carry ``ifc_class`` / ``material_class`` payload indexes).
    """
    properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    description = _synthesise_description(raw)

    # Prefer an explicit classification block on the raw dict (existing
    # behaviour); fall back to the material-aware auto-hint only when no
    # classification was supplied upstream.
    classifier_hint = extract_classifier_hint(raw)
    if classifier_hint is None:
        classifier_hint = _auto_classifier_hint(raw, properties)

    envelope = build_envelope_base(
        source="bim",
        raw=raw,
        description=description,
        category=str(raw.get("category") or "").strip(),
        source_lang=str(raw.get("language") or properties.get("language") or ""),
        properties=dict(properties),
        quantities=extract_quantities(raw),
        classifier_hint=classifier_hint,
    )

    # ── v3 structured fields ─────────────────────────────────────────
    # Populate ``ifc_class`` from the source's IFC entity-type so the
    # SearchPlan can pin it as a hard filter. The check inside
    # ``build_search_plan`` also verifies the bound catalogue actually
    # carries the ``ifc_class`` payload field — collections that don't
    # (e.g., raw DDC v3 snapshots) silently drop the predicate, so this
    # is safe to populate unconditionally.
    ifc_class = _normalise_ifc_class(raw)
    if ifc_class:
        envelope.ifc_class = ifc_class

    # ``ifc_predefined_type`` lives in ``properties`` for canonical-
    # format payloads and at the top level for some pipelines.
    pred_type = (
        properties.get("ifc_predefined_type")
        or properties.get("predefined_type")
        or raw.get("ifc_predefined_type")
        or raw.get("predefined_type")
    )
    if pred_type:
        envelope.ifc_predefined_type = str(pred_type)[:64]

    # ``material_class`` powers a soft boost — never a hard filter — so
    # we collapse free-form material strings onto the canonical token
    # set (``concrete`` / ``masonry`` / ``timber`` / ``steel`` / …).
    material_class = _normalise_material_class(raw)
    if material_class:
        envelope.material_class = material_class

    # Pset trinary booleans — hard filters when explicitly True (per
    # MAPPING_PROCESS.md §4.2.1). False rarely helps as a filter — most
    # catalogue rates don't carry a definitely-not-external flag.
    for src_key, dst_attr in (
        ("is_external", "is_external"),
        ("IsExternal", "is_external"),
        ("is_loadbearing", "is_loadbearing"),
        ("LoadBearing", "is_loadbearing"),
        ("is_structural", "is_structural"),
    ):
        v = properties.get(src_key)
        if v is None:
            v = raw.get(src_key)
        if isinstance(v, bool) and v:
            setattr(envelope, dst_attr, True)

    # ``nominal_size_mm`` — pull the integer thickness when the
    # geometry block carries one. The catalogue's soft boost matches
    # within ±10% so a 220mm-wall envelope still picks up the 200mm
    # boost.
    geometry = raw.get("geometry") if isinstance(raw.get("geometry"), dict) else {}
    thickness_m = (
        geometry.get("thickness_m")
        or properties.get("thickness_m")
        or raw.get("thickness_m")
    )
    if thickness_m:
        try:
            envelope.nominal_size_mm = int(round(float(thickness_m) * 1000))
        except (TypeError, ValueError):
            pass

    return envelope
