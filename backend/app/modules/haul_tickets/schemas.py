# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ tickets request and response schemas. Decimals travel as strings."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.decimal_types import (
    Decimal8_2,
    Decimal8_3,
    Decimal10_2,
    Decimal12_3,
    Decimal14_3,
    Decimal18_2,
    Decimal18_4,
)

HaulType = Literal["earthworks", "aggregates", "concrete", "asphalt", "waste", "other"]
LocationKind = Literal["quarry", "plant", "site", "dump", "other"]
Unit = Literal["t", "m3", "load"]
RateBasis = Literal["t", "m3", "load", "hour"]
Status = Literal["issued", "loaded", "delivered", "verified", "invoiced", "rejected"]


class _DecimalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _ser(self, v: Any) -> Any:
        return str(v) if isinstance(v, Decimal) else v


class TicketFields(BaseModel):
    ticket_number: str = Field(default="", max_length=60)
    haul_type: HaulType = "other"
    direction: Literal["inbound", "outbound", "internal"] = "inbound"
    ticket_date: date | None = None
    time_out: datetime | None = None
    time_in: datetime | None = None
    origin: str = Field(default="", max_length=255)
    origin_kind: LocationKind = "other"
    destination: str = Field(default="", max_length=255)
    destination_kind: LocationKind = "site"
    material_code: str = Field(default="", max_length=60)
    material_name: str = Field(default="", max_length=255)
    unit: Unit = "t"
    gross_t: Decimal12_3 | None = Field(default=None, ge=0)
    tare_t: Decimal12_3 | None = Field(default=None, ge=0)
    net_t: Decimal12_3 | None = None
    volume_m3: Decimal12_3 | None = Field(default=None, ge=0)
    loads: int = Field(default=1, ge=0, le=1000)
    truck_source: Literal["own", "hired"] = "hired"
    equipment_id: uuid.UUID | None = None
    haulier_name: str = Field(default="", max_length=255)
    haulier_party_id: uuid.UUID | None = None
    plate: str = Field(default="", max_length=30)
    driver_name: str = Field(default="", max_length=255)
    vehicle_max_gross_t: Decimal10_2 | None = Field(default=None, ge=0)
    vehicle_capacity: Decimal10_2 | None = Field(default=None, ge=0)
    po_id: uuid.UUID | None = None
    rate_basis: RateBasis = "t"
    rate: Decimal18_4 | None = Field(default=None, ge=0)
    hours: Decimal8_2 | None = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=10)
    boq_position_id: uuid.UUID | None = None
    cost_code: str = Field(default="", max_length=100)
    receiver_name: str = Field(default="", max_length=255)
    signature: str | None = Field(default=None, max_length=400_000)
    waste_code: str = Field(default="", max_length=40)
    waste_catalogue: str = Field(default="", max_length=40)
    hazardous: bool = False
    receiving_facility: str = Field(default="", max_length=255)
    facility_permit_ref: str = Field(default="", max_length=120)
    transport_id: uuid.UUID | None = None
    delivery_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=4000)


class TicketCreate(TicketFields):
    project_id: uuid.UUID
    client_op_id: str | None = Field(default=None, max_length=80)
    source: Literal["manual", "field", "import"] = "manual"


