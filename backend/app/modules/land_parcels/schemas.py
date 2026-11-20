# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Land and parcels request and response schemas.

Areas and money travel as decimal strings ("1202.67") so a lesson number reads
the same on every screen; coordinates as JSON numbers with up to four decimals.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.decimal_types import Decimal6_3, Decimal8_3, Decimal18_2, finite_decimal

ParcelStatus = Literal["needed", "negotiating", "acquired", "expropriation"]
RightKind = Literal["ownership", "lease", "easement", "servitude", "mortgage", "restriction", "other"]
PartyKind = Literal["person", "organisation", "public"]
ImportFormat = Literal["geojson", "shapefile"]
ImportTarget = Literal["parcels", "work_zone"]
#: A boundary mark key; the offered list comes from the country profile (``ProfileOut.marks``).
Mark = Annotated[str, Field(max_length=30, pattern=r"^[a-z0-9_]*$")]


class BoundaryPointIn(BaseModel):
    label: str = Field("", max_length=64)
    e: float
    n: float
    mark: Mark = ""
    accuracy_m: float | None = Field(None, ge=0, le=100)
    #: found | set | calculated | ""
    corner_status: str = Field("", max_length=20)
    accuracy_class: str = Field("", max_length=60)


class BoundaryPointOut(BoundaryPointIn):
    seq: int


class ParcelCreate(BaseModel):
    parcel_ref: str = Field(min_length=1, max_length=100)
    name: str = Field("", max_length=255)
    legal_area: finite_decimal(16, 4) | None = Field(None, ge=0)
    status: ParcelStatus = "needed"
    acquisition_cost: Decimal18_2 | None = Field(None, ge=0)
    acquired_on: date | None = None
    note: str = Field("", max_length=4000)
    points: list[BoundaryPointIn] = Field(default_factory=list, max_length=2000)


class ParcelUpdate(BaseModel):
    parcel_ref: str | None = Field(None, min_length=1, max_length=100)
    name: str | None = Field(None, max_length=255)
    legal_area: finite_decimal(16, 4) | None = Field(None, ge=0)
    status: ParcelStatus | None = None
    acquisition_cost: Decimal18_2 | None = Field(None, ge=0)
    acquired_on: date | None = None
    note: str | None = Field(None, max_length=4000)
    #: Explicit nulls clear these fields; omitted fields stay.
    clear: list[Literal["legal_area", "acquisition_cost", "acquired_on"]] = Field(default_factory=list)


class FindingOut(BaseModel):
    rule_id: str
    severity: str
    message: str
    suggestion: str | None = None
    element_ref: str | None = None


class PartyIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: PartyKind = "person"
    reference: str = Field("", max_length=255)
    note: str = Field("", max_length=4000)


