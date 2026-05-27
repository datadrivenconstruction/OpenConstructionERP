# OpenConstructionERP — DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""Progress tracking Pydantic schemas — request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Progress Entry ────────────────────────────────────────────────────────────


class ProgressEntryCreate(BaseModel):
    """Record a new percent-complete observation for a BOQ position."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    boq_position_id: UUID | None = None
    period_label: str = Field(..., min_length=1, max_length=20)
    percent_complete: float = Field(..., ge=0.0, le=100.0)
    notes: str | None = Field(default=None, max_length=2000)
    # WGS84 geo pin from the field worker's device
    geo_lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    geo_lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    photos: list[str] = Field(default_factory=list, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("photos")
    @classmethod
    def _validate_photos(cls, v: list[str]) -> list[str]:
        """Reject photo paths that look like path-traversal attempts or are oversized.

        Progress photos stored here should be server-issued opaque paths (e.g.
        ``uploads/progress/photos/<uuid>.jpg``).  We sanitise caller-supplied
        values so that no path-traversal string can be persisted.
        """
        cleaned: list[str] = []
        for raw in v:
            if not isinstance(raw, str):
                raise ValueError("Each photo entry must be a string")
            if len(raw) > 512:
                raise ValueError(f"Photo path too long (max 512 chars): {raw[:80]!r}")
            # Reject obvious path-traversal patterns
            normalised = raw.replace("\\", "/")
            if ".." in normalised.split("/"):
                raise ValueError(f"Photo path contains path traversal component: {raw!r}")
            cleaned.append(raw)
        return cleaned

    @field_validator("percent_complete")
    @classmethod
    def _round_pct(cls, v: float) -> float:
        """Round to 3 decimal places to avoid submitting >100 due to FP drift."""
        rounded = round(v, 3)
        if rounded < 0 or rounded > 100:
            raise ValueError("percent_complete must be in [0, 100]")
        return rounded


class ProgressEntryResponse(BaseModel):
    """Single progress entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    boq_position_id: UUID | None = None
    period_label: str
    percent_complete: float
    notes: str | None = None
    recorded_by: str | None = None
    recorded_at: datetime
    geo_lat: float | None = None
    geo_lon: float | None = None
    photos: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Progress Plan ─────────────────────────────────────────────────────────────


class ProgressPlanCreate(BaseModel):
    """Create or upsert a planned S-curve data point."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    period_label: str = Field(..., min_length=1, max_length=20)
    planned_pct: float = Field(..., ge=0.0, le=100.0)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("planned_pct")
    @classmethod
    def _round_pct(cls, v: float) -> float:
        rounded = round(v, 3)
        if rounded < 0 or rounded > 100:
            raise ValueError("planned_pct must be in [0, 100]")
        return rounded


class ProgressPlanResponse(BaseModel):
    """Single planned data point returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    period_label: str
    planned_pct: float
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Position progress summary ─────────────────────────────────────────────────


class PositionProgressSummary(BaseModel):
    """Current progress state for a single BOQ position."""

    boq_position_id: UUID
    current_pct: float = 0.0
    """Latest recorded percent_complete for this position."""
    entries_count: int = 0
    last_recorded_at: datetime | None = None
    last_period_label: str | None = None
    """Rollup from children: if this position has children in the BOQ hierarchy,
    current_pct is the weighted average of their latest percent_completes."""
    is_rollup: bool = False


# ── Cumulative / per-period summary ──────────────────────────────────────────


class PeriodProgress(BaseModel):
    """Progress for a single period."""

    period_label: str
    delta_pct: float = 0.0
    """Increase in completion % during this period (can be 0 but never negative by design)."""
    cumulative_pct: float = 0.0
    """Running total of percent_complete at end of this period."""
    entry_count: int = 0


class CumulativeProgressResponse(BaseModel):
    """Per-period breakdown and cumulative rollup for a project or position."""

    project_id: UUID
    boq_position_id: UUID | None = None
    periods: list[PeriodProgress] = Field(default_factory=list)
    current_cumulative_pct: float = 0.0


# ── S-curve ───────────────────────────────────────────────────────────────────


class SCurvePoint(BaseModel):
    """One point on the S-curve (actual vs planned)."""

    period_label: str
    actual_cumulative_pct: float = 0.0
    planned_cumulative_pct: float | None = None
    """None when no plan entry exists for this period."""


class SCurveResponse(BaseModel):
    """S-curve data: actual vs planned progress over time."""

    project_id: UUID
    points: list[SCurvePoint] = Field(default_factory=list)
