# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the Asset Operations API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Health / lifecycle ────────────────────────────────────────────────────────


class AssetHealthSchema(BaseModel):
    """Computed warranty / maintenance / lifecycle health for one asset."""

    warranty_status: str
    warranty_until: str | None = None
    days_to_warranty_expiry: int | None = None

    maintenance_status: str
    next_maintenance_due: str | None = None
    days_to_maintenance: int | None = None
    maintenance_interval_days: int | None = None
    last_serviced: str | None = None

    age_days: int | None = None
    age_years: float | None = None

    service_log_count: int = 0
    attention_score: int = 0
    issues: list[str] = Field(default_factory=list)


class AssetRow(BaseModel):
    """One asset enriched with computed health, for the operations list."""

    id: UUID
    model_id: UUID
    project_id: UUID
    model_name: str
    stable_id: str
    element_type: str | None = None
    name: str | None = None
    storey: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    operational_status: str | None = None
    parent_system: str | None = None
    asset_info: dict[str, Any] = Field(default_factory=dict)
    health: AssetHealthSchema


class AssetListResponse(BaseModel):
    """Paginated, health-enriched asset list."""

    items: list[AssetRow] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ── Portfolio summary ─────────────────────────────────────────────────────────


class PortfolioSummary(BaseModel):
    """Roll-up KPIs across every tracked asset in a project."""

    total_assets: int = 0
    by_operational_status: dict[str, int] = Field(default_factory=dict)
    by_warranty_status: dict[str, int] = Field(default_factory=dict)
    by_maintenance_status: dict[str, int] = Field(default_factory=dict)
    warranties_expiring_soon: int = 0
    warranties_expired: int = 0
    maintenance_due: int = 0
    maintenance_overdue: int = 0
    needs_attention: int = 0
    models_covered: int = 0
    avg_age_years: float | None = None
    # Top assets by attention score, ready for a "needs attention" panel.
    top_attention: list[AssetRow] = Field(default_factory=list)


# ── Discovery ─────────────────────────────────────────────────────────────────


class DiscoveryCandidate(BaseModel):
    """A BIM element ranked as a likely managed asset."""

    id: UUID
    model_id: UUID
    model_name: str
    stable_id: str
    element_type: str | None = None
    name: str | None = None
    storey: str | None = None
    score: int
    reasons: list[str] = Field(default_factory=list)
    suggested_asset_info: dict[str, str] = Field(default_factory=dict)


class DiscoveryResponse(BaseModel):
    """Ranked discovery candidates plus a scan summary."""

    items: list[DiscoveryCandidate] = Field(default_factory=list)
    total_candidates: int = 0
    scanned_elements: int = 0
    already_tracked: int = 0
    models_scanned: int = 0
    threshold: int = 35


# ── Warranty alerting ─────────────────────────────────────────────────────────


class WarrantyAlertRequest(BaseModel):
    """Configure a warranty-alert scan + dispatch."""

    model_config = ConfigDict(str_strip_whitespace=True)

    lead_days: int = Field(default=90, ge=1, le=730)
    # When false, returns the would-notify list without sending anything.
    dispatch: bool = False


class WarrantyAlertItem(BaseModel):
    """One asset whose warranty is expired / expiring within the lead window."""

    id: UUID
    model_id: UUID
    model_name: str
    stable_id: str
    name: str | None = None
    warranty_until: str | None = None
    days_to_expiry: int | None = None
    status: str  # expired | expiring


class WarrantyAlertResponse(BaseModel):
    """Result of a warranty-alert scan."""

    items: list[WarrantyAlertItem] = Field(default_factory=list)
    total: int = 0
    dispatched: bool = False
    notifications_sent: int = 0
    recipients: int = 0
    # True when notifications were requested but the notifications module
    # is unavailable - the scan still returns the list (graceful degrade).
    notifications_unavailable: bool = False


# ── Service log ───────────────────────────────────────────────────────────────


class ServiceLogEntryRequest(BaseModel):
    """Append a maintenance / service event to an asset's history.

    Persisted into ``BIMElement.asset_info.service_log`` via the BIM Hub,
    so no new table is needed.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    date: str = Field(..., max_length=20, description="ISO-8601 service date")
    note: str = Field(..., min_length=1, max_length=1000)
    kind: str = Field(default="service", max_length=40)
    cost: str | None = Field(default=None, max_length=40)
    performed_by: str | None = Field(default=None, max_length=255)


class ServiceLogResponse(BaseModel):
    """Full service log for an asset after an append."""

    asset_id: UUID
    service_log: list[dict[str, Any]] = Field(default_factory=list)
    health: AssetHealthSchema
