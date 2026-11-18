# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Item-code patterns per classification standard, edition and subdivision.

The data lives in ``country_data/item_code_patterns.json``; this module only
reads it. A standard names its editions, each with the patterns a code of that
edition may take, and optional subdivision overlays (a provincial prefix) that
add patterns for projects located there. The uniqueness scope says where a code
may not repeat: the whole bill, one section, or one sub-project.

Standard library only. Nothing here may import from ``app.modules``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "DATA_PATH",
    "code_patterns",
    "default_edition_key",
    "editions",
    "standard_entry",
    "standard_for_country",
    "uniqueness_scope",
]

DATA_PATH = Path(__file__).resolve().parent / "country_data" / "item_code_patterns.json"


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def standard_entry(standard: str) -> dict[str, Any]:
    """The raw entry of one classification standard, or an empty dict."""
    entry = (_data().get("standards") or {}).get((standard or "").strip().lower())
    return entry if isinstance(entry, dict) else {}


def standard_for_country(country: str) -> str | None:
    """The standard whose data names ``country``, or ``None``."""
    wanted = (country or "").strip().upper()
    if not wanted:
        return None
    for key, entry in (_data().get("standards") or {}).items():
        if isinstance(entry, dict) and str(entry.get("country") or "").upper() == wanted:
            return str(key)
    return None


def default_edition_key(standard: str) -> str | None:
    """The edition a project of this standard takes when it states none."""
    value = standard_entry(standard).get("default_edition")
    return str(value) if value else None


def editions(standard: str) -> list[dict[str, Any]]:
    """The editions of a standard as ``{"key", "label", "in_force_from"}`` rows, oldest first."""
    rows = [
        {"key": key, "label": str(row.get("label") or key), "in_force_from": row.get("in_force_from")}
        for key, row in (standard_entry(standard).get("editions") or {}).items()
        if isinstance(row, dict)
    ]
    return sorted(rows, key=lambda row: str(row["in_force_from"] or ""))


def code_patterns(standard: str, edition: str | None = None, subdivision: str | None = None) -> list[str]:
    """The patterns a code may match for this standard, edition and subdivision.

    An unknown edition falls back to the standard's default edition, so a bill
    whose edition is not recorded is still checked against something stated.
    A subdivision overlay adds patterns; it never removes the national ones.
    """
    entry = standard_entry(standard)
    editions = entry.get("editions") or {}
    chosen = editions.get(edition or "") or editions.get(entry.get("default_edition") or "") or {}
    patterns = list(chosen.get("patterns") or [])
    overlay = (entry.get("subdivisions") or {}).get((subdivision or "").strip().upper()) or {}
    patterns.extend(overlay.get("patterns") or [])
    return patterns


def uniqueness_scope(standard: str) -> str:
    """Where a code of this standard may not repeat: bill, section or sub_project."""
    return str(standard_entry(standard).get("uniqueness_scope") or "bill")
