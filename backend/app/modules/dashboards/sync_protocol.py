# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Preset → Snapshot Sync Protocol (T09 / task #192).

A dashboard preset (T05) freezes a bundle of column choices and filter
values that came out of a *snapshot at a given point in time*. When the
underlying snapshot is rebuilt (a column gets renamed in the source
model, a category gets dropped from a filter set, a numeric column flips
to a string), the preset's references go stale.

This module gives presets a way to detect, classify, and (where safe)
auto-heal that staleness.

Pipeline
--------

1. Snapshot is refreshed (a fresh Parquet dump is written) →
   :data:`SNAPSHOT_REFRESHED` event fires, every preset whose
   ``config_json.snapshot_id`` points at the refreshed snapshot is
   marked ``sync_status='stale'``.
2. The user opens the preset (or clicks the badge) → the frontend hits
   ``POST /presets/{id}/sync-check`` which loads the snapshot's current
   meta and runs :class:`PresetSyncProbe` to produce a
   :class:`SyncReport`.
3. The user reviews the report. Issues with ``suggested_fix='auto_*'``
   can be applied with one click via ``POST /presets/{id}/sync-heal``;
   issues marked ``manual`` need a human (e.g. a referenced column went
   away with no obvious successor).
4. After healing, ``sync_status`` flips to ``'synced'`` (no remaining
   issues) or ``'needs_review'`` (auto-fixes applied but manual issues
   remain).

The probe is intentionally tolerant: a preset that already lacks the
keys it would reference (an empty ``config_json``) is treated as
"in sync, nothing to check" rather than producing spurious noise. The
heuristics never *delete* a chart or filter card — at worst they drop
specific filter values whose column is still present but whose value
disappeared. Anything more destructive falls back to ``manual``.

The protocol is i18n-friendly: every issue carries a
:attr:`SyncIssue.message_key` that the router/UI can translate. The
``message`` field is a human-readable English fallback for log lines
and tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Literal

logger = logging.getLogger(__name__)


# ── Event constants ────────────────────────────────────────────────────────


SNAPSHOT_REFRESHED: Final = "snapshot.refreshed"
"""Fired by the snapshot service when an existing snapshot's data is
re-materialised from a fresh upload. Payload contains at minimum
``{snapshot_id, project_id, tenant_id}``. Marked-stale presets carry
the same ``snapshot_id`` inside their ``config_json``."""


# ── Public types ───────────────────────────────────────────────────────────


SyncStatus = Literal["synced", "stale", "needs_review"]
"""Lifecycle states for the :attr:`DashboardPreset.sync_status` column."""

Severity = Literal["warning", "error"]
"""Per-issue severity. Errors mean the preset cannot be loaded as-is
without losing meaning; warnings mean it loads but may behave
unexpectedly."""

SuggestedFix = Literal["auto_rename", "drop_filter", "manual"]
"""How :func:`auto_heal` should respond to the issue:

* ``auto_rename`` — pure column rename detected; safe to update in place.
* ``drop_filter`` — a filter value disappeared from the snapshot's value
  set; drop just that value from the preset's filter list.
* ``manual`` — a column went away entirely or its dtype shifted in a
  way that breaks chart axes; needs human review.
"""

IssueKind = Literal[
    "column_rename",
    "dropped_column",
    "dropped_filter_value",
    "dtype_change",
]


