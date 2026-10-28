# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A requirement governs work, plural, and both writers have to agree on that.

``link_to_position`` predates the link table. It writes ``linked_position_id``,
one column, so linking position A and then position B leaves the requirement
naming B and nothing at all remembering A. That was defensible while one column
was the whole answer. It stopped being defensible the moment
``linked_position_ids`` started reporting every position a requirement governs,
because then the route quietly loses data the model claims to hold.

The two writers therefore have to maintain the same two representations. The
column keeps its meaning, the most recently linked position, and the link table
accumulates. These tests hold both writers to that, in both orders, and check
that unlinking is not confused by a requirement that arrived through the old
route and was migrated into the new table.

A requirement and the bill it links to belong to one project. These tests once
paired two unrelated random project ids, which made every one of them an
assertion about a boundary that should not be crossable at all; they now build
one real project and put both sides of the link inside it.

Pattern: PostgreSQL transaction-isolated session, FK enforcement off, same as
the neighbouring matrix tests.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure FK targets are in metadata.
import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.requirements.models import Requirement, RequirementSet
from app.modules.requirements.schemas import PositionLinkCreate
from app.modules.requirements.service import RequirementsService
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _make_boq(session: AsyncSession, project_id: uuid.UUID) -> BOQ:
    boq = BOQ(project_id=project_id, name="Bill")
    session.add(boq)
    await session.flush()
    await session.refresh(boq)
    return boq


async def _make_position(session: AsyncSession, boq_id: uuid.UUID, ordinal: str) -> Position:
    position = Position(
        boq_id=boq_id,
        ordinal=ordinal,
        description=f"Exterior wall {ordinal}",
        unit="m2",
    )
    session.add(position)
    await session.flush()
    await session.refresh(position)
    return position


