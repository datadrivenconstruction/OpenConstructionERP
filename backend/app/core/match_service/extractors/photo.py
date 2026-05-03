# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photo element → envelope adapter (stub).

Input shape: ``{file_url, ai_extracted_tags?, description?, ...}``. The
real CV pipeline (PaddleOCR + YOLO) is a separate multi-week build —
this extractor exercises the matcher interface end-to-end with a
partial-quality envelope so tests pass and the rest of the system
doesn't block waiting on CV.

# v2.8 follow-up: depends on CV pipeline build (B=full CV pipeline from scratch)
# Tracked in: CLAUDE.md Phase 3 "AI Takeoff" → ``services/cv-pipeline/``.
# Replace ``description`` synthesis with the structured CV output
# (object detections + dimension OCR + symbol classification).
"""

from __future__ import annotations

from typing import Any

from app.core.match_service.envelope import ElementEnvelope
from app.core.match_service.extractors._helpers import build_envelope_base


def _description_from_tags(tags: list[Any]) -> str:
    """Stringify CV-extracted tags into a description blob."""
    if not tags:
        return ""
    return ", ".join(str(t).strip() for t in tags if str(t).strip())


def extract(raw: dict[str, Any]) -> ElementEnvelope:
    """Build an :class:`ElementEnvelope` from a photo-element dict.

    Pulls description from either ``description`` (direct) or
    ``ai_extracted_tags`` (rendered as ``"tag1, tag2, tag3"``).
    Quantities come from ``estimated_*`` keys exported by the CV
    confidence-scoring step.
    """
    description = str(raw.get("description") or "").strip()
    if not description:
        tags = raw.get("ai_extracted_tags") or raw.get("tags") or []
        if isinstance(tags, list):
            description = _description_from_tags(tags)

    category = str(raw.get("category") or raw.get("estimated_category") or "").strip()

    quantities: dict[str, float] = {}
    for src_key, dst_key in (
        ("estimated_area_m2", "area_m2"),
        ("estimated_length_m", "length_m"),
        ("estimated_volume_m3", "volume_m3"),
        ("estimated_quantity", "quantity"),
        ("estimated_count", "count"),
    ):
        value = raw.get(src_key)
        if value in (None, "", 0):
            continue
        try:
            quantities[dst_key] = float(value)
        except (TypeError, ValueError):
            continue

    properties: dict[str, Any] = {}
    confidence = raw.get("cv_confidence") or raw.get("confidence")
    if confidence is not None:
        properties["cv_confidence"] = confidence
    file_url = raw.get("file_url")
    if file_url:
        properties["file_url"] = file_url

    unit_hint = str(raw.get("estimated_unit") or raw.get("unit") or "").strip() or None

    return build_envelope_base(
        source="photo",
        raw=raw,
        description=description,
        category=category,
        source_lang=str(raw.get("language") or "en"),
        properties=properties,
        quantities=quantities or None,
        unit_hint=unit_hint,
    )
