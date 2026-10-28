# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A revision that widens a column never ran, so the heal has to do it.

What runs on upgrade for most installs is ``postgres_auto_migrate``, not the
migration chain. Until now it only ever added things, so a revision whose whole
content was ``ALTER COLUMN ... DROP NOT NULL`` had no effect on any of those
installs. The old constraint survived, the models went on declaring the value
optional, and the first ordinary write that left it empty raised
NotNullViolation from inside a request that had already written its row.

That is not hypothetical. It shipped: ``oe_supplier_catalogs_stock_movement``
and ``oe_supplier_catalogs_stock_balance`` both carry a cost column the models
made optional, and on an upgraded database both were still NOT NULL.

These drive the real heal against a metadata built here rather than against
``Base``. Both sides of the comparison then belong to the test, so the aged
shape is exact, the count is exact, and nothing in the shared cluster is
disturbed. The end-to-end proof on a genuinely aged database is the upgrade
lane; what is pinned here is the mechanism and, in particular, that it refuses
the one column PostgreSQL would reject it on.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from app.core.postgres_migrator import postgres_auto_migrate

pytestmark = pytest.mark.asyncio

_TABLE = "oe_test_widened_column_heal"


def _model(*, id_is_primary_key: bool = True, widened_nullable: bool = True) -> SimpleNamespace:
    """What the current code declares. ``base`` only ever has ``.metadata`` read."""
    md = sa.MetaData()
    sa.Table(
        _TABLE,
        md,
        sa.Column("id", sa.Integer, primary_key=id_is_primary_key, nullable=not id_is_primary_key),
        sa.Column("widened", sa.Numeric(18, 4), nullable=widened_nullable),
        sa.Column("untouched", sa.Integer, nullable=False),
    )
    return SimpleNamespace(metadata=md)


async def _create_aged_table(conn) -> None:
    """The shape the database is actually in: ``widened`` is still NOT NULL."""
    await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))
    await conn.execute(
        text(
            f'CREATE TABLE "{_TABLE}" ('
            " id INTEGER NOT NULL PRIMARY KEY,"
            " widened NUMERIC(18, 4) NOT NULL,"
            " untouched INTEGER NOT NULL"
            ")"
        )
    )


async def _is_nullable(conn, column: str) -> bool:
    row = await conn.execute(
        text("SELECT is_nullable FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": _TABLE, "c": column},
    )
    value = row.scalar()
    assert value is not None, f"{_TABLE}.{column} is not in the database at all"
    return value == "YES"


@pytest.fixture
async def aged_table(pg_engine):
    """Create the aged table, and take it away again however the test ends."""
    async with pg_engine.begin() as conn:
        await _create_aged_table(conn)
    yield
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))


async def test_a_column_the_models_widened_is_relaxed(pg_engine, aged_table) -> None:
    """The repair itself, with the count measured rather than assumed."""
    async with pg_engine.connect() as conn:
        assert await _is_nullable(conn, "widened") is False, "the aged fixture did not come up NOT NULL"

    repairs = await postgres_auto_migrate(pg_engine, _model())

    async with pg_engine.connect() as conn:
        assert await _is_nullable(conn, "widened") is True
        # Exactly the one column, and nothing swept up alongside it. A pass that
        # relaxed every column would satisfy the line above and be a far worse
        # bug than the one being fixed.
        assert await _is_nullable(conn, "untouched") is False
        assert await _is_nullable(conn, "id") is False

    assert repairs == 1, f"expected exactly one repair on this table, got {repairs}"


async def test_a_database_that_already_agrees_is_left_alone(pg_engine, aged_table) -> None:
    """The control that has to come out the other way.

    A pass that emitted its statement unconditionally would turn the test above
    green while being wrong on every boot of every healthy install. Running it
    twice is also the idempotence check: the second call has nothing to do.
    """
    first = await postgres_auto_migrate(pg_engine, _model())
    second = await postgres_auto_migrate(pg_engine, _model())

    assert first == 1
    assert second == 0, "the heal repeated work it had already done"


async def test_the_primary_key_is_refused_even_when_the_model_says_nullable(pg_engine, aged_table) -> None:
    """PostgreSQL rejects DROP NOT NULL on a primary key, so it is never attempted.

    The model here does not mark ``id`` as the primary key, but the live database
    does. That is the case the guard exists for: on an aged database the two
    definitions can disagree, and reading the model alone would emit a statement
    the server refuses. The table is left intact either way, because every
    statement runs in its own SAVEPOINT, so what this pins is that the column
    keeps its NOT NULL and the repair is not counted.
    """
    repairs = await postgres_auto_migrate(pg_engine, _model(id_is_primary_key=False))

    async with pg_engine.connect() as conn:
        assert await _is_nullable(conn, "id") is False, "a primary key was relaxed"
        assert await _is_nullable(conn, "widened") is True

    # One repair, and it is the ordinary column. The primary key contributed none.
    assert repairs == 1


async def test_the_two_columns_that_shipped_wrong_are_optional_in_the_models() -> None:
    """The models are the side that has to keep saying these are optional.

    The heal above only relaxes what the models declare nullable, so if either
    column were ever re-tightened, the repair would silently stop happening and
    the upgrade lane would go green while upgraded installs kept failing. This is
    a cheap tripwire on that, read from the real metadata.
    """
    from app.database import Base

    tables = Base.metadata.tables
    for table_name, column_name in (
        ("oe_supplier_catalogs_stock_movement", "unit_cost"),
        ("oe_supplier_catalogs_stock_balance", "unit_cost_avg"),
    ):
        column = tables[table_name].columns[column_name]
        assert column.nullable is True, f"{table_name}.{column_name} is no longer optional in the models"
