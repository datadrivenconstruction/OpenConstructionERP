"""Geometric floor-plan validator — pure Python, no shapely/DB.

All checks are axis-aligned (MVP D1).  Rooms are rectangles with exactly
4 corners in CCW order.
"""

from __future__ import annotations

from app.modules.acap.layout.schema import (
    FloorPlan,
    Level,
    Point,
    Room,
    bounding_box,
)

# ── Constants ────────────────────────────────────────────────────────────────

MIN_AREA_M2: dict[str, float] = {
    "kamar_tidur_utama": 9.0,
    "kamar_tidur": 6.0,
    "kamar_mandi": 2.25,
    "dapur": 4.0,
    "ruang_tamu": 7.5,
    "ruang_keluarga": 9.0,
    "ruang_makan": 6.0,
    "carport": 12.5,
    "garasi": 15.0,
    "musholla": 2.25,
    "gudang": 2.0,
    "teras": 3.0,
    "taman": 0.0,
    "sirkulasi": 0.0,
    "other": 2.0,
}

DEFAULT_MIN_AREA: float = 4.0
MIN_DIM_M: float = 1.2
KDB_MAX: float = 0.7  # max ground-floor footprint ratio
AREA_TOL: float = 0.05  # 5 % relative tolerance for declared vs. computed area
EPS: float = 1e-6


# ── Helpers ──────────────────────────────────────────────────────────────────


def shoelace_area(points: list[Point]) -> float:
    """Compute the absolute area of a polygon via the shoelace formula."""
    n = len(points)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        j = (i + 1) % n
        total += points[i].x * points[j].y
        total -= points[j].x * points[i].y
    return abs(total) / 2.0


def rect_overlap_area(a: Room, b: Room) -> float:
    """Axis-aligned rectangle intersection area.  Returns 0.0 if no overlap."""
    a_min_x, a_min_y, a_max_x, a_max_y = bounding_box(a)
    b_min_x, b_min_y, b_max_x, b_max_y = bounding_box(b)

    dx = max(0.0, min(a_max_x, b_max_x) - max(a_min_x, b_min_x))
    dy = max(0.0, min(a_max_y, b_max_y) - max(a_min_y, b_min_y))
    return dx * dy


def _is_axis_aligned_rect(polygon: list[Point]) -> bool:
    """True when *polygon* has exactly 4 corners forming an axis-aligned rect."""
    if len(polygon) != 4:
        return False

    xs = sorted({p.x for p in polygon})
    ys = sorted({p.y for p in polygon})

    if len(xs) != 2 or len(ys) != 2:
        return False

    expected = {
        Point(x=xs[0], y=ys[0]),
        Point(x=xs[1], y=ys[0]),
        Point(x=xs[1], y=ys[1]),
        Point(x=xs[0], y=ys[1]),
    }
    return set(polygon) == expected


def _area_matches(declared: float, computed: float) -> bool:
    """True when declared and computed areas are within AREA_TOL relative."""
    if computed == 0.0:
        return declared == 0.0
    diff = abs(declared - computed) / computed
    return diff <= AREA_TOL


# ── Exceptions ───────────────────────────────────────────────────────────────


