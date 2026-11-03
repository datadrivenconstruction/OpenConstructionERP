# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Budget ledger request and response shapes. Money goes out as decimal strings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.costmodel.cost_control_schemas import Money


class LegIn(BaseModel):
    cost_line_id: UUID
    amount: Decimal = Field(description="Negative takes budget off the line, positive adds it")


class TransferIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    legs: list[LegIn] = Field(min_length=2, max_length=50)


class ModificationIn(BaseModel):
    cost_line_id: UUID
    amount: Decimal
    reason: str = Field(min_length=1, max_length=2000)
    approval_ref: str = Field(default="", max_length=200, description="Owner's approval: letter, minute or order no.")


class DecisionIn(BaseModel):
    note: str = Field(default="", max_length=2000)


class LegOut(BaseModel):
    cost_line_id: UUID
    code: str = ""
    amount: Money


class TransferOut(BaseModel):
    id: UUID
    code: str
    status: str
    reason: str
    legs: list[LegOut]
    moved: Money
    requested_by: str | None = None
    submitted_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_note: str = ""
    created_at: datetime | None = None


class ModificationOut(BaseModel):
    id: UUID
    code: str
    status: str
    cost_line_id: UUID
    line_code: str = ""
    amount: Money
    reason: str
    approval_ref: str = ""
    requested_by: str | None = None
    submitted_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_note: str = ""
    created_at: datetime | None = None


class AuditOut(BaseModel):
    entity_kind: str
    entity_id: UUID
    action: str
    from_status: str = ""
    to_status: str = ""
    actor: str | None = None
    note: str = ""
    created_at: datetime | None = None


class LineEffect(BaseModel):
    """What approved entries did to one cost line's budget."""

    cost_line_id: UUID
    code: str = ""
    original: Money
    transfers: Money
    modifications: Money
    revised: Money
    committed: Money


class BudgetLedger(BaseModel):
    project_id: UUID
    currency: str
    transfers: list[TransferOut]
    modifications: list[ModificationOut]
    lines: list[LineEffect]
    pending_transfers: int = 0
    pending_modifications: int = 0
    audit: list[AuditOut] = Field(default_factory=list)
