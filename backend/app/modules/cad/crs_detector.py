# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Coordinate Reference System (CRS) auto-detection for CAD/BIM uploads.

A real-world construction file (DWG / DXF / IFC / RVT canonical JSON)
arrives with coordinates expressed in *some* projected CRS — a UTM zone,
a national grid, a Gauss-Krüger band — but the CRS itself is rarely
labelled. This module picks the most likely EPSG code from three
signals, in priority order:

    1. IFC4 ``IfcProjectedCRS`` header (gold — labelled by the source)
    2. AutoCAD ``ACAD_PROJECTION_GEODATA`` dictionary (gold — labelled)
    3. Bounding-box heuristic against ~80 high-frequency construction
       CRSs, ranked by how tightly the bbox fits each region's window.

Each detector returns a :class:`CRSGuess` with the best match, up to
three alternates, and a 0-1 confidence score. ``epsg = None`` is a
legitimate result and means "we could not auto-detect — ask the user".

Public API
==========

* :func:`detect_from_bbox` — universal fallback, given just (xmin, ymin,
  xmax, ymax) and a units string.
* :func:`detect_from_dwg_header` — read DXF/DWG header via ``ezdxf``.
* :func:`detect_from_ifc` — regex-grep the IFC STEP header (no
  IfcOpenShell — see project CLAUDE.md).
* :func:`detect_from_canonical` — entry point used by the IFC/RVT
  pipeline once a canonical JSON dict is in memory.

``pyproj`` is an *optional* runtime dependency. When available we use
it to resolve canonical CRS display names so the labels never drift
from the upstream EPSG registry. When missing the detector falls back
to the built-in name table — coverage stays identical, only the labels
get marginally less verbose.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ── Optional pyproj — purely for name lookup ────────────────────────────
try:
    from pyproj import CRS as _PyprojCRS  # type: ignore[import-not-found]

    _HAS_PYPROJ = True
except ImportError:  # pragma: no cover — covered by manual smoke
    _PyprojCRS = None  # type: ignore[assignment]
    _HAS_PYPROJ = False


# ── Bbox = (xmin, ymin, xmax, ymax) ─────────────────────────────────────
BBox = tuple[float, float, float, float]
Units = Literal["m", "ft", "mm", "in", "lat-lon", "unitless"]
DetectionMethod = Literal[
    "ifc_projected_crs",
    "dwg_geodata",
    "bbox_heuristic",
    "user_supplied",
    "unknown",
]


# ── Schema ──────────────────────────────────────────────────────────────


