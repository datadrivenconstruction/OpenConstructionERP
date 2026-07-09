# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Pure geometry take-off tests — NO database, NO app.database import.

Covers app.modules.acap.takeoff: floor_area, wall_length, opening_area,
net_wall_area, takeoff(). All pure functions over the acap.layout.schema
pydantic models (FloorPlan/Level/Room/Opening) — deterministic geometry only.
"""

from __future__ import annotations

from app.modules.acap.layout.schema import Level, Opening, Point, Room
from app.modules.acap.takeoff import (
    OPENING_HEIGHT_M,
    WALL_HEIGHT_M,
    floor_area,
    net_wall_area,
    opening_area,
    takeoff,
    wall_length,
)


def _rect_room(name: str, x0: float, y0: float, x1: float, y1: float, room_type: str = "kamar_tidur") -> Room:
    """CCW axis-aligned rectangle room from (x0,y0) to (x1,y1)."""
    w, h = x1 - x0, y1 - y0
    return Room(
        name=name,
        type=room_type,  # type: ignore[arg-type]
        polygon=[
            Point(x=x0, y=y0),
            Point(x=x1, y=y0),
            Point(x=x1, y=y1),
            Point(x=x0, y=y1),
        ],
        area_m2=w * h,
    )


# ── Assertion 1: single room, no openings ───────────────────────────────────


def test_single_room_no_openings():
    room = _rect_room("Kamar Tidur", 0.0, 0.0, 3.0, 4.0)
    level = Level(level=1, rooms=[room], walls=[], openings=[])

    assert WALL_HEIGHT_M == 3.0
    assert floor_area(level) == 12.0
    assert wall_length(level) == 14.0
    gross = wall_length(level) * WALL_HEIGHT_M
    assert gross == 42.0
    assert opening_area(level) == 0.0
    assert net_wall_area(level) == 42.0

    result = takeoff_single(level)
    assert result["floor_area_m2"] == 12.0
    assert result["wall_length_m"] == 14.0
    assert result["gross_wall_area_m2"] == 42.0
    assert result["opening_area_m2"] == 0.0
    assert result["net_wall_area_m2"] == 42.0


def takeoff_single(level: Level) -> dict:
    """Helper: run takeoff() on a single-level plan-like object and return that level's dict."""
    from app.modules.acap.layout.schema import FloorPlan, Kavling

    plan = FloorPlan(kavling=Kavling(width_m=20.0, length_m=20.0), levels=[level])
    out = takeoff(plan)
    return out[0]


# ── Assertion 2: add one door width 0.9 ─────────────────────────────────────


def test_single_room_with_door():
    room = _rect_room("Kamar Tidur", 0.0, 0.0, 3.0, 4.0)
    door = Opening(type="door", room="Kamar Tidur", width_m=0.9)
    level = Level(level=1, rooms=[room], walls=[], openings=[door])

    assert OPENING_HEIGHT_M["door"] == 2.1
    expected_opening_area = 0.9 * 2.1
    assert abs(opening_area(level) - expected_opening_area) < 1e-9
    assert abs(opening_area(level) - 1.89) < 1e-9

    expected_net = 42.0 - 1.89
    assert abs(net_wall_area(level) - expected_net) < 1e-9
    assert abs(net_wall_area(level) - 40.11) < 1e-9


# ── Assertion 3: two adjacent rooms sharing one full edge — dedup ──────────


def test_adjacent_rooms_shared_edge_deduped():
    room_a = _rect_room("A", 0.0, 0.0, 3.0, 4.0)
    room_b = _rect_room("B", 3.0, 0.0, 6.0, 4.0)
    level = Level(level=1, rooms=[room_a, room_b], walls=[], openings=[])

    # Naive (no dedup) sum would be 14.0 (room A perimeter) + 14.0 (room B
    # perimeter) = 28.0. The shared edge x=3, y in [0,4] (length 4) must be
    # counted ONCE, not twice.
    naive_sum = 14.0 + 14.0
    deduped = wall_length(level)

    assert deduped == 24.0
    assert deduped != naive_sum
    assert floor_area(level) == 24.0  # 12.0 + 12.0
