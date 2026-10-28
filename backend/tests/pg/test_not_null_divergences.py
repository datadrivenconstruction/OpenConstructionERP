# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Does this database still match the models, and can anything say so.

``not_null_divergences`` answers the standing question. The heal's own warning
answers a different one - what this boot decided - and goes quiet on every boot
afterwards, so on an install that upgraded on an earlier release it says
nothing while the divergence is still there. The last test here is the one that
ties the two halves together: it drives the real heal into its silent path and
then asks the standing check what the database looks like afterwards.

The controls carry most of the weight. A check that reported every nullable
column, or every NOT NULL one, would satisfy the positive test and be useless.
One of them pins a limit rather than a success: the inverse divergence, where
the models allow NULL and the database refuses it, is real and is NOT reported
here, because it is a different fault with a different repair.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from app.core.postgres_migrator import not_null_divergences, postgres_auto_migrate

pytestmark = pytest.mark.asyncio

_TABLE = "oe_test_divergence_probe"
_ABSENT = "oe_test_divergence_never_built"


def _model(*, agreed_nullable: bool = True) -> SimpleNamespace:
    md = sa.MetaData()
    sa.Table(
        _TABLE,
        md,
        sa.Column("id", sa.Integer, primary_key=True),
        # The divergence: models insist, database does not.
        sa.Column("insisted", sa.String(32), nullable=False),
        # Control: both sides say NOT NULL.
        sa.Column("agreed_strict", sa.String(32), nullable=False),
        # Control: both sides allow NULL.
        sa.Column("agreed_loose", sa.String(32), nullable=agreed_nullable),
        # Control for the inverse: the models allow NULL and the live column
        # does not. A real divergence, a different one, not this function's.
        sa.Column("inverse", sa.String(32), nullable=True),
    )
    # A table the database has never built. create_all builds it correctly, so
    # it must not be reported as diverged.
    sa.Table(_ABSENT, md, sa.Column("id", sa.Integer, primary_key=True))
    return SimpleNamespace(metadata=md)


@pytest.fixture
async def live_table(pg_engine):
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))
        await conn.execute(
            text(
                f'CREATE TABLE "{_TABLE}" ('
                " id INTEGER NOT NULL PRIMARY KEY,"
                " insisted VARCHAR(32),"
                " agreed_strict VARCHAR(32) NOT NULL,"
                " agreed_loose VARCHAR(32),"
                " inverse VARCHAR(32) NOT NULL"
                ")"
            )
        )
    yield
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))


async def test_a_column_the_database_left_nullable_is_reported(pg_engine, live_table) -> None:
    found = await not_null_divergences(pg_engine, _model())
    assert f"{_TABLE}.insisted" in found


async def test_columns_both_sides_agree_about_are_not_reported(pg_engine, live_table) -> None:
    """Both directions of agreement, because either one alone lets a bug through.

    Reporting ``agreed_strict`` would mean the check fires on any NOT NULL
    column; reporting ``agreed_loose`` would mean it fires on any nullable one.
    Each would pass the positive test above on its own.
    """
    found = await not_null_divergences(pg_engine, _model())
    assert f"{_TABLE}.agreed_strict" not in found
    assert f"{_TABLE}.agreed_loose" not in found


async def test_the_inverse_divergence_is_not_reported_and_that_is_the_limit(pg_engine, live_table) -> None:
    """The models allow NULL here and the database refuses it. Also wrong, not this.

    That fault makes ordinary writes raise NotNullViolation rather than leaving
    a constraint unenforced, and the heal already repairs it by dropping the
    NOT NULL. Folding it in here would put two different faults with two
    different repairs behind one health field.
    """
    found = await not_null_divergences(pg_engine, _model())
    assert f"{_TABLE}.inverse" not in found


async def test_a_table_the_database_has_not_built_is_not_reported(pg_engine, live_table) -> None:
    """create_all builds a missing table with every constraint, so it is not diverged."""
    found = await not_null_divergences(pg_engine, _model())
    assert not [name for name in found if name.startswith(f"{_ABSENT}.")]


async def test_the_answer_is_stable_and_sorted(pg_engine, live_table) -> None:
    """Two runs have to be comparable, which means order cannot wander."""
    first = await not_null_divergences(pg_engine, _model())
    second = await not_null_divergences(pg_engine, _model())
    assert first == second
    assert list(first) == sorted(first)


async def test_the_heals_silent_path_is_exactly_what_this_reports(pg_engine) -> None:
    """The two halves, joined, on a real heal rather than a hand-built table.

    This is the case the whole pair exists for: the heal adds a NOT NULL column
    to a populated table, cannot carry the constraint, adds it nullable, and the
    standing check then names precisely that column. Without this test the two
    halves could drift into answering about different things and every other
    test here would stay green.
    """
    md = sa.MetaData()
    sa.Table(
        _TABLE,
        md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("needs_value", sa.String(32), nullable=False),
    )
    base = SimpleNamespace(metadata=md)

    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))
        await conn.execute(text(f'CREATE TABLE "{_TABLE}" (id INTEGER NOT NULL PRIMARY KEY)'))
        await conn.execute(text(f'INSERT INTO "{_TABLE}" (id) VALUES (1)'))

    try:
        before = await not_null_divergences(pg_engine, base)
        assert f"{_TABLE}.needs_value" not in before, "the column is not there yet, so it cannot be diverged yet"

        await postgres_auto_migrate(pg_engine, base)

        after = await not_null_divergences(pg_engine, base)
        assert f"{_TABLE}.needs_value" in after, "the heal left the divergence and the standing check missed it"
    finally:
        async with pg_engine.begin() as conn:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))
