"""T02 unit tests — Quick-Insight Panel auto-chart heuristics.

Covers the pure-function surface of
:mod:`app.modules.dashboards.insights`. The router glue is exercised
indirectly via the existing snapshot fixtures; these tests pin the
heuristic decisions so a future refactor doesn't silently change which
charts users see.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from app.modules.dashboards.insights import (
    InsightChart,
    generate_quick_insights,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def numeric_only_df() -> pd.DataFrame:
    """A snapshot with only numeric columns (≥10 distinct values each)."""
    return pd.DataFrame(
        {
            "thickness_mm": [50, 100, 150, 200, 240, 280, 300, 350, 400, 450, 500] * 3,
            "height_m": [2.5, 2.7, 2.8, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0, 4.5, 5.0] * 3,
        }
    )


@pytest.fixture
def numeric_x_categorical_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "category": (["wall"] * 20) + (["door"] * 15) + (["window"] * 10),
            "area_m2": (
                # walls cluster around 25, doors around 2, windows around 1.5
                [22.0, 24.0, 25.0, 26.0, 28.0] * 4
                + [1.8, 2.0, 2.1, 2.2, 2.3] * 3
                + [1.4, 1.5, 1.6, 1.7, 1.8] * 2
            ),
        }
    )


@pytest.fixture
def datetime_x_numeric_df() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=24, freq="D")
    return pd.DataFrame(
        {
            "created_at": dates,
            "elements_added": list(range(1, 25)),
        }
    )


@pytest.fixture
def correlated_numerics_df() -> pd.DataFrame:
    # area = thickness * length-ish — strong linear correlation.
    rows = []
    for i in range(40):
        thickness = 100 + i * 10  # 100..490
        length = 1000 + i * 50  # 1000..2950
        # add a tiny non-linearity so r < 1 but still > 0.5
        area = thickness * length / 1000 + (i % 5) * 2
        rows.append({"thickness": thickness, "length": length, "area": area})
    return pd.DataFrame(rows)


@pytest.fixture
def all_null_column_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "category": ["wall"] * 5 + ["door"] * 5,
            "phantom_field": [None] * 10,
            "thickness_mm": [100, 150, 200, 240, 280, 300, 350, 400, 450, 500],
        }
    )


@pytest.fixture
def low_cardinality_categorical_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "discipline": (
                ["architecture"] * 10
                + ["structure"] * 6
                + ["mep"] * 4
            ),
            "thickness_mm": list(range(20)) * 1,
        }
    )


@pytest.fixture
def uuid_column_df() -> pd.DataFrame:
    """A column whose values look like UUIDs — must be skipped."""
    import uuid

    return pd.DataFrame(
        {
            "entity_guid": [str(uuid.uuid4()) for _ in range(20)],
            "category": ["wall"] * 10 + ["door"] * 10,
            "thickness_mm": list(range(20)),
        }
    )


# ── Heuristic-by-heuristic ────────────────────────────────────────────────


class TestNumericOnly:
    def test_numeric_only_yields_at_least_one_histogram(
        self, numeric_only_df: pd.DataFrame,
    ) -> None:
        charts = generate_quick_insights(numeric_only_df, limit=6)
        types = {c.chart_type for c in charts}
        assert "histogram" in types
        # At least one histogram per usable numeric column survives the
        # diversity step when there's nothing to compete with it.
        histograms = [c for c in charts if c.chart_type == "histogram"]
        assert len(histograms) >= 1

    def test_histogram_data_shape(self, numeric_only_df: pd.DataFrame) -> None:
        charts = generate_quick_insights(numeric_only_df, limit=6)
        h = next(c for c in charts if c.chart_type == "histogram")
        assert h.x_field == "label"
        assert h.y_field == "count"
        assert h.agg_fn == "count"
        assert len(h.data) >= 5
        assert all("bin_start" in d and "bin_end" in d for d in h.data)


class TestNumericXCategorical:
    def test_yields_bar_chart(self, numeric_x_categorical_df: pd.DataFrame) -> None:
        charts = generate_quick_insights(numeric_x_categorical_df, limit=6)
        bars = [c for c in charts if c.chart_type == "bar"]
        assert bars, "expected at least one bar chart for numeric x categorical"
        bar = bars[0]
        assert bar.agg_fn == "mean"
        assert bar.x_field == "category"
        assert bar.y_field == "area_m2"
        names = {row["category"] for row in bar.data}
        assert names <= {"wall", "door", "window"}

    def test_bar_chart_uses_top_k_categories(self) -> None:
        # 12 distinct categories — bar chart caps at top 10 by frequency.
        df = pd.DataFrame(
            {
                "category": [f"cat_{i % 12}" for i in range(120)],
                "value": [float(i) for i in range(120)],
            }
        )
        charts = generate_quick_insights(df, limit=12)
        bars = [c for c in charts if c.chart_type == "bar"]
        assert bars
        for bar in bars:
            assert len(bar.data) <= 10


class TestDatetimeXNumeric:
    def test_yields_line_chart(self, datetime_x_numeric_df: pd.DataFrame) -> None:
        charts = generate_quick_insights(datetime_x_numeric_df, limit=6)
        lines = [c for c in charts if c.chart_type == "line"]
        assert lines, "expected at least one line chart for datetime x numeric"
        line = lines[0]
        assert line.agg_fn == "mean"
        assert line.x_field == "created_at"
        assert line.y_field == "elements_added"
        assert len(line.data) >= 3


class TestCorrelatedNumerics:
    def test_yields_scatter(self, correlated_numerics_df: pd.DataFrame) -> None:
        charts = generate_quick_insights(correlated_numerics_df, limit=6)
        scatters = [c for c in charts if c.chart_type == "scatter"]
        assert scatters, "expected at least one scatter for correlated numerics"
        s = scatters[0]
        assert s.agg_fn is None
        assert s.x_field in {"thickness", "length", "area"}
        assert s.y_field in {"thickness", "length", "area"}
        # Pearson r above the threshold.
        r = abs(s.metadata.get("pearson_r", 0))
        assert r >= 0.5

    def test_uncorrelated_numerics_no_scatter(self) -> None:
        # Two independent random walks with low correlation — the
        # heuristic must NOT emit a scatter card.
        import numpy as np

        rng = np.random.default_rng(42)
        df = pd.DataFrame(
            {
                "x": rng.normal(size=200),
                "y": rng.normal(size=200),
            }
        )
        charts = generate_quick_insights(df, limit=8)
        scatters = [c for c in charts if c.chart_type == "scatter"]
        assert not scatters, "uncorrelated numerics must not emit scatter"


class TestNullAndPKExclusion:
    def test_all_null_column_excluded(self, all_null_column_df: pd.DataFrame) -> None:
        charts = generate_quick_insights(all_null_column_df, limit=12)
        # No chart's metadata should reference the phantom field.
        for c in charts:
            assert "phantom_field" not in {c.x_field, c.y_field}
            for v in c.metadata.values():
                assert v != "phantom_field"

    def test_uuid_column_excluded(self, uuid_column_df: pd.DataFrame) -> None:
        charts = generate_quick_insights(uuid_column_df, limit=12)
        for c in charts:
            assert "entity_guid" not in {c.x_field, c.y_field}

    def test_pk_named_column_excluded(self) -> None:
        df = pd.DataFrame(
            {
                "id": list(range(50)),
                "source_file_id": ["abc"] * 25 + ["def"] * 25,
                "thickness_mm": list(range(50)),
            }
        )
        charts = generate_quick_insights(df, limit=8)
        for c in charts:
            assert c.x_field not in {"id", "source_file_id"}
            assert c.y_field not in {"id", "source_file_id"}


class TestLowCardinalityDonut:
    def test_yields_donut(
        self, low_cardinality_categorical_df: pd.DataFrame,
    ) -> None:
        charts = generate_quick_insights(low_cardinality_categorical_df, limit=6)
        donuts = [c for c in charts if c.chart_type == "donut"]
        assert donuts, "expected at least one donut for low-cardinality cat"
        donut = donuts[0]
        assert donut.agg_fn == "count"
        names = {row["name"] for row in donut.data}
        assert names == {"architecture", "structure", "mep"}
        # Fractions add up to ~1.0.
        total = sum(row["fraction"] for row in donut.data)
        assert math.isclose(total, 1.0, abs_tol=0.01)


class TestRankingAndDiversity:
    def test_returns_at_most_limit(self) -> None:
        df = pd.DataFrame(
            {
                f"num_{i}": list(range(50))
                for i in range(8)
            }
        )
        charts = generate_quick_insights(df, limit=4)
        assert len(charts) <= 4

    def test_diversity_spreads_chart_types(self) -> None:
        # A DataFrame with multiple usable numeric / categorical / dt
        # columns should yield more than one chart_type in the top-6.
        df = pd.DataFrame(
            {
                "category": (["wall"] * 20 + ["door"] * 15 + ["window"] * 10) * 1,
                "discipline": (
                    ["arch"] * 18 + ["mep"] * 15 + ["struct"] * 12
                ),
                "thickness_mm": list(range(45)),
                "height_m": [1.5 + i * 0.05 for i in range(45)],
                "created_at": pd.date_range("2025-01-01", periods=45, freq="D"),
            }
        )
        charts = generate_quick_insights(df, limit=6)
        types = {c.chart_type for c in charts}
        assert len(types) >= 2

    def test_empty_df_returns_empty(self) -> None:
        assert generate_quick_insights(pd.DataFrame(), limit=4) == []

    def test_single_value_column_excluded(self) -> None:
        df = pd.DataFrame(
            {
                "constant": ["x"] * 50,
                "thickness_mm": list(range(50)),
            }
        )
        charts = generate_quick_insights(df, limit=4)
        for c in charts:
            assert c.x_field != "constant"
            assert c.y_field != "constant"


class TestInsightChartSerialisation:
    def test_to_dict_round_trip(self) -> None:
        chart = InsightChart(
            chart_type="histogram",
            title="x",
            data=[{"label": "a", "count": 1}],
            x_field="label",
            y_field="count",
            agg_fn="count",
            interestingness=1.234567,
            metadata={"column": "x"},
        )
        d = chart.to_dict()
        assert d["chart_type"] == "histogram"
        assert d["interestingness"] == 1.2346
        assert d["metadata"] == {"column": "x"}
