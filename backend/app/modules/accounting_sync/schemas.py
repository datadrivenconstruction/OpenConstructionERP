# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync request and response schemas. Money is serialised as strings."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Money = Annotated[Decimal | None, PlainSerializer(lambda v: None if v is None else str(v), return_type=str | None)]
Provider = Literal["xero", "qbo", "datev", "journal", "saft"]


class ConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    provider: Provider
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    chart_template: str | None = Field(default=None, max_length=40)
    base_currency: str = Field(default="EUR", min_length=3, max_length=3)
    is_sandbox: bool = True
    client_id: str | None = Field(default=None, max_length=255)
    client_secret: str | None = Field(default=None, max_length=500)
    external_tenant_id: str | None = Field(default=None, max_length=120)
    lock_date: date | None = None
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_sandbox: bool | None = None
    client_id: str | None = Field(default=None, max_length=255)
    client_secret: str | None = Field(default=None, max_length=500)
    external_tenant_id: str | None = Field(default=None, max_length=120)
    lock_date: date | None = None
    clear_lock_date: bool = False
    project_ids: list[uuid.UUID] | None = None
    settings: dict[str, Any] | None = None


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    provider: str
    country_code: str | None
    chart_template: str
    base_currency: str
    status: str
    is_sandbox: bool
    client_id: str | None
    has_client_secret: bool = False
    is_authorised: bool = False
    external_tenant_id: str | None
    lock_date: date | None
    project_ids: list[str]
    settings: dict[str, Any] = Field(default_factory=dict)
    last_sync_at: str | None
    last_sync_status: str | None
    created_at: datetime | None = None


class AccountMappingRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: str = Field(..., max_length=60)
    account_code: str = Field(default="", max_length=40)
    account_name: str = Field(default="", max_length=255)


class TaxMappingRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tax_code: str = Field(..., max_length=40)
    direction: Literal["sales", "purchase"]
    external_code: str = Field(default="", max_length=40)
    rate_pct: Money = None


class MappingsResponse(BaseModel):
    chart_template: str
    templates: list[dict[str, Any]]
    tax_codes: list[dict[str, Any]]
    accounts: list[AccountMappingRow]
    taxes: list[TaxMappingRow]


class MappingsUpdate(BaseModel):
    accounts: list[AccountMappingRow] = Field(default_factory=list)
    taxes: list[TaxMappingRow] = Field(default_factory=list)


class TemplateApply(BaseModel):
    chart_template: str = Field(..., max_length=40)


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None
    record_id: str | None = None


class LogEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    project_id: uuid.UUID | None
    action: str
    record_type: str
    record_id: str
    record_label: str
    status: str
    attempt: int
    error_reason: str | None
    external_id: str | None
    amount: Money = None
    resolved: bool
    created_at: datetime | None = None


class LogListResponse(BaseModel):
    items: list[LogEntryResponse]
    total: int


class SyncCounts(BaseModel):
    success: int = 0
    failed: int = 0
    skipped: int = 0


class PushRequest(BaseModel):
    project_id: uuid.UUID | None = None
    record_ids: list[str] | None = None


class OAuthStartResponse(BaseModel):
    authorization_url: str


class OAuthComplete(BaseModel):
    code: str = Field(..., min_length=1, max_length=2000)
    redirect_uri: str = Field(..., max_length=500)
    tenant_id: str | None = Field(default=None, max_length=120)


class PreviewDocument(BaseModel):
    record_id: str
    record_type: str
    source: str
    number: str
    doc_date: date
    counterparty: str
    project_code: str
    currency: str
    net_total: Money
    tax_total: Money
    gross_total: Money
    external_id: str | None = None
