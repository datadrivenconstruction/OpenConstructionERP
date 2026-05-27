# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for :mod:`app.modules.file_references`.

Coverage:
    * ISO 19650 validator passes on a well-formed name.
    * Missing volume / bad level / bad role / bad number flagged separately.
    * Catch-all not-iso19650 on garbage names with no hyphens.
    * scan_project writes rows for invalid filenames and clears them
      when the name becomes valid on a re-scan.
    * Acknowledging a violation stamps acknowledged_at.
    * create_reference is idempotent on the unique key.
    * by-target / for-file listings + delete round-trip.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.documents.models import Document  # noqa: F401 — registers ORM
from app.modules.file_references.models import (  # noqa: F401 — registers ORM
    FileNamingViolation,
    FileReference,
)
from app.modules.file_references.schemas import FileReferenceCreate
from app.modules.file_references.service import (
    acknowledge_violation,
    create_reference,
    delete_reference,
    list_files_for_target,
    list_references_for_file,
    list_violations,
    scan_project,
    validate_iso19650_name,
)
from app.modules.projects.models import Project  # noqa: F401 — registers ORM
from app.modules.users.models import User  # noqa: F401 — registers ORM


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Per-test in-memory SQLite with full schema applied."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _seed_user(session: AsyncSession) -> User:
    user = User(
        email=f"refs-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Refs Tester",
        role="admin",
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_project(session: AsyncSession) -> tuple[User, Project]:
    user = await _seed_user(session)
    project = Project(name="Refs Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return user, project


# ── ISO 19650 ──────────────────────────────────────────────────────────


def test_iso19650_valid_seven_part_passes() -> None:
    """A clean 7-part ISO 19650 name passes validation.

    Fields: Project=PRJ1, Originator=ABC, Volume=01, Level=02,
    Type=DR, Role=AR (2-char discipline), Number=0001.
    """
    result = validate_iso19650_name("PRJ1-ABC-01-02-DR-AR-0001.pdf")
    assert result.is_valid is True, f"Expected pass, got codes={result.violation_codes}"
    assert result.violation_codes == []
    assert result.parts.project == "PRJ1"
    assert result.parts.originator == "ABC"
    assert result.parts.volume == "01"
    assert result.parts.level == "02"
    assert result.parts.type == "DR"
    assert result.parts.role == "AR"
    assert result.parts.number == "0001"


def test_iso19650_valid_with_optional_status_and_revision() -> None:
    """Nine-part name with status + revision is also valid."""
    result = validate_iso19650_name("PRJ1-ABC-XX-00-DR-AR-0001-S2-P01.pdf")
    assert result.is_valid is True, f"Expected pass, got codes={result.violation_codes}"
    assert result.parts.status == "S2"
    assert result.parts.revision == "P01"


def test_iso19650_missing_volume_flagged() -> None:
    """Empty volume field surfaces ``missing-volume``."""
    # Empty volume slot — leave the position blank with two hyphens.
    result = validate_iso19650_name("PRJ1-ABC--02-DR-AR-0001.pdf")
    assert result.is_valid is False
    assert "missing-volume" in result.violation_codes


def test_iso19650_bad_level_flagged() -> None:
    """Single-char level fails the 2-char rule."""
    result = validate_iso19650_name("PRJ1-ABC-01-X-DR-AR-0001.pdf")
    assert result.is_valid is False
    assert "bad-level" in result.violation_codes


def test_iso19650_bad_role_flagged() -> None:
    """Single-char role fails the 2-4 char rule."""
    result = validate_iso19650_name("PRJ1-ABC-01-02-DR-A-0001.pdf")
    assert result.is_valid is False
    assert "bad-role-code" in result.violation_codes


def test_iso19650_bad_number_flagged() -> None:
    """Non-4-digit number triggers ``bad-number``."""
    result = validate_iso19650_name("PRJ1-ABC-01-02-DR-AR-001.pdf")
    assert result.is_valid is False
    assert "bad-number" in result.violation_codes


def test_iso19650_no_hyphens_is_not_iso19650() -> None:
    """A plain filename gets the catch-all ``not-iso19650``."""
    result = validate_iso19650_name("untitled.pdf")
    assert result.is_valid is False
    assert result.violation_codes == ["not-iso19650"]


def test_iso19650_too_few_parts_flagged() -> None:
    """Five-part hyphen-split fails the 7-min."""
    result = validate_iso19650_name("PRJ1-ABC-01-02-DR.pdf")
    assert result.is_valid is False
    assert "too-few-parts" in result.violation_codes


def test_iso19650_multiple_codes_accumulate() -> None:
    """A name with several breakages surfaces all the codes."""
    # Volume empty + bad level + bad number — three separate codes.
    result = validate_iso19650_name("PRJ1-ABC--Z-DR-AR-99.pdf")
    assert result.is_valid is False
    assert "missing-volume" in result.violation_codes
    assert "bad-level" in result.violation_codes
    assert "bad-number" in result.violation_codes


# ── Project scan ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_project_writes_rows_for_invalid_filenames(
    session: AsyncSession,
) -> None:
    """Bad document names get violation rows; valid names don't."""
    user, project = await _seed_project(session)

    bad_doc = Document(
        project_id=project.id,
        name="bad name with no convention.pdf",
        mime_type="application/pdf",
        file_size=10,
    )
    good_doc = Document(
        project_id=project.id,
        name="PRJ1-ABC-01-02-DR-AR-0001.pdf",
        mime_type="application/pdf",
        file_size=20,
    )
    session.add_all([bad_doc, good_doc])
    await session.flush()

    response = await scan_project(session, project.id)
    assert response.scanned == 2
    # Exactly the bad doc surfaces.
    assert response.violations_added == 1
    assert response.violations_updated == 0
    assert response.violations_cleared == 0

    rows = list(
        (
            await session.execute(select(FileNamingViolation).where(FileNamingViolation.project_id == project.id))
        ).scalars()
    )
    assert len(rows) == 1
    assert rows[0].filename == "bad name with no convention.pdf"
    assert "not-iso19650" in rows[0].violation_codes
    assert rows[0].file_id == str(bad_doc.id)
    assert rows[0].acknowledged_at is None


@pytest.mark.asyncio
async def test_rescan_clears_row_when_file_becomes_valid(
    session: AsyncSession,
) -> None:
    """A row that was bad on the first scan is removed when fixed."""
    user, project = await _seed_project(session)

    doc = Document(
        project_id=project.id,
        name="garbage.pdf",
        mime_type="application/pdf",
        file_size=10,
    )
    session.add(doc)
    await session.flush()

    first = await scan_project(session, project.id)
    assert first.violations_added == 1

    # Rename the doc to a compliant name.
    doc.name = "PRJ1-ABC-01-02-DR-AR-0001.pdf"
    await session.flush()

    second = await scan_project(session, project.id)
    assert second.violations_added == 0
    assert second.violations_cleared == 1

    rows = list(
        (
            await session.execute(select(FileNamingViolation).where(FileNamingViolation.project_id == project.id))
        ).scalars()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_acknowledge_violation_stamps_row(
    session: AsyncSession,
) -> None:
    """Acknowledging marks the row + drops it from the un-ack'd list."""
    user, project = await _seed_project(session)

    doc = Document(
        project_id=project.id,
        name="violator.pdf",
        mime_type="application/pdf",
        file_size=10,
    )
    session.add(doc)
    await session.flush()

    await scan_project(session, project.id)
    rows = list(
        (
            await session.execute(select(FileNamingViolation).where(FileNamingViolation.project_id == project.id))
        ).scalars()
    )
    assert len(rows) == 1
    target = rows[0]

    ack = await acknowledge_violation(session, target.id, actor_id=user.id)
    assert ack is not None
    assert ack.acknowledged_at is not None
    assert ack.acknowledged_by_id == user.id

    # Default list filters out acknowledged rows.
    items, total = await list_violations(session, project.id)
    assert total == 0
    assert items == []

    items_all, total_all = await list_violations(session, project.id, include_acknowledged=True)
    assert total_all == 1


# ── References CRUD ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_reference_and_list_by_target_and_file(
    session: AsyncSession,
) -> None:
    """A link surfaces via both for-file and by-target queries."""
    user, project = await _seed_project(session)

    file_id = uuid.uuid4().hex
    rfi_id = uuid.uuid4().hex

    created = await create_reference(
        session,
        FileReferenceCreate(
            project_id=project.id,
            file_kind="document",
            file_id=file_id,
            target_type="rfi",
            target_id=rfi_id,
            relation="references",
            target_label="RFI-142",
        ),
        actor_id=user.id,
    )
    assert created.target_label == "RFI-142"
    assert created.relation == "references"

    # By file ─ Returns the RFI link.
    by_file, total = await list_references_for_file(session, file_kind="document", file_id=file_id)
    assert total == 1
    assert by_file[0].target_type == "rfi"
    assert by_file[0].target_id == rfi_id

    # By target — same row, viewed from the other end.
    by_target, total_t = await list_files_for_target(session, target_type="rfi", target_id=rfi_id)
    assert total_t == 1
    assert by_target[0].file_kind == "document"
    assert by_target[0].file_id == file_id


@pytest.mark.asyncio
async def test_create_reference_is_idempotent(session: AsyncSession) -> None:
    """Re-creating the same triple returns the existing row, no duplicate."""
    user, project = await _seed_project(session)
    file_id = uuid.uuid4().hex
    target_id = uuid.uuid4().hex
    payload = FileReferenceCreate(
        project_id=project.id,
        file_kind="document",
        file_id=file_id,
        target_type="task",
        target_id=target_id,
    )
    first = await create_reference(session, payload, actor_id=user.id)
    second = await create_reference(session, payload, actor_id=user.id)
    assert first.id == second.id

    # Only one row in the table.
    rows = list((await session.execute(select(FileReference))).scalars())
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_delete_reference_removes_link(session: AsyncSession) -> None:
    """Delete drops the row + leaves by-target empty."""
    user, project = await _seed_project(session)
    file_id = uuid.uuid4().hex
    rfi_id = uuid.uuid4().hex
    created = await create_reference(
        session,
        FileReferenceCreate(
            project_id=project.id,
            file_kind="document",
            file_id=file_id,
            target_type="rfi",
            target_id=rfi_id,
        ),
        actor_id=user.id,
    )

    ok = await delete_reference(session, created.id)
    assert ok is True

    items, total = await list_files_for_target(session, target_type="rfi", target_id=rfi_id)
    assert total == 0
    assert items == []

    # Idempotent failure mode — second delete is False, not an error.
    again = await delete_reference(session, created.id)
    assert again is False
