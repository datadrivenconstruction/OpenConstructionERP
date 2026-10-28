# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Edge-case integration tests for the connectors module (PostgreSQL, py3.12).

Complements ``test_connector_sync.py`` (the happy-path + root-confinement suite)
with the boundary cases a thin integration test usually skips: an empty folder,
the wrong-project / access-denied 404 the router enforces, a fetch of a missing
source, idempotency of a re-sync that finds a brand-new file, and that two
sources in the same project do not deduplicate against each other.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import verify_project_access
from app.modules.connectors.service import ConnectorService
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
    monkeypatch.setenv("OE_CONNECTORS_BASE_DIR", str(tmp_path))


async def _user(session: AsyncSession, *, role: str = "admin") -> User:
    user = User(
        email=f"conn-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Conn",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, owner: User) -> Project:
    proj = Project(name=f"Conn {uuid.uuid4().hex[:6]}", owner_id=owner.id)
    session.add(proj)
    await session.flush()
    return proj


async def _docs_for(session: AsyncSession, project_id: uuid.UUID) -> list[Document]:
    return list((await session.execute(select(Document).where(Document.project_id == project_id))).scalars().all())


@pytest.mark.asyncio
async def test_sync_empty_folder_creates_nothing(session: AsyncSession, tmp_path: Path) -> None:
    """An existing-but-empty watched folder syncs to nothing (no rows, no error)."""
    user = await _user(session)
    proj = await _project(session, user)
    empty = tmp_path / "empty-drop"
    empty.mkdir()

    source = await ConnectorService(session).create_source(
        project_id=proj.id, name="Empty", root_path=str(empty), created_by=str(user.id)
    )
    result = await ConnectorService(session).sync_source(source, user_id=str(user.id))

    assert result == {
        "source_id": str(source.id),
        "created": 0,
        "duplicate": 0,
        "already_known": 0,
        "total": 0,
        "created_document_ids": [],
    }
    assert await _docs_for(session, proj.id) == []
    # Even an empty sync stamps the source so the UI shows it ran.
    assert source.last_synced_at
    assert source.last_result["total"] == 0


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_access_denied_is_404_for_non_member(session: AsyncSession) -> None:
    """A non-owner, non-member, non-admin hitting another project's source 404s.

    This is the IDOR gate the connectors router applies before listing or syncing
    a source; a 404 (not 403) keeps project existence from leaking.
    """
    owner = await _user(session, role="manager")
    proj = await _project(session, owner)
    stranger = await _user(session, role="manager")

    with pytest.raises(HTTPException) as exc:
        await verify_project_access(proj.id, str(stranger.id), session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_missing_source_returns_none(session: AsyncSession) -> None:
    """Fetching a source id that does not exist returns None (router -> 404)."""
    assert await ConnectorService(session).get_source(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_resync_after_new_file_is_incremental(session: AsyncSession, tmp_path: Path) -> None:
    """A second sync imports only the genuinely new file, not the known ones."""
    user = await _user(session)
    proj = await _project(session, user)
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "a.txt").write_text("alpha")
    svc = ConnectorService(session)
    source = await svc.create_source(project_id=proj.id, name="Drop", root_path=str(drop), created_by=str(user.id))

    first = await svc.sync_source(source, user_id=str(user.id))
    assert first["created"] == 1

    # Drop a new file and re-sync: only the new one is created, the old is known.
    (drop / "b.txt").write_text("bravo")
    second = await svc.sync_source(source, user_id=str(user.id))
    assert second["created"] == 1
    assert second["already_known"] == 1
    assert second["total"] == 2
    assert len(await _docs_for(session, proj.id)) == 2


@pytest.mark.asyncio
async def test_two_sources_do_not_cross_deduplicate(session: AsyncSession, tmp_path: Path) -> None:
    """Identical content under two distinct sources imports once per source.

    Dedup is keyed on the source name, so the same bytes arriving through a
    different registered source are still captured (they are a different record
    of receipt), not silently dropped as a duplicate of the other source.
    """
    user = await _user(session)
    proj = await _project(session, user)
    svc = ConnectorService(session)

    drop_a = tmp_path / "a"
    drop_b = tmp_path / "b"
    drop_a.mkdir()
    drop_b.mkdir()
    (drop_a / "shared.txt").write_text("same bytes")
    (drop_b / "shared.txt").write_text("same bytes")

    src_a = await svc.create_source(project_id=proj.id, name="Source A", root_path=str(drop_a), created_by=str(user.id))
    src_b = await svc.create_source(project_id=proj.id, name="Source B", root_path=str(drop_b), created_by=str(user.id))

    r_a = await svc.sync_source(src_a, user_id=str(user.id))
    r_b = await svc.sync_source(src_b, user_id=str(user.id))

    assert r_a["created"] == 1
    # Source B sees its own file as new despite the identical content under A.
    assert r_b["created"] == 1
    assert len(await _docs_for(session, proj.id)) == 2


@pytest.mark.asyncio
async def test_sources_are_project_scoped(session: AsyncSession, tmp_path: Path) -> None:
    """list_sources returns only the queried project's sources, not a sibling's."""
    user = await _user(session)
    proj_a = await _project(session, user)
    proj_b = await _project(session, user)
    svc = ConnectorService(session)

    drop = tmp_path / "shared"
    drop.mkdir()
    await svc.create_source(project_id=proj_a.id, name="Only A", root_path=str(drop), created_by=str(user.id))

    assert len(await svc.list_sources(proj_a.id)) == 1
    assert await svc.list_sources(proj_b.id) == []
