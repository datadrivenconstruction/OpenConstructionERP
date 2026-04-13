"""NCR Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    linked_inspection_id: str | None = Field(default=None, max_length=36)
    change_order_id: str | None = Field(default=None, max_length=36)
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    linked_inspection_id: str | None = Field(default=None, max_length=36)
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
    linked_inspection_id: str | None = None
    change_order_id: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