@dataclass(frozen=True)
class SyncIssue:
    """One staleness signal between a preset and its snapshot."""

    kind: IssueKind
    severity: Severity
    suggested_fix: SuggestedFix
    column: str
    """The column the issue references (the *original* name when the
    issue is a rename — :attr:`new_column` carries the proposed
    successor)."""

    new_column: str | None = None
    """Proposed successor column name for renames; ``None`` otherwise."""

    dropped_values: tuple[str, ...] = ()
    """Filter values that vanished from the snapshot. Populated only for
    ``dropped_filter_value`` issues."""

    old_dtype: str | None = None
    """For ``dtype_change``, the dtype the preset expected (taken from
    the snapshot meta it was built against)."""

    new_dtype: str | None = None
    """For ``dtype_change``, the dtype the snapshot carries today."""

    message_key: str = "preset.sync.unknown"
    """i18n key the UI uses to localise the issue's headline."""

    message: str = ""
    """English fallback for log lines / tests."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "suggested_fix": self.suggested_fix,
            "column": self.column,
            "new_column": self.new_column,
            "dropped_values": list(self.dropped_values),
            "old_dtype": self.old_dtype,
            "new_dtype": self.new_dtype,
            "message_key": self.message_key,
            "message": self.message,
        }


@dataclass
class SyncReport:
    """The probe's verdict on a (preset, snapshot meta) pair."""

    preset_id: str
    snapshot_id: str | None
    column_renames: list[SyncIssue] = field(default_factory=list)
    dropped_columns: list[SyncIssue] = field(default_factory=list)
    dropped_filter_values: list[SyncIssue] = field(default_factory=list)
    dtype_changes: list[SyncIssue] = field(default_factory=list)

    @property
    def all_issues(self) -> list[SyncIssue]:
        return (
            self.column_renames
            + self.dropped_columns
            + self.dropped_filter_values
            + self.dtype_changes
        )

    @property
    def is_in_sync(self) -> bool:
        return not self.all_issues

    @property
    def status(self) -> SyncStatus:
        """Computed sync_status that auto_heal should land on if applied
        right now: ``synced`` if zero issues, ``needs_review`` if any
        manual fixes remain after auto-healing the rest, else ``stale``.
        """
        if self.is_in_sync:
            return "synced"
        if any(i.suggested_fix == "manual" for i in self.all_issues):
            return "needs_review"
        return "stale"

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "is_in_sync": self.is_in_sync,
            "column_renames": [i.to_dict() for i in self.column_renames],
            "dropped_columns": [i.to_dict() for i in self.dropped_columns],
            "dropped_filter_values": [
                i.to_dict() for i in self.dropped_filter_values
            ],
            "dtype_changes": [i.to_dict() for i in self.dtype_changes],
        }


@dataclass(frozen=True)
class SnapshotMeta:
    """Lightweight description of a snapshot's column shape.

    The probe only ever cares about three things:

    * ``columns`` — the set of column names callers can reference.
    * ``dtypes`` — per-column dtype string (``numeric`` / ``string`` /
      ``datetime`` / ``boolean``). The granularity matches
      :mod:`integrity` so the two systems agree on dtype semantics.
    * ``value_sets`` — for the columns the preset filters on, the set
      of distinct values currently present. Optional — when missing,
      the probe skips the dropped-filter-value check for that column.
    """

    columns: tuple[str, ...] = ()
    dtypes: dict[str, str] = field(default_factory=dict)
    value_sets: dict[str, frozenset[str]] = field(default_factory=dict)

    def has_column(self, name: str) -> bool:
        return name in self.columns

    def values_for(self, column: str) -> frozenset[str] | None:
        return self.value_sets.get(column)


# ── Pure diff helper ───────────────────────────────────────────────────────


def diff_snapshot_meta(
    old_meta: SnapshotMeta,
    new_meta: SnapshotMeta,
) -> dict[str, Any]:
    """Compare two snapshot metas. Pure / side-effect-free.

    Returns a dict with three keys:

    * ``added`` — columns present in ``new`` but not ``old``.
    * ``removed`` — columns present in ``old`` but not ``new``.
    * ``dtype_changes`` — list of ``(column, old_dtype, new_dtype)``
      tuples for columns present in both whose dtype shifted.

    No rename inference happens here — that's the probe's job and uses
    the *preset's* references rather than just the meta diff.
    """
    old_cols = set(old_meta.columns)
    new_cols = set(new_meta.columns)
    added = sorted(new_cols - old_cols)
    removed = sorted(old_cols - new_cols)

    dtype_changes: list[tuple[str, str, str]] = []
    for col in sorted(old_cols & new_cols):
        old_dt = old_meta.dtypes.get(col)
        new_dt = new_meta.dtypes.get(col)
        if old_dt is not None and new_dt is not None and old_dt != new_dt:
            dtype_changes.append((col, old_dt, new_dt))

    return {
        "added": added,
        "removed": removed,
        "dtype_changes": dtype_changes,
    }


