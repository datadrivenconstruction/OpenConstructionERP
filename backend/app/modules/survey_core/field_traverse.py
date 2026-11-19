# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A traverse from field observations: horizontal angles and distances.

Angles are measured at each station from the backsight to the foresight.
``right`` means clockwise (the usual angle right), ``left`` counter-clockwise;
an angle left is turned into ``360 - angle`` before anything else. The forward
azimuth of a leg is ``backsight azimuth + angle right``; the next station's
backsight is that azimuth plus 180 deg.

Two shapes:

* ``loop``: starts and ends on the same known station. Input is the azimuth
  of the first leg and one angle per station, the start station last in the
  propagation. The angles must sum to ``(n - 2) * 180`` (interior) or
  ``(n + 2) * 180`` (exterior); the nearer one is the expected sum.
* ``link``: from a known station with a known backsight azimuth to another
  known station with a known closing azimuth; one angle per station including
  both ends.

The angular misclosure is spread evenly over the angles (``-w / n`` each), the
coordinates are then run with the corrected azimuths and closed by the Bowditch
(compass) rule. Allowance is ``k * sqrt(n)`` seconds, with ``k`` from a
tolerance class or the survey profile (no core default).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.modules.survey_core.survey_math import linear_misclosure, misclosure_ratio

LOOP = "loop"
LINK = "link"


@dataclass(frozen=True)
class Station:
    station_id: str
    #: Angle from backsight to foresight in decimal degrees.
    angle_deg: float
    #: Distance to the next station in metres; None on the last station of a link.
    distance_m: float | None = None


@dataclass
class AdjustedStation:
    station_id: str
    e: float
    n: float
    angle_corrected_deg: float
    azimuth_deg: float | None
    c_e: float = 0.0
    c_n: float = 0.0


@dataclass
class FieldTraverseResult:
    shape: str
    angle_count: int
    angle_sum_deg: float
    expected_sum_deg: float | None
    angular_misclosure_sec: float
    angular_correction_sec: float
    length_m: float
    f_e: float
    f_n: float
    misclosure_m: float
    ratio: int | None
    stations: list[AdjustedStation] = field(default_factory=list)


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def angular_allowed_sec(k_sec: float, n: int) -> float:
    """Allowed angular misclosure ``k * sqrt(n)`` in seconds."""
    return k_sec * math.sqrt(max(n, 0))


def angular_verdict(misclosure_sec: float, n: int, k_sec: float | None) -> tuple[float | None, str]:
    """Allowance and ``pass``/``fail``; ``no_profile`` without ``k``."""
    if not k_sec:
        return None, "no_profile"
    allowed = angular_allowed_sec(k_sec, n)
    return allowed, ("pass" if abs(misclosure_sec) <= allowed + 1e-9 else "fail")


def adjust(
    shape: str,
    start: tuple[float, float],
    azimuth_deg: float,
    stations: list[Station],
    angle_sense: str = "right",
    end: tuple[float, float] | None = None,
    closing_azimuth_deg: float | None = None,
) -> FieldTraverseResult:
    """Angular closure, even angular correction and Bowditch adjustment of a field traverse.

    Args:
        shape: ``loop`` or ``link``.
        start: E, N of the first station.
        azimuth_deg: loop - azimuth of the first leg; link - backsight azimuth at the first station.
        stations: in traverse order; a loop lists the start station first.
        angle_sense: ``right`` (clockwise) or ``left``.
        end: link only - E, N of the last station.
        closing_azimuth_deg: link only - the known forward azimuth at the last station.

    Raises:
        ValueError: when the observations cannot form that traverse.
    """
    n = len(stations)
    if shape not in (LOOP, LINK):
        raise ValueError("A traverse is a loop or a link")
    if n < (3 if shape == LOOP else 2):
        raise ValueError("Too few stations for this traverse")
    angles = [s.angle_deg if angle_sense == "right" else 360.0 - s.angle_deg for s in stations]
    legs = stations if shape == LOOP else stations[:-1]
    if any(s.distance_m is None or s.distance_m <= 0 for s in legs):
        raise ValueError("Every leg needs a positive distance")
    total = sum(angles)

    if shape == LOOP:
        interior, exterior = (n - 2) * 180.0, (n + 2) * 180.0
        expected = interior if abs(total - interior) <= abs(total - exterior) else exterior
        w_deg = total - expected
    else:
        if end is None or closing_azimuth_deg is None:
            raise ValueError("A link traverse needs the closing station and azimuth")
        computed = azimuth_deg + total - (n - 1) * 180.0
        expected = None
        w_deg = _wrap180(computed - closing_azimuth_deg)
    corr = -w_deg / n
    fixed = [a + corr for a in angles]

    # Forward azimuth of every leg with the corrected angles.
    azimuths: list[float] = []
    if shape == LOOP:
        az = azimuth_deg % 360.0
        azimuths.append(az)
        for a in fixed[1:]:
            az = (az + 180.0 + a) % 360.0
            azimuths.append(az)
        azimuths = azimuths[:n]
    else:
        back = azimuth_deg
        for a in fixed[:-1]:
            fwd = (back + a) % 360.0
            azimuths.append(fwd)
            back = fwd + 180.0

    d_e = [s.distance_m * math.sin(math.radians(az)) for s, az in zip(legs, azimuths, strict=True)]  # type: ignore[operator]
    d_n = [s.distance_m * math.cos(math.radians(az)) for s, az in zip(legs, azimuths, strict=True)]  # type: ignore[operator]
    length = sum(s.distance_m for s in legs)  # type: ignore[misc]
    target = start if shape == LOOP else end
    f_e = start[0] + sum(d_e) - target[0]  # type: ignore[index]
    f_n = start[1] + sum(d_n) - target[1]  # type: ignore[index]

    out: list[AdjustedStation] = [AdjustedStation(stations[0].station_id, start[0], start[1], fixed[0], azimuths[0])]
    e, nn, run = start[0], start[1], 0.0
    for i, s in enumerate(legs):
        run += s.distance_m  # type: ignore[operator]
        e += d_e[i]
        nn += d_n[i]
        c_e, c_n = -f_e * run / length, -f_n * run / length
        nxt = i + 1
        if shape == LOOP and nxt == n:
            break  # back on the start station
        out.append(
            AdjustedStation(
                stations[nxt].station_id,
                e + c_e,
                nn + c_n,
                fixed[nxt],
                azimuths[nxt] if nxt < len(azimuths) else None,
                c_e,
                c_n,
            )
        )
    f = linear_misclosure(f_e, f_n)
    return FieldTraverseResult(
        shape=shape,
        angle_count=n,
        angle_sum_deg=total,
        expected_sum_deg=expected,
        angular_misclosure_sec=w_deg * 3600.0,
        angular_correction_sec=corr * 3600.0,
        length_m=length,
        f_e=f_e,
        f_n=f_n,
        misclosure_m=f,
        ratio=misclosure_ratio(length, f),
        stations=out,
    )


__all__ = [
    "LINK",
    "LOOP",
    "AdjustedStation",
    "FieldTraverseResult",
    "Station",
    "adjust",
    "angular_allowed_sec",
    "angular_verdict",
]
