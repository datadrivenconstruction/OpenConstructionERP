# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Suggested supplier on BOQ material resources (issue #516).

An estimator can name the supplier they expect a material to come from. The
suggestion is a Vendor directory id, stored in the position's metadata:

* ``metadata_["suggested_vendor_id"]`` is the position default;
* ``metadata_["resources"][i]["suggested_vendor_id"]`` is a material resource's own.

A resource's own suggestion wins over the position default. Nothing here takes
part in pricing: ``unit_rate``, ``total`` and the resource quantities are never
read or written, so the estimating calculations stay exactly as they were.

The Vendor directory belongs to the supplier catalogue module. The BOQ does not
depend on it, so the lookup is lazy, and an install without the module cannot
name a supplier (422) rather than storing an id nobody can resolve.

A requisition raised from the BOQ copies the effective suggestion of each
source when it is written, so a later edit here does not rewrite a requisition
someone has already sent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import Position
from app.modules.price_breakdown import ResourceKind, coerce_kind

#: Metadata key on the position and on each resource dict.
SUGGESTED_VENDOR_KEY = "suggested_vendor_id"

#: Where an effective suggestion came from.
ORIGIN_RESOURCE = "resource"
ORIGIN_POSITION = "position"


def resource_key_in_split(res: Mapping[str, Any], index: int) -> str:
    """A reference to one resource within a position's resource split.

    The resource's own ``id`` when it carries one, otherwise its index and code
    (``"2:CWICR-123"``), or the index alone. The buy list names its sources with
    the same reference, so a requisition source finds its resource again.
    """
    own = str(res.get("id") or "").strip()
    if own:
        return own
    code = str(res.get("code") or "").strip()
    return f"{index}:{code}" if code else str(index)


