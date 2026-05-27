# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍DWG source adapter — reads ``oe_takeoff_cad_session`` for the
match-elements module.

Phase B of /match-elements. The DDC ``DwgExporter`` pipeline lands an
extracted DWG/DXF (or RVT/DGN — same table is used for any CAD via
DDC) as a row in :class:`CadExtractionSession` whose ``elements_data``
JSON column carries the per-element dicts the takeoff UI shows. We
reuse those dicts here verbatim so a session a user already inspected
under /quantities can be matched against CWICR without re-extracting.

``MatchSession.bim_model_id`` overload
--------------------------------------
The match-elements schema only has one optional source-scope FK on
:class:`MatchSession` — ``bim_model_id``. Adding a second FK plus a
migration just to namespace DWG sessions is unjustified for Phase B,
so this adapter overloads ``bim_model_id`` as a *source-agnostic*
scope id: when ``MatchSession.source == "dwg"`` it is interpreted as
a :class:`CadExtractionSession.id` (the table's GUID PK from ``Base``,
not the human-friendly ``session_id`` string column).

When ``bim_model_id`` is ``None`` for a DWG session we fall back to
"latest non-expired CAD session for this project", which matches how
the BIM adapter falls back to "all models in the project". The choice
is documented here rather than in the model so the BIM contract stays
declarative.

Field mapping (DDC Excel header → SourceElement)
------------------------------------------------
The DDC ``DwgExporter`` Excel headers land as lowercase dict keys
(``parse_cad_excel`` strips ``" : Type"`` suffixes). We forward the
keys the BIM adapter already emits so the matchers don't branch:

    category / element type   → ``category`` + ``ifc_class`` alias
    type name / family / type → ``type_name``
    layer                     → ``layer`` (DWG-specific, kept for
                                 group-by)
    block name                → ``block_name``
    color                     → ``color``
    entity_type               → ``entity_type``
    material                  → ``material``
    level                     → ``level``
    volume / volume (m3)      → ``quantities.volume_m3``
    area / area (m2)          → ``quantities.area_m2``
    length / length (m)       → ``quantities.length_m``
    count                     → ``quantities.count`` (defaults 1.0)

DWG has no opening/void relations — ``use_net_quantities`` is accepted
for signature compatibility but ignored.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.match_elements.sources.base import SourceElement
from app.modules.takeoff.models import CadExtractionSession

logger = logging.getLogger(__name__)


# Canonical group-by keys we surface first when their values are
# populated — order matters because the chip-bar honours it.
_GROUP_BY_KEY_ORDER = (
    "ifc_class",
    "category",
    "type_name",
    "layer",
    "block_name",
    "level",
    "material",
    "entity_type",
    "color",
)


# DDC Excel headers arrive lowercase. These aliases project the raw
# header onto our canonical attribute name.
_HEADER_ALIASES: dict[str, str] = {
    "category": "category",
    "element type": "category",
    "type name": "type_name",
    "type": "type_name",
    "family": "type_name",
    "layer": "layer",
    "block name": "block_name",
    "block": "block_name",
    "blockname": "block_name",
    "color": "color",
    "colour": "color",
    "entity_type": "entity_type",
    "entity type": "entity_type",
    "level": "level",
    "storey": "level",
    "material": "material",
    "discipline": "discipline",
    "name": "name",
}


# Quantity-column aliases. Floats only — strings drop through.
_QUANTITY_ALIASES: dict[str, str] = {
    "volume": "volume_m3",
    "volume (m3)": "volume_m3",
    "volume_m3": "volume_m3",
    "gross volume": "volume_m3",
    "area": "area_m2",
    "area (m2)": "area_m2",
    "area_m2": "area_m2",
    "gross area": "area_m2",
    "length": "length_m",
    "length (m)": "length_m",
    "length_m": "length_m",
    "perimeter": "perimeter_m",
    "count": "count",
}


