"""Project Pydantic schemas for request/response validation."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ── Create / Update ───────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    """Create a new project."""

    name: str = Field(..., min_length=1, max_length=255)

    @field_validator("name", mode="after")
    @classmethod
    def strip_html_tags(cls, v: str) -> str:
        """Remove HTML tags to prevent XSS in project names."""
        return _HTML_TAG_RE.sub("", v).strip()
    description: str = Field(default="", max_length=5000)
    region: str = Field(
        default="",
        max_length=100,
        description="Region/market identifier — user must choose, no default bias",
    )
    classification_standard: str = Field(
        default="",
        max_length=100,
        description="Classification standard — accepts any standard identifier",
    )
    currency: str = Field(
        default="",
        max_length=10,
        description="ISO 4217 currency code — user must choose, no default bias",
    )
    locale: str = Field(default="en", max_length=10)
    validation_rule_sets: list[str] = Field(default_factory=lambda: ["boq_quality"])


class ProjectUpdate(BaseModel):
    """Update project fields. All optional — only provided fields are updated."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    region: str | None = Field(default=None, max_length=100)
    classification_standard: str | None = Field(default=None, max_length=100)
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
