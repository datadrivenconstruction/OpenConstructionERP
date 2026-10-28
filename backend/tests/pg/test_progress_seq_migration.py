"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: migration ``v3258_progress_entry_seq`` actually runs, and backfills in order.

Every "latest wins" query in the progress module now leads with ``seq``, so a
migration that fails, or that numbers historical rows in the wrong order, is not
a schema inconvenience - it silently changes which reading the page reports.

The tests below execute the real migration file against a real table holding
real rows. They do not re-implement its SQL: re-running the same UPDATE inside
the test body would measure the test's arithmetic twice and the migration zero
times.

Two properties matter and neither is visible from reading the file:

* the backfill follows ``recorded_at, created_at, id`` rather than physical row
  order, so the rows are seeded in a deliberately wrong physical order;
* the sequence restarts ABOVE the highest backfilled value, so the first row
  written after the migration does not collide at 1.

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

from app.modules.projects.models import Project
from app.modules.users.models import User

_MIGRATION = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3258_progress_entry_seq.py"

_INSERT_ENTRY = text(
    "INSERT INTO oe_progress_entry "
    "(id, project_id, period_label, percent_complete, recorded_at, photos, metadata, created_at, updated_at) "
    "VALUES (:i, :p, :l, :c, :r, '[]', '{}', now(), now())"
)


def _load_migration():
    """Import the migration module by path (it is not on the import path)."""
    spec = importlib.util.spec_from_file_location("mig_v3258", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _drop_seq(session) -> None:
    """Return the table to its pre-migration shape."""
    await session.execute(text("ALTER TABLE oe_progress_entry DROP COLUMN seq CASCADE"))
    await session.execute(text("DROP SEQUENCE IF EXISTS oe_progress_entry_seq_seq CASCADE"))
    for name in ("ix_progress_entry_position_seq", "ix_progress_entry_project_seq"):
        await session.execute(text(f"DROP INDEX IF EXISTS {name}"))


async def _seed_project(session) -> uuid.UUID:
    owner = User(email=f"seqmig-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(name="Migration project", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project.id


async def _run_migration(session) -> None:
    """Execute the real ``upgrade()`` against this test's connection."""
    connection = await session.connection()

    def _apply(sync_connection) -> None:
        context = MigrationContext.configure(sync_connection)
        with Operations.context(context):
            _load_migration().upgrade()

    await connection.run_sync(_apply)


@pytest.mark.asyncio
async def test_the_backfill_numbers_rows_by_observation_order(pg_session) -> None:
    """Historical rows are numbered by recorded_at, not by where they sit on disk."""
    await _drop_seq(pg_session)
    project_id = await _seed_project(pg_session)

    # Physical order is deliberately wrong: the NEWEST observation is inserted
    # first. A backfill that followed insertion order would invert the history.
    base = datetime.now(UTC)
    for percent, recorded_at in ((90.0, base + timedelta(hours=2)), (10.0, base), (50.0, base + timedelta(hours=1))):
        await pg_session.execute(
            _INSERT_ENTRY,
            {
                "i": str(uuid.uuid4()),
                "p": str(project_id),
                "l": "2026-W21",
                "c": percent,
                "r": recorded_at,
            },
        )

    await _run_migration(pg_session)

    rows = (await pg_session.execute(text("SELECT percent_complete, seq FROM oe_progress_entry ORDER BY seq"))).all()
    assert [float(percent) for percent, _seq in rows] == [10.0, 50.0, 90.0]
    assert [seq for _percent, seq in rows] == [1, 2, 3]


@pytest.mark.asyncio
async def test_the_sequence_restarts_above_the_backfilled_rows(pg_session) -> None:
    """A row written after the migration must not collide with a backfilled one."""
    await _drop_seq(pg_session)
    project_id = await _seed_project(pg_session)

    base = datetime.now(UTC)
    for index in range(3):
        await pg_session.execute(
            _INSERT_ENTRY,
            {
                "i": str(uuid.uuid4()),
                "p": str(project_id),
                "l": "2026-W21",
                "c": 10.0 * index,
                "r": base + timedelta(hours=index),
            },
        )

    await _run_migration(pg_session)

    await pg_session.execute(
        _INSERT_ENTRY,
        {
            "i": str(uuid.uuid4()),
            "p": str(project_id),
            "l": "2026-W22",
            "c": 30.0,
            "r": base + timedelta(days=7),
        },
    )

    new_seq = (
        await pg_session.execute(text("SELECT seq FROM oe_progress_entry WHERE period_label = '2026-W22'"))
    ).scalar()
    assert new_seq == 4


@pytest.mark.asyncio
async def test_running_the_migration_twice_is_a_no_op(pg_session) -> None:
    """Inspector-guarded, so an already-migrated database is left alone."""
    await _drop_seq(pg_session)
    project_id = await _seed_project(pg_session)
    await pg_session.execute(
        _INSERT_ENTRY,
        {
            "i": str(uuid.uuid4()),
            "p": str(project_id),
            "l": "2026-W21",
            "c": 42.0,
            "r": datetime.now(UTC),
        },
    )

    await _run_migration(pg_session)
    await _run_migration(pg_session)

    rows = (await pg_session.execute(text("SELECT seq FROM oe_progress_entry"))).all()
    assert [seq for (seq,) in rows] == [1]
