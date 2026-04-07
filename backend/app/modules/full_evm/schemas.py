"""Full EVM Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── EVM Forecast ────────────────────────────────────────────────────────────


class EVMForecastCreate(BaseModel):
    """Manually create an EVM forecast record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    forecast_date: str = Field(..., max_length=20)
    etc: str = Field(default="0", max_length=50, alias="etc_")
    eac: str = Field(default="0", max_length=50)
    vac: str = Field(default="0", max_length=50)
    tcpi: str = Field(default="0", max_length=50)
    forecast_method: str = Field(default="cpi", max_length=50)
    confidence_range_low: str | None = Field(default=None, max_length=50)
    confidence_range_high: str | None = Field(default=None, max_length=50)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EVMForecastResponse(BaseModel):
    """EVM forecast returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    forecast_date: str
    etc: str = Field(default="0", validation_alias="etc_")
    eac: str = "0"
    vac: str = "0"
    tcpi: str = "0"
    forecast_method: str = "cpi"
    confidence_range_low: str | None = None
    confidence_range_high: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class EVMForecastListResponse(BaseModel):
    """Paginated list of EVM forecasts."""

    items: list[EVMForecastResponse]
    total: int


class EVMCalculateRequest(BaseModel):
    """Request to calculate EVM forecast from latest snapshot data."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    forecast_method: str = Field(default="cpi", max_length=50)


class SCurveDataResponse(BaseModel):
    """S-curve data for charting."""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    snapshots: list[dict[str, Any]] = Field(default_factory=list)
    forecasts: list[dict[str, Any]] = Field(default_factory=list)
