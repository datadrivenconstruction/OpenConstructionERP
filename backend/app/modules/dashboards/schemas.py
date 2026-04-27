"""Pydantic DTOs for the dashboards module.

Each schema here is a direct mapping between an API request/response
and a domain-level concept. ``from_attributes=True`` lets FastAPI build
the response straight from the ORM row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

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
        ...,
        description='One of "histogram" | "bar" | "line" | "scatter" | "donut".',
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


# ── Cascade Filter Engine (T04) ────────────────────────────────────────────


class CascadeValuesRequest(BaseModel):
    """Body for ``POST /snapshots/{id}/cascade-values``.

    ``selected`` is a column → allowed-values map. An empty list under a
    key means "no filter on that column" — the engine drops it before
    generating SQL (DuckDB rejects ``WHERE col IN ()``).
    """

    model_config = ConfigDict(extra="forbid")

    selected: dict[str, list[str]] = Field(default_factory=dict)
    target_column: str = Field(..., min_length=1, max_length=200)
    q: str = Field(default="", max_length=200)
    limit: int = Field(default=50, ge=1, le=200)


class CascadeValueOut(BaseModel):
    """One distinct-value/count pair under the active selection."""

    value: str
    count: int = Field(..., ge=0)


class CascadeValuesOut(BaseModel):
    snapshot_id: uuid.UUID
    target_column: str
    q: str = ""
    values: list[CascadeValueOut] = Field(default_factory=list)


class CascadeRowCountOut(BaseModel):
    """Response for ``GET /snapshots/{id}/row-count``.

    ``matched`` is the number of rows consistent with the selection;
    ``total`` is the snapshot's full entity count. The frontend pairs
    these to render "X of Y rows match".
    """

    snapshot_id: uuid.UUID
    matched: int = Field(..., ge=0)
    total: int = Field(..., ge=0)


# ── Dashboard Presets & Collections (T05) ──────────────────────────────────


PresetKind = Literal["preset", "collection"]


class DashboardPresetCreate(BaseModel):
    """Request body for ``POST /v1/dashboards/presets``."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    kind: PresetKind = "preset"
    project_id: uuid.UUID | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    shared_with_project: bool = False


class DashboardPresetUpdate(BaseModel):
    """Request body for ``PATCH /v1/dashboards/presets/{id}``."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    kind: PresetKind | None = None
    config_json: dict[str, Any] | None = None
    shared_with_project: bool | None = None


SyncStatus = Literal["synced", "stale", "needs_review"]


class DashboardPresetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: str | None = None
    project_id: uuid.UUID | None = None
    owner_id: uuid.UUID
    name: str
    description: str | None = None
    kind: PresetKind
    config_json: dict[str, Any] = Field(default_factory=dict)
    shared_with_project: bool = False
    sync_status: SyncStatus = "synced"
    last_sync_check_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DashboardPresetListResponse(BaseModel):
    total: int
    items: list[DashboardPresetOut]


# ── Sync Protocol (T09 / task #192) ────────────────────────────────────────


SyncIssueKind = Literal[
    "column_rename",
    "dropped_column",
    "dropped_filter_value",
    "dtype_change",
]
SyncSeverity = Literal["warning", "error"]
SyncSuggestedFix = Literal["auto_rename", "drop_filter", "manual"]


class SyncIssueOut(BaseModel):
    """One staleness signal between a preset and its source snapshot."""

    kind: SyncIssueKind
    severity: SyncSeverity
    suggested_fix: SyncSuggestedFix
    column: str
    new_column: str | None = None
    dropped_values: list[str] = Field(default_factory=list)
    old_dtype: str | None = None
    new_dtype: str | None = None
    message_key: str
    message: str = ""


class SyncReportOut(BaseModel):
    """Full sync report for a preset against its current snapshot meta."""

    preset_id: uuid.UUID
    snapshot_id: uuid.UUID | None = None
    status: SyncStatus
    is_in_sync: bool
    column_renames: list[SyncIssueOut] = Field(default_factory=list)
    dropped_columns: list[SyncIssueOut] = Field(default_factory=list)
    dropped_filter_values: list[SyncIssueOut] = Field(default_factory=list)
    dtype_changes: list[SyncIssueOut] = Field(default_factory=list)


class SyncHealOut(BaseModel):
    """Result of POST /presets/{id}/sync-heal — patched preset + report."""

    preset: DashboardPresetOut
    report: SyncReportOut


# ── Tabular Data I/O (T06) ─────────────────────────────────────────────────


class SnapshotRowsOut(BaseModel):
    """Paginated row reader response."""

    snapshot_id: uuid.UUID
    columns: list[str]
    rows: list[dict[str, Any]] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class SnapshotImportPreviewOut(BaseModel):
    """Result of the dry-run import endpoint.

    ``staging_id`` is an opaque token the caller passes back to
    ``POST /import/commit`` to materialise the upload.
    """

    snapshot_id: uuid.UUID
    staging_id: str
    columns: list[str]
    matched_columns: list[str]
    missing_columns: list[str] = Field(default_factory=list)
    extra_columns: list[str] = Field(default_factory=list)
    total_rows: int
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)


class SnapshotImportCommitIn(BaseModel):
    staging_id: str = Field(..., min_length=1, max_length=200)


class SnapshotImportCommitOut(BaseModel):
    snapshot_id: uuid.UUID
    staging_id: str
    rows_committed: int


# ── Dataset Integrity Overview (T07) ───────────────────────────────────────


class IntegritySampleValueOut(BaseModel):
    """One top-frequency value from a column's sample."""

    value: str
    count: int = Field(..., ge=0)


