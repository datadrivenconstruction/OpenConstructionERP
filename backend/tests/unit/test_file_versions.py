# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for :mod:`app.modules.file_versions`.

Coverage:
    * Registering a brand-new file → version 1 marked current.
    * Re-uploading the same canonical_name → v1 superseded, v2 current,
      chain pointer wired both directions.
    * Restoring v1 → flips current back; the previously-current row
      becomes superseded with a fresh chain pointer.
    * ``list_chain`` returns newest-first.
    * ``list_for_file`` finds chain seeds by file_id.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_versions.models import FileVersion  # noqa: F401 — registers ORM
from app.modules.file_versions.schemas import FileVersionCreate
from app.modules.file_versions.service import FileVersionService
from app.modules.projects.models import Project  # noqa: F401 — registers ORM
from app.modules.users.models import User  # noqa: F401 — registers ORM
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Per-test PostgreSQL session inside a rolled-back outer transaction.

    The shared ``oe_test_unit`` database already carries the full schema, so
    no per-test DDL is needed; the outer transaction is rolled back on teardown
    to isolate each test.
    """
    async with transactional_session() as s:
        yield s


async def _seed_project(session: AsyncSession) -> uuid.UUID:
    """Return a fresh project_id so FK constraints on FileVersion pass."""
    user = User(
        email=f"ver-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Version Tester",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Version Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id


async def _seed_payload(
    session: AsyncSession,
    name: str = "drawing-001.pdf",
) -> FileVersionCreate:
    project_id = await _seed_project(session)
    return FileVersionCreate(
        project_id=project_id,
        file_kind="document",
        file_id=uuid.uuid4().hex,
        canonical_name=name,
        notes=None,
        file_size=2048,
        checksum=None,
    )


@pytest.mark.asyncio
async def test_register_first_version_is_current(session: AsyncSession) -> None:
    svc = FileVersionService(session)
    seed = await _seed_payload(session)
    row = await svc.register_new_version(seed, uploaded_by_id=None)

    assert row.is_current is True
    assert row.version_number == 1
    assert row.previous_version_id is None
    assert row.superseded_at is None
    assert row.superseded_by_id is None


@pytest.mark.asyncio
async def test_reupload_same_name_supersedes_previous(session: AsyncSession) -> None:
    svc = FileVersionService(session)
    seed_a = await _seed_payload(session)
    v1 = await svc.register_new_version(seed_a, uploaded_by_id=None)

    seed_b = FileVersionCreate(
        project_id=seed_a.project_id,
        file_kind=seed_a.file_kind,
        file_id=uuid.uuid4().hex,
        canonical_name=seed_a.canonical_name,
        notes="rev B",
        file_size=4096,
        checksum=None,
    )
    v2 = await svc.register_new_version(seed_b, uploaded_by_id=None)

    # Re-fetch v1 to see the supersede side-effects.
    await session.refresh(v1)

    assert v2.version_number == 2
    assert v2.is_current is True
    assert v2.previous_version_id == v1.id
    assert v2.notes == "rev B"

    assert v1.is_current is False
    assert v1.superseded_at is not None
    assert v1.superseded_by_id == v2.id


@pytest.mark.asyncio
async def test_list_chain_newest_first(session: AsyncSession) -> None:
    svc = FileVersionService(session)
    seed = await _seed_payload(session, "plans.pdf")
    v1 = await svc.register_new_version(seed, uploaded_by_id=None)
    seed2 = seed.model_copy(update={"file_id": uuid.uuid4().hex})
    v2 = await svc.register_new_version(seed2, uploaded_by_id=None)
    seed3 = seed.model_copy(update={"file_id": uuid.uuid4().hex})
    v3 = await svc.register_new_version(seed3, uploaded_by_id=None)

    chain = await svc.list_chain(
        project_id=seed.project_id,
        file_kind=seed.file_kind,
        canonical_name=seed.canonical_name,
    )
    assert [r.id for r in chain] == [v3.id, v2.id, v1.id]
    assert [r.version_number for r in chain] == [3, 2, 1]
    assert [r.is_current for r in chain] == [True, False, False]


@pytest.mark.asyncio
async def test_restore_promotes_old_version(session: AsyncSession) -> None:
    svc = FileVersionService(session)
    seed = await _seed_payload(session, "restore-me.pdf")
    v1 = await svc.register_new_version(seed, uploaded_by_id=None)
    seed2 = seed.model_copy(update={"file_id": uuid.uuid4().hex, "notes": "v2"})
    v2 = await svc.register_new_version(seed2, uploaded_by_id=None)

    restored = await svc.restore_version(v1.id, actor_id=None)
    await session.refresh(v2)

    assert restored.id == v1.id
    assert restored.is_current is True
    assert restored.superseded_at is None
    assert restored.superseded_by_id is None
    assert v2.is_current is False
    assert v2.superseded_at is not None
    assert v2.superseded_by_id == v1.id


@pytest.mark.asyncio
async def test_restore_current_version_is_noop(session: AsyncSession) -> None:
    svc = FileVersionService(session)
    seed = await _seed_payload(session, "noop.pdf")
    v1 = await svc.register_new_version(seed, uploaded_by_id=None)

    restored = await svc.restore_version(v1.id, actor_id=None)
    assert restored.id == v1.id
    assert restored.is_current is True


@pytest.mark.asyncio
async def test_list_for_file_id_finds_chain_seed(session: AsyncSession) -> None:
    svc = FileVersionService(session)
    seed = await _seed_payload(session, "find-by-id.pdf")
    v1 = await svc.register_new_version(seed, uploaded_by_id=None)

    rows = await svc.list_for_file(file_id=v1.file_id, file_kind="document")
    assert len(rows) == 1
    assert rows[0].id == v1.id


@pytest.mark.asyncio
async def test_register_unknown_kind_raises(session: AsyncSession) -> None:
    from fastapi import HTTPException

    project_id = await _seed_project(session)
    svc = FileVersionService(session)
    bad = FileVersionCreate.model_construct(
        project_id=project_id,
        file_kind="bogus_kind",  # bypass pydantic Literal
        file_id="abc",
        canonical_name="x.pdf",
        notes=None,
        file_size=0,
        checksum=None,
        previous_version_id=None,
    )
    with pytest.raises(HTTPException) as exc_info:
        await svc.register_new_version(bad, uploaded_by_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_different_canonical_names_do_not_collide(session: AsyncSession) -> None:
    """Two different canonical names share project+kind but get
    independent version_number counters."""
    svc = FileVersionService(session)
    seed_a = await _seed_payload(session, "file-a.pdf")
    a = await svc.register_new_version(seed_a, uploaded_by_id=None)
    seed_b = FileVersionCreate(
        project_id=seed_a.project_id,
        file_kind=seed_a.file_kind,
        file_id=uuid.uuid4().hex,
        canonical_name="file-b.pdf",
        notes=None,
        file_size=0,
        checksum=None,
    )
    b = await svc.register_new_version(seed_b, uploaded_by_id=None)

    assert a.version_number == 1
    assert b.version_number == 1
    assert a.is_current is True
    assert b.is_current is True
