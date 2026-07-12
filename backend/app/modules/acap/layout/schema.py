"""ACAP floor-plan JSON schema — pydantic v2 models for layout representation.

Pure Python (pydantic v2 + stdlib only).  No shapely, no DB, no app.* imports
beyond pydantic.  Rooms are axis-aligned rectangles in MVP (D1).

Coordinate system: origin at south-west corner of the kavling, x→east, y→north.
All dimensions in meters.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Point ────────────────────────────────────────────────────────────────────


class Point(BaseModel):
    """A 2-D point in meters."""

    x: float
    y: float

    def __hash__(self) -> int:
        return hash((self.x, self.y))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Point):
            return NotImplemented
        return self.x == other.x and self.y == other.y


# ── Room types ───────────────────────────────────────────────────────────────

ROOM_TYPES = Literal[
    "kamar_tidur_utama",
    "kamar_tidur",
    "kamar_mandi",
    "dapur",
    "ruang_tamu",
    "ruang_keluarga",
    "ruang_makan",
    "carport",
    "garasi",
    "musholla",
    "gudang",
    "teras",
    "taman",
    "sirkulasi",
    "other",
]

# ── Room ─────────────────────────────────────────────────────────────────────


class Room(BaseModel):
    """A single room — axis-aligned rectangle in MVP.

    ``polygon`` MUST be exactly 4 corners in CCW order.  The first point is
    NOT repeated at the end (closed implicitly).
    """

    name: str = Field(max_length=120)
    type: ROOM_TYPES  # type: ignore[valid-type]
    polygon: list[Point]
    area_m2: float = Field(ge=0.0)


# ── Wall ─────────────────────────────────────────────────────────────────────


class Wall(BaseModel):
    """A wall segment between two points."""

    start: Point
    end: Point
    thickness_m: float = 0.15


# ── Opening ──────────────────────────────────────────────────────────────────


class Opening(BaseModel):
    """Door or window belonging to a room."""

    type: Literal["door", "window"]
    room: str  # room name this opening belongs to
    width_m: float = Field(gt=0.0)


# ── Level ────────────────────────────────────────────────────────────────────


class Level(BaseModel):
    """One floor of the layout."""

    level: int = Field(ge=1)  # 1-based floor number
    rooms: list[Room] = []
    walls: list[Wall] = []
    openings: list[Opening] = []


# ── Kavling ──────────────────────────────────────────────────────────────────


class Kavling(BaseModel):
    """Lot bounding box — origin at (0, 0)."""

    width_m: float = Field(gt=0.0)
    length_m: float = Field(gt=0.0)


# ── FloorPlan ────────────────────────────────────────────────────────────────


class FloorPlan(BaseModel):
    """Complete multi-level floor-plan."""

    kavling: Kavling
    levels: list[Level]
    requirement_text: str = ""
    jumlah_lantai: int = Field(ge=1, default=1)
    generated_by: str = ""  # model id
    notes: str = ""


# ── Helper ───────────────────────────────────────────────────────────────────


def bounding_box(room: Room) -> tuple[float, float, float, float]:
    """Return ``(min_x, min_y, max_x, max_y)`` for the given room."""
    if not room.polygon:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p.x for p in room.polygon]
    ys = [p.y for p in room.polygon]
    return (min(xs), min(ys), max(xs), max(ys))
