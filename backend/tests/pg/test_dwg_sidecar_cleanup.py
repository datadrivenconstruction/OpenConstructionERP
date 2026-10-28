# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The converter's intermediate spreadsheet must not outlive the conversion.

Issue #409. A DWG conversion writes a ``<name>_dwg.xlsx`` beside the upload,
reads the entities out of it, and left it there. On every path: the five error
branches, the success path, and drawing deletion. Nothing else ever reads it.

That matters in proportion to the drawing, which is the wrong way round. The
reporter's file was 22 MB, the spreadsheet a large drawing produces is larger
still, and a conversion that fails is the one people retry, so the copies pile
up fastest on the installation that just failed to convert something big.

Every test here asserts the file is present before the act that should remove
it. Asserting only its absence afterwards would pass just as well against a
test that never created it.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.dwg_takeoff.models  # noqa: F401  (ORM registration)
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from app.modules.dwg_takeoff import service as dwg_service
from app.modules.dwg_takeoff.models import DwgDrawing
from app.modules.dwg_takeoff.service import (
    DwgTakeoffService,
    _remove_sidecar_xlsx,
    _run_dwg_conversion_in_background,
    _sidecar_xlsx_path,
)
from tests._pg import isolated_engine


@pytest_asyncio.fixture
async def session_factory():
    """Sessions on a throwaway database, each with its own connection."""
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def drawing(session_factory) -> tuple[uuid.UUID, str]:
    """A committed drawing, its upload on disk, and a sidecar beside it.

    The upload is deliberately not a valid DWG. The conversion has to fail for
    these tests to say anything: cleanup on the happy path is the easy half.
    """
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    fd, path = tempfile.mkstemp(suffix=".dwg", prefix="oe-409-sidecar-")
    with os.fdopen(fd, "wb") as handle:
        handle.write(b"not a drawing at all")
    Path(_sidecar_xlsx_path(path)).write_bytes(b"x" * 4096)

    async with session_factory() as session:
        user = User(
            email=f"sc-{uuid.uuid4().hex[:8]}@test.io",
            hashed_password="x",
            full_name="Sidecar Tester",
        )
        session.add(user)
        await session.flush()
        project = Project(name="Issue 409 sidecar", owner_id=user.id)
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
    Path(_sidecar_xlsx_path(path)).unlink(missing_ok=True)


def test_the_sidecar_sits_beside_the_upload_under_a_predictable_name() -> None:
    """One derivation, because three callers depend on agreeing about it."""
    assert _sidecar_xlsx_path("/data/dwg/site-plan.dwg") == "/data/dwg/site-plan_dwg.xlsx"
    assert _sidecar_xlsx_path("/data/dwg/rev.2.plan.dwg") == "/data/dwg/rev.2.plan_dwg.xlsx"


def test_removing_a_sidecar_that_was_never_written_is_not_an_error() -> None:
    """Cleanup that can fail is worse than the litter it removes."""
    _remove_sidecar_xlsx("/no/such/directory/anywhere/file.dwg")


@pytest.mark.asyncio
async def test_a_failed_conversion_clears_its_sidecar(session_factory, drawing, monkeypatch) -> None:
    """The path that matters: cleanup has to survive the conversion failing.

    The upload is not a real DWG, so the conversion gives up early and returns
    rather than completing. That is the shape of the reporter's runs, and it is
    the shape under which the spreadsheet used to be left behind.
    """
    drawing_id, path = drawing
    monkeypatch.setattr(dwg_service, "async_session_factory", session_factory)
    sidecar = _sidecar_xlsx_path(path)

    assert os.path.exists(sidecar), "fixture did not write the sidecar it is meant to test"

    await _run_dwg_conversion_in_background(drawing_id, path)

    assert not os.path.exists(sidecar), "a failed conversion left its spreadsheet behind"


@pytest.mark.asyncio
async def test_deleting_a_drawing_removes_a_sidecar_left_by_a_crash(session_factory, drawing) -> None:
    """The backstop, for the case no conversion is alive to clean up after.

    A process that dies mid-conversion leaves the spreadsheet with nothing that
    knows it exists. Deleting the drawing is the last moment anything can
    connect the two.
    """
    drawing_id, path = drawing
    sidecar = _sidecar_xlsx_path(path)

    assert os.path.exists(sidecar)

    async with session_factory() as session:
        await DwgTakeoffService(session).delete_drawing(drawing_id)
        await session.commit()

    assert not os.path.exists(sidecar), "deleting the drawing left its spreadsheet behind"
    assert not os.path.exists(path), "deleting the drawing left the upload behind"
