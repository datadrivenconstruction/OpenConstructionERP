# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Historical Snapshot Navigator (T11).

Pure helpers that power the snapshot timeline + diff UX. The functions
in this module never reach into FastAPI — they take a session-shaped
repository (or a pre-loaded list of ``Snapshot`` rows) and return plain
dataclasses. The router glue maps the dataclasses onto Pydantic
schemas; tests exercise this module directly without spinning up an
HTTP client.

Two entry points
----------------
* :func:`list_snapshots_for_project` — newest-first slice of snapshot
  metadata, optionally cursored with a ``before`` timestamp so the
  frontend can keep loading history without ``offset`` drift when new
  snapshots arrive concurrently.
* :func:`diff_two_snapshots` — column-level adds / drops / dtype
  changes plus row-count delta for two arbitrary snapshots in the same
  project. The two snapshots do not need to be parent/child — the
  navigator UX lets the user pick any pair.

Schema introspection
--------------------
For the diff we need each snapshot's column list. Two paths exist:

1. The ``summary_stats`` blob on the row already encodes per-category
   row counts — cheap, no I/O.
2. The on-disk Parquet file gives the authoritative ``(name, dtype)``
   pairs and the row count. We prefer this path when the parquet is
   reachable; we fall back to ``summary_stats`` if it isn't (deleted
   files, S3 backend without httpfs, etc.).

Both code paths feed :class:`SchemaSnapshot` so the diff function only
sees a uniform shape.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── Public dataclasses ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class SnapshotMeta:
    """Lightweight timeline row.

    The historical navigator pulls these in pages of 50 — keeping the
    shape narrow makes the JSON payload small for projects with
    hundreds of snapshots. ``schema_hash`` is taken from the manifest
    when available so the timeline can render an "identical schema"
    icon without a per-row Parquet probe.
    """

    id: uuid.UUID
    project_id: uuid.UUID
    label: str
    created_at: datetime
    created_by_user_id: uuid.UUID
    parent_snapshot_id: uuid.UUID | None
    total_entities: int
    total_categories: int
    source_file_count: int
    schema_hash: str | None = None
    completeness_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "label": self.label,
            "created_at": self.created_at.isoformat(),
            "created_by_user_id": str(self.created_by_user_id),
            "parent_snapshot_id": (
                str(self.parent_snapshot_id) if self.parent_snapshot_id else None
            ),
            "total_entities": self.total_entities,
            "total_categories": self.total_categories,
            "source_file_count": self.source_file_count,
            "schema_hash": self.schema_hash,
            "completeness_score": self.completeness_score,
        }


@dataclass(frozen=True)
class SchemaSnapshot:
    """Column inventory for a single snapshot.

    Used only as an internal handle by :func:`diff_two_snapshots`. Not
    exposed to the API — the diff endpoint returns the *delta*, not the
    raw schemas.
    """

    snapshot_id: uuid.UUID
    columns: dict[str, str]
    """``{column_name: dtype_string}`` — order is irrelevant for the
    diff but kept stable so callers that want to render the columns in
    file-order can sort by their own key."""
    row_count: int
    schema_hash: str | None = None


@dataclass(frozen=True)
class ColumnChange:
    """One column with a dtype that differs between A and B."""

    name: str
    a_dtype: str
    b_dtype: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "a_dtype": self.a_dtype,
            "b_dtype": self.b_dtype,
        }


