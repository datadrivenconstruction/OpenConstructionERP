# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quick-Insight Panel — auto-chart heuristics (T02).

Given a snapshot's tabular data (entities + flattened attributes), produce
a small bundle of "interesting" charts using rule-based heuristics. No
ML — the goal is "show me something useful in <500ms" rather than
optimal chart selection.

Heuristic catalogue
-------------------
1. Numeric column with ≥10 distinct values  →  histogram (sqrt(n) bins).
2. Numeric × categorical (cat. cardinality 2..30, num. distinct ≥5)
                                            →  bar of mean(num) by cat (top-10 by frequency).
3. Datetime + numeric                       →  line over time (resampled).
4. Two numerics with |Pearson r| > 0.5      →  scatter (sample-capped).
5. Categorical with cardinality 2..8        →  donut/pie of value frequencies.

Skipped automatically:
* Columns where every value is null.
* Columns where every value is identical (zero variance / single category).
* Columns whose name looks like a primary key (``id``, ``*_id``, ``*_guid``,
  ``uuid``) — these are visually noisy.
* Columns whose values look like UUIDs (≥80% match the canonical UUID regex).

Ranking
-------
Each candidate carries an ``interestingness`` score:
* histograms: coefficient of variation (std / |mean|), capped at 5.0.
* bar charts: spread of group means (max - min) / global std.
* line charts: amplitude (max - min) / global std.
* scatter: |r|.
* donut: normalised Shannon entropy.

Returns the top-N (default 6) by score, with at least one chart of each
type if the snapshot supports it (so we don't return six histograms).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# ── Public types ────────────────────────────────────────────────────────────


@dataclass
class InsightChart:
    """One auto-generated chart suggestion.

    The ``data`` payload is shaped for direct rendering in Recharts:
    a list of small dicts with the field names that match ``x_field`` and
    ``y_field``. The frontend never needs to re-aggregate.
    """

    chart_type: str  # "histogram" | "bar" | "line" | "scatter" | "donut"
    title: str
    data: list[dict[str, Any]]
    x_field: str
    y_field: str
    agg_fn: str | None = None  # "mean" | "count" | None
    interestingness: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart_type": self.chart_type,
            "title": self.title,
            "data": self.data,
            "x_field": self.x_field,
            "y_field": self.y_field,
            "agg_fn": self.agg_fn,
            "interestingness": round(self.interestingness, 4),
            "metadata": self.metadata,
        }


# ── Constants ──────────────────────────────────────────────────────────────


_PK_NAME_PATTERNS = re.compile(
    r"^(id|guid|uuid|.*_id|.*_guid|.*_uuid|entity_guid|source_file_id)$",
    re.IGNORECASE,
)
_UUID_VALUE_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_MIN_NUMERIC_DISTINCT_FOR_HISTOGRAM = 10
_MIN_NUMERIC_DISTINCT_FOR_BAR = 5
_MAX_CATEGORICAL_FOR_BAR = 30
_MIN_CATEGORICAL_FOR_BAR = 2
_MIN_CATEGORICAL_FOR_DONUT = 2
_MAX_CATEGORICAL_FOR_DONUT = 8
_MIN_CORRELATION = 0.5
_TOP_K_BAR = 10
_SCATTER_SAMPLE_CAP = 500
_DEFAULT_LIMIT = 6


# ── Public entry point ─────────────────────────────────────────────────────


