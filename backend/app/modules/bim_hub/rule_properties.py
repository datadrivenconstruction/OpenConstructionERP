# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Properties a filter names that an element's database row does not carry.

The CAD import keeps at most 30 properties per element row
(``ifc_processor._excel_elements_to_bim_result``), while the model's Parquet
sidecar keeps every column. Property search reads the sidecar, so without this
a quantity rule, a dynamic group or the change review on a parameter the cap
dropped matched nothing while property search found the elements.

Callers name the keys each element is missing; this reads just those columns
for just those elements from the sidecar, matched by the sidecar ``id`` (the
element's ``mesh_ref``, else its ``stable_id``, the same pairing the viewer
uses). Values come back cleaned the way the import cleans a property, and are
merged into a COPY of the properties: the database rows are never touched.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub import dataframe_store
from app.modules.bim_hub.smart_views import _resolve_field

# What the import drops as "no value" (``_excel_elements_to_bim_result``).
_EMPTY_VALUES = ("none", "null", "n/a")
_MAX_VALUE_LENGTH = 500


@dataclass
class RuleSubject:
    """What the rule engine reads of an element, with the missing properties filled in."""

    element_type: str | None
    properties: dict[str, Any] = field(default_factory=dict)
    quantities: dict[str, Any] = field(default_factory=dict)


def rule_property_keys(property_filter: Any, quantity_source: str | None = None) -> list[str]:
    """The property keys a filter (and a ``property:`` quantity source) reads."""
    keys = [str(k) for k in (property_filter or {}) if str(k).strip()] if isinstance(property_filter, dict) else []
    source = str(quantity_source or "")
    if source.startswith("property:") and source[len("property:") :].strip():
        keys.append(source[len("property:") :])
    return list(dict.fromkeys(keys))


def missing_keys(element: Any, keys: Iterable[str]) -> list[str]:
    """The keys of *keys* the element's own properties do not answer."""
    return [k for k in keys if _resolve_field(element, f"properties.{k}") is None]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in _EMPTY_VALUES:
        return None
    return text[:_MAX_VALUE_LENGTH]


def read_missing_properties(
    project_id: str,
    model_id: str,
    wants: Sequence[tuple[Any, list[str]]],
) -> list[dict[str, str]]:
    """Sidecar values for each ``(element, missing keys)``, aligned with *wants*.

    Blocking (Parquet I/O): call through ``asyncio.to_thread``. Elements of
    one model only. An element the sidecar has no row for, or whose cells are
    empty, gets ``{}``.
    """
    out: list[dict[str, str]] = [{} for _ in wants]
    index: dict[str, int] = {}
    # mesh_ref first: on a DDC model the sidecar id IS the mesh_ref, and a
    # stable_id that happens to equal another element's mesh_ref must not win.
    for attr in ("mesh_ref", "stable_id"):
        for i, (element, _keys) in enumerate(wants):
            ref = getattr(element, attr, None)
            if ref is not None and str(ref).strip():
                index.setdefault(str(ref).strip(), i)
    all_keys = list(dict.fromkeys(k for _el, keys in wants for k in keys))
    if not index or not all_keys:
        return out
    columns, cells = dataframe_store.read_element_cells(project_id, model_id, keys=all_keys, ids=list(index))
    if not columns:
        return out
    for row_id, row in cells.items():
        i = index.get(row_id)
        if i is None:
            continue
        for key in wants[i][1]:
            column = columns.get(key)
            value = _clean(row.get(column)) if column is not None else None
            if value is not None:
                out[i][column] = value  # type: ignore[index]
    return out


async def fill_missing_properties(
    session: AsyncSession,
    wants: Sequence[tuple[Any, list[str]]],
) -> list[dict[str, str]]:
    """:func:`read_missing_properties` for elements of any number of models.

    Each element needs ``model_id``; the project comes from its model row.
    Returns the values to add per element, aligned with *wants*.
    """
    from app.modules.bim_hub.models import BIMModel

    out: list[dict[str, str]] = [{} for _ in wants]
    by_model: dict[uuid.UUID, list[int]] = {}
    for i, (element, keys) in enumerate(wants):
        model_id = getattr(element, "model_id", None)
        if model_id is not None and keys:
            by_model.setdefault(model_id, []).append(i)
    if not by_model:
        return out
    rows = await session.execute(select(BIMModel.id, BIMModel.project_id).where(BIMModel.id.in_(list(by_model))))
    projects = {row[0]: row[1] for row in rows}
    for model_id, indices in by_model.items():
        project_id = projects.get(model_id)
        if project_id is None:
            continue
        found = await asyncio.to_thread(
            read_missing_properties, str(project_id), str(model_id), [wants[i] for i in indices]
        )
        for i, values in zip(indices, found, strict=True):
            out[i] = values
    return out


def with_properties(element: Any, extra: dict[str, str]) -> RuleSubject:
    """A rule subject reading as *element* plus *extra*, the values its row lacked."""
    return RuleSubject(
        element_type=getattr(element, "element_type", None),
        properties={**(getattr(element, "properties", None) or {}), **extra},
        quantities=dict(getattr(element, "quantities", None) or {}),
    )
