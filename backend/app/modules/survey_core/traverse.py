# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closed traverses and level runs: read the legs, compute the closure, judge it.

A traverse file has one row per leg with its measured length and coordinate
differences (``leg,from,to,length_m,d_e,d_n``). Round a closed loop the
differences should sum to zero; what is left is the misclosure. This is the
check field software already did, repeated here so the closure travels with
the project; it is not a least-squares adjustment.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from app.modules.survey_core.survey_math import (
    bowditch_correction,
    level_allowed_mm,
    linear_misclosure,
    misclosure_ratio,
)

PASS = "pass"
FAIL = "fail"
NO_PROFILE = "no_profile"
_HEADER_ALIASES = {
    "leg": "leg",
    "from": "from",
    "to": "to",
    "length_m": "length_m",
    "length": "length_m",
    "distance": "length_m",
    "d_e": "d_e",
    "de": "d_e",
    "delta_e": "d_e",
    "d_n": "d_n",
    "dn": "d_n",
    "delta_n": "d_n",
}


@dataclass
class Leg:
    leg: str
    start: str
    end: str
    length_m: float
    d_e: float
    d_n: float


@dataclass
class TraverseResult:
    length_m: float
    f_e: float
    f_n: float
    misclosure_m: float
    ratio: int | None
    corrections: list[tuple[float, float]] = field(default_factory=list)


def parse_legs(text: str) -> list[Leg]:
    """Legs from CSV text with a header row naming the columns.

    Raises:
        ValueError: when a column is missing or a number cannot be read.
    """
    rows = [r for r in csv.reader(io.StringIO(text.lstrip("﻿"))) if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("The traverse file is empty")
    header = [_HEADER_ALIASES.get(c.strip().lower(), c.strip().lower()) for c in rows[0]]
    missing = {"length_m", "d_e", "d_n"} - set(header)
    if missing:
        raise ValueError(f"The traverse file needs the columns {', '.join(sorted(missing))}")
    col = {name: i for i, name in enumerate(header)}
    legs: list[Leg] = []
    for line, row in enumerate(rows[1:], start=2):

        def cell(name: str, row: list[str] = row) -> str:
            i = col.get(name)
            return row[i].strip() if i is not None and i < len(row) else ""

        try:
            legs.append(
                Leg(
                    leg=cell("leg") or str(len(legs) + 1),
                    start=cell("from"),
                    end=cell("to"),
                    length_m=float(cell("length_m")),
                    d_e=float(cell("d_e")),
                    d_n=float(cell("d_n")),
                )
            )
        except ValueError as exc:
            raise ValueError(f"Line {line}: a number cannot be read") from exc
    if not legs:
        raise ValueError("The traverse file has no legs")
    return legs


def close_traverse(legs: list[Leg]) -> TraverseResult:
    """Misclosure, ratio and Bowditch corrections of a closed loop of legs."""
    length = sum(leg.length_m for leg in legs)
    if length <= 0:
        raise ValueError("The traverse has no length")
    f_e = sum(leg.d_e for leg in legs)
    f_n = sum(leg.d_n for leg in legs)
    f = linear_misclosure(f_e, f_n)
    return TraverseResult(
        length_m=length,
        f_e=f_e,
        f_n=f_n,
        misclosure_m=f,
        ratio=misclosure_ratio(length, f),
        corrections=[bowditch_correction(f_e, f_n, leg.length_m, length) for leg in legs],
    )


def traverse_verdict(ratio: int | None, profile_ratio: int | None) -> str:
    """Pass when ``1:ratio`` is at least as good as ``1:profile_ratio``; no profile, no verdict."""
    if not profile_ratio:
        return NO_PROFILE
    if ratio is None:
        return PASS
    return PASS if ratio >= profile_ratio else FAIL


def level_verdict(misclosure_mm: float, distance_km: float, k_mm: float | None) -> tuple[float | None, str]:
    """Allowed misclosure ``k * sqrt(km)`` and the verdict; no ``k``, no verdict."""
    if not k_mm:
        return None, NO_PROFILE
    allowed = level_allowed_mm(k_mm, distance_km)
    return allowed, (PASS if abs(misclosure_mm) <= allowed else FAIL)


__all__ = [
    "FAIL",
    "NO_PROFILE",
    "PASS",
    "Leg",
    "TraverseResult",
    "close_traverse",
    "level_verdict",
    "parse_legs",
    "traverse_verdict",
]