class IntegrityColumnOut(BaseModel):
    """Per-column integrity diagnostics."""

    name: str
    dtype: str
    inferred_type: str = Field(
        ...,
        description='One of "numeric" | "datetime" | "boolean" | "string" | "empty".',
    )
    row_count: int = Field(..., ge=0)
    null_count: int = Field(..., ge=0)
    null_pct: float = Field(..., ge=0.0, le=1.0)
    unique_count: int = Field(..., ge=0)
    completeness: float = Field(..., ge=0.0, le=1.0)
    sample_values: list[IntegritySampleValueOut] = Field(default_factory=list)
    zero_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    outlier_count: int | None = Field(default=None, ge=0)
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    issues: list[str] = Field(default_factory=list)


class IntegrityReportOut(BaseModel):
    """Whole-snapshot integrity report.

    ``completeness_score`` is the average of per-column completeness
    (1 − null_pct). ``schema_hash`` lets the frontend cache column
    detail views across reloads — a hash change means the snapshot's
    column shape moved.
    """

    snapshot_id: uuid.UUID
    project_id: uuid.UUID
    row_count: int = Field(..., ge=0)
    column_count: int = Field(..., ge=0)
    completeness_score: float = Field(..., ge=0.0, le=1.0)
    schema_hash: str
    columns: list[IntegrityColumnOut] = Field(default_factory=list)
    issue_summary: dict[str, int] = Field(default_factory=dict)


class IntegrityReportRequest(BaseModel):
    """Body for ``POST /v1/dashboards/integrity-report``.

    The endpoint takes ``snapshot_id`` in the body (rather than the URL)
    so the panel can refresh after a snapshot edit without re-keying
    the route. ``project_id`` is required up front — the report has to
    namespace caches by project, and we don't want to round-trip the
    snapshot detail just for that.
    """

    model_config = ConfigDict(extra="forbid")

    snapshot_id: uuid.UUID
    project_id: uuid.UUID


# ── Historical Snapshot Navigator (T11) ────────────────────────────────────


class SnapshotTimelineItemOut(BaseModel):
    """One row of the navigator timeline.

    Narrow on purpose — the timeline must scroll smoothly through
    hundreds of snapshots, so we ship only what the timeline card and
    the per-row badges need. The diff endpoint does the heavier work.
    """

    id: uuid.UUID
    project_id: uuid.UUID
    label: str
    created_at: datetime
    created_by_user_id: uuid.UUID
    parent_snapshot_id: uuid.UUID | None = None
    total_entities: int = Field(..., ge=0)
    total_categories: int = Field(..., ge=0)
    source_file_count: int = Field(..., ge=0)
    schema_hash: str | None = None
    completeness_score: float | None = Field(default=None, ge=0.0, le=1.0)


class SnapshotTimelineResponse(BaseModel):
    """Paginated timeline response.

    ``next_before`` is the cursor the frontend should send back to load
    older entries; it is the ``created_at`` of the oldest item in the
    current page (or ``None`` when there is nothing else to fetch).
    """

    project_id: uuid.UUID
    items: list[SnapshotTimelineItemOut] = Field(default_factory=list)
    next_before: datetime | None = None


class SnapshotDiffColumnChangeOut(BaseModel):
    """One column whose dtype differs between A and B."""

    name: str
    a_dtype: str
    b_dtype: str


class SnapshotDiffOut(BaseModel):
    """Structural diff between two snapshots.

    All deltas are reported as ``A → B``: ``columns_added`` is the set
    of columns *new* in B, ``columns_removed`` is *dropped* in B,
    ``rows_added`` / ``rows_removed`` are positive non-overlapping
    deltas. ``schema_hash_match`` is ``True`` only when both sides
    recorded a hash and the hashes agree.
    """

    snapshot_a_id: uuid.UUID
    snapshot_b_id: uuid.UUID
    a_label: str
    b_label: str
    a_created_at: datetime
    b_created_at: datetime
    columns_added: list[str] = Field(default_factory=list)
    columns_removed: list[str] = Field(default_factory=list)
    columns_changed: list[SnapshotDiffColumnChangeOut] = Field(default_factory=list)
    a_row_count: int = Field(..., ge=0)
    b_row_count: int = Field(..., ge=0)
    rows_added: int = Field(..., ge=0)
    rows_removed: int = Field(..., ge=0)
    schema_hash_match: bool = False
    is_identical: bool = False
