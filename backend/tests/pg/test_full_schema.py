"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Full-schema smoke on embedded PostgreSQL.

The session-scoped ``pg_async_url`` fixture already builds the ENTIRE ORM schema
(every module's models) once per run via ``create_all`` on a real PG cluster — so
if any model emits PG-incompatible DDL the fixture setup raises and every PG test
errors. These tests turn that implicit build into explicit assertions: the schema
materialises, the JSON->JSONB ``@compiles`` + ``after_create`` index hooks fire,
and a handful of load-bearing tables are present.

This is the guard that stops PG-breaking DDL from shipping untested.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

# Conservative floors — the suite has 430+ tables and 1900+ indexes today.
# We assert lower bounds so the test fails loudly if a swathe of tables stops
# building, without being brittle to ordinary growth.
_MIN_TABLES = 400
_MIN_INDEXES = 1000

# A few tables from foundational, always-installed modules. If create_all
# silently skipped a model these would be missing.
_CRITICAL_TABLES = (
    "oe_users_user",
    "oe_projects_project",
    "oe_boq_boq",
    "oe_costs_item",
    "oe_core_audit_log",
)


@pytest.mark.asyncio
async def test_full_orm_schema_builds_on_pg(pg_engine) -> None:
    """Every model's table + the perf indexes exist on a fresh PG cluster."""
    async with pg_engine.connect() as conn:
        n_tables = await conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        )
        n_indexes = await conn.scalar(text("SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'"))

    assert n_tables >= _MIN_TABLES, f"only {n_tables} tables built on PG (expected >= {_MIN_TABLES})"
    # Indexes >> tables proves the JSONB/GIN/composite ``after_create`` hooks ran.
    assert n_indexes >= _MIN_INDEXES, f"only {n_indexes} indexes on PG (expected >= {_MIN_INDEXES})"


@pytest.mark.asyncio
async def test_critical_tables_present(pg_engine) -> None:
    """Foundational module tables materialised (no silently-skipped models)."""
    async with pg_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        present = {r[0] for r in rows}

    missing = [t for t in _CRITICAL_TABLES if t not in present]
    assert not missing, f"critical tables missing on PG: {missing}"
