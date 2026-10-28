"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the SQL fallback layer of unified search.

BUG-013 / IMP-016: when LanceDB is not installed (fresh ``pip install``
without ``[vector]`` extras) the unified search must still return hits
via SQL ILIKE on the canonical text columns of every collection's
backing table. Without this the global search is silently broken on
every default deployment.

These tests exercise :func:`_sql_search_collection` directly with a
transaction-isolated PostgreSQL session (cloned from a schema-loaded
template by ``tests._pg.transactional_session``) seeded with rows in the
tables that back each collection (BOQ positions, tasks, risks,
requirements, costs). The vector layer is intentionally not invoked -
the goal is to pin the SQL contract independent of any embedding model.
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
    COLLECTION_TASKS,
)
from app.modules.boq.models import BOQ, Position
from app.modules.costs.models import CostItem
from app.modules.projects.models import Project
from app.modules.requirements.models import Requirement, RequirementSet
from app.modules.risk.models import RiskItem
from app.modules.search.service import _sql_search_collection
from app.modules.tasks.models import Task
from app.modules.users.models import User


@pytest_asyncio.fixture
async def session() -> AsyncIterator[tuple[AsyncSession, str]]:
    """Transaction-isolated PostgreSQL session seeded with one row per collection.

    Yields ``(session, project_id)`` so individual tests can exercise the
    optional ``project_id`` scope filter without re-seeding.
    """
    from tests._pg import transactional_session

    project_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    async with transactional_session() as s:
        # Owner — Project.owner_id is NOT NULL with FK to oe_users_user.
        owner = User(
            id=owner_id,
            email="owner@test.io",
            hashed_password="x",
            full_name="Test Owner",
        )
        s.add(owner)
        await s.flush()

        # Project (FK target for everything else)
        project = Project(id=project_id, name="Test Project", description="", owner_id=owner_id)
        s.add(project)
        await s.flush()

        # BOQ + Positions
        boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="Main BOQ", description="")
        s.add(boq)
        await s.flush()

        s.add_all(
            [
                Position(
                    id=uuid.uuid4(),
                    boq_id=boq.id,
                    ordinal="01.001",
                    description="Test position 1",
                    unit="m2",
                    quantity="10",
                    unit_rate="50",
                    total="500",
                    classification={},
                    cad_element_ids=[],
                    metadata_={},
                ),
                Position(
                    id=uuid.uuid4(),
                    boq_id=boq.id,
                    ordinal="01.002",
                    description="Concrete wall foundation",
                    unit="m3",
                    quantity="5",
                    unit_rate="200",
                    total="1000",
                    classification={},
                    cad_element_ids=[],
                    metadata_={},
                ),
            ]
        )

        # Tasks
        s.add_all(
            [
                Task(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    task_type="general",
                    title="Test task — review drawings",
                    description="Walk through the structural set",
                    checklist=[],
                    persons_involved=[],
                    bim_element_ids=[],
                ),
                Task(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    task_type="general",
                    title="Order steel rebar",
                    description="",
                    checklist=[],
                    persons_involved=[],
                    bim_element_ids=[],
                ),
            ]
        )

        # Risks
        s.add(
            RiskItem(
                id=uuid.uuid4(),
                project_id=project_id,
                code="R-001",
                title="Test risk — weather delay",
                description="Unexpected rainfall during foundation pour",
                category="schedule",
            )
        )

        # Requirement set + requirement
        rset = RequirementSet(
            id=uuid.uuid4(),
            project_id=project_id,
            name="Fire safety",
            description="",
        )
        s.add(rset)
        await s.flush()
        s.add(
            Requirement(
                id=uuid.uuid4(),
                requirement_set_id=rset.id,
                entity="exterior_wall",
                attribute="fire_rating",
                constraint_type="equals",
                constraint_value="F90",
                notes="Test requirement constraint",
            )
        )

        # Costs
        s.add(
            CostItem(
                id=uuid.uuid4(),
                code="C-100",
                description="Test cost item — concrete C30/37",
                unit="m3",
                rate="120.00",
                currency="EUR",
                source="cwicr",
                classification={},
                components=[],
                tags=[],
                region="DE_BERLIN",
                is_active=True,
                metadata_={},
            )
        )

        await s.commit()
        yield s, str(project_id)


