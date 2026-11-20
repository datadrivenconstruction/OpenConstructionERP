# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schemas of the plan-editor surface routes: design pads, contours, section samples, mesh."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.modules.surfaces_volumes.schemas import Finding, SurfaceOut

Coord = tuple[float, float]


class PadCreate(BaseModel):
    """A design pad drawn on the plan: outline, level and batters."""

    name: str = Field("", max_length=255)
    outline: list[Coord] = Field(min_length=3, max_length=5000)
    level: float = Field(ge=-11000, le=9000)
    #: Batter 1:n, n horizontal to 1 vertical; 0 means no batters.
    batter_n: float = Field(2.0, ge=0, le=100)
    cross_fall_pct: float = Field(0.0, ge=-50, le=50)
    #: Grid bearing the top falls towards, degrees clockwise from north.
    fall_bearing_deg: float = Field(0.0, ge=0, lt=360)
    #: The existing ground the batters run out to; without it the pad is the top alone.
    ground_surface_id: uuid.UUID | None = None
    note: str = Field("", max_length=4000)


class PadOut(BaseModel):
    surface: SurfaceOut
    top: list[tuple[float, float, float]]
    daylight: list[tuple[float, float, float]] = Field(default_factory=list)
    unresolved: int = 0
    findings: list[Finding] = Field(default_factory=list)


class PadCheckIn(BaseModel):
    """The live SRV-083 check the editor runs while a pad is drawn."""

    name: str = Field("", max_length=255)
    outline: list[Coord] = Field(default_factory=list, max_length=5000)
    level: float | None = None


class PadCheckOut(BaseModel):
    valid: bool
    area_m2: float
    self_intersections: int
    findings: list[Finding] = Field(default_factory=list)


class ContourLineOut(BaseModel):
    z: float
    index: bool
    closed: bool = False
    coords: list[Coord]


class ContoursOut(BaseModel):
    surface_id: uuid.UUID
    interval: float
    auto_interval: float
    index_every: int
    z_min: float | None = None
    z_max: float | None = None
    lines: list[ContourLineOut] = Field(default_factory=list)


class SampleIn(BaseModel):
    """The section contract: ``{polyline, interval, offsets}`` to rows of heights."""

    polyline: list[Coord] = Field(min_length=2, max_length=5000)
    interval: float = Field(10.0, gt=0, le=10000)
    offsets: list[float] = Field(default_factory=lambda: [0.0], max_length=401)


class SampleRowOut(BaseModel):
    ch: float
    offset: float
    e: float
    n: float
    z: float | None = None


class SampleOut(BaseModel):
    surface_id: uuid.UUID
    length_m: float
    rows: list[SampleRowOut] = Field(default_factory=list)


class MeshOut(BaseModel):
    """Vertices and triangles for hillshade and TIN edges on the plan."""

    surface_id: uuid.UUID
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]
    z_min: float | None = None
    z_max: float | None = None


__all__ = [
    "ContourLineOut",
    "ContoursOut",
    "MeshOut",
    "PadCheckIn",
    "PadCheckOut",
    "PadCreate",
    "PadOut",
    "SampleIn",
    "SampleOut",
    "SampleRowOut",
]
