# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Index healing in :func:`app.core.postgres_migrator.postgres_auto_migrate`.

Upgraded embedded-PG installs stamp alembic instead of running it, so an
index added in a later release (e.g. ``ix_oe_costs_item_catalog_id``) never
materialises via ``create_all`` - the largest table then seq-scans forever.
These tests pin the heal: missing single- and multi-column model-declared
indexes are recreated via ``CREATE INDEX IF NOT EXISTS``, counted in the
return value, and the function stays a no-op on a current schema.

Uses a throwaway schema-loaded database (``tests._pg.isolated_engine``)
because the heal mutates the schema itself, which must not leak into the
shared transactional unit database.

Run:
    cd backend
    python -m pytest tests/unit/test_postgres_migrator_indexes.py -v --tb=short
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests._pg import isolated_engine

_TABLE = "oe_costs_item"
_SINGLE_COL_INDEX = "ix_oe_costs_item_catalog_id"  # catalog_id (index=True)
_MULTI_COL_INDEX = "ix_costs_active_code"  # Index("ix_costs_active_code", "is_active", "code")


async def _index_names(engine: AsyncEngine, table: str) -> set[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(lambda sync_conn: {ix["name"] for ix in inspect(sync_conn).get_indexes(table)})


@pytest.mark.asyncio
async def test_auto_migrate_recreates_missing_indexes() -> None:
    from app.core.postgres_migrator import postgres_auto_migrate
    from app.database import Base

    async with isolated_engine() as engine:
        before = await _index_names(engine, _TABLE)
        assert _SINGLE_COL_INDEX in before
        assert _MULTI_COL_INDEX in before

        # Simulate an upgraded install whose older schema predates the
        # indexes: drop them, then heal.
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP INDEX "{_SINGLE_COL_INDEX}"'))
            await conn.execute(text(f'DROP INDEX "{_MULTI_COL_INDEX}"'))

        added = await postgres_auto_migrate(engine, Base)
        assert added >= 2  # at least the two dropped indexes

        after = await _index_names(engine, _TABLE)
        assert _SINGLE_COL_INDEX in after
        assert _MULTI_COL_INDEX in after


@pytest.mark.asyncio
async def test_auto_migrate_noop_on_current_schema() -> None:
    """A schema built by create_all needs neither columns nor indexes."""
    from app.core.postgres_migrator import postgres_auto_migrate
    from app.database import Base

    async with isolated_engine() as engine:
        assert await postgres_auto_migrate(engine, Base) == 0
