# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Displacement, rate and level arithmetic for monitoring points (no database).

Coordinates and values are metres, displacements are millimetres. All arithmetic
is ``Decimal``, so 34.497 - 34.512 is exactly -15 mm and not -14.999999 mm.

* Displacement is the change from the point's baseline, the first reading by
  date. Along ``z`` and ``value`` it keeps its sign (settlement is negative);
  ``horizontal`` and ``3d`` are distances and never negative.
* Rate is the change of displacement since the previous reading divided by the
  days between them (mm/day).
* Level is judged on the numbers as shown: displacement rounded to 0.1 mm, rate
  to 0.01 mm/day. A threshold is crossed when the absolute value reaches it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

AXES: tuple[str, ...] = ("z", "horizontal", "3d", "value")
POINT_TYPES: tuple[str, ...] = ("prism", "settlement_pin", "convergence_chord", "inclinometer")
LEVELS: tuple[str, ...] = ("ok", "alert", "action", "alarm")
RANK: dict[str, int] = {name: i for i, name in enumerate(LEVELS)}

#: The axis a point type is read along unless the person says otherwise.
DEFAULT_AXIS: dict[str, str] = {
    "prism": "3d",
    "settlement_pin": "z",
    "convergence_chord": "value",
    "inclinometer": "value",
}

_MM = Decimal(1000)
_TENTH = Decimal("0.1")
_HUNDREDTH = Decimal("0.01")
_SECONDS_PER_DAY = Decimal(86400)


@dataclass(frozen=True)
class Reading:
    """One point's reading: coordinates and/or a value, in metres."""

    at: datetime
    e: Decimal | None = None
    n: Decimal | None = None
    z: Decimal | None = None
    value: Decimal | None = None