class CRSGuess(BaseModel):
    """‌⁠‍A single CRS guess with confidence and provenance.

    Use ``epsg=None`` for "we could not auto-detect"; the frontend
    surfaces a "Set CRS" affordance in that case. ``alternatives`` is
    always present and may be empty — never ``None``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    epsg: int | None = Field(default=None, description="EPSG code or None if unknown")
    name: str = Field(default="Unknown", description="Human-readable CRS name")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    units: Units = Field(default="unitless")
    bbox: BBox = Field(default=(0.0, 0.0, 0.0, 0.0))
    detection_method: DetectionMethod = Field(default="unknown")
    alternatives: list[CRSGuess] = Field(default_factory=list)

    def short_label(self) -> str:
        """‌⁠‍One-line label for UI chips."""
        if self.epsg is None:
            return self.name
        return f"{self.name} (EPSG:{self.epsg})"


# ── Region heuristic table ──────────────────────────────────────────────
#
# Each entry: (name, epsg, xmin, ymin, xmax, ymax, units).
# The bbox is the *coordinate-valid window* in that CRS — not the
# country bbox. We use it to score how likely an incoming model belongs
# in this CRS. See .claude/research/crs_detection.md §1 for sources.

_REGION_TABLE: list[tuple[str, int, float, float, float, float, str]] = [
    # ── India — UTM 42N..46N. Y window matches Indian latitude band
    # (lat 8°..36° → y ≈ 880_000..3_990_000 in UTM Northern hemisphere).
    ("UTM Zone 42N (WGS 84)", 32642, 166_000, 800_000, 833_000, 4_000_000, "m"),
    ("UTM Zone 43N (WGS 84)", 32643, 166_000, 800_000, 833_000, 4_000_000, "m"),
    ("UTM Zone 44N (WGS 84)", 32644, 166_000, 800_000, 833_000, 4_000_000, "m"),
    ("UTM Zone 45N (WGS 84)", 32645, 166_000, 800_000, 833_000, 4_000_000, "m"),
    ("UTM Zone 46N (WGS 84)", 32646, 166_000, 800_000, 833_000, 4_000_000, "m"),
    # ── Germany — UTM 32N / 33N (ETRS89) ────────────────────────────────
    ("ETRS89 / UTM zone 32N", 25832, 166_000, 5_200_000, 833_000, 6_100_000, "m"),
    ("ETRS89 / UTM zone 33N", 25833, 166_000, 5_200_000, 833_000, 6_100_000, "m"),
    # ── Germany — DHDN / Gauss-Krüger zones 2-5 ─────────────────────────
    ("DHDN / 3-Grad GK zone 2", 31466, 2_400_000, 5_200_000, 2_900_000, 6_100_000, "m"),
    ("DHDN / 3-Grad GK zone 3", 31467, 3_300_000, 5_200_000, 3_900_000, 6_100_000, "m"),
    ("DHDN / 3-Grad GK zone 4", 31468, 4_300_000, 5_200_000, 4_900_000, 6_100_000, "m"),
    ("DHDN / 3-Grad GK zone 5", 31469, 5_300_000, 5_200_000, 5_900_000, 6_100_000, "m"),
    # ── Switzerland — LV95 ──────────────────────────────────────────────
    ("CH1903+ / LV95", 2056, 2_480_000, 1_070_000, 2_840_000, 1_300_000, "m"),
    # ── Austria — MGI / Austria zones ───────────────────────────────────
    ("MGI / Austria M28", 31256, -200_000, 5_100_000, 250_000, 5_500_000, "m"),
    ("MGI / Austria M31", 31257, -100_000, 5_100_000, 350_000, 5_500_000, "m"),
    ("MGI / Austria M34", 31258, 0, 5_100_000, 400_000, 5_500_000, "m"),
    # ── UK — British National Grid + Irish TM75 ─────────────────────────
    ("OSGB36 / British National Grid", 27700, 0, 0, 700_000, 1_300_000, "m"),
    ("TM75 / Irish Grid", 29903, 0, 0, 500_000, 600_000, "m"),
    # ── France — RGF93 Lambert-93 ───────────────────────────────────────
    ("RGF93 / Lambert-93", 2154, 100_000, 6_000_000, 1_300_000, 7_200_000, "m"),
    # ── Netherlands — RD New ────────────────────────────────────────────
    ("Amersfoort / RD New", 28992, -7_000, 289_000, 300_000, 629_000, "m"),
    # ── US — State Plane (top-10 by population) — wide windows ──────────
    ("NAD83 / California zone 1 (ft)", 2225, 5_500_000, 1_300_000, 7_800_000, 2_700_000, "ft"),
    ("NAD83 / California zone 3 (ft)", 2227, 5_500_000, 1_400_000, 7_400_000, 2_400_000, "ft"),
    ("NAD83 / Texas Central (ft)", 2277, 2_500_000, 6_500_000, 5_300_000, 10_500_000, "ft"),
    ("NAD83 / New York Long Island (ft)", 2263, 800_000, 0, 1_100_000, 350_000, "ft"),
    ("NAD83 / Florida East (ft)", 2236, 400_000, 0, 1_100_000, 1_700_000, "ft"),
    ("NAD83 / Illinois East (ft)", 3435, 800_000, 0, 1_300_000, 2_500_000, "ft"),
    ("NAD83 / Pennsylvania South (ft)", 2272, 1_200_000, 0, 3_000_000, 800_000, "ft"),
    ("NAD83 / Ohio South (ft)", 3735, 1_200_000, 0, 2_400_000, 800_000, "ft"),
    ("NAD83 / Georgia East (ft)", 2239, 500_000, 0, 1_000_000, 1_700_000, "ft"),
    ("NAD83 / Michigan Central (ft)", 2253, 5_000_000, 7_000_000, 9_000_000, 11_500_000, "ft"),
    # ── US UTM (zones 10N..19N) — y band tied to US lat 24°..49° ────────
    # Y window matches the USA latitude band only (2_600_000..5_500_000)
    # so US bboxes don't get confused with Indian UTM at lower y.
    ("UTM Zone 10N (WGS 84)", 32610, 166_000, 3_500_000, 833_000, 5_500_000, "m"),
    ("UTM Zone 11N (WGS 84)", 32611, 166_000, 3_500_000, 833_000, 5_500_000, "m"),
    ("UTM Zone 12N (WGS 84)", 32612, 166_000, 3_500_000, 833_000, 5_500_000, "m"),
    ("UTM Zone 13N (WGS 84)", 32613, 166_000, 3_500_000, 833_000, 5_500_000, "m"),
    ("UTM Zone 14N (WGS 84)", 32614, 166_000, 3_500_000, 833_000, 5_500_000, "m"),
    ("UTM Zone 15N (WGS 84)", 32615, 166_000, 3_500_000, 833_000, 5_500_000, "m"),
    ("UTM Zone 16N (WGS 84)", 32616, 166_000, 3_500_000, 833_000, 5_500_000, "m"),
    ("UTM Zone 17N (WGS 84)", 32617, 166_000, 3_500_000, 833_000, 5_500_000, "m"),
    ("UTM Zone 18N (WGS 84)", 32618, 166_000, 3_500_000, 833_000, 5_500_000, "m"),
    ("UTM Zone 19N (WGS 84)", 32619, 166_000, 3_500_000, 833_000, 5_500_000, "m"),
    # ── UAE / KSA / Iran / Pakistan — UTM 38N..40N (lat 16°..37°) ───────
    ("UTM Zone 38N (WGS 84)", 32638, 166_000, 1_800_000, 833_000, 4_100_000, "m"),
    ("UTM Zone 39N (WGS 84)", 32639, 166_000, 1_800_000, 833_000, 4_100_000, "m"),
    ("UTM Zone 40N (WGS 84)", 32640, 166_000, 1_800_000, 833_000, 4_100_000, "m"),
    # ── Japan — JGD2011 plane rectangular CS zones I..XIX ───────────────
    ("JGD2011 / Japan Plane Zone I", 6669, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone II", 6670, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone III", 6671, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone IV", 6672, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone V", 6673, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone VI", 6674, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone VII", 6675, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone VIII", 6676, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone IX", 6677, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone X", 6678, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone XI", 6679, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone XII", 6680, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone XIII", 6681, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone XIV", 6682, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone XV", 6683, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone XVI", 6684, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone XVII", 6685, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone XVIII", 6686, -250_000, -400_000, 250_000, 400_000, "m"),
    ("JGD2011 / Japan Plane Zone XIX", 6687, -250_000, -400_000, 250_000, 400_000, "m"),
    # ── Brazil — SIRGAS 2000 UTM 18S..25S ───────────────────────────────
    ("SIRGAS 2000 / UTM zone 18S", 31978, 166_000, 6_100_000, 833_000, 10_000_000, "m"),
    ("SIRGAS 2000 / UTM zone 19S", 31979, 166_000, 6_100_000, 833_000, 10_000_000, "m"),
    ("SIRGAS 2000 / UTM zone 20S", 31980, 166_000, 6_100_000, 833_000, 10_000_000, "m"),
    ("SIRGAS 2000 / UTM zone 21S", 31981, 166_000, 6_100_000, 833_000, 10_000_000, "m"),
    ("SIRGAS 2000 / UTM zone 22S", 31982, 166_000, 6_100_000, 833_000, 10_000_000, "m"),
    ("SIRGAS 2000 / UTM zone 23S", 31983, 166_000, 6_100_000, 833_000, 10_000_000, "m"),
    ("SIRGAS 2000 / UTM zone 24S", 31984, 166_000, 6_100_000, 833_000, 10_000_000, "m"),
    ("SIRGAS 2000 / UTM zone 25S", 31985, 166_000, 6_100_000, 833_000, 10_000_000, "m"),
    # ── China — CGCS2000 3-degree Gauss-Krüger zones 13..23 ─────────────
    ("CGCS2000 / 3-degree GK zone 13", 4513, 13_300_000, 1_800_000, 13_700_000, 6_000_000, "m"),
    ("CGCS2000 / 3-degree GK zone 14", 4514, 14_300_000, 1_800_000, 14_700_000, 6_000_000, "m"),
    ("CGCS2000 / 3-degree GK zone 15", 4515, 15_300_000, 1_800_000, 15_700_000, 6_000_000, "m"),
    ("CGCS2000 / 3-degree GK zone 16", 4516, 16_300_000, 1_800_000, 16_700_000, 6_000_000, "m"),
    ("CGCS2000 / 3-degree GK zone 17", 4517, 17_300_000, 1_800_000, 17_700_000, 6_000_000, "m"),
    ("CGCS2000 / 3-degree GK zone 18", 4518, 18_300_000, 1_800_000, 18_700_000, 6_000_000, "m"),
    ("CGCS2000 / 3-degree GK zone 19", 4519, 19_300_000, 1_800_000, 19_700_000, 6_000_000, "m"),
    ("CGCS2000 / 3-degree GK zone 20", 4520, 20_300_000, 1_800_000, 20_700_000, 6_000_000, "m"),
    ("CGCS2000 / 3-degree GK zone 21", 4521, 21_300_000, 1_800_000, 21_700_000, 6_000_000, "m"),
    ("CGCS2000 / 3-degree GK zone 22", 4522, 22_300_000, 1_800_000, 22_700_000, 6_000_000, "m"),
    ("CGCS2000 / 3-degree GK zone 23", 4523, 23_300_000, 1_800_000, 23_700_000, 6_000_000, "m"),
    # ── Levant — Palestine 1923 Grid ────────────────────────────────────
    ("Palestine 1923 / Palestine Grid", 28191, 100_000, 50_000, 250_000, 350_000, "m"),
]


# ── Heuristic scoring ───────────────────────────────────────────────────


def _bbox_overlap(a: BBox, b: BBox) -> tuple[float, float, float]:
    """Return ``(overlap_area, a_area, b_area)`` between two AABBs."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ox0 = max(ax0, bx0)
    oy0 = max(ay0, by0)
    ox1 = min(ax1, bx1)
    oy1 = min(ay1, by1)
    if ox1 <= ox0 or oy1 <= oy0:
        return 0.0, max(0.0, (ax1 - ax0) * (ay1 - ay0)), max(0.0, (bx1 - bx0) * (by1 - by0))
    overlap = (ox1 - ox0) * (oy1 - oy0)
    a_area = max(1e-9, (ax1 - ax0) * (ay1 - ay0))
    b_area = max(1e-9, (bx1 - bx0) * (by1 - by0))
    return overlap, a_area, b_area


