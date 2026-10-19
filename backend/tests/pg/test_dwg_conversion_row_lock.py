# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A DWG conversion must not hold the drawing row while it runs.

Issue #409 reported a 22 MB DWG whose conversion failed, and then three
things that look like separate problems and are not:

    Request timeout after 45000ms: PATCH /v1/dwg_takeoff/drawings/<id>/scale/

the drawing could not be deleted afterwards, and a second upload elsewhere in
the application failed to reach the server at all. One cause covers all of it.
The background conversion marked the drawing ``processing`` and then ran for
minutes before its session committed, so PostgreSQL held a row lock on that
drawing for the whole conversion and every other write to the same row queued
behind it until the client gave up at 45 seconds.

These tests need two real connections to the same database, which is why they
live in the PostgreSQL lane rather than the shared savepoint fixture: a lock is
only observable between separate transactions.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.dwg_takeoff.models  # noqa: F401  (ORM registration)
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from app.modules.dwg_takeoff.models import DwgDrawing
from app.modules.dwg_takeoff.service import DwgTakeoffService
from tests._pg import isolated_engine

# A DWG 2018 header. The service sniffs these six bytes before it does anything
# else and rejects the file outright when they do not match, so the fixture file
# has to carry a real one to reach the code under test.
_DWG_2018_MAGIC = b"AC1032"

# Long enough that a lock really is being waited on, short enough that a blocked
# statement fails inside the test rather than at the client's 45 second cap.
_LOCK_TIMEOUT = "500ms"


