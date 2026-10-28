# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Timeline read queries: scope, filters and paging stability."""

from __future__ import annotations

import uuid

import pytest

from app.modules.timeline.service import (
    count_entity_timeline,
    count_project_timeline,
    get_entity_timeline,
    get_project_timeline,
)
from tests.modules.timeline.conftest import make_entry, make_project, make_user, minutes_ago, now

pytestmark = pytest.mark.asyncio


async def _project(session):
    user = await make_user(session)
    return await make_project(session, user.id)


# ── scope ────────────────────────────────────────────────────────────────────


async def test_rows_roll_up_to_their_parent_project(session) -> None:
    project = await _project(session)
    await make_entry(session, project_id=project.id, action="ncr.created")

    rows = await get_project_timeline(session, project_id=project.id)

    assert [r.action for r in rows] == ["ncr.created"]


async def test_rows_logged_against_the_project_itself_are_included(session) -> None:
    """A project-level row carries the project as its *entity*, not its parent."""
    project = await _project(session)
    await make_entry(
        session,
        project_id=None,
        entity_type="project",
        entity_id=str(project.id),
        action="project.status_changed",
        module="projects",
    )

    rows = await get_project_timeline(session, project_id=project.id)

    assert [r.action for r in rows] == ["project.status_changed"]


@pytest.mark.tenant_isolation
async def test_another_projects_rows_are_not_returned(session) -> None:
    mine = await _project(session)
    theirs = await _project(session)
    await make_entry(session, project_id=mine.id, action="ncr.created")
    await make_entry(session, project_id=theirs.id, action="safety.incident.created")

    rows = await get_project_timeline(session, project_id=mine.id)

    assert [r.action for r in rows] == ["ncr.created"]


# ── paging stability ─────────────────────────────────────────────────────────


async def test_the_feed_is_ordered_by_a_total_key() -> None:
    """``ORDER BY`` must include the primary key, not ``created_at`` alone.

    This is asserted structurally, on the compiled statement, and that is a
    deliberate choice rather than a shortcut. ``created_at`` is filled from a
    Python-side default, so a burst of bridge writes lands several rows on one
    timestamp; ordering by it alone leaves tied rows in whatever order the plan
    happens to emit, and ``OFFSET``/``LIMIT`` over a non-total order may drop
    some rows and repeat others between pages.

    The behaviour cannot be provoked on demand: with a few tied rows PostgreSQL
    sorts deterministically, and this suite was checked with the tiebreaker
    removed - every behavioural paging assertion still passed. A test that only
    fails when the planner changes its mind is a flaky test that proves nothing
    on the runs where it passes, so the guarantee is gated where it is actually
    decided.
    """
    from sqlalchemy import select

    from app.core.audit_log import ActivityLog
    from app.modules.timeline.repository import _ordered

    compiled = str(_ordered(select(ActivityLog)).compile())
    order_by = compiled.split("ORDER BY", 1)[1]

    assert "created_at DESC" in order_by
    assert "oe_activity_log.id" in order_by, (
        "the feed orders by created_at alone, which is not a total order over rows "
        f"that share a timestamp; ORDER BY was:{order_by}"
    )


async def test_paging_covers_every_tied_row_exactly_once(session) -> None:
    """Sanity check over rows that do share a timestamp.

    Passes with or without the tiebreaker on this data volume - see the
    structural test above for the real gate. It is kept because it would catch
    an off-by-one in the offset arithmetic, which no structural check sees.
    """
    project = await _project(session)
    tied = now()
    for i in range(7):
        await make_entry(session, project_id=project.id, action=f"ncr.step_{i}", created_at=tied)

    seen: list[uuid.UUID] = []
    for offset in range(0, 7, 2):
        page = await get_project_timeline(session, project_id=project.id, limit=2, offset=offset)
        seen.extend(r.id for r in page)

    assert len(seen) == 7
    assert len(set(seen)) == 7, "paging repeated a row"


