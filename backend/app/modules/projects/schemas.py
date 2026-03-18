"""Project Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Create / Update ───────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    """Create a new project."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    region: str = Field(
        default="DACH",
        pattern=r"^(DACH|UK|US|INTL)$",
    )
    classification_standard: str = Field(
        default="din276",
        pattern=r"^(din276|nrm|masterformat)$",
    )
    currency: str = Field(default="EUR", max_length=10)
    locale: str = Field(default="de", max_length=10)
    validation_rule_sets: list[str] = Field(default_factory=lambda: ["boq_quality"])


class ProjectUpdate(BaseModel):
    """Update project fields. All optional — only provided fields are updated."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    region: str | None = Field(default=None, pattern=r"^(DACH|UK|US|INTL)$")
    classification_standard: str | None = Field(
        default=None,
        pattern=r"^(din276|nrm|masterformat)$",
    )
    currency: str | None = Field(default=None, max_length=10)
    locale: str | None = Field(default=None, max_length=10)
    validation_rule_sets: list[str] | None = None
    metadata: dict[str, Any] | None = None


# ── Response ──────────────────────────────────────────────────────────────


class ProjectResponse(BaseModel):
    """Project in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    region: str
    classification_standard: str
    currency: str
    locale: str
    validation_rule_sets: list[str]
    status: str
    owner_id: UUID
    metadata_: dict[str, Any] = Field(alias="metadata_")
    created_at: datetime
    updated_at: datetime
