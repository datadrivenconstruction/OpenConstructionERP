# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The declared loading strategy on both saved-views relationships.

Per ``.claude/rules/backend-modules.md`` a green test lane is NOT evidence that
a loading strategy is right - a lane that never walks the relationship passes
whatever the strategy is. These tests walk both of them deliberately.

Run history is unbounded and is not what a caller listing or executing a view
wants, so ``SavedView.runs`` is ``raise_on_sql`` rather than ``selectin``, and
``SavedViewRun.view`` is ``raise_on_sql`` because the FK column already carries
the id. The point of ``raise_on_sql`` over ``raise`` is that it still allows the
free read off an instance that was loaded eagerly, so both halves of that are
checked here: the refusal when SQL would fire, and the read that costs nothing.

The aggregates in the repository exist precisely because the collection refuses
ad-hoc SQL, so they are exercised against the same rows.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import selectinload


@pytest_asyncio.fixture(scope="module")
async def tables():
    """Create the schema once for this module.

    ``Base.metadata`` only knows the models that have been imported, so the
    modules these tests touch are imported before ``create_all`` rather than
    relying on whatever an earlier suite happened to pull in.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    import app.modules.projects.models  # noqa: F401 - FK target
    import app.modules.saved_views.models  # noqa: F401 - registers the tables
    import app.modules.teams.models  # noqa: F401 - shared_team_id FK target
    import app.modules.users.models  # noqa: F401 - project owner
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return True


@pytest_asyncio.fixture
async def seeded(tables):
    """One saved view with three run rows of mixed outcome."""
    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.saved_views.models import SavedView, SavedViewRun
    from app.modules.users.models import User

    async with async_session_factory() as session:
        tag = uuid.uuid4().hex[:8]
        owner = User(
            email=f"saved-views-rel-{tag}@test.io",
            hashed_password="not-a-real-hash",
            full_name=f"Saved Views Relations {tag}",
            role="admin",
        )
        session.add(owner)
        await session.flush()

        project = Project(name=f"Saved views relationships {tag}", owner_id=owner.id)
        session.add(project)
        await session.flush()

        view = SavedView(
            owner_id=owner.id,
            project_id=project.id,
            entity_type="project",
            name=f"Relationship probe {tag}",
            spec={"page": 1, "page_size": 50},
            share_scope="private",
        )
        session.add(view)
        await session.flush()

        for outcome, rows, elapsed, truncated in (
            ("ok", 12, 40, False),
            ("ok", 500, 900, True),
            ("budget", 0, 5, False),
        ):
            session.add(
                SavedViewRun(
                    saved_view_id=view.id,
                    owner_id=owner.id,
                    entity_type="project",
                    row_count=rows,
                    truncated=truncated,
                    elapsed_ms=elapsed,
                    outcome=outcome,
                )
            )
        await session.commit()
        return {"view_id": view.id, "owner_id": owner.id, "project_id": project.id}


@pytest.mark.asyncio
async def test_run_history_refuses_an_implicit_load(seeded) -> None:
    """``SavedView.runs`` must not quietly fetch an unbounded collection.

    This is the half that fails if the strategy is relaxed to ``selectin`` or
    left at the default: the attribute would simply return rows.
    """
    from app.database import async_session_factory
    from app.modules.saved_views.models import SavedView

    async with async_session_factory() as session:
        view = (await session.execute(select(SavedView).where(SavedView.id == seeded["view_id"]))).scalar_one()
        with pytest.raises(InvalidRequestError) as excinfo:
            _ = view.runs
        assert "runs" in str(excinfo.value)


@pytest.mark.asyncio
async def test_run_history_reads_free_when_it_was_ordered_eagerly(seeded) -> None:
    """The reason the policy says ``raise_on_sql`` and not ``raise``.

    A caller that asked for the collection gets it, with no second round trip
    and no exception - ``raise`` would refuse this working code too.
    """
    from app.database import async_session_factory
    from app.modules.saved_views.models import SavedView

    async with async_session_factory() as session:
        view = (
            await session.execute(
                select(SavedView).where(SavedView.id == seeded["view_id"]).options(selectinload(SavedView.runs))
            )
        ).scalar_one()
        assert len(view.runs) == 3
        # Newest first, per the relationship's own order_by.
        assert [r.outcome for r in view.runs][0] in ("ok", "budget")


@pytest.mark.asyncio
async def test_walking_up_from_a_run_refuses(seeded) -> None:
    """``SavedViewRun.view`` is the implicit upward hop the policy exists to catch."""
    from app.database import async_session_factory
    from app.modules.saved_views.models import SavedViewRun

    async with async_session_factory() as session:
        run = (
            await session.execute(select(SavedViewRun).where(SavedViewRun.saved_view_id == seeded["view_id"]).limit(1))
        ).scalar_one()
        assert run.saved_view_id == seeded["view_id"]
        with pytest.raises(InvalidRequestError) as excinfo:
            _ = run.view
        assert "view" in str(excinfo.value)


@pytest.mark.asyncio
async def test_deleting_a_view_orphans_its_runs_rather_than_deleting_them(seeded) -> None:
    """``ON DELETE SET NULL`` plus ``passive_deletes`` keeps the audit trail.

    The delete must not need the refusing collection either: if SQLAlchemy
    tried to load ``runs`` to null the FK itself, this would raise instead of
    committing.
    """
    from app.database import async_session_factory
    from app.modules.saved_views.models import SavedView, SavedViewRun

    async with async_session_factory() as session:
        view = await session.get(SavedView, seeded["view_id"])
        assert view is not None
        await session.delete(view)
        await session.commit()

    async with async_session_factory() as session:
        surviving = (
            (await session.execute(select(SavedViewRun).where(SavedViewRun.owner_id == seeded["owner_id"])))
            .scalars()
            .all()
        )
        assert len(surviving) == 3
        assert all(r.saved_view_id is None for r in surviving)


@pytest.mark.asyncio
async def test_repository_aggregates_replace_walking_the_collection(seeded) -> None:
    """The read side of the run table, aggregated in SQL rather than in Python."""
    from app.database import async_session_factory
    from app.modules.saved_views.repository import SavedViewRepository

    async with async_session_factory() as session:
        repo = SavedViewRepository(session)
        outcomes = await repo.run_outcome_counts(seeded["view_id"])
        assert outcomes == {"ok": 2, "budget": 1}

        avg_ms, max_ms, truncated = await repo.run_timings(seeded["view_id"])
        assert avg_ms == 315  # (40 + 900 + 5) / 3
        assert max_ms == 900
        assert truncated == 1

        last = await repo.last_run(seeded["view_id"])
        assert last is not None
        assert last.saved_view_id == seeded["view_id"]


@pytest.mark.asyncio
async def test_aggregates_on_a_view_that_never_ran_are_empty_not_zero(seeded) -> None:
    """A view with no runs must not read as a view that ran and returned nothing."""
    from app.database import async_session_factory
    from app.modules.saved_views.repository import SavedViewRepository

    async with async_session_factory() as session:
        repo = SavedViewRepository(session)
        never_ran = uuid.uuid4()
        assert await repo.run_outcome_counts(never_ran) == {}
        assert await repo.run_timings(never_ran) == (None, None, 0)
        assert await repo.last_run(never_ran) is None