async def test_newest_first(session) -> None:
    project = await _project(session)
    await make_entry(session, project_id=project.id, action="old", created_at=minutes_ago(10))
    await make_entry(session, project_id=project.id, action="new", created_at=minutes_ago(1))

    rows = await get_project_timeline(session, project_id=project.id)

    assert [r.action for r in rows] == ["new", "old"]


# ── filters ──────────────────────────────────────────────────────────────────


async def test_module_and_action_filters(session) -> None:
    project = await _project(session)
    await make_entry(session, project_id=project.id, action="ncr.created", module="ncr")
    await make_entry(session, project_id=project.id, action="safety.incident.created", module="safety")

    by_module = await get_project_timeline(session, project_id=project.id, modules=["safety"])
    by_action = await get_project_timeline(session, project_id=project.id, actions=["ncr.created"])

    assert [r.module for r in by_module] == ["safety"]
    assert [r.action for r in by_action] == ["ncr.created"]


async def test_actor_filter(session) -> None:
    project = await _project(session)
    actor = uuid.uuid4()
    await make_entry(session, project_id=project.id, action="ncr.created", actor_id=actor)
    await make_entry(session, project_id=project.id, action="ncr.closed", actor_id=uuid.uuid4())

    rows = await get_project_timeline(session, project_id=project.id, actor_id=actor)

    assert [r.action for r in rows] == ["ncr.created"]


async def test_since_and_until_bound_the_window(session) -> None:
    project = await _project(session)
    await make_entry(session, project_id=project.id, action="before", created_at=minutes_ago(30))
    await make_entry(session, project_id=project.id, action="inside", created_at=minutes_ago(10))
    await make_entry(session, project_id=project.id, action="after", created_at=minutes_ago(1))

    rows = await get_project_timeline(
        session,
        project_id=project.id,
        since=minutes_ago(20),
        until=minutes_ago(5),
    )

    assert [r.action for r in rows] == ["inside"]


async def test_count_matches_the_filtered_feed(session) -> None:
    project = await _project(session)
    for _ in range(3):
        await make_entry(session, project_id=project.id, action="ncr.created", module="ncr")
    await make_entry(session, project_id=project.id, action="x", module="safety")

    total = await count_project_timeline(session, project_id=project.id, modules=["ncr"])
    rows = await get_project_timeline(session, project_id=project.id, modules=["ncr"], limit=2)

    assert total == 3
    assert len(rows) == 2, "the page is capped by limit while total counts the whole set"


# ── entity history ───────────────────────────────────────────────────────────


async def test_entity_history_returns_only_that_record(session) -> None:
    project = await _project(session)
    ncr = str(uuid.uuid4())
    await make_entry(session, project_id=project.id, entity_type="ncr", entity_id=ncr, action="ncr.created")
    await make_entry(session, project_id=project.id, entity_type="ncr", entity_id=ncr, action="ncr.closed")
    await make_entry(
        session,
        project_id=project.id,
        entity_type="ncr",
        entity_id=str(uuid.uuid4()),
        action="ncr.created",
    )

    rows = await get_entity_timeline(session, entity_type="ncr", entity_id=ncr, project_id=project.id)

    assert sorted(r.action for r in rows) == ["ncr.closed", "ncr.created"]
    assert await count_entity_timeline(session, entity_type="ncr", entity_id=ncr, project_id=project.id) == 2


@pytest.mark.tenant_isolation
async def test_entity_history_does_not_cross_projects(session) -> None:
    """``entity_id`` is a free string, not a foreign key, so ids are unique only
    by convention. Without the project clause a caller authorised for one
    project could read another project's history by presenting its id.
    """
    mine = await _project(session)
    theirs = await _project(session)
    shared_id = str(uuid.uuid4())
    await make_entry(session, project_id=mine.id, entity_type="ncr", entity_id=shared_id, action="mine")
    await make_entry(session, project_id=theirs.id, entity_type="ncr", entity_id=shared_id, action="theirs")

    rows = await get_entity_timeline(session, entity_type="ncr", entity_id=shared_id, project_id=mine.id)

    assert [r.action for r in rows] == ["mine"]
    assert await count_entity_timeline(session, entity_type="ncr", entity_id=shared_id, project_id=mine.id) == 1