def _canon_attr(raw_key: str) -> str | None:
    """‌⁠‍Map a raw element dict key to our canonical attribute name.

    Keys not in the alias table pass through untouched (so a project
    that ships extra DDC columns — wall fire rating, hatch pattern,
    etc — can still be used in group-by). Quantity keys return
    ``None`` so callers know to route to ``quantities``.
    """
    k = raw_key.strip().lower()
    if k in _QUANTITY_ALIASES:
        return None
    return _HEADER_ALIASES.get(k, k)


def _to_float(val: Any) -> float | None:
    """‌⁠‍Best-effort numeric coercion. DDC Excel ships floats already
    but some rows arrive as strings ('12.3 m²' for human display)."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    # Drop trailing units / commas a human-formatted Excel cell may
    # carry (e.g. "12,3 m²" → 12.3). Strip non-numeric tail then swap
    # decimal comma for point.
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


def _quantities_from_element(elem: dict[str, Any]) -> dict[str, float]:
    """Build the rolled-up quantity dict for a single DWG element."""
    out: dict[str, float] = {}
    for raw_key, val in elem.items():
        if not isinstance(raw_key, str):
            continue
        canon = _QUANTITY_ALIASES.get(raw_key.strip().lower())
        if canon is None:
            continue
        f = _to_float(val)
        if f is None:
            continue
        # Sum across duplicates (e.g. an element with both ``area``
        # and ``area (m2)`` headers — unusual but seen in mixed
        # exports) rather than overwrite.
        out[canon] = out.get(canon, 0.0) + f
    if "count" not in out:
        out["count"] = 1.0
    return out


def _attributes_from_element(elem: dict[str, Any]) -> dict[str, Any]:
    """Project an element's raw dict into the canonical attribute map.

    BIM adapter's downstream matchers read ``ifc_class``, ``type_name``,
    ``level``, ``discipline`` first; DWG has no IFC class so we promote
    the DWG ``category`` value to ``ifc_class`` as well — this lets the
    same group-by key (``ifc_class``) work across sources without the
    matcher caring.
    """
    out: dict[str, Any] = {}
    for raw_key, val in elem.items():
        if not isinstance(raw_key, str):
            continue
        canon = _canon_attr(raw_key)
        if canon is None:  # quantity → handled separately
            continue
        if val is None:
            continue
        out.setdefault(canon, val)
    # Promote category → ifc_class so cross-source group-by works.
    if "category" in out and "ifc_class" not in out:
        out["ifc_class"] = out["category"]
    return out


class DwgAdapter:
    """Reads DWG (and any DDC-converted CAD: DGN, RVT-via-takeoff)
    elements for the match-elements service.

    The adapter is keyed off :class:`CadExtractionSession`, the durable
    backing store the takeoff/quantities page already writes. We do
    not re-run the converter — we read the JSON the user already
    accepted. This keeps the matcher input identical to what's
    visible in /quantities, avoiding "the matcher saw different rows
    than I did" surprises.
    """

    source_name: str = "dwg"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _resolve_cad_session(
        self,
        project_id: uuid.UUID,
        bim_model_id: uuid.UUID | None,
    ) -> CadExtractionSession | None:
        """Resolve the CadExtractionSession to read elements from.

        ``bim_model_id`` here is the overload described at the top of
        the module — when set, it's a CadExtractionSession.id. When
        unset we pick the most recent non-expired session for the
        project (mirrors BIM's "all models" fallback).
        """
        if bim_model_id is not None:
            row = await self.session.get(CadExtractionSession, bim_model_id)
            if row is not None:
                return row
            logger.warning(
                "DwgAdapter: CadExtractionSession %s not found, falling back to latest for project %s",
                bim_model_id,
                project_id,
            )

        # Project_id on CadExtractionSession is String(255) not GUID,
        # so coerce to str. Also accept the UUID's string form with
        # and without dashes — older sessions wrote bare hex.
        pid_str = str(project_id)
        pid_hex = pid_str.replace("-", "")
        stmt = (
            select(CadExtractionSession)
            .where(CadExtractionSession.project_id.in_([pid_str, pid_hex]))
            .order_by(CadExtractionSession.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_attribute_keys(
        self,
        project_id: uuid.UUID,
        bim_model_id: uuid.UUID | None = None,
    ) -> list[str]:
        """Sample up to 200 elements to figure out which attribute
        keys are populated. Drives the chip-bar's drag-source list."""
        sess = await self._resolve_cad_session(project_id, bim_model_id)
        if sess is None or not sess.elements_data:
            return []
        keys: set[str] = {"ifc_class", "category"}
        for elem in sess.elements_data[:200]:
            if not isinstance(elem, dict):
                continue
            for raw_key in elem:
                if not isinstance(raw_key, str):
                    continue
                canon = _canon_attr(raw_key)
                if canon:
                    keys.add(canon)
        ordered = [k for k in _GROUP_BY_KEY_ORDER if k in keys]
        ordered.extend(sorted(k for k in keys if k not in _GROUP_BY_KEY_ORDER))
        return ordered

    async def list_categories(
        self,
        project_id: uuid.UUID,
        bim_model_id: uuid.UUID | None = None,
    ) -> list[tuple[str, int]]:
        """Return ``[(category, count), ...]`` for the scope-filter
        chip-bar, sorted by descending count."""
        sess = await self._resolve_cad_session(project_id, bim_model_id)
        if sess is None or not sess.elements_data:
            return []
        counter: Counter[str] = Counter()
        for elem in sess.elements_data:
            if not isinstance(elem, dict):
                continue
            cat = elem.get("category") or elem.get("element type") or "Unknown"
            counter[str(cat) or "Unknown"] += 1
        return counter.most_common()

    async def iter_elements(
        self,
        *,
        project_id: uuid.UUID,
        bim_model_id: uuid.UUID | None = None,
        filters: dict[str, list[Any]] | None = None,
        excluded_categories: list[str] | None = None,
        use_net_quantities: bool = True,  # noqa: ARG002 — DWG no-op
    ) -> list[SourceElement]:
        """Load all elements from the CAD session, applying scope
        filters in Python (the source is a JSON blob — no SQL filter
        is possible without a full table scan anyway).
        """
        sess = await self._resolve_cad_session(project_id, bim_model_id)
        if sess is None or not sess.elements_data:
            return []

        excluded = {c for c in (excluded_categories or []) if c}
        # Pre-lower the filter values once. A DWG project's `Layer`
        # vs `LAYER` mismatch is much more common than in IFC.
        norm_filters: dict[str, set[str]] = {}
        if filters:
            for fkey, fvals in filters.items():
                if not fvals:
                    continue
                norm_filters[fkey] = {str(v) for v in fvals}

        out: list[SourceElement] = []
        for idx, elem in enumerate(sess.elements_data):
            if not isinstance(elem, dict):
                continue

            attrs = _attributes_from_element(elem)
            category = str(attrs.get("category") or "Unknown")

            # Scope filter — drop excluded categories before the
            # per-attribute filters so the user's "exclude
            # Annotation" chip cuts work uniformly.
            if category in excluded:
                continue

            # Per-attribute filter (chip selections from the UI).
            skip = False
            for fkey, fvals in norm_filters.items():
                actual = attrs.get(fkey)
                if actual is None or str(actual) not in fvals:
                    skip = True
                    break
            if skip:
                continue

            qty = _quantities_from_element(elem)

            # DDC sometimes carries a stable "Id" or "ElementId" key
            # — prefer that so re-imports keep group membership; fall
            # back to a synthetic positional id (the row's index in
            # the JSON list, prefixed with the cad session id so a
            # multi-session project doesn't collide).
            raw_id = (
                elem.get("id") or elem.get("Id") or elem.get("element id") or elem.get("elementid") or elem.get("guid")
            )
            element_id = str(raw_id) if raw_id is not None else f"{sess.id}:{idx}"

            name = attrs.get("name") or attrs.get("type_name") or elem.get("description")

            out.append(
                SourceElement(
                    id=element_id,
                    category=category,
                    name=str(name) if name is not None else None,
                    attributes=attrs,
                    quantities=qty,
                    raw_ref=str(sess.id),
                )
            )
        return out