def generate_quick_insights(
    df: pd.DataFrame,
    *,
    limit: int = _DEFAULT_LIMIT,
) -> list[InsightChart]:
    """Return the top-N most interesting auto-charts for ``df``.

    The DataFrame is treated as the snapshot's wide-form view: each
    column is a candidate field. Caller is responsible for shaping the
    DataFrame (e.g. flattening a ``attributes`` JSON column). For empty
    DataFrames or DataFrames where every column is filtered out, returns
    ``[]`` rather than raising.
    """
    if df is None or df.empty:
        return []

    usable = _classify_columns(df)
    candidates: list[InsightChart] = []

    # Histograms — one per numeric column.
    for col in usable["numeric"]:
        chart = _try_histogram(df, col)
        if chart is not None:
            candidates.append(chart)

    # Bars — one per (numeric, categorical) pairing whose cat is small.
    for num_col in usable["numeric"]:
        for cat_col in usable["categorical"]:
            chart = _try_bar(df, num_col, cat_col)
            if chart is not None:
                candidates.append(chart)

    # Lines — one per (datetime, numeric) pairing.
    for dt_col in usable["datetime"]:
        for num_col in usable["numeric"]:
            chart = _try_line(df, dt_col, num_col)
            if chart is not None:
                candidates.append(chart)

    # Scatter — pairwise numeric correlations.
    numeric_cols = usable["numeric"]
    for i, a in enumerate(numeric_cols):
        for b in numeric_cols[i + 1 :]:
            chart = _try_scatter(df, a, b)
            if chart is not None:
                candidates.append(chart)

    # Donuts — one per low-cardinality categorical.
    for col in usable["categorical"]:
        chart = _try_donut(df, col)
        if chart is not None:
            candidates.append(chart)

    return _rank_and_diversify(candidates, limit=limit)


# ── Column classification ──────────────────────────────────────────────────


def _classify_columns(df: pd.DataFrame) -> dict[str, list[str]]:
    """Bucket columns into ``numeric`` / ``categorical`` / ``datetime``.

    Drops PK-shaped columns, all-null columns, all-same-value columns,
    and UUID-shaped object columns. The rules are deliberately loose —
    we'd rather skip a borderline-useful column than emit a useless
    chart.
    """
    numeric: list[str] = []
    categorical: list[str] = []
    datetime_: list[str] = []

    for col in df.columns:
        if _PK_NAME_PATTERNS.match(str(col)):
            continue
        series = df[col]
        if series.isna().all():
            continue
        if series.nunique(dropna=True) <= 1:
            continue

        if pd.api.types.is_datetime64_any_dtype(series):
            datetime_.append(str(col))
            continue

        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            numeric.append(str(col))
            continue

        if pd.api.types.is_bool_dtype(series):
            categorical.append(str(col))
            continue

        # Object-typed: tag as categorical unless it looks like UUIDs.
        if _looks_like_uuid_column(series):
            continue
        # Try datetime parse — pandas treats parseable strings as object.
        # Suppress the "could not infer format" warning: if the column
        # is heterogeneous we'd rather silently bucket it as categorical.
        import warnings

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                parsed = pd.to_datetime(series, errors="coerce", utc=False)
        except Exception:  # pragma: no cover — defensive
            parsed = None
        if parsed is not None and parsed.notna().sum() >= max(5, int(len(series) * 0.5)):
            datetime_.append(str(col))
            continue
        categorical.append(str(col))

    return {"numeric": numeric, "categorical": categorical, "datetime": datetime_}


def _looks_like_uuid_column(series: pd.Series, sample: int = 50) -> bool:
    """Return True if ≥80% of non-null string values match the UUID regex."""
    non_null = series.dropna()
    if non_null.empty:
        return False
    sample_values = non_null.iloc[: min(sample, len(non_null))]
    matches = sum(
        1 for v in sample_values if isinstance(v, str) and _UUID_VALUE_PATTERN.match(v)
    )
    return matches >= 0.8 * len(sample_values)


# ── Per-chart heuristics ───────────────────────────────────────────────────


def _try_histogram(df: pd.DataFrame, col: str) -> InsightChart | None:
    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if series.empty:
        return None
    if series.nunique() < _MIN_NUMERIC_DISTINCT_FOR_HISTOGRAM:
        return None
    n = len(series)
    bins = max(5, min(40, int(math.sqrt(n))))
    counts, edges = _safe_histogram(series, bins)
    if counts is None:
        return None
    data = [
        {
            "bin_start": float(edges[i]),
            "bin_end": float(edges[i + 1]),
            "label": _format_bin_label(edges[i], edges[i + 1]),
            "count": int(counts[i]),
        }
        for i in range(len(counts))
    ]
    mean_abs = abs(float(series.mean())) or 1.0
    cv = min(float(series.std(ddof=0)) / mean_abs, 5.0)
    return InsightChart(
        chart_type="histogram",
        title=f"Distribution of {col}",
        data=data,
        x_field="label",
        y_field="count",
        agg_fn="count",
        interestingness=cv,
        metadata={"column": col, "bin_count": bins, "n": n},
    )