# ── Probe ──────────────────────────────────────────────────────────────────


# Common rename patterns we trust enough to auto-suggest. Each tuple is
# ``(pattern in old, pattern in new)`` — a bidirectional equivalence
# class. We only fire a rename suggestion when an old column is gone,
# *exactly one* candidate exists in the snapshot's added columns, and
# the candidate's dtype matches.
_RENAME_HEURISTICS: Final[tuple[tuple[str, str], ...]] = (
    ("name", "label"),
    ("label", "name"),
    ("qty", "quantity"),
    ("quantity", "qty"),
    ("amt", "amount"),
    ("amount", "amt"),
    ("desc", "description"),
    ("description", "desc"),
    ("category", "type"),
    ("type", "category"),
)


class PresetSyncProbe:
    """Compare a preset against a current :class:`SnapshotMeta`.

    The probe is stateless — instantiate once, call :meth:`run` per
    preset. It accepts both the meta the preset *was built against*
    (read out of ``config_json['snapshot_meta']`` if present) and the
    snapshot's *current* meta. When the historical meta is absent we
    fall back to "every referenced column must exist today" — coarser,
    but never wrong.
    """

    def __init__(self) -> None:
        # Caches normalised forms of column names for cheap lookups.
        self._normalise_cache: dict[str, str] = {}

    # -- public entrypoint ------------------------------------------------

    def run(
        self,
        preset_config: dict[str, Any],
        current_meta: SnapshotMeta,
        *,
        preset_id: str,
    ) -> SyncReport:
        """Generate a :class:`SyncReport`.

        ``preset_config`` is the raw dict stored in
        :attr:`DashboardPreset.config_json`. Recognised keys:

        * ``snapshot_id`` — the snapshot the preset references.
        * ``snapshot_meta`` — optional :class:`SnapshotMeta`-shaped dict
          captured at preset-save time. Used to anchor rename and dtype
          diffs.
        * ``columns`` — list of column names referenced by the preset's
          charts.
        * ``filters`` — column → list-of-values mapping (same shape as
          the cascade engine).
        """
        snapshot_id = self._extract_snapshot_id(preset_config)
        old_meta = self._extract_old_meta(preset_config)

        report = SyncReport(preset_id=preset_id, snapshot_id=snapshot_id)

        referenced_columns = self._referenced_columns(preset_config)
        filters = self._referenced_filters(preset_config)

        # 1. Column-level diff: missing columns + rename candidates.
        present_columns = set(current_meta.columns)
        meta_diff = (
            diff_snapshot_meta(old_meta, current_meta)
            if old_meta.columns
            else {"added": [], "removed": [], "dtype_changes": []}
        )

        for col in sorted(referenced_columns):
            if col in present_columns:
                continue
            # Try a rename heuristic.
            renamed_to = self._suggest_rename(
                col,
                added_columns=meta_diff["added"] or list(present_columns),
                old_meta=old_meta,
                new_meta=current_meta,
            )
            if renamed_to is not None:
                report.column_renames.append(
                    SyncIssue(
                        kind="column_rename",
                        severity="warning",
                        suggested_fix="auto_rename",
                        column=col,
                        new_column=renamed_to,
                        message_key="preset.sync.column_rename",
                        message=(
                            f"Column '{col}' looks renamed to "
                            f"'{renamed_to}' in the refreshed snapshot."
                        ),
                    )
                )
            else:
                report.dropped_columns.append(
                    SyncIssue(
                        kind="dropped_column",
                        severity="error",
                        suggested_fix="manual",
                        column=col,
                        message_key="preset.sync.dropped_column",
                        message=(
                            f"Column '{col}' is no longer present in the "
                            f"snapshot. Pick a replacement manually."
                        ),
                    )
                )

        # 2. Dtype changes on columns the preset still references.
        for col, old_dt, new_dt in meta_diff["dtype_changes"]:
            if col not in referenced_columns:
                continue
            severity, fix = self._classify_dtype_change(old_dt, new_dt)
            report.dtype_changes.append(
                SyncIssue(
                    kind="dtype_change",
                    severity=severity,
                    suggested_fix=fix,
                    column=col,
                    old_dtype=old_dt,
                    new_dtype=new_dt,
                    message_key="preset.sync.dtype_change",
                    message=(
                        f"Column '{col}' dtype changed: {old_dt} → {new_dt}."
                    ),
                )
            )

        # 3. Dropped filter values: only meaningful when the column
        #    still exists *and* the snapshot reports a value set for it.
        for col, allowed in filters.items():
            if col not in present_columns:
                # Already covered as either a rename or a dropped col.
                continue
            current_values = current_meta.values_for(col)
            if current_values is None:
                continue
            missing = tuple(
                v for v in allowed if v not in current_values
            )
            if not missing:
                continue
            report.dropped_filter_values.append(
                SyncIssue(
                    kind="dropped_filter_value",
                    severity="warning",
                    suggested_fix="drop_filter",
                    column=col,
                    dropped_values=missing,
                    message_key="preset.sync.dropped_filter_value",
                    message=(
                        f"Filter '{col}' references {len(missing)} "
                        f"value(s) no longer present: "
                        f"{', '.join(missing[:3])}"
                        + ("…" if len(missing) > 3 else "")
                    ),
                )
            )

        return report

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _extract_snapshot_id(config: dict[str, Any]) -> str | None:
        sid = config.get("snapshot_id")
        return str(sid) if sid else None

    @staticmethod
    def _extract_old_meta(config: dict[str, Any]) -> SnapshotMeta:
        raw = config.get("snapshot_meta") or {}
        if not isinstance(raw, dict):
            return SnapshotMeta()
        columns = tuple(str(c) for c in raw.get("columns", ()))
        dtypes = {
            str(k): str(v) for k, v in (raw.get("dtypes") or {}).items()
        }
        value_sets_raw = raw.get("value_sets") or {}
        value_sets = {
            str(k): frozenset(str(x) for x in (v or []))
            for k, v in value_sets_raw.items()
        }
        return SnapshotMeta(
            columns=columns,
            dtypes=dtypes,
            value_sets=value_sets,
        )

    @staticmethod
    def _referenced_columns(config: dict[str, Any]) -> set[str]:
        cols: set[str] = set()
        # Top-level "columns" list (chart axes / table columns).
        for c in config.get("columns") or []:
            if isinstance(c, str) and c.strip():
                cols.add(c.strip())
        # Charts can pin x_field / y_field individually — collect those
        # so a chart-only preset still surfaces dropped columns.
        for chart in config.get("charts") or []:
            if not isinstance(chart, dict):
                continue
            for key in ("x_field", "y_field", "column"):
                v = chart.get(key)
                if isinstance(v, str) and v.strip():
                    cols.add(v.strip())
        # Filter keys.
        for k in (config.get("filters") or {}):
            if isinstance(k, str) and k.strip():
                cols.add(k.strip())
        return cols

    @staticmethod
    def _referenced_filters(config: dict[str, Any]) -> dict[str, list[str]]:
        raw = config.get("filters") or {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, list[str]] = {}
        for k, v in raw.items():
            if not isinstance(k, str):
                continue
            if not isinstance(v, list):
                continue
            out[k] = [str(x) for x in v]
        return out

    def _normalise(self, name: str) -> str:
        cached = self._normalise_cache.get(name)
        if cached is not None:
            return cached
        norm = name.strip().lower().replace("-", "_").replace(" ", "_")
        self._normalise_cache[name] = norm
        return norm

    def _suggest_rename(
        self,
        old_column: str,
        *,
        added_columns: list[str],
        old_meta: SnapshotMeta,
        new_meta: SnapshotMeta,
    ) -> str | None:
        """Return a rename candidate for ``old_column`` or ``None``.

        Strategy:

        1. If exactly one ``added`` column shares the same dtype as
           ``old_column`` did and matches a known synonym pattern, take it.
        2. If exactly one ``added`` column shares the same normalised
           name (case- / dash-insensitive), take it.
        3. Otherwise: no auto-rename.
        """
        if not added_columns:
            return None

        old_norm = self._normalise(old_column)
        old_dt = old_meta.dtypes.get(old_column)

        # Step 2 (cheaper) first: case-insensitive name equivalence.
        normalised_match = [
            c for c in added_columns if self._normalise(c) == old_norm
        ]
        if len(normalised_match) == 1:
            return normalised_match[0]

        # Step 1: known synonym patterns within the same dtype family.
        candidates: list[str] = []
        for cand in added_columns:
            if old_dt is not None:
                cand_dt = new_meta.dtypes.get(cand)
                if cand_dt is not None and cand_dt != old_dt:
                    continue
            cand_norm = self._normalise(cand)
            for pattern_old, pattern_new in _RENAME_HEURISTICS:
                if pattern_old in old_norm and pattern_new in cand_norm:
                    candidates.append(cand)
                    break
        if len(candidates) == 1:
            return candidates[0]

        return None

    @staticmethod
    def _classify_dtype_change(
        old_dt: str, new_dt: str,
    ) -> tuple[Severity, SuggestedFix]:
        """Decide how serious a dtype shift is.

        Numeric ↔ numeric (e.g. ``int`` → ``float``) — warning, manual
        (chart axes work either way but tooltips may surprise the user).

        Anything that crosses the numeric/string/datetime boundary —
        error, manual (charts that bucketise on the column will break).
        """
        equiv: dict[str, set[str]] = {
            "numeric": {"numeric", "int", "float", "integer", "double"},
            "string": {"string", "object", "text"},
            "datetime": {"datetime", "date", "timestamp"},
            "boolean": {"boolean", "bool"},
        }

        def _family(dt: str) -> str:
            for fam, members in equiv.items():
                if dt in members:
                    return fam
            return dt

        if _family(old_dt) == _family(new_dt):
            return ("warning", "manual")
        return ("error", "manual")


