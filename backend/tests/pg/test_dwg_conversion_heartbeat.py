# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A running conversion must not be declared dead, and reading must not write.

Issue #409. The orphan detector used to ask "has this taken too long?" and
treat the answer as "is the task that owns it gone?". Those are different
questions and elapsed time cannot separate them, because the work has no upper
bound to compare against: the DDC subprocess is capped, but the xlsx parse
after it has no timeout and its cost tracks the size of the drawing. Measured
on a 200,000 row export that parse alone took 86 seconds.

So a large drawing crossed the cutoff while converting normally, and was told
it was dead. The message it was given asked the user to delete the drawing and
upload it again, and deleting was the one operation blocked at that moment by
the conversion's own row lock. The advice on screen and the state of the
system were in direct contradiction.

These live in the PostgreSQL lane because that is the only lane that gates
anything, and because two of them need a second connection to prove that a
read really did leave the row alone.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.dwg_takeoff.models  # noqa: F401  (ORM registration)
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from app.modules.dwg_takeoff import service as dwg_service
from app.modules.dwg_takeoff.models import DwgDrawing, DwgDrawingVersion
from app.modules.dwg_takeoff.service import DwgTakeoffService
from tests._pg import isolated_engine

_TABLE = "oe_dwg_takeoff_drawing"

# Comfortably past ``_legacy_stale_cutoff_seconds`` (600s by default). A
# drawing this old is exactly the case the old rule condemned.
_LONG_AGO = timedelta(hours=1)


