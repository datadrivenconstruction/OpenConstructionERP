"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: the boot heal numbers ``seq`` by heap order, and the fixup puts it back.

``app.core.postgres_migrator`` adds ``oe_progress_entry.seq`` to a pre-v3258
table with ``ADD COLUMN ... DEFAULT nextval(...)``, which PostgreSQL evaluates
while rewriting the table - so the rows come out numbered in the order they
happen to lie on disk. The Alembic migration numbers the same rows by
``recorded_at, created_at, id``. Every "latest wins" query in the progress
repository leads with ``seq``, so until this fixup existed the same three rows
reported a different current reading depending on which path built the schema.

The first test drives the REAL heal rather than re-typing its ALTER statement:
the claim under test is what ``postgres_auto_migrate`` does to real rows, and a
test that issued its own ADD COLUMN would measure the test's SQL instead. It
uses ``pg_engine`` because the heal bounds every DDL with ``SET LOCAL
lock_timeout = '3s'`` and would fail against a test holding the table open.

The rest reach the same broken STATE the cheap way - rows whose ``recorded_at``
runs against their insertion order, which is what heap-order numbering leaves
behind - so they run inside the rolled-back ``pg_session``.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.postgres_migrator import postgres_auto_migrate
from app.database import Base
from app.modules.progress.models import ProgressEntry
from app.modules.progress.repository import ProgressRepository
from app.modules.progress.seq_repair import repair_progress_entry_seq
from app.modules.projects.models import Project
from app.modules.users.models import User

_TABLE = "oe_progress_entry"
_SEQUENCE = "oe_progress_entry_seq_seq"
_UNIQUE = "uq_oe_progress_entry_seq"
_INDEXES = (
    ("ix_progress_entry_position_seq", "boq_position_id"),
    ("ix_progress_entry_project_seq", "project_id"),
)
_PERIOD = "2026-W21"

_MIGRATION = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3258_progress_entry_seq.py"

_INSERT_ENTRY = text(
    "INSERT INTO oe_progress_entry "
    "(id, project_id, period_label, percent_complete, recorded_at, photos, metadata, created_at, updated_at) "
    "VALUES (:i, :p, :l, :c, :r, '[]', '{}', :t, :t)"
)

# Physical order deliberately disagrees with observation order: the reading
# OBSERVED last is written first. This is the shape measured on 2026-08-01.
_HISTORY = ((90.0, 2), (10.0, 0), (50.0, 1))


