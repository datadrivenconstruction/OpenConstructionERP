# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parquet spool for EAC runs that overflow the OLTP cap (Wave 1, RFC 36 W1.1).

When :func:`run_ruleset` produces more per-element result rows than
``HOT_RESULT_ITEM_CAP`` (default 100k), the surplus is written to a
Parquet file in the project's storage backend (local FS or S3) instead
of being kept in PostgreSQL. The path is recorded on
``EacRun.spool_path`` so the client can request a presigned URL via
``GET /runs/{id}/results.parquet``.

This module is the I/O envelope around pyarrow — pure conversion plus a
storage write. The actual decision to spool lives in
``runner.run_ruleset``; here we just turn ``ExecutionResult`` slices
into Parquet bytes and persist them.
"""

from __future__ import annotations

import io
import json
import uuid
from typing import Any, Iterable, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from app.core.storage import StorageBackend
from app.modules.eac.engine.executor import ExecutionResult

# Storage key prefix; the actual key is "{prefix}/{run_id}.parquet".
# Surfaces clearly in S3 listings as a single, named directory.
SPOOL_PREFIX = "eac/runs"


# Parquet schema is fixed. Keeping it declarative (not derived from a
# Pydantic model) means downstream readers — DuckDB queries, the
# frontend's parquet-wasm decoder, ad-hoc Pandas — see a stable,
# self-documenting contract regardless of how ExecutionResult evolves.
_SCHEMA = pa.schema(
    [
        pa.field("run_id", pa.string()),
        pa.field("rule_id", pa.string()),
        pa.field("element_id", pa.string()),
        # Boolean nullable: True/False for boolean-mode rows, NULL for
        # issue-mode and aggregate-mode rows that don't carry a verdict.
        pa.field("pass_", pa.bool_()),
        # JSON-encoded payloads. We store as string rather than struct
        # so heterogeneous shapes (issue payload vs aggregate payload)
        # ride a single column without schema churn per rule.
        pa.field("attribute_snapshot_json", pa.string()),
        pa.field("result_value_json", pa.string()),
        pa.field("error", pa.string()),
        pa.field("output_mode", pa.string()),
    ]
)


def spool_key_for(run_id: uuid.UUID) -> str:
    """Return the storage key for a run's Parquet artefact."""
    return f"{SPOOL_PREFIX}/{run_id}.parquet"


def _execution_result_to_rows(
    *,
    run_id: uuid.UUID,
    rule_id: uuid.UUID,
    result: ExecutionResult,
) -> Iterable[dict[str, Any]]:
    """Project an ``ExecutionResult`` into flat rows matching ``_SCHEMA``.

    Mirrors ``runner._materialise_result_items`` but emits dicts shaped
    for Parquet rather than ORM rows. Heterogeneous payloads
    (issue.title, aggregate.value, ...) are JSON-stringified into the
    ``result_value_json`` column.
    """
    run_id_s = str(run_id)
    rule_id_s = str(rule_id)

    if result.output_mode == "boolean":
        for entry in result.boolean_results:
            yield {
                "run_id": run_id_s,
                "rule_id": rule_id_s,
                "element_id": entry.element_id or "",
                "pass_": entry.passed,
                "attribute_snapshot_json": json.dumps(
                    dict(entry.attribute_snapshot), default=str, sort_keys=True
                ),
                "result_value_json": "",
                "error": entry.error or "",
                "output_mode": "boolean",
            }
        return

    if result.output_mode == "issue":
        for issue in result.issue_results:
            payload = {
                "title": issue.title,
                "description": issue.description,
                "topic_type": issue.topic_type,
                "priority": issue.priority,
                "stage": issue.stage,
                "labels": list(issue.labels),
            }
            yield {
                "run_id": run_id_s,
                "rule_id": rule_id_s,
                "element_id": issue.element_id or "",
                "pass_": False,
                "attribute_snapshot_json": json.dumps(
                    dict(issue.attribute_snapshot), default=str, sort_keys=True
                ),
                "result_value_json": json.dumps(payload, default=str, sort_keys=True),
                "error": "",
                "output_mode": "issue",
            }
        return

    if result.output_mode == "aggregate" and result.aggregate_result is not None:
        payload = {
            "value": result.aggregate_result.value,
            "result_unit": result.aggregate_result.result_unit,
            "elements_evaluated": result.aggregate_result.elements_evaluated,
        }
        yield {
            "run_id": run_id_s,
            "rule_id": rule_id_s,
            "element_id": "__aggregate__",
            "pass_": None,
            "attribute_snapshot_json": "",
            "result_value_json": json.dumps(payload, default=str, sort_keys=True),
            "error": "",
            "output_mode": "aggregate",
        }


def rows_to_parquet_bytes(rows: Sequence[dict[str, Any]]) -> bytes:
    """Serialise a list of result-row dicts into Parquet bytes.

    Empty input yields a valid (zero-row) Parquet file so downstream
    readers don't have to special-case "no spilled rows".
    """
    # pa.Table.from_pylist requires non-empty lists for some Arrow
    # versions; build an empty table from the schema directly when no
    # rows came in.
    if not rows:
        table = pa.Table.from_pydict(
            {field.name: [] for field in _SCHEMA},
            schema=_SCHEMA,
        )
    else:
        table = pa.Table.from_pylist(list(rows), schema=_SCHEMA)

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


async def write_spool(
    *,
    storage: StorageBackend,
    run_id: uuid.UUID,
    rows: Sequence[dict[str, Any]],
) -> str:
    """Write ``rows`` as a Parquet object and return the storage key."""
    key = spool_key_for(run_id)
    payload = rows_to_parquet_bytes(rows)
    await storage.put(key, payload)
    return key


def collect_overflow_rows(
    *,
    run_id: uuid.UUID,
    rule_id: uuid.UUID,
    result: ExecutionResult,
    skip: int,
) -> list[dict[str, Any]]:
    """Return overflow rows beyond the first ``skip`` materialised entries.

    The runner persists the first N rows into the OLTP table; we spool
    everything from index ``skip`` onward. Keeping this projection
    pure (no I/O) keeps the runner's hot loop simple — it just feeds
    us per-rule slices and the spool decides what's overflow.
    """
    rows = list(
        _execution_result_to_rows(run_id=run_id, rule_id=rule_id, result=result)
    )
    if skip >= len(rows):
        return []
    return rows[skip:]


__all__ = [
    "SPOOL_PREFIX",
    "collect_overflow_rows",
    "rows_to_parquet_bytes",
    "spool_key_for",
    "write_spool",
]
