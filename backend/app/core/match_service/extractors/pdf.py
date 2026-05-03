# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PDF takeoff element → envelope adapter.

Input shape mirrors ``backend/app/modules/takeoff/schemas.py``
``ExtractedElement`` plus the takeoff-measurement view: free-form
``description`` text plus a couple of derived dimensions
(``quantity`` / ``unit`` / ``measurement_value``).

This extractor is fully functional in v2.8.0 — PDF takeoff is the
primary user-facing source besides BIM.
"""

from __future__ import annotations

from typing import Any

from app.core.match_service.envelope import ElementEnvelope
from app.core.match_service.extractors._helpers import (
    build_envelope_base,
    extract_classifier_hint,
)
from app.modules.cad.classification_mapper import (
    enrich_classification,
    get_supported_standards,
)


def _auto_classifier_hint_from_category(category: str) -> dict[str, str] | None:
    """Coarse classifier hint from category alone (no material).

    Useful for PDF takeoff and DWG layer-derived elements where the
    material is rarely surfaced in the raw row. Falls back to ``None``
    when even the coarse map has no entry.
    """
    if not category:
        return None
    out: dict[str, str] = {}
    for standard in get_supported_standards():
        code = enrich_classification(category, standard=standard)
        if code:
            out[standard] = code
    return out or None


def _quantities_from_takeoff(raw: dict[str, Any]) -> dict[str, float]:
    """Derive ``quantities`` from PDF/takeoff measurement output.

    Takeoff measurements expose the dimension as ``measurement_value``
    paired with ``measurement_unit``. We translate that pair into the
    canonical key the matcher looks for so the unit-boost can fire.
    """
    out: dict[str, float] = {}

    # Direct hit if takeoff already populated canonical keys.
    for key in ("length_m", "area_m2", "volume_m3", "perimeter_m", "count", "quantity"):
        value = raw.get(key)
        if value not in (None, ""):
            try:
                fv = float(value)
            except (TypeError, ValueError):
                continue
            if fv:
                out[key] = fv

    # Map ``measurement_value`` + ``measurement_unit`` → canonical.
    measurement_value = raw.get("measurement_value")
    measurement_unit = str(raw.get("measurement_unit") or raw.get("unit") or "").strip().lower()
    measurement_unit = measurement_unit.replace("²", "2").replace("³", "3")
    quantity_value = raw.get("quantity")

    candidate_value: float | None = None
    if measurement_value not in (None, ""):
        try:
            candidate_value = float(measurement_value)
        except (TypeError, ValueError):
            candidate_value = None
    elif quantity_value not in (None, ""):
        try:
            candidate_value = float(quantity_value)
        except (TypeError, ValueError):
            candidate_value = None

    if candidate_value:
        if measurement_unit in ("m", "lm"):
            out.setdefault("length_m", candidate_value)
        elif measurement_unit in ("m2", "sqm"):
            out.setdefault("area_m2", candidate_value)
        elif measurement_unit in ("m3", "cbm"):
            out.setdefault("volume_m3", candidate_value)
        elif measurement_unit == "kg":
            out.setdefault("mass_kg", candidate_value)
        elif measurement_unit in ("pcs", "ea", "stk"):
            out.setdefault("count", candidate_value)
    return out


def extract(raw: dict[str, Any]) -> ElementEnvelope:
    """Build an :class:`ElementEnvelope` from a takeoff/PDF element dict.

    PDF takeoff rarely surfaces a structured material — we only have a
    free-form description. So we hint at classification using the
    category alone (coarse 3-digit DIN / 1-2-segment NRM / 6-digit
    MasterFormat) when an upstream ``classification`` is missing.
    """
    description = str(raw.get("description") or raw.get("annotation") or "").strip()
    category = str(raw.get("category") or raw.get("type") or "").strip()
    unit_hint = str(raw.get("unit") or raw.get("measurement_unit") or "").strip() or None

    classifier_hint = extract_classifier_hint(raw)
    if classifier_hint is None:
        classifier_hint = _auto_classifier_hint_from_category(category)

    return build_envelope_base(
        source="pdf",
        raw=raw,
        description=description,
        category=category,
        source_lang=str(raw.get("language") or "en"),
        properties={
            k: v
            for k, v in raw.items()
            if k in ("group_name", "page", "depth", "perimeter")
            and v not in (None, "", 0)
        },
        quantities=_quantities_from_takeoff(raw),
        unit_hint=unit_hint,
        classifier_hint=classifier_hint,
    )