# ── Auto-heal ──────────────────────────────────────────────────────────────


def auto_heal(
    preset_config: dict[str, Any],
    sync_report: SyncReport,
) -> dict[str, Any]:
    """Apply every safe fix from ``sync_report`` to ``preset_config``.

    Returns a *new* dict — the caller is expected to assign it back to
    :attr:`DashboardPreset.config_json`. Issues with
    ``suggested_fix='manual'`` are left untouched; their entries remain
    in the report so the UI can drive the human review.

    Safe fixes:

    * ``column_rename`` → rewrites the column reference in
      ``columns``, ``filters`` keys, and per-chart ``x_field`` /
      ``y_field`` / ``column`` fields.
    * ``dropped_filter_value`` → removes the missing values from the
      filter list. If the resulting list is empty the *key* stays in
      ``filters`` — that's the cascade engine's "no filter on this
      column" shape, never an empty IN-list.
    """
    patched: dict[str, Any] = _deep_copy_dict(preset_config)

    # Build rename map (old → new).
    renames = {
        i.column: i.new_column
        for i in sync_report.column_renames
        if i.suggested_fix == "auto_rename" and i.new_column
    }

    # 1. Apply renames.
    if renames:
        # Top-level columns list.
        if isinstance(patched.get("columns"), list):
            patched["columns"] = [
                renames.get(c, c) if isinstance(c, str) else c
                for c in patched["columns"]
            ]
        # Charts.
        if isinstance(patched.get("charts"), list):
            new_charts = []
            for chart in patched["charts"]:
                if not isinstance(chart, dict):
                    new_charts.append(chart)
                    continue
                chart = dict(chart)
                for key in ("x_field", "y_field", "column"):
                    v = chart.get(key)
                    if isinstance(v, str) and v in renames:
                        chart[key] = renames[v]
                new_charts.append(chart)
            patched["charts"] = new_charts
        # Filter keys.
        filters = patched.get("filters")
        if isinstance(filters, dict):
            new_filters: dict[str, Any] = {}
            for k, v in filters.items():
                key = renames.get(k, k) if isinstance(k, str) else k
                new_filters[key] = v
            patched["filters"] = new_filters

    # 2. Drop missing filter values.
    drops = {
        i.column: set(i.dropped_values)
        for i in sync_report.dropped_filter_values
        if i.suggested_fix == "drop_filter"
    }
    if drops and isinstance(patched.get("filters"), dict):
        cleaned: dict[str, Any] = {}
        for k, v in patched["filters"].items():
            if k in drops and isinstance(v, list):
                cleaned[k] = [
                    item for item in v if str(item) not in drops[k]
                ]
            else:
                cleaned[k] = v
        patched["filters"] = cleaned

    return patched


