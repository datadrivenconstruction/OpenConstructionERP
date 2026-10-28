"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The paged reindex walk, against real PostgreSQL and a real Session.

The unit test beside this one replaces the session with a recorder, which is
what makes its peak measurable - but a recorder agrees with whatever the code
asks it for. Three things it cannot answer live here instead: that
``OFFSET/LIMIT`` over a statement that JOINs through a parent table returns each
row once and all of them, that a real ``Session`` really does let go of a page
when it is expunged, and that the ``selectinload`` on the parent still fires on
every page - the requirement's parent is ``lazy="raise_on_sql"``, so a page that
lost its eager load raises the moment the adapter reads it rather than quietly
issuing another query.

The scope under test is the real one the requirements module registers, not a
copy of it. The last test covers the same three questions for BOQ positions,
which do not come through the factory at all - the endpoint is hand-written
around its own ownership gate - but do share the walk, and are the highest-count
rows in the product, so the eager parent they read through (``Position.boq``,
also ``raise_on_sql``) is the one that costs most if paging breaks it.

The identity map is sampled DURING the pass, from inside the indexing call,
because it holds instances weakly: once the handler returns, the rows it was
holding are garbage whatever shape the read had, and a measurement taken then
would report the same small number for a buffered read and a paged one.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core import vector_routes
from app.modules.projects.models import Project
from app.modules.requirements.models import Requirement, RequirementSet
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

PAGE = 4
ROWS = 13
COLLECTION = "vec_reindex_pg"


class _Adapter:
    collection_name = COLLECTION
    module_name = "vec_reindex_pg"


class _Indexer:
    """Stands in for ``reindex_collection`` and samples the live identity map."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self.ids: list[str] = []
        self.parents: list[str] = []
        self.page_sizes: list[int] = []
        self.peak_held = 0

    async def __call__(self, adapter: Any, rows: list[Any], **_: Any) -> dict[str, Any]:
        self.page_sizes.append(len(rows))
        for row in rows:
            self.ids.append(str(row.id))
            # ``raise_on_sql``: this is a read, not a lazy load, only because
            # the page was fetched with the parent eager-loaded.
            self.parents.append(row.requirement_set.name)
        held = sum(1 for obj in self._session.identity_map.values() if isinstance(obj, Requirement))
        self.peak_held = max(self.peak_held, held)
        return {"indexed": len(rows), "skipped": 0, "purged": False, "collection": adapter.collection_name}


async def _seed(session: Any) -> tuple[uuid.UUID, list[str]]:
    """One project, one requirement set, ROWS requirements. Returns the ids in PK order."""
    owner = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="x",
        full_name="Requirements Manager",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Vector reindex walk", owner_id=owner.id)
    session.add(project)
    await session.flush()
    requirement_set = RequirementSet(project_id=project.id, name="Employer requirements")
    session.add(requirement_set)
    await session.flush()
    for index in range(ROWS):
        session.add(
            Requirement(
                requirement_set_id=requirement_set.id,
                entity=f"Wall {index}",
                attribute="fire_rating",
                constraint_value=f"REI{index}",
            )
        )
    await session.flush()
    ids = [str(value) for value in (await session.execute(select(Requirement.id).order_by(Requirement.id))).scalars()]
    # Start the walk from an empty identity map, so what it holds is what it
    # read rather than what the seeding left behind.
    session.expunge_all()
    return project.id, ids


def _handler(**kwargs: Any) -> Any:
    router = vector_routes.create_vector_routes(
        collection=COLLECTION,
        adapter=_Adapter(),  # type: ignore[arg-type]
        read_permission=None,
        write_permission=None,
        **kwargs,
    )
    return next(route.endpoint for route in router.routes if route.path == "/vector/reindex/")  # type: ignore[attr-defined]


async def test_the_joined_scope_is_walked_once_end_to_end_and_released(
    pg_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.requirements.router import _requirements_statement

    project_id, ids = await _seed(pg_session)
    indexer = _Indexer(pg_session)
    monkeypatch.setattr(vector_routes, "reindex_collection", indexer)
    monkeypatch.setattr(vector_routes, "_REINDEX_PAGE_ROWS", PAGE, raising=False)

    handler = _handler(statement_factory=_requirements_statement)
    result = await handler(pg_session, None, project_id, False)

    # Total: every row once, in the order the pages were addressed by.
    assert indexer.ids == ids
    assert len(set(indexer.ids)) == ROWS
    assert result["scanned"] == ROWS
    assert result["indexed"] == ROWS
    assert result["truncated"] is False

    # Bounded: no page larger than the bound, and the real Session holding no
    # more than one page of requirements at any point during the pass.
    assert max(indexer.page_sizes) <= PAGE
    assert len(indexer.page_sizes) == 4  # 4 + 4 + 4 + 1
    assert indexer.peak_held <= PAGE, (
        f"the session was holding {indexer.peak_held} requirements at once under a page bound of {PAGE}"
    )

    # The eager load survived the paging: every row could read its parent
    # although the relationship refuses to emit SQL of its own.
    assert indexer.parents == ["Employer requirements"] * ROWS


async def test_an_unfiltered_walk_sees_the_same_rows_as_a_project_scoped_one(
    pg_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ``?project_id=`` branch adds a JOIN and a WHERE to the statement the
    # pages are cut from. With one project in the database the two must agree,
    # which is what says the join did not multiply or drop rows under LIMIT.
    from app.modules.requirements.router import _requirements_statement

    project_id, ids = await _seed(pg_session)
    monkeypatch.setattr(vector_routes, "_REINDEX_PAGE_ROWS", PAGE, raising=False)
    handler = _handler(statement_factory=_requirements_statement)

    scoped = _Indexer(pg_session)
    monkeypatch.setattr(vector_routes, "reindex_collection", scoped)
    await handler(pg_session, None, project_id, False)

    unscoped = _Indexer(pg_session)
    monkeypatch.setattr(vector_routes, "reindex_collection", unscoped)
    await handler(pg_session, None, None, False)

    assert scoped.ids == ids
    assert unscoped.ids == ids


class _PositionIndexer:
    """As ``_Indexer``, for the BOQ endpoint's rows and their eager parent."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self.ids: list[str] = []
        self.parents: list[str] = []
        self.page_sizes: list[int] = []
        self.peak_held = 0

    async def __call__(self, adapter: Any, rows: list[Any], **_: Any) -> dict[str, Any]:
        from app.modules.boq.models import Position

        self.page_sizes.append(len(rows))
        for row in rows:
            self.ids.append(str(row.id))
            # ``Position.boq`` is ``raise_on_sql``: reading it here is a read
            # rather than a lazy load only because the page was fetched with
            # the parent eager-loaded. A page that lost the option raises.
            self.parents.append(str(row.boq.project_id))
        held = sum(1 for obj in self._session.identity_map.values() if isinstance(obj, Position))
        self.peak_held = max(self.peak_held, held)
        return {"indexed": len(rows), "skipped": 0, "purged": False, "collection": adapter.collection_name}


