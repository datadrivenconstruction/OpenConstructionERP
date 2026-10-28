# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the Project Controls snapshot + drill-down API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ControlsKPI(BaseModel):
    """One KPI tile in the controls snapshot."""

    code: str
    label: str
    value: str
    unit: str
    status: str = Field(description="green | amber | red")
    source_record_count: int = 0
    breakdown: dict[str, Any] = Field(default_factory=dict)
    drill_url: str = Field(description="In-app drill-down endpoint for this KPI.")


class ControlsGroup(BaseModel):
    """A domain group (cost / schedule / quality / safety / risk / changes)."""

    domain: str
    label: str
    kpis: list[ControlsKPI] = Field(default_factory=list)


class ControlsAlert(BaseModel):
    """A banded KPI that crossed an amber/red threshold."""

    kpi_code: str
    severity: str = Field(description="warning (amber) | critical (red)")
    message: str


class ControlsSnapshotResponse(BaseModel):
    """The whole executive controls spine in one round-trip."""

    project_id: str | None
    currency: str = ""
    multi_currency: bool = False
    generated_at: str
    groups: list[ControlsGroup] = Field(default_factory=list)
    alerts: list[ControlsAlert] = Field(default_factory=list)


class ControlsDrillRecord(BaseModel):
    """One underlying source record behind a KPI, with a deep link."""

    fields: dict[str, Any] = Field(default_factory=dict)
    deep_link: str | None = None


class ControlsDrillResponse(BaseModel):
    """Drill-down rows for a single KPI, enriched with cross-module links."""

    kpi_code: str
    project_id: str | None
    record_count: int
    records: list[ControlsDrillRecord] = Field(default_factory=list)
