# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schemas for editable estimate templates."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.boq.user_templates import money_text, to_decimal


def _clean_amount(value: object) -> str | None:
    """Blank reads as ``None``; anything else must be a finite number."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    parsed = to_decimal(value)
    if parsed is None:
        raise ValueError("must be a number")
    return money_text(parsed)


class TemplatePositionBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ordinal: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=5000)
    unit: str = Field(default="", max_length=20)
    quantity: str | None = None
    qty_factor: str | None = None
    rate: str | None = None
    classification: dict[str, str] = Field(default_factory=dict)

    @field_validator("quantity", "qty_factor", "rate", mode="before")
    @classmethod
    def _amount(cls, value: object) -> str | None:
        return _clean_amount(value)


class TemplateSectionBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ordinal: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=1000)
    classification: dict[str, str] = Field(default_factory=dict)
    positions: list[TemplatePositionBody] = Field(default_factory=list, max_length=5000)


class TemplateMarkupBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    markup_type: str = Field(default="percentage", max_length=50)
    category: str = Field(default="overhead", max_length=100)
    percentage: str = "0"
    fixed_amount: str = "0"
    apply_to: str = Field(default="direct_cost", max_length=50)

    @field_validator("percentage", "fixed_amount", mode="before")
    @classmethod
    def _amount(cls, value: object) -> str:
        # Out-of-band percentages are a warning from the template rules, not a refusal.
        parsed = to_decimal(value)
        return money_text(parsed if parsed is not None else 0) or "0"


class TemplateWrite(BaseModel):
    """Body of create and update; also the body checked by the validate endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=5000)
    icon: str = Field(default="FileText", max_length=50)
    classification_standard: str = Field(default="", max_length=50)
    sections: list[TemplateSectionBody] = Field(default_factory=list, max_length=500)
    markups: list[TemplateMarkupBody] = Field(default_factory=list, max_length=100)


class TemplateIssue(BaseModel):
    rule_id: str
    severity: Literal["warning"] = "warning"
    path: dict[str, int] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)


class TemplateDetail(BaseModel):
    id: str
    builtin: bool
    name: str
    description: str
    icon: str
    classification_standard: str
    origin: str
    copied_from: str | None = None
    sections: list[TemplateSectionBody]
    markups: list[TemplateMarkupBody]
    warnings: list[TemplateIssue] = Field(default_factory=list)


class TemplateFromBOQRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    boq_id: UUID
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    classification_standard: str = Field(default="", max_length=50)
    keep_quantities: bool = False
    keep_rates: bool = True
    include_markups: bool = False
    renumber: bool = True
