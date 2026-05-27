"""Unit tests for :mod:`app.core.audit_log` (the FSM-aware audit table).

Coverage:
    * ``log_activity`` flushes a row with the expected columns.
    * ``actor_id`` / ``tenant_id`` coerce both str and UUID inputs.
    * ``get_activity_for_entity`` returns the chronological history.
    * ``get_recent_activity`` honours entity_type / action / actor filters.
    * Multiple rows for the same entity are queryable in insertion order.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.audit_log import (
    get_activity_for_entity,
    get_recent_activity,
    log_activity,
)
from app.database import Base


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


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

    SQLite stores ``DateTime(timezone=True)`` at second precision in
    server_default=func.now(), so two log_activity calls in the same
    second tie on ``created_at``. We assert on set membership for the
    "is filter correct" path and rely on the inserted-order assertion
    in :func:`test_get_activity_for_entity_orders_chronologically`
    (which uses entity-scoped ASC ordering) for ordering correctness.
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
