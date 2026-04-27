# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""T11 unit tests — Historical Snapshot Navigator.

Pins the pure helpers in
:mod:`app.modules.dashboards.snapshot_navigator`. Each test exercises
one branch in isolation:

* ``list_snapshots_for_project`` — newest-first ordering, ``before``
  cursor, ``limit`` cap, schema-hash overlay, completeness overlay.
* ``diff_two_snapshots`` — column adds / drops / dtype changes,
  row-count delta, identical-snapshot detection, schema-hash gating.
* ``schema_from_summary_stats`` — fallback path when parquet is
  unreachable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.dashboards.snapshot_navigator import (
    ColumnChange,
    SchemaSnapshot,
    SnapshotDiff,
    SnapshotMeta,
    diff_two_snapshots,
    list_snapshots_for_project,
    schema_from_summary_stats,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@dataclass
class _FakeSnapshotRow:
    """Stand-in for the ORM row — only the fields the navigator reads."""

    id: uuid.UUID
    project_id: uuid.UUID
    label: str
    created_at: datetime
    created_by_user_id: uuid.UUID
    parent_snapshot_id: uuid.UUID | None
    total_entities: int
    total_categories: int
    summary_stats: dict[str, int]
    source_files_json: list


def _make_row(
    *,
    label: str,
    created_at: datetime,
    project_id: uuid.UUID | None = None,
    parent: uuid.UUID | None = None,
    total_entities: int = 100,
    total_categories: int = 5,
    summary_stats: dict[str, int] | None = None,
    source_files: int = 1,
) -> _FakeSnapshotRow:
    return _FakeSnapshotRow(
        id=uuid.uuid4(),
        project_id=project_id or uuid.UUID("11111111-1111-1111-1111-111111111111"),
        label=label,
        created_at=created_at,
        created_by_user_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        parent_snapshot_id=parent,
        total_entities=total_entities,
        total_categories=total_categories,
        summary_stats=summary_stats or {"wall": 60, "door": 40},
        source_files_json=[{"id": str(uuid.uuid4())} for _ in range(source_files)],
    )


# ── Timeline tests ─────────────────────────────────────────────────────────


class TestListSnapshotsForProject:
    def test_orders_newest_first(self) -> None:
        base = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)
        rows = [
            _make_row(label="Older", created_at=base - timedelta(days=2)),
            _make_row(label="Newest", created_at=base),
            _make_row(label="Middle", created_at=base - timedelta(days=1)),
        ]
        out = list_snapshots_for_project(rows)
        assert [m.label for m in out] == ["Newest", "Middle", "Older"]

    def test_limit_caps_results(self) -> None:
        base = datetime(2026, 4, 27, tzinfo=UTC)
        rows = [
            _make_row(label=f"#{i}", created_at=base - timedelta(hours=i))
            for i in range(10)
        ]
        out = list_snapshots_for_project(rows, limit=3)
        assert len(out) == 3
        assert [m.label for m in out] == ["#0", "#1", "#2"]

    def test_before_cursor_filters_out_newer_rows(self) -> None:
        base = datetime(2026, 4, 27, tzinfo=UTC)
        rows = [
            _make_row(label="Newer", created_at=base + timedelta(hours=1)),
            _make_row(label="Cursor", created_at=base),
            _make_row(label="Older", created_at=base - timedelta(hours=1)),
        ]
        out = list_snapshots_for_project(rows, before=base)
        # Strictly less-than cursor — "Cursor" itself drops, "Newer"
        # is filtered out. Only "Older" remains.
        labels = [m.label for m in out]
        assert "Newer" not in labels
        assert "Cursor" not in labels
        assert "Older" in labels

    def test_invalid_limit_raises(self) -> None:
        with pytest.raises(ValueError):
            list_snapshots_for_project([], limit=0)
        with pytest.raises(ValueError):
            list_snapshots_for_project([], limit=-3)

    def test_overlay_schema_hashes_and_completeness(self) -> None:
        base = datetime(2026, 4, 27, tzinfo=UTC)
        row = _make_row(label="A", created_at=base)
        out = list_snapshots_for_project(
            [row],
            schema_hashes={row.id: "abc123def456"},
            completeness_scores={row.id: 0.92},
        )
        assert len(out) == 1
        assert out[0].schema_hash == "abc123def456"
        assert out[0].completeness_score == pytest.approx(0.92)

    def test_meta_includes_source_file_count(self) -> None:
        base = datetime(2026, 4, 27, tzinfo=UTC)
        row = _make_row(label="A", created_at=base, source_files=4)
        out = list_snapshots_for_project([row])
        assert out[0].source_file_count == 4

    def test_to_dict_round_trips(self) -> None:
        base = datetime(2026, 4, 27, tzinfo=UTC)
        row = _make_row(label="A", created_at=base)
        out = list_snapshots_for_project([row])
        d = out[0].to_dict()
        assert d["label"] == "A"
        assert d["total_entities"] == 100
        assert d["created_at"].startswith("2026-04-27")
        assert isinstance(d["id"], str)


