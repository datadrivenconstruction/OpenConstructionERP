# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A database create_all just built must not need repairing on the same boot.

A fresh 17.0.2 install logged nine ``Schema repair:`` lines on its first boot.
The nine are the columns ``formwork/repairs.py`` and ``requirements/repairs.py``
tighten: the models declared each ``nullable=False`` with a Python-side default
and no ``server_default``, so ``create_all`` built them NOT NULL and without a
DEFAULT, and :func:`app.core.not_null_repair.tighten_not_null` then read the
missing DEFAULT as the divergence it exists to close and issued ``SET DEFAULT``
for every one of them. The alembic revisions that introduced the columns do
declare a server default, so a migration-built database never showed this. The
create_all path is the one every embedded and self-hosted install boots on.

This builds its own database on the session cluster rather than using the one
the fixtures share: the data-repair tests run the same repairs against the
shared schema, so whether the nine columns still lack their DEFAULT there
depends on test order. A database nobody else has touched is the population the
defect was reported on.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.not_null_repair import tighten_not_null
from app.modules.formwork.repairs import _ASSIGNMENT, _ASSIGNMENT_COLUMNS, _SYSTEM, _SYSTEM_COLUMNS
from app.modules.requirements.repairs import _ITEM, _ITEM_COLUMNS

pytestmark = pytest.mark.asyncio

#: The three repairs' own column lists, so this test cannot drift from what the
#: boot path actually tightens.
_REPAIRED: tuple[tuple[str, dict[str, str]], ...] = (
    (_SYSTEM, _SYSTEM_COLUMNS),
    (_ASSIGNMENT, _ASSIGNMENT_COLUMNS),
    (_ITEM, _ITEM_COLUMNS),
)


@pytest.fixture
async def fresh_database(pg_engine, pg_async_url):
    """An empty database on the session cluster with the full schema built by create_all."""
    from app.database import Base

    name = f"oe_fresh_{uuid.uuid4().hex[:12]}"
    async with pg_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text(f'CREATE DATABASE "{name}"'))

    url = make_url(pg_async_url).set(database=name)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()
        async with pg_engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


async def _column_state(engine, table: str) -> dict[str, tuple[str, object]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t"
            ),
            {"t": table},
        )
        return {column: (nullable, default) for column, nullable, default in rows}


async def test_create_all_builds_the_nine_columns_with_the_default_the_repair_expects(fresh_database) -> None:
    """The schema half: what create_all emits already satisfies the repair's own check."""
    for table, columns in _REPAIRED:
        live = await _column_state(fresh_database, table)
        for column in columns:
            assert column in live, f"{table}.{column} was not created at all"
            is_nullable, default = live[column]
            assert is_nullable == "NO", f"{table}.{column} came out nullable from create_all"
            assert default is not None, (
                f"{table}.{column} came out of create_all without a DEFAULT, so the boot repair "
                "will report a schema repair on a database that is seconds old"
            )


async def test_the_first_boot_repairs_nothing_on_a_database_create_all_just_built(fresh_database, caplog) -> None:
    """The boot half: the nine repairs run and have nothing to say."""
    with caplog.at_level(logging.INFO, logger="app.core.not_null_repair"):
        async with AsyncSession(fresh_database) as session:
            rewritten = 0
            for table, columns in _REPAIRED:
                rewritten += await tighten_not_null(session, table, columns)
            await session.commit()

    repairs = [record.getMessage() for record in caplog.records if record.getMessage().startswith("Schema repair:")]
    assert rewritten == 0, "a fresh database holds no rows, so nothing can have been backfilled"
    assert repairs == [], "a database create_all just built was reported as repaired:\n" + "\n".join(repairs)
