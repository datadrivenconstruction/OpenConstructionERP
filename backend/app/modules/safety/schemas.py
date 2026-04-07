"""Safety Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Incident schemas ─────────────────────────────────────────────────────


class CorrectiveActionEntry(BaseModel):
    """A corrective action within an incident."""

    description: str = Field(..., min_length=1, max_length=1000)
    responsible_id: str | None = None
    due_date: str | None = Field(default=None, max_length=20)
    status: str = Field(default="open", pattern=r"^(open|in_progress|completed)$")


class IncidentCreate(BaseModel):
    """Create a new safety incident."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    incident_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    location: str | None = Field(default=None, max_length=500)
    incident_type: str = Field(
        ...,
        pattern=r"^(injury|near_miss|property_damage|environmental|fire)$",
    )
    description: str = Field(..., min_length=1)
    injured_person_details: dict[str, Any] | None = None
    treatment_type: str | None = Field(
        default=None,
        pattern=r"^(first_aid|medical|hospital|fatality)$",
    )
    days_lost: int = Field(default=0, ge=0)
    root_cause: str | None = None
    corrective_actions: list[CorrectiveActionEntry] = Field(default_factory=list)
    reported_to_regulator: bool = False
    status: str = Field(
        default="reported",
        pattern=r"^(reported|investigating|corrective_action|closed)$",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentUpdate(BaseModel):
    """Partial update for a safety incident."""

    model_config = ConfigDict(str_strip_whitespace=True)

    incident_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    location: str | None = Field(default=None, max_length=500)
    incident_type: str | None = Field(
        default=None,
        pattern=r"^(injury|near_miss|property_damage|environmental|fire)$",
    )
    description: str | None = Field(default=None, min_length=1)
    injured_person_details: dict[str, Any] | None = None
    treatment_type: str | None = Field(
        default=None,
        pattern=r"^(first_aid|medical|hospital|fatality)$",
    )
    days_lost: int | None = Field(default=None, ge=0)
    root_cause: str | None = None
    corrective_actions: list[CorrectiveActionEntry] | None = None
    reported_to_regulator: bool | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(reported|investigating|corrective_action|closed)$",
    )
    metadata: dict[str, Any] | None = None


class IncidentResponse(BaseModel):
    """Incident returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    incident_number: str
    incident_date: str
    location: str | None = None
    incident_type: str
    description: str
    injured_person_details: dict[str, Any] | None = None
    treatment_type: str | None = None
    days_lost: int = 0
    root_cause: str | None = None
    corrective_actions: list[dict[str, Any]] = Field(default_factory=list)
    reported_to_regulator: bool = False
    status: str = "reported"
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Observation schemas ──────────────────────────────────────────────────


class ObservationCreate(BaseModel):
    """Create a new safety observation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    observation_type: str = Field(
        ...,
        pattern=r"^(positive|unsafe_act|unsafe_condition|near_miss)$",
    )
    description: str = Field(..., min_length=1)
    location: str | None = Field(default=None, max_length=500)
    severity: int = Field(default=1, ge=1, le=5)
    likelihood: int = Field(default=1, ge=1, le=5)
    immediate_action: str | None = None
    corrective_action: str | None = None
    status: str = Field(default="open", pattern=r"^(open|in_progress|closed)$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObservationUpdate(BaseModel):
    """Partial update for a safety observation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    observation_type: str | None = Field(
        default=None,
        pattern=r"^(positive|unsafe_act|unsafe_condition|near_miss)$",
    )
    description: str | None = Field(default=None, min_length=1)
    location: str | None = Field(default=None, max_length=500)
    severity: int | None = Field(default=None, ge=1, le=5)
    likelihood: int | None = Field(default=None, ge=1, le=5)
    immediate_action: str | None = None
    corrective_action: str | None = None
    status: str | None = Field(default=None, pattern=r"^(open|in_progress|closed)$")
    metadata: dict[str, Any] | None = None


class ObservationResponse(BaseModel):
    """Observation returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    observation_number: str
    observation_type: str
    description: str
    location: str | None = None
    severity: int = 1
    likelihood: int = 1
    risk_score: int = 1
    immediate_action: str | None = None
    corrective_action: str | None = None
    status: str = "open"
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
