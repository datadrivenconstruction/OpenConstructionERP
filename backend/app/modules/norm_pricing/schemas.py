# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response schemas of the norm pricing module.

Money and coefficients travel as decimal strings, never floats.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class EstimatePricingSettings(BaseModel):
    """What a project records for norm-based pricing. Every field is optional."""

    model_config = ConfigDict(extra="forbid")

    estimate_wage: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    monthly_hours: Decimal | None = Field(default=None, gt=0, le=744, max_digits=6, decimal_places=2)
    funding_class: str | None = Field(default=None, max_length=64)
    estimate_role: Literal["investor", "contractor"] | None = None
    labour_location: str | None = Field(default=None, max_length=64)

    @field_serializer("estimate_wage", "monthly_hours")
    def _dec(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class LabeledOption(BaseModel):
    key: str
    label: str
    source: str = ""
    factor: str | None = None


class MarkupCapOut(BaseModel):
    key: str
    label: str
    cap_percent: str


class FundingClassOut(LabeledOption):
    markup_caps: list[MarkupCapOut] = []
    investor_estimate_at_cap: bool = False
    min_quotes: int | None = None


class NormTypeOut(BaseModel):
    prefix: str
    title: str | None = None
    collections: int | None = None


class NormBaseOut(BaseModel):
    key: str
    name: str
    classification_key: str
    code_example: str
    types: list[NormTypeOut]
    legacy_prefixes: dict[str, str]


class PricingProfile(BaseModel):
    """What the project's country pack offers, and what the project chose.

    ``available`` is false when no pack covering the project's country carries
    norm data; the client then shows nothing.
    """

    available: bool
    pack_slug: str | None = None
    currency: str | None = None
    norm_bases: list[NormBaseOut] = []
    funding_classes: list[FundingClassOut] = []
    location_factors: list[LabeledOption] = []
    grades: list[str] = []
    base_grade: str | None = None
    grading_status: str | None = None
    default_monthly_hours: str | None = None
    settings: EstimatePricingSettings = Field(default_factory=EstimatePricingSettings)


class RateOut(BaseModel):
    grade: str
    base_grade: str
    base_rate: str
    grade_one_rate: str
    base_coefficient: str
    coefficient: str
    rate: str
    location_factor: str
    rate_with_location: str


class LabourRatesOut(BaseModel):
    """Hourly rates per grade with the figures each was derived from."""

    estimate_wage: str
    monthly_hours: str
    rates: list[RateOut]
    missing_grades: list[str] = []


class CodeCheckIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class CodeCheckOut(BaseModel):
    status: Literal["ok", "legacy", "shape", "no_base"]
    code: str
    suggested: str | None = None
    old_prefix: str | None = None
    new_prefix: str | None = None
