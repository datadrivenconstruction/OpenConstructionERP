# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dataset Integrity Overview (T07).

Surfaces data-quality issues across snapshot columns *before* users slice
dashboards. The aim is "did the upload land cleanly?" rather than
domain-level validation: nulls, dtype confusion, outliers, sparsity.

Per-column metrics
------------------
* ``null_count`` / ``null_pct`` — how many rows are missing this field.
* ``unique_count`` — distinct non-null values.
* ``dtype`` — pandas-inferred dtype name ("object", "int64", ...).
* ``inferred_type`` — best-guess "real" type ("numeric", "datetime",
  "boolean", "string"). When pandas says ``object`` but ≥80% of values
  parse as numbers, ``inferred_type = "numeric"`` and we flag a
  ``dtype_mismatch`` issue.
* ``sample_values`` — top-5 values by frequency (for the click-to-expand
  drawer in the UI).
* ``zero_pct`` — fraction of zero values (numeric only). Useful for
  spotting "everything-is-zero" pricing columns.
* ``outlier_count`` — IQR-based outliers (1.5·IQR fence). ``None`` for
  non-numeric columns.
* ``issues`` — short list of issue codes (machine-readable, used by the
  frontend to render coloured badges).

Overall report
--------------
* ``row_count`` / ``column_count``
* ``completeness_score`` — ``1 - mean(null_pct)``, clamped to ``[0, 1]``.
* ``schema_hash`` — stable digest of ``(name, dtype)`` pairs in column
  order. Lets the frontend cache column-detail views across reloads.

The function is pure — the router glue passes a DataFrame and gets a
report back. For the production endpoint we read the same Parquet file
that quick-insights / cascade already use; for unit tests we feed
hand-crafted DataFrames.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

# ── Public types ────────────────────────────────────────────────────────────


IssueCode = Literal[
    "all_null",
    "high_null_pct",
    "constant",
    "dtype_mismatch",
    "outliers_present",
    "high_zero_pct",
    "low_cardinality_string",
    "uuid_like",
]
"""Machine-readable issue codes surfaced per column.

The frontend maps each code to a localised label + colour. New codes
land here when a new heuristic is added — keep them lowercase and
snake_case.
"""


InferredType = Literal["numeric", "datetime", "boolean", "string", "empty"]


@dataclass
class ColumnIntegrity:
    """Per-column integrity diagnostics."""

    name: str
    dtype: str
    inferred_type: InferredType
    row_count: int
    null_count: int
    null_pct: float
    unique_count: int
    completeness: float  # 1 - null_pct
    sample_values: list[dict[str, Any]] = field(default_factory=list)
    zero_pct: float | None = None
    outlier_count: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    issues: list[IssueCode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "inferred_type": self.inferred_type,
            "row_count": self.row_count,
            "null_count": self.null_count,
            "null_pct": round(self.null_pct, 6),
            "unique_count": self.unique_count,
            "completeness": round(self.completeness, 6),
            "sample_values": self.sample_values,
            "zero_pct": (None if self.zero_pct is None else round(self.zero_pct, 6)),
            "outlier_count": self.outlier_count,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "mean_value": self.mean_value,
            "issues": list(self.issues),
        }


@dataclass
class IntegrityReport:
    """Whole-snapshot integrity diagnostics."""

    snapshot_id: str
    project_id: str
    row_count: int
    column_count: int
    completeness_score: float  # 0..1
    schema_hash: str
    columns: list[ColumnIntegrity] = field(default_factory=list)
    issue_summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "project_id": self.project_id,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "completeness_score": round(self.completeness_score, 6),
            "schema_hash": self.schema_hash,
            "columns": [c.to_dict() for c in self.columns],
            "issue_summary": dict(self.issue_summary),
        }


# ── Constants & thresholds ─────────────────────────────────────────────────


_HIGH_NULL_PCT = 0.30
"""Columns with >30% nulls earn a ``high_null_pct`` badge."""

_HIGH_ZERO_PCT = 0.50
"""Numeric columns with >50% zeros earn a ``high_zero_pct`` badge."""

_DTYPE_MISMATCH_RATIO = 0.80
"""If ≥80% of an object column's non-null values parse as numbers /
dates / bools, we record ``dtype_mismatch`` and override
``inferred_type``."""

_LOW_STRING_CARDINALITY_MAX = 5
"""String columns with ≤5 distinct values across ≥10 rows become
``low_cardinality_string`` candidates — they're usually enums in
disguise that should be Categorical."""

