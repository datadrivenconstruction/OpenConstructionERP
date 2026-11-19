# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Central purchasing request and response schemas. Money and quantities travel as decimal strings."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Dec = Annotated[Decimal, PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json")]

_KIND = "^(subcontract|supply)$"
_MODE = "^(per_project_contracts|framework_call_off)$"


class BundleCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    kind: str = Field(default="subcontract", pattern=_KIND)
    mode: str = Field(default="per_project_contracts", pattern=_MODE)
    currency: str = Field(default="", max_length=3)
    cost_code_standard: str | None = Field(default=None, max_length=40)
    budget_tolerance_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class BundleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    kind: str | None = Field(default=None, pattern=_KIND)
    mode: str | None = Field(default=None, pattern=_MODE)
    currency: str | None = Field(default=None, max_length=3)
    cost_code_standard: str | None = Field(default=None, max_length=40)
    budget_tolerance_pct: Decimal | None = Field(default=None, ge=0, le=100)
    vendor_name: str | None = Field(default=None, max_length=255)
    subcontractor_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    discount_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    lump_sum: Decimal | None = Field(default=None, ge=0)
    clear_discount: bool = False
    clear_lump_sum: bool = False


class ProjectAdd(BaseModel):
    project_id: uuid.UUID
    budget_amount: Decimal | None = Field(default=None, ge=0)


class ProjectUpdate(BaseModel):
    budget_amount: Decimal | None = Field(default=None, ge=0)
    clear_budget: bool = False


class ShareIn(BaseModel):
    bundle_project_id: uuid.UUID
    #: ``None`` leaves the share blank (the rule flags it); ``0`` means none of this line.
    quantity: Decimal | None = Field(default=None, ge=0)
    cost_line_id: uuid.UUID | None = None


class LineIn(BaseModel):
    code: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=5000)
    unit: str = Field(default="", max_length=20)
    quantity: Decimal = Field(..., ge=0)
    unit_rate: Decimal | None = Field(default=None, ge=0)
    cost_code: str | None = Field(default=None, max_length=40)
    shares: list[ShareIn] | None = None


class LineUpdate(BaseModel):
    code: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=5000)
    unit: str | None = Field(default=None, max_length=20)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit_rate: Decimal | None = Field(default=None, ge=0)
    clear_rate: bool = False
    cost_code: str | None = Field(default=None, max_length=40)
    shares: list[ShareIn] | None = None


class PreviewRequest(BaseModel):
    """Terms not saved yet: the split is recomputed as the buyer types."""

    discount_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    lump_sum: Decimal | None = Field(default=None, ge=0)
    rates: dict[uuid.UUID, Decimal] = Field(default_factory=dict)


class AwardRequest(BaseModel):
    vendor_name: str = Field(..., min_length=1, max_length=255)
    subcontractor_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    discount_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    lump_sum: Decimal | None = Field(default=None, ge=0)


class CallOffLineIn(BaseModel):
    line_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0)


class CallOffRequest(BaseModel):
    project_id: uuid.UUID
    lines: list[CallOffLineIn] = Field(..., min_length=1, max_length=500)


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    suggestion: str | None = None
    element_ref: str | None = None


class DocumentRef(BaseModel):
    type: str
    id: uuid.UUID | None = None
    code: str = ""
    status: str = ""
    project_id: uuid.UUID | None = None


class ShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bundle_project_id: uuid.UUID
    quantity: Dec | None = None
    cost_line_id: uuid.UUID | None = None
    cost_line_code: str | None = None


class LineOut(BaseModel):
    id: uuid.UUID
    order_index: int
    code: str
    description: str
    unit: str
    quantity: Dec
    unit_rate: Dec | None = None
    cost_code: str | None = None
    shares: list[ShareOut] = Field(default_factory=list)
    share_sum: Dec


class ProjectOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    project_code: str | None = None
    legal_entity_id: uuid.UUID | None = None
    legal_entity_name: str | None = None
    budget_amount: Dec | None = None
    budget_from_lines: Dec | None = None


class SplitRow(BaseModel):
    bundle_project_id: uuid.UUID
    project_name: str
    legal_entity_name: str | None = None
    gross: Dec
    discount: Dec
    net: Dec
    budget: Dec | None = None
    over_budget: bool = False
    budget_delta: Dec | None = None
    document: DocumentRef | None = None


class SplitOut(BaseModel):
    method: str
    gross: Dec
    net: Dec
    target: Dec
    reconciles: bool
    rows: list[SplitRow]
    cells: dict[str, dict[str, Dec]] = Field(default_factory=dict)


class BundleSummary(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    kind: str
    mode: str
    status: str
    currency: str
    vendor_name: str
    project_count: int
    line_count: int
    gross: Dec
    net: Dec
    errors: int
    warnings: int
    updated_at: Any = None


class BundleDetail(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    description: str
    kind: str
    mode: str
    status: str
    currency: str
    cost_code_standard: str | None = None
    budget_tolerance_pct: Dec
    vendor_name: str
    subcontractor_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    discount_pct: Dec | None = None
    lump_sum: Dec | None = None
    awarded_at: str | None = None
    projects: list[ProjectOut]
    lines: list[LineOut]
    split: SplitOut
    findings: list[Finding]
    agreements: list[DocumentRef] = Field(default_factory=list)


class CallOffResult(BaseModel):
    document: DocumentRef
    total: Dec
    findings: list[Finding]


class MyShareLine(BaseModel):
    code: str
    description: str
    unit: str
    quantity: Dec | None = None
    rate: Dec | None = None
    net: Dec | None = None
    called_off: Dec | None = None


class MyShare(BaseModel):
    bundle_id: uuid.UUID
    code: str
    title: str
    status: str
    kind: str
    mode: str
    currency: str
    vendor_name: str
    budget: Dec | None = None
    gross: Dec
    net: Dec
    over_budget: bool = False
    lines: list[MyShareLine]
    document: DocumentRef | None = None


class CostLineOption(BaseModel):
    id: uuid.UUID
    code: str
    description: str


class Catalogue(BaseModel):
    standard: str | None = None
    label: str | None = None
    countries: list[str] = Field(default_factory=list)
    codes: list[dict[str, str]] = Field(default_factory=list)
