# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the connectors sync service (PostgreSQL, py3.12).

Drops files into a temp folder, registers a watched-folder source, and checks
that a sync imports each new file as a project Document, deduplicates on a
re-sync (idempotent) and on identical content, and tolerates a missing folder.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.connectors.models import ConnectorSource
from app.modules.connectors.service import CONNECTOR_META_KEY, ConnectorService
from app.modules.documents.models import Document
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _watch_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the connectors base dir at ``tmp_path`` for the duration of a test.

    The service confines a watched-folder root to this base dir, so the temp
    folders these tests drop files into must live under it.
    """
    monkeypatch.setenv("OE_CONNECTORS_BASE_DIR", str(tmp_path))


async def _project(session: AsyncSession) -> tuple[User, Project]:
    user = User(
        email=f"conn-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Conn",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Conn {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return user, proj


async def _docs_for(session: AsyncSession, project_id: uuid.UUID) -> list[Document]:
    return list((await session.execute(select(Document).where(Document.project_id == project_id))).scalars().all())


async def _make_source(session: AsyncSession, proj: Project, user: User, root: Path) -> ConnectorSource:
    service = ConnectorService(session)
    return await service.create_source(
        project_id=proj.id,
        name="Site drop",
        root_path=str(root),
        created_by=str(user.id),
    )


@pytest.mark.asyncio
async def test_sync_imports_new_files_as_documents(session: AsyncSession, tmp_path: Path) -> None:
    user, proj = await _project(session)
    (tmp_path / "rfi-001.txt").write_text("Please confirm the rebar spacing.")
    (tmp_path / "variation-2.txt").write_text("Add a second access door to level 3.")

    source = await _make_source(session, proj, user, tmp_path)
    result = await ConnectorService(session).sync_source(source, user_id=str(user.id))

    assert result["created"] == 2
    assert result["total"] == 2
    assert len(result["created_document_ids"]) == 2

    docs = await _docs_for(session, proj.id)
    assert len(docs) == 2
    for doc in docs:
        marker = doc.metadata_[CONNECTOR_META_KEY]
        assert marker["source"] == "Site drop"
        assert marker["external_id"]
        assert marker["content_hash"]
    # The source records its last sync outcome for the UI.
    assert source.last_synced_at
    assert source.last_result["created"] == 2


@pytest.mark.asyncio
async def test_resync_is_idempotent(session: AsyncSession, tmp_path: Path) -> None:
    user, proj = await _project(session)
    (tmp_path / "a.txt").write_text("alpha")
    (tmp_path / "b.txt").write_text("bravo")
    source = await _make_source(session, proj, user, tmp_path)
    svc = ConnectorService(session)

    first = await svc.sync_source(source, user_id=str(user.id))
    assert first["created"] == 2

    # No folder change -> a second sync creates nothing and counts both as known.
    second = await svc.sync_source(source, user_id=str(user.id))
    assert second["created"] == 0
    assert second["already_known"] == 2
    assert len(await _docs_for(session, proj.id)) == 2


@pytest.mark.asyncio
async def test_identical_content_is_deduplicated(session: AsyncSession, tmp_path: Path) -> None:
    user, proj = await _project(session)
    (tmp_path / "a.txt").write_text("same bytes")
    (tmp_path / "b.txt").write_text("other bytes")
    # c.txt carries identical content to a.txt -> caught as duplicate content.
    (tmp_path / "c.txt").write_text("same bytes")

    source = await _make_source(session, proj, user, tmp_path)
    result = await ConnectorService(session).sync_source(source, user_id=str(user.id))

    assert result["total"] == 3
    assert result["created"] == 2
    assert result["duplicate"] == 1
    assert len(await _docs_for(session, proj.id)) == 2


@pytest.mark.asyncio
async def test_missing_folder_syncs_to_nothing(session: AsyncSession, tmp_path: Path) -> None:
    user, proj = await _project(session)
    missing = tmp_path / "does-not-exist"
    source = await _make_source(session, proj, user, missing)

    result = await ConnectorService(session).sync_source(source, user_id=str(user.id))
    assert result["created"] == 0
    assert result["total"] == 0
    assert await _docs_for(session, proj.id) == []


# ---------------------------------------------------------------------------
# Watched-folder root is confined to the connectors base dir.
# (The autouse ``_watch_base`` fixture points the base dir at ``tmp_path``.)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_source_accepts_root_inside_base(session: AsyncSession, tmp_path: Path) -> None:
    user, proj = await _project(session)
    inside = tmp_path / "site-drop"
    inside.mkdir()

    source = await _make_source(session, proj, user, inside)
    assert source.root_path == str(inside)


@pytest.mark.asyncio
async def test_create_source_rejects_root_outside_base(session: AsyncSession, tmp_path: Path) -> None:
    user, proj = await _project(session)
    # A real absolute path that is not under the base dir (a sibling of it).
    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex[:6]}"
    outside.mkdir()

    with pytest.raises(ValueError, match="connectors base directory"):
        await _make_source(session, proj, user, outside)
    # Nothing was persisted.
    assert await ConnectorService(session).list_sources(proj.id) == []


@pytest.mark.asyncio
async def test_create_source_rejects_parent_traversal(session: AsyncSession, tmp_path: Path) -> None:
    user, proj = await _project(session)
    # ``<base>/../<base-name>-escape`` resolves outside the base dir.
    escape = tmp_path / ".." / f"escape-{uuid.uuid4().hex[:6]}"

    with pytest.raises(ValueError, match="connectors base directory"):
        await _make_source(session, proj, user, escape)


@pytest.mark.asyncio
async def test_create_source_rejects_relative_root(session: AsyncSession) -> None:
    user, proj = await _project(session)
    service = ConnectorService(session)

    with pytest.raises(ValueError, match="absolute path"):
        await service.create_source(
            project_id=proj.id,
            name="Relative",
            root_path="some/relative/dir",
            created_by=str(user.id),
        )


@pytest.mark.asyncio
async def test_create_source_rejects_blank_root(session: AsyncSession) -> None:
    user, proj = await _project(session)
    service = ConnectorService(session)

    with pytest.raises(ValueError, match="absolute path"):
        await service.create_source(
            project_id=proj.id,
            name="Blank",
            root_path="   ",
            created_by=str(user.id),
        )