class PartyOut(PartyIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class RightIn(BaseModel):
    party_id: uuid.UUID | None = None
    kind: RightKind = "ownership"
    share: str = Field("", max_length=20)
    description: str = Field("", max_length=4000)
    registry_ref: str = Field("", max_length=255)
    valid_from: date | None = None
    valid_to: date | None = None


class RightOut(RightIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parcel_id: uuid.UUID
    party_name: str = ""


class ParcelOut(BaseModel):
    id: uuid.UUID
    parcel_ref: str
    name: str
    status: ParcelStatus
    legal_area: str | None = None
    computed_area: str | None = None
    area_diff: str | None = None
    ring_closed: bool = True
    epsg: int | None = None
    acquisition_cost: str | None = None
    currency: str = ""
    acquired_on: date | None = None
    note: str = ""
    source: str = "manual"
    source_filename: str = ""
    point_count: int = 0
    rights_count: int = 0
    rights_kinds: list[str] = Field(default_factory=list)
    boq_position_id: uuid.UUID | None = None
    sent_at: datetime | None = None
    #: Parcels this one was split from or merged out of.
    parent_ids: list[str] = Field(default_factory=list)
    superseded: bool = False
    findings: list[FindingOut] = Field(default_factory=list)


class ParcelDetail(ParcelOut):
    points: list[BoundaryPointOut] = Field(default_factory=list)
    rights: list[RightOut] = Field(default_factory=list)


class WorkZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    epsg: int | None = None
    source_filename: str = ""
    vertex_count: int = 0


class MarkTypeOut(BaseModel):
    key: str
    monumented: bool


class ProfileOut(BaseModel):
    """What the active country pack adds; neutral values without one."""

    country: str = ""
    id_label_key: str
    id_label_default: str
    id_example: str = ""
    area_decimals: int = 2
    area_tolerance_source: str = ""
    export_formats: list[str] = Field(default_factory=list)
    #: The parcel number format (a full-match regex) for the live PAR-006 check; "" = any.
    id_pattern: str = ""
    marks: list[MarkTypeOut] = Field(default_factory=list)


class SettingsOut(BaseModel):
    area_tolerance_pct: Decimal
    gap_tolerance_m: Decimal

    @field_serializer("area_tolerance_pct", "gap_tolerance_m")
    def _s(self, v: Decimal) -> str:
        return format(v.normalize(), "f")


class SettingsIn(BaseModel):
    area_tolerance_pct: Decimal6_3 = Field(ge=0, le=100)
    gap_tolerance_m: Decimal8_3 = Field(ge=0, le=10)


class ParcelSummary(BaseModel):
    parcels: int = 0
    acquired: int = 0
    total_area: str = "0"
    blocking_works: int = 0
    cost_to_acquire: str = "0"
    currency: str = ""
    findings: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)


class ImportRequest(BaseModel):
    format: ImportFormat = "geojson"
    target: ImportTarget = "parcels"
    filename: str = Field("", max_length=255)
    #: GeoJSON text, or a base64 zip for a Shapefile.
    text: str = Field("", max_length=30_000_000)
    content_base64: str = Field("", max_length=70_000_000)
    id_field: str = Field("", max_length=64)
    legal_area_field: str = Field("", max_length=64)
    #: EPSG the file is in when it does not say; overrides nothing the file declares.
    source_epsg: int | None = Field(None, ge=1000, le=999999)
    #: An existing parcel id in the file: replace its boundary (``replace``) or leave it (``skip``).
    on_existing: Literal["skip", "replace"] = "skip"


class ImportFeatureOut(BaseModel):
    index: int
    ref: str
    name: str = ""
    legal_area: str | None = None
    computed_area: str | None = None
    status: str = "needed"
    vertices: int = 0
    closed: bool = True
    exists: bool = False


class ImportPreview(BaseModel):
    features_read: int = 0
    problem_count: int = 0
    problems: list[dict] = Field(default_factory=list)
    features: list[ImportFeatureOut] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    file_epsg: int | None = None
    project_epsg: int | None = None
    #: Both codes are shown; the import transforms only between these two.
    transform: str | None = None
    total_area: str = "0"


class ImportResult(BaseModel):
    created: int = 0
    replaced: int = 0
    skipped: int = 0
    work_zones: int = 0
    total_area: str = "0"


class SendToBoqRequest(BaseModel):
    boq_id: uuid.UUID
    #: Replace this position's quantity and rate; without it a new position is added.
    position_id: uuid.UUID | None = None


class SendToBoqResult(BaseModel):
    position_id: uuid.UUID
    boq_id: uuid.UUID
    ordinal: str
    description: str
    total: str
    mode: Literal["added", "replaced"]


class ValidationReportOut(BaseModel):
    status: str
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    findings: list[FindingOut] = Field(default_factory=list)


class ParcelListResponse(BaseModel):
    items: list[ParcelOut]
    total: int
    offset: int = 0
    limit: int = 50


class PartyListResponse(BaseModel):
    items: list[PartyOut]
    total: int
    offset: int = 0
    limit: int = 50


class RightListResponse(BaseModel):
    items: list[RightOut]
    total: int
    offset: int = 0
    limit: int = 50


class WorkZoneListResponse(BaseModel):
    items: list[WorkZoneOut]
    total: int
    offset: int = 0
    limit: int = 50


class WorkZoneIn(BaseModel):
    """A work zone drawn on the plan: a ring in the project grid."""

    name: str = Field(min_length=1, max_length=255)
    ring: list[tuple[float, float]] = Field(min_length=3, max_length=5000)


class TouchedParcel(BaseModel):
    parcel_id: uuid.UUID
    parcel_ref: str
    status: str
    overlap_m2: float
    #: PAR-003: the zone enters land the project does not hold yet.
    blocking: bool


class WorkZoneDetail(WorkZoneOut):
    ring: list[tuple[float, float]] = Field(default_factory=list)
    touched: list[TouchedParcel] = Field(default_factory=list)
    findings: list[FindingOut] = Field(default_factory=list)


class BoundaryPointRow(BaseModel):
    """One boundary point of the register, shared by every parcel that has it as a corner."""

    point_no: str
    e: float
    n: float
    mark: str = ""
    #: From the country mark list; None when no mark is recorded.
    monumented: bool | None = None
    accuracy_m: float | None = None
    corner_status: str = ""
    parcels: list[str] = Field(default_factory=list)
    #: The parcels record different marks for this point.
    mark_conflict: bool = False
    #: Largest distance between the copies of this point in different parcels, m.
    position_spread_m: float = 0.0


class BoundaryPointRegister(BaseModel):
    items: list[BoundaryPointRow]
    total: int
    monumented: int = 0
    unmarked: int = 0
    conflicts: int = 0


class DemoLoadResult(BaseModel):
    parcels: int
    work_zones: int
    skipped: bool = False