# ── BOQ ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sql_fallback_finds_boq_position(session: tuple[AsyncSession, str]) -> None:
    """BUG-013 reproduction: 'Test' in BOQ description must surface."""
    s, _project_id = session
    hits = await _sql_search_collection(s, COLLECTION_BOQ, "Test", limit=10)
    assert len(hits) >= 1
    descriptions = [h.text for h in hits]
    assert any("Test position 1" in d for d in descriptions)
    assert all(h.collection == COLLECTION_BOQ for h in hits)


@pytest.mark.asyncio
async def test_sql_fallback_boq_project_scope(session: tuple[AsyncSession, str]) -> None:
    """``project_id`` filter must drop hits from other projects."""
    s, project_id = session
    same = await _sql_search_collection(s, COLLECTION_BOQ, "Test", project_id=project_id)
    assert len(same) >= 1
    other = await _sql_search_collection(s, COLLECTION_BOQ, "Test", project_id=str(uuid.uuid4()))
    assert other == []


# ── Tasks ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sql_fallback_finds_task(session: tuple[AsyncSession, str]) -> None:
    s, _ = session
    hits = await _sql_search_collection(s, COLLECTION_TASKS, "Test task", limit=10)
    assert len(hits) == 1
    assert "review drawings" in hits[0].text.lower() or "review drawings" in hits[0].payload.get("title", "").lower()


@pytest.mark.asyncio
async def test_sql_fallback_task_matches_description(
    session: tuple[AsyncSession, str],
) -> None:
    """Substring in description (not title) must still match."""
    s, _ = session
    hits = await _sql_search_collection(s, COLLECTION_TASKS, "structural", limit=10)
    assert len(hits) == 1


# ── Risks ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sql_fallback_finds_risk(session: tuple[AsyncSession, str]) -> None:
    s, _ = session
    hits = await _sql_search_collection(s, COLLECTION_RISKS, "weather", limit=10)
    assert len(hits) == 1
    assert hits[0].payload.get("code") == "R-001"


# ── Requirements ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sql_fallback_finds_requirement(session: tuple[AsyncSession, str]) -> None:
    s, _ = session
    hits = await _sql_search_collection(s, COLLECTION_REQUIREMENTS, "fire_rating", limit=10)
    assert len(hits) == 1
    assert "fire_rating" in hits[0].payload.get("title", "")


@pytest.mark.asyncio
async def test_sql_fallback_requirement_via_notes(
    session: tuple[AsyncSession, str],
) -> None:
    """A free-text token in ``notes`` must still surface the requirement."""
    s, _ = session
    hits = await _sql_search_collection(s, COLLECTION_REQUIREMENTS, "Test requirement", limit=10)
    assert len(hits) == 1


# ── Costs ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sql_fallback_finds_cost_item(session: tuple[AsyncSession, str]) -> None:
    s, _ = session
    hits = await _sql_search_collection(s, COLLECTION_COSTS, "concrete", limit=10)
    assert len(hits) == 1
    assert hits[0].payload.get("code") == "C-100"


# ── Empty / no-match safety ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sql_fallback_empty_query_returns_no_hits(
    session: tuple[AsyncSession, str],
) -> None:
    s, _ = session
    hits = await _sql_search_collection(s, COLLECTION_BOQ, "   ", limit=10)
    assert hits == []


@pytest.mark.asyncio
async def test_sql_fallback_no_match_returns_empty(
    session: tuple[AsyncSession, str],
) -> None:
    s, _ = session
    hits = await _sql_search_collection(s, COLLECTION_BOQ, "definitely-not-anywhere-xyz", limit=10)
    assert hits == []


@pytest.mark.asyncio
async def test_sql_fallback_unknown_collection_returns_empty(
    session: tuple[AsyncSession, str],
) -> None:
    """Collections without a SQL fallback (chat, validation, bim_elements
    via DDC, …) gracefully degrade to []."""
    s, _ = session
    hits = await _sql_search_collection(s, "oe_chat", "anything", limit=10)
    assert hits == []
