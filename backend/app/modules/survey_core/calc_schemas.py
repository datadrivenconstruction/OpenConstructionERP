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


class InstrumentClassOut(BaseModel):
    key: str
    angle_sd_sec: float
    dist_sd_mm: float
    dist_ppm: float
    centering_sd_mm: float


class CalcClassesOut(BaseModel):
    closure: list[ClosureClassOut] = Field(default_factory=list)
    corner: list[CornerClassOut] = Field(default_factory=list)
    #: Instrument accuracy grades for the least-squares weights (the same in every market).
    instruments: list[InstrumentClassOut] = Field(default_factory=list)


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
    #: ``bowditch`` (compass rule) or ``lsq`` (least squares; Bowditch is returned alongside).
    method: Literal["bowditch", "lsq"] = "bowditch"
    instrument_key: str = Field(default="", max_length=32)
    angle_sd_sec: float | None = Field(default=None, gt=0, le=600)
    dist_sd_mm: float | None = Field(default=None, ge=0, le=1000)
    dist_ppm: float | None = Field(default=None, ge=0, le=1000)
    centering_sd_mm: float | None = Field(default=None, ge=0, le=100)
    save_points: bool = False
    note: str = Field(default="", max_length=2000)


class LsqResidualOut(BaseModel):
    kind: Literal["angle", "distance"]
    ref: str
    observed: float
    #: Arc seconds for an angle, millimetres for a distance.
    residual: float
    sd: float
    redundancy: float
    standardized: float | None = None
    flagged: bool = False
    suspect: bool = False


class EllipseOut(BaseModel):
    ref: str
    a_m: float
    b_m: float
    azimuth_deg: float
    sd_e_m: float = 0.0
    sd_n_m: float = 0.0


class LsqStationOut(BaseModel):
    station_id: str
    e: float
    n: float
    fixed: bool = False
    #: LSQ minus Bowditch, millimetres.
    d_e_mm: float = 0.0
    d_n_mm: float = 0.0


class LsqOut(BaseModel):
    iterations: int
    observations: int
    unknowns: int
    redundancy: int
    vtpv: float
    sigma0: float
    chi2_lower: float
    chi2_upper: float
    chi2_pass: bool
    alpha: float
    confidence_95: float
    angle_sd_sec: float
    dist_sd_mm: float
    dist_ppm: float
    centering_sd_mm: float
    stations: list[LsqStationOut] = Field(default_factory=list)
    residuals: list[LsqResidualOut] = Field(default_factory=list)
    ellipses: list[EllipseOut] = Field(default_factory=list)
    relative_ellipses: list[EllipseOut] = Field(default_factory=list)


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
    #: Bowditch-adjusted stations (always computed, the comparison column for LSQ).
    stations: list[AdjustedStationOut] = Field(default_factory=list)
    method: str = "bowditch"
    lsq: LsqOut | None = None
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


class CalcDemoOut(BaseModel):
    """Field observations of the riverside survey demo, ready to load into the calculation forms."""

    traverse: FieldTraverseIn
    level_book: LevelBookIn


class TraverseReportIn(BaseModel):
    """A traverse to print: the same input as the calculation plus labels in the reader's language."""

    traverse: FieldTraverseIn
    title: str = Field(default="", max_length=255)
    labels: dict[str, str] = Field(default_factory=dict, max_length=200)


SurveyLinkKind = Literal["traverse", "point_set"]


class DiaryLinkIn(BaseModel):
    """Record a traverse, level run or import in the site diary of its day."""

    diary_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    title: str = Field(min_length=1, max_length=500)
    crew: str = Field(default="", max_length=500)
    instrument: str = Field(default="", max_length=255)
    weather: str = Field(default="", max_length=255)
    note: str = Field(default="", max_length=2000)


class DiaryLinkOut(BaseModel):
    entry_id: str
    diary_id: str
    diary_date: str
    title: str
    crew: str = ""
    instrument: str = ""
    weather: str = ""


class DocumentLinkOut(BaseModel):
    reference_id: str
    file_kind: str
    file_id: str
    label: str = ""


class SurveyLinksOut(BaseModel):
    kind: SurveyLinkKind
    target_id: str
    diary: list[DiaryLinkOut] = Field(default_factory=list)
    documents: list[DocumentLinkOut] = Field(default_factory=list)
