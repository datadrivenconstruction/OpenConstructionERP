# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response shapes of the survey calculations (COGO, field traverse, level book)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.modules.survey_core.schemas import Finding, TraverseOut

AngleUnit = Literal["deg", "dms", "gon"]
CogoMethod = Literal["inverse", "polar", "bearing_bearing", "line_line", "distance_distance", "offset", "area"]
Coord = list[float]
Angle = str | float


class ClosureClassOut(BaseModel):
    key: str
    label: str
    country: str
    source: str
    status: str = ""
    angular_k_sec: float | None = None
    traverse_min_ratio: int | None = None
    level_k_mm: float | None = None


class CornerClassOut(BaseModel):
    key: str
    label: str
    country: str
    source: str
    status: str = ""
    base_m: float
    ppm: float = 0.0


class CalcClassesOut(BaseModel):
    closure: list[ClosureClassOut] = Field(default_factory=list)
    corner: list[CornerClassOut] = Field(default_factory=list)


class CogoRequest(BaseModel):
    """Inputs by method: inverse a,b; polar a,bearing_a,distance; bearing_bearing a,bearing_a,b,bearing_b;
    line_line a,b,c,d; distance_distance a,distance_a,b,distance_b; offset a,b,c; area ring."""

    method: CogoMethod
    angle_unit: AngleUnit = "deg"
    a: Coord | None = Field(default=None, min_length=2, max_length=3)
    b: Coord | None = Field(default=None, min_length=2, max_length=3)
    c: Coord | None = Field(default=None, min_length=2, max_length=3)
    d: Coord | None = Field(default=None, min_length=2, max_length=3)
    bearing_a: Angle | None = None
    bearing_b: Angle | None = None
    distance: float | None = Field(default=None, ge=0, le=1e7)
    distance_a: float | None = Field(default=None, ge=0, le=1e7)
    distance_b: float | None = Field(default=None, ge=0, le=1e7)
    ring: list[Coord] | None = Field(default=None, max_length=5000)


class CogoResult(BaseModel):
    method: str
    angle_unit: str
    distance: float | None = None
    bearing_deg: float | None = None
    #: The bearing in the request's unit, as text ready to show.
    bearing_text: str | None = None
    d_e: float | None = None
    d_n: float | None = None
    d_z: float | None = None
    chainage: float | None = None
    offset: float | None = None
    area: float | None = None
    perimeter: float | None = None
    #: Computed points (E, N); two for an ambiguous distance-distance intersection.
    solutions: list[list[float]] = Field(default_factory=list)
    #: The normalised inputs, to keep with a saved point.
    inputs: dict = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)


class ComputedPointIn(BaseModel):
    point_id: str = Field(min_length=1, max_length=64)
    e: float
    n: float
    z: float | None = None
    code: str = Field(default="", max_length=64)
    kind: Literal["control", "benchmark", "topo", "stake", "asbuilt"] = "topo"
    method: str = Field(min_length=1, max_length=32)
    inputs: dict = Field(default_factory=dict)
    description: str = Field(default="", max_length=255)


class ComputedPointsSave(BaseModel):
    name: str = Field(default="", max_length=255)
    points: list[ComputedPointIn] = Field(min_length=1, max_length=5000)


class SavedPoints(BaseModel):
    point_set_id: str
    saved: int


class StationIn(BaseModel):
    station_id: str = Field(min_length=1, max_length=64)
    angle: Angle
    distance_m: float | None = Field(default=None, gt=0, le=1e6)


class KnownPoint(BaseModel):
    station_id: str = Field(default="", max_length=64)
    e: float
    n: float


class FieldTraverseIn(BaseModel):
    name: str = Field(default="Traverse", min_length=1, max_length=255)
    shape: Literal["loop", "link"] = "loop"
    angle_unit: AngleUnit = "dms"
    angle_sense: Literal["right", "left"] = "right"
    start: KnownPoint
    #: Loop: azimuth of the first leg. Link: backsight azimuth at the start station.
    azimuth: Angle
    stations: list[StationIn] = Field(min_length=2, max_length=500)
    end: KnownPoint | None = None
    closing_azimuth: Angle | None = None
    class_key: str = Field(default="", max_length=60)
    angular_k_sec: float | None = Field(default=None, gt=0, le=3600)
    min_ratio: int | None = Field(default=None, ge=100, le=10_000_000)
    save_points: bool = False
    note: str = Field(default="", max_length=2000)


class AdjustedStationOut(BaseModel):
    station_id: str
    e: float
    n: float
    angle_corrected_deg: float
    azimuth_deg: float | None = None
    c_e: float = 0.0
    c_n: float = 0.0


class FieldTraverseOut(BaseModel):
    shape: str
    angle_count: int
    angle_sum_deg: float
    expected_sum_deg: float | None = None
    angular_misclosure_sec: float
    angular_correction_sec: float
    angular_k_sec: float | None = None
    angular_allowed_sec: float | None = None
    angular_verdict: str = "no_profile"
    length_m: float
    f_e: float
    f_n: float
    misclosure_m: float
    ratio: int | None = None
    min_ratio: int | None = None
    linear_verdict: str = "no_profile"
    class_label: str = ""
    stations: list[AdjustedStationOut] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    traverse: TraverseOut | None = None
    points_saved: int = 0


class BookRowIn(BaseModel):
    station: str = Field(min_length=1, max_length=64)
    bs: float | None = Field(default=None, ge=-100, le=100)
    is_: float | None = Field(default=None, ge=-100, le=100, alias="is")
    fs: float | None = Field(default=None, ge=-100, le=100)
    distance_m: float | None = Field(default=None, ge=0, le=1e6)
    rl: float | None = None

    model_config = {"populate_by_name": True}


class LevelBookIn(BaseModel):
    name: str = Field(default="Level run", min_length=1, max_length=255)
    method: Literal["rise_fall", "hi"] = "rise_fall"
    start_rl: float
    close_rl: float | None = None
    rows: list[BookRowIn] = Field(min_length=2, max_length=2000)
    class_key: str = Field(default="", max_length=60)
    k_mm: float | None = Field(default=None, gt=0, le=1000)
    write_rls: bool = False
    note: str = Field(default="", max_length=2000)


class ReducedRowOut(BaseModel):
    station: str
    bs: float | None = None
    is_: float | None = Field(default=None, serialization_alias="is")
    fs: float | None = None
    rise: float | None = None
    fall: float | None = None
    hi: float | None = None
    rl: float
    run_m: float
    correction_mm: float
    step_mm: float = 0.0
    rl_adjusted: float


class LevelBookOut(BaseModel):
    method: str
    rows: list[ReducedRowOut]
    sum_bs: float
    sum_fs: float
    sum_rise: float
    sum_fall: float
    first_rl: float
    last_rl: float
    arithmetic_ok: bool
    known_close_rl: float | None = None
    misclosure_mm: float | None = None
    distance_km: float
    k_mm: float | None = None
    allowed_mm: float | None = None
    verdict: str = "no_profile"
    class_label: str = ""
    findings: list[Finding] = Field(default_factory=list)
    traverse: TraverseOut | None = None
    points_updated: int = 0
