# ADR-001 — Snapshot storage model

- **Status:** Accepted
- **Date:** 2026-04-23
- **Owner:** dashboards module
- **Related:** `CLAUDE-DASHBOARDS.md` T00, T01

## Context

The dashboards layer (`CLAUDE-DASHBOARDS.md`) needs to store entity data
for multiple snapshots of a project. Per-snapshot row counts range from
hundreds (small takeoffs) to multi-millions (federated projects with
many linked models). Queries the layer must answer in < 500 ms p95:

- Category/attribute enumeration.
- `GROUP BY attribute` aggregations (bar / donut).
- Cross-attribute filter SQL with ad-hoc `WHERE` trees.
- Full-text-ish value autocomplete over 100 k+ distinct values.
- Cross-snapshot diff on two 500 k-entity snapshots in < 1 s.

The existing OCERP baseline stores BIMElement rows in SQLAlchemy +
(SQLite or PostgreSQL). That works for single-row CRUD and the "Linked
BOQ" panel, but loses badly on the above analytical workloads at
100 k+ rows — SQLite's query planner has no column statistics, and
PostgreSQL's JSONB path extraction is 10-100× slower than columnar
equivalents at this shape of query.

## Options considered

### Option A — "Pure SQL" (reject)
Store everything in the primary DB. BIMElement rows, one row per entity,
JSONB for attributes.
- **Pros:** zero new infrastructure.
- **Cons:** 10 M-entity federated snapshots kill the query planner;
  `GROUP BY attribute` on JSONB is disastrous on SQLite;
  already the path we're trying to augment.

### Option B — "Pure columnar" (reject)
Drop the primary DB for analytical data entirely. Snapshots live only as
Parquet files on disk, with a manifest.json for metadata.
- **Pros:** clean separation.
- **Cons:** no relational joins across snapshots or between snapshots
  and org-wide tables (users, tenants, dashboards, compliance rules);
  reinventing auth / tenancy on top of the filesystem.

### Option C — "SQL meta + Parquet data + DuckDB queries" (accepted)
- **Metadata** (one row per snapshot, one row per dashboard, one row per
  compliance rule, etc.) in the existing primary DB (SQLite default,
  PostgreSQL via `[server]` extra). This keeps tenant scoping, auth,
  RLS-style predicates, and the event bus semantics consistent with
  every other module.
- **Entity data** in Parquet files, laid out per snapshot under
  `dashboards/<project_id>/<snapshot_id>/{entities,materials,source_files,
  attribute_value_index}.parquet`. The existing
  `app.core.storage.StorageBackend` abstraction owns the on-disk layout
  — `LocalStorageBackend` today, S3 via `[s3]` extra later.
- **Analytical queries** go through DuckDB. A per-snapshot connection in
  `app.modules.dashboards.duckdb_pool` registers each Parquet file as a
  read-only view and executes parameterised SQL against it.
- **No schema migrations inside Parquet.** Each snapshot captures the
  entity schema as it was when the snapshot was created. Cross-snapshot
  diffs explicitly handle schema drift in the query layer (T11).

## Decision

Adopt **Option C**. Commit to DuckDB as a base dependency (previously
optional in `[analytics]`). Treat Parquet as the only entity-data
format; the primary DB never holds entity rows.

## Consequences

### Good
- Analytical queries scale to multi-million-entity snapshots without
  touching the primary DB.
- Snapshots are immutable byte blobs — easy to diff, archive, replicate,
  or ship to a reviewer.
- The `StorageBackend` abstraction means operators can point at S3-like
  storage without any code change in the dashboard layer (the DuckDB
  path resolution will need `httpfs` support; see
  `ParquetNotLocalError` in `snapshot_storage.py`).
- Sidesteps JSONB performance pathology on SQLite.

### Bad / load-bearing
- DuckDB is now a **base dependency** (wheel size ~50 MB). Operators on
  very constrained VPS (1 GB RAM class) may prefer not to install; we
  do not ship a non-DuckDB fallback for analytical queries.
- `[analytics]` extra becomes a deprecated alias to satisfy prior install
  commands.
- S3 storage cannot serve Parquet to DuckDB until the `httpfs`
  extension is wired (follow-up; out of scope for T00/T01).

### Rollback path
If DuckDB becomes untenable (licence change, bus-factor, CVE-storm) we
can swap the analytical engine without changing Parquet layout: any
engine that reads Parquet + SQL (datafusion, clickhouse-local, polars-sql)
can drop in at `duckdb_pool.py`. The migration would not touch entity
data on disk.

## Implementation pointers

- `backend/app/modules/dashboards/snapshot_storage.py` —
  key layout + serialisation + DuckDB path resolution.
- `backend/app/modules/dashboards/duckdb_pool.py` —
  LRU-cached read-only connections with view registration.
- `backend/pyproject.toml` — `duckdb>=1.2.0` promoted to base; `analytics`
  kept as deprecated-empty alias.
- `backend/tests/unit/test_dashboards_scaffolding.py` — smoke test
  asserting the module loads, manifests are valid, messages round-trip,
  and snapshot storage helpers raise the right errors for unsupported
  backends.