@dataclass(frozen=True)
class Thresholds:
    """Level thresholds; a missing one never triggers. Displacement in mm, rate in mm/day."""

    alert_mm: Decimal | None = None
    action_mm: Decimal | None = None
    alarm_mm: Decimal | None = None
    rate_alert: Decimal | None = None
    rate_action: Decimal | None = None
    rate_alarm: Decimal | None = None

    def is_empty(self) -> bool:
        return all(v is None for v in self.as_tuple())

    def as_tuple(self) -> tuple[Decimal | None, ...]:
        return (self.alert_mm, self.action_mm, self.alarm_mm, self.rate_alert, self.rate_action, self.rate_alarm)

    def as_json(self) -> dict[str, str | None]:
        return {k: None if v is None else str(v) for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class Evaluation:
    """A reading judged against the baseline, the previous reading and the thresholds."""

    at: datetime
    displacement_mm: Decimal | None
    rate_mm_day: Decimal | None
    level: str
    #: True when ``level`` is higher than the previous reading's level.
    crossed: bool


def ordered(thresholds: Thresholds) -> bool:
    """Whether each set threshold family rises from alert to action to alarm."""
    for family in (
        (thresholds.alert_mm, thresholds.action_mm, thresholds.alarm_mm),
        (thresholds.rate_alert, thresholds.rate_action, thresholds.rate_alarm),
    ):
        given = [v for v in family if v is not None]
        if any(v <= 0 for v in given) or given != sorted(given) or len(set(given)) != len(given):
            return False
    return True


def round_mm(value: Decimal) -> Decimal:
    """Displacement as shown: 0.1 mm."""
    return value.quantize(_TENTH, rounding=ROUND_HALF_UP)


def displacement_mm(axis: str, base: Reading, current: Reading) -> Decimal | None:
    """Exact displacement of ``current`` from ``base`` in mm, or None when a needed number is missing."""
    if axis not in AXES:
        raise ValueError(f"unknown axis {axis!r}")
    if axis == "z":
        return _diff(base.z, current.z)
    if axis == "value":
        return _diff(base.value, current.value)
    de, dn = _diff(base.e, current.e), _diff(base.n, current.n)
    if de is None or dn is None:
        return None
    if axis == "horizontal":
        return (de * de + dn * dn).sqrt()
    if axis == "3d":
        dz = _diff(base.z, current.z)
        return None if dz is None else (de * de + dn * dn + dz * dz).sqrt()
    return None


def _diff(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else (b - a) * _MM


def days_between(earlier: datetime, later: datetime) -> Decimal:
    """Elapsed days, fractional; zero or negative when ``later`` is not after ``earlier``."""
    return Decimal(int((later - earlier).total_seconds())) / _SECONDS_PER_DAY


def rate_mm_day(previous_mm: Decimal | None, current_mm: Decimal | None, days: Decimal) -> Decimal | None:
    """Change of displacement per day, 0.01 mm/day; None without a previous displacement or time."""
    if previous_mm is None or current_mm is None or days <= 0:
        return None
    return ((current_mm - previous_mm) / days).quantize(_HUNDREDTH, rounding=ROUND_HALF_UP)


def level_of(displacement: Decimal | None, rate: Decimal | None, t: Thresholds) -> str:
    """The highest level crossed by the displacement (0.1 mm) or the rate (0.01 mm/day)."""
    best = 0
    if displacement is not None:
        for rank, limit in ((3, t.alarm_mm), (2, t.action_mm), (1, t.alert_mm)):
            if limit is not None and abs(displacement) >= limit:
                best = max(best, rank)
                break
    if rate is not None:
        for rank, limit in ((3, t.rate_alarm), (2, t.rate_action), (1, t.rate_alert)):
            if limit is not None and abs(rate) >= limit:
                best = max(best, rank)
                break
    return LEVELS[best]


def evaluate(axis: str, readings: Sequence[Reading], thresholds: Thresholds) -> list[Evaluation]:
    """Judge every reading of one point, oldest first. The first reading is the baseline (level ok)."""
    series = sorted(readings, key=lambda r: r.at)
    out: list[Evaluation] = []
    if not series:
        return out
    base = series[0]
    previous_exact: Decimal | None = None
    previous_at = base.at
    previous_level = "ok"
    for i, reading in enumerate(series):
        exact = Decimal(0) if i == 0 and displacement_mm(axis, base, base) is not None else None
        if i > 0:
            exact = displacement_mm(axis, base, reading)
        rate = None if i == 0 else rate_mm_day(previous_exact, exact, days_between(previous_at, reading.at))
        shown = None if exact is None else round_mm(exact)
        level = "ok" if i == 0 else level_of(shown, rate, thresholds)
        out.append(Evaluation(reading.at, shown, rate, level, RANK[level] > RANK[previous_level]))
        if exact is not None:  # a reading without the needed numbers never becomes the reference
            previous_exact, previous_at, previous_level = exact, reading.at, level
    return out


# ── Forecast ──────────────────────────────────────────────────────────────

#: Epochs the trend is fitted over unless the caller says otherwise.
FORECAST_EPOCHS = 5


@dataclass(frozen=True)
class Forecast:
    """Linear trend over the last epochs and when it reaches the next level."""

    slope_mm_day: float
    fitted_mm: float
    epochs: int
    level: str | None = None
    limit_mm: float | None = None
    days: float | None = None


def forecast(evaluations: Sequence[Evaluation], t: Thresholds, last_n: int = FORECAST_EPOCHS) -> Forecast | None:
    """Least-squares line through the last ``last_n`` displacements and the days to the next threshold.

    The next threshold is the lowest displacement limit the fitted value has not reached. A trend
    running back towards zero, or flat, reaches nothing. None with fewer than two usable epochs.
    """
    pts = [(e.at, float(e.displacement_mm)) for e in evaluations if e.displacement_mm is not None][-max(last_n, 2) :]
    if len(pts) < 2:
        return None
    t0 = pts[0][0]
    xs = [(at - t0).total_seconds() / 86400.0 for at, _ in pts]
    ys = [y for _, y in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    fitted = my + slope * (xs[-1] - mx)
    out = Forecast(round(slope, 4), round(fitted, 3), len(pts))
    away = abs(slope) > 1e-9 and (fitted == 0 or (slope > 0) == (fitted > 0))
    if not away:
        return out
    for level, limit in (("alert", t.alert_mm), ("action", t.action_mm), ("alarm", t.alarm_mm)):
        if limit is None or abs(fitted) >= float(limit):
            continue
        days = (float(limit) - abs(fitted)) / abs(slope)
        return Forecast(out.slope_mm_day, out.fitted_mm, out.epochs, level, float(limit), round(days, 1))
    return out
