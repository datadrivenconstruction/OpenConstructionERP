# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Concrete maturity​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ and strength (ASTM C1074): Nurse-Saul, equivalent age, a calibrated curve.

Two maturity indices:

* Nurse-Saul temperature-time factor ``M = sum((T_avg - T0) * dt)`` in degC-hours,
  datum ``T0`` 0 degC unless the lab calibrated the mix with another.
* Equivalent age (Freiesleben-Hansen, Arrhenius) ``te = sum(exp(-E/R (1/T - 1/Tr)) dt)``
  in hours at the reference temperature ``Tr`` (20 degC), activation energy 40 kJ/mol.

Strength follows the mix's calibrated curve ``S = a + b * log10(index)``, fitted
by least squares to the mix's own cube results. Floats in, floats out: a
temperature probe is not more exact than that.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import datetime

__all__ = [
    "DEFAULT_ACTIVATION_KJ_MOL",
    "DEFAULT_DATUM_C",
    "DEFAULT_REFERENCE_C",
    "equivalent_age",
    "fit_log_curve",
    "hours_to_strength",
    "hours_to_target_range",
    "maturity_for_strength",
    "maturity_series",
    "nurse_saul",
    "strength_estimate",
    "strength_from_maturity",
]

DEFAULT_DATUM_C = 0.0
DEFAULT_ACTIVATION_KJ_MOL = 40.0
DEFAULT_REFERENCE_C = 20.0
_R_J_MOL_K = 8.314
_K = 273.15


def nurse_saul(
    readings: Iterable[tuple[datetime, float]], datum_c: float = DEFAULT_DATUM_C
) -> list[tuple[datetime, float]]:
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


def equivalent_age(
    readings: Iterable[tuple[datetime, float]],
    activation_kj_mol: float = DEFAULT_ACTIVATION_KJ_MOL,
    reference_c: float = DEFAULT_REFERENCE_C,
) -> list[tuple[datetime, float]]:
    """Cumulative equivalent age at ``reference_c``, in hours, after each reading."""
    rows = sorted(readings, key=lambda r: r[0])
    q = activation_kj_mol * 1000.0 / _R_J_MOL_K
    tr = reference_c + _K
    out: list[tuple[datetime, float]] = []
    total = 0.0
    for i, (t, temp) in enumerate(rows):
        if i:
            t_prev, temp_prev = rows[i - 1]
            dt_h = (t - t_prev).total_seconds() / 3600.0
            mean_k = (temp + temp_prev) / 2.0 + _K
            if dt_h > 0 and mean_k > 0:
                total += math.exp(-q * (1.0 / mean_k - 1.0 / tr)) * dt_h
        out.append((t, total))
    return out


def maturity_series(
    readings: Iterable[tuple[datetime, float]],
    method: str = "nurse_saul",
    datum_c: float = DEFAULT_DATUM_C,
    activation_kj_mol: float = DEFAULT_ACTIVATION_KJ_MOL,
    reference_c: float = DEFAULT_REFERENCE_C,
) -> list[tuple[datetime, float]]:
    """The mix's maturity index after each reading: degC-h (Nurse-Saul) or hours (equivalent age)."""
    if method == "equivalent_age":
        return equivalent_age(readings, activation_kj_mol, reference_c)
    return nurse_saul(readings, datum_c)


def fit_log_curve(points: Sequence[tuple[float, float]]) -> tuple[float, float, float] | None:
    """Least-squares ``S = a + b * log10(x)`` through ``(index, MPa)`` points.

    Returns:
        ``(a, b, r_squared)``, or None with fewer than two usable points or a single index value.
    """
    usable = [(math.log10(x), s) for x, s in points if x > 1.0]
    n = len(usable)
    if n < 2:
        return None
    mx = sum(x for x, _ in usable) / n
    my = sum(y for _, y in usable) / n
    sxx = sum((x - mx) ** 2 for x, _ in usable)
    if sxx <= 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in usable) / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for _, y in usable)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in usable)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return a, b, r2


def strength_from_maturity(maturity: float, a: float, b: float) -> float:
    """Strength the curve gives in MPa, never negative, 0 at M <= 1."""
    if maturity <= 1.0:
        return 0.0
    return max(0.0, a + b * math.log10(maturity))


def strength_estimate(
    index: float, a: float, b: float, lo: float | None = None, hi: float | None = None
) -> tuple[float | None, str]:
    """Strength with its standing against the calibrated range.

    Below the first calibration point, or at M <= 1, the curve says nothing,
    so there is no strength. Above the last point it is extrapolated and flagged.

    Returns:
        ``(MPa or None, status)``; status ``ok``, ``below_range``, ``above_range`` or ``uncalibrated``.
    """
    if index <= 1.0 or (lo is not None and index < lo):
        return None, "below_range"
    value = round(strength_from_maturity(index, a, b), 2)
    if lo is None or hi is None:
        return value, "uncalibrated"
    return value, "above_range" if index > hi else "ok"


def maturity_for_strength(strength: float, a: float, b: float) -> float | None:
    """Maturity the mix needs to reach ``strength``, None for a flat or falling curve."""
    if b <= 0:
        return None
    return 10 ** ((strength - a) / b)


def hours_to_target_range(
    series: list[tuple[datetime, float]], target_maturity: float, window_h: float = 6.0
) -> tuple[float, float] | None:
    """Fastest and slowest hours to ``target_maturity`` at the gain rates of the last ``window_h``.

    The target is a point on the log curve (``maturity_for_strength``); the
    fastest and slowest interval rates in the window bound the range.
    ``(0, 0)`` when reached, None when the pour is not gaining.
    """
    if not series:
        return None
    t_last, m_last = series[-1]
    if m_last >= target_maturity:
        return 0.0, 0.0
    recent = [(t, m) for t, m in series if (t_last - t).total_seconds() <= window_h * 3600]
    rates = []
    for (t0, m0), (t1, m1) in zip(recent, recent[1:], strict=False):
        dt = (t1 - t0).total_seconds() / 3600.0
        if dt > 0 and m1 > m0:
            rates.append((m1 - m0) / dt)
    if not rates:
        return None
    left = target_maturity - m_last
    return left / max(rates), left / min(rates)


def hours_to_strength(
    series: list[tuple[datetime, float]], target_maturity: float, window_h: float = 6.0
) -> float | None:
    """Hours until ``target_maturity`` at the mean rate of the window; 0 when reached, None when not gaining."""
    rng = hours_to_target_range(series, target_maturity, window_h)
    if rng is None:
        return None
    if rng == (0.0, 0.0):
        return 0.0
    t_last, m_last = series[-1]
    recent = [(t, m) for t, m in series if (t_last - t).total_seconds() <= window_h * 3600]
    t0, m0 = recent[0]
    span_h = (t_last - t0).total_seconds() / 3600.0
    return (target_maturity - m_last) / ((m_last - m0) / span_h)
