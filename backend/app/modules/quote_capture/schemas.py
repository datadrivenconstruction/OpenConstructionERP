# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ capture API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class QuoteTextCreate(BaseModel):
    """A quote pasted as text (an email body, for example)."""

    project_id: uuid.UUID
    package_id: uuid.UUID | None = None
    text: str = Field(..., min_length=1, max_length=200_000)
    filename: str = Field(default="email.txt", max_length=255)
    locale: str | None = Field(default=None, max_length=10)


class HeaderFieldUpdate(BaseModel):
    value: str | None = Field(default=None, max_length=500)


class QuoteUpdate(BaseModel):
    """Reviewer edits to the header, the package link and the conditions."""

    package_id: uuid.UUID | None = None
    header: dict[str, HeaderFieldUpdate] = Field(default_factory=dict)
    acknowledge_notes: list[str] = Field(default_factory=list)
    status: Literal["draft", "in_review", "rejected"] | None = None


class LineUpdate(BaseModel):
    """Reviewer edit of one line: values, the matched position, the reviewed tick."""

    description: str | None = Field(default=None, max_length=1000)
    quantity: str | None = Field(default=None, max_length=50)
    unit: str | None = Field(default=None, max_length=20)
    unit_rate: str | None = Field(default=None, max_length=50)
    total: str | None = Field(default=None, max_length=50)
    position_id: str | None = Field(default=None, max_length=36)
    clear_match: bool = False
    reviewed: bool | None = None
    ignored: bool | None = None


class ConfirmRequest(BaseModel):
    target: Literal["bid", "price_list", "po_draft"]
    accept_warnings: bool = False


class FindingOut(BaseModel):
    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None


class QuoteSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    package_id: uuid.UUID | None
    supplier_name: str
    status: str
    source_kind: str
    original_filename: str
    extraction_engine: str
    currency: str
    quote_total: str
    created_at: datetime
    line_count: int = 0
    open_findings: int = 0


class QuoteOut(QuoteSummaryOut):
    boq_id: uuid.UUID | None
    locale: str
    page_count: int
    has_file: bool = False
    header: dict[str, Any]
    lines: list[dict[str, Any]]
    notes: list[dict[str, Any]]
    document: dict[str, Any]
    confirmation: dict[str, Any]
    tax: dict[str, Any] = Field(default_factory=dict)
    findings: list[FindingOut] = Field(default_factory=list)


class ConfirmOut(BaseModel):
    quote_id: uuid.UUID
    target: str
    target_id: str
    audit: list[dict[str, Any]]


class LevellingOut(BaseModel):
    package_id: uuid.UUID
    currency: str
    rows: list[dict[str, Any]]
    quotes: list[dict[str, Any]]
    excluded_off_currency: list[str] = Field(default_factory=list)