async def _make_project(session: AsyncSession) -> uuid.UUID:
    """A real project, owned by a real user, for a requirement and a bill to share.

    These tests used to give the requirement set one random project_id and the
    BOQ another, so every one of them linked a requirement to a position in a
    different project. That is not a crossable boundary, and once
    ``link_to_position`` started comparing the two projects all eight failed.
    They were not incidental casualties of that guard: between them they were
    the closest thing the suite had to a description of the old behaviour, and
    what they described was the defect.
    """
    user = User(email=f"u{uuid.uuid4().hex[:8]}@link.test", hashed_password="x")
    session.add(user)
    await session.flush()

    project = Project(name="Link Test Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


async def _make_requirement(session: AsyncSession, project_id: uuid.UUID) -> Requirement:
    req_set = RequirementSet(
        project_id=project_id,
        name="Fire protection",
        description="",
        source_type="manual",
        status="draft",
        created_by="test",
    )
    session.add(req_set)
    await session.flush()

    req = Requirement(
        requirement_set_id=req_set.id,
        entity="wall",
        attribute="fire_rating",
        constraint_type="equals",
        constraint_value="F90",
        priority="must",
        status="open",
        created_by="test",
    )
    session.add(req)
    await session.flush()
    await session.refresh(req)
    return req


class TestTheLegacyRouteKeepsWhatItWasGiven:
    @pytest.mark.asyncio
    async def test_linking_a_second_position_does_not_lose_the_first(self, session: AsyncSession) -> None:
        """Link A, then link B. Both are still governed.

        Before the link table this route could only answer with B, because one
        column cannot hold two answers. Now that ``linked_position_ids`` exists,
        answering with B alone is a loss, not a limitation.
        """
        project_id = await _make_project(session)
        req = await _make_requirement(session, project_id)
        boq = await _make_boq(session, project_id)
        first = await _make_position(session, boq.id, "01.010")
        second = await _make_position(session, boq.id, "01.020")

        service = RequirementsService(session)
        await service.link_to_position(req.id, first.id)
        await service.link_to_position(req.id, second.id)

        links = await service.list_position_links(req.id)
        assert {link.position_id for link in links} == {first.id, second.id}

    @pytest.mark.asyncio
    async def test_the_column_still_names_the_most_recent_position(self, session: AsyncSession) -> None:
        """Callers reading the single column see what they always saw.

        Kept separate from the test above on purpose: the point of the fix is
        that the link table grew a second answer, not that the column changed
        its meaning. A caller that reads ``linked_position_id`` is entitled to
        the same value it got before.
        """
        project_id = await _make_project(session)
        req = await _make_requirement(session, project_id)
        boq = await _make_boq(session, project_id)
        first = await _make_position(session, boq.id, "02.010")
        second = await _make_position(session, boq.id, "02.020")

        service = RequirementsService(session)
        await service.link_to_position(req.id, first.id)
        await service.link_to_position(req.id, second.id)

        stored = await service.req_repo.get_by_id(req.id)
        assert stored is not None
        assert stored.linked_position_id == second.id

    @pytest.mark.asyncio
    async def test_relinking_the_same_position_is_not_an_error(self, session: AsyncSession) -> None:
        """Pressing the button twice must not hit the unique constraint.

        The link table refuses a duplicate pair, and letting that refusal reach
        the caller would surface as a 500 on an action that changed nothing.
        """
        project_id = await _make_project(session)
        req = await _make_requirement(session, project_id)
        boq = await _make_boq(session, project_id)
        position = await _make_position(session, boq.id, "03.010")

        service = RequirementsService(session)
        await service.link_to_position(req.id, position.id)
        await service.link_to_position(req.id, position.id)

        links = await service.list_position_links(req.id)
        assert [link.position_id for link in links] == [position.id]


class TestTheTwoWritersAgree:
    @pytest.mark.asyncio
    async def test_the_old_route_then_the_new_one_reports_both(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        req = await _make_requirement(session, project_id)
        boq = await _make_boq(session, project_id)
        old = await _make_position(session, boq.id, "04.010")
        new = await _make_position(session, boq.id, "04.020")

        service = RequirementsService(session)
        await service.link_to_position(req.id, old.id)
        await service.attach_position(req.id, PositionLinkCreate(position_id=new.id), user_id="tester")

        links = await service.list_position_links(req.id)
        assert {link.position_id for link in links} == {old.id, new.id}

    @pytest.mark.asyncio
    async def test_the_new_route_then_the_old_one_reports_both(self, session: AsyncSession) -> None:
        """The reverse order, which is the one that used to be safe.

        ``attach_position`` never touched the column, so this order never lost
        anything. Asserting it anyway keeps the pair symmetric: a later change
        that makes the old route authoritative again would break here first.
        """
        project_id = await _make_project(session)
        req = await _make_requirement(session, project_id)
        boq = await _make_boq(session, project_id)
        new = await _make_position(session, boq.id, "05.010")
        old = await _make_position(session, boq.id, "05.020")

        service = RequirementsService(session)
        await service.attach_position(req.id, PositionLinkCreate(position_id=new.id), user_id="tester")
        await service.link_to_position(req.id, old.id)

        links = await service.list_position_links(req.id)
        assert {link.position_id for link in links} == {new.id, old.id}

    @pytest.mark.asyncio
    async def test_a_position_reads_back_the_requirement_linked_the_old_way(self, session: AsyncSession) -> None:
        """The reverse direction has to see legacy links too.

        Opening a bill item and asking what it must satisfy is the whole point
        of the link table. A requirement linked through the old route is just as
        binding as one attached through the new one, so it has to appear here.
        """
        project_id = await _make_project(session)
        req = await _make_requirement(session, project_id)
        boq = await _make_boq(session, project_id)
        position = await _make_position(session, boq.id, "06.010")

        service = RequirementsService(session)
        await service.link_to_position(req.id, position.id)

        governing = await service.requirements_for_position(position.id)
        assert [item.id for item in governing] == [req.id]


class TestDetachingWhatTheOldRouteLinked:
    @pytest.mark.asyncio
    async def test_detaching_clears_both_representations(self, session: AsyncSession) -> None:
        """One detach, and neither the table nor the column still claims it.

        A migrated requirement carries the position twice, once per
        representation. Leaving either behind would mean a position that reads
        as detached from one side and attached from the other.
        """
        project_id = await _make_project(session)
        req = await _make_requirement(session, project_id)
        boq = await _make_boq(session, project_id)
        position = await _make_position(session, boq.id, "07.010")

        service = RequirementsService(session)
        await service.link_to_position(req.id, position.id)
        await service.detach_position(req.id, position.id)

        assert await service.list_position_links(req.id) == []
        stored = await service.req_repo.get_by_id(req.id)
        assert stored is not None
        assert stored.linked_position_id is None

    @pytest.mark.asyncio
    async def test_detaching_one_of_two_leaves_the_other(self, session: AsyncSession) -> None:
        project_id = await _make_project(session)
        req = await _make_requirement(session, project_id)
        boq = await _make_boq(session, project_id)
        kept = await _make_position(session, boq.id, "08.010")
        dropped = await _make_position(session, boq.id, "08.020")

        service = RequirementsService(session)
        await service.link_to_position(req.id, kept.id)
        await service.link_to_position(req.id, dropped.id)
        await service.detach_position(req.id, dropped.id)

        links = await service.list_position_links(req.id)
        assert [link.position_id for link in links] == [kept.id]
