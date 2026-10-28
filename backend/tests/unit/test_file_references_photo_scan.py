# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The naming scan has to reach site photos.

``_iter_project_files`` guarded the photo kind with
``hasattr(DiaryPhoto, "project_id") and hasattr(DiaryPhoto, "filename")``.
``project_id`` is there; ``filename`` never was - the model stores the
photo's location in ``file_url``. The condition was therefore permanently
False, so photos were silently absent from every project scan. Nothing
raised and nothing logged, because a guard that skips is not an error.

``file_url`` is a location, not a name: it is ``String(2000)`` while
``FileNamingViolation.filename`` is ``String(255)``, and a URL's path
separators and query string would be read as ISO 19650 fields. The scan
therefore has to take the basename, which is what these tests pin.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.daily_diary.models import DiaryPhoto  # noqa: F401 — registers ORM
from app.modules.documents.models import Document  # noqa: F401 — registers ORM
from app.modules.file_references.models import FileNamingViolation  # noqa: F401 — registers ORM
from app.modules.file_references.service import scan_project
from app.modules.projects.models import Project  # noqa: F401 — registers ORM
from app.modules.users.models import User  # noqa: F401 — registers ORM
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _seed_project(session: AsyncSession) -> Project:
    user = User(
        email=f"photoscan-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Photo Scan Tester",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Photo Scan Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project


def _photo(project_id: uuid.UUID, file_url: str) -> DiaryPhoto:
    return DiaryPhoto(
        project_id=project_id,
        taken_at=datetime.now(UTC),
        file_url=file_url,
        mime_type="image/jpeg",
        file_size_bytes=1024,
    )


async def _violations(session: AsyncSession, project_id: uuid.UUID) -> list[FileNamingViolation]:
    stmt = select(FileNamingViolation).where(FileNamingViolation.project_id == project_id)
    return list((await session.execute(stmt)).scalars())


def test_the_model_names_the_column_the_scan_reads() -> None:
    """A guard on a column the model does not have is a guard that never fires."""
    assert hasattr(DiaryPhoto, "project_id")
    assert hasattr(DiaryPhoto, "file_url")
    assert not hasattr(DiaryPhoto, "filename")


@pytest.mark.asyncio
async def test_the_scan_reaches_site_photos(session: AsyncSession) -> None:
    project = await _seed_project(session)
    # The document is the control: if the stubbed-out photo kind is the only
    # thing this asserts on, a scan that returned nothing at all would read
    # the same as a scan that skipped photos.
    session.add(
        Document(
            project_id=project.id,
            name="PRJ1-ABC-01-02-DR-AR-0001.pdf",
            mime_type="application/pdf",
            file_size=10,
        )
    )
    session.add(_photo(project.id, "https://cdn.example.io/site/2026/03/site photo.jpg"))
    await session.flush()

    response = await scan_project(session, project.id)

    assert response.scanned == 2, "the photo kind never entered the scan"
    assert response.violations_added == 1

    rows = await _violations(session, project.id)
    assert [(row.file_kind, row.filename) for row in rows] == [("photo", "site photo.jpg")]
    assert "not-iso19650" in rows[0].violation_codes


@pytest.mark.asyncio
async def test_a_compliantly_named_photo_raises_no_violation(session: AsyncSession) -> None:
    project = await _seed_project(session)
    session.add(_photo(project.id, "/uploads/diary/PRJ1-ABC-01-02-DR-AR-0001.jpg"))
    await session.flush()

    response = await scan_project(session, project.id)

    assert response.scanned == 1
    assert response.violations_added == 0
    assert await _violations(session, project.id) == []


@pytest.mark.asyncio
async def test_a_long_url_is_reduced_to_the_name_it_ends_in(session: AsyncSession) -> None:
    """``file_url`` is String(2000); the violation's ``filename`` column is String(255)."""
    project = await _seed_project(session)
    long_path = "/".join(f"segment{i:03d}" for i in range(60))
    session.add(_photo(project.id, f"https://cdn.example.io/{long_path}/bad photo name.jpg?sig=abc&x=1"))
    await session.flush()

    response = await scan_project(session, project.id)

    assert response.scanned == 1
    rows = await _violations(session, project.id)
    assert len(rows) == 1
    assert rows[0].filename == "bad photo name.jpg"
    assert len(rows[0].filename) <= 255
