# DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Response shapes of the cash-flow forecast. Money is a decimal string."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CashFlowScenario(BaseModel):
    receipt_delay_days: int = 0
    cost_overrun_pct: str = "0"


class CashFlowMonthOut(BaseModel):
    period: str
    is_past: bool
    planned_in: str
    planned_out: str
    actual_in: str
    actual_out: str
    expected_in: str
    expected_out: str
    net: str
    cumulative: str
    variance_in: str
    variance_out: str


class CashFlowTotals(BaseModel):
    planned_in: str
    planned_out: str
    actual_in: str
    actual_out: str
    expected_in: str
    expected_out: str


class CashFlowSourceOut(BaseModel):
    source: str
    direction: str
    amount: str


class PeakFunding(BaseModel):
    amount: str = Field(description="Cash needed to cover the lowest cumulative position (positive).")
    period: str


class CurrencyForecastOut(BaseModel):
    currency: str
    months: list[CashFlowMonthOut]
    totals: CashFlowTotals
    sources: list[CashFlowSourceOut]
    closing_position: str
    peak_funding: PeakFunding | None = None


class CashFlowFinding(BaseModel):
    rule_id: str
    severity: str
    message: str
    suggestion: str = ""
    element_ref: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class ProjectCashFlowForecast(BaseModel):
    project_id: str
    project_name: str
    as_of: str
    scenario: CashFlowScenario
    threshold: str
    has_inputs: bool
    currencies: list[CurrencyForecastOut]
    findings: list[CashFlowFinding]


class PortfolioProjectRow(BaseModel):
    project_id: str
    project_name: str
    closing_position: str
    peak_funding: PeakFunding | None = None
    negative: bool


class PortfolioCurrencyOut(BaseModel):
    currency: str
    months: list[CashFlowMonthOut]
    closing_position: str
    peak_funding: PeakFunding | None = None
    projects: list[PortfolioProjectRow]


class ProjectRef(BaseModel):
    project_id: str
    project_name: str


class PortfolioCashFlowForecast(BaseModel):
    as_of: str
    scenario: CashFlowScenario
    currencies: list[PortfolioCurrencyOut]
    projects_without_forecast: list[ProjectRef]
    findings_count: int


class CashFlowEvaluation(BaseModel):
    findings: list[CashFlowFinding]
    published: int