def _score_region(bbox: BBox, region: BBox) -> float:
    """Score how well ``bbox`` fits inside ``region``. 0..1, higher = better.

    Scoring rules:

    * 0.0 → bbox has no overlap with region.
    * ``overlap_frac`` → fraction of bbox area inside region (1.0 when
      fully contained).
    * Plus a tightness bonus: when the bbox is fully inside, smaller
      regions score marginally higher than huge ones. This is what
      breaks ties between e.g. ``British National Grid`` (huge window)
      and ``Palestine 1923 Grid`` (small window) for a bbox that
      happens to fit both — the tighter region wins, which matches
      real-world surveyor expectations.
    """
    overlap, a_area, b_area = _bbox_overlap(bbox, region)
    if a_area <= 0:
        return 0.0
    overlap_frac = min(1.0, overlap / a_area)
    if overlap_frac < 1.0:
        return overlap_frac
    # Fully contained — tightness bonus inversely proportional to region
    # size. Bounded to 0.001..0.05 so it only ever breaks ties between
    # otherwise-equal candidates and never overrides a partial-fit
    # candidate that would be a better match.
    if b_area <= 0:
        return overlap_frac
    # Log-scale tightness: large regions (10^11 m² ≈ UK) → tiny bonus;
    # small regions (10^9 m² ≈ Palestine) → larger bonus.
    import math as _math

    tightness = max(0.0, 12 - _math.log10(b_area + 1)) / 240.0
    return min(1.0, overlap_frac + tightness)


