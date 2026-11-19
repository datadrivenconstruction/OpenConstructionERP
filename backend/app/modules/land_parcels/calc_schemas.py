# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response shapes of parcel subdivision, merge, corner register and setback check."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.land_parcels.schemas import FindingOut

Coord = list[float]
CornerStatus = Literal["", "found", "set", "calculated"]


class SplitIn(BaseModel):
    """``line``: cut by a and b. ``parallel``: target area next to side ``side`` (corner index).
    ``rotate``: target area cut by a line turning about ``pivot``."""

    mode: Literal["line", "parallel", "rotate"] = "line"
    a: Coord | None = Field(default=None, min_length=2, max_length=2)
    b: Coord | None = Field(default=None, min_length=2, max_length=2)
    side: int = Field(default=0, ge=0, le=2000)
    pivot: Coord | None = Field(default=None, min_length=2, max_length=2)
    target_area: float | None = Field(default=None, gt=0, le=1e10)
    refs: list[str] = Field(default_factory=list, max_length=2)
    #: True: compute and check only; False: create the children and supersede the parent.
    preview: bool = True


class PartOut(BaseModel):
    ref: str
    area: float
    ring: list[Coord]
    parcel_id: uuid.UUID | None = None


class SplitOut(BaseModel):
    parent_area: float
    parts: list[PartOut]
    cut: list[Coord] = Field(default_factory=list)
    cut_length: float | None = None
    #: Distance of the cut from the side (parallel) or its azimuth in degrees (rotate).
    position: float | None = None
    findings: list[FindingOut] = Field(default_factory=list)
    saved: bool = False


class MergeIn(BaseModel):
    parcel_ids: list[uuid.UUID] = Field(min_length=2, max_length=2)
    ref: str = Field(default="", max_length=100)
    preview: bool = True


class CornerOut(BaseModel):
    seq: int
    label: str
    e: float
    n: float
    mark: str = ""
    corner_status: str = ""
    accuracy_class: str = ""
    accuracy_m: float | None = None
    #: The class allowance for this corner (base + ppm of the distance to its neighbour).
    limit_m: float | None = None
    class_label: str = ""
    findings: list[FindingOut] = Field(default_factory=list)


class CornerClassOption(BaseModel):
    key: str
    label: str
    source: str
    status: str = ""
    base_m: float
    ppm: float = 0.0


class CornerRegisterOut(BaseModel):
    parcel_id: uuid.UUID
    parcel_ref: str
    corners: list[CornerOut]
    classes: list[CornerClassOption] = Field(default_factory=list)


class CornerPatch(BaseModel):
    corner_status: CornerStatus | None = None
    accuracy_class: str | None = Field(default=None, max_length=60)
    accuracy_m: float | None = Field(default=None, ge=0, le=100)
    mark: str | None = Field(default=None, max_length=30)
    clear_accuracy: bool = False


class SetbackIn(BaseModel):
    footprint: list[Coord] = Field(min_length=3, max_length=5000)
    name: str = Field(default="Footprint", max_length=255)
    setback_m: float = Field(gt=0, le=1000)


class EdgeOut(BaseModel):
    edge: int
    label: str
    distance: float
    encroaches: bool
    ok: bool


class SetbackOut(BaseModel):
    min_distance: float
    setback_m: float
    edges: list[EdgeOut]
    findings: list[FindingOut] = Field(default_factory=list)


class StakeCornersIn(BaseModel):
    name: str = Field(default="", max_length=255)
    tolerance_key: str = Field(default="", max_length=80)


class StakeCornersOut(BaseModel):
    request_id: uuid.UUID
    code: str
    stakes: int