# ── Snapshot meta loader ───────────────────────────────────────────────────


async def load_current_meta(
    *,
    pool: Any,
    snapshot_id: str,
    project_id: str,
    columns_for_value_sets: list[str] | None = None,
    max_values_per_column: int = 200,
) -> SnapshotMeta:
    """Read the current shape of a snapshot into a :class:`SnapshotMeta`.

    Lives next to the probe so callers don't have to assemble the meta
    by hand. Uses the same DuckDB pool the cascade engine / smart
    values do; falls back to an empty meta when the snapshot's parquet
    file is unreachable (so a sync-check on a freshly-deleted snapshot
    is still well-defined — every referenced column will surface as
    "dropped" rather than the endpoint 500-ing).
    """
    columns: list[str] = []
    dtypes: dict[str, str] = {}
    try:
        rows = await pool.execute(
            snapshot_id,
            project_id,
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'entities'",
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "sync.load_current_meta failed snapshot_id=%s: %s",
            snapshot_id,
            type(exc).__name__,
        )
        return SnapshotMeta()

    for col_row in rows:
        name = str(col_row[0])
        dtype_raw = str(col_row[1]) if len(col_row) > 1 else ""
        columns.append(name)
        dtypes[name] = _coerce_dtype(dtype_raw)

    value_sets: dict[str, frozenset[str]] = {}
    if columns_for_value_sets:
        for col in columns_for_value_sets:
            if col not in dtypes:
                continue
            try:
                rows = await pool.execute(
                    snapshot_id,
                    project_id,
                    f'SELECT DISTINCT CAST("{col}" AS VARCHAR) '
                    f'FROM entities WHERE "{col}" IS NOT NULL '
                    f'LIMIT {int(max_values_per_column)}',
                )
            except Exception:
                continue
            value_sets[col] = frozenset(str(r[0]) for r in rows if r[0] is not None)

    return SnapshotMeta(
        columns=tuple(columns),
        dtypes=dtypes,
        value_sets=value_sets,
    )