def _pyproj_verify(epsg: int, bbox: BBox) -> float | None:
    """When pyproj is available, project the bbox centre back to lat/lon
    and return a 0..1 score for how plausible the inverse coordinates
    are (mostly: in valid lat/lon range). Returns ``None`` when pyproj
    isn't available or the projection failed.
    """
    if not _HAS_PYPROJ or _PyprojCRS is None:
        return None
    try:
        from pyproj import Transformer  # type: ignore[import-not-found]

        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        transformer = Transformer.from_crs(epsg, 4326, always_xy=True)
        lon, lat = transformer.transform(cx, cy)
        if lon is None or lat is None or not (-180.0 <= lon <= 180.0) or not (-90.0 <= lat <= 90.0):
            return 0.0
        # All in range → full bonus.
        return 1.0
    except Exception:  # noqa: BLE001 — pyproj has many failure modes
        return None


def _is_degenerate(bbox: BBox) -> bool:
    xmin, ymin, xmax, ymax = bbox
    if any(_is_nan(v) for v in (xmin, ymin, xmax, ymax)):
        return True
    return xmax <= xmin or ymax <= ymin


def _is_nan(x: float) -> bool:
    return x != x  # NaN is the only float that fails self-equality


def _lookup_name(epsg: int, fallback: str) -> str:
    """Resolve a CRS display name from ``pyproj``, falling back to local."""
    if _HAS_PYPROJ and _PyprojCRS is not None:
        try:
            return _PyprojCRS.from_epsg(epsg).name  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001 — any pyproj error → fallback
            pass
    return fallback


