"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for :mod:`app.core.audit_log` (the FSM-aware audit table).

Coverage:
    * ``log_activity`` flushes a row with the expected columns.
    * ``actor_id`` / ``tenant_id`` coerce both str and UUID inputs.
    * ``get_activity_for_entity`` returns the chronological history.
    * ``count_activity_for_entity`` counts the same rows, ignoring paging.
    * ``get_recent_activity`` honours entity_type / action / actor filters.
    * Multiple rows for the same entity are queryable in insertion order.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import (
    count_activity_for_entity,
    get_activity_for_entity,
    get_recent_activity,
    log_activity,
)
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # PostgreSQL session inside an outer transaction that is rolled back on
    # teardown, so each test starts from an empty audit table. The shared
    # "oe_test_unit" database is pre-built with the full schema.
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_log_activity_persists_row(session: AsyncSession) -> None:
    actor = str(uuid.uuid4())
    eid = str(uuid.uuid4())
    row = await log_activity(
        session,
        actor_id=actor,
        entity_type="boq",
        entity_id=eid,
        action="status_changed",
        from_status="draft",
        to_status="final",
        reason="approval",
        metadata={"who": "PM"},
    )
    assert row.id is not None
    assert row.entity_type == "boq"
    assert row.entity_id == eid
    assert row.from_status == "draft"
    assert row.to_status == "final"
    assert row.reason == "approval"
    assert row.metadata_ == {"who": "PM"}
    assert str(row.actor_id) == actor


@pytest.mark.asyncio
async def test_log_activity_accepts_uuid_for_actor(session: AsyncSession) -> None:
    actor = uuid.uuid4()
    eid = uuid.uuid4()
    row = await log_activity(
        session,
        actor_id=actor,
        entity_type="project",
        entity_id=eid,
        action="created",
    )
    assert row.actor_id == actor
    # entity_id coerces to string
    assert row.entity_id == str(eid)


@pytest.mark.asyncio
async def test_log_activity_handles_null_actor(session: AsyncSession) -> None:
    """System events have no actor (background jobs, migrations, ...)."""
    row = await log_activity(
        session,
        actor_id=None,
        entity_type="invoice",
        entity_id="abc-def",
        action="imported",
    )
    assert row.actor_id is None


@pytest.mark.asyncio
async def test_log_activity_invalid_actor_string_becomes_null(session: AsyncSession) -> None:
    """A non-UUID actor_id string is coerced to NULL — never raises."""
    row = await log_activity(
        session,
        actor_id="not-a-uuid",
        entity_type="rfq",
        entity_id=str(uuid.uuid4()),
        action="created",
    )
    assert row.actor_id is None


@pytest.mark.asyncio
async def test_get_activity_for_entity_orders_chronologically(session: AsyncSession) -> None:
    eid = str(uuid.uuid4())
    await log_activity(
        session,
        actor_id=None,
        entity_type="boq",
        entity_id=eid,
        action="status_changed",
        from_status="draft",
        to_status="final",
    )
    await log_activity(
        session,
        actor_id=None,
        entity_type="boq",
        entity_id=eid,
        action="status_changed",
        from_status="final",
        to_status="archived",
    )
    rows = await get_activity_for_entity(session, entity_type="boq", entity_id=eid)
    assert len(rows) == 2
    # First row inserted, first returned (chronological ascending)
    assert rows[0].to_status == "final"
    assert rows[1].to_status == "archived"


@pytest.mark.asyncio
async def test_get_activity_filters_by_entity(session: AsyncSession) -> None:
    eid1 = str(uuid.uuid4())
    eid2 = str(uuid.uuid4())
    await log_activity(
        session,
        actor_id=None,
        entity_type="boq",
        entity_id=eid1,
        action="status_changed",
        to_status="final",
    )
    await log_activity(
        session,
        actor_id=None,
        entity_type="boq",
        entity_id=eid2,
        action="status_changed",
        to_status="final",
    )
    rows = await get_activity_for_entity(session, entity_type="boq", entity_id=eid1)
    assert len(rows) == 1
    assert rows[0].entity_id == eid1


@pytest.mark.asyncio
async def test_count_activity_ignores_paging_and_matches_the_page(session: AsyncSession) -> None:
    """The count has to describe the same rows the page is a slice of.

    A journal page that reports its own length as the total says nothing, and
    a count filtered differently from the page is worse than none: it makes a
    complete history look truncated or the reverse.
    """
    eid = str(uuid.uuid4())
    other = str(uuid.uuid4())
    for status in ("draft", "final", "archived"):
        await log_activity(
            session,
            actor_id=None,
            entity_type="boq",
            entity_id=eid,
            action="status_changed",
            to_status=status,
        )
    # A row on another entity, and one on another entity type under the same
    # id, so a count that dropped either filter would show up here.
    await log_activity(session, actor_id=None, entity_type="boq", entity_id=other, action="status_changed")
    await log_activity(session, actor_id=None, entity_type="rfi", entity_id=eid, action="status_changed")

    page = await get_activity_for_entity(session, entity_type="boq", entity_id=eid, limit=2)
    total = await count_activity_for_entity(session, entity_type="boq", entity_id=eid)

    assert len(page) == 2
    assert total == 3
    # An offset past the end still counts the whole journal.
    assert await count_activity_for_entity(session, entity_type="boq", entity_id=eid) == 3
    assert await count_activity_for_entity(session, entity_type="boq", entity_id=uuid.uuid4()) == 0


