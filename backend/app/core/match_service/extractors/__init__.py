# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Source-specific element-to-envelope extractors.

Use :func:`build_envelope` to dispatch by source name — that's the
boundary the router and the eval harness both go through. New sources
register here so the dispatch surface stays one symbol wide.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.match_service.envelope import ElementEnvelope, SourceType
from app.core.match_service.extractors import bim, dwg, pdf, photo

ExtractorFn = Callable[[dict[str, Any]], ElementEnvelope]

EXTRACTORS: dict[SourceType, ExtractorFn] = {
    "bim": bim.extract,
    "pdf": pdf.extract,
    "dwg": dwg.extract,
    "photo": photo.extract,
}


def build_envelope(source: str, raw_data: dict[str, Any]) -> ElementEnvelope:
    """Dispatch to the registered extractor for ``source``.

    Args:
        source: One of ``"bim"``, ``"pdf"``, ``"dwg"``, ``"photo"``.
        raw_data: The source-specific raw element dict.

    Raises:
        ValueError: If ``source`` is not a registered extractor.
    """
    key = source.strip().lower()
    if key not in EXTRACTORS:
        msg = f"Unknown match source '{source}'. Known: {sorted(EXTRACTORS)}"
        raise ValueError(msg)
    return EXTRACTORS[key](raw_data or {})  # type: ignore[index]


__all__ = ["EXTRACTORS", "ExtractorFn", "build_envelope"]
