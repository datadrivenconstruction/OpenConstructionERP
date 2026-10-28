# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Edge-case integration tests for the retrieval module (PostgreSQL, py3.12).

Complements ``test_retrieval_search.py`` with the boundaries: searching a project
that holds nothing, a term that matches nothing, the wrong-project / access-denied
404 the router enforces, that one project's records never surface in another's
search, and a record-type facet that matches no record.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import verify_project_access
from app.modules.changeorders.models import ChangeOrder
from app.modules.correspondence.models import Correspondence
from app.modules.documents.models import Document
from app.modules.projects.models import Project
from app.modules.retrieval.facet_query import FacetQuery
from app.modules.retrieval.service import RetrievalService
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, *, role: str = "admin") -> User:
    user = User(
        email=f"ret-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Ret",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, owner: User) -> Project:
    proj = Project(name=f"Ret {uuid.uuid4().hex[:6]}", owner_id=owner.id)
    session.add(proj)
    await session.flush()
    return proj


async def _seed_one_doc(session: AsyncSession, project_id: uuid.UUID) -> None:
    session.add(
        Document(
            project_id=project_id,
            name="Rebar layout drawing",
            description="Rebar spacing for the level 3 slab.",
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_empty_project_search_returns_nothing(session: AsyncSession) -> None:
    """Searching (or browsing) a project with no records yields an empty list."""
    owner = await _user(session)
    proj = await _project(session, owner)

    svc = RetrievalService(session)
    assert await svc.search(proj.id, FacetQuery()) == []
    assert await svc.search(proj.id, FacetQuery(text="anything")) == []


@pytest.mark.asyncio
async def test_term_matching_nothing_returns_empty(session: AsyncSession) -> None:
    """A free-text term no record contains returns no hits (not an error)."""
    owner = await _user(session)
    proj = await _project(session, owner)
    await _seed_one_doc(session, proj.id)

    results = await RetrievalService(session).search(proj.id, FacetQuery(text="helicopter"))
    assert results == []


@pytest.mark.asyncio
async def test_unknown_record_type_facet_returns_empty(session: AsyncSession) -> None:
    """A record-type facet that matches no record type yields nothing."""
    owner = await _user(session)
    proj = await _project(session, owner)
    await _seed_one_doc(session, proj.id)

    results = await RetrievalService(session).search(proj.id, FacetQuery(record_types=frozenset({"nonsense_type"})))
    assert results == []


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_access_denied_is_404_for_non_member(session: AsyncSession) -> None:
    """A stranger searching another project is 404 (the router's IDOR gate)."""
    owner = await _user(session, role="manager")
    proj = await _project(session, owner)
    stranger = await _user(session, role="manager")

    with pytest.raises(HTTPException) as exc:
        await verify_project_access(proj.id, str(stranger.id), session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_search_is_project_scoped(session: AsyncSession) -> None:
    """One project's records never surface in another project's search."""
    owner = await _user(session)
    proj_a = await _project(session, owner)
    proj_b = await _project(session, owner)

    # Seed distinctive records on A only.
    session.add_all(
        [
            Document(project_id=proj_a.id, name="Alpha drawing", description="rebar at level 3"),
            Correspondence(
                project_id=proj_a.id,
                reference_number="C-1",
                direction="incoming",
                subject="rebar query",
                correspondence_type="letter",
                date_sent="2026-06-20",
            ),
            ChangeOrder(project_id=proj_a.id, code="CO-1", title="rebar addition", description="more rebar"),
        ]
    )
    await session.flush()

    svc = RetrievalService(session)
    assert len(await svc.search(proj_a.id, FacetQuery(text="rebar"))) == 3
    # B holds nothing matching - the term that lit up A is silent here.
    assert await svc.search(proj_b.id, FacetQuery(text="rebar")) == []
    # And a blank browse on B is empty too.
    assert await svc.search(proj_b.id, FacetQuery()) == []