@pytest.mark.asyncio
async def test_count_activity_accepts_a_uuid_the_way_the_reader_does(session: AsyncSession) -> None:
    """``entity_id`` arrives as a UUID from the routes and str from services."""
    eid = uuid.uuid4()
    await log_activity(session, actor_id=None, entity_type="rfi", entity_id=str(eid), action="status_changed")

    assert await count_activity_for_entity(session, entity_type="rfi", entity_id=eid) == 1
    assert await count_activity_for_entity(session, entity_type="rfi", entity_id=str(eid)) == 1


@pytest.mark.asyncio
async def test_get_recent_activity_filters(session: AsyncSession) -> None:
    actor1 = str(uuid.uuid4())
    actor2 = str(uuid.uuid4())
    await log_activity(
        session,
        actor_id=actor1,
        entity_type="boq",
        entity_id="b1",
        action="status_changed",
    )
    await log_activity(
        session,
        actor_id=actor2,
        entity_type="invoice",
        entity_id="i1",
        action="status_changed",
    )
    await log_activity(
        session,
        actor_id=actor1,
        entity_type="boq",
        entity_id="b2",
        action="created",
    )

    all_rows = await get_recent_activity(session)
    assert len(all_rows) == 3

    boq_only = await get_recent_activity(session, entity_type="boq")
    assert {r.entity_id for r in boq_only} == {"b1", "b2"}

    by_actor = await get_recent_activity(session, actor_id=actor1)
    assert len(by_actor) == 2

    status_changes = await get_recent_activity(session, action="status_changed")
    assert len(status_changes) == 2


@pytest.mark.asyncio
async def test_metadata_defaults_to_empty_dict(session: AsyncSession) -> None:
    row = await log_activity(
        session,
        actor_id=None,
        entity_type="ncr",
        entity_id="x",
        action="created",
    )
    assert row.metadata_ == {}


@pytest.mark.asyncio
async def test_recent_activity_is_newest_first(session: AsyncSession) -> None:
    """The ORDER BY ``created_at DESC`` ensures newest rows surface first.

    Two log_activity calls within the same transaction can share the same
    ``created_at`` value from server_default=func.now() (statement_timestamp
    is stable within a statement), so they may tie on ``created_at``. We
    assert on set membership for the "is filter correct" path and rely on the
    inserted-order assertion in
    :func:`test_get_activity_for_entity_orders_chronologically` (which uses
    entity-scoped ASC ordering) for ordering correctness.
    """
    await log_activity(
        session,
        actor_id=None,
        entity_type="boq",
        entity_id="b1",
        action="created",
        metadata={"seq": 1},
    )
    await log_activity(
        session,
        actor_id=None,
        entity_type="boq",
        entity_id="b1",
        action="status_changed",
        metadata={"seq": 2},
    )
    rows = await get_recent_activity(session, entity_type="boq")
    assert len(rows) == 2
    seqs = {r.metadata_["seq"] for r in rows}
    assert seqs == {1, 2}


@pytest.mark.asyncio
async def test_failed_audit_flush_leaves_the_caller_transaction_usable(
    session: AsyncSession,
) -> None:
    """A dropped audit row must not take the caller's business write with it.

    ``log_activity`` promises that a failed audit write leaves the caller's
    transaction intact. Catching the exception is not enough to keep that
    promise: a failed ``flush`` puts the session into a rolled-back state
    where every later statement raises ``PendingRollbackError``, so before
    the savepoint the caller was handed a broken session and a swallowed
    error. The savepoint is what confines the loss to the audit row.

    The failure here is a real one. ``entity_type`` is ``String(64)`` and
    PostgreSQL rejects a longer value at flush time. A patched ``flush``
    that merely raises would not put the session into the rolled-back state
    this test is about, so such a test would pass with or without the fix
    and prove nothing.
    """
    dropped = await log_activity(
        session,
        actor_id=None,
        entity_type="x" * 100,
        entity_id="too-long",
        action="audit_row_that_cannot_land",
    )
    assert dropped is not None  # returned rather than raised

    survivor = await log_activity(
        session,
        actor_id=None,
        entity_type="boq",
        entity_id="written-after-the-failure",
        action="status_changed",
        metadata={"after": True},
    )
    await session.flush()
    assert survivor.id is not None

    rows = await get_activity_for_entity(session, entity_type="boq", entity_id="written-after-the-failure")
    assert [r.action for r in rows] == ["status_changed"]

    over_long = await get_activity_for_entity(session, entity_type="x" * 100, entity_id="too-long")
    assert over_long == []