# ── Public detectors ────────────────────────────────────────────────────


def _project_local_guess(bbox: BBox, units: str = "m") -> CRSGuess:
    """Build the "project-local, unknown CRS" answer for a small bbox."""
    return CRSGuess(
        epsg=None,
        name="Project-local (unknown CRS)",
        confidence=0.4,
        units=_normalise_units(units),
        bbox=bbox,
        detection_method="bbox_heuristic",
        alternatives=[],
    )


def _unknown_guess(bbox: BBox | None = None, units: str = "unitless") -> CRSGuess:
    return CRSGuess(
        epsg=None,
        name="Unknown",
        confidence=0.0,
        units=_normalise_units(units),
        bbox=bbox or (0.0, 0.0, 0.0, 0.0),
        detection_method="unknown",
        alternatives=[],
    )


_UNITS_ALIAS: dict[str, Units] = {
    "m": "m",
    "metre": "m",
    "meter": "m",
    "metres": "m",
    "meters": "m",
    "ft": "ft",
    "feet": "ft",
    "foot": "ft",
    "mm": "mm",
    "millimetre": "mm",
    "millimeter": "mm",
    "millimetres": "mm",
    "millimeters": "mm",
    "in": "in",
    "inch": "in",
    "inches": "in",
    "lat-lon": "lat-lon",
    "latlon": "lat-lon",
    "degree": "lat-lon",
    "degrees": "lat-lon",
}


def _normalise_units(u: str | None) -> Units:
    if not u:
        return "unitless"
    return _UNITS_ALIAS.get(u.strip().lower(), "unitless")