_TOP_K_SAMPLE = 5

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# ── Public entry point ─────────────────────────────────────────────────────


def compute_integrity_report(
    df: pd.DataFrame,
    *,
    snapshot_id: str,
    project_id: str,
) -> IntegrityReport:
    """Build an :class:`IntegrityReport` for a wide-form snapshot DataFrame.

    The DataFrame must already be exploded (no ``attributes`` dict
    column). Empty DataFrames yield a degenerate report — zero rows,
    zero columns, completeness score 1.0 — rather than raising.
    """
    if df is None or len(df.columns) == 0:
        return IntegrityReport(
            snapshot_id=snapshot_id,
            project_id=project_id,
            row_count=0 if df is None else int(len(df)),
            column_count=0,
            completeness_score=1.0,
            schema_hash=_schema_hash([]),
            columns=[],
            issue_summary={},
        )

    row_count = int(len(df))
    columns: list[ColumnIntegrity] = []
    issue_counts: dict[str, int] = {}

    for raw_col in df.columns:
        col = str(raw_col)
        col_metrics = _analyse_column(df[raw_col], row_count=row_count, name=col)
        columns.append(col_metrics)
        for issue in col_metrics.issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

    if columns:
        completeness_score = sum(c.completeness for c in columns) / len(columns)
        completeness_score = max(0.0, min(1.0, completeness_score))
    else:
        completeness_score = 1.0

    schema_pairs = [(c.name, c.dtype) for c in columns]
    return IntegrityReport(
        snapshot_id=snapshot_id,
        project_id=project_id,
        row_count=row_count,
        column_count=len(columns),
        completeness_score=completeness_score,
        schema_hash=_schema_hash(schema_pairs),
        columns=columns,
        issue_summary=issue_counts,
    )


# ── Per-column analysis ────────────────────────────────────────────────────


def _analyse_column(
    series: pd.Series,
    *,
    row_count: int,
    name: str,
) -> ColumnIntegrity:
    dtype_name = str(series.dtype)
    null_count = int(series.isna().sum())
    null_pct = (null_count / row_count) if row_count > 0 else 0.0
    completeness = 1.0 - null_pct

    non_null = series.dropna()
    unique_count = int(non_null.nunique()) if len(non_null) > 0 else 0

    issues: list[IssueCode] = []

    # All-null short-circuit — most other checks are meaningless here.
    if row_count > 0 and null_count == row_count:
        issues.append("all_null")
        return ColumnIntegrity(
            name=name,
            dtype=dtype_name,
            inferred_type="empty",
            row_count=row_count,
            null_count=null_count,
            null_pct=null_pct,
            unique_count=0,
            completeness=completeness,
            sample_values=[],
            zero_pct=None,
            outlier_count=None,
            issues=issues,
        )

    if null_pct > _HIGH_NULL_PCT:
        issues.append("high_null_pct")

    if unique_count == 1:
        issues.append("constant")

    inferred_type = _infer_type(series, non_null)

    # Dtype mismatch: pandas inferred object but the values look numeric
    # / datetime / boolean. Flag it so the user can fix the upstream
    # CSV / parquet dtype before slicing.
    if pd.api.types.is_object_dtype(series) and inferred_type != "string":
        issues.append("dtype_mismatch")

    # UUID-ish columns aren't a hard error, but the user probably
    # doesn't want to filter on them. Tag the column to make the badge
    # visible.
    if inferred_type == "string" and _looks_like_uuid_column(non_null):
        issues.append("uuid_like")

    sample_values = _top_k_sample(non_null)

    zero_pct: float | None = None
    outlier_count: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None

    if inferred_type == "numeric":
        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        if not numeric.empty:
            zero_pct = float((numeric == 0).sum()) / float(len(numeric))
            outlier_count = _iqr_outlier_count(numeric)
            min_value = _safe_float(numeric.min())
            max_value = _safe_float(numeric.max())
            mean_value = _safe_float(numeric.mean())
            if zero_pct is not None and zero_pct > _HIGH_ZERO_PCT:
                issues.append("high_zero_pct")
            if outlier_count is not None and outlier_count > 0:
                issues.append("outliers_present")

    elif (
        inferred_type == "string"
        and unique_count > 0
        and unique_count <= _LOW_STRING_CARDINALITY_MAX
        and len(non_null) >= 10
    ):
        issues.append("low_cardinality_string")

    return ColumnIntegrity(
        name=name,
        dtype=dtype_name,
        inferred_type=inferred_type,
        row_count=row_count,
        null_count=null_count,
        null_pct=null_pct,
        unique_count=unique_count,
        completeness=completeness,
        sample_values=sample_values,
        zero_pct=zero_pct,
        outlier_count=outlier_count,
        min_value=min_value,
        max_value=max_value,
        mean_value=mean_value,
        issues=issues,
    )


