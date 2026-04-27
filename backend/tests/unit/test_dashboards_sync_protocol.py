# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""T09 unit tests — Preset → Snapshot Sync Protocol.

Pure-Python coverage of the probe + auto-heal pipeline. No DB, no
DuckDB — every test feeds hand-crafted ``SnapshotMeta`` objects into
:class:`PresetSyncProbe` and asserts the resulting :class:`SyncReport`.
"""

from __future__ import annotations

import pytest

from app.modules.dashboards.sync_protocol import (
    PresetSyncProbe,
    SnapshotMeta,
    SyncReport,
    auto_heal,
    diff_snapshot_meta,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def probe() -> PresetSyncProbe:
    return PresetSyncProbe()


@pytest.fixture
def baseline_meta() -> SnapshotMeta:
    return SnapshotMeta(
        columns=("category", "material", "qty", "level"),
        dtypes={
            "category": "string",
            "material": "string",
            "qty": "numeric",
            "level": "string",
        },
        value_sets={
            "category": frozenset({"wall", "door", "window"}),
            "material": frozenset({"concrete", "steel", "wood"}),
            "level": frozenset({"L01", "L02", "L03"}),
        },
    )


# ── 1: in-sync (no-op) ─────────────────────────────────────────────────────


class TestInSync:
    def test_empty_config_is_in_sync(
        self, probe: PresetSyncProbe, baseline_meta: SnapshotMeta,
    ) -> None:
        report = probe.run({}, baseline_meta, preset_id="p-1")
        assert report.is_in_sync is True
        assert report.status == "synced"
        assert report.all_issues == []

    def test_matching_columns_no_issues(
        self, probe: PresetSyncProbe, baseline_meta: SnapshotMeta,
    ) -> None:
        config = {
            "snapshot_id": "snap-A",
            "columns": ["category", "qty"],
            "filters": {"category": ["wall", "door"]},
        }
        report = probe.run(config, baseline_meta, preset_id="p-1")
        assert report.is_in_sync
        assert report.status == "synced"


# ── 2: column rename detection ─────────────────────────────────────────────


class TestColumnRenames:
    def test_synonym_rename_qty_to_quantity(
        self, probe: PresetSyncProbe,
    ) -> None:
        old = SnapshotMeta(
            columns=("category", "qty"),
            dtypes={"category": "string", "qty": "numeric"},
        )
        new = SnapshotMeta(
            columns=("category", "quantity"),
            dtypes={"category": "string", "quantity": "numeric"},
        )
        config = {
            "snapshot_meta": {
                "columns": list(old.columns),
                "dtypes": dict(old.dtypes),
            },
            "columns": ["category", "qty"],
        }
        report = probe.run(config, new, preset_id="p-1")
        assert len(report.column_renames) == 1
        rename = report.column_renames[0]
        assert rename.column == "qty"
        assert rename.new_column == "quantity"
        assert rename.suggested_fix == "auto_rename"
        assert rename.severity == "warning"
        # No duplicate "dropped column" issue when a rename was matched.
        assert report.dropped_columns == []

    def test_case_insensitive_rename(self, probe: PresetSyncProbe) -> None:
        """Snapshot rebuilt with canonicalised column casing."""
        old = SnapshotMeta(
            columns=("Category",),
            dtypes={"Category": "string"},
        )
        new = SnapshotMeta(
            columns=("category",),
            dtypes={"category": "string"},
        )
        config = {
            "snapshot_meta": {
                "columns": ["Category"],
                "dtypes": {"Category": "string"},
            },
            "columns": ["Category"],
        }
        report = probe.run(config, new, preset_id="p-2")
        assert len(report.column_renames) == 1
        assert report.column_renames[0].new_column == "category"


# ── 3: dropped column detection ────────────────────────────────────────────


class TestDroppedColumns:
    def test_unrelated_drop_is_manual_error(
        self, probe: PresetSyncProbe, baseline_meta: SnapshotMeta,
    ) -> None:
        config = {
            "columns": ["category", "fire_rating"],
        }
        report = probe.run(config, baseline_meta, preset_id="p-3")
        assert len(report.dropped_columns) == 1
        issue = report.dropped_columns[0]
        assert issue.column == "fire_rating"
        assert issue.severity == "error"
        assert issue.suggested_fix == "manual"

    def test_chart_axis_reference_surfaces_drop(
        self, probe: PresetSyncProbe, baseline_meta: SnapshotMeta,
    ) -> None:
        """Charts that pin x_field/y_field independently should still
        show up in the dropped-columns set."""
        config = {
            "charts": [
                {"x_field": "level", "y_field": "ghost_metric"},
            ],
        }
        report = probe.run(config, baseline_meta, preset_id="p-4")
        kinds = {i.column for i in report.dropped_columns}
        assert "ghost_metric" in kinds


# ── 4: dropped filter values ───────────────────────────────────────────────


class TestDroppedFilterValues:
    def test_partial_drop_within_present_column(
        self, probe: PresetSyncProbe, baseline_meta: SnapshotMeta,
    ) -> None:
        config = {
            "filters": {
                "material": ["concrete", "asbestos", "steel"],
            },
        }
        report = probe.run(config, baseline_meta, preset_id="p-5")
        assert len(report.dropped_filter_values) == 1
        issue = report.dropped_filter_values[0]
        assert issue.column == "material"
        assert "asbestos" in issue.dropped_values
        # Severity: warning, suggested fix: drop_filter (auto-applicable).
        assert issue.severity == "warning"
        assert issue.suggested_fix == "drop_filter"

    def test_no_drop_when_value_set_unknown(
        self, probe: PresetSyncProbe,
    ) -> None:
        """If snapshot meta has the column but no value_set, the probe
        skips the drop check rather than guessing."""
        meta = SnapshotMeta(
            columns=("category",),
            dtypes={"category": "string"},
            value_sets={},
        )
        config = {"filters": {"category": ["wall", "ghost"]}}
        report = probe.run(config, meta, preset_id="p-6")
        assert report.dropped_filter_values == []


# ── 5: dtype change ────────────────────────────────────────────────────────


class TestDtypeChange:
    def test_within_family_is_warning(
        self, probe: PresetSyncProbe,
    ) -> None:
        old = SnapshotMeta(
            columns=("qty",),
            dtypes={"qty": "int"},
        )
        new = SnapshotMeta(
            columns=("qty",),
            dtypes={"qty": "float"},
        )
        config = {
            "snapshot_meta": {"columns": ["qty"], "dtypes": {"qty": "int"}},
            "columns": ["qty"],
        }
        report = probe.run(config, new, preset_id="p-7")
        assert len(report.dtype_changes) == 1
        issue = report.dtype_changes[0]
        assert issue.severity == "warning"
        assert issue.old_dtype == "int"
        assert issue.new_dtype == "float"

    def test_cross_family_is_error(self, probe: PresetSyncProbe) -> None:
        old = SnapshotMeta(
            columns=("qty",),
            dtypes={"qty": "numeric"},
        )
        new = SnapshotMeta(
            columns=("qty",),
            dtypes={"qty": "string"},
        )
        config = {
            "snapshot_meta": {"columns": ["qty"], "dtypes": {"qty": "numeric"}},
            "columns": ["qty"],
        }
        report = probe.run(config, new, preset_id="p-8")
        assert len(report.dtype_changes) == 1
        assert report.dtype_changes[0].severity == "error"
        assert report.dtype_changes[0].suggested_fix == "manual"


# ── 6: status classification ───────────────────────────────────────────────


class TestStatus:
    def test_status_synced_when_no_issues(
        self, probe: PresetSyncProbe, baseline_meta: SnapshotMeta,
    ) -> None:
        report = probe.run({"columns": ["category"]}, baseline_meta, preset_id="p")
        assert report.status == "synced"

    def test_status_needs_review_when_manual_present(
        self, probe: PresetSyncProbe, baseline_meta: SnapshotMeta,
    ) -> None:
        config = {"columns": ["unknown_col"]}
        report = probe.run(config, baseline_meta, preset_id="p")
        assert report.status == "needs_review"

    def test_status_stale_when_only_auto_fixes(
        self, probe: PresetSyncProbe,
    ) -> None:
        old = SnapshotMeta(columns=("qty",), dtypes={"qty": "numeric"})
        new = SnapshotMeta(
            columns=("quantity",),
            dtypes={"quantity": "numeric"},
        )
        config = {
            "snapshot_meta": {"columns": ["qty"], "dtypes": {"qty": "numeric"}},
            "columns": ["qty"],
        }
        report = probe.run(config, new, preset_id="p")
        # Only an auto_rename — auto-healable.
        assert report.status == "stale"


# ── 7: auto_heal ───────────────────────────────────────────────────────────


class TestAutoHeal:
    def test_heal_applies_rename(self) -> None:
        config = {
            "snapshot_meta": {"columns": ["qty"], "dtypes": {"qty": "numeric"}},
            "columns": ["qty", "category"],
            "charts": [{"x_field": "category", "y_field": "qty"}],
            "filters": {"qty": ["1", "2"]},
        }
        new_meta = SnapshotMeta(
            columns=("category", "quantity"),
            dtypes={"category": "string", "quantity": "numeric"},
        )
        probe = PresetSyncProbe()
        report = probe.run(config, new_meta, preset_id="p")
        patched = auto_heal(config, report)
        assert "qty" not in patched["columns"]
        assert "quantity" in patched["columns"]
        assert patched["charts"][0]["y_field"] == "quantity"
        assert "quantity" in patched["filters"]
        assert "qty" not in patched["filters"]

    def test_heal_drops_missing_filter_values(self) -> None:
        config = {
            "filters": {"category": ["wall", "ghost"]},
        }
        meta = SnapshotMeta(
            columns=("category",),
            dtypes={"category": "string"},
            value_sets={"category": frozenset({"wall"})},
        )
        probe = PresetSyncProbe()
        report = probe.run(config, meta, preset_id="p")
        patched = auto_heal(config, report)
        assert patched["filters"]["category"] == ["wall"]

    def test_heal_leaves_manual_issues_alone(self) -> None:
        config = {"columns": ["unknown_col", "category"]}
        meta = SnapshotMeta(
            columns=("category",),
            dtypes={"category": "string"},
        )
        probe = PresetSyncProbe()
        report = probe.run(config, meta, preset_id="p")
        patched = auto_heal(config, report)
        # auto_heal is *additive only* for safe fixes — the unknown
        # column stays in the patched config so the user can see it
        # while reviewing the manual issue.
        assert "unknown_col" in patched["columns"]


# ── 8: diff_snapshot_meta ──────────────────────────────────────────────────


class TestDiff:
    def test_diff_lists_added_removed_dtype_changes(self) -> None:
        old = SnapshotMeta(
            columns=("a", "b", "c"),
            dtypes={"a": "numeric", "b": "string", "c": "string"},
        )
        new = SnapshotMeta(
            columns=("a", "c", "d"),
            dtypes={"a": "string", "c": "string", "d": "numeric"},
        )
        diff = diff_snapshot_meta(old, new)
        assert diff["added"] == ["d"]
        assert diff["removed"] == ["b"]
        assert diff["dtype_changes"] == [("a", "numeric", "string")]

    def test_diff_no_changes_returns_empty(self) -> None:
        meta = SnapshotMeta(
            columns=("x",),
            dtypes={"x": "string"},
        )
        diff = diff_snapshot_meta(meta, meta)
        assert diff == {"added": [], "removed": [], "dtype_changes": []}


# ── 9: report serialisation ────────────────────────────────────────────────


class TestSerialisation:
    def test_report_to_dict_round_trips_keys(
        self, probe: PresetSyncProbe, baseline_meta: SnapshotMeta,
    ) -> None:
        config = {
            "filters": {"material": ["asbestos", "concrete"]},
            "columns": ["unknown"],
        }
        report = probe.run(config, baseline_meta, preset_id="p")
        d = report.to_dict()
        assert d["preset_id"] == "p"
        assert "status" in d
        assert "is_in_sync" in d
        assert isinstance(d["dropped_columns"], list)
        assert isinstance(d["dropped_filter_values"], list)


# ── 10: edge cases ─────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_filter_with_empty_list_no_issue(
        self, probe: PresetSyncProbe, baseline_meta: SnapshotMeta,
    ) -> None:
        """Empty filter list = 'no filter' — should not produce a
        dropped-value issue."""
        config = {"filters": {"material": []}}
        report = probe.run(config, baseline_meta, preset_id="p")
        assert report.dropped_filter_values == []

    def test_malformed_snapshot_meta_treated_as_absent(
        self, probe: PresetSyncProbe, baseline_meta: SnapshotMeta,
    ) -> None:
        config = {"snapshot_meta": "not-a-dict", "columns": ["category"]}
        # Malformed meta means we fall through to the coarser check.
        report = probe.run(config, baseline_meta, preset_id="p")
        assert report.is_in_sync

    def test_no_rename_when_two_candidates(
        self, probe: PresetSyncProbe,
    ) -> None:
        """Synonym ambiguity → fall back to manual."""
        old = SnapshotMeta(
            columns=("qty",),
            dtypes={"qty": "numeric"},
        )
        new = SnapshotMeta(
            columns=("quantity_a", "quantity_b"),
            dtypes={"quantity_a": "numeric", "quantity_b": "numeric"},
        )
        config = {
            "snapshot_meta": {"columns": ["qty"], "dtypes": {"qty": "numeric"}},
            "columns": ["qty"],
        }
        report = probe.run(config, new, preset_id="p")
        assert report.column_renames == []
        assert len(report.dropped_columns) == 1
        assert report.dropped_columns[0].suggested_fix == "manual"


# ── 11: report covers integration with all-issues view ─────────────────────


def test_combined_report_aggregates_all_issue_kinds(
    probe: PresetSyncProbe,
) -> None:
    """One config that triggers a rename, a drop, a missing filter
    value, and a dtype change in a single probe run."""
    old = SnapshotMeta(
        columns=("qty", "ghost", "level"),
        dtypes={"qty": "numeric", "ghost": "string", "level": "string"},
    )
    new = SnapshotMeta(
        columns=("quantity", "level"),
        dtypes={"quantity": "string", "level": "string"},
        value_sets={"level": frozenset({"L01"})},
    )
    config = {
        "snapshot_meta": {
            "columns": list(old.columns),
            "dtypes": dict(old.dtypes),
        },
        "columns": ["qty", "ghost", "level"],
        "filters": {"level": ["L01", "L99"]},
    }
    report = probe.run(config, new, preset_id="p")
    # Renamed: qty → quantity (synonym, dtype mismatch though).
    # qty's dtype shifted to string, so the rename heuristic that
    # requires same-family dtype rejects it. Then qty becomes a
    # dropped_column, not a rename.
    rename_cols = {i.column for i in report.column_renames}
    drop_cols = {i.column for i in report.dropped_columns}
    drop_filter_cols = {i.column for i in report.dropped_filter_values}
    assert "ghost" in drop_cols
    assert "level" in drop_filter_cols
    # all_issues aggregator works.
    assert len(report.all_issues) == (
        len(report.column_renames)
        + len(report.dropped_columns)
        + len(report.dropped_filter_values)
        + len(report.dtype_changes)
    )


# ── 12: SyncReport convenience properties ──────────────────────────────────


def test_report_status_in_sync_when_empty() -> None:
    report = SyncReport(preset_id="p", snapshot_id=None)
    assert report.is_in_sync is True
    assert report.status == "synced"


def test_load_current_meta_handles_pool_failure_gracefully() -> None:
    """If the pool raises, we get an empty SnapshotMeta — never an
    exception bubbling up to the endpoint."""
    import asyncio

    from app.modules.dashboards.sync_protocol import load_current_meta

    class _BoomPool:
        async def execute(self, *args, **kwargs):  # noqa: ARG002
            raise RuntimeError("snapshot deleted")

    meta = asyncio.run(
        load_current_meta(
            pool=_BoomPool(),
            snapshot_id="missing",
            project_id="p",
        ),
    )
    assert meta.columns == ()
    assert meta.dtypes == {}
