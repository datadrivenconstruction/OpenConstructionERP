# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Creating a requirement has to leave something a response can be built from.

Both write routes in this module answered with a server error. The cause was
not in either route: ``create`` and ``bulk_create`` add a row and flush it, and
a flush is not a load, so the ``selectin`` collections and every column the
insert did not name came back unloaded. The response schema then read
``linked_position_ids``, which reads ``position_links``, which asked the
database for rows from inside a synchronous property on an asynchronous
session. That cannot emit IO from where it is standing, so it raised, and both
routes turned the raise into a 500.

What makes this worth pinning rather than patching is that no test could see
it. The suite's own helpers call ``session.refresh`` after creating a row, and
a refresh is a load, so every fixture-built requirement was fully populated and
every assertion about one passed. Only a row created the way the service
creates one is in the failing state.

These assert the response path itself - the same ``model_validate`` the router
runs - rather than the exception type, because pydantic wraps the failure and a
test that named the inner error would pass for the wrong reason.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager

import pytest
import pytest_asyncio
from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.projects.models  # noqa: F401  - FK target must be in metadata
from app.modules.projects.models import Project
from app.modules.requirements.models import Requirement, RequirementSet
from app.modules.requirements.repository import settle_new_row
from app.modules.requirements.schemas import RequirementCreate, RequirementResponse
from app.modules.requirements.service import RequirementsService, _requirement_from_create
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@contextmanager
def _counting_queries(session: AsyncSession) -> Iterator[Callable[[], int]]:
    """Count the ORM statements issued inside the block.

    Verified to see what it needs to see: the refresh-based alternative to the
    repair measures four here, so a fix that quietly started fetching would be
    caught rather than merely disapproved of in a comment.
    """
    seen = 0

    def _bump(_context: object) -> None:
        nonlocal seen
        seen += 1

    sync_session = session.sync_session
    event.listen(sync_session, "do_orm_execute", _bump)
    try:
        yield lambda: seen
    finally:
        event.remove(sync_session, "do_orm_execute", _bump)


async def _make_set(session: AsyncSession) -> uuid.UUID:
    """A real project owned by a real user, and one set inside it."""
    user = User(email=f"u{uuid.uuid4().hex[:8]}@unloaded.test", hashed_password="x")
    session.add(user)
    await session.flush()

    project = Project(name="Unloaded Row Project", owner_id=user.id)
    session.add(project)
    await session.flush()

    req_set = RequirementSet(
        project_id=project.id,
        name="Fire protection",
        description="",
        source_type="manual",
        status="draft",
        created_by="test",
    )
    session.add(req_set)
    await session.flush()
    return req_set.id


def _payload(entity: str = "wall") -> RequirementCreate:
    return RequirementCreate(
        entity=entity,
        attribute="fire_rating",
        constraint_type="equals",
        constraint_value="F90",
    )


class TestASingleWriteAnswersWithTheRowItWrote:
    @pytest.mark.asyncio
    async def test_the_response_schema_can_read_a_freshly_added_requirement(self, session: AsyncSession) -> None:
        """This is the 500. ``_req_to_response`` runs exactly this call."""
        set_id = await _make_set(session)

        item = await RequirementsService(session).add_requirement(set_id, _payload(), user_id="test")
        response = RequirementResponse.model_validate(item, from_attributes=True)

        assert response.entity == "wall"
        assert response.linked_position_ids == []
        assert response.linked_position_id is None

    @pytest.mark.asyncio
    async def test_the_eager_collections_are_settled_without_a_query(self, session: AsyncSession) -> None:
        """Empty because the row is new, not because anything was fetched.

        A row that did not exist a moment ago has no links, no deliverables and
        no children, so the repository says so instead of asking.

        The query count is asserted rather than described. Settling the row by
        refreshing it would satisfy every other test in this file while costing
        four extra round trips on every write, and a test that only checked the
        loaded state would not notice.
        """
        set_id = await _make_set(session)
        item = _requirement_from_create(set_id, _payload(), "test")
        session.add(item)
        await session.flush()

        # Bracketed around the settling alone. ``add_requirement`` reads the set
        # first and is entitled to that query; the repair is what must be free.
        with _counting_queries(session) as count:
            settle_new_row(item)
            settled = count()

        unloaded = inspect(item).unloaded
        assert "position_links" not in unloaded
        assert "deliverables" not in unloaded
        assert "children" not in unloaded
        assert settled == 0, f"settling a new row cost {settled} queries; it should cost none"

    @pytest.mark.asyncio
    async def test_the_scalar_relationships_are_left_alone(self, session: AsyncSession) -> None:
        """``parent`` and ``requirement_set`` are ``raise_on_sql`` by declaration.

        Unloaded is the state that declaration asks for. Settling them to None
        would answer "this requirement has no set", and it has one.
        """
        set_id = await _make_set(session)

        item = await RequirementsService(session).add_requirement(set_id, _payload(), user_id="test")

        unloaded = inspect(item).unloaded
        assert "parent" in unloaded
        assert "requirement_set" in unloaded


class TestTheBulkWriteAnswersWithEveryRowItWrote:
    @pytest.mark.asyncio
    async def test_the_response_schema_can_read_every_bulk_added_requirement(self, session: AsyncSession) -> None:
        """The bulk route had the same defect and no test of its own.

        It shares a creator with the single-row route, so a fix placed there
        covers both - but a fix proved only on the route that was already
        covered is a fix tested at the wrong end.
        """
        set_id = await _make_set(session)

        items = await RequirementsService(session).bulk_add_requirements(
            set_id,
            [_payload("wall"), _payload("slab"), _payload("column")],
            user_id="test",
        )

        assert len(items) == 3
        responses = [RequirementResponse.model_validate(item, from_attributes=True) for item in items]
        assert {r.entity for r in responses} == {"wall", "slab", "column"}
        assert all(r.linked_position_ids == [] for r in responses)

    @pytest.mark.asyncio
    async def test_a_bulk_row_reports_its_completeness(self, session: AsyncSession) -> None:
        """The two computed fields read the link table through the same property.

        They are separate fields on the response, and all three failures the
        route reported traced back to this one access.
        """
        set_id = await _make_set(session)

        items = await RequirementsService(session).bulk_add_requirements(set_id, [_payload()], user_id="test")

        assert isinstance(items[0].cycle_completeness, float)
        assert isinstance(items[0].unanswered_questions, list)


class TestTheTextImportWritesReadableRowsToo:
    @pytest.mark.asyncio
    async def test_rows_built_outside_the_factory_are_settled_as_well(self, session: AsyncSession) -> None:
        """Inline rows reach the same creator, which is why it holds the repair.

        ``import_from_text`` constructs its requirements directly rather than
        through ``_requirement_from_create``. Put at the factory, the fix would
        have covered two of the three creators and missed this one, which is
        only safe today because the route happens to re-read the set.
        """
        set_id = await _make_set(session)

        item = Requirement(
            requirement_set_id=set_id,
            entity="door",
            attribute="fire_rating",
            constraint_type="equals",
            constraint_value="T30",
            created_by="test",
        )
        (created,) = await RequirementsService(session).req_repo.bulk_create([item])

        assert RequirementResponse.model_validate(created, from_attributes=True).linked_position_ids == []
