# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM element → envelope adapter (canonical format).

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
    extract_quantities,
)


def _synthesise_description(raw: dict[str, Any]) -> str:
    """Compose a description string from canonical-format properties.

    The matcher embeds this string, so it must be human-readable and
    contain the discriminating signal (material, dimensions, ratings).
    """
    parts: list[str] = []

    category = str(raw.get("category") or "").strip()
    if category:
        parts.append(category)

    properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    name = str(raw.get("name") or "").strip()
    description = str(raw.get("description") or "").strip()

    # Free-form name/description first, properties second — name often
    # carries the brand, model, or assembly type the embedder wants.
    if description and description not in parts:
        parts.append(description)
    elif name and name not in parts:
        parts.append(name)

    material = str(properties.get("material") or "").strip()
    if material:
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


def extract(raw: dict[str, Any]) -> ElementEnvelope:
    """Build an :class:`ElementEnvelope` for a BIM canonical-format element."""
    properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    description = _synthesise_description(raw)
    return build_envelope_base(
        source="bim",
        raw=raw,
        description=description,
        category=str(raw.get("category") or "").strip(),
        source_lang=str(raw.get("language") or properties.get("language") or "en"),
        properties=dict(properties),
        quantities=extract_quantities(raw),
    )