# ── Diff tests ─────────────────────────────────────────────────────────────


class TestDiffTwoSnapshots:
    def test_detects_added_and_removed_columns(self) -> None:
        sa = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns={"category": "object", "thickness_mm": "float64"},
            row_count=100,
        )
        sb = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns={"category": "object", "fire_rating": "object"},
            row_count=100,
        )
        diff = diff_two_snapshots(
            sa, sb,
            a_label="Baseline",
            b_label="With fire-rating",
            a_created_at=datetime(2026, 4, 1, tzinfo=UTC),
            b_created_at=datetime(2026, 4, 27, tzinfo=UTC),
        )
        assert diff.columns_added == ["fire_rating"]
        assert diff.columns_removed == ["thickness_mm"]
        assert diff.columns_changed == []
        assert diff.is_identical is False

    def test_detects_dtype_change(self) -> None:
        common_id = uuid.uuid4()
        sa = SchemaSnapshot(
            snapshot_id=common_id,
            columns={"thickness_mm": "object"},  # was string
            row_count=10,
        )
        sb = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns={"thickness_mm": "float64"},  # now numeric
            row_count=10,
        )
        diff = diff_two_snapshots(
            sa, sb,
            a_label="Pre-clean",
            b_label="Post-clean",
            a_created_at=datetime(2026, 4, 1, tzinfo=UTC),
            b_created_at=datetime(2026, 4, 27, tzinfo=UTC),
        )
        assert diff.columns_added == []
        assert diff.columns_removed == []
        assert len(diff.columns_changed) == 1
        change = diff.columns_changed[0]
        assert isinstance(change, ColumnChange)
        assert change.name == "thickness_mm"
        assert change.a_dtype == "object"
        assert change.b_dtype == "float64"

    def test_no_overlap_diff(self) -> None:
        sa = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns={"a1": "int64", "a2": "int64"},
            row_count=5,
        )
        sb = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns={"b1": "object", "b2": "object", "b3": "object"},
            row_count=12,
        )
        diff = diff_two_snapshots(
            sa, sb,
            a_label="A",
            b_label="B",
            a_created_at=datetime(2026, 4, 1, tzinfo=UTC),
            b_created_at=datetime(2026, 4, 27, tzinfo=UTC),
        )
        assert sorted(diff.columns_added) == ["b1", "b2", "b3"]
        assert sorted(diff.columns_removed) == ["a1", "a2"]
        assert diff.columns_changed == []
        # Row delta is positive → ``rows_added`` populated, the inverse stays zero.
        assert diff.rows_added == 7
        assert diff.rows_removed == 0

    def test_identical_snapshot_diff(self) -> None:
        cols = {"category": "object", "thickness": "float64"}
        sa = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns=dict(cols),
            row_count=42,
            schema_hash="hash-A",
        )
        sb = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns=dict(cols),
            row_count=42,
            schema_hash="hash-A",
        )
        diff = diff_two_snapshots(
            sa, sb,
            a_label="Day 1",
            b_label="Day 2",
            a_created_at=datetime(2026, 4, 1, tzinfo=UTC),
            b_created_at=datetime(2026, 4, 2, tzinfo=UTC),
        )
        assert diff.columns_added == []
        assert diff.columns_removed == []
        assert diff.columns_changed == []
        assert diff.rows_added == 0
        assert diff.rows_removed == 0
        assert diff.is_identical is True
        assert diff.schema_hash_match is True

    def test_row_count_decrease_populates_rows_removed(self) -> None:
        sa = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns={"x": "int64"},
            row_count=200,
        )
        sb = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns={"x": "int64"},
            row_count=180,
        )
        diff = diff_two_snapshots(
            sa, sb,
            a_label="Before purge",
            b_label="After purge",
            a_created_at=datetime(2026, 4, 1, tzinfo=UTC),
            b_created_at=datetime(2026, 4, 27, tzinfo=UTC),
        )
        assert diff.rows_removed == 20
        assert diff.rows_added == 0
        # Schema agrees, but no hashes were recorded.
        assert diff.columns_changed == []
        assert diff.schema_hash_match is False

    def test_schema_hash_match_requires_both_sides(self) -> None:
        cols = {"x": "int64"}
        sa = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns=dict(cols),
            row_count=10,
            schema_hash="abc",
        )
        sb = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns=dict(cols),
            row_count=10,
            schema_hash=None,  # missing on B
        )
        diff = diff_two_snapshots(
            sa, sb,
            a_label="A",
            b_label="B",
            a_created_at=datetime(2026, 4, 1, tzinfo=UTC),
            b_created_at=datetime(2026, 4, 27, tzinfo=UTC),
        )
        # Even though the columns + rows agree, missing hash on B
        # prevents the strict "matches" claim.
        assert diff.is_identical is True
        assert diff.schema_hash_match is False

    def test_diff_to_dict_shape(self) -> None:
        sa = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns={"x": "int64"},
            row_count=10,
        )
        sb = SchemaSnapshot(
            snapshot_id=uuid.uuid4(),
            columns={"y": "int64"},
            row_count=15,
        )
        diff = diff_two_snapshots(
            sa, sb,
            a_label="A",
            b_label="B",
            a_created_at=datetime(2026, 4, 1, tzinfo=UTC),
            b_created_at=datetime(2026, 4, 27, tzinfo=UTC),
        )
        d = diff.to_dict()
        assert d["columns_added"] == ["y"]
        assert d["columns_removed"] == ["x"]
        assert d["rows_added"] == 5
        assert d["is_identical"] is False
        assert isinstance(d["snapshot_a_id"], str)


