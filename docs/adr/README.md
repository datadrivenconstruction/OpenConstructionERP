# Architecture Decision Records

This directory holds ADRs — short, timestamped records of non-obvious
architectural choices. Each file answers three questions:

1. **Context.** What problem forced the decision?
2. **Decision.** What we picked, and (briefly) why.
3. **Consequences.** What changes, what we now can't easily undo,
   and what the rollback path is.

## Index

| ID | Status | Title | Date |
|---|---|---|---|
| [001](001-snapshot-storage-model.md) | Accepted | Snapshot storage model (SQL meta + Parquet data + DuckDB queries) | 2026-04-23 |
| [002](002-no-ifcopenshell-ddc-canonical-only.md) | Accepted | No IfcOpenShell — DDC canonical format is the single source of truth | 2026-04-25 |
| [003](003-vector-match-service.md) | Accepted | Vector match service | — |
| [2026-05-28](2026-05-28-partner-pack-architecture.md) | Accepted | Partner-pack architecture (Shape A, single-tenant, entry-points) | 2026-05-28 |
| [004](004-case-role-marks-replace-portraits.md) | Accepted | Case role cells are drawn marks, not photographs | 2026-08-26 |
| [005](005-organization-is-the-tenant.md) | Accepted | The organization is the tenant | 2026-10-29 |
| [006](006-project-participant-grants.md) | Accepted | Project participant grants (stages 1-4 implemented; project-scoped-only tables remain) | 2026-10-30 |

## Writing a new ADR

- Filename: `NNN-kebab-case-title.md`, ID monotonic.
- Status: `Proposed` → `Accepted` → `Superseded by NNN` (never delete).
- Keep it short. One page is a feature, not a bug.
- Link to the files that implement the decision once they exist.
- A retired script or page gets an ADR too, including one that lives under
  a path this repository does not track. A note left in the file itself
  reaches only someone who already opened it, and nobody clones an ignored
  directory.