@pytest_asyncio.fixture
async def session_factory():
    """Sessions on a throwaway database, each with its own connection."""
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def drawing(session_factory) -> uuid.UUID:
    """A committed DWG drawing sitting at ``processing``."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    async with session_factory() as session:
        user = User(
            email=f"hb-{uuid.uuid4().hex[:8]}@test.io",
            hashed_password="x",
            full_name="Heartbeat Tester",
        )
        session.add(user)
        await session.flush()
        project = Project(name="Issue 409 heartbeat", owner_id=user.id)
        session.add(project)
        await session.flush()
        row = DwgDrawing(
            project_id=project.id,
            name="large.dwg",
            filename="large.dwg",
            file_format="dwg",
            file_path="/nowhere/large.dwg",
            size_bytes=22_000_000,
            status="processing",
            metadata_={},
            created_by="tester",
        )
        session.add(row)
        await session.flush()
        drawing_id = row.id
        await session.commit()

    return drawing_id


async def _set_clock(
    session_factory,
    drawing_id: uuid.UUID,
    *,
    touched_ago: timedelta,
    heartbeat_ago: timedelta | None,
) -> None:
    """Place the row's timestamps by hand.

    Raw SQL on purpose. ``updated_at`` carries a Python-side ``onupdate``, so
    writing this through the ORM would silently stamp it with the current time
    and the test would be arranging a state it never actually measured.

    ``id`` is bound as a string because ``GUID`` is a ``varchar(36)`` here, and
    raw SQL bypasses the type decorator that would otherwise convert it.
    """
    now = datetime.now(UTC)
    async with session_factory() as session:
        await session.execute(
            text(f"UPDATE {_TABLE} SET updated_at = :touched, conversion_heartbeat_at = :beat WHERE id = :id"),
            {
                "touched": now - touched_ago,
                "beat": None if heartbeat_ago is None else now - heartbeat_ago,
                "id": str(drawing_id),
            },
        )
        await session.commit()


async def _view_status(session_factory, drawing_id: uuid.UUID) -> tuple[str, str | None]:
    """What the viewer would be told about this drawing right now."""
    async with session_factory() as session:
        svc = DwgTakeoffService(session)
        _drawing, _version, status, message = await svc.get_drawing_with_view_status(drawing_id)
        return status, message


@pytest.mark.asyncio
async def test_a_slow_conversion_that_is_still_beating_is_not_declared_dead(session_factory, drawing) -> None:
    """The regression. Old enough for the old rule, alive by the new one."""
    await _set_clock(session_factory, drawing, touched_ago=_LONG_AGO, heartbeat_ago=timedelta(seconds=2))

    status, message = await _view_status(session_factory, drawing)

    assert status == "processing", "a conversion still reporting itself alive was called dead"
    assert message is None


@pytest.mark.asyncio
async def test_a_conversion_that_stopped_beating_is_declared_dead(session_factory, drawing) -> None:
    """The detector still does the job it exists for."""
    await _set_clock(session_factory, drawing, touched_ago=_LONG_AGO, heartbeat_ago=_LONG_AGO)

    status, message = await _view_status(session_factory, drawing)

    assert status == "error"
    assert message is not None and "upload it again" in message


@pytest.mark.asyncio
async def test_a_row_from_before_the_heartbeat_is_still_caught(session_factory, drawing) -> None:
    """A NULL heartbeat falls back to elapsed time, which is all we have."""
    await _set_clock(session_factory, drawing, touched_ago=_LONG_AGO, heartbeat_ago=None)

    status, _message = await _view_status(session_factory, drawing)

    assert status == "error"


@pytest.mark.asyncio
async def test_a_fresh_row_without_a_heartbeat_is_not_condemned(session_factory, drawing) -> None:
    """NULL is absence of evidence, not evidence of death."""
    await _set_clock(session_factory, drawing, touched_ago=timedelta(seconds=5), heartbeat_ago=None)

    status, _message = await _view_status(session_factory, drawing)

    assert status == "processing"


@pytest.mark.asyncio
async def test_a_null_heartbeat_is_never_read_as_death(session_factory, drawing) -> None:
    """NULL means no conversion has run, which is not the same as a dead one.

    Named for the semantics rather than the scenario, because this is the test
    that has to survive somebody later "simplifying" the two-branch check into
    one. The tempting simplification reads the silence since the heartbeat and
    treats a missing one as infinite silence, which is a single line and looks
    tidier. It would declare every row that predates the column orphaned on the
    first read after an upgrade, which on a real installation means the whole
    drawing register at once.

    The drawing here has never been converted at all: uploaded, no heartbeat,
    no entities, and recent. The assertion is that it is not reported dead
    rather than naming the state it is in, because the alternative between
    ``processing`` and ``needs_conversion`` turns on whether a converter binary
    happens to exist on the machine running the test, and that is not what is
    being pinned here.
    """
    async with session_factory() as session:
        await session.execute(
            text(f"UPDATE {_TABLE} SET status = 'uploaded' WHERE id = :id"),
            {"id": str(drawing)},
        )
        await session.commit()
    await _set_clock(session_factory, drawing, touched_ago=timedelta(seconds=3), heartbeat_ago=None)

    status, message = await _view_status(session_factory, drawing)

    assert status != "error", "a drawing with no heartbeat was reported dead"
    assert message is None


@pytest.mark.asyncio
async def test_reading_an_orphaned_drawing_does_not_write_to_it(session_factory, drawing) -> None:
    """A GET reports the verdict and leaves the record alone.

    This one fails against the previous implementation, which persisted the
    inferred error onto the row. The check runs on a second connection so it
    sees committed state rather than the reading session's own view.
    """
    await _set_clock(session_factory, drawing, touched_ago=_LONG_AGO, heartbeat_ago=_LONG_AGO)

    status, message = await _view_status(session_factory, drawing)
    assert status == "error"
    assert message is not None

    async with session_factory() as other:
        stored = (
            await other.execute(
                text(f"SELECT status, error_message FROM {_TABLE} WHERE id = :id"),
                {"id": str(drawing)},
            )
        ).one()

    assert stored.status == "processing", "the read wrote a status it had only inferred"
    assert stored.error_message is None, "the read wrote an error message onto the row"


@pytest.mark.asyncio
async def test_the_heartbeat_writer_advances_the_column(session_factory, drawing, monkeypatch) -> None:
    """The beat really reaches the database, on its own session."""
    monkeypatch.setenv("OE_DWG_HEARTBEAT_S", "1")
    monkeypatch.setattr(dwg_service, "async_session_factory", session_factory)
    await _set_clock(session_factory, drawing, touched_ago=_LONG_AGO, heartbeat_ago=_LONG_AGO)

    beat = asyncio.create_task(dwg_service._beat_while_converting(drawing))
    await asyncio.sleep(0.5)
    beat.cancel()
    with pytest.raises(asyncio.CancelledError):
        await beat

    async with session_factory() as session:
        written = (
            await session.execute(select(DwgDrawing.conversion_heartbeat_at).where(DwgDrawing.id == drawing))
        ).scalar_one()

    assert written is not None
    silence = (datetime.now(UTC) - written).total_seconds()
    assert silence < 30, f"heartbeat did not reach the database, last write was {silence:.0f}s ago"


@pytest.mark.asyncio
async def test_that_check_would_have_noticed_a_write(session_factory, drawing) -> None:
    """Control for the test above, and the reason it means anything.

    A test asserting "the row did not change" passes just as happily against a
    check that cannot observe changes at all. So make exactly the write the
    previous implementation made, through the same repository it used, and
    show the same second-connection read catches it.
    """
    await _set_clock(session_factory, drawing, touched_ago=_LONG_AGO, heartbeat_ago=_LONG_AGO)

    async with session_factory() as session:
        svc = DwgTakeoffService(session)
        await svc.drawing_repo.update_fields(
            drawing,
            status="error",
            error_message="written by hand",
        )
        await session.commit()

    async with session_factory() as other:
        stored = (
            await other.execute(
                text(f"SELECT status, error_message FROM {_TABLE} WHERE id = :id"),
                {"id": str(drawing)},
            )
        ).one()

    assert stored.status == "error"
    assert stored.error_message == "written by hand"


@pytest.mark.asyncio
async def test_the_service_notices_the_drawing_is_gone(session_factory, drawing) -> None:
    """The guard that stands in for the foreign key error."""
    async with session_factory() as session:
        svc = DwgTakeoffService(session)
        assert await svc._drawing_exists(drawing) is True

    async with session_factory() as session:
        await session.execute(text(f"DELETE FROM {_TABLE} WHERE id = :id"), {"id": str(drawing)})
        await session.commit()

    async with session_factory() as session:
        svc = DwgTakeoffService(session)
        assert await svc._drawing_exists(drawing) is False


@pytest.mark.asyncio
async def test_a_version_for_a_missing_drawing_really_does_violate_the_key(session_factory) -> None:
    """The control that keeps the test above honest.

    Without this, ``_drawing_exists`` could be guarding against nothing and
    every other test here would still pass. The insert has to genuinely fail
    for the guard to be worth having.
    """
    async with session_factory() as session:
        session.add(
            DwgDrawingVersion(
                drawing_id=uuid.uuid4(),  # no such drawing
                version_number=1,
                layers=[],
                entities_key="nowhere/entities.json",
                entity_count=1,
                extents={},
                status="ready",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
