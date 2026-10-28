# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠NCR Pydantic schemas - request/response models."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NCRCreate(BaseModel):
    """Create a new NCR."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1, max_length=10000)
    ncr_type: str = Field(
        ...,
        pattern=r"^(material|workmanship|design|documentation|safety)$",
    )
    severity: str = Field(
        ...,
        pattern=r"^(critical|major|minor|observation)$",
    )
    root_cause: str | None = Field(default=None, max_length=5000)
    root_cause_category: str | None = Field(default=None, max_length=100)
    corrective_action: str | None = Field(default=None, max_length=5000)
    preventive_action: str | None = Field(default=None, max_length=5000)
    status: str = Field(
        default="identified",
        pattern=r"^(identified|under_review|corrective_action|verification|closed|void)$",
    )
    cost_impact: str | None = Field(default=None, max_length=50)
    schedule_impact_days: int | None = Field(default=None, ge=0)
    location_description: str | None = Field(default=None, max_length=500)
    # Optional WGS84 position. Supplying both puts the NCR on the project map;
    # supplying neither leaves it exactly as NCRs behaved before. One without
    # the other is not a position and is rejected by the model validator below.
    location_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    location_lon: Decimal | None = Field(default=None, ge=-180, le=180)
    location_accuracy_m: Decimal | None = Field(default=None, ge=0)
    linked_inspection_id: str | None = Field(default=None, max_length=36)
    # Soft link to a contract package (id or code); scopes this report for package acceptance.
    package_ref: str | None = Field(default=None, max_length=64)
    change_order_id: str | None = Field(default=None, max_length=36)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _coordinates_come_in_pairs(self) -> "NCRCreate":
        """Reject half a position.

        A latitude with no longitude is not a location that can be drawn;
        accepting it would store a row that looks located and silently never
        appears on the map. Accuracy without a position is meaningless in the
        same way, so it is rejected rather than quietly dropped.
        """
        if (self.location_lat is None) != (self.location_lon is None):
            raise ValueError("location_lat and location_lon must be supplied together")
        if self.location_accuracy_m is not None and self.location_lat is None:
            raise ValueError("location_accuracy_m needs a location_lat and location_lon to describe")
        return self


class NCRUpdate(BaseModel):
    """Partial update for an NCR."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    ncr_type: str | None = Field(
        default=None,
        pattern=r"^(material|workmanship|design|documentation|safety)$",
    )
    severity: str | None = Field(
        default=None,
        pattern=r"^(critical|major|minor|observation)$",
    )
    root_cause: str | None = Field(default=None, max_length=5000)
    root_cause_category: str | None = Field(default=None, max_length=100)
    corrective_action: str | None = Field(default=None, max_length=5000)
    preventive_action: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(
        default=None,
        pattern=r"^(identified|under_review|corrective_action|verification|closed|void)$",
    )
    cost_impact: str | None = Field(default=None, max_length=50)
    schedule_impact_days: int | None = Field(default=None, ge=0)
    location_description: str | None = Field(default=None, max_length=500)
    # No pair validator here, unlike NCRCreate: a PATCH that carries only
    # ``location_lon`` is a legitimate correction to a row that already has a
    # latitude, and refusing it would be wrong. The pair rule is enforced in
    # ``NCRService.update_ncr`` against the merged result, which is the only
    # place that can see both halves. Sending both as null clears the position.
    location_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    location_lon: Decimal | None = Field(default=None, ge=-180, le=180)
    location_accuracy_m: Decimal | None = Field(default=None, ge=0)
    linked_inspection_id: str | None = Field(default=None, max_length=36)
    # Soft link to a contract package (id or code); scopes this report for package acceptance.
    package_ref: str | None = Field(default=None, max_length=64)
    change_order_id: str | None = Field(default=None, max_length=36)
    metadata: dict[str, Any] | None = None


class NCRResponse(BaseModel):
    """NCR returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    ncr_number: str
    title: str
    description: str
    ncr_type: str
    severity: str
    root_cause: str | None = None
    root_cause_category: str | None = None
    corrective_action: str | None = None
    preventive_action: str | None = None
    status: str = "identified"
    cost_impact: str | None = None
    schedule_impact_days: int | None = None
    location_description: str | None = None
    location_lat: Decimal | None = None
    location_lon: Decimal | None = None
    location_accuracy_m: Decimal | None = None
    linked_inspection_id: str | None = None
    package_ref: str | None = None
    change_order_id: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class NCRListResponse(BaseModel):
    """One page of a project's NCR register plus the size of the whole set.

    ``total`` counts the reports the type, status and severity filters
    matched, not the length of ``items``. Non-conformance reports are quality
    evidence that accumulates for the life of a project and is never pruned,
    so this is a register that grows without bound and a page of it says
    nothing about the register unless it carries the count.
    """

    items: list[NCRResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50
