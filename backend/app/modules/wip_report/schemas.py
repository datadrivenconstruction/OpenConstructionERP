# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report API schemas. Money and percentages travel as decimal strings, never floats."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Money = Annotated[Decimal, PlainSerializer(lambda v: str(v) if v is not None else None, return_type=str)]
MoneyOpt = Annotated[
    Decimal | None, PlainSerializer(lambda v: str(v) if v is not None else None, return_type=str | None)
]

_PERIOD = r"^\d{4}-(0[1-9]|1[0-2])$"


class _Figures(BaseModel):
    currency: str = ""
    original_contract_value: Money = Decimal("0")
    approved_changes: Money = Decimal("0")
    contract_value: Money = Decimal("0")
    estimated_cost: Money = Decimal("0")
    cost_to_date: Money = Decimal("0")
    percent_complete: Money = Decimal("0")
    earned_revenue: Money = Decimal("0")
    billed_to_date: Money = Decimal("0")
    over_billing: Money = Decimal("0")
    under_billing: Money = Decimal("0")
    projected_gross_profit: Money = Decimal("0")
    previous_gross_profit: MoneyOpt = None
    fade: MoneyOpt = None
    backlog: Money = Decimal("0")
    loss_job: bool = False
    flags: list[str] = Field(default_factory=list)


class WipRow(_Figures):
    """The live WIP row of one project."""

    project_id: UUID
    project_name: str = ""
    as_of: date
    previous_period: str | None = None
    cost_to_complete: Money = Decimal("0")
    percent_complete_raw: Money = Decimal("0")
    projected_margin_pct: Money = Decimal("0")
    gross_profit_to_date: Money = Decimal("0")
    forecast_note: str | None = None
    sources: dict[str, Any] = Field(default_factory=dict)


class WipTotals(BaseModel):
    """Portfolio totals in one currency."""

    currency: str
    projects: int
    contract_value: Money
    estimated_cost: Money
    cost_to_date: Money
    cost_to_complete: Money
    earned_revenue: Money
    billed_to_date: Money
    over_billing: Money
    under_billing: Money
    projected_gross_profit: Money
    fade: Money
    backlog: Money
    percent_complete: Money


class PortfolioResponse(BaseModel):
    as_of: date
    rows: list[WipRow]
    totals: list[WipTotals]


class WipPeriodResponse(_Figures):
    """A closed month-end snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    period: str
    as_of: date
    notes: str | None = None
    closed_by: str | None = None
    created_at: datetime | None = None


class WipPeriodListResponse(BaseModel):
    items: list[WipPeriodResponse]
    total: int
    offset: int = 0
    limit: int = 50


class ClosePeriodRequest(BaseModel):
    period: str = Field(pattern=_PERIOD)
    notes: str | None = Field(default=None, max_length=2000)


class ForecastRequest(BaseModel):
    """``estimated_cost`` null clears the override and falls back to the cost report forecast."""

    estimated_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    note: str | None = Field(default=None, max_length=2000)


class ForecastResponse(BaseModel):
    estimated_cost: MoneyOpt = None
    note: str | None = None


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    details: dict[str, str] = Field(default_factory=dict)


class FindingsResponse(BaseModel):
    findings: list[Finding]
