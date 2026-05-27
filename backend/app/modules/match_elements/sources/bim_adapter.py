# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍BIM source adapter — reads ``oe_bim_element`` for the match-elements module.

The adapter joins through ``oe_bim_model`` to scope by project, returning
``SourceElement`` records that carry both the raw and net quantities the
service needs to roll up by group.

Net-quantity logic for Phase A:
    * ``volume_m3``  = ``properties.gross_volume_m3 - properties.openings_volume_m3``
       (falls back to ``quantities.volume_m3`` when the model didn't carry
       opening relations).
    * ``area_m2``    = ``properties.gross_area_m2 - properties.openings_area_m2``
       (similar fallback).
    * ``length_m`` and ``count`` always pass through unchanged.

The DDC cad2data converters store opening info under the ``properties``
JSON keys above; older imports without those keys degrade gracefully —
gross == net.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.match_elements.sources.base import SourceElement

_GROUP_BY_KEY_ORDER = (
    "ifc_class",
    "type_name",
    "category",
    "level",
    "discipline",
    "material",
    "thickness_mm",
    "fire_rating",
    "load_bearing",
    "is_external",
)

# Hard cap on elements pulled per session. A 100k-element model would
# otherwise materialize the whole BIMElement table in memory before the
# service even starts grouping. The Python-side filter below still
# evaluates per row, so the cap is "the first N matching rows" — paired
# with element_count desc grouping, the cap rarely matters in practice
# but protects against OOM on pathological imports.
_MAX_ELEMENTS_PER_SESSION = 200_000
# Stream rows in chunks so SQLAlchemy doesn't buffer the whole result
# set into a list before we touch the first row.
_YIELD_PER = 2_000


def _read_attr(element: BIMElement, key: str) -> Any:
    """‌⁠‍Best-effort lookup across Bim element attributes.

    BIM extractors store some keys as columns (``element_type``, ``storey``,
    ``discipline``) and others inside ``properties``. The match-elements
    user picks attribute names from a unified namespace, so this helper
    hides the storage difference.
    """
    if key in ("ifc_class", "category", "element_type"):
        return element.element_type
    if key in ("level", "storey"):
        return element.storey
    if key == "discipline":
        return element.discipline
    if key == "name":
        return element.name
    if key == "type_name":
        # Revit "Type Name" lives in properties on most extractors.
        props = element.properties or {}
        return props.get("type_name") or props.get("Type") or props.get("Family") or element.element_type
    props = element.properties or {}
    if key in props:
        return props.get(key)
    # Fall back to a case-insensitive scan — Revit family params arrive
    # with various capitalisations.
    key_lower = key.lower()
    for k, v in props.items():
        if k.lower() == key_lower:
            return v
    return None


def _net_quantities(
    raw: dict[str, Any],
    properties: dict[str, Any],
    use_net: bool,
) -> dict[str, float]:
    """‌⁠‍Build the rolled-up quantity dict for a single element."""
    out: dict[str, float] = {}

    def _f(d: dict[str, Any], *keys: str) -> float | None:
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    gross_vol = _f(properties, "gross_volume_m3", "volume_gross_m3")
    open_vol = _f(properties, "openings_volume_m3", "voids_volume_m3")
    raw_vol = _f(raw, "volume_m3", "volume", "Volume")
    if gross_vol is not None:
        out["gross_volume_m3"] = gross_vol
        net = gross_vol - (open_vol or 0.0)
        out["net_volume_m3"] = net
        out["volume_m3"] = net if use_net else gross_vol
    elif raw_vol is not None:
        out["volume_m3"] = raw_vol
        out["gross_volume_m3"] = raw_vol
        out["net_volume_m3"] = raw_vol

    gross_area = _f(properties, "gross_area_m2", "area_gross_m2")
    open_area = _f(properties, "openings_area_m2", "voids_area_m2")
    raw_area = _f(raw, "area_m2", "area", "Area")
    if gross_area is not None:
        out["gross_area_m2"] = gross_area
        net_a = gross_area - (open_area or 0.0)
        out["net_area_m2"] = net_a
        out["area_m2"] = net_a if use_net else gross_area
    elif raw_area is not None:
        out["area_m2"] = raw_area

    length = _f(raw, "length_m", "length", "Length")
    if length is not None:
        out["length_m"] = length

    count = _f(raw, "count", "Count")
    out["count"] = count if count is not None else 1.0
    return out


