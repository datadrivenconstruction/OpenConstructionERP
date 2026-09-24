# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The project list pages in a total order, so no page repeats or skips a row.

``ProjectRepository.list_for_user`` sorted by ``created_at`` alone. Projects
created in one transaction (a seed, a pack install, a bulk import) share that
timestamp, and PostgreSQL does not promise any order among tied rows: a top-N
sort under ``LIMIT`` may hand the same project to two pages and none to
another. ``id`` now breaks the tie.

The tied rows are given one identical ``created_at`` on purpose, and the order
is checked against ``id`` descending, which random UUIDs would match by chance
about once in 720 tries on six rows. A test that only paged through rows with
distinct timestamps would pass with or without the tiebreaker.

Run:
    cd backend
    python -m pytest tests/modules/test_project_list_ties_break_on_id.py -v
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from tests._pg import transactional_session

_TIED_AT = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so projects can be seeded without standing up a user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _tied_projects(session: AsyncSession, owner_id: uuid.UUID, count: int) -> list[uuid.UUID]:
    ids = []
    for n in range(count):
        project = Project(name=f"Tied {n} {uuid.uuid4().hex[:6]}", currency="EUR", region="DACH", owner_id=owner_id)
        session.add(project)
        await session.flush()
        ids.append(project.id)
    await session.execute(update(Project).where(Project.id.in_(ids)).values(created_at=_TIED_AT))
    await session.flush()
    session.expunge_all()
    return ids


async def test_tied_projects_come_back_in_id_order(session: AsyncSession) -> None:
    owner_id = uuid.uuid4()
    ids = await _tied_projects(session, owner_id, 6)

    listed, total = await ProjectRepository(session).list_for_user(owner_id, offset=0, limit=50)

    assert total == 6
    assert [p.id for p in listed] == sorted(ids, key=lambda i: i.hex, reverse=True)


async def test_pages_over_tied_projects_neither_repeat_nor_skip(session: AsyncSession) -> None:
    owner_id = uuid.uuid4()
    ids = await _tied_projects(session, owner_id, 6)
    repo = ProjectRepository(session)

    paged: list[uuid.UUID] = []
    for offset in range(0, 6, 2):
        page, _ = await repo.list_for_user(owner_id, offset=offset, limit=2)
        paged.extend(p.id for p in page)

    assert len(paged) == len(set(paged)) == 6
    assert set(paged) == set(ids)
