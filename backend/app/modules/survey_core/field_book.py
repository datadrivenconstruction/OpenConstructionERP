# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reduction of a traverse field book to horizontal angles right and horizontal distances.

A field book row is what the surveyor writes at one station: the backsight and foresight
ids, the horizontal angle on face left and/or face right, the distance (horizontal, or
slope with its zenith angle) and the instrument and target heights. The book sets how the
angles were booked:

* ``right``: clockwise from backsight to foresight (used as is);
* ``left``: counter-clockwise (``360 - a``);
* ``deflection``: from the prolongation of the back line, right positive (``180 + d``);
* ``azimuth``: the forward azimuth of each leg (``a_i - (a_(i-1) + 180)``).

Two faces are meaned on the circle; their difference is kept as a check. Slope distances
reduce to ``HD = SD sin Z`` and ``dH = SD cos Z + HI - HT``. The reduced angles and
distances then go through :func:`app.modules.survey_core.field_traverse.adjust`.

A loop with a backsight on another mark (a control point) closes its first angle with the
closing angle read at the start station from the last station to that mark: the interior
angle at the start is ``closing + angle(backsight -> first foresight)``.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.survey_core.field_traverse import LINK, LOOP, Station

ANGLE_MODES = ("right", "left", "deflection", "azimuth")
DEMO_BOOK = Path(__file__).resolve().parent / "demo" / "riverside" / "traverse_fieldbook.csv"


@dataclass(frozen=True)
class BookRow:
    station: str
    #: Face left / face right reading in decimal degrees; at least one is set.
    face_l: float | None
    face_r: float | None
    distance: float | None = None
    #: ``horizontal`` | ``slope``
    dist_mode: str = "horizontal"
    zenith_deg: float | None = None
    hi: float | None = None
    ht: float | None = None


@dataclass
class ReducedRow:
    station: str
    angle_deg: float
    angle_right_deg: float
    face_diff_sec: float | None
    hd: float | None
    dh: float | None


@dataclass
class ReducedBook:
    #: Loop: azimuth of the first leg. Link: backsight azimuth at the start.
    azimuth_deg: float
    stations: list[Station]
    rows: list[ReducedRow] = field(default_factory=list)
    closing_azimuth_deg: float | None = None


def _wrap360(deg: float) -> float:
    return deg % 360.0


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def mean_faces(face_l: float | None, face_r: float | None) -> tuple[float, float | None]:
    """Circular mean of the two faces and their difference ``FL - FR`` in seconds."""
    if face_l is None and face_r is None:
        raise ValueError("A station needs a face left or a face right reading")
    if face_l is None or face_r is None:
        return _wrap360(face_l if face_l is not None else face_r), None  # type: ignore[arg-type]
    diff = _wrap180(face_l - face_r)
    return _wrap360(face_r + diff / 2.0), diff * 3600.0


def horizontal(row: BookRow) -> tuple[float | None, float | None]:
    """Horizontal distance and height difference (instrument to target mark) of a row."""
    if row.distance is None:
        return None, None
    if row.dist_mode == "slope":
        if row.zenith_deg is None:
            raise ValueError(f"Station {row.station}: a slope distance needs its zenith angle")
        z = math.radians(row.zenith_deg)
        dh = row.distance * math.cos(z)
        if row.hi is not None and row.ht is not None:
            dh += row.hi - row.ht
        return row.distance * math.sin(z), dh
    return row.distance, None


def reduce_book(
    shape: str,
    angle_mode: str,
    rows: list[BookRow],
    backsight_azimuth_deg: float | None,
    closing_angle_deg: float | None = None,
    closing_azimuth_deg: float | None = None,
) -> ReducedBook:
    """Angles right and horizontal distances ready for the traverse adjustment.

    Raises:
        ValueError: an unknown mode, a missing orientation or a row that cannot be reduced.
    """
    if angle_mode not in ANGLE_MODES:
        raise ValueError(f"Unknown angle mode {angle_mode}")
    if shape not in (LOOP, LINK):
        raise ValueError("A traverse is a loop or a link")
    if not rows:
        raise ValueError("The field book is empty")
    means = [mean_faces(r.face_l, r.face_r) for r in rows]
    values = [m[0] if angle_mode != "deflection" else _wrap180(m[0]) for m in means]
    n = len(rows)
    if angle_mode == "azimuth":
        az = values
        if shape == LOOP:
            right = [_wrap360(az[i] - (az[i - 1] + 180.0)) for i in range(n)]
            first = az[0]
        else:
            if backsight_azimuth_deg is None:
                raise ValueError("A link traverse needs the backsight azimuth")
            right = [_wrap360(az[0] - backsight_azimuth_deg)]
            right += [_wrap360(az[i] - (az[i - 1] + 180.0)) for i in range(1, n)]
            first = backsight_azimuth_deg
    else:
        if backsight_azimuth_deg is None:
            raise ValueError("The field book needs the backsight azimuth at the start")
        if angle_mode == "right":
            right = [_wrap360(v) for v in values]
        elif angle_mode == "left":
            right = [_wrap360(360.0 - v) for v in values]
        else:
            right = [_wrap360(180.0 + v) for v in values]
        if shape == LOOP:
            first = _wrap360(backsight_azimuth_deg + right[0])
            if closing_angle_deg is not None:
                right[0] = _wrap360(closing_angle_deg + right[0])
        else:
            first = backsight_azimuth_deg
    out = ReducedBook(azimuth_deg=first, stations=[], closing_azimuth_deg=closing_azimuth_deg)
    for i, (row, (mean, diff)) in enumerate(zip(rows, means, strict=True)):
        hd, dh = horizontal(row)
        out.rows.append(ReducedRow(row.station, mean, right[i], diff, hd, dh))
        out.stations.append(Station(row.station, right[i], hd))
    return out


# ── CSV ────────────────────────────────────────────────────────────────────

BOOK_COLUMNS = ("station", "bs", "fs", "face_l", "face_r", "dist_mode", "distance", "zenith", "hi", "ht", "note")


def parse_book_csv(text: str) -> dict:
    """A field book file: ``#key,value...`` header lines, then one row per station.

    Header keys: ``name``, ``shape``, ``angle_unit``, ``angle_mode``, ``start`` (id, E, N),
    ``backsight`` (id, azimuth), ``closing_angle``, ``end`` (id, E, N), ``closing_azimuth``.
    Angles stay text in the book's unit, so the client shows them exactly as booked.
    """
    meta: dict = {"name": "", "shape": LOOP, "angle_unit": "dms", "angle_mode": "right"}
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            parts = [p.strip() for p in line[1:].split(",")]
            key, rest = parts[0].lower(), parts[1:]
            if key in ("start", "end") and len(rest) >= 3:
                meta[key] = {"station_id": rest[0], "e": float(rest[1]), "n": float(rest[2])}
            elif key == "backsight" and len(rest) >= 2:
                meta["backsight_id"], meta["backsight_azimuth"] = rest[0], rest[1]
            elif rest:
                meta[key] = rest[0]
        elif line.strip():
            body.append(line)
    rows = []
    for rec in csv.DictReader(io.StringIO("\n".join(body))):
        row = {k: (rec.get(k) or "").strip() for k in BOOK_COLUMNS}
        rows.append(row)
    meta["rows"] = rows
    return meta


__all__ = [
    "ANGLE_MODES",
    "BOOK_COLUMNS",
    "DEMO_BOOK",
    "BookRow",
    "ReducedBook",
    "ReducedRow",
    "horizontal",
    "mean_faces",
    "parse_book_csv",
    "reduce_book",
]
