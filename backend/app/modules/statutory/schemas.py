# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory checks transport schemas. Money and percentages travel as strings."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RetentionFacts(BaseModel):
    """Retention held on one payment."""

    payment_amount: str | None = Field(default=None, description="Gross amount of the payment, decimal string.")
    retention_amount: str | None = Field(default=None, description="Money held back, decimal string.")
    retention_pct: str | None = Field(default=None, description="Percent held, when no amount is known.")


class TaxLineIn(BaseModel):
    """One priced line for the tax treatment engine."""

    id: str
    kind: str = Field(default="unclassified", description="material | fixture | labor | equipment | other")
    cost: str = "0"
    price: str | None = None
    quantity: str | None = None
    description: str = ""
    priced_tax: str | None = None
    priced_surtax: str | None = None


class TaxFacts(BaseModel):
    """The bid's tax position."""

    contract_form: str | None = None
    rate_pct: str | None = Field(default=None, description="Jobsite address rate for the period, percent.")
    surtax_pct: str | None = None
    exemption_certificate_on_file: bool = False
    lines: list[TaxLineIn] = Field(default_factory=list, max_length=2000)


class NoticeFacts(BaseModel):
    """Events that start statutory clocks."""

    role: str | None = Field(default=None, description="direct_contractor | subcontractor | supplier")
    events: dict[str, date] = Field(default_factory=dict)
    work_months: list[str] = Field(default_factory=list, max_length=120, description="YYYY-MM")
    today: date | None = None

    @field_validator("work_months")
    @classmethod
    def _months(cls, value: list[str]) -> list[str]:
        for month in value:
            year, _, mm = month.partition("-")
            if not (year.isdigit() and mm.isdigit() and 1 <= int(mm) <= 12):
                raise ValueError(f"work month {month!r} is not YYYY-MM")
        return value


class WageFacts(BaseModel):
    """Wage schedules on file for the project."""

    public_work: bool = False
    determination_authorities: list[str] = Field(default_factory=list)


class StatutoryFacts(BaseModel):
    """Everything the statutory checks read for one project."""

    jurisdiction: str = Field(min_length=2, max_length=10)
    sector: Literal["public", "private"] | None = None
    project_type: str | None = None
    agreement_date: date | None = None
    contract_value: str | None = None
    retention: RetentionFacts | None = None
    tax: TaxFacts | None = None
    notices: NoticeFacts | None = None
    wage: WageFacts | None = None
    contract_clauses: list[str] = Field(default_factory=list)


class StatutoryOutcome(BaseModel):
    """What the engines computed and what the checks found."""

    jurisdiction: str
    name: str
    notices: list[dict[str, Any]] = Field(default_factory=list)
    retention: dict[str, Any] | None = None
    tax: dict[str, Any] | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)
    verify_note: str = ""


class JurisdictionSummary(BaseModel):
    """What the UI needs to build the forms for one jurisdiction."""

    code: str
    name: str
    country: str
    verify_note: str = ""
    sectors: list[str] = Field(default_factory=list)
    claimant_roles: list[str] = Field(default_factory=list)
    project_types: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    monthly_notices: bool = False
    tax: dict[str, Any] | None = None
    retention: list[dict[str, Any]] = Field(default_factory=list)
    notice_rules: list[dict[str, Any]] = Field(default_factory=list)
    payroll_export_profiles: list[str] = Field(default_factory=list)
    contract_clauses: list[str] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)
