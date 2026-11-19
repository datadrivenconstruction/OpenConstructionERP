# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closure and boundary-corner classes contributed by country data.

Core holds no class value. ``country_data/survey_tolerances.json`` lists, per
ISO country, traverse/levelling closure classes (``angular_k_sec``,
``traverse_min_ratio``, ``level_k_mm``) and boundary-corner classes
(``base_m + ppm``), each with its source. A class is offered only while its
country is an active market, and it is applied only when the surveyor picks it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[2] / "core" / "country_data" / "survey_tolerances.json"


@dataclass(frozen=True)
class ClosureClass:
    key: str
    label: str
    country: str
    source: str
    status: str = ""
    angular_k_sec: float | None = None
    traverse_min_ratio: int | None = None
    level_k_mm: float | None = None


@dataclass(frozen=True)
class CornerClass:
    key: str
    label: str
    country: str
    source: str
    base_m: float
    ppm: float = 0.0
    status: str = ""


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _countries(markets: Iterable[str]) -> list[str]:
    from app.core.active_markets import pack_active  # noqa: PLC0415

    markets = list(markets)
    return [c for c in sorted(k for k in _data() if not k.startswith("_")) if pack_active(markets, [c])]


def closure_classes(markets: Iterable[str]) -> list[ClosureClass]:
    """Closure classes of the active markets, in file order."""
    out = []
    for country in _countries(markets):
        for row in _data()[country].get("closure_classes", []):
            out.append(
                ClosureClass(
                    key=row["key"],
                    label=row["label"],
                    country=country,
                    source=row.get("source", ""),
                    status=row.get("status", ""),
                    angular_k_sec=row.get("angular_k_sec"),
                    traverse_min_ratio=row.get("traverse_min_ratio"),
                    level_k_mm=row.get("level_k_mm"),
                )
            )
    return out


def corner_classes(markets: Iterable[str]) -> list[CornerClass]:
    """Boundary-corner precision classes of the active markets."""
    out = []
    for country in _countries(markets):
        for row in _data()[country].get("corner_classes", []):
            out.append(
                CornerClass(
                    key=row["key"],
                    label=row["label"],
                    country=country,
                    source=row.get("source", ""),
                    base_m=float(row["base_m"]),
                    ppm=float(row.get("ppm") or 0),
                    status=row.get("status", ""),
                )
            )
    return out


def find_closure(key: str, markets: Iterable[str]) -> ClosureClass | None:
    return next((c for c in closure_classes(markets) if c.key == key), None)


def find_corner(key: str, markets: Iterable[str]) -> CornerClass | None:
    return next((c for c in corner_classes(markets) if c.key == key), None)


__all__ = ["ClosureClass", "CornerClass", "closure_classes", "corner_classes", "find_closure", "find_corner"]
