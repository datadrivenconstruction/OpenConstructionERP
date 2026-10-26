# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Geofence and clock-shift arithmetic for the field time clock​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Pure standard library: no ORM, no session, no FastAPI. The service and the
``field_time.clock_*`` validation rules both call these functions, so one
answer to "was this clock inside the site" and "do these shifts overlap" exists
in the whole platform, and it is unit-tested without a database.

Positions are WGS84 degrees. Distances are metres on a spherical earth
(haversine), which is well inside a metre at site scale and far below the
accuracy any phone reports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

EARTH_RADIUS_M = 6_371_008.8

SHAPE_CIRCLE = "circle"
SHAPE_POLYGON = "polygon"
ALL_SHAPES = (SHAPE_CIRCLE, SHAPE_POLYGON)

KIND_IN = "in"
KIND_OUT = "out"
ALL_KINDS = (KIND_IN, KIND_OUT)

APPROVAL_NOT_REQUIRED = "not_required"
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
ALL_APPROVAL_STATUSES = (APPROVAL_NOT_REQUIRED, APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_REJECTED)

#: A shift still open after this many hours is reported as a missing clock-out.
MISSING_CLOCK_OUT_HOURS = 16

#: Retention bounds for stored clock positions (days).
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650
DEFAULT_RETENTION_DAYS = 90


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS84 points in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def point_in_polygon(lat: float, lng: float, polygon: list[list[float]] | list[tuple[float, float]]) -> bool:
    """Ray casting on ``[[lat, lng], ...]``; the ring may be open or closed."""
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        yi, xi = float(polygon[i][0]), float(polygon[i][1])
        yj, xj = float(polygon[j][0]), float(polygon[j][1])
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lng < x_cross:
                inside = not inside
        j = i
    return inside


def _distance_to_segment_m(lat: float, lng: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    """Approximate metres from a point to a segment (local equirectangular plane)."""
    k = math.cos(math.radians(lat))
    ax, ay = (a[1] - lng) * k, a[0] - lat
    bx, by = (b[1] - lng) * k, b[0] - lat
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    t = 0.0 if seg == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg))
    px, py = ax + t * dx, ay + t * dy
    return math.radians(math.hypot(px, py)) * EARTH_RADIUS_M


def distance_to_polygon_edge_m(lat: float, lng: float, polygon: list[list[float]]) -> float:
    """Shortest distance from a point to the polygon's boundary in metres."""
    pts = [(float(p[0]), float(p[1])) for p in polygon]
    if not pts:
        return math.inf
    best = math.inf
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        best = min(best, _distance_to_segment_m(lat, lng, a, b))
    return best


@dataclass(frozen=True)
class FenceSpec:
    """The geometry of one site geofence, independent of the ORM row."""

    fence_id: str
    name: str
    shape: str
    center_lat: float | None = None
    center_lng: float | None = None
    radius_m: float | None = None
    polygon: tuple[tuple[float, float], ...] = ()
    tolerance_m: float = 0.0


@dataclass(frozen=True)
class FenceHit:
    """Where a position sits relative to a fence.

    ``distance_m`` is 0 inside, otherwise the metres outside the boundary
    (tolerance not subtracted), so a supervisor sees the honest figure.
    """

    fence_id: str
    name: str
    inside: bool
    distance_m: float


def validate_fence(spec: FenceSpec) -> list[str]:
    """Return problem codes for a fence definition (empty when it is usable)."""
    problems: list[str] = []
    if spec.shape not in ALL_SHAPES:
        problems.append("shape_unknown")
        return problems
    if spec.shape == SHAPE_CIRCLE:
        if spec.center_lat is None or spec.center_lng is None:
            problems.append("center_required")
        elif not (-90 <= spec.center_lat <= 90 and -180 <= spec.center_lng <= 180):
            problems.append("center_out_of_range")
        if spec.radius_m is None or spec.radius_m <= 0:
            problems.append("radius_positive")
    else:
        if len(spec.polygon) < 3:
            problems.append("polygon_min_points")
        for lat, lng in spec.polygon:
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                problems.append("polygon_out_of_range")
                break
    if spec.tolerance_m < 0:
        problems.append("tolerance_negative")
    return problems


