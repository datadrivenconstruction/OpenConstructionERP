"""T07 unit tests — Dataset Integrity Overview.

Pins the per-column heuristics in
:mod:`app.modules.dashboards.integrity` so future refactors don't
silently change which issues are surfaced. Each test exercises one
heuristic in isolation, then a final pair of tests cover the overall
report shape (completeness score, schema hash, all-clean snapshot).
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.modules.dashboards.integrity import (
    ColumnIntegrity,
    IntegrityReport,
    compute_integrity_report,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def healthy_df() -> pd.DataFrame:
    """A snapshot with no integrity issues — used as a baseline.

    Uses a 6-value categorical (above the low-cardinality threshold of
    5) and well-spread numerics so no heuristic fires.
    """
    return pd.DataFrame(
        {
            "category": [
                "wall",
                "door",
                "window",
                "floor",
                "roof",
                "beam",
                "wall",
                "door",
                "window",
                "floor",
                "roof",
                "beam",
                "wall",
                "door",
                "window",
            ],
            "thickness_mm": [
                100,
                120,
                150,
                180,
                200,
                220,
                240,
                260,
                280,
                300,
                320,
                340,
                360,
                380,
                400,
            ],
            "area_m2": [
                1.0,
                2.0,
                3.0,
                4.0,
                5.0,
                6.0,
                7.0,
                8.0,
                9.0,
                10.0,
                11.0,
                12.0,
                13.0,
                14.0,
                15.0,
            ],
        }
    )


# ── Per-column tests ───────────────────────────────────────────────────────


class TestEmptySnapshot:
    def test_empty_dataframe_returns_degenerate_report(self) -> None:
        report = compute_integrity_report(
            pd.DataFrame(),
            snapshot_id="snap-empty",
            project_id="proj-1",
        )
        assert isinstance(report, IntegrityReport)
        assert report.row_count == 0
        assert report.column_count == 0
        assert report.completeness_score == 1.0
        assert report.columns == []
        # schema_hash is still deterministic — empty hash for empty schema.
        assert isinstance(report.schema_hash, str)
        assert len(report.schema_hash) == 16

    def test_none_dataframe_returns_degenerate_report(self) -> None:
        report = compute_integrity_report(
            None,  # type: ignore[arg-type]
            snapshot_id="snap-none",
            project_id="proj-1",
        )
        assert report.row_count == 0
        assert report.column_count == 0


class TestAllNullColumn:
    def test_all_null_column_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "category": ["wall", "door", "window"],
                "phantom_field": [None, None, None],
            }
        )
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        phantom = next(c for c in report.columns if c.name == "phantom_field")
        assert "all_null" in phantom.issues
        assert phantom.null_count == 3
        assert phantom.null_pct == 1.0
        assert phantom.unique_count == 0
        assert phantom.completeness == 0.0
        # Sample values are empty for an all-null column.
        assert phantom.sample_values == []
        assert report.issue_summary.get("all_null", 0) == 1


class TestHighNullPct:
    def test_high_null_pct_flagged(self) -> None:
        # 7/10 null → 70% null, well above the 30% threshold.
        df = pd.DataFrame(
            {
                "sparse": [None, None, None, None, None, None, None, "a", "b", "c"],
            }
        )
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        col = report.columns[0]
        assert col.null_count == 7
        assert col.null_pct == pytest.approx(0.7, rel=1e-6)
        assert "high_null_pct" in col.issues
        assert "all_null" not in col.issues  # not entirely null


class TestConstantColumn:
    def test_constant_column_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "constant_col": ["a"] * 20,
                "varied_col": list(range(20)),
            }
        )
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        const_col = next(c for c in report.columns if c.name == "constant_col")
        assert "constant" in const_col.issues
        assert const_col.unique_count == 1


class TestDtypeMismatch:
    def test_string_column_with_numeric_values_is_flagged(self) -> None:
        # Object dtype, but every value parses as a number.
        df = pd.DataFrame(
            {
                "mostly_numbers": ["1", "2", "3.5", "4", "5", "6", "7", "8", "9", "10"],
            }
        )
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        col = report.columns[0]
        assert col.dtype.startswith("object") or col.dtype == "string"
        assert col.inferred_type == "numeric"
        assert "dtype_mismatch" in col.issues

    def test_clean_string_column_is_not_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "names": ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa"],
            }
        )
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        col = report.columns[0]
        assert col.inferred_type == "string"
        assert "dtype_mismatch" not in col.issues


class TestOutliers:
    def test_iqr_outliers_detected(self) -> None:
        # 19 normal-ish values plus a wild outlier at 10000.
        df = pd.DataFrame(
            {
                "thickness": [
                    100,
                    110,
                    120,
                    125,
                    130,
                    135,
                    140,
                    145,
                    150,
                    155,
                    160,
                    165,
                    170,
                    175,
                    180,
                    185,
                    190,
                    195,
                    200,
                    10000,
                ],
            }
        )
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        col = report.columns[0]
        assert col.inferred_type == "numeric"
        assert col.outlier_count is not None
        assert col.outlier_count >= 1
        assert "outliers_present" in col.issues

    def test_no_outliers_for_well_behaved_numeric(self) -> None:
        df = pd.DataFrame({"x": list(range(20))})
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        col = report.columns[0]
        assert col.outlier_count == 0
        assert "outliers_present" not in col.issues


class TestZeros:
    def test_high_zero_pct_flagged(self) -> None:
        # 8 zeros + 2 non-zeros → 80% zero, above the 50% threshold.
        df = pd.DataFrame({"price": [0.0] * 8 + [100.0, 200.0]})
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        col = report.columns[0]
        assert col.zero_pct == pytest.approx(0.8, rel=1e-6)
        assert "high_zero_pct" in col.issues


class TestLowCardinalityString:
    def test_low_cardinality_string_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "discipline": (["arch"] * 5 + ["struct"] * 5 + ["mep"] * 5),
            }
        )
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        col = report.columns[0]
        assert col.inferred_type == "string"
        assert col.unique_count == 3
        assert "low_cardinality_string" in col.issues

    def test_low_cardinality_below_min_rows_not_flagged(self) -> None:
        # Same shape but only 6 rows — below the 10-row floor.
        df = pd.DataFrame({"discipline": ["arch", "struct", "mep"] * 2})
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        col = report.columns[0]
        assert "low_cardinality_string" not in col.issues


class TestUuidLike:
    def test_uuid_column_flagged(self) -> None:
        import uuid

        df = pd.DataFrame(
            {
                "entity_guid": [str(uuid.uuid4()) for _ in range(20)],
            }
        )
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        col = report.columns[0]
        assert col.inferred_type == "string"
        assert "uuid_like" in col.issues


# ── Whole-report tests ─────────────────────────────────────────────────────


class TestOverallReport:
    def test_clean_snapshot_has_no_issues(self, healthy_df: pd.DataFrame) -> None:
        report = compute_integrity_report(
            healthy_df,
            snapshot_id="snap-1",
            project_id="proj-1",
        )
        assert report.snapshot_id == "snap-1"
        assert report.project_id == "proj-1"
        assert report.row_count == 15
        assert report.column_count == 3
        assert report.completeness_score == 1.0
        # Every column is fully-populated, varied, well-typed → empty
        # issue lists across the board.
        for col in report.columns:
            assert isinstance(col, ColumnIntegrity)
            assert col.completeness == 1.0
            assert col.null_count == 0
            assert col.issues == []
        assert report.issue_summary == {}

    def test_completeness_score_averages_across_columns(self) -> None:
        # col_a is fully populated (1.0), col_b is half-null (0.5).
        # Expected mean: 0.75.
        df = pd.DataFrame(
            {
                "col_a": list(range(10)),
                "col_b": [None, None, None, None, None, 6, 7, 8, 9, 10],
            }
        )
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        assert report.completeness_score == pytest.approx(0.75, rel=1e-6)

    def test_schema_hash_changes_with_dtype(self) -> None:
        df_a = pd.DataFrame({"x": [1, 2, 3]})
        df_b = pd.DataFrame({"x": ["1", "2", "3"]})
        hash_a = compute_integrity_report(
            df_a,
            snapshot_id="s",
            project_id="p",
        ).schema_hash
        hash_b = compute_integrity_report(
            df_b,
            snapshot_id="s",
            project_id="p",
        ).schema_hash
        assert hash_a != hash_b

    def test_schema_hash_stable_for_same_shape(self) -> None:
        df_a = pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]})
        df_b = pd.DataFrame({"x": [10, 20, 30], "y": ["d", "e", "f"]})
        hash_a = compute_integrity_report(
            df_a,
            snapshot_id="s",
            project_id="p",
        ).schema_hash
        hash_b = compute_integrity_report(
            df_b,
            snapshot_id="s",
            project_id="p",
        ).schema_hash
        # Same column names and dtypes — hash must agree even though
        # the values differ.
        assert hash_a == hash_b

    def test_sample_values_returns_top_5_by_frequency(self) -> None:
        # Heavy-tailed distribution: "wall" dominates.
        df = pd.DataFrame(
            {
                "category": (
                    ["wall"] * 10 + ["door"] * 5 + ["window"] * 3 + ["floor"] * 2 + ["roof"] * 1 + ["beam"] * 1
                ),
            }
        )
        report = compute_integrity_report(
            df,
            snapshot_id="s",
            project_id="p",
        )
        col = report.columns[0]
        # Top-5 only — "beam" is dropped.
        assert len(col.sample_values) == 5
        names = [s["value"] for s in col.sample_values]
        assert names[0] == "wall"
        assert col.sample_values[0]["count"] == 10
        assert "beam" not in names

    def test_to_dict_round_trips_safely(self, healthy_df: pd.DataFrame) -> None:
        report = compute_integrity_report(
            healthy_df,
            snapshot_id="snap-1",
            project_id="proj-1",
        )
        d = report.to_dict()
        assert d["snapshot_id"] == "snap-1"
        assert d["project_id"] == "proj-1"
        assert d["completeness_score"] == 1.0
        assert isinstance(d["columns"], list)
        assert isinstance(d["columns"][0], dict)
        assert "issues" in d["columns"][0]