class TicketUpdate(BaseModel):
    """Partial update: only the fields sent are changed."""

    model_config = ConfigDict(extra="ignore")

    ticket_number: str | None = Field(default=None, max_length=60)
    haul_type: HaulType | None = None
    direction: Literal["inbound", "outbound", "internal"] | None = None
    ticket_date: date | None = None
    time_out: datetime | None = None
    time_in: datetime | None = None
    origin: str | None = Field(default=None, max_length=255)
    origin_kind: LocationKind | None = None
    destination: str | None = Field(default=None, max_length=255)
    destination_kind: LocationKind | None = None
    material_code: str | None = Field(default=None, max_length=60)
    material_name: str | None = Field(default=None, max_length=255)
    unit: Unit | None = None
    gross_t: Decimal12_3 | None = Field(default=None, ge=0)
    tare_t: Decimal12_3 | None = Field(default=None, ge=0)
    net_t: Decimal12_3 | None = None
    volume_m3: Decimal12_3 | None = Field(default=None, ge=0)
    loads: int | None = Field(default=None, ge=0, le=1000)
    truck_source: Literal["own", "hired"] | None = None
    equipment_id: uuid.UUID | None = None
    haulier_name: str | None = Field(default=None, max_length=255)
    haulier_party_id: uuid.UUID | None = None
    plate: str | None = Field(default=None, max_length=30)
    driver_name: str | None = Field(default=None, max_length=255)
    vehicle_max_gross_t: Decimal10_2 | None = Field(default=None, ge=0)
    vehicle_capacity: Decimal10_2 | None = Field(default=None, ge=0)
    po_id: uuid.UUID | None = None
    rate_basis: RateBasis | None = None
    rate: Decimal18_4 | None = Field(default=None, ge=0)
    hours: Decimal8_2 | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    boq_position_id: uuid.UUID | None = None
    cost_code: str | None = Field(default=None, max_length=100)
    receiver_name: str | None = Field(default=None, max_length=255)
    signature: str | None = Field(default=None, max_length=400_000)
    waste_code: str | None = Field(default=None, max_length=40)
    waste_catalogue: str | None = Field(default=None, max_length=40)
    hazardous: bool | None = None
    receiving_facility: str | None = Field(default=None, max_length=255)
    facility_permit_ref: str | None = Field(default=None, max_length=120)
    transport_id: uuid.UUID | None = None
    delivery_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)


class TransitionRequest(BaseModel):
    status: Status
    reason: str = Field(default="", max_length=2000)
    receiver_name: str | None = Field(default=None, max_length=255)
    signature: str | None = Field(default=None, max_length=400_000)
    accept_warnings: bool = True


class FindingOut(BaseModel):
    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None


class TicketOut(_DecimalOut):
    id: uuid.UUID
    project_id: uuid.UUID
    ticket_number: str
    haul_type: str
    direction: str
    ticket_date: date
    time_out: datetime | None
    time_in: datetime | None
    origin: str
    origin_kind: str
    destination: str
    destination_kind: str
    material_code: str
    material_name: str
    unit: str
    gross_t: Decimal | None
    tare_t: Decimal | None
    net_t: Decimal | None
    volume_m3: Decimal | None
    loads: int
    quantity: Decimal
    truck_source: str
    equipment_id: uuid.UUID | None
    haulier_name: str
    haulier_party_id: uuid.UUID | None
    plate: str
    driver_name: str
    vehicle_max_gross_t: Decimal | None
    vehicle_capacity: Decimal | None
    po_id: uuid.UUID | None
    rate_basis: str
    rate: Decimal | None
    hours: Decimal | None
    currency: str
    amount: Decimal
    boq_position_id: uuid.UUID | None
    cost_code: str
    status: str
    reject_reason: str
    receiver_name: str
    has_signature: bool = False
    signed_at: datetime | None
    photos: list[dict[str, Any]] = []
    waste_code: str
    waste_catalogue: str
    hazardous: bool
    receiving_facility: str
    facility_permit_ref: str
    transport_id: uuid.UUID | None
    delivery_id: uuid.UUID | None
    invoice_id: uuid.UUID | None
    qr_token: str
    source: str
    notes: str
    created_at: datetime
    findings: list[FindingOut] = []


class TicketListResponse(BaseModel):
    items: list[TicketOut]
    total: int
    offset: int
    limit: int


