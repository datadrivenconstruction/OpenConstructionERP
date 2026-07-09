"""Pure unit tests for ACAP layout schema + geometric validator.

No DB, no LLM, no async — plain pytest, pydantic + stdlib only.
"""

from __future__ import annotations

import pytest

from app.modules.acap.layout.schema import (
    FloorPlan,
    Kavling,
    Level,
    Point,
    Room,
    bounding_box,
)
from app.modules.acap.layout.validator import (
    LayoutValidationError,
    is_valid,
    rect_overlap_area,
    shoelace_area,
    validate_plan,
)


# ── Helper ───────────────────────────────────────────────────────────────────


def make_rect_room(name: str, rtype: str, x: float, y: float, w: float, h: float) -> Room:
    """Build an axis-aligned rectangular room with CCW polygon and ``area_m2=w*h``."""
    return Room(
        name=name,
        type=rtype,
        polygon=[
            Point(x=x, y=y),
            Point(x=x + w, y=y),
            Point(x=x + w, y=y + h),
            Point(x=x, y=y + h),
        ],
        area_m2=w * h,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Happy path
# ═══════════════════════════════════════════════════════════════════════════


def test_valid_plan():
    """A valid 3-room single-level plan does NOT raise validation errors."""
    kavling = Kavling(width_m=10, length_m=15)
    level1 = Level(
        level=1,
        rooms=[
            make_rect_room("R. Tamu", "ruang_tamu", 0, 0, 4, 4),        # 16 m²
            make_rect_room("K. Tidur Utama", "kamar_tidur_utama", 4, 0, 3, 3),  # 9 m²
            make_rect_room("K. Mandi", "kamar_mandi", 7, 0, 1.5, 1.5),  # 2.25 m²
        ],
    )
    plan = FloorPlan(kavling=kavling, levels=[level1], jumlah_lantai=1)

    # Should not raise
    validate_plan(plan)

    ok, reasons = is_valid(plan)
    assert ok, f"Expected valid but got: {reasons}"


# ═══════════════════════════════════════════════════════════════════════════
# Overlap
# ═══════════════════════════════════════════════════════════════════════════


def test_overlap_invalid():
    """Overlapping rooms on the same level → LayoutValidationError."""
    kavling = Kavling(width_m=10, length_m=10)
    room_a = make_rect_room("A", "ruang_tamu", 0, 0, 4, 4)   # 0..4
    room_b = make_rect_room("B", "kamar_tidur", 2, 2, 4, 4)   # 2..6 → overlaps A
    level1 = Level(level=1, rooms=[room_a, room_b])
    plan = FloorPlan(kavling=kavling, levels=[level1])

    with pytest.raises(LayoutValidationError) as exc_info:
        validate_plan(plan)

    reasons = exc_info.value.reasons
    assert any("overlap" in r.lower() or "overlaps" in r.lower() for r in reasons), (
        f"Expected overlap reason, got: {reasons}"
    )

    ok, _ = is_valid(plan)
    assert not ok


# ═══════════════════════════════════════════════════════════════════════════
# Small room
# ═══════════════════════════════════════════════════════════════════════════


def test_small_room_invalid():
    """kamar_tidur 2×2 = 4 m² < minimum 6 m²."""
    kavling = Kavling(width_m=10, length_m=10)
    room = make_rect_room("KT", "kamar_tidur", 0, 0, 2, 2)  # 4 m²
    level1 = Level(level=1, rooms=[room])
    plan = FloorPlan(kavling=kavling, levels=[level1])

    with pytest.raises(LayoutValidationError) as exc_info:
        validate_plan(plan)

    reasons = exc_info.value.reasons
    assert any("4.00" in r and "minimum" in r.lower() for r in reasons), (
        f"Expected small-room reason, got: {reasons}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Min dimension
# ═══════════════════════════════════════════════════════════════════════════


def test_min_dim_invalid():
    """Room 0.8 × 5 m has width < MIN_DIM_M (1.2)."""
    kavling = Kavling(width_m=10, length_m=10)
    room = make_rect_room("Tiny", "ruang_keluarga", 0, 0, 0.8, 5)  # 4 m² → OK by area, but too narrow
    level1 = Level(level=1, rooms=[room])
    plan = FloorPlan(kavling=kavling, levels=[level1])

    with pytest.raises(LayoutValidationError) as exc_info:
        validate_plan(plan)

    reasons = exc_info.value.reasons
    assert any("0.8" in r for r in reasons), f"Expected min-dim reason, got: {reasons}"


# ═══════════════════════════════════════════════════════════════════════════
# Out of bounds
# ═══════════════════════════════════════════════════════════════════════════


def test_out_of_bounds_invalid():
    """Room at x=9, w=3 on 10-wide kavling extends to 12 → invalid."""
    kavling = Kavling(width_m=10, length_m=10)
    room = make_rect_room("Spill", "ruang_tamu", 9, 0, 3, 4)  # 9→12 > 10
    level1 = Level(level=1, rooms=[room])
    plan = FloorPlan(kavling=kavling, levels=[level1])

    with pytest.raises(LayoutValidationError) as exc_info:
        validate_plan(plan)

    reasons = exc_info.value.reasons
    assert any("outside kavling" in r.lower() for r in reasons), (
        f"Expected OOB reason, got: {reasons}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Area mismatch
# ═══════════════════════════════════════════════════════════════════════════


def test_area_mismatch_invalid():
    """Declared area 99 m² but polygon is 3×3 = 9 m²."""
    kavling = Kavling(width_m=10, length_m=10)
    # Manually construct so area_m2 is wrong
    room = Room(
        name="Fake",
        type="ruang_tamu",
        polygon=[
            Point(x=0, y=0),
            Point(x=3, y=0),
            Point(x=3, y=3),
            Point(x=0, y=3),
        ],
        area_m2=99.0,  # wrong!
    )
    level1 = Level(level=1, rooms=[room])
    plan = FloorPlan(kavling=kavling, levels=[level1])

    with pytest.raises(LayoutValidationError) as exc_info:
        validate_plan(plan)

    reasons = exc_info.value.reasons
    assert any("area" in r.lower() and "differ" in r.lower() for r in reasons), (
        f"Expected area-mismatch reason, got: {reasons}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# KDB exceeded
# ═══════════════════════════════════════════════════════════════════════════


def test_kdb_exceeded():
    """Ground-floor footprint >70% of kavling area → KDB violation."""
    kavling = Kavling(width_m=10, length_m=10)  # 100 m² kavling
    # One big room: 8.5 × 8.5 = 72.25 / 100 = 72.25% > 70%
    room = make_rect_room("Big Room", "ruang_keluarga", 0, 0, 8.5, 8.5)
    level1 = Level(level=1, rooms=[room])
    plan = FloorPlan(kavling=kavling, levels=[level1])

    with pytest.raises(LayoutValidationError) as exc_info:
        validate_plan(plan)

    reasons = exc_info.value.reasons
    assert any("kdb" in r.lower() or "footprint" in r.lower() for r in reasons), (
        f"Expected KDB reason, got: {reasons}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Geometry helpers
# ═══════════════════════════════════════════════════════════════════════════


def test_shoelace_and_overlap_helpers():
    """shoelace_area and rect_overlap_area give exact answers."""
    # 3×4 rectangle → area 12
    pts = [Point(x=0, y=0), Point(x=3, y=0), Point(x=3, y=4), Point(x=0, y=4)]
    assert shoelace_area(pts) == pytest.approx(12.0)

    # Overlap: (0,0)-(4,4) with (2,2)-(6,6) → overlap (2,2)-(4,4) = 4
    a = make_rect_room("A", "ruang_tamu", 0, 0, 4, 4)
    b = make_rect_room("B", "ruang_tamu", 2, 2, 4, 4)
    assert rect_overlap_area(a, b) == pytest.approx(4.0)

    # No overlap
    c = make_rect_room("C", "ruang_tamu", 10, 10, 2, 2)
    assert rect_overlap_area(a, c) == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Smoke: bounding_box helper
# ═══════════════════════════════════════════════════════════════════════════


def test_bounding_box():
    room = make_rect_room("Test", "dapur", 1, 2, 3, 4)
    assert bounding_box(room) == (1.0, 2.0, 4.0, 6.0)