def _coerce_dtype(raw: str) -> str:
    """Map DuckDB's catalogue dtype names to the four families the
    probe and integrity engine agree on."""
    raw_l = raw.lower()
    if any(t in raw_l for t in ("int", "double", "float", "decimal", "numeric", "real")):
        return "numeric"
    if any(t in raw_l for t in ("timestamp", "date", "time")):
        return "datetime"
    if "bool" in raw_l:
        return "boolean"
    if any(t in raw_l for t in ("varchar", "char", "text", "string", "blob")):
        return "string"
    return raw_l or "string"


# ── Internal helpers ───────────────────────────────────────────────────────


def _deep_copy_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Shallow-clone the top level + every nested list/dict.

    Cheaper than copy.deepcopy: preset configs are JSON-shaped and
    never carry custom objects, so this is sufficient and avoids the
    pickle-machinery overhead that ``copy.deepcopy`` adds for large
    nested filter dicts.
    """
    out: dict[str, Any] = {}
    for k, v in d.items():
        out[k] = _clone(v)
    return out


def _clone(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _clone(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_clone(x) for x in v]
    return v


__all__ = [
    "PresetSyncProbe",
    "SNAPSHOT_REFRESHED",
    "Severity",
    "SnapshotMeta",
    "SuggestedFix",
    "SyncIssue",
    "SyncReport",
    "SyncStatus",
    "auto_heal",
    "diff_snapshot_meta",
    "load_current_meta",
]
