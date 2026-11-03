# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Pure helpers for site survey captures (no database, no I/O).

Planned progress is the linear share of an activity's duration that has
elapsed on the capture date. Variance is ``observed - planned`` in percentage
points: positive means the site is ahead of plan.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

DEFAULT_TOLERANCE_PCT = 5.0
TOLERANCE_KEY = "geo_hub.survey_tolerance_pct"
WINDOW_MARGIN_DAYS = 30
ANCHOR_MISS_KM = 5.0
COARSE_GSD_CM = 10.0

AHEAD, ON_TRACK, BEHIND, UNOBSERVED = "ahead", "on_track", "behind", "unobserved"


def parse_date(raw: Any) -> date | None:
    """Parse ``YYYY-MM-DD`` (or an ISO datetime) into a date; ``None`` if unreadable."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def planned_pct_on_date(start: Any, end: Any, on: date) -> float:
    """Linear planned progress, 0 before ``start``, 100 on or after ``end``."""
    s, e = parse_date(start), parse_date(end)
    if s is None and e is None:
        return 0.0
    if s is None:
        s = e
    if e is None:
        e = s
    if on >= e:
        return 100.0
    if on <= s:
        return 0.0
    return round((on - s).days / (e - s).days * 100.0, 2)


def status_for(variance: float | None, tolerance: float = DEFAULT_TOLERANCE_PCT) -> str:
    if variance is None:
        return UNOBSERVED
    if abs(variance) <= tolerance:
        return ON_TRACK
    return AHEAD if variance > 0 else BEHIND


def baseline_dates(snapshot: Any) -> dict[str, tuple[Any, Any]]:
    """``{activity_id: (start, end)}`` from a baseline ``snapshot_data`` blob.

    Accepts the same shapes the schedule module reads: ``{"activities": [...]}``
    or a bare list whose entries carry ``id``/``activity_id`` plus dates.
    """
    entries = snapshot.get("activities") if isinstance(snapshot, dict) else snapshot
    out: dict[str, tuple[Any, Any]] = {}
    if not isinstance(entries, list):
        return out
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        aid = entry.get("activity_id") or entry.get("id")
        start = entry.get("start_date") or entry.get("start") or entry.get("baseline_start")
        end = entry.get("end_date") or entry.get("finish") or entry.get("baseline_finish")
        if aid and (start or end):
            out[str(aid)] = (start, end)
    return out


def tolerance_from(metadata: Any) -> float:
    """The project's ``geo_hub.survey_tolerance_pct`` setting, falling back to 5."""
    if isinstance(metadata, dict):
        raw = metadata.get(TOLERANCE_KEY)
        if raw is None and isinstance(metadata.get("geo_hub"), dict):
            raw = metadata["geo_hub"].get("survey_tolerance_pct")
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_TOLERANCE_PCT
        if 0 <= val <= 100:
            return val
    return DEFAULT_TOLERANCE_PCT


def in_project_window(captured_on: date, start: Any, end: Any, margin_days: int = WINDOW_MARGIN_DAYS) -> bool:
    """True when the date lies within the project's dates +/- margin (open ends always pass)."""
    s, e = parse_date(start), parse_date(end)
    if s is not None and captured_on < s - timedelta(days=margin_days):
        return False
    return not (e is not None and captured_on > e + timedelta(days=margin_days))


def bbox_distance_km(bbox: tuple[float, float, float, float], lat: float, lon: float) -> float:
    """Distance in km from a point to a ``(min_lon, min_lat, max_lon, max_lat)`` box (0 inside)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    clat = min(max(lat, min_lat), max_lat)
    clon = min(max(lon, min_lon), max_lon)
    if (clat, clon) == (lat, lon):
        return 0.0
    p1, p2 = math.radians(lat), math.radians(clat)
    dphi, dlmb = p2 - p1, math.radians(clon - lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))
