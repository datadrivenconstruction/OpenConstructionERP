# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the retrieval (findability) service (PostgreSQL, py3.12).

Seeds a document, a correspondence and a change order on one project, then
checks faceted, ranked search across all three: free text, record-type filter,
party filter, and the empty "browse everything" query.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _seed(session: AsyncSession) -> Project:
    user = User(
        email=f"ret-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Ret",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Ret {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()

    session.add_all(
        [
            Document(
                project_id=proj.id,
                name="Rebar layout drawing",
                description="Rebar spacing for the level 3 slab.",
            ),
            Correspondence(
                project_id=proj.id,
                reference_number="C-100",
                direction="incoming",
                subject="Concrete pour schedule",
                correspondence_type="letter",
                from_contact_id="acme",
                date_sent="2026-06-20",
                notes="Confirm the concrete pour date.",
            ),
            ChangeOrder(
                project_id=proj.id,
                code="CO-7",
                title="Additional rebar to core wall",
                description="Add rebar to the core wall.",
                ball_in_court="contractor-a",
            ),
        ]
    )
    await session.flush()
    return proj


@pytest.mark.asyncio
async def test_text_search_ranks_matching_records(session: AsyncSession) -> None:
    proj = await _seed(session)
    results = await RetrievalService(session).search(proj.id, FacetQuery(text="rebar"))

    types = {r.record.record_type for r in results}
    assert "document" in types
    assert "change_order" in types
    # The concrete-only correspondence does not match the term.
    assert "correspondence" not in types
    # Every hit carries provenance for reconstruction.
    for r in results:
        assert r.provenance["module"]
        assert r.provenance["record_id"] == r.record.record_id


@pytest.mark.asyncio
async def test_record_type_facet_filters(session: AsyncSession) -> None:
    proj = await _seed(session)
    results = await RetrievalService(session).search(proj.id, FacetQuery(record_types=frozenset({"document"})))
    assert len(results) == 1
    assert results[0].record.record_type == "document"


@pytest.mark.asyncio
async def test_party_facet_filters(session: AsyncSession) -> None:
    proj = await _seed(session)
    results = await RetrievalService(session).search(proj.id, FacetQuery(parties=frozenset({"contractor-a"})))
    assert len(results) == 1
    assert results[0].record.record_type == "change_order"


@pytest.mark.asyncio
async def test_empty_query_browses_everything(session: AsyncSession) -> None:
    proj = await _seed(session)
    results = await RetrievalService(session).search(proj.id, FacetQuery())
    # All three seeded records come back as a ranked browse.
    assert len(results) == 3
    assert {r.record.record_type for r in results} == {"document", "correspondence", "change_order"}
