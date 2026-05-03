# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DWG element → envelope adapter (interim).

Input shape: a layer-name + textual description from the DWG takeoff
parser. Quantities are best-effort because the DWG visual viewer is
still being built (see CLAUDE memory ``session_todo.md`` — DWG visual
viewer is in flight). The extractor still produces a fully-valid
envelope so the matcher's interface is exercised end-to-end.

# v2.8 follow-up: full DWG extraction once viewer ships
# Tracked in: session_todo.md → "DWG visual viewer". Replace this
# stub-style description synthesis with the layer-walking + block
# attribute reader once the viewer pipeline emits structured elements.
"""

from __future__ import annotations

from typing import Any

from app.core.match_service.envelope import ElementEnvelope
from app.core.match_service.extractors._helpers import build_envelope_base


def _category_from_layer(layer: str) -> str:
    """Best-effort category guess from AIA/CAD layer naming convention.

    AIA layer codes are ``DISCIPLINE-MAJOR-MINOR`` — e.g. ``A-WALL-PRTN``
    is "Architecture / Wall / Partition". We return the major group as
    the category since that's what DIN 276 and CWICR group on.
    """
    if not layer:
        return ""
    parts = [p for p in layer.upper().split("-") if p]
    if len(parts) < 2:
        return ""
    major = parts[1]
    return {
        "WALL": "wall",
        "DOOR": "door",
        "WIN": "window",
        "WINDOW": "window",
        "FLOR": "floor",
        "FLOOR": "floor",
        "ROOF": "roof",
        "BEAM": "structural_beam",
        "COLM": "column",
        "FACD": "facade",
        "DUCT": "hvac_duct",
        "PIPE": "pipe",
    }.get(major, major.lower())


def extract(raw: dict[str, Any]) -> ElementEnvelope:
    """Build an :class:`ElementEnvelope` from a DWG-element dict.

    Required fields in ``raw``: ``description`` (text). Optional:
    ``layer``, ``length_m``, ``area_m2``, ``height_m``, ``thickness_m``.
    """
    description = str(raw.get("description") or "").strip()
    layer = str(raw.get("layer") or "").strip()
    category = (
        str(raw.get("category") or "").strip()
        or _category_from_layer(layer)
    )

    properties: dict[str, Any] = {}
    if layer:
        properties["layer"] = layer
    for key in ("cross_section", "weight_kg_per_m"):
        if key in raw and raw[key] not in (None, ""):
            properties[key] = raw[key]

    return build_envelope_base(
        source="dwg",
        raw=raw,
        description=description,
        category=category,
        source_lang=str(raw.get("language") or "en"),
        properties=properties,
    )