@dataclass(frozen=True)
class SnapshotDiff:
    """Result of comparing two snapshots."""

    snapshot_a_id: uuid.UUID
    snapshot_b_id: uuid.UUID
    a_label: str
    b_label: str
    a_created_at: datetime
    b_created_at: datetime
    columns_added: list[str] = field(default_factory=list)
    """Columns present in B but missing from A — i.e. *new* in B."""
    columns_removed: list[str] = field(default_factory=list)
    """Columns present in A but missing from B — i.e. *dropped* in B."""
    columns_changed: list[ColumnChange] = field(default_factory=list)
    """Columns whose dtype differs between A and B."""
    a_row_count: int = 0
    b_row_count: int = 0
    rows_added: int = 0
    """``max(0, b_row_count - a_row_count)`` — the timeline always
    diffs older→newer, so 'added' is the positive delta."""
    rows_removed: int = 0
    """``max(0, a_row_count - b_row_count)``."""
    schema_hash_match: bool = False
    """Whether the manifest-side schema hashes agree. ``False`` even
    when the column lists agree but at least one snapshot has no
    schema hash recorded — callers should treat ``True`` as a strict
    "identical structure" claim."""

    @property
    def is_identical(self) -> bool:
        """Two snapshots are *identical* if neither side reports any
        column movement and the row count matches."""
        return (
            not self.columns_added
            and not self.columns_removed
            and not self.columns_changed
            and self.a_row_count == self.b_row_count
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_a_id": str(self.snapshot_a_id),
            "snapshot_b_id": str(self.snapshot_b_id),
            "a_label": self.a_label,
            "b_label": self.b_label,
            "a_created_at": self.a_created_at.isoformat(),
            "b_created_at": self.b_created_at.isoformat(),
            "columns_added": list(self.columns_added),
            "columns_removed": list(self.columns_removed),
            "columns_changed": [c.to_dict() for c in self.columns_changed],
            "a_row_count": self.a_row_count,
            "b_row_count": self.b_row_count,
            "rows_added": self.rows_added,
            "rows_removed": self.rows_removed,
            "schema_hash_match": self.schema_hash_match,
            "is_identical": self.is_identical,
        }


# ── Errors ──────────────────────────────────────────────────────────────────


class SnapshotNavigatorError(Exception):
    """Base error for navigator helpers.

    Mirrors :class:`SnapshotError` from the service layer — each
    subclass carries a ``message_key`` so the router can localise the
    response without leaking internals.
    """

    http_status: int = 500
    message_key: str = "common.unknown_error"


class SnapshotsNotInSameProjectError(SnapshotNavigatorError):
    """Raised when the user asks to diff snapshots across projects."""

    http_status = 422
    message_key = "navigator.diff.cross_project"


class SnapshotForDiffNotFoundError(SnapshotNavigatorError):
    """One or both snapshot ids in a diff request did not resolve."""

    http_status = 404
    message_key = "snapshot.not_found"


# ── Pure helpers ────────────────────────────────────────────────────────────


_TIMELINE_DEFAULT_LIMIT = 50
_TIMELINE_MAX_LIMIT = 200


