"""Risk Register Pydantic schemas — request/response models.

Defines create, update, and response schemas for risk register items.
Numeric values (probability, impact_cost, risk_score, response_cost) are exposed
as floats in the API but stored as strings in SQLite-compatible models.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Risk schemas ─────────────────────────────────────────────────────────


class RiskCreate(BaseModel):
    """Create a new risk item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    category: str = Field(
        default="technical",
        pattern=r"^(technical|financial|schedule|regulatory|environmental|safety)$",
    )
    probability: float = Field(default=0.5, ge=0.0, le=1.0)
    impact_cost: float = Field(default=0.0, ge=0.0)
    impact_schedule_days: int = Field(default=0, ge=0)
    impact_severity: str = Field(
        default="medium",
        pattern=r"^(low|medium|high|critical)$",
    )
    mitigation_strategy: str = Field(default="", max_length=5000)
    contingency_plan: str = Field(default="", max_length=5000)
    owner_name: str = Field(default="", max_length=255)
    response_cost: float = Field(default=0.0, ge=0.0)
    currency: str = Field(default="EUR", max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskUpdate(BaseModel):
    """Partial update for a risk item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(
        default=None,
        pattern=r"^(technical|financial|schedule|regulatory|environmental|safety)$",
    )
    probability: float | None = Field(default=None, ge=0.0, le=1.0)
    impact_cost: float | None = Field(default=None, ge=0.0)
    impact_schedule_days: int | None = Field(default=None, ge=0)
    impact_severity: str | None = Field(
        default=None,
        pattern=r"^(low|medium|high|critical)$",
    )
    status: str | None = Field(
        default=None,
        pattern=r"^(identified|assessed|mitigating|closed|occurred)$",
    )
    mitigation_strategy: str | None = Field(default=None, max_length=5000)
    contingency_plan: str | None = Field(default=None, max_length=5000)
    owner_name: str | None = Field(default=None, max_length=255)
    response_cost: float | None = Field(default=None, ge=0.0)
    currency: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None


class RiskResponse(BaseModel):
    """Risk item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    code: str
    title: str
    description: str
    category: str
    probability: float = 0.5
    impact_cost: float = 0.0
    impact_schedule_days: int = 0
    impact_severity: str = "medium"
    risk_score: float = 0.0
    status: str = "identified"
    mitigation_strategy: str = ""
    contingency_plan: str = ""
    owner_name: str = ""
    response_cost: float = 0.0
    currency: str = "EUR"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Summary schema ───────────────────────────────────────────────────────


class TopRisk(BaseModel):
    """A high-scoring risk for display in stats."""

    title: str
    score: float


class RiskSummary(BaseModel):
    """Aggregated risk stats for a project."""

    total: int = 0
    total_risks: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_tier: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    high_critical_count: int = 0
    avg_risk_score: float = 0.0
    total_exposure: float = 0.0
    with_mitigation: int = 0
    without_mitigation: int = 0
    mitigated_count: int = 0
    top_risks: list[TopRisk] = Field(default_factory=list)
    currency: str = "EUR"


# ── Risk Matrix schema ───────────────────────────────────────────────────


class RiskMatrixCell(BaseModel):
    """Single cell in the 5x5 risk matrix."""

    probability_level: str
    impact_level: str
    count: int = 0
    risk_ids: list[UUID] = Field(default_factory=list)


class RiskMatrixResponse(BaseModel):
    """5x5 risk matrix data."""

    cells: list[RiskMatrixCell] = Field(default_factory=list)
