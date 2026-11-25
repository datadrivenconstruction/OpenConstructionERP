# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rules for a user's named sidebar layouts.

A layout is a saved arrangement of the left menu (hidden rows and sections,
pins, order, work mode) under a name the user chose. The list lives in the
user's ``metadata_`` JSON under ``sidebar_layouts``. Pure functions: no
database, no request; the router turns :class:`SidebarLayoutError` into 422.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

MAX_LAYOUTS_PER_USER = 20
MAX_NAME_LENGTH = 60
MAX_ID_LENGTH = 64
MAX_DATA_BYTES = 64 * 1024


class SidebarLayoutError(ValueError):
    """A layout rule failed; ``code`` is stable and maps to a UI message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalise_name(raw: object) -> str:
    """Trim and check one layout name (non-empty, at most 60 characters)."""
    if not isinstance(raw, str):
        raise SidebarLayoutError("name_empty", "Layout name is required")
    name = " ".join(raw.split())
    if not name:
        raise SidebarLayoutError("name_empty", "Layout name is required")
    if len(name) > MAX_NAME_LENGTH:
        raise SidebarLayoutError("name_too_long", f"Layout name is longer than {MAX_NAME_LENGTH} characters")
    return name


def validate_layouts(raw_layouts: Sequence[object]) -> list[dict[str, Any]]:
    """Validate the whole list a client wants to store and return the clean copy.

    Names must be unique per user, compared case-insensitively. The list is
    capped at :data:`MAX_LAYOUTS_PER_USER` and each layout's data at 64 KB so a
    runaway client cannot bloat the user record.
    """
    if len(raw_layouts) > MAX_LAYOUTS_PER_USER:
        raise SidebarLayoutError("too_many", f"At most {MAX_LAYOUTS_PER_USER} layouts are allowed")
    cleaned: list[dict[str, Any]] = []
    names: set[str] = set()
    ids: set[str] = set()
    for raw in raw_layouts:
        if not isinstance(raw, dict):
            raise SidebarLayoutError("invalid", "Layout must be an object")
        name = normalise_name(raw.get("name"))
        key = name.casefold()
        if key in names:
            raise SidebarLayoutError("name_taken", "A layout with this name already exists")
        names.add(key)
        layout_id = raw.get("id")
        if not isinstance(layout_id, str) or not layout_id.strip() or len(layout_id) > MAX_ID_LENGTH:
            raise SidebarLayoutError("invalid", "Layout id is missing or too long")
        if layout_id in ids:
            raise SidebarLayoutError("invalid", "Layout ids must be unique")
        ids.add(layout_id)
        data = raw.get("data")
        if not isinstance(data, dict):
            raise SidebarLayoutError("invalid", "Layout data must be an object")
        if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > MAX_DATA_BYTES:
            raise SidebarLayoutError("too_large", "Layout data is too large")
        cleaned.append({"id": layout_id, "name": name, "data": data})
    return cleaned


def read_layouts(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Stored layouts from user metadata; malformed entries are dropped."""
    raw = (metadata or {}).get("sidebar_layouts", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:MAX_LAYOUTS_PER_USER]:
        if (
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("data"), dict)
        ):
            out.append({"id": item["id"], "name": item["name"], "data": item["data"]})
    return out
