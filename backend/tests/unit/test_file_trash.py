# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for :mod:`app.modules.file_trash`.

Coverage:
    * Soft-deleting a document → original row gone, trash row holds full payload.
    * Restoring a trash row → original kind table gets the row back; restored_at set.
    * Restoring already-restored row → 409.
    * ``purge_expired_trash`` removes only rows past their retention_days
      window; younger rows are untouched.
    * ``purge`` requires the matching restore_token (403 on mismatch).
    * Stats endpoint returns count + bytes for non-restored / non-purged rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.documents.models import Document  # noqa: F401 — register model
from app.modules.file_trash.models import FileTrash
from app.modules.file_trash.service import FileTrashService, purge_expired_trash
from app.modules.projects.models import Project  # noqa: F401 — register model
from app.modules.users.models import User  # noqa: F401 — register model


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Return (user_id, project_id) so trash rows have valid FK targets."""
    user = User(
        email=f"trash-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Trash Tester",
        role="admin",
    )
    session.add(user)
    await session.flush()

    project = Project(
        name="Trash Project",
        owner_id=user.id,
    )
    session.add(project)
    await session.flush()
    return user.id, project.id


async def _seed_document(session: AsyncSession, project_id: uuid.UUID) -> Document:
    doc = Document(
        project_id=project_id,
        name="contract-v1.pdf",
        description="Test contract",
        category="contract",
        file_size=4096,
        mime_type="application/pdf",
        file_path="/tmp/contract-v1.pdf",
        version=1,
        uploaded_by="tester",
    )
    session.add(doc)
    await session.flush()
    return doc


@pytest.mark.asyncio
async def test_soft_delete_removes_original_and_snapshots_payload(
    session: AsyncSession,
) -> None:
    user_id, project_id = await _seed_project(session)
    doc = await _seed_document(session, project_id)
    doc_id = doc.id
    doc_name = doc.name

    svc = FileTrashService(session)
    trash = await svc.soft_delete(
        project_id=project_id,
        kind="document",
        original_id=str(doc_id),
        canonical_name=doc_name,
        actor_id=user_id,
    )

    # Original gone.
    refreshed = await session.get(Document, doc_id)
    assert refreshed is None

    # Trash row has the snapshot.
    assert trash.original_kind == "document"
    assert trash.original_id == str(doc_id)
    assert trash.canonical_name == doc_name
    assert trash.payload_json["name"] == doc_name
    assert trash.payload_json["category"] == "contract"
    assert trash.payload_json["file_size"] == 4096
    assert trash.trashed_by_id == user_id
    assert trash.retention_days == 30
    assert trash.restored_at is None
    assert trash.purged_at is None
    assert trash.restore_token  # non-empty


@pytest.mark.asyncio
async def test_soft_delete_with_explicit_payload_keeps_original_alone(
    session: AsyncSession,
) -> None:
    """When payload is supplied, the service does NOT touch the source row.

    This is the path used by callers that already hold the row in
    memory and want to remove it themselves (or by tests that don't
    have a real row to point at)."""
    _user_id, project_id = await _seed_project(session)
    fake_id = uuid.uuid4().hex

    svc = FileTrashService(session)
    trash = await svc.soft_delete(
        project_id=project_id,
        kind="report",  # arbitrary kind, no real row needed
        original_id=fake_id,
        canonical_name="manual.snapshot",
        payload={"name": "manual.snapshot", "size_bytes": 8192},
    )
    assert trash.payload_json["size_bytes"] == 8192
    assert trash.file_size == 8192  # derived property


@pytest.mark.asyncio
async def test_restore_recreates_original_row(session: AsyncSession) -> None:
    user_id, project_id = await _seed_project(session)
    doc = await _seed_document(session, project_id)
    doc_id = doc.id

    svc = FileTrashService(session)
    trash = await svc.soft_delete(
        project_id=project_id,
        kind="document",
        original_id=str(doc_id),
        canonical_name=doc.name,
        actor_id=user_id,
    )

    restored = await svc.restore(trash.id, actor_id=user_id)
    assert restored.restored_at is not None
    assert restored.restored_by_id == user_id

    # Document is back in the kind table.
    rows = (await session.execute(select(Document).where(Document.project_id == project_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "contract-v1.pdf"
    assert rows[0].file_size == 4096


@pytest.mark.asyncio
async def test_restore_twice_raises_409(session: AsyncSession) -> None:
    from fastapi import HTTPException

    user_id, project_id = await _seed_project(session)
    doc = await _seed_document(session, project_id)
    svc = FileTrashService(session)
    trash = await svc.soft_delete(
        project_id=project_id,
        kind="document",
        original_id=str(doc.id),
        canonical_name=doc.name,
        actor_id=user_id,
    )
    await svc.restore(trash.id, actor_id=user_id)
    with pytest.raises(HTTPException) as exc_info:
        await svc.restore(trash.id, actor_id=user_id)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_purge_requires_matching_token(session: AsyncSession) -> None:
    from fastapi import HTTPException

    _user_id, project_id = await _seed_project(session)
    svc = FileTrashService(session)
    trash = await svc.soft_delete(
        project_id=project_id,
        kind="report",
        original_id=uuid.uuid4().hex,
        canonical_name="x",
        payload={"name": "x"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.purge(trash.id, confirm_token="wrong-token")
    assert exc_info.value.status_code == 403

    # With the right token the row is gone.
    await svc.purge(trash.id, confirm_token=trash.restore_token)
    again = await session.get(FileTrash, trash.id)
    assert again is None


@pytest.mark.asyncio
async def test_purge_expired_trash_removes_only_old_rows(
    session: AsyncSession,
) -> None:
    user_id, project_id = await _seed_project(session)
    svc = FileTrashService(session)

    # One old row (40 days ago) — should be purged.
    old = await svc.soft_delete(
        project_id=project_id,
        kind="report",
        original_id="old-id",
        canonical_name="old.pdf",
        payload={"name": "old.pdf"},
        retention_days=30,
        actor_id=user_id,
    )
    old.trashed_at = datetime.now(UTC) - timedelta(days=40)
    await session.flush()

    # One fresh row — must survive.
    young = await svc.soft_delete(
        project_id=project_id,
        kind="report",
        original_id="young-id",
        canonical_name="young.pdf",
        payload={"name": "young.pdf"},
        retention_days=30,
        actor_id=user_id,
    )

    purged = await purge_expired_trash(session)
    assert purged == 1

    # Old row is gone, young row still there.
    assert await session.get(FileTrash, old.id) is None
    assert await session.get(FileTrash, young.id) is not None


@pytest.mark.asyncio
async def test_purge_expired_respects_per_row_retention(
    session: AsyncSession,
) -> None:
    """A row trashed 10 days ago with retention_days=7 is expired; a row
    trashed 10 days ago with retention_days=30 is not."""
    _user_id, project_id = await _seed_project(session)
    svc = FileTrashService(session)

    a = await svc.soft_delete(
        project_id=project_id,
        kind="report",
        original_id="short",
        canonical_name="a",
        payload={},
        retention_days=7,
    )
    b = await svc.soft_delete(
        project_id=project_id,
        kind="report",
        original_id="long",
        canonical_name="b",
        payload={},
        retention_days=30,
    )
    ten_days_ago = datetime.now(UTC) - timedelta(days=10)
    a.trashed_at = ten_days_ago
    b.trashed_at = ten_days_ago
    await session.flush()

    purged = await purge_expired_trash(session)
    assert purged == 1
    assert await session.get(FileTrash, a.id) is None
    assert await session.get(FileTrash, b.id) is not None


@pytest.mark.asyncio
async def test_stats_counts_only_active_trash(session: AsyncSession) -> None:
    _user_id, project_id = await _seed_project(session)
    svc = FileTrashService(session)

    a = await svc.soft_delete(
        project_id=project_id,
        kind="report",
        original_id="id-a",
        canonical_name="a",
        payload={"name": "a", "size_bytes": 1024},
    )
    b = await svc.soft_delete(
        project_id=project_id,
        kind="report",
        original_id="id-b",
        canonical_name="b",
        payload={"name": "b", "size_bytes": 2048},
    )
    # Mark `a` as restored so stats ignores it.
    a.restored_at = datetime.now(UTC)
    await session.flush()

    count, rows, oldest, newest = await svc.repo.stats_for_project(project_id)
    assert count == 1
    assert rows[0].id == b.id
    total_bytes = sum(r.file_size for r in rows)
    assert total_bytes == 2048
    assert oldest is not None
    assert newest is not None