def _as_uuid(raw: object) -> uuid.UUID | None:
    if raw is None or raw == "":
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _meta(position: Position | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(position, Mapping):
        meta = position.get("metadata_") or position.get("metadata") or {}
    else:
        meta = position.metadata_ or {}
    return meta if isinstance(meta, Mapping) else {}


def _resources(meta: Mapping[str, Any]) -> list[Any]:
    resources = meta.get("resources")
    return resources if isinstance(resources, list) else []


def is_material(res: Mapping[str, Any]) -> bool:
    """Whether a resource dict is a material, read the way the buy list reads it."""
    return coerce_kind(res.get("type") or res.get("resource_type") or res.get("kind")) is ResourceKind.MATERIAL


def effective_suggestion(
    meta: Mapping[str, Any],
    res: Mapping[str, Any] | None,
) -> tuple[uuid.UUID | None, str | None]:
    """The suggested supplier of one resource and where it came from.

    The resource's own suggestion, else the position default, else none.
    """
    if res is not None:
        own = _as_uuid(res.get(SUGGESTED_VENDOR_KEY))
        if own is not None:
            return own, ORIGIN_RESOURCE
    default = _as_uuid(meta.get(SUGGESTED_VENDOR_KEY))
    if default is not None:
        return default, ORIGIN_POSITION
    return None, None


def find_resource(meta: Mapping[str, Any], resource_key: str) -> tuple[int, Mapping[str, Any]] | None:
    """The index and dict of the resource a key names, or None."""
    for index, res in enumerate(_resources(meta)):
        if isinstance(res, Mapping) and resource_key_in_split(res, index) == resource_key:
            return index, res
    return None


async def resolve_suggested_vendors(
    session: AsyncSession,
    sources: Iterable[tuple[uuid.UUID | None, str | None]],
) -> dict[tuple[uuid.UUID, str | None], uuid.UUID | None]:
    """The effective suggestion for each (position id, resource key) pair, in one query.

    A pair whose position is gone, or whose key names no resource, gets the
    position default when the position exists and None otherwise.
    """
    pairs = {(pid, key) for pid, key in sources if pid is not None}
    if not pairs:
        return {}
    ids = {pid for pid, _key in pairs}
    rows = (await session.execute(select(Position.id, Position.metadata_).where(Position.id.in_(ids)))).all()
    metas = {row.id: (row.metadata_ if isinstance(row.metadata_, Mapping) else {}) for row in rows}
    out: dict[tuple[uuid.UUID, str | None], uuid.UUID | None] = {}
    for pid, key in pairs:
        meta = metas.get(pid)
        if meta is None:
            out[(pid, key)] = None
            continue
        found = find_resource(meta, key) if key else None
        out[(pid, key)] = effective_suggestion(meta, found[1] if found else None)[0]
    return out


async def load_vendor_entries(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
    """``{vendor id: (name, status)}`` from the Vendor directory; empty without the module."""
    if not ids:
        return {}
    try:
        from app.modules.supplier_catalogs.models import Vendor  # noqa: PLC0415
    except ImportError:  # pragma: no cover - module not installed
        return {}
    rows = (await session.execute(select(Vendor.id, Vendor.name, Vendor.status).where(Vendor.id.in_(ids)))).all()
    return {row.id: (row.name, row.status) for row in rows}


class SupplierSuggestionService:
    """Read and set the suggested supplier of a position and its material resources."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def describe(self, position: Position) -> dict[str, Any]:
        """The position default and one entry per material resource, with vendor names."""
        meta = _meta(position)
        default = _as_uuid(meta.get(SUGGESTED_VENDOR_KEY))
        entries: list[dict[str, Any]] = []
        wanted: set[uuid.UUID] = {default} if default else set()
        for index, res in enumerate(_resources(meta)):
            if not isinstance(res, Mapping) or not is_material(res):
                continue
            own = _as_uuid(res.get(SUGGESTED_VENDOR_KEY))
            effective, origin = effective_suggestion(meta, res)
            if own:
                wanted.add(own)
            entries.append(
                {
                    "resource_key": resource_key_in_split(res, index),
                    "name": str(res.get("name") or res.get("description") or res.get("code") or "").strip() or "-",
                    "code": str(res.get("code") or "").strip() or None,
                    "unit": str(res.get("unit") or "").strip() or None,
                    "suggested_vendor_id": own,
                    "effective_vendor_id": effective,
                    "origin": origin,
                }
            )
        names = await load_vendor_entries(self.session, wanted)

        def _name(vid: uuid.UUID | None) -> str | None:
            return names[vid][0] if vid and vid in names else None

        def _status(vid: uuid.UUID | None) -> str | None:
            return names[vid][1] if vid and vid in names else None

        for entry in entries:
            entry["effective_vendor_name"] = _name(entry["effective_vendor_id"])
            entry["effective_vendor_status"] = _status(entry["effective_vendor_id"])
        return {
            "position_id": position.id,
            "default_vendor_id": default,
            "default_vendor_name": _name(default),
            "default_vendor_status": _status(default),
            "resources": entries,
        }

    async def set_suggestion(
        self,
        position: Position,
        *,
        vendor_id: uuid.UUID | None,
        resource_key: str | None,
    ) -> bool:
        """Set or clear one suggestion. Returns whether anything changed.

        ``resource_key`` None targets the position default. A vendor id must be
        in the Vendor directory (any status: whether a suspended supplier may be
        ordered from is asked when a requisition is approved). The metadata dict
        and the resource list are replaced, not mutated, so the ORM sees the
        change; no other key is touched.
        """
        if vendor_id is not None and vendor_id not in await load_vendor_entries(self.session, {vendor_id}):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Vendor {vendor_id} is not in the Vendor directory.",
            )
        meta = dict(_meta(position))
        value = str(vendor_id) if vendor_id else None
        if resource_key is None:
            if meta.get(SUGGESTED_VENDOR_KEY) == value or (value is None and SUGGESTED_VENDOR_KEY not in meta):
                return False
            if value is None:
                meta.pop(SUGGESTED_VENDOR_KEY, None)
            else:
                meta[SUGGESTED_VENDOR_KEY] = value
            position.metadata_ = meta
            return True

        found = find_resource(meta, resource_key)
        if found is None or not is_material(found[1]):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Position {position.id} has no material resource '{resource_key}'.",
            )
        index, res = found
        if res.get(SUGGESTED_VENDOR_KEY) == value or (value is None and SUGGESTED_VENDOR_KEY not in res):
            return False
        updated = dict(res)
        if value is None:
            updated.pop(SUGGESTED_VENDOR_KEY, None)
        else:
            updated[SUGGESTED_VENDOR_KEY] = value
        resources = list(_resources(meta))
        resources[index] = updated
        meta["resources"] = resources
        position.metadata_ = meta
        return True