@pytest_asyncio.fixture
async def session_factory():
    """Sessions on a throwaway database, each with its own connection."""
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def drawing(session_factory) -> tuple[uuid.UUID, str]:
    """A committed DWG drawing at ``uploaded``, plus the path to its file."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    fd, path = tempfile.mkstemp(suffix=".dwg", prefix="oe-409-")
    with os.fdopen(fd, "wb") as handle:
        handle.write(_DWG_2018_MAGIC + b"\x00" * 128)

    async with session_factory() as session:
        user = User(
            email=f"dwg-{uuid.uuid4().hex[:8]}@test.io",
            hashed_password="x",
            full_name="DWG Tester",
        )
        session.add(user)
        await session.flush()
        project = Project(name="Issue 409", owner_id=user.id)
        session.add(project)
        await session.flush()
        row = DwgDrawing(
            project_id=project.id,
            name="large.dwg",
            filename="large.dwg",
            file_format="dwg",
            file_path=path,
            size_bytes=22_000_000,
            status="uploaded",
            metadata_={},
            created_by="tester",
        )
        session.add(row)
        await session.flush()
        drawing_id = row.id
        await session.commit()

    yield drawing_id, path

    Path(path).unlink(missing_ok=True)


class _ConversionWouldStartHere(BaseException):
    """Marker for the moment the converter is about to be launched.

    Deliberately not an ``Exception``. The handler catches those and writes an
    error status, which would put a second, uncommitted write on the row and
    make these tests measure the wrong thing entirely: they would show a lock
    that the running application never holds, because it commits that error the
    moment the handler returns.
    """


async def _start_conversion(session: AsyncSession, drawing_id: uuid.UUID, path: str) -> None:
    """Leave the drawing exactly as a conversion in progress leaves it.

    The converter is reported as present so the handler does not bail out
    before the status transition, and the call that would launch it raises
    the marker above. What remains is the state the row is in
    for however long the conversion runs, which for the report behind these
    tests was several minutes.
    """
    from app.modules.boq import cad_import, ddc_runner

    original_find = cad_import.find_converter
    original_run = ddc_runner.run_converter

    def _fake_find(fmt: str):
        return Path(path).parent / "dwg2excel.exe"

    def _fake_run(*_args, **_kwargs):
        raise _ConversionWouldStartHere

    cad_import.find_converter = _fake_find  # type: ignore[assignment]
    ddc_runner.run_converter = _fake_run  # type: ignore[assignment]
    try:
        await DwgTakeoffService(session)._handle_dwg(drawing_id, path)
    except _ConversionWouldStartHere:
        pass
    finally:
        cad_import.find_converter = original_find  # type: ignore[assignment]
        ddc_runner.run_converter = original_run  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_the_scale_can_still_be_set_while_a_conversion_runs(session_factory, drawing) -> None:
    """The reported PATCH: another session writes the row and is not blocked."""
    drawing_id, path = drawing

    async with session_factory() as converting, session_factory() as user_request:
        await _start_conversion(converting, drawing_id, path)

        await user_request.execute(text(f"SET lock_timeout = '{_LOCK_TIMEOUT}'"))
        await user_request.execute(
            text("UPDATE oe_dwg_takeoff_drawing SET scale_denominator = 50 WHERE id = :id"),
            {"id": str(drawing_id)},
        )
        await user_request.commit()

        scale = await user_request.scalar(
            text("SELECT scale_denominator FROM oe_dwg_takeoff_drawing WHERE id = :id"),
            {"id": str(drawing_id)},
        )
        assert int(scale) == 50


@pytest.mark.asyncio
async def test_the_drawing_can_still_be_deleted_while_a_conversion_runs(session_factory, drawing) -> None:
    """The other half of the report: a failed upload can be cleared away.

    Restarting the server was the only way out, which is what happens when the
    row a user is trying to remove is locked for the length of a conversion.
    """
    drawing_id, path = drawing

    async with session_factory() as converting, session_factory() as user_request:
        await _start_conversion(converting, drawing_id, path)

        await user_request.execute(text(f"SET lock_timeout = '{_LOCK_TIMEOUT}'"))
        await user_request.execute(
            text("DELETE FROM oe_dwg_takeoff_drawing WHERE id = :id"),
            {"id": str(drawing_id)},
        )
        await user_request.commit()

        remaining = await user_request.scalar(
            text("SELECT count(*) FROM oe_dwg_takeoff_drawing WHERE id = :id"),
            {"id": str(drawing_id)},
        )
        assert remaining == 0


@pytest.mark.asyncio
async def test_the_page_sees_the_drawing_go_into_processing(session_factory, drawing) -> None:
    """The status is meant to be read by someone else, so it has to be committed.

    The upload page polls this row to know where the conversion has got to. A
    transition that is still inside an open transaction is visible to nobody,
    so the page read ``uploaded`` for the entire conversion.
    """
    drawing_id, path = drawing

    async with session_factory() as converting, session_factory() as polling:
        await _start_conversion(converting, drawing_id, path)

        status = await polling.scalar(
            text("SELECT status FROM oe_dwg_takeoff_drawing WHERE id = :id"),
            {"id": str(drawing_id)},
        )
        assert status == "processing"


@pytest.mark.asyncio
async def test_an_uncommitted_write_really_does_block_the_other_session(session_factory, drawing) -> None:
    """Guard the guard: show the lock the tests above rely on being released.

    Without this, all three would pass just as well against a database that
    never blocked anyone, and the fix they are meant to hold in place could be
    taken out again without a single failure. This is the same write the
    conversion used to leave open, made by hand.
    """
    drawing_id, _path = drawing

    async with session_factory() as holding, session_factory() as user_request:
        await holding.execute(
            text("UPDATE oe_dwg_takeoff_drawing SET status = 'processing' WHERE id = :id"),
            {"id": str(drawing_id)},
        )
        await holding.flush()

        await user_request.execute(text(f"SET lock_timeout = '{_LOCK_TIMEOUT}'"))
        with pytest.raises(DBAPIError) as caught:
            await user_request.execute(
                text("UPDATE oe_dwg_takeoff_drawing SET scale_denominator = 50 WHERE id = :id"),
                {"id": str(drawing_id)},
            )
        # It has to fail for the right reason. Any other database error would
        # make this test pass while proving nothing about locking, which is the
        # whole thing it exists to establish.
        assert "lock timeout" in str(caught.value).lower(), str(caught.value)

        await user_request.rollback()
        await holding.rollback()