async def _drop_seq(executor) -> None:
    """Put the table back into its pre-v3258 shape (CASCADE takes the constraint)."""
    await executor.execute(text(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS seq CASCADE"))
    await executor.execute(text(f"DROP SEQUENCE IF EXISTS {_SEQUENCE} CASCADE"))
    for name, _column in _INDEXES:
        await executor.execute(text(f"DROP INDEX IF EXISTS {name}"))


async def _restore(conn) -> None:
    """Leave the shared schema healed even when the test failed before the heal ran."""
    await conn.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {_SEQUENCE}"))
    await conn.execute(
        text(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS seq BIGINT NOT NULL DEFAULT nextval('{_SEQUENCE}')")
    )
    for name, column in _INDEXES:
        await conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {_TABLE} ({column}, seq)"))
    # ADD CONSTRAINT has no IF NOT EXISTS.
    await conn.execute(
        text(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{_UNIQUE}') "
            f"THEN ALTER TABLE {_TABLE} ADD CONSTRAINT {_UNIQUE} UNIQUE (seq); END IF; END $$"
        )
    )


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Create the owner and project the entries hang off. Returns ``(project, owner)``."""
    owner = User(email=f"seqfix-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(name="Seq repair project", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project.id, owner.id


async def _write_history(executor, project_id: uuid.UUID) -> None:
    """Write the three readings in an insertion order that contradicts their timestamps."""
    base = datetime.now(UTC) - timedelta(days=1)
    for percent, hours in _HISTORY:
        await executor.execute(
            _INSERT_ENTRY,
            {
                "i": str(uuid.uuid4()),
                "p": str(project_id),
                "l": _PERIOD,
                "c": percent,
                "r": base + timedelta(hours=hours),
                "t": base + timedelta(hours=hours),
            },
        )


async def _in_seq_order(executor, project_id: uuid.UUID) -> list[float]:
    """The project's readings, lowest ``seq`` first."""
    rows = (
        await executor.execute(
            text(f"SELECT percent_complete FROM {_TABLE} WHERE project_id = :p ORDER BY seq"),  # noqa: S608
            {"p": str(project_id)},
        )
    ).all()
    return [float(pct) for (pct,) in rows]


async def _seq_values(executor, project_id: uuid.UUID) -> list[int]:
    rows = (
        await executor.execute(
            text(f"SELECT seq FROM {_TABLE} WHERE project_id = :p ORDER BY seq"),  # noqa: S608
            {"p": str(project_id)},
        )
    ).all()
    return [int(seq) for (seq,) in rows]


async def _headline_pct(session: AsyncSession, project_id: uuid.UUID) -> float:
    """What the module actually reports: the winner of the seq-led "latest wins" query."""
    series = await ProgressRepository(session).project_level_pct_by_period(project_id)
    return series[0][1]


async def _cleanup(conn, project_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    """Committed rows have to go: this lane shares one cluster across the session."""
    await conn.execute(text(f"DELETE FROM {_TABLE} WHERE project_id = :p"), {"p": str(project_id)})  # noqa: S608
    await conn.execute(text("DELETE FROM oe_projects_project WHERE id = :p"), {"p": str(project_id)})
    await conn.execute(text("DELETE FROM oe_users_user WHERE id = :o"), {"o": str(owner_id)})


def _load_migration():
    """Import the migration module by path (it is not on the import path)."""
    spec = importlib.util.spec_from_file_location("mig_v3258_fixup", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run_migration(session: AsyncSession) -> None:
    """Execute the real ``upgrade()`` against this test's connection."""
    connection = await session.connection()

    def _apply(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            _load_migration().upgrade()

    await connection.run_sync(_apply)


@pytest.mark.asyncio
async def test_the_fixup_reorders_what_the_real_heal_numbered_by_heap(pg_engine) -> None:
    """End to end: heal a pre-v3258 table, then repair the order the heal produced."""
    async with pg_engine.begin() as conn:
        await _drop_seq(conn)
        # Committing through a savepoint-joined session keeps the seeded rows
        # in the surrounding transaction instead of rolling them back on close.
        async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint") as session:
            project_id, owner_id = await _seed_project(session)
            await session.commit()
        await _write_history(conn, project_id)

    try:
        await postgres_auto_migrate(pg_engine, Base)

        async with AsyncSession(pg_engine) as session:
            healed = await _in_seq_order(session, project_id)
            healed_headline = await _headline_pct(session, project_id)

        # Precondition, and the bug itself: the heal numbered the rows where
        # they sit on disk, so the reading recorded FIRST is reported as
        # current and the latest observation is buried.
        assert healed == [90.0, 10.0, 50.0], "precondition: the heal must number in heap order"
        assert healed_headline == 50.0

        async with pg_engine.begin() as conn:
            total = (await conn.execute(text(f"SELECT count(*) FROM {_TABLE}"))).scalar()  # noqa: S608
            renumbered = await repair_progress_entry_seq(conn)

        assert renumbered == total, "the renumber covers the table, not a subset"

        async with AsyncSession(pg_engine) as session:
            assert await _in_seq_order(session, project_id) == [10.0, 50.0, 90.0]
            # The query the progress page runs now answers with the latest
            # observation, exactly as it does on an Alembic-built database.
            assert await _headline_pct(session, project_id) == 90.0
    finally:
        async with pg_engine.begin() as conn:
            await _cleanup(conn, project_id, owner_id)
            await _restore(conn)


@pytest.mark.asyncio
async def test_a_reading_recorded_after_the_repair_wins(pg_session) -> None:
    """The sequence is parked above every renumbered row, so the next INSERT wins.

    This is the assertion the other tests cannot make: they all pass with a
    sequence left pointing below ``MAX(seq)``, where the next reading either
    collides with a number a row already holds or lands beneath the history it
    is supposed to top.
    """
    project_id, _owner_id = await _seed_project(pg_session)
    await _write_history(pg_session, project_id)

    assert await repair_progress_entry_seq(await pg_session.connection()) > 0
    highest_before = max(await _seq_values(pg_session, project_id))

    pg_session.add(ProgressEntry(project_id=project_id, period_label=_PERIOD, percent_complete=30.0))
    await pg_session.flush()

    fresh = (
        await pg_session.execute(
            text(f"SELECT seq FROM {_TABLE} WHERE project_id = :p AND percent_complete = 30"),  # noqa: S608
            {"p": str(project_id)},
        )
    ).scalar()
    assert int(fresh) > highest_before, "a reading written after the repair must outrank the repaired rows"
    assert await _headline_pct(pg_session, project_id) == 30.0


@pytest.mark.asyncio
async def test_a_second_run_finds_nothing_to_do(pg_session) -> None:
    """Idempotent, because it runs on every boot."""
    project_id, _owner_id = await _seed_project(pg_session)
    await _write_history(pg_session, project_id)

    assert await repair_progress_entry_seq(await pg_session.connection()) > 0
    after_first = await _seq_values(pg_session, project_id)

    assert await repair_progress_entry_seq(await pg_session.connection()) == 0
    assert await _seq_values(pg_session, project_id) == after_first


@pytest.mark.asyncio
async def test_the_fixup_leaves_an_alembic_numbered_table_alone(pg_session) -> None:
    """The migration already numbers by observation order, so there is nothing to repair."""
    await _drop_seq(pg_session)
    project_id, _owner_id = await _seed_project(pg_session)
    await _write_history(pg_session, project_id)
    await _run_migration(pg_session)

    numbered = await _seq_values(pg_session, project_id)
    assert await _in_seq_order(pg_session, project_id) == [10.0, 50.0, 90.0]

    assert await repair_progress_entry_seq(await pg_session.connection()) == 0
    assert await _seq_values(pg_session, project_id) == numbered


@pytest.mark.asyncio
async def test_a_batch_written_in_one_transaction_is_not_a_divergence(pg_session) -> None:
    """Rows that tie on both timestamps keep the only order that separates them.

    A bulk write - the demo seeder, an import - lands every row with the same
    ``recorded_at`` (PostgreSQL's ``now()`` is the TRANSACTION timestamp) and
    the same ``created_at`` on a coarse clock. Their observation order is then
    decided by ``id``, a random uuid4, while ``seq`` holds the order they were
    actually written in. Detection counts STRICT descents for exactly that
    reason: a tied group is not evidence of anything, and renumbering it would
    trade insertion order for a coin toss on a database that never diverged.

    The ids below descend as the rows are written, so a renumber that reached
    this batch would demonstrably reverse it.
    """
    project_id, _owner_id = await _seed_project(pg_session)

    stamped = datetime.now(UTC) - timedelta(hours=3)
    for index in range(4):
        await pg_session.execute(
            _INSERT_ENTRY,
            {
                "i": f"00000000-0000-4000-8000-00000000000{9 - index}",
                "p": str(project_id),
                "l": _PERIOD,
                "c": 10.0 * (index + 1),
                "r": stamped,
                "t": stamped,
            },
        )

    written = await _in_seq_order(pg_session, project_id)
    assert written == [10.0, 20.0, 30.0, 40.0], "precondition: seq holds the order the rows were written in"

    assert await repair_progress_entry_seq(await pg_session.connection()) == 0
    assert await _in_seq_order(pg_session, project_id) == written
