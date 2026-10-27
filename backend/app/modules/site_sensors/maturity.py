# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Concrete maturity​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ by the Nurse-Saul function of ASTM C1074, and strength from a mix curve.

``M(t) = sum((T_avg - T0) * dt)`` over the intervals where the mean
temperature is above the datum ``T0``, in degC-hours. Strength follows the
mix's calibrated curve ``S = a + b * log10(M)``. Pure functions, floats in,
floats out: a temperature probe is not more exact than that.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime

__all__ = ["hours_to_strength", "maturity_for_strength", "nurse_saul", "strength_from_maturity"]


def nurse_saul(readings: Iterable[tuple[datetime, float]], datum_c: float = -10.0) -> list[tuple[datetime, float]]:
    """Cumulative maturity after each reading (the first reading is 0).

    Args:
        readings: ``(time, temperature degC)``, any order.
        datum_c: Datum temperature T0.

    Returns:
        ``(time, maturity degC-h)`` in time order.
    """
    rows = sorted(readings, key=lambda r: r[0])
    out: list[tuple[datetime, float]] = []
    total = 0.0
    for i, (t, temp) in enumerate(rows):
        if i:
            t_prev, temp_prev = rows[i - 1]
            dt_h = (t - t_prev).total_seconds() / 3600.0
            mean = (temp + temp_prev) / 2.0
            if dt_h > 0 and mean > datum_c:
                total += (mean - datum_c) * dt_h
        out.append((t, total))
    return out


def strength_from_maturity(maturity: float, a: float, b: float) -> float:
    """Estimated compressive strength in MPa (0 before any maturity)."""
    if maturity <= 1.0:
        return 0.0
    return max(0.0, a + b * math.log10(maturity))


def maturity_for_strength(strength: float, a: float, b: float) -> float | None:
    """Maturity the mix needs to reach ``strength``, None for a flat or falling curve."""
    if b <= 0:
        return None
    return 10 ** ((strength - a) / b)


def hours_to_strength(
    series: list[tuple[datetime, float]], target_maturity: float, window_h: float = 24.0
) -> float | None:
    """Hours until ``target_maturity`` at the recent rate of gain; 0 when reached, None when not gaining."""
    if not series:
        return None
    t_last, m_last = series[-1]
    if m_last >= target_maturity:
        return 0.0
    recent = [(t, m) for t, m in series if (t_last - t).total_seconds() <= window_h * 3600]
    t0, m0 = recent[0]
    span_h = (t_last - t0).total_seconds() / 3600.0
    if span_h <= 0 or m_last <= m0:
        return None
    rate = (m_last - m0) / span_h
    return (target_maturity - m_last) / rate
