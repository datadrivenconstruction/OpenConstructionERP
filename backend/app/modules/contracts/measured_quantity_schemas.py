# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Response shapes of a measured quantity offered to a payment certificate (decimals travel as strings)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class MeasuredFinding(BaseModel):
    rule_id: str
    severity: str
    message: str
    key: str = ""
    params: dict[str, str] = Field(default_factory=dict)


class MeasuredContract(BaseModel):
    id: uuid.UUID
    code: str
    title: str = ""
    currency: str = ""


class MeasuredLine(BaseModel):
    id: uuid.UUID
    code: str = ""
    description: str = ""
    unit: str = ""
    quantity: Decimal
    unit_rate: Decimal
    total_value: Decimal


class MeasuredClaim(BaseModel):
    id: uuid.UUID
    number: str
    status: str
    currency: str = ""
    gross_amount: Decimal | None = None
    retention_amount: Decimal | None = None
    net_due: Decimal | None = None


class MeasuredFigures(BaseModel):
    percent_to_date: Decimal
    capped: bool
    period_qty: Decimal
    period_value: Decimal
    prior_value: Decimal
    cumulative_value: Decimal


class MeasuredPreview(BaseModel):
    """What the certificate line would carry (preview) or now carries (after confirm)."""

    boq_position_id: uuid.UUID
    ordinal: str
    description: str
    boq_quantity: Decimal
    boq_unit: str
    quantity: Decimal
    unit: str
    quantity_kind: str = ""
    source: dict[str, Any] = Field(default_factory=dict)
    contract: MeasuredContract | None = None
    line: MeasuredLine | None = None
    claim: MeasuredClaim | None = None
    figures: MeasuredFigures | None = None
    findings: list[MeasuredFinding] = Field(default_factory=list)
    can_commit: bool
    progress_entry_id: uuid.UUID | None = None