# ── Fallback path ──────────────────────────────────────────────────────────


class TestSchemaFromSummaryStats:
    def test_fallback_builds_int_columns_from_categories(self) -> None:
        snapshot_id = uuid.uuid4()
        schema = schema_from_summary_stats(
            snapshot_id,
            summary_stats={"wall": 60, "door": 40},
            total_entities=100,
        )
        assert isinstance(schema, SchemaSnapshot)
        assert schema.snapshot_id == snapshot_id
        assert set(schema.columns) == {"wall", "door"}
        # Every fallback entry stamps the same dtype — diff against
        # a parquet-side schema for that snapshot would surface this
        # as a dtype change, which is the correct UX signal.
        assert all(v == "int64" for v in schema.columns.values())
        assert schema.row_count == 100

    def test_fallback_handles_empty_summary(self) -> None:
        schema = schema_from_summary_stats(
            uuid.uuid4(),
            summary_stats=None,
            total_entities=0,
        )
        assert schema.columns == {}
        assert schema.row_count == 0


# ── SnapshotMeta direct test ────────────────────────────────────────────────


class TestSnapshotMeta:
    def test_meta_dataclass_round_trips(self) -> None:
        meta = SnapshotMeta(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            label="L",
            created_at=datetime(2026, 4, 27, tzinfo=UTC),
            created_by_user_id=uuid.uuid4(),
            parent_snapshot_id=None,
            total_entities=10,
            total_categories=2,
            source_file_count=1,
            schema_hash="x",
            completeness_score=0.5,
        )
        d = meta.to_dict()
        assert d["label"] == "L"
        assert d["schema_hash"] == "x"
        assert d["completeness_score"] == 0.5
        assert d["parent_snapshot_id"] is None


# ── SnapshotDiff dataclass invariant ───────────────────────────────────────


class TestSnapshotDiffInvariants:
    def test_rows_added_and_removed_are_mutually_exclusive(self) -> None:
        # When B grew, only ``rows_added`` should be > 0; when B shrank,
        # only ``rows_removed`` should be. This is a property test in
        # spirit — exercise both sides explicitly.
        sa = SchemaSnapshot(
            snapshot_id=uuid.uuid4(), columns={"x": "int64"}, row_count=10,
        )
        sb_grown = SchemaSnapshot(
            snapshot_id=uuid.uuid4(), columns={"x": "int64"}, row_count=15,
        )
        sb_shrunk = SchemaSnapshot(
            snapshot_id=uuid.uuid4(), columns={"x": "int64"}, row_count=5,
        )
        d_grown = diff_two_snapshots(
            sa, sb_grown,
            a_label="A", b_label="B",
            a_created_at=datetime(2026, 4, 1, tzinfo=UTC),
            b_created_at=datetime(2026, 4, 2, tzinfo=UTC),
        )
        d_shrunk = diff_two_snapshots(
            sa, sb_shrunk,
            a_label="A", b_label="B",
            a_created_at=datetime(2026, 4, 1, tzinfo=UTC),
            b_created_at=datetime(2026, 4, 2, tzinfo=UTC),
        )
        assert (d_grown.rows_added, d_grown.rows_removed) == (5, 0)
        assert (d_shrunk.rows_added, d_shrunk.rows_removed) == (0, 5)

    def test_isinstance_diff(self) -> None:
        sa = SchemaSnapshot(
            snapshot_id=uuid.uuid4(), columns={"x": "int64"}, row_count=10,
        )
        sb = SchemaSnapshot(
            snapshot_id=uuid.uuid4(), columns={"x": "int64"}, row_count=10,
        )
        diff = diff_two_snapshots(
            sa, sb,
            a_label="A", b_label="B",
            a_created_at=datetime(2026, 4, 1, tzinfo=UTC),
            b_created_at=datetime(2026, 4, 2, tzinfo=UTC),
        )
        assert isinstance(diff, SnapshotDiff)
