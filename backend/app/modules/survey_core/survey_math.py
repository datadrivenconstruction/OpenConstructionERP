# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plain survey arithmetic (no database, no I/O).

Closed traverse: linear misclosure ``f = sqrt(fE^2 + fN^2)``, ratio ``1:(L/f)``,
Bowditch correction ``cE_i = -fE * l_i / L`` (same for N). Level run: the
allowed misclosure is ``k * sqrt(km)`` millimetres, ``k`` from a profile.
"""

from __future__ import annotations

import math

#: Two readings of one point id closer than this in E, N and Z are the same point.
SAME_POINT_TOLERANCE_M = 0.001


def linear_misclosure(f_e: float, f_n: float) -> float:
    """Linear misclosure of a closed traverse in metres."""
    return math.hypot(f_e, f_n)


def misclosure_ratio(length_m: float, misclosure_m: float) -> int | None:
    """``x`` in ``1:x``; ``None`` for a perfect closure. Higher is better."""
    if misclosure_m <= 0:
        return None
    return round(length_m / misclosure_m)


def bowditch_correction(f_e: float, f_n: float, leg_m: float, length_m: float) -> tuple[float, float]:
    """Bowditch (compass rule) correction of one leg, in metres.

    Raises:
        ValueError: when the traverse has no length.
    """
    if length_m <= 0:
        raise ValueError("traverse length must be positive")
    share = leg_m / length_m
    return -f_e * share, -f_n * share


def level_allowed_mm(k_mm: float, distance_km: float) -> float:
    """Allowed level-run misclosure ``k * sqrt(km)`` in millimetres."""
    return k_mm * math.sqrt(max(distance_km, 0.0))


def same_position(
    a: tuple[float, float, float | None],
    b: tuple[float, float, float | None],
    tol: float = SAME_POINT_TOLERANCE_M,
) -> bool:
    """Whether two readings describe one position (a missing height differs from any height)."""
    if abs(a[0] - b[0]) > tol or abs(a[1] - b[1]) > tol:
        return False
    if a[2] is None or b[2] is None:
        return a[2] is None and b[2] is None
    return abs(a[2] - b[2]) <= tol