class LayoutValidationError(ValueError):
    """Raised when one or more geometric constraints are violated."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        msg = f"Layout validation failed with {len(reasons)} reason(s):\n" + "\n".join(
            f"  - {r}" for r in reasons
        )
        super().__init__(msg)


# ── Main validator ───────────────────────────────────────────────────────────


def validate_plan(plan: FloorPlan) -> None:
    """Raise :class:`LayoutValidationError` if *plan* violates any rule.

    Collects ALL reasons before raising — never stops at the first error.
    """
    reasons: list[str] = []

    kavling_w = plan.kavling.width_m
    kavling_h = plan.kavling.length_m
    kavling_area = kavling_w * kavling_h

    for level in plan.levels:
        _validate_level(level, kavling_w, kavling_h, kavling_area, reasons)

    if reasons:
        raise LayoutValidationError(reasons)


def _validate_level(
    level: Level,
    kavling_w: float,
    kavling_h: float,
    kavling_area: float,
    reasons: list[str],
) -> None:
    """Validate all rooms on a single level."""
    lvl_tag = f"level {level.level}"

    # Track footprint for KDB check on ground floor (level 1)
    if level.level == 1:
        ground_footprint = 0.0

    for i, room in enumerate(level.rooms):
        room_tag = f"{lvl_tag}, room '{room.name}' (#{i + 1})"

        # ── Axis-aligned rectangle check ────────────────────────────
        poly = room.polygon
        if len(poly) < 4:
            reasons.append(f"{room_tag}: polygon has {len(poly)} points, need ≥4")
        elif not _is_axis_aligned_rect(poly):
            reasons.append(
                f"{room_tag}: polygon is not an axis-aligned rectangle "
                f"(got {[(round(p.x, 3), round(p.y, 3)) for p in poly]})"
            )

        # ── Area match ──────────────────────────────────────────────
        computed = shoelace_area(poly)
        if not _area_matches(room.area_m2, computed):
            reasons.append(
                f"{room_tag}: declared area {room.area_m2:.2f} m² differs from "
                f"computed area {computed:.2f} m² (> {AREA_TOL:.0%} tolerance)"
            )

        # ── Min area by type ────────────────────────────────────────
        min_area = MIN_AREA_M2.get(room.type, DEFAULT_MIN_AREA)
        if room.area_m2 < min_area - EPS:
            reasons.append(
                f"{room_tag}: area {room.area_m2:.2f} m² < minimum "
                f"{min_area:.2f} m² for type '{room.type}'"
            )

        # ── Min dimension ───────────────────────────────────────────
        if len(poly) >= 4:
            min_x, min_y, max_x, max_y = bounding_box(room)
            w = max_x - min_x
            h = max_y - min_y
            if w < MIN_DIM_M - EPS:
                reasons.append(
                    f"{room_tag}: width {w:.3f} m < minimum {MIN_DIM_M} m"
                )
            if h < MIN_DIM_M - EPS:
                reasons.append(
                    f"{room_tag}: height {h:.3f} m < minimum {MIN_DIM_M} m"
                )

        # ── Outside kavling bounds ──────────────────────────────────
        if len(poly) >= 4:
            min_x, min_y, max_x, max_y = bounding_box(room)
            if min_x < -EPS or min_y < -EPS:
                reasons.append(
                    f"{room_tag}: extends outside kavling (min ({min_x:.2f}, {min_y:.2f}) < (0,0))"
                )
            if max_x > kavling_w + EPS:
                reasons.append(
                    f"{room_tag}: extends outside kavling (max_x {max_x:.2f} > {kavling_w:.2f})"
                )
            if max_y > kavling_h + EPS:
                reasons.append(
                    f"{room_tag}: extends outside kavling (max_y {max_y:.2f} > {kavling_h:.2f})"
                )

        # ── Footprint for KDB ───────────────────────────────────────
        if level.level == 1 and len(poly) >= 4:
            ground_footprint += computed

        # ── Overlap with other rooms on SAME level ──────────────────
        for j in range(i + 1, len(level.rooms)):
            other = level.rooms[j]
            overlap = rect_overlap_area(room, other)
            if overlap > EPS:
                reasons.append(
                    f"{room_tag}: overlaps room '{other.name}' "
                    f"with overlap area {overlap:.4f} m²"
                )

    # ── KDB check (ground floor only) ───────────────────────────────
    if level.level == 1 and kavling_area > 0:
        kdb_ratio = ground_footprint / kavling_area
        if kdb_ratio > KDB_MAX + EPS:
            reasons.append(
                f"{lvl_tag}: ground-floor footprint {ground_footprint:.2f} m² / "
                f"kavling {kavling_area:.2f} m² = {kdb_ratio:.2%} > KDB max {KDB_MAX:.0%}"
            )


# ── Convenience ──────────────────────────────────────────────────────────────


def is_valid(plan: FloorPlan) -> tuple[bool, list[str]]:
    """Return (True, []) for valid plans; (False, reasons) otherwise. Never raises."""
    try:
        validate_plan(plan)
    except LayoutValidationError as e:
        return (False, e.reasons)
    return (True, [])
