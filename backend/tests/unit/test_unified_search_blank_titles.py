# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The unified search must name a hit by something the searcher could have typed.

The SQL track matches a row on one set of columns and titles it from a
narrower one. Where a searched column is missing from the title chain, a row
that carries only that column comes back with no title at all, and
``VectorHit.title`` then falls through its own chain to the row's bare id. A
UUID identifies nothing to the person reading the result list, and this is the
track a stock install runs on: the vector extra is optional, so on most
deployments SQL recall is the only recall there is.

Each test asserts the title carries the string that was searched for. A title
of ``"."`` or of a raw id is truthy, so a check for a non-empty string would
pass against exactly the output being fixed here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector_index import (
    COLLECTION_BOQ,
    COLLECTION_COSTS,
    COLLECTION_REQUIREMENTS,
    COLLECTION_RISKS,
    COLLECTION_SUBMITTALS,
)
from app.modules.boq.models import BOQ, Position
from app.modules.costs.models import CostItem
from app.modules.projects.models import Project
from app.modules.requirements.models import Requirement, RequirementSet
from app.modules.risk.models import RiskItem
from app.modules.search.service import _sql_search_collection_raw
from app.modules.submittals.models import Submittal
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside a rolled-back outer transaction."""
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def project_id(session: AsyncSession) -> uuid.UUID:
    """A project to hang the project-scoped records off."""
    owner = User(
        email=f"unified-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Unified Titles",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Unified titles", owner_id=owner.id, currency="EUR", region="DE_BERLIN")
    session.add(project)
    await session.flush()
    return project.id


def _token() -> str:
    """A string no other row in the database can carry."""
    return uuid.uuid4().hex[:10]


def _assert_named_by(hits: list, needle: str, row_id: uuid.UUID) -> None:
    """One hit, titled by the string the searcher typed rather than by its id."""
    assert len(hits) == 1
    title = hits[0].title
    assert title != str(row_id), "a bare identifier is not a name a person can read"
    assert needle in title, f"title {title!r} does not carry the searched string {needle!r}"


@pytest.mark.asyncio
async def test_a_position_found_by_its_ordinal_is_named_by_it(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Positions are searched on the ordinal, and were titled on description alone."""
    token = _token()
    boq = BOQ(project_id=project_id, name="Unified harness")
    session.add(boq)
    await session.flush()
    position = Position(boq_id=boq.id, ordinal=f"01.{token}", description="", unit="m3")
    session.add(position)
    await session.flush()

    hits = await _sql_search_collection_raw(session, COLLECTION_BOQ, token)

    _assert_named_by(hits, token, position.id)


@pytest.mark.asyncio
async def test_a_risk_found_by_its_code_is_named_by_it(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Risks are searched on the register code, which the title never carried."""
    token = _token()
    risk = RiskItem(project_id=project_id, code=f"R-{token}", title="", description="")
    session.add(risk)
    await session.flush()

    hits = await _sql_search_collection_raw(session, COLLECTION_RISKS, token)

    _assert_named_by(hits, token, risk.id)


@pytest.mark.asyncio
async def test_a_submittal_found_by_its_spec_section_is_named_by_it(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """The spec section is searched, and is often all a raised submittal has."""
    token = _token()
    submittal = Submittal(
        project_id=project_id,
        submittal_number="",
        title="",
        submittal_type="product_data",
        spec_section=f"03 30 {token}",
    )
    session.add(submittal)
    await session.flush()

    hits = await _sql_search_collection_raw(session, COLLECTION_SUBMITTALS, token)

    _assert_named_by(hits, token, submittal.id)


@pytest.mark.asyncio
async def test_a_requirement_found_by_its_notes_is_not_titled_by_a_lone_dot(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """Entity and attribute may both be blank, leaving the joining dot alone."""
    token = _token()
    rset = RequirementSet(project_id=project_id, name="Unified harness")
    session.add(rset)
    await session.flush()
    requirement = Requirement(
        requirement_set_id=rset.id,
        entity="",
        attribute="",
        constraint_value="",
        notes=f"Client to confirm the finish {token}",
    )
    session.add(requirement)
    await session.flush()

    hits = await _sql_search_collection_raw(session, COLLECTION_REQUIREMENTS, token)

    assert len(hits) == 1
    assert hits[0].title != ".", "a lone separator names nothing"
    _assert_named_by(hits, token, requirement.id)


@pytest.mark.asyncio
async def test_a_cost_item_found_by_its_code_is_named_by_it(session: AsyncSession) -> None:
    """Cost items are searched on the code, and were titled on description alone.

    This one never lost the code: with no title, ``VectorHit`` fell through to
    the snippet, which prefixes it. What the reader got was the separator with
    nothing after it, so the title is pinned exactly rather than by substring.
    """
    token = _token()
    item = CostItem(code=f"C-{token}", description="", unit="m", rate="42.00")
    session.add(item)
    await session.flush()

    hits = await _sql_search_collection_raw(session, COLLECTION_COSTS, token)

    _assert_named_by(hits, token, item.id)
    assert hits[0].title == f"C-{token}"


# --- Negative controls: the added fallbacks must not displace a real title ---


@pytest.mark.asyncio
async def test_a_described_position_is_still_titled_by_its_description(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """Without this, a fix reaching for the ordinal would renumber every result."""
    token = _token()
    boq = BOQ(project_id=project_id, name="Unified harness")
    session.add(boq)
    await session.flush()
    session.add(Position(boq_id=boq.id, ordinal="01.10.030", description=f"Blinding {token}", unit="m2"))
    await session.flush()

    hits = await _sql_search_collection_raw(session, COLLECTION_BOQ, token)

    assert len(hits) == 1
    assert hits[0].title == f"Blinding {token}"


@pytest.mark.asyncio
async def test_a_titled_risk_is_still_titled_by_its_title(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The code is the last resort, not the label."""
    token = _token()
    session.add(RiskItem(project_id=project_id, code="R-014", title=f"Late steel delivery {token}"))
    await session.flush()

    hits = await _sql_search_collection_raw(session, COLLECTION_RISKS, token)

    assert len(hits) == 1
    assert hits[0].title == f"Late steel delivery {token}"


@pytest.mark.asyncio
async def test_a_requirement_still_reads_entity_dot_attribute(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The pair is how a requirement reads on its own page; keep it."""
    token = _token()
    rset = RequirementSet(project_id=project_id, name="Unified harness")
    session.add(rset)
    await session.flush()
    session.add(
        Requirement(
            requirement_set_id=rset.id,
            entity=f"exterior_wall_{token}",
            attribute="fire_rating",
            constraint_value="EI90",
        )
    )
    await session.flush()

    hits = await _sql_search_collection_raw(session, COLLECTION_REQUIREMENTS, token)

    assert len(hits) == 1
    assert hits[0].title == f"exterior_wall_{token}.fire_rating"