def detect_from_bbox(bbox: BBox, units: str = "m") -> CRSGuess:
    """Guess the CRS from a bounding box alone — the universal fallback.

    Args:
        bbox: ``(xmin, ymin, xmax, ymax)`` in whatever units the source
            file declared. If the source declared no units, pass ``"m"``
            (the IFC default) or ``"ft"`` for survey-foot models.
        units: Source units. See :data:`_UNITS_ALIAS` for accepted
            spellings.

    Returns:
        :class:`CRSGuess`. ``epsg=None`` means "could not decide — ask
        the user", which is a *legitimate* result for project-local
        files with arbitrary origins.
    """
    norm_units = _normalise_units(units)

    if _is_degenerate(bbox):
        return _unknown_guess(bbox, norm_units)

    xmin, ymin, xmax, ymax = bbox

    # WGS 84 lat-lon — narrow window, distinctive ranges.
    if (
        -180.0 <= xmin <= 180.0
        and -180.0 <= xmax <= 180.0
        and -90.0 <= ymin <= 90.0
        and -90.0 <= ymax <= 90.0
        and max(abs(xmin), abs(xmax)) < 360.0
        and max(abs(ymin), abs(ymax)) < 100.0
    ):
        # Disambiguate against small project-local models in metres.
        # If user explicitly declared metres / feet, it's not lat-lon.
        if norm_units not in ("m", "ft", "mm", "in"):
            return CRSGuess(
                epsg=4326,
                name=_lookup_name(4326, "WGS 84 (geographic)"),
                confidence=0.92,
                units="lat-lon",
                bbox=bbox,
                detection_method="bbox_heuristic",
                alternatives=[],
            )

    # Project-local — small origin, area under ~1 km².
    area = (xmax - xmin) * (ymax - ymin)
    if (
        abs(xmin) < 10_000
        and abs(xmax) < 10_000
        and abs(ymin) < 10_000
        and abs(ymax) < 10_000
        and area < 1_000_000  # 1 km²
    ):
        return _project_local_guess(bbox, norm_units)

    # Score every region.
    scored: list[tuple[float, str, int, str]] = []
    for name, epsg, rxmin, rymin, rxmax, rymax, runits in _REGION_TABLE:
        score = _score_region(bbox, (rxmin, rymin, rxmax, rymax))
        if score > 0:
            # Tighten score: bbox must also be at least 10× larger than
            # noise (small bboxes that happen to land inside a huge UTM
            # window without really belonging there) — see project-local
            # guard above which already filters the worst cases.
            scored.append((score, name, epsg, runits))

    if not scored:
        # No region matched at all — likely project-local with a big
        # offset, or coordinates we don't cover. Emit unknown.
        return _unknown_guess(bbox, norm_units)

    scored.sort(key=lambda t: -t[0])
    top_score, top_name, top_epsg, top_units = scored[0]

    # Build the alternate list. When several candidates tie at the top
    # score (e.g. all UTM zones in the same latitude band fit equally),
    # keep every tied candidate so the frontend can show every
    # plausible zone in the "Set CRS" dropdown. Otherwise cap at 3 to
    # keep the dropdown tidy when the heuristic is decisive.
    ties = [t for t in scored if abs(t[0] - top_score) < 0.001]
    max_alts = max(3, len(ties) - 1) if len(ties) > 1 else 3

    alternates: list[CRSGuess] = []
    for score, name, epsg, runits in scored[1 : 1 + max_alts]:
        alternates.append(
            CRSGuess(
                epsg=epsg,
                name=_lookup_name(epsg, name),
                confidence=round(score, 3),
                units=_normalise_units(runits),
                bbox=bbox,
                detection_method="bbox_heuristic",
                alternatives=[],
            )
        )

    # If pyproj is available, prefer the candidate whose inverse
    # projection lands inside lat/lon bounds. This lets us pick
    # (e.g.) UAE UTM 40N over India UTM 43N when the bbox is at
    # x≈325k, y≈2.8M — both fit the bbox window but only one
    # back-projects to UAE longitudes.
    if _HAS_PYPROJ:
        verified: list[tuple[float, str, int, str, float]] = []
        for score, name, epsg, runits in scored:
            verify = _pyproj_verify(epsg, bbox)
            combined = score if verify is None else score * (0.5 + 0.5 * verify)
            verified.append((combined, name, epsg, runits, score))
        verified.sort(key=lambda t: -t[0])
        if verified and verified[0][2] != top_epsg:
            # Override primary with the verified pick; preserve the
            # original score in the response.
            _, top_name, top_epsg, top_units, top_orig_score = verified[0]
            top_score = top_orig_score
            alternates = []
            for combined, name, epsg, runits, orig in verified[1 : 1 + max_alts]:
                alternates.append(
                    CRSGuess(
                        epsg=epsg,
                        name=_lookup_name(epsg, name),
                        confidence=round(orig, 3),
                        units=_normalise_units(runits),
                        bbox=bbox,
                        detection_method="bbox_heuristic",
                        alternatives=[],
                    )
                )

    return CRSGuess(
        epsg=top_epsg,
        name=_lookup_name(top_epsg, top_name),
        confidence=round(top_score, 3),
        units=_normalise_units(top_units),
        bbox=bbox,
        detection_method="bbox_heuristic",
        alternatives=alternates,
    )


# ── DWG / DXF ───────────────────────────────────────────────────────────


_INSUNITS_TO_NAME: dict[int, Units] = {
    0: "unitless",
    1: "in",
    2: "ft",
    4: "mm",
    5: "mm",  # cm — closest accepted Units literal
    6: "m",
    7: "m",  # km — closest accepted Units literal
}


def detect_from_dwg_header(dwg_path: Path) -> CRSGuess:
    """Detect CRS from a DWG/DXF file header via ``ezdxf``.

    Tries in order:

    1. ``ACAD_PROJECTION_GEODATA`` dictionary — if present, returns
       ``detection_method="dwg_geodata"`` with confidence 1.0.
    2. ``$EXTMIN/$EXTMAX/$INSUNITS`` → :func:`detect_from_bbox`.
    """
    try:
        import ezdxf  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover — ezdxf is a hard dep
        logger.warning("ezdxf not installed — CRS detection skipped for %s", dwg_path)
        return _unknown_guess()

    try:
        doc = ezdxf.readfile(str(dwg_path))
    except Exception as exc:  # noqa: BLE001 — any ezdxf failure → unknown
        logger.debug("ezdxf could not read %s: %s", dwg_path, exc)
        return _unknown_guess()

    # Step 1 — try the geodata dictionary (Civil 3D / AutoCAD 2010+).
    epsg = _read_acad_geodata_epsg(doc)
    insunits = int(doc.header.get("$INSUNITS", 0))
    units = _INSUNITS_TO_NAME.get(insunits, "unitless")

    if epsg is not None:
        return CRSGuess(
            epsg=epsg,
            name=_lookup_name(epsg, f"EPSG:{epsg}"),
            confidence=1.0,
            units=units,
            bbox=_dwg_bbox(doc),
            detection_method="dwg_geodata",
            alternatives=[],
        )

    # Step 2 — bbox heuristic.
    bbox = _dwg_bbox(doc)
    guess = detect_from_bbox(bbox, units=units)
    return guess