def evaluate_fence(lat: float, lng: float, spec: FenceSpec) -> FenceHit:
    """Is the position inside the fence (tolerance counts as inside)?"""
    if spec.shape == SHAPE_CIRCLE and spec.center_lat is not None and spec.center_lng is not None:
        d = haversine_m(lat, lng, spec.center_lat, spec.center_lng) - float(spec.radius_m or 0)
        outside_by = max(0.0, d)
    else:
        poly = [list(p) for p in spec.polygon]
        outside_by = 0.0 if point_in_polygon(lat, lng, poly) else distance_to_polygon_edge_m(lat, lng, poly)
    return FenceHit(
        fence_id=spec.fence_id,
        name=spec.name,
        inside=outside_by <= spec.tolerance_m,
        distance_m=round(outside_by, 1),
    )


def evaluate_fences(lat: float, lng: float, specs: list[FenceSpec]) -> FenceHit | None:
    """The best fence for a position: the first that contains it, else the nearest.

    None when the project has no fences at all, in which case a clock is
    neither inside nor outside anything and needs no approval.
    """
    hits = [evaluate_fence(lat, lng, s) for s in specs]
    if not hits:
        return None
    inside = [h for h in hits if h.inside]
    if inside:
        return min(inside, key=lambda h: h.distance_m)
    return min(hits, key=lambda h: h.distance_m)


def approval_for(hit: FenceHit | None) -> str:
    """Outside the fence is flagged for approval, never refused."""
    if hit is None or hit.inside:
        return APPROVAL_NOT_REQUIRED
    return APPROVAL_PENDING


# ── Shifts ──────────────────────────────────────────────────────────────────


@dataclass
class Shift:
    """A clock-in paired with its clock-out (``ended_at`` None while open)."""

    worker: str
    started_at: datetime
    ended_at: datetime | None
    in_event_id: str
    out_event_id: str | None = None
    fence_id: str | None = None
    approval_statuses: list[str] = field(default_factory=list)


def pair_shifts(events: list[dict[str, Any]]) -> list[Shift]:
    """Pair clock events into shifts per worker, in time order.

    Each event dict carries ``id``, ``worker``, ``kind``, ``occurred_at``
    (aware datetime), optional ``geofence_id`` and ``approval_status``. A second
    ``in`` before an ``out`` closes nothing: the first shift stays open (it is a
    missing clock-out) and a new one starts. An ``out`` with no open shift is
    ignored here; the service refuses it at capture time.
    """
    ordered = sorted(events, key=lambda e: (str(e["worker"]), e["occurred_at"], 0 if e["kind"] == KIND_IN else 1))
    open_by_worker: dict[str, Shift] = {}
    shifts: list[Shift] = []
    for ev in ordered:
        worker = str(ev["worker"])
        status = str(ev.get("approval_status") or APPROVAL_NOT_REQUIRED)
        if ev["kind"] == KIND_IN:
            shift = Shift(
                worker=worker,
                started_at=ev["occurred_at"],
                ended_at=None,
                in_event_id=str(ev["id"]),
                fence_id=ev.get("geofence_id"),
                approval_statuses=[status],
            )
            open_by_worker[worker] = shift
            shifts.append(shift)
        else:
            shift = open_by_worker.pop(worker, None)
            if shift is None:
                continue
            shift.ended_at = ev["occurred_at"]
            shift.out_event_id = str(ev["id"])
            shift.approval_statuses.append(status)
    return shifts


def missing_clock_outs(shifts: list[Shift], now: datetime) -> list[Shift]:
    """Open shifts older than :data:`MISSING_CLOCK_OUT_HOURS`, or superseded ones."""
    out: list[Shift] = []
    by_worker: dict[str, list[Shift]] = {}
    for s in shifts:
        by_worker.setdefault(s.worker, []).append(s)
    for worker_shifts in by_worker.values():
        worker_shifts.sort(key=lambda s: s.started_at)
        for i, s in enumerate(worker_shifts):
            if s.ended_at is not None:
                continue
            superseded = i < len(worker_shifts) - 1
            stale = now - s.started_at > timedelta(hours=MISSING_CLOCK_OUT_HOURS)
            if superseded or stale:
                out.append(s)
    return out