class BIMSourceAdapter:
    """Reads BIM elements for the match-elements service."""

    source_name: str = "bim"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_attribute_keys(
        self,
        project_id: uuid.UUID,
        bim_model_id: uuid.UUID | None = None,
    ) -> list[str]:
        """Sample the first 200 elements of the project to figure out
        which attribute keys are populated. This drives the chip-bar's
        drag-source list."""
        stmt = (
            select(BIMElement.properties, BIMElement.element_type)
            .join(BIMModel, BIMElement.model_id == BIMModel.id)
            .where(BIMModel.project_id == project_id)
            .limit(200)
        )
        if bim_model_id is not None:
            stmt = stmt.where(BIMElement.model_id == bim_model_id)
        result = await self.session.execute(stmt)
        keys: set[str] = {"ifc_class", "type_name", "level", "discipline"}
        for props, _et in result.all():
            if isinstance(props, dict):
                keys.update(props.keys())
        # Prefer canonical order, then everything else alphabetically.
        ordered = [k for k in _GROUP_BY_KEY_ORDER if k in keys]
        ordered.extend(sorted(k for k in keys if k not in _GROUP_BY_KEY_ORDER))
        return ordered

    async def list_categories(
        self,
        project_id: uuid.UUID,
        bim_model_id: uuid.UUID | None = None,
    ) -> list[tuple[str, int]]:
        """Return ``[(ifc_class, count), ...]`` for the scope-filter chip-bar."""
        from sqlalchemy import func

        stmt = (
            select(BIMElement.element_type, func.count(BIMElement.id))
            .join(BIMModel, BIMElement.model_id == BIMModel.id)
            .where(BIMModel.project_id == project_id)
            .group_by(BIMElement.element_type)
            .order_by(func.count(BIMElement.id).desc())
        )
        if bim_model_id is not None:
            stmt = stmt.where(BIMElement.model_id == bim_model_id)
        result = await self.session.execute(stmt)
        return [(row[0] or "Unknown", int(row[1])) for row in result.all()]

    async def iter_elements(
        self,
        *,
        project_id: uuid.UUID,
        bim_model_id: uuid.UUID | None = None,
        filters: dict[str, list[Any]] | None = None,
        excluded_categories: list[str] | None = None,
        use_net_quantities: bool = True,
    ) -> list[SourceElement]:
        """Load all elements for the project, applying scope filters.

        Filters are applied at the Python layer for free-form property
        keys; ``ifc_class`` (== ``element_type``) gets a SQL filter for
        speed since most projects exclude IfcSite/IfcFurniture-style
        categories at scope time.
        """
        excluded = set(excluded_categories or [])

        stmt = (
            select(BIMElement, BIMModel.id.label("bim_model_id"))
            .join(BIMModel, BIMElement.model_id == BIMModel.id)
            .where(BIMModel.project_id == project_id)
        )
        if bim_model_id is not None:
            stmt = stmt.where(BIMElement.model_id == bim_model_id)
        if excluded:
            stmt = stmt.where(BIMElement.element_type.notin_(list(excluded)))

        # SQL-level filter for ifc_class, since it's the most common chip
        # filter and lives in a column.
        if filters:
            ifc_filter = filters.get("ifc_class")
            if ifc_filter:
                stmt = stmt.where(
                    BIMElement.element_type.in_(list(ifc_filter)),
                )

        stmt = stmt.limit(_MAX_ELEMENTS_PER_SESSION)
        result = await self.session.stream(
            stmt.execution_options(yield_per=_YIELD_PER),
        )

        out: list[SourceElement] = []
        async for elem, model_uuid in result:
            elem: BIMElement
            props = elem.properties or {}

            # Python-side filter for non-ifc_class keys.
            if filters:
                skip = False
                for fkey, fvals in filters.items():
                    if fkey == "ifc_class":
                        continue
                    actual = _read_attr(elem, fkey)
                    if actual is None or actual not in fvals:
                        skip = True
                        break
                if skip:
                    continue

            # Build the unified attributes dict — group-by reads from this.
            attrs: dict[str, Any] = {
                "ifc_class": elem.element_type,
                "category": elem.element_type,
                "level": elem.storey,
                "discipline": elem.discipline,
                "name": elem.name,
                "type_name": _read_attr(elem, "type_name"),
            }
            # Pass through every property key — group-by can target any of them.
            attrs.update(props)

            qty = _net_quantities(elem.quantities or {}, props, use_net_quantities)

            out.append(
                SourceElement(
                    id=str(elem.id),
                    category=elem.element_type or "Unknown",
                    name=elem.name,
                    attributes=attrs,
                    quantities=qty,
                    raw_ref=str(model_uuid),
                )
            )
        return out