def _try_bar(
    df: pd.DataFrame, num_col: str, cat_col: str,
) -> InsightChart | None:
    cat_series = df[cat_col].astype("string")
    if cat_series.dropna().empty:
        return None
    cardinality = cat_series.nunique(dropna=True)
    if not (_MIN_CATEGORICAL_FOR_BAR <= cardinality <= _MAX_CATEGORICAL_FOR_BAR):
        return None
    num_series = pd.to_numeric(df[num_col], errors="coerce")
    if num_series.dropna().nunique() < _MIN_NUMERIC_DISTINCT_FOR_BAR:
        return None

    sub = pd.DataFrame({cat_col: cat_series, num_col: num_series}).dropna()
    if sub.empty:
        return None
    # Top categories by frequency.
    top = sub[cat_col].value_counts().head(_TOP_K_BAR).index.tolist()
    sub = sub[sub[cat_col].isin(top)]
    grouped = sub.groupby(cat_col)[num_col].mean().reindex(top)
    if grouped.empty:
        return None

    global_std = float(num_series.std(ddof=0)) or 1.0
    spread = float(grouped.max() - grouped.min())
    score = min(spread / global_std, 5.0)

    data = [
        {cat_col: str(k), num_col: _round_safe(v)}
        for k, v in grouped.items()
        if pd.notna(v)
    ]
    return InsightChart(
        chart_type="bar",
        title=f"Mean {num_col} by {cat_col}",
        data=data,
        x_field=cat_col,
        y_field=num_col,
        agg_fn="mean",
        interestingness=score,
        metadata={"category": cat_col, "metric": num_col, "top_k": _TOP_K_BAR},
    )


def _try_line(
    df: pd.DataFrame, dt_col: str, num_col: str,
) -> InsightChart | None:
    dt_series = pd.to_datetime(df[dt_col], errors="coerce", utc=False)
    num_series = pd.to_numeric(df[num_col], errors="coerce")
    sub = pd.DataFrame({dt_col: dt_series, num_col: num_series}).dropna()
    if sub.empty or sub[dt_col].nunique() < 3:
        return None

    # Resample to a sensible bucket — at most ~50 points on the line.
    span_days = (sub[dt_col].max() - sub[dt_col].min()).days or 1
    if span_days > 365 * 2:
        rule = "ME"  # month-end (replaces deprecated "M")
    elif span_days > 60:
        rule = "W"
    elif span_days > 7:
        rule = "D"
    else:
        rule = "h"
    resampled = (
        sub.set_index(dt_col)[num_col]
        .resample(rule)
        .mean()
        .dropna()
    )
    if resampled.empty:
        return None

    global_std = float(num_series.std(ddof=0)) or 1.0
    amplitude = float(resampled.max() - resampled.min())
    score = min(amplitude / global_std, 5.0)

    data = [
        {dt_col: ts.isoformat(), num_col: _round_safe(v)}
        for ts, v in resampled.items()
    ]
    return InsightChart(
        chart_type="line",
        title=f"{num_col} over time",
        data=data,
        x_field=dt_col,
        y_field=num_col,
        agg_fn="mean",
        interestingness=score,
        metadata={"resample_rule": rule},
    )


