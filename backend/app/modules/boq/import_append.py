"""Allocate fresh ordinal roots for an explicitly repeated native import."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def append_import_ordinals(rows: list[dict[str, Any]], existing: Iterable[str]) -> None:
    """Remap a colliding, ID-free tree without changing stored rows or source codes.

    Only the import-again path calls this. Keep non-colliding imports and
    Position-ID round trips exactly as supplied. Reserve complete roots so a
    new section cannot accidentally adopt existing descendants.
    """
    occupied = {str(value).strip() for value in existing}
    if any(row.get("position_id") for row in rows):
        return
    if not any(str(row["ordinal"]).strip() in occupied for row in rows):
        return
    used_roots = {ordinal.split(".", 1)[0] for ordinal in occupied}
    next_root = max((int(root) for root in used_roots if root.isdecimal()), default=0) + 1
    roots: dict[str, str] = {}
    for row in rows:
        root = str(row["ordinal"]).strip().split(".", 1)[0]
        if root not in roots:
            while str(next_root) in used_roots:
                next_root += 1
            roots[root] = str(next_root)
            used_roots.add(str(next_root))
            next_root += 1

    def remap(value: str) -> str:
        root, separator, tail = value.strip().partition(".")
        return roots.get(root, root) + separator + tail

    for row in rows:
        original = str(row["ordinal"])
        row["ordinal"] = remap(original)
        for field in ("metadata", "classification"):
            values = dict(row.get(field) or {})
            for key in ("gaeb_section", "import_section"):
                if values.get(key):
                    values[key] = remap(str(values[key]))
            if field == "metadata":
                values.setdefault("import_original_ordinal", original)
            row[field] = values
