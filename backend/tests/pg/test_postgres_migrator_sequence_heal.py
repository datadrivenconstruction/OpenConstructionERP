"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: the auto-migrator creates the sequence its own ADD COLUMN defaults from.

``oe_progress_entry.seq`` defaults from a named sequence. On a database created
before v3258 the column is absent, so the boot-time healer emits
``ALTER TABLE ... ADD COLUMN seq BIGINT NOT NULL DEFAULT nextval('oe_progress_entry_seq_seq')``
- and until this heal existed that statement failed with ``UndefinedTableError:
relation "oe_progress_entry_seq_seq" does not exist``, taking the two ``seq``
indexes and the unique constraint down with it. Every failure is logged at
WARNING and the boot continues, so the only symptom is that every read of the
progress module 500s afterwards: the ORM maps a column the table does not have.

``create_all`` runs immediately after the healer and does NOT repair this - the
sequence is column-attached, and ``create_all`` only emits column-attached
sequences from inside ``visit_table``, which it skips for a table that already
exists. The second test below holds that behaviour down, because it is what
makes the failure permanent rather than one boot long.

``test_progress_seq_migration.py`` cannot catch any of this: it drives the
Alembic migration, which creates its own sequence, so it exercises the one
schema-building path that was never broken.

Uses ``pg_engine`` rather than ``pg_session`` on purpose: the healer bounds every
DDL with ``SET LOCAL lock_timeout = '3s'``, so a test holding an open transaction
on ``oe_progress_entry`` would make it fail for a reason that has nothing to do
with sequences.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.postgres_migrator import postgres_auto_migrate
from app.database import Base

_TABLE = "oe_progress_entry"
_COLUMN = "seq"
_SEQUENCE = "oe_progress_entry_seq_seq"
_INDEXES = (
    ("ix_progress_entry_position_seq", "boq_position_id"),
    ("ix_progress_entry_project_seq", "project_id"),
)
_UNIQUE = "uq_oe_progress_entry_seq"


async def _drop_seq(conn) -> None:
    """Put the table back into its pre-v3258 shape.

    Same statements as ``test_progress_seq_migration._drop_seq``. The CASCADE
    takes the unique constraint on the column with it.
    """
    await conn.execute(text(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS {_COLUMN} CASCADE"))
    await conn.execute(text(f"DROP SEQUENCE IF EXISTS {_SEQUENCE} CASCADE"))
    for name, _column in _INDEXES:
        await conn.execute(text(f"DROP INDEX IF EXISTS {name}"))


async def _restore(conn) -> None:
    """Leave the table healed for whatever runs next, even if the test failed.

    The whole point of these tests is that the healer may not do this, so the
    teardown cannot delegate to it.
    """
    await conn.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {_SEQUENCE}"))
    await conn.execute(
        text(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS {_COLUMN} BIGINT NOT NULL DEFAULT nextval('{_SEQUENCE}')")
    )
    for name, column in _INDEXES:
        await conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {_TABLE} ({column}, {_COLUMN})"))
    # ADD CONSTRAINT has no IF NOT EXISTS.
    await conn.execute(
        text(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{_UNIQUE}') "
            f"THEN ALTER TABLE {_TABLE} ADD CONSTRAINT {_UNIQUE} UNIQUE ({_COLUMN}); END IF; END $$"
        )
    )


async def _shape(conn) -> dict:
    """What the live table actually looks like right now."""
    column_default = (
        await conn.execute(
            text("SELECT column_default FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
            {"t": _TABLE, "c": _COLUMN},
        )
    ).scalar()
    sequence = (await conn.execute(text("SELECT to_regclass(:s)"), {"s": _SEQUENCE})).scalar()
    indexes = {
        name
        for (name,) in (
            await conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = :t"), {"t": _TABLE})
        ).all()
    }
    unique = (await conn.execute(text("SELECT conname FROM pg_constraint WHERE conname = :n"), {"n": _UNIQUE})).scalar()
    return {"column_default": column_default, "sequence": sequence, "indexes": indexes, "unique": unique}


@pytest.mark.asyncio
async def test_the_healer_creates_the_sequence_before_the_column_that_needs_it(pg_engine) -> None:
    """A pre-v3258 table comes out of the heal with column, sequence and indexes."""
    async with pg_engine.begin() as conn:
        await _drop_seq(conn)
        gone = await _shape(conn)

    assert gone["column_default"] is None, "precondition: the column must be absent before the heal"
    assert gone["sequence"] is None, "precondition: the sequence must be absent before the heal"

    try:
        await postgres_auto_migrate(pg_engine, Base)

        async with pg_engine.connect() as conn:
            healed = await _shape(conn)

        assert healed["sequence"] is not None, f"{_SEQUENCE} was not created"
        assert healed["column_default"] is not None, f"{_TABLE}.{_COLUMN} was not added"
        assert f"nextval('{_SEQUENCE}'" in healed["column_default"]
        for name, _column in _INDEXES:
            assert name in healed["indexes"], f"{name} was not created"
        assert healed["unique"] == _UNIQUE, "the unique constraint on seq was not restored"
    finally:
        async with pg_engine.begin() as conn:
            await _restore(conn)


@pytest.mark.asyncio
async def test_create_all_does_not_repair_a_column_attached_sequence(pg_engine) -> None:
    """The boot after a failed heal is not a fresh start - it fails the same way.

    ``create_all`` emits standalone metadata sequences, but one attached to a
    column is only emitted while creating its table, and an existing table is
    skipped. So the sequence the healer needed is still missing on the next
    boot, and so is the column. This is a characterisation test: it holds both
    before and after the fix, and proves the severity, not the fix.
    """
    try:
        async with pg_engine.begin() as conn:
            await _drop_seq(conn)
            await conn.run_sync(Base.metadata.create_all)
            after = await _shape(conn)

        assert after["sequence"] is None, "create_all now repairs this - the heal ordering can be revisited"
        assert after["column_default"] is None
    finally:
        async with pg_engine.begin() as conn:
            await _restore(conn)
