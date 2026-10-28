# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Management of Change (MoC) Pydantic schemas."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _dec_str(v: Any) -> str | None:
    """Coerce money input to a canonical decimal string."""
    if v is None:
        return None
    return str(Decimal(str(v)))


class MoCImpactCreate(BaseModel):
    impact_area: str = Field(default="cost", max_length=40)
    description: str = Field(default="")
    severity: str = Field(default="medium", max_length=20)
    cost_impact: str = Field(default="0")
    schedule_delta_days: int = Field(default=0)
    currency: str = Field(default="", max_length=10)
    mitigation: str = Field(default="")

    @field_validator("cost_impact", mode="before")
    @classmethod
    def _coerce_cost(cls, v: Any) -> str:
        return str(Decimal(str(v))) if v is not None else "0"


class MoCImpactUpdate(BaseModel):
    impact_area: str | None = Field(default=None, max_length=40)
    description: str | None = None
    severity: str | None = Field(default=None, max_length=20)
    cost_impact: str | None = None
    schedule_delta_days: int | None = None
    currency: str | None = Field(default=None, max_length=10)
    mitigation: str | None = None

    @field_validator("cost_impact", mode="before")
    @classmethod
    def _coerce_cost(cls, v: Any) -> str | None:
        if v is None:
            return None
        return str(Decimal(str(v)))


class MoCImpactResponse(BaseModel):
    id: uuid.UUID
    moc_entry_id: uuid.UUID
    impact_area: str
    description: str
    severity: str
    cost_impact: str
    schedule_delta_days: int
    currency: str
    mitigation: str

    model_config = {"from_attributes": True}

    @field_validator("cost_impact", mode="before")
    @classmethod
    def _coerce_cost(cls, v: Any) -> str:
        return str(Decimal(str(v))) if v is not None else "0"


class MoCEntryCreate(BaseModel):
    project_id: uuid.UUID
    title: str = Field(default="", max_length=500)
    description: str = Field(default="")
    change_category: str = Field(default="engineering", max_length=40)
    risk_level: str = Field(default="medium", max_length=20)
    cost_impact: str = Field(default="0")
    schedule_delta_days: int = Field(default=0)
    currency: str = Field(default="", max_length=10)
    variation_request_id: uuid.UUID | None = None
    variation_order_id: uuid.UUID | None = None
    change_order_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("cost_impact", mode="before")
    @classmethod
    def _coerce_cost(cls, v: Any) -> str:
        return str(Decimal(str(v))) if v is not None else "0"


class MoCEntryUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    change_category: str | None = Field(default=None, max_length=40)
    risk_level: str | None = Field(default=None, max_length=20)
    cost_impact: str | None = None
    schedule_delta_days: int | None = None
    currency: str | None = Field(default=None, max_length=10)
    review_notes: str | None = None
    decision_notes: str | None = None
    variation_request_id: uuid.UUID | None = None
    variation_order_id: uuid.UUID | None = None
    change_order_id: uuid.UUID | None = None
    ball_in_court: str | None = None
    response_due_date: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("cost_impact", mode="before")
    @classmethod
    def _coerce_cost(cls, v: Any) -> str | None:
        if v is None:
            return None
        return str(Decimal(str(v)))


class MoCEntryResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    title: str
    description: str
    change_category: str
    risk_level: str
    proposed_by: str | None
    proposed_at: str | None
    reviewed_by: str | None
    reviewed_at: str | None
    review_notes: str
    decided_by: str | None
    decided_at: str | None
    decision_notes: str
    implemented_by: str | None
    implemented_at: str | None
    cost_impact: str
    schedule_delta_days: int
    currency: str
    status: str
    variation_request_id: uuid.UUID | None
    variation_order_id: uuid.UUID | None
    change_order_id: uuid.UUID | None
    ball_in_court: str | None = None
    response_due_date: str | None = None
    # The ORM stores this under the ``metadata_`` attribute (``metadata`` is
    # reserved by SQLAlchemy declarative for the MetaData registry). Read from
    # the real attribute via validation_alias, mirroring NCR/procurement, so the
    # stored data actually reaches the client instead of silently coercing the
    # inherited MetaData object to {}.
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    impacts: list[MoCImpactResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @field_validator("cost_impact", mode="before")
    @classmethod
    def _coerce_cost(cls, v: Any) -> str:
        return str(Decimal(str(v))) if v is not None else "0"

    @field_validator("metadata", mode="before")
    @classmethod
    def _coerce_meta(cls, v: Any) -> dict[str, Any]:
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        return {}