def _try_scatter(
    df: pd.DataFrame, col_a: str, col_b: str,
) -> InsightChart | None:
    a = pd.to_numeric(df[col_a], errors="coerce")
    b = pd.to_numeric(df[col_b], errors="coerce")
    sub = pd.DataFrame({col_a: a, col_b: b}).dropna()
    if len(sub) < 5:
        return None
    a_arr = sub[col_a].to_numpy()
    b_arr = sub[col_b].to_numpy()
    if a_arr.std(ddof=0) == 0 or b_arr.std(ddof=0) == 0:
        return None
    try:
        import numpy as np

        corr_matrix = np.corrcoef(a_arr, b_arr)
        r = float(corr_matrix[0, 1])
    except Exception:  # pragma: no cover — defensive
        return None
    if not math.isfinite(r) or abs(r) < _MIN_CORRELATION:
        return None

    if len(sub) > _SCATTER_SAMPLE_CAP:
        sub = sub.sample(_SCATTER_SAMPLE_CAP, random_state=42)
    data = [
        {col_a: _round_safe(row[col_a]), col_b: _round_safe(row[col_b])}
        for _, row in sub.iterrows()
    ]
    return InsightChart(
        chart_type="scatter",
        title=f"{col_a} vs {col_b} (r={r:.2f})",
        data=data,
        x_field=col_a,
        y_field=col_b,
        agg_fn=None,
        interestingness=abs(r),
        metadata={"pearson_r": round(r, 4), "n": len(data)},
    )


def _try_donut(df: pd.DataFrame, col: str) -> InsightChart | None:
    series = df[col].astype("string").dropna()
    if series.empty:
        return None
    cardinality = series.nunique()
    if not (_MIN_CATEGORICAL_FOR_DONUT <= cardinality <= _MAX_CATEGORICAL_FOR_DONUT):
        return None
    counts = series.value_counts()
    total = int(counts.sum())
    if total == 0:
        return None
    # Normalised Shannon entropy: max entropy for k classes is log(k).
    probs = counts / total
    entropy = float(-(probs * probs.apply(math.log)).sum())
    max_entropy = math.log(cardinality) if cardinality > 1 else 1.0
    score = entropy / max_entropy if max_entropy > 0 else 0.0
    data = [
        {"name": str(k), "value": int(v), "fraction": round(int(v) / total, 4)}
        for k, v in counts.items()
    ]
    return InsightChart(
        chart_type="donut",
        title=f"Breakdown of {col}",
        data=data,
        x_field="name",
        y_field="value",
        agg_fn="count",
        interestingness=score,
        metadata={"cardinality": int(cardinality), "total": total},
    )


# ── Ranking & diversity ────────────────────────────────────────────────────


def _rank_and_diversify(
    candidates: list[InsightChart], *, limit: int,
) -> list[InsightChart]:
    """Sort by score, then re-order to spread chart types across the top.

    Without diversity, a snapshot with 12 numeric columns would surface
    12 histograms. We greedy-pick: walk the sorted list and prefer charts
    whose ``chart_type`` is under-represented in the already-picked set,
    bumping equally-scored alternatives.
    """
    if not candidates:
        return []
    candidates.sort(key=lambda c: c.interestingness, reverse=True)

    picked: list[InsightChart] = []
    type_counts: dict[str, int] = {}
    pool = candidates.copy()

    while pool and len(picked) < limit:
        # Pick the highest-scoring candidate whose type is not already
        # the most-represented in picked.
        max_count = max(type_counts.values()) if type_counts else 0
        for i, c in enumerate(pool):
            if type_counts.get(c.chart_type, 0) < max_count or len(picked) < 3:
                picked.append(c)
                type_counts[c.chart_type] = type_counts.get(c.chart_type, 0) + 1
                pool.pop(i)
                break
        else:
            # All remaining candidates share the most-represented type;
            # take the next one anyway.
            c = pool.pop(0)
            picked.append(c)
            type_counts[c.chart_type] = type_counts.get(c.chart_type, 0) + 1
    return picked


# ── Helpers ────────────────────────────────────────────────────────────────


def _safe_histogram(series: pd.Series, bins: int):
    try:
        import numpy as np

        counts, edges = np.histogram(series.to_numpy(), bins=bins)
        return counts, edges
    except Exception:  # pragma: no cover — defensive
        return None, None


def _format_bin_label(start: float, end: float) -> str:
    return f"{_round_safe(start)}–{_round_safe(end)}"


def _round_safe(v: Any) -> Any:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if not math.isfinite(f):
        return None
    if abs(f) >= 1000:
        return round(f, 1)
    if abs(f) >= 1:
        return round(f, 3)
    return round(f, 4)


__all__ = ["InsightChart", "generate_quick_insights"]
