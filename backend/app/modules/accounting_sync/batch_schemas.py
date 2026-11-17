# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schemas of export batches, imports, reconciliation and the extra mappings. Money is serialised as strings."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Money = Annotated[Decimal, PlainSerializer(lambda v: str(v), return_type=str)]
BatchFormat = Literal["csv", "xlsx", "datev", "journal"]
BatchStatus = Literal["draft", "exported", "confirmed", "voided"]


class BatchRequest(BaseModel):
    format: BatchFormat
    date_from: date
    date_to: date
    record_types: list[str] = Field(..., min_length=1, max_length=10)


class BatchFinding(BaseModel):
    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None
    record_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class BatchPreview(BaseModel):
    row_count: int
    by_type: dict[str, int]
    total_net: str
    total_tax: str
    total_gross: str
    errors: int
    warnings: int
    findings: list[BatchFinding]


class BatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    batch_no: int
    format: str
    period_from: date
    period_to: date
    record_types: list[str]
    row_count: int
    total_net: Money
    total_tax: Money
    total_gross: Money
    sha256: str
    status: BatchStatus
    file_name: str
    void_reason: str | None = None
    created_by: str | None = None
    created_at: datetime


class BatchListResponse(BaseModel):
    items: list[BatchResponse]
    total: int
    offset: int = 0
    limit: int = 50


class VoidRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=1000)


class CostCodeRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    platform_code: str = Field(..., min_length=1, max_length=60)
    standard: str = Field(default="project", max_length=40)
    external_cost_center: str = Field(default="", max_length=40)


class SupplierRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    contact_id: str = Field(..., min_length=1, max_length=80)
    external_account: str = Field(default="", max_length=40)


class ExtraMappingsResponse(BaseModel):
    cost_codes: list[CostCodeRow]
    suppliers: list[SupplierRow]


class ExtraMappingsUpdate(BaseModel):
    cost_codes: list[CostCodeRow] | None = None
    suppliers: list[SupplierRow] | None = None


class ImportSummary(BaseModel):
    import_id: str
    file_name: str
    lines: int
    skipped: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ImportRow(BaseModel):
    import_id: str
    file_name: str
    lines: int
    date_from: str | None = None
    date_to: str | None = None
    created_at: str | None = None


class ImportListResponse(BaseModel):
    items: list[ImportRow]
    total: int
    offset: int = 0
    limit: int = 50


class ReconciliationCounts(BaseModel):
    matched: int
    mismatches: int
    platform_only: int
    books_only: int


class ReconciliationResponse(BaseModel):
    counts: ReconciliationCounts
    matched: list[dict[str, Any]]
    mismatches: list[dict[str, Any]]
    platform_only: list[dict[str, Any]]
    books_only: list[dict[str, Any]]
