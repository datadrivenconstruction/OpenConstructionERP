# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas for the project tax profile."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaxMethodLiteral = Literal["general", "simplified", "exempt"]
TaxpayerSizeLiteral = Literal["general", "small"]


class ProfileFields(BaseModel):
    """The fields a person states about a project's tax position."""

    tax_method: TaxMethodLiteral = "general"
    election_date: date | None = None
    lock_months: int | None = Field(default=None, ge=0, le=240)
    grandfathered: bool = False
    simplified_basis: str | None = Field(default=None, max_length=40)
    employer_supplied: bool = False
    taxpayer_size: TaxpayerSizeLiteral = "general"
    permit_start_date: date | None = None
    contract_date: date | None = None
    tender_date: date | None = None
    standard_edition: str | None = Field(default=None, max_length=40)
    site_subdivision: str | None = Field(default=None, max_length=10)
    site_city: str | None = Field(default=None, max_length=100)
    home_subdivision: str | None = Field(default=None, max_length=10)
    home_city: str | None = Field(default=None, max_length=100)
    notes: str = Field(default="", max_length=4000)


class ProfileUpdate(ProfileFields):
    """Body of the PUT. Every field is stated; a missing one takes its default."""

    model_config = ConfigDict(extra="forbid")


class EditionOption(BaseModel):
    """One edition of the project's bill standard a person can pick."""

    key: str
    label: str
    in_force_from: str | None = None


class ProfileResponse(ProfileFields):
    """The stored profile, or a derived proposal when ``stored`` is false."""

    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    stored: bool = True
    edition_source: Literal["stored", "derived", "none"] = "stored"
    cross_region: bool | None = None
    lock_ends_on: date | None = None
    method_history: list[dict[str, Any]] = Field(default_factory=list)
    editions: list[EditionOption] = Field(default_factory=list)


class ProfileFinding(BaseModel):
    """One validation finding on a saved profile."""

    rule_id: str
    severity: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ProfileSaveResponse(BaseModel):
    """What a save returns: the profile as stored and what the rules said."""

    profile: ProfileResponse
    findings: list[ProfileFinding] = Field(default_factory=list)
