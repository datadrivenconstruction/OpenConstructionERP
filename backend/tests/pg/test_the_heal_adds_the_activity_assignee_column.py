# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An install from before ``Activity.assignee_id`` gets the column on boot.

The column was added to the model without an Alembic revision. Installs are
stamped rather than migrated, so the column reaches an existing database only
if ``postgres_auto_migrate`` adds it. If it did not, every activity query would
select a column the table lacks and the schedule would fail to load, not just
show "Unassigned".

The heal is driven against a copy of the real ``oe_schedule_activity``
definition under a test-owned name, created without ``assignee_id``: the shape
of a database from before the column. Using the model's own ``Column`` objects
keeps the type and the index the ones the application declares, and the shared
schema is never touched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from app.core.postgres_migrator import postgres_auto_migrate

pytestmark = pytest.mark.asyncio

_TABLE = "oe_test_aged_schedule_activity"


def _current_model() -> SimpleNamespace:
    """The activity table as the code declares it today, under the test name."""
    from app.modules.schedule.models import Activity

    md = sa.MetaData()
    source = Activity.__table__
    sa.Table(
        _TABLE,
        md,
        # Plain copies: foreign keys and named indexes of the real table would
        # collide with or point at the shared schema.
        *[
            sa.Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable, index=c.index)
            for c in source.columns
        ],
    )
    return SimpleNamespace(metadata=md)


@pytest.fixture
async def aged_table(pg_engine):
    """The table as it stood before the assignee column, removed afterwards."""
    md = _current_model().metadata
    aged = md.tables[_TABLE]
    aged_md = sa.MetaData()
    sa.Table(
        _TABLE,
        aged_md,
        *[
            sa.Column(c.name, c.type, primary_key=c.primary_key, nullable=not c.primary_key)
            for c in aged.columns
            if c.name != "assignee_id"
        ],
    )
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))
        await conn.run_sync(aged_md.create_all)
    yield
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))


async def _columns(conn) -> set[str]:
    rows = await conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": _TABLE},
    )
    return {r[0] for r in rows}


async def test_the_assignee_column_is_added_to_an_aged_activity_table(pg_engine, aged_table) -> None:
    async with pg_engine.connect() as conn:
        assert "assignee_id" not in await _columns(conn), "the aged fixture already has the column"

    await postgres_auto_migrate(pg_engine, _current_model())

    async with pg_engine.connect() as conn:
        assert "assignee_id" in await _columns(conn)
        # The value round-trips as the model's GUID type expects.
        await conn.execute(text(f'UPDATE "{_TABLE}" SET assignee_id = NULL'))
        indexed = await conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = :t AND indexdef ILIKE '%(assignee_id)%'"),
            {"t": _TABLE},
        )
        assert indexed.first() is not None, "the column arrived without the index the model declares"
