# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The heal drops a NOT NULL it cannot honour, and now it says so.

``postgres_auto_migrate`` enforces NOT NULL on a column it is adding only when
a default exists to backfill the rows already in the table. Without one it adds
the column nullable, which is the right call - the alternative fails outright
on a populated table - but it leaves the models and the database disagreeing
about that column for the life of the install, because no revision body ever
runs to tighten it later.

Until the line under test existed, that divergence was created in total
silence. The column went in, the heal counted it as a success, and no log line,
no health field and no gate recorded that the NOT NULL had been dropped on the
way. The nearby warning in the same function is a different case: it fires when
the database *refuses* a DEFAULT, not when the models never offered one.

What is pinned here is the announcement and its aim. A warning that named every
added column, or fired on a column the models made optional, would satisfy a
test for "a warning appeared" and be useless in a boot log, so both controls
have to come out the other way.

Note the limit, which is deliberate and is why this is only half the signal:
the line fires on the boot that adds the column, not on the boots afterwards.
An install that upgraded months ago has the divergence and logs nothing about
it now. Answering "does this database match the models today" is a standing
question about the schema and needs a standing signal, not this log.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from app.core.postgres_migrator import postgres_auto_migrate

pytestmark = pytest.mark.asyncio

_TABLE = "oe_test_declined_not_null_heal"
_LOGGER = "app.core.postgres_migrator"


def _model() -> SimpleNamespace:
    """What the current code declares. ``base`` only ever has ``.metadata`` read."""
    md = sa.MetaData()
    sa.Table(
        _TABLE,
        md,
        sa.Column("id", sa.Integer, primary_key=True),
        # The divergence: NOT NULL with nothing to backfill existing rows from.
        sa.Column("needs_value", sa.String(32), nullable=False),
        # The control: NOT NULL the heal *can* honour, because the default
        # gives every existing row a value.
        sa.Column("has_default", sa.String(32), nullable=False, server_default="x"),
        # The other control: the models call this one optional, so a nullable
        # column here is agreement, not divergence.
        sa.Column("optional", sa.String(32), nullable=True),
    )
    return SimpleNamespace(metadata=md)


async def _create_aged_table(conn) -> None:
    """The shape the database is in: the table exists and holds a row."""
    await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))
    await conn.execute(text(f'CREATE TABLE "{_TABLE}" (id INTEGER NOT NULL PRIMARY KEY)'))
    # A row already in the table is the whole reason the NOT NULL cannot go on.
    # On an empty table PostgreSQL would accept it and the defect would not
    # reproduce at all.
    await conn.execute(text(f'INSERT INTO "{_TABLE}" (id) VALUES (1)'))


async def _is_nullable(conn, column: str) -> bool:
    row = await conn.execute(
        text("SELECT is_nullable FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": _TABLE, "c": column},
    )
    value = row.scalar()
    assert value is not None, f"{_TABLE}.{column} is not in the database at all"
    return value == "YES"


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING and r.name == _LOGGER]


@pytest.fixture
async def aged_table(pg_engine):
    """Create the aged table, and take it away again however the test ends."""
    async with pg_engine.begin() as conn:
        await _create_aged_table(conn)
    yield
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))


async def test_the_heal_says_it_added_a_column_without_the_not_null(pg_engine, aged_table, caplog) -> None:
    """The announcement, and the divergence it announces, measured together.

    Asserting the log alone would pass just as well if the heal had honoured
    the NOT NULL and logged about it anyway, so the live column is read back:
    the line has to be telling the truth, not merely present.
    """
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await postgres_auto_migrate(pg_engine, _model())

    said = [m for m in _warnings(caplog) if "needs_value" in m]
    assert said, f"the heal dropped a NOT NULL and said nothing; warnings were {_warnings(caplog)}"
    assert _TABLE in said[0], "the warning has to name the table, not only the column"

    async with pg_engine.connect() as conn:
        assert await _is_nullable(conn, "needs_value") is True, "the warning described a divergence that is not there"


async def test_a_not_null_the_heal_could_honour_is_not_announced(pg_engine, aged_table, caplog) -> None:
    """The control that decides whether the warning means anything.

    ``has_default`` is NOT NULL in the models too. The difference is that the
    heal can carry it, so there is nothing to report. A warning that fired on
    every NOT NULL column would turn the test above green and fill the boot log
    of a perfectly healthy install.
    """
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await postgres_auto_migrate(pg_engine, _model())

    assert not [m for m in _warnings(caplog) if "has_default" in m]

    async with pg_engine.connect() as conn:
        assert await _is_nullable(conn, "has_default") is False, "the heal failed to carry a NOT NULL it can carry"


async def test_a_column_the_models_call_optional_is_not_announced(pg_engine, aged_table, caplog) -> None:
    """The second control: nullable is only a divergence when the models disagree."""
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await postgres_auto_migrate(pg_engine, _model())

    assert not [m for m in _warnings(caplog) if "optional" in m]

    async with pg_engine.connect() as conn:
        assert await _is_nullable(conn, "optional") is True


async def test_the_boot_that_changes_nothing_says_nothing(pg_engine, aged_table, caplog) -> None:
    """Second boot is silent, and that is the limit of this signal.

    The column is already there, so nothing is added and nothing is announced -
    which is right for a line about an action, and is exactly why it cannot
    answer "is this database diverged from the models right now". Every install
    that took the divergence on an earlier release is silent here.
    """
    await postgres_auto_migrate(pg_engine, _model())
    # caplog keeps every record for the whole test, so without this the first
    # boot's warning is still sitting there and the assertion below reads it as
    # the second boot's. That is a live trap, not a hypothetical: it failed
    # exactly that way before the clear was added.
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        again = await postgres_auto_migrate(pg_engine, _model())

    assert again == 0, "the heal repeated work it had already done"
    assert not [m for m in _warnings(caplog) if "needs_value" in m]

    async with pg_engine.connect() as conn:
        assert await _is_nullable(conn, "needs_value") is True, "the divergence is still there, unannounced"
