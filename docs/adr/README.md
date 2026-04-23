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

## Writing a new ADR

- Filename: `NNN-kebab-case-title.md`, ID monotonic.
- Status: `Proposed` → `Accepted` → `Superseded by NNN` (never delete).
- Keep it short. One page is a feature, not a bug.
- Link to the files that implement the decision once they exist.