async def test_the_boq_positions_walk_is_total_and_keeps_its_eager_parent(
    pg_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.boq.models import BOQ, Position
    from app.modules.boq.router import boq_vector_reindex

    owner = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="x",
        full_name="Quantity Surveyor",
    )
    pg_session.add(owner)
    await pg_session.flush()
    project = Project(name="Vector reindex positions", owner_id=owner.id)
    pg_session.add(project)
    await pg_session.flush()
    boq = BOQ(project_id=project.id, name="Structural works")
    pg_session.add(boq)
    await pg_session.flush()
    for index in range(ROWS):
        pg_session.add(
            Position(
                boq_id=boq.id,
                ordinal=f"01.{index:03d}",
                description=f"Reinforced concrete wall {index}",
                unit="m3",
            )
        )
    await pg_session.flush()
    ids = [str(v) for v in (await pg_session.execute(select(Position.id).order_by(Position.id))).scalars()]
    pg_session.expunge_all()

    indexer = _PositionIndexer(pg_session)
    monkeypatch.setattr(vector_routes, "reindex_collection", indexer)
    monkeypatch.setattr(vector_routes, "_REINDEX_PAGE_ROWS", PAGE, raising=False)

    # Tenant-wide, so the ownership gate takes its administrator branch and the
    # walk sees every position in the database.
    result = await boq_vector_reindex(pg_session, owner.id, {"role": "admin"}, None, None, False)

    assert indexer.ids == ids
    assert len(set(indexer.ids)) == ROWS
    assert result["scanned"] == ROWS
    assert result["truncated"] is False
    assert max(indexer.page_sizes) <= PAGE
    assert indexer.peak_held <= PAGE, (
        f"the session was holding {indexer.peak_held} positions at once under a page bound of {PAGE}"
    )
    assert indexer.parents == [str(project.id)] * ROWS
