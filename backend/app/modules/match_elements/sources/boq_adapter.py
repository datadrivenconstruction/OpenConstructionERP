# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Excel BoQ source adapter — pre-parsed BoQ rows to /match-elements.

Implements MAPPING_PROCESS.md §4.1.5 — the "Excel BoQ" source. The
estimator uploads an xlsx (description + qty + unit, optionally a
pre-existing rate code), we parse it once at session-creation time
and persist the rows into ``MatchSession.metadata_["boq_rows"]``.

This adapter is then a thin reader over those rows — no xlsx parsing
on the hot path. Each row becomes a :class:`SourceElement` with the
description landing in the dense/sparse query and the unit mapped to
a canonical quantity dimension so the v3 SearchPlan's ``unit_dim``
hard filter can narrow the catalogue.

Fast-path for explicit codes
----------------------------
When a BoQ row carries an exact CWICR ``code`` column, the adapter
forwards it as ``attributes["exact_code"]``. The downstream ranker
short-circuits the Qdrant fan-out for those rows — direct parquet
lookup by ``rate_code`` is O(50 ms) regardless of catalogue size.
This matches MAPPING_PROCESS §4.4 ("если запрос — это явно один
токен (код или класс) — переключайся на sparse-only").

Storage shape
-------------
``MatchSession.metadata_["boq_rows"]`` is a list of dicts. Required:
``description``. Recognised optional keys:

    description / name / text   → element name
    qty / quantity              → numeric quantity
    unit / uom                  → canonical CWICR unit
    code / rate_code            → exact-match shortcut
    category / section          → group-by dimension
    source_lang                 → query-language hint

Any other keys pass through verbatim into ``attributes``, so a tenant
shipping its own column ("supplier", "delivery_week") can still group
on it. The Excel parser at session-creation time is responsible for
trimming whitespace and casting to the right primitive.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.match_elements.models import MatchSession
from app.modules.match_elements.sources.base import SourceElement

_GROUP_BY_KEY_ORDER = (
    "category",
    "section",
    "ifc_class",
    "description",
    "unit",
    "source_lang",
)


# Unit → canonical quantity-dimension mapping. Mirrors
# ``costs/query_builder._UNIT_DIM`` but lives here so the BoQ parsing
# stays self-contained and a custom unit ("100 m³") added by a tenant
# doesn't need a circular import to recognise.
_UNIT_TO_QTY_KEY: dict[str, str] = {
    # Volume
    "m3": "volume_m3",
    "m³": "volume_m3",
    "м3": "volume_m3",
    "м³": "volume_m3",
    "cbm": "volume_m3",
    "cum": "volume_m3",
    # Area
    "m2": "area_m2",
    "m²": "area_m2",
    "м2": "area_m2",
    "м²": "area_m2",
    "sqm": "area_m2",
    "sm": "area_m2",
    # Length
    "m": "length_m",
    "м": "length_m",
    "lm": "length_m",
    "rm": "length_m",
    "lfm": "length_m",
    # Mass
    "kg": "mass_kg",
    "кг": "mass_kg",
    "lb": "mass_kg",
    # Mass (tonnes — convert to kg for downstream consistency)
    "t": "mass_t",
    "ton": "mass_t",
    "tonne": "mass_t",
    "т": "mass_t",
    "to": "mass_t",
    # Count
    "pcs": "count",
    "шт": "count",
    "ea": "count",
    "stk": "count",
    "stck": "count",
    "nr": "count",
    "no": "count",
    "u": "count",
}


def _to_float(val: Any) -> float | None:
    """‌⁠‍Coerce a BoQ qty cell to float, tolerating "12,3" and "12.3 m³".

    Returns ``None`` for blanks, non-numeric text, or coercion failures —
    callers treat that as "no quantity for this row".
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    cleaned = s.replace(",", ".")
    head: list[str] = []
    seen_dot = False
    for ch in cleaned:
        if ch.isdigit() or (ch == "-" and not head):
            head.append(ch)
        elif ch == "." and not seen_dot:
            head.append(ch)
            seen_dot = True
        elif head:
            break
    if not head:
        return None
    try:
        return float("".join(head))
    except ValueError:
        return None


def _quantities_for(unit: str | None, qty: float | None) -> dict[str, float]:
    """‌⁠‍Map ``unit`` + ``qty`` onto the canonical quantity dimensions.

    Always returns at least ``count=1.0`` so a "no qty / lump-sum" BoQ
    row still flows through the matcher pipeline.
    """
    out: dict[str, float] = {"count": 1.0}
    if qty is None or qty == 0:
        return out
    key = (unit or "").strip().lower().replace(" ", "")
    canon = _UNIT_TO_QTY_KEY.get(key)
    if canon is None:
        return out
    if canon == "mass_t":
        out["mass_kg"] = qty * 1000.0
        return out
    out[canon] = qty
    if canon == "count":
        out["count"] = qty
    return out


class BoqAdapter:
    """Reads pre-parsed BoQ rows from ``MatchSession.metadata_``."""

    source_name: str = "boq"

    def __init__(
        self,
        session: AsyncSession,
        match_session: MatchSession | None = None,
    ) -> None:
        self.session = session
        self.match_session = match_session

    def _rows(self) -> list[dict[str, Any]]:
        """Return the raw BoQ rows from session metadata.

        Empty list when no session is bound or ``boq_rows`` is missing.
        Non-dict entries are filtered out so a malformed metadata blob
        doesn't crash the matcher.
        """
        if self.match_session is None:
            return []
        meta = self.match_session.metadata_ or {}
        raw_rows = meta.get("boq_rows") or []
        if not isinstance(raw_rows, list):
            return []
        return [r for r in raw_rows if isinstance(r, dict)]

    async def list_attribute_keys(
        self,
        project_id: uuid.UUID,  # noqa: ARG002 — boq adapter is session-scoped
        bim_model_id: uuid.UUID | None = None,  # noqa: ARG002
    ) -> list[str]:
        """Return the union of dict keys across all BoQ rows.

        Filters out quantity columns (qty/quantity) since those drive
        ``quantities``, not the chip-bar group-by.
        """
        keys: set[str] = {"category", "ifc_class", "description", "unit"}
        for row in self._rows():
            keys.update(row.keys())
        for q in ("qty", "quantity", "Qty", "Quantity"):
            keys.discard(q)
        ordered = [k for k in _GROUP_BY_KEY_ORDER if k in keys]
        ordered.extend(sorted(k for k in keys if k not in _GROUP_BY_KEY_ORDER))
        return ordered

    async def list_categories(
        self,
        project_id: uuid.UUID,  # noqa: ARG002
        bim_model_id: uuid.UUID | None = None,  # noqa: ARG002
    ) -> list[tuple[str, int]]:
        """Group rows by ``category`` (or ``section``) — fallback "BoQ"."""
        counter: Counter[str] = Counter()
        for row in self._rows():
            cat = str(row.get("category") or row.get("section") or "BoQ") or "BoQ"
            counter[cat] += 1
        return counter.most_common()

    async def iter_elements(
        self,
        *,
        project_id: uuid.UUID,  # noqa: ARG002
        bim_model_id: uuid.UUID | None = None,  # noqa: ARG002
        filters: dict[str, list[Any]] | None = None,
        excluded_categories: list[str] | None = None,
        use_net_quantities: bool = True,  # noqa: ARG002 — BoQ has no openings
    ) -> list[SourceElement]:
        """Convert each parsed BoQ row to a :class:`SourceElement`."""
        excluded = {str(c) for c in (excluded_categories or []) if c}
        norm_filters: dict[str, set[str]] = {}
        if filters:
            for fkey, fvals in filters.items():
                if fvals:
                    norm_filters[fkey] = {str(v) for v in fvals}

        out: list[SourceElement] = []
        for idx, row in enumerate(self._rows()):
            cat = str(row.get("category") or row.get("section") or "BoQ") or "BoQ"
            if cat in excluded:
                continue

            description = str(row.get("description") or row.get("name") or row.get("text") or "").strip()
            unit = str(row.get("unit") or row.get("uom") or "").strip()
            qty = _to_float(row.get("qty") or row.get("quantity") or row.get("Qty") or row.get("Quantity"))

            attrs: dict[str, Any] = dict(row)
            attrs.setdefault("category", cat)
            attrs.setdefault("description", description)
            attrs.setdefault("unit", unit)
            # ``ifc_class`` is kept only when the BoQ row carries a real
            # IFC class name (``IfcWall`` / ``IfcSlab`` / …). The
            # synthetic source label (default ``"BoQ"``, or whatever the
            # estimator wrote in the ``category`` / ``section`` column)
            # is NOT an IFC class — promoting it would poison the
            # downstream Qdrant ``ifc_class`` hard filter and eliminate
            # 100% of CWICR candidate rows (see
            # :doc:`memory/match_elements_three_filter_bugs`).
            row_ifc = attrs.get("ifc_class")
            if not (isinstance(row_ifc, str) and row_ifc.startswith("Ifc")):
                attrs.pop("ifc_class", None)

            # Exact-code shortcut (§4.4 — sparse-only would be enough,
            # but the ranker layer reads ``exact_code`` and skips Qdrant
            # fan-out entirely when present).
            code = row.get("code") or row.get("rate_code")
            if code:
                attrs["exact_code"] = str(code).strip()

            if norm_filters:
                skip = False
                for fkey, fvals in norm_filters.items():
                    actual = attrs.get(fkey)
                    if actual is None or str(actual) not in fvals:
                        skip = True
                        break
                if skip:
                    continue

            quantities = _quantities_for(unit, qty)

            row_id = row.get("id") or row.get("row_id") or row.get("ordinal") or f"boq:{idx}"
            ref = str(self.match_session.id) if self.match_session is not None else None

            out.append(
                SourceElement(
                    id=str(row_id),
                    category=cat,
                    name=description[:200] or None,
                    attributes=attrs,
                    quantities=quantities,
                    raw_ref=ref,
                )
            )
        return out


__all__ = ["BoqAdapter"]