# ── Type inference ─────────────────────────────────────────────────────────


def _infer_type(series: pd.Series, non_null: pd.Series) -> InferredType:
    """Best-guess "real" type for a column.

    Pandas' dtype is a starting point — for object columns we sniff the
    actual values to catch the common upload-from-CSV failure where
    everything came back as strings.
    """
    if non_null.empty:
        return "empty"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    # Object dtype — sniff values.
    if pd.api.types.is_object_dtype(series):
        # Bool-like first: {"true", "false"} or {True, False}.
        if _ratio_passes(non_null, _is_bool_like) >= _DTYPE_MISMATCH_RATIO:
            return "boolean"
        # Numeric next.
        if _ratio_passes(non_null, _is_numeric_like) >= _DTYPE_MISMATCH_RATIO:
            return "numeric"
        # Datetime — only attempt parse if values are strings.
        if _ratio_passes(non_null, _is_datetime_like) >= _DTYPE_MISMATCH_RATIO:
            return "datetime"
    return "string"


def _ratio_passes(
    series: pd.Series, predicate: Callable[[Any], bool],
) -> float:
    """Return the fraction of values satisfying ``predicate``."""
    if len(series) == 0:
        return 0.0
    hits = sum(1 for v in series if predicate(v))
    return hits / len(series)


def _is_numeric_like(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return not (isinstance(value, float) and math.isnan(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return False
        try:
            float(s)
        except ValueError:
            return False
        return True
    return False


def _is_bool_like(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "false", "yes", "no", "0", "1"}
    return False


def _is_datetime_like(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    if len(s) < 8:
        return False
    try:
        # pandas.to_datetime is the most permissive parser available;
        # rely on its NaT-on-failure path rather than rolling our own.
        parsed = pd.to_datetime(s, errors="coerce")
    except (ValueError, TypeError):
        return False
    return not pd.isna(parsed)


def _looks_like_uuid_column(non_null: pd.Series, sample: int = 50) -> bool:
    """≥80% of (string) values match the canonical UUID regex."""
    sample_values = non_null.iloc[: min(sample, len(non_null))]
    matches = sum(1 for v in sample_values if isinstance(v, str) and _UUID_PATTERN.match(v))
    if len(sample_values) == 0:
        return False
    return matches >= 0.8 * len(sample_values)


# ── Numeric helpers ────────────────────────────────────────────────────────


def _iqr_outlier_count(numeric: pd.Series) -> int:
    """Count outliers under the 1.5·IQR fence rule.

    For very small samples (<5 values) the IQR is too noisy to be
    meaningful — return 0 in that case to avoid false-positive badges.
    """
    if len(numeric) < 5:
        return 0
    q1 = float(numeric.quantile(0.25))
    q3 = float(numeric.quantile(0.75))
    iqr = q3 - q1
    if iqr == 0:
        return 0
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    mask = (numeric < lower) | (numeric > upper)
    return int(mask.sum())


def _safe_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


# ── Sampling & hashing ─────────────────────────────────────────────────────


def _top_k_sample(non_null: pd.Series) -> list[dict[str, Any]]:
    """Return the top-K most-frequent values plus their counts."""
    if non_null.empty:
        return []
    try:
        counts = non_null.astype("string").value_counts().head(_TOP_K_SAMPLE)
    except (TypeError, ValueError):
        # Mixed types we can't cast cleanly — fall back to str().
        counts = non_null.map(lambda v: str(v)).value_counts().head(_TOP_K_SAMPLE)
    out: list[dict[str, Any]] = []
    for value, count in counts.items():
        out.append({"value": str(value), "count": int(count)})
    return out


def _schema_hash(pairs: list[tuple[str, str]]) -> str:
    """Stable hash of (column, dtype) pairs in column order."""
    payload = "\n".join(f"{name}\t{dtype}" for name, dtype in pairs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "ColumnIntegrity",
    "IntegrityReport",
    "IssueCode",
    "compute_integrity_report",
]
