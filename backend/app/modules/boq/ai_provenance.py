"""AI-origin marking for BOQ exports (EU AI Act, art. 50(2)).

Content a model produced has to be marked as such in a machine-readable way
wherever it leaves the system. A BOQ position records how it was entered in
``source``: every AI write path stores a value starting with ``ai_``
(``ai_copilot_accepted``, ``ai_precise_estimate``, ``ai_match`` ...), and the
AI estimator additionally stamps ``metadata.ai_estimator_run_id``. Exporters
ask :func:`ai_origin` per row and write the answer in their own format.

The marker says where the content came from, not whether a person confirmed
it: an accepted suggestion is still AI-generated content.
"""

from __future__ import annotations

from typing import Any

# Prefix of every ``Position.source`` value an AI write path stores.
AI_SOURCE_PREFIX = "ai_"

# Metadata keys AI pipelines stamp on rows they produced.
_AI_METADATA_KEYS = ("ai_estimator_run_id", "ai_takeoff_run_id")

# Machine-readable token used in every export format (PDF keywords and info
# dictionary, XLSX custom property, GAEB text marker).
AI_MARK_TOKEN = "AI-GENERATED"

# Text marker for formats that only carry text per row (GAEB). Parsable as
# ``[AI-GENERATED source=<value>]``.
AI_MARK_TEXT_PREFIX = f"[{AI_MARK_TOKEN} source="


def ai_origin(pos: Any) -> str | None:
    """Return the AI source of a position, or ``None`` when no model produced it."""
    source = str(getattr(pos, "source", "") or "").strip()
    if source.lower().startswith(AI_SOURCE_PREFIX):
        return source
    meta = getattr(pos, "metadata", None)
    if not isinstance(meta, dict):
        meta = getattr(pos, "metadata_", None)
    if isinstance(meta, dict):
        for key in _AI_METADATA_KEYS:
            if meta.get(key):
                return source if source and source != "manual" else key.removesuffix("_run_id")
    return None


def ai_mark_text(source: str) -> str:
    """The per-row text marker, e.g. ``[AI-GENERATED source=ai_copilot_accepted]``."""
    return f"{AI_MARK_TEXT_PREFIX}{source}]"