class SettingsIn(BaseModel):
    mandatory_fields: list[str] = Field(default_factory=list, max_length=30)
    max_gross_t: Decimal10_2 | None = Field(default=None, ge=0)
    capacity_tolerance_pct: int = Field(default=10, ge=0, le=100)
    price_tolerance_pct: int = Field(default=1, ge=0, le=50)
    waste_catalogue: str = Field(default="", max_length=40)
    currency: str = Field(default="", max_length=10)


class SettingsOut(_DecimalOut, SettingsIn):
    candidates: list[str] = []
    waste_catalogues: list[dict[str, str]] = []


class RateIn(BaseModel):
    haulier_name: str = Field(max_length=255)
    material_code: str = Field(default="", max_length=60)
    rate_basis: RateBasis = "t"
    rate: Decimal18_4 = Field(ge=0)
    currency: str = Field(default="", max_length=10)
    po_id: uuid.UUID | None = None


class RateOut(_DecimalOut, RateIn):
    id: uuid.UUID


class RateListResponse(BaseModel):
    items: list[RateOut]
    total: int
    offset: int = 0
    limit: int = 200


class MaterialIn(BaseModel):
    code: str = Field(min_length=1, max_length=60)
    name: str = Field(default="", max_length=255)
    unit: Unit = "t"
    haul_type: HaulType = "other"
    density_t_m3: Decimal8_3 | None = Field(default=None, gt=0)
    waste_code: str = Field(default="", max_length=40)


class MaterialOut(_DecimalOut, MaterialIn):
    id: uuid.UUID | None = None
    builtin: bool = False


class MaterialListResponse(BaseModel):
    items: list[MaterialOut]
    total: int
    offset: int = 0
    limit: int = 200


class InvoiceLineIn(BaseModel):
    ticket_number: str = Field(default="", max_length=60)
    quantity: Decimal14_3 | None = None
    rate: Decimal18_4 | None = None
    amount: Decimal18_2 | None = None
    description: str = Field(default="", max_length=255)


class InvoiceIn(BaseModel):
    project_id: uuid.UUID
    haulier_name: str = Field(max_length=255)
    invoice_number: str = Field(max_length=60)
    invoice_date: date | None = None
    period_from: date | None = None
    period_to: date | None = None
    currency: str = Field(default="", max_length=10)
    lines: list[InvoiceLineIn] = Field(default_factory=list, max_length=5000)


class InvoiceOut(_DecimalOut):
    id: uuid.UUID
    project_id: uuid.UUID
    haulier_name: str
    invoice_number: str
    invoice_date: date | None
    period_from: date | None
    period_to: date | None
    currency: str
    total: Decimal
    lines: list[dict[str, Any]]
    status: str
    result: dict[str, Any]
    findings: list[FindingOut] = []


class InvoiceListResponse(BaseModel):
    items: list[InvoiceOut]
    total: int
    offset: int = 0
    limit: int = 100


class ImportPreviewOut(BaseModel):
    headers: list[str]
    mapping: dict[str, int]
    target_fields: list[str]
    rows: list[dict[str, Any]]
    total: int
    duplicates: int


class ImportCommitOut(BaseModel):
    created: int
    skipped_duplicates: int
    ticket_ids: list[uuid.UUID]


class SummaryRow(_DecimalOut):
    key: str
    label: str
    loads: int
    tonnes: Decimal
    volume_m3: Decimal
    amount: Decimal
    tickets: int


class SummaryOut(BaseModel):
    group_by: str
    rows: list[SummaryRow]
    totals: SummaryRow


class ExpectedDeliveryOut(BaseModel):
    delivery_id: uuid.UUID
    supplier_name: str
    window_start: datetime
    window_end: datetime
    vehicle_type: str | None
    materials_desc: str | None
    po_ref: str | None
    direction: str
    gross_weight_t: str | None
    transport_id: uuid.UUID | None
    ticketed: bool


class ExpectedDeliveryListResponse(BaseModel):
    items: list[ExpectedDeliveryOut]
    total: int
    offset: int = 0
    limit: int = 200
