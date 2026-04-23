"""Dashboards module — analytical layer over snapshots.

Tasks in scope (see ``CLAUDE-DASHBOARDS.md`` in the repo root):
    T01 Data Snapshot Registry
    T02 Quick-Insight Panel
    T03 Smart Value Autocomplete
    T04 Cascade Filter Engine
    T05 Dashboards & Collections
    T06 Tabular Data I/O
    T07 Dataset Integrity Overview
    T09 Model-Dashboard Sync Protocol
    T10 Multi-Source Project Federation
    T11 Historical Snapshot Navigator

Architecture overview (ADR-001): SQLAlchemy + alembic for metadata, the
configured ``StorageBackend`` for Parquet blobs, DuckDB read-only
connection pool for analytical queries.
"""
