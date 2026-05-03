# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared envelope-construction helpers used by every extractor."""

from __future__ import annotations

from typing import Any

from app.core.match_service.envelope import ElementEnvelope, SourceType

# Quantity keys the canonical-format / takeoff payload uses. Mirrors the
# brief and the extractor-specific docs.
_QUANTITY_KEYS: tuple[str, ...] = (
    "length_m",
    "perimeter_m",
    "area_m2",
    "volume_m3",
    "mass_kg",
    "weight_kg",
    "count",
    "quantity",
    "depth_m",
    "height_m",
    "thickness_m",
    "width_m",
)


def _coerce_float(value: Any) -> float | None:
    """Convert numeric-ish values to float; non-numeric → ``None``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def extract_quantities(raw: dict[str, Any]) -> dict[str, float]:
    """Pull recognised quantity keys out of an arbitrary raw element dict.

    Looks at both the top level (``raw["area_m2"]``) and a nested
    ``geometry`` block (``raw["geometry"]["area_m2"]``) — the canonical
    format puts dimensions inside ``geometry``.
    """
    out: dict[str, float] = {}
    sources: list[dict[str, Any]] = [raw]
    geometry = raw.get("geometry")
    if isinstance(geometry, dict):
        sources.append(geometry)
    quantities = raw.get("quantities")
    if isinstance(quantities, dict):
        sources.append(quantities)

    for source in sources:
        for key in _QUANTITY_KEYS:
            if key in out:
                continue
            value = _coerce_float(source.get(key))
            if value is not None and value != 0:
                out[key] = value
    return out


def extract_classifier_hint(raw: dict[str, Any]) -> dict[str, str] | None:
    """Pull a ``{din276/nrm/masterformat}`` hint dict if present."""
    classification = raw.get("classification") or raw.get("classifier_hint")
    if not isinstance(classification, dict):
        return None
    out: dict[str, str] = {}
    for key in ("din276", "nrm", "masterformat"):
        value = classification.get(key)
        if value:
            out[key] = str(value)
    return out or None


def build_envelope_base(
    *,
    source: SourceType,
    raw: dict[str, Any],
    description: str,
    category: str = "",
    source_lang: str | None = None,
    properties: dict[str, Any] | None = None,
    quantities: dict[str, float] | None = None,
    unit_hint: str | None = None,
    classifier_hint: dict[str, str] | None = None,
) -> ElementEnvelope:
    """Assemble an :class:`ElementEnvelope` with the shared default plumbing.

    Centralises:

    * ``source_lang`` resolution (raw["language"] → "en" fallback)
    * quantity extraction via :func:`extract_quantities`
    * classifier-hint extraction via :func:`extract_classifier_hint`

    so individual source extractors stay focussed on the bits that
    differ (where to read ``description`` from, what's the category).
    """
    lang = (source_lang or str(raw.get("language") or raw.get("source_lang") or "en")).strip().lower() or "en"
    final_props = dict(properties or {})
    final_quantities = quantities if quantities is not None else extract_quantities(raw)
    final_hint = classifier_hint if classifier_hint is not None else extract_classifier_hint(raw)

    return ElementEnvelope(
        source=source,
        source_lang=lang,
        category=(category or str(raw.get("category") or "")).strip(),
        description=description.strip(),
        properties=final_props,
        quantities=final_quantities,
        unit_hint=(unit_hint or str(raw.get("unit") or raw.get("unit_hint") or "") or None) or None,
        classifier_hint=final_hint,
    )
