# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Text source adapter — free-form text inputs to /match-elements.

Implements MAPPING_PROCESS.md §4.1.6 — the "Text" source type. The
estimator types (or pastes) one or more free-form descriptions
("ленточный фундамент 800x600", "Stahlbetonwand C30/37, d=240mm") and
each line becomes a single :class:`SourceElement` with no structured
attributes. The semantic search path then carries the heavy lifting:
BGE-M3 dense + sparse fuse via RRF in Qdrant and surface the closest
CWICR rates, recall@10 ≈ 0.97 per the spec's bench.

Storage
-------
Text inputs live on the parent :class:`MatchSession`'s ``metadata_``
JSON column under the ``text_inputs`` key — either a list of strings
(simple) or a list of dicts ``{raw_text, project_country?, stage?}``
(when the user wants per-line overrides). Persisting in the session
metadata avoids a new table for what is essentially a thin scratch-pad;
re-import diff and template suggestions still flow through the regular
:class:`MatchGroup` rows the service builds from this adapter's output.

When the adapter is constructed without a ``match_session`` reference
(unit-test or smoke probe), it returns empty results from every method
rather than crashing — the loose contract mirrors ``DwgAdapter``'s
"no CAD session → empty list" fallback.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.match_elements.models import MatchSession
from app.modules.match_elements.sources.base import SourceElement

_GROUP_BY_KEY_ORDER = (
    "category",
    "ifc_class",
    "raw_text",
    "project_country",
    "stage",
)


def _coerce_text_input(raw: Any) -> dict[str, Any] | None:
    """‌⁠‍Normalise a single ``text_inputs`` entry to a dict shape.

    Accepts either a plain string (most common — UI just collects lines)
    or a dict with ``raw_text`` plus optional per-line metadata. Returns
    ``None`` for blank or non-stringable rows so the caller can drop them.
    """
    if isinstance(raw, str):
        text = raw.strip()
        return {"raw_text": text} if text else None
    if isinstance(raw, dict):
        text = str(raw.get("raw_text") or raw.get("text") or "").strip()
        if not text:
            return None
        out = {"raw_text": text}
        for key in ("project_country", "stage", "category", "ifc_class"):
            val = raw.get(key)
            if val:
                out[key] = str(val)
        return out
    return None


class TextAdapter:
    """‌⁠‍Reads free-form text inputs from ``MatchSession.metadata_``.

    Each non-empty line becomes a single :class:`SourceElement` with
    ``category="Text"`` (or the user-provided override) and a
    ``count=1`` quantity — semantic search drives recall.
    """

    source_name: str = "text"

    def __init__(
        self,
        session: AsyncSession,
        match_session: MatchSession | None = None,
    ) -> None:
        self.session = session
        self.match_session = match_session

    def _inputs(self) -> list[dict[str, Any]]:
        """Return the normalised list of text-input dicts.

        Empty list when no session is bound or ``metadata_["text_inputs"]``
        is missing/malformed — callers don't need to guard.
        """
        if self.match_session is None:
            return []
        meta = self.match_session.metadata_ or {}
        raw_list = meta.get("text_inputs") or []
        if not isinstance(raw_list, list):
            return []
        out: list[dict[str, Any]] = []
        for raw in raw_list:
            coerced = _coerce_text_input(raw)
            if coerced is not None:
                out.append(coerced)
        return out

    async def list_attribute_keys(
        self,
        project_id: uuid.UUID,  # noqa: ARG002 — text adapter is session-scoped
        bim_model_id: uuid.UUID | None = None,  # noqa: ARG002
    ) -> list[str]:
        """Return the union of keys present across all text inputs.

        Always carries ``category`` and ``ifc_class`` so the cross-source
        group-by chip ("ifc_class") still resolves on text sessions.
        """
        keys: set[str] = {"category", "ifc_class", "raw_text"}
        for entry in self._inputs():
            keys.update(entry.keys())
        ordered = [k for k in _GROUP_BY_KEY_ORDER if k in keys]
        ordered.extend(sorted(k for k in keys if k not in _GROUP_BY_KEY_ORDER))
        return ordered

    async def list_categories(
        self,
        project_id: uuid.UUID,  # noqa: ARG002
        bim_model_id: uuid.UUID | None = None,  # noqa: ARG002
    ) -> list[tuple[str, int]]:
        """Group text inputs by their ``category`` (or "Text" fallback)."""
        from collections import Counter

        counter: Counter[str] = Counter()
        for entry in self._inputs():
            cat = str(entry.get("category") or "Text") or "Text"
            counter[cat] += 1
        return counter.most_common()

    async def iter_elements(
        self,
        *,
        project_id: uuid.UUID,  # noqa: ARG002
        bim_model_id: uuid.UUID | None = None,  # noqa: ARG002
        filters: dict[str, list[Any]] | None = None,
        excluded_categories: list[str] | None = None,
        use_net_quantities: bool = True,  # noqa: ARG002 — text has no net/gross
    ) -> list[SourceElement]:
        """Convert each text input to a single :class:`SourceElement`."""
        excluded = {str(c) for c in (excluded_categories or []) if c}
        norm_filters: dict[str, set[str]] = {}
        if filters:
            for fkey, fvals in filters.items():
                if fvals:
                    norm_filters[fkey] = {str(v) for v in fvals}

        out: list[SourceElement] = []
        for idx, entry in enumerate(self._inputs()):
            text = entry["raw_text"]
            cat = str(entry.get("category") or "Text") or "Text"

            if cat in excluded:
                continue

            attrs: dict[str, Any] = dict(entry)
            attrs.setdefault("category", cat)
            # Promote category → ifc_class so cross-source group-by works.
            attrs.setdefault("ifc_class", cat)

            if norm_filters:
                skip = False
                for fkey, fvals in norm_filters.items():
                    actual = attrs.get(fkey)
                    if actual is None or str(actual) not in fvals:
                        skip = True
                        break
                if skip:
                    continue

            ref = str(self.match_session.id) if self.match_session is not None else None
            out.append(
                SourceElement(
                    id=f"text:{idx}",
                    category=cat,
                    name=text[:200],
                    attributes=attrs,
                    quantities={"count": 1.0},
                    raw_ref=ref,
                )
            )
        return out


__all__ = ["TextAdapter"]
