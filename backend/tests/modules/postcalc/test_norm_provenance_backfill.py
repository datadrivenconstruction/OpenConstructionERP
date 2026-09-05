# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The v3320 backfill, run against real PostgreSQL rather than read.

The write side of the norm provenance shipped before the column existed, so
there is a window of bills that carry ``metadata["norm_id"]`` against a NULL
column. v3320 copies them across, and the statements it uses cannot be checked
by reading them: they are raw SQL, they use PostgreSQL JSON operators, and the
one thing most likely to be wrong about them is a type that only the database
knows.

That is not hypothetical here, and the trap is subtler than it first looks.
``app.database.GUID`` is a TypeDecorator over ``String(36)`` on every dialect -
no ``load_dialect_impl``, never a native ``uuid`` - so ``norm_id`` is a
``varchar(36)``. From which it is easy to conclude that the obvious backfill,
``SET norm_id = (metadata ->> 'norm_id')::uuid``, would be rejected. It is not:
uuid to text is an assignment cast in PostgreSQL and the statement runs fine.
Reasoning about the types gave the wrong answer in both directions, which is the
argument for these tests rather than for a closer reading.

What the cast really costs shows up on bad input: it raises, inside the single
transaction that wraps the whole upgrade, on any metadata value that is not a
uuid - and metadata is free-form JSON that clients write. The predicate the
revision ships skips those rows instead, and the parametrised case below is what
holds it to that.

So these tests import the statements the revision actually ships and execute
them. Importing rather than restating is the point: a copy pasted into a test
goes on passing after the revision it was copied from has been changed.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from tests._pg import transactional_session

_REVISION = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "v3320_boq_position_norm_provenance.py"


def _load_revision():
    """Import the revision module by path.

    ``alembic/versions`` is not an importable package, so the usual import
    statement cannot reach it and this is how the revision's own loader gets at
    it too.
    """
    spec = importlib.util.spec_from_file_location("v3320_under_test", _REVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REVISION = _load_revision()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def seed(session: AsyncSession, metadata: dict) -> Position:
    boq = BOQ(project_id=uuid.uuid4(), name="Bill of quantities", description="")
    session.add(boq)
    await session.flush()
    position = Position(
        boq_id=boq.id,
        ordinal="1.1",
        description="Internal plastering",
        unit="m2",
        quantity="100",
        unit_rate="16.20",
        total="1620.00",
        source="assembly",
        metadata_=metadata,
    )
    session.add(position)
    await session.flush()
    # The column starts NULL: this is a row from before v3320 existed.
    assert position.norm_id is None
    return position


async def run_backfill(session: AsyncSession) -> None:
    """Execute exactly the statements the revision ships."""
    await session.execute(text(REVISION._BACKFILL_NORM_ID_SQL))
    await session.execute(text(REVISION._BACKFILL_WORK_KEY_SQL))
    await session.flush()


async def read_back(session: AsyncSession, position_id) -> tuple[str | None, str | None]:
    row = (
        await session.execute(
            text("SELECT norm_id, norm_work_key FROM oe_boq_position WHERE id = :id"),
            {"id": str(position_id)},
        )
    ).first()
    assert row is not None
    return row[0], row[1]


class TestTheStatementsRunAtAllOnPostgres:
    """The half a reading review cannot do."""

    async def test_a_row_from_before_the_column_is_carried_across(self, session: AsyncSession) -> None:
        norm_id = uuid.uuid4()
        position = await seed(
            session,
            {
                "assembly_id": str(uuid.uuid4()),
                "norm_id": str(norm_id),
                "work_key": "plastering_internal",
            },
        )

        await run_backfill(session)

        stored_id, stored_key = await read_back(session, position.id)
        assert stored_id == str(norm_id)
        assert stored_key == "plastering_internal"

    async def test_the_stored_form_matches_what_the_application_writes(self, session: AsyncSession) -> None:
        """An upper-case id in the metadata must not become a second identity.

        ``str(uuid.UUID(...))`` is lower case and that is what the application
        puts in the column. A backfilled row that kept an upper-case spelling
        would be a different string to every SQL grouping, and the norm would
        appear twice in a report with its work split between the two.
        """
        norm_id = uuid.uuid4()
        position = await seed(session, {"norm_id": str(norm_id).upper(), "work_key": "brickwork"})

        await run_backfill(session)

        stored_id, _ = await read_back(session, position.id)
        assert stored_id == str(norm_id)


class TestWhatItLeavesAlone:
    async def test_a_position_with_no_norm_is_untouched(self, session: AsyncSession) -> None:
        position = await seed(session, {"assembly_id": str(uuid.uuid4())})
        await run_backfill(session)
        assert await read_back(session, position.id) == (None, None)

    @pytest.mark.parametrize("junk", ["", "not-a-uuid", "12345", "None"])
    async def test_an_unparseable_id_is_not_written(self, session: AsyncSession, junk: str) -> None:
        """Metadata is free-form JSON that clients write, so it holds anything.

        The regex guard is what keeps a malformed id out of a column typed to
        hold one, and it has to be a guard rather than a cast: the column is
        varchar, so an unguarded copy would store the junk happily and the
        report would carry a norm nobody can look up.
        """
        position = await seed(session, {"norm_id": junk, "work_key": "brickwork"})
        await run_backfill(session)
        assert await read_back(session, position.id) == (None, None)

    async def test_a_work_key_without_an_id_is_not_written(self, session: AsyncSession) -> None:
        """The two columns may never disagree about whether there is a norm."""
        position = await seed(session, {"work_key": "plastering_internal"})
        await run_backfill(session)
        assert await read_back(session, position.id) == (None, None)

    async def test_running_it_twice_changes_nothing(self, session: AsyncSession) -> None:
        """An operator who runs the upgrade by hand after a boot heal did it."""
        norm_id = uuid.uuid4()
        position = await seed(session, {"norm_id": str(norm_id), "work_key": "plastering_internal"})

        await run_backfill(session)
        first = await read_back(session, position.id)
        await run_backfill(session)

        assert await read_back(session, position.id) == first

    async def test_a_row_the_application_already_filled_in_is_not_rewritten(self, session: AsyncSession) -> None:
        """The backfill repairs the gap; it does not overrule the writer."""
        written = uuid.uuid4()
        stale = uuid.uuid4()
        position = await seed(session, {"norm_id": str(stale), "work_key": "stale"})
        position.norm_id = written
        position.norm_work_key = "written_by_the_application"
        await session.flush()

        await run_backfill(session)

        assert await read_back(session, position.id) == (str(written), "written_by_the_application")


class TestTheGuardsOnTheStatementsThemselves:
    async def test_a_work_key_longer_than_the_column_is_truncated_not_rejected(self, session: AsyncSession) -> None:
        """A 400-character key would abort the whole upgrade transaction.

        The column is 120 characters, matching the norm library's own, so a key
        that fits in the library fits here. Metadata is not the library and can
        hold a longer string, and a value error inside ``upgrade()`` rolls back
        every revision in the run rather than this one.
        """
        norm_id = uuid.uuid4()
        position = await seed(session, {"norm_id": str(norm_id), "work_key": "x" * 400})

        await run_backfill(session)

        stored_id, stored_key = await read_back(session, position.id)
        assert stored_id == str(norm_id)
        assert stored_key == "x" * 120