def _dwg_bbox(doc: Any) -> BBox:
    extmin = doc.header.get("$EXTMIN", (0.0, 0.0, 0.0))
    extmax = doc.header.get("$EXTMAX", (0.0, 0.0, 0.0))
    # ezdxf returns ``Vec3`` — index access works for tuples too.
    return (float(extmin[0]), float(extmin[1]), float(extmax[0]), float(extmax[1]))


_ACAD_EPSG_RE = re.compile(r"EPSG[:\s]*(\d{4,6})", re.IGNORECASE)


def _read_acad_geodata_epsg(doc: Any) -> int | None:
    """Best-effort scan for an EPSG code in the AutoCAD geodata dict.

    AutoCAD writes a ``ACAD_PROJECTION_GEODATA`` dictionary entry that
    embeds an XML-like CRS definition. We don't fully parse it — we
    grep for the canonical ``EPSG:<digits>`` token, which all
    well-authored geodata blocks include.
    """
    try:
        rootdict = doc.rootdict
    except AttributeError:
        return None

    try:
        for key, _entity in rootdict.items() if hasattr(rootdict, "items") else []:
            if "GEODATA" in str(key).upper() or "PROJECTION" in str(key).upper():
                # We can't deeply inspect arbitrary ezdxf objects in a
                # version-stable way; serialise to text and grep.
                try:
                    text = str(_entity.dxf.export_dxf_attribs)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    text = str(_entity)
                m = _ACAD_EPSG_RE.search(text)
                if m:
                    return int(m.group(1))
    except Exception:  # noqa: BLE001 — best-effort
        return None
    return None


# ── IFC (no IfcOpenShell — regex over STEP text) ────────────────────────


_IFC_PROJECTED_CRS_RE = re.compile(
    r"IFCPROJECTEDCRS\s*\(\s*'([^']*)'\s*,\s*'([^']*)'",
    re.IGNORECASE,
)
_IFC_MAP_CONVERSION_RE = re.compile(
    r"IFCMAPCONVERSION\s*\(\s*[^,]*,\s*[^,]*,\s*"
    r"([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)",
    re.IGNORECASE,
)
_IFC_EPSG_RE = re.compile(r"EPSG[:\s]*(\d{4,6})", re.IGNORECASE)
_IFC_UNIT_RE = re.compile(
    r"IFCSIUNIT\s*\([^)]*\.LENGTHUNIT\.\s*,\s*([.A-Z]*)\s*,\s*\.([A-Z]+)\.",
    re.IGNORECASE,
)


def detect_from_ifc(ifc_path: Path) -> CRSGuess:
    """Detect CRS from an IFC file, reading only the STEP text.

    Tries ``IfcProjectedCRS`` first (IFC4+); falls back to bbox derived
    from ``IfcMapConversion`` eastings/northings; finally returns
    ``unknown`` if neither is present and we can't compute a bbox.
    """
    try:
        # Read up to ~256 KB — header + first chunk is enough. IFC
        # files put schema metadata at the top.
        text = ifc_path.read_text(encoding="utf-8", errors="replace")[:262_144]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read %s: %s", ifc_path, exc)
        return _unknown_guess()

    return _detect_from_ifc_text(text)


def _detect_from_ifc_text(text: str) -> CRSGuess:
    # Step 1 — IfcProjectedCRS Name field.
    m = _IFC_PROJECTED_CRS_RE.search(text)
    epsg: int | None = None
    descriptive_name: str | None = None
    if m:
        crs_name_field = m.group(1).strip()
        descriptive_name = m.group(2).strip() or None
        epsg_match = _IFC_EPSG_RE.search(crs_name_field)
        if epsg_match:
            epsg = int(epsg_match.group(1))

    # If Name didn't carry EPSG, scan the whole header for any EPSG token.
    if epsg is None:
        any_epsg = _IFC_EPSG_RE.search(text)
        if any_epsg:
            epsg = int(any_epsg.group(1))

    # Step 2 — IfcMapConversion → eastings/northings hint for bbox.
    mc = _IFC_MAP_CONVERSION_RE.search(text)
    origin: tuple[float, float] | None = None
    if mc:
        try:
            origin = (float(mc.group(1)), float(mc.group(2)))
        except ValueError:
            origin = None

    if epsg is not None:
        name = descriptive_name or _lookup_name(epsg, f"EPSG:{epsg}")
        bbox = (origin[0], origin[1], origin[0] + 1, origin[1] + 1) if origin else (0.0, 0.0, 0.0, 0.0)
        return CRSGuess(
            epsg=epsg,
            name=name,
            confidence=1.0,
            units="m",
            bbox=bbox,
            detection_method="ifc_projected_crs",
            alternatives=[],
        )

    # No CRS declared → use the origin (if any) for the heuristic.
    if origin is not None:
        # Stretch the bbox out by 1km so the heuristic has something to bite.
        bbox = (origin[0] - 500, origin[1] - 500, origin[0] + 500, origin[1] + 500)
        return detect_from_bbox(bbox, units="m")

    return _unknown_guess(units="m")


