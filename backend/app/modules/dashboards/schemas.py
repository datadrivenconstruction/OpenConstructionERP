"""Pydantic DTOs for the dashboards module.

Each schema here is a direct mapping between an API request/response
and a domain-level concept. ``from_attributes=True`` lets FastAPI build
the response straight from the ORM row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Snapshot source-file ──────────────────────────────────────────────────


class SnapshotSourceFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_name: str
    format: str
    discipline: str | None
    entity_count: int
    bytes_size: int
    converter_notes: dict[str, Any] = Field(default_factory=dict)


# ── Snapshot ─────────────────────────────────────────────────────────────────


class SnapshotSummaryOut(BaseModel):
    """List-row shape. No ``source_files`` — list views don't need them."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    label: str
    total_entities: int
    total_categories: int
    summary_stats: dict[str, int] = Field(default_factory=dict)
    created_by_user_id: uuid.UUID
    created_at: datetime


class SnapshotOut(SnapshotSummaryOut):
    """Detail-view shape including source-file descriptors."""

    parquet_dir: str
    parent_snapshot_id: uuid.UUID | None = None
    source_files: list[SnapshotSourceFileOut] = Field(default_factory=list)


class SnapshotListResponse(BaseModel):
    total: int
    items: list[SnapshotSummaryOut]


class SnapshotCreateForm(BaseModel):
    """Request body for ``POST /projects/{project_id}/snapshots``.

    Used for the JSON parts of a multipart upload. The actual file
    bytes arrive as ``UploadFile`` parameters on the router.
    """

    label: str = Field(..., min_length=1, max_length=200)
    disciplines: list[str] = Field(default_factory=list)
    # Optional — if provided and matches an existing snapshot on the
    # same project, the new snapshot records that relationship
    # (powers the historical diff in T11).
    parent_snapshot_id: uuid.UUID | None = None


class SnapshotManifestOut(BaseModel):
    """Shape of the on-disk ``manifest.json`` exposed via
    ``GET /snapshots/{id}/manifest``."""

    label: str
    total_entities: int
    total_categories: int
    summary_stats: dict[str, int]
    source_files: list[dict[str, Any]]
    created_by_user_id: str
    created_at: str


# ── Error envelope (for typed 4xx/5xx) ─────────────────────────────────────


class SnapshotErrorOut(BaseModel):
    """Structured error envelope. All dashboard endpoints return this
    shape on non-2xx; frontend picks up ``message_key`` to render the
    already-localised string from its i18n bundle."""

    message_key: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


# ── Quick-Insight Panel (T02) ──────────────────────────────────────────────


class QuickInsightChartOut(BaseModel):
    """One auto-generated chart suggestion.

    ``data`` is shaped for direct rendering in Recharts: a list of
    small dicts whose keys match ``x_field`` and ``y_field``. ``agg_fn``
    tells the frontend whether the y values are means, counts, or raw.
    ``interestingness`` is a 0..5 score the panel uses to decide the
    visual prominence of the card.
    """

    chart_type: str = Field(
        ..., description='One of "histogram" | "bar" | "line" | "scatter" | "donut".',
    )
    title: str
    data: list[dict[str, Any]] = Field(default_factory=list)
    x_field: str
    y_field: str
    agg_fn: str | None = None
    interestingness: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuickInsightsOut(BaseModel):
    """Top-N auto-charts for a snapshot."""

    snapshot_id: uuid.UUID
    charts: list[QuickInsightChartOut] = Field(default_factory=list)
    total_candidates: int = 0


# ── Smart Value Autocomplete (T03) ─────────────────────────────────────────


class SmartValueOut(BaseModel):
    """One autocomplete suggestion."""

    value: str
    count: int = Field(..., ge=0)
    score: float = Field(default=0.0, description="rapidfuzz WRatio (0..100)")


class SmartValuesOut(BaseModel):
    snapshot_id: uuid.UUID
    column: str
    query: str = ""
    items: list[SmartValueOut] = Field(default_factory=list)