def overlapping_shifts(shifts: list[Shift]) -> list[tuple[Shift, Shift]]:
    """Pairs of closed shifts of the same worker whose intervals overlap."""
    pairs: list[tuple[Shift, Shift]] = []
    by_worker: dict[str, list[Shift]] = {}
    for s in shifts:
        if s.ended_at is not None:
            by_worker.setdefault(s.worker, []).append(s)
    for worker_shifts in by_worker.values():
        worker_shifts.sort(key=lambda s: s.started_at)
        for i, a in enumerate(worker_shifts):
            for b in worker_shifts[i + 1 :]:
                if b.started_at >= (a.ended_at or a.started_at):
                    break
                pairs.append((a, b))
    return pairs


def shift_hours(shift: Shift, break_minutes: int = 0) -> Decimal:
    """Paid hours of a closed shift, two decimals, never negative."""
    if shift.ended_at is None:
        return Decimal("0")
    seconds = (shift.ended_at - shift.started_at).total_seconds() - max(0, break_minutes) * 60
    hours = Decimal(str(max(0.0, seconds) / 3600))
    return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def effective_break(shift: Shift, break_minutes: int) -> int:
    """The break never exceeds the shift itself."""
    if shift.ended_at is None:
        return 0
    minutes = int((shift.ended_at - shift.started_at).total_seconds() // 60)
    return max(0, min(break_minutes, minutes))


def shift_is_approved(shift: Shift) -> bool:
    """A shift counts once each of its flagged ends has a supervisor's approval."""
    return all(s in (APPROVAL_NOT_REQUIRED, APPROVAL_APPROVED) for s in shift.approval_statuses)


def unapproved_outside(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clock events outside the fence that no supervisor has approved yet."""
    return [e for e in events if str(e.get("approval_status")) in (APPROVAL_PENDING, APPROVAL_REJECTED)]


def purge_cutoff(today: date, retention_days: int) -> date:
    """Positions captured before this date are erased."""
    days = max(MIN_RETENTION_DAYS, min(MAX_RETENTION_DAYS, int(retention_days)))
    return today - timedelta(days=days)


def read_clock_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], datetime | None]:
    """Unpack the validation payload: event dicts with parsed datetimes and ``now``."""
    events: list[dict[str, Any]] = []
    for raw in payload.get("clock_events") or []:
        if not isinstance(raw, dict):
            continue
        occurred = raw.get("occurred_at")
        if isinstance(occurred, str):
            try:
                occurred = datetime.fromisoformat(occurred)
            except ValueError:
                continue
        if not isinstance(occurred, datetime):
            continue
        events.append({**raw, "occurred_at": occurred})
    now_raw = payload.get("now")
    now = datetime.fromisoformat(now_raw) if isinstance(now_raw, str) else None
    return events, now


__all__ = [
    "ALL_APPROVAL_STATUSES",
    "ALL_KINDS",
    "ALL_SHAPES",
    "APPROVAL_APPROVED",
    "APPROVAL_NOT_REQUIRED",
    "APPROVAL_PENDING",
    "APPROVAL_REJECTED",
    "DEFAULT_RETENTION_DAYS",
    "KIND_IN",
    "KIND_OUT",
    "MISSING_CLOCK_OUT_HOURS",
    "SHAPE_CIRCLE",
    "SHAPE_POLYGON",
    "FenceHit",
    "FenceSpec",
    "Shift",
    "approval_for",
    "effective_break",
    "evaluate_fence",
    "evaluate_fences",
    "haversine_m",
    "missing_clock_outs",
    "overlapping_shifts",
    "pair_shifts",
    "point_in_polygon",
    "purge_cutoff",
    "read_clock_payload",
    "shift_hours",
    "shift_is_approved",
    "unapproved_outside",
    "validate_fence",
]