def list_snapshots_for_project(
    rows: list[Any],
    *,
    limit: int = _TIMELINE_DEFAULT_LIMIT,
    before: datetime | None = None,
    schema_hashes: dict[uuid.UUID, str] | None = None,
    completeness_scores: dict[uuid.UUID, float] | None = None,
) -> list[SnapshotMeta]:
    """Build the timeline from a pre-loaded list of ORM rows.

    Pure / side-effect free — the caller (router or test) is
    responsible for fetching the rows. We accept an in-memory list
    rather than an :class:`AsyncSession` so the function stays
    trivially testable.

    Parameters
    ----------
    rows
        Iterable of :class:`~app.modules.dashboards.models.Snapshot`
        rows. Order does not matter — we sort newest-first ourselves.
    limit
        Maximum number of timeline entries to return. Capped at 200.
    before
        Cursor timestamp. When set, only rows with
        ``created_at < before`` are returned. The frontend uses the
        oldest ``created_at`` it currently shows as the next cursor.
    schema_hashes
        Optional map of ``snapshot_id → schema_hash`` so the timeline
        can render an "identical schema" badge per row. The values
        come from manifests (cheap) or T07 integrity reports (also
        cheap, but server-side already). Missing entries surface as
        ``None`` in the output.
    completeness_scores
        Same idea, but for the integrity-overview score. ``None``
        means "not yet computed for this snapshot".
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    limit = min(limit, _TIMELINE_MAX_LIMIT)

    schema_hashes = schema_hashes or {}
    completeness_scores = completeness_scores or {}

    # Filter on the cursor first to keep the working set small.
    filtered: list[Any] = [
        r for r in rows
        if before is None or r.created_at < before
    ]
    # Newest-first.
    filtered.sort(key=lambda r: r.created_at, reverse=True)
    filtered = filtered[:limit]

    out: list[SnapshotMeta] = []
    for row in filtered:
        source_files = row.source_files_json or []
        out.append(
            SnapshotMeta(
                id=row.id,
                project_id=row.project_id,
                label=row.label,
                created_at=row.created_at,
                created_by_user_id=row.created_by_user_id,
                parent_snapshot_id=row.parent_snapshot_id,
                total_entities=int(row.total_entities or 0),
                total_categories=int(row.total_categories or 0),
                source_file_count=len(source_files),
                schema_hash=schema_hashes.get(row.id),
                completeness_score=completeness_scores.get(row.id),
            )
        )
    return out


def diff_two_snapshots(
    schema_a: SchemaSnapshot,
    schema_b: SchemaSnapshot,
    *,
    a_label: str,
    b_label: str,
    a_created_at: datetime,
    b_created_at: datetime,
) -> SnapshotDiff:
    """Compare two snapshot schemas and return the structural delta.

    The function is symmetric with respect to the labels (it does not
    re-order based on timestamps) — callers decide which snapshot is
    "before" by passing it as A. The frontend always passes the older
    timestamp as A so ``columns_added`` reads as a chronological diff.

    ``schema_hash_match`` is ``True`` only if both sides recorded a
    hash *and* the values agree — a missing hash on either side
    forces ``False`` so callers don't accidentally treat
    "no hash" as "matches".
    """
    a_cols = dict(schema_a.columns)
    b_cols = dict(schema_b.columns)
    a_names = set(a_cols)
    b_names = set(b_cols)

    columns_added = sorted(b_names - a_names)
    columns_removed = sorted(a_names - b_names)

    columns_changed: list[ColumnChange] = []
    for name in sorted(a_names & b_names):
        a_dtype = a_cols[name]
        b_dtype = b_cols[name]
        if a_dtype != b_dtype:
            columns_changed.append(
                ColumnChange(name=name, a_dtype=a_dtype, b_dtype=b_dtype)
            )

    delta = schema_b.row_count - schema_a.row_count
    rows_added = max(0, delta)
    rows_removed = max(0, -delta)

    schema_hash_match = bool(
        schema_a.schema_hash
        and schema_b.schema_hash
        and schema_a.schema_hash == schema_b.schema_hash
    )

    return SnapshotDiff(
        snapshot_a_id=schema_a.snapshot_id,
        snapshot_b_id=schema_b.snapshot_id,
        a_label=a_label,
        b_label=b_label,
        a_created_at=a_created_at,
        b_created_at=b_created_at,
        columns_added=columns_added,
        columns_removed=columns_removed,
        columns_changed=columns_changed,
        a_row_count=schema_a.row_count,
        b_row_count=schema_b.row_count,
        rows_added=rows_added,
        rows_removed=rows_removed,
        schema_hash_match=schema_hash_match,
    )


def schema_from_summary_stats(
    snapshot_id: uuid.UUID,
    *,
    summary_stats: dict[str, int] | None,
    total_entities: int,
    schema_hash: str | None = None,
) -> SchemaSnapshot:
    """Build a :class:`SchemaSnapshot` from the cheap row-side data.

    This path is the fallback for snapshots whose Parquet is no
    longer reachable. It treats the per-category counts as
    "categories present" — fine for the navigator UI, which only
    surfaces high-level structural movement. Dtype is set to
    ``"int64"`` for every entry; this means dtype mismatches will
    *not* be detected on the fallback path. The frontend tags the diff
    as ``"summary-only"`` so the user knows the comparison is shallow.
    """
    cols: dict[str, str] = {}
    for cat in summary_stats or {}:
        cols[str(cat)] = "int64"
    return SchemaSnapshot(
        snapshot_id=snapshot_id,
        columns=cols,
        row_count=int(total_entities or 0),
        schema_hash=schema_hash,
    )


__all__ = [
    "ColumnChange",
    "SchemaSnapshot",
    "SnapshotDiff",
    "SnapshotForDiffNotFoundError",
    "SnapshotMeta",
    "SnapshotNavigatorError",
    "SnapshotsNotInSameProjectError",
    "diff_two_snapshots",
    "list_snapshots_for_project",
    "schema_from_summary_stats",
]