# ── Canonical JSON entry point ──────────────────────────────────────────


def detect_from_canonical(canonical: dict[str, Any]) -> CRSGuess:
    """Entry point used by the IFC/RVT pipeline.

    Reads ``bounding_box`` from the canonical dict (top-level or under
    ``metadata``) and falls back to :func:`detect_from_bbox`. Also
    honours an explicit ``crs`` field if a previous pass already
    decided.
    """
    if not isinstance(canonical, dict):
        return _unknown_guess()

    # Honour an existing decision (idempotent re-runs).
    pre = canonical.get("crs")
    if isinstance(pre, dict) and pre.get("epsg"):
        try:
            return CRSGuess(**pre)
        except Exception:  # noqa: BLE001 — fall through to recompute
            pass

    bbox_field = canonical.get("bounding_box") or (
        canonical.get("metadata", {}).get("bounding_box") if isinstance(canonical.get("metadata"), dict) else None
    )

    units = canonical.get("units") or "m"

    if isinstance(bbox_field, dict):
        try:
            xmin = float(bbox_field.get("min_x", bbox_field.get("xmin", 0.0)))
            ymin = float(bbox_field.get("min_y", bbox_field.get("ymin", 0.0)))
            xmax = float(bbox_field.get("max_x", bbox_field.get("xmax", 0.0)))
            ymax = float(bbox_field.get("max_y", bbox_field.get("ymax", 0.0)))
        except (TypeError, ValueError):
            return _unknown_guess(units=units)
        return detect_from_bbox((xmin, ymin, xmax, ymax), units=units)

    if isinstance(bbox_field, (list, tuple)) and len(bbox_field) >= 4:
        try:
            xmin, ymin, xmax, ymax = (float(v) for v in bbox_field[:4])
        except (TypeError, ValueError):
            return _unknown_guess(units=units)
        return detect_from_bbox((xmin, ymin, xmax, ymax), units=units)

    # Derive bbox from elements if present.
    elements = canonical.get("elements") or []
    if elements:
        xs: list[float] = []
        ys: list[float] = []
        for elem in elements:
            bb = (elem or {}).get("bounding_box") if isinstance(elem, dict) else None
            if isinstance(bb, dict):
                try:
                    xs.append(float(bb.get("min_x", bb.get("xmin", 0.0))))
                    xs.append(float(bb.get("max_x", bb.get("xmax", 0.0))))
                    ys.append(float(bb.get("min_y", bb.get("ymin", 0.0))))
                    ys.append(float(bb.get("max_y", bb.get("ymax", 0.0))))
                except (TypeError, ValueError):
                    continue
        if xs and ys:
            return detect_from_bbox(
                (min(xs), min(ys), max(xs), max(ys)),
                units=units,
            )

    return _unknown_guess(units=units)


# ── User-supplied override ──────────────────────────────────────────────


def from_user_supplied(epsg: int) -> CRSGuess:
    """Construct a :class:`CRSGuess` from a manually-picked EPSG code.

    Used when the auto-detector falls short and the user types/picks an
    EPSG in the viewer's "Set CRS" dropdown.
    """
    return CRSGuess(
        epsg=epsg,
        name=_lookup_name(epsg, f"EPSG:{epsg}"),
        confidence=1.0,
        units="m",
        bbox=(0.0, 0.0, 0.0, 0.0),
        detection_method="user_supplied",
        alternatives=[],
    )


__all__ = [
    "CRSGuess",
    "detect_from_bbox",
    "detect_from_canonical",
    "detect_from_dwg_header",
    "detect_from_ifc",
    "from_user_supplied",
]
