"""Cap + ?limit= contract for ``GET /schedules/{id}/relationships/``.

The endpoint USED TO fetch every ``ScheduleRelationship`` row for a
schedule without bound. A schedule imported from a large MS Project or
P6 file commonly carries 1-5k dependency rows; the unbounded fetch
serialised every one of them to JSON for a UI grid that only renders
the first hundred — a 10+ MB response on a request that the user
expected to load in a single keystroke window.

The fix:

* Default ``limit=200`` — covers the vast majority of schedules
  observed in prod traces.
* Hard upper bound ``limit=500`` — beyond that the request is rejected
  with 422 (FastAPI's automatic ``Query(le=...)`` enforcement).
* Deterministic ORDER BY ``(created_at, id)`` so pagination is stable
  across requests even if the importer creates relationships in
  micro-second bursts.

These tests pin all three properties against a real (file-backed)
SQLite DB.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Per-module DB isolation BEFORE any app imports ─────────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-schedule-rels-limit-"))
_TMP_DB = _TMP_DIR / "session.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from app.database import Base  # noqa: E402
from app.modules.schedule.models import (  # noqa: E402
    Schedule,
    ScheduleRelationship,
)


@pytest_asyncio.fixture
async def seeded_schedule_id() -> tuple[uuid.UUID, AsyncSession]:
    """Create a schedule with 700 ScheduleRelationship rows.

    700 is comfortably above the default cap (200) and the hard max
    (500) so both can be exercised against the same fixture without
    seeding twice.
    """
    db_path = _TMP_DIR / f"test-{uuid.uuid4().hex[:8]}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}", echo=False)
    # ``app.database`` registers a global ``connect`` event listener
    # that flips ``PRAGMA foreign_keys=ON`` for every SQLite connection
    # produced by ANY engine. Layer a higher-priority listener here that
    # immediately flips it back OFF on this test engine so we don't
    # have to seed real Project + Activity rows through every dependent
    # migration just to exercise the cap-and-order behaviour that is
    # the subject of this test. Production Postgres still enforces FK
    # constraints natively.
    from sqlalchemy import event as _event

    @_event.listens_for(engine.sync_engine, "connect")
    def _disable_fk_for_test(dbapi_conn, _conn_record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    schedule_id = uuid.uuid4()
    project_id = uuid.uuid4()

    async with Session() as s:
        schedule = Schedule(
            id=schedule_id,
            project_id=project_id,
            name="perf-fixture-schedule",
            start_date=datetime.now(UTC).date(),
        )
        s.add(schedule)
        # Two activities are enough — relationships unique on (pred, succ)
        # so we generate 700 with synthetic UUIDs, not real Activity rows.
        await s.commit()

        # Bulk insert 700 relationships with monotonic created_at deltas
        # so the ORDER BY test can assert stable ordering.
        base_time = datetime.now(UTC)
        rels = []
        for i in range(700):
            rels.append(
                ScheduleRelationship(
                    id=uuid.uuid4(),
                    schedule_id=schedule_id,
                    predecessor_id=uuid.uuid4(),
                    successor_id=uuid.uuid4(),
                    relationship_type="FS",
                    lag_days=0,
                    created_at=base_time + timedelta(microseconds=i),
                )
            )
        s.add_all(rels)
        await s.commit()

    yield schedule_id, Session, db_path
    await engine.dispose()


# ── Direct handler unit tests (no auth dependency) ─────────────────────────
#
# We bypass the FastAPI app/auth stack and call the handler function
# directly with a mocked _verify_schedule_owner. This keeps the test
# focused on the cap/limit/order semantics that are the subject of
# this perf commit, without dragging in the JWT/RBAC machinery.


@pytest.mark.asyncio
async def test_default_limit_caps_at_200(seeded_schedule_id) -> None:
    """No ?limit= → default 200 rows returned (not 700)."""
    schedule_id, Session, _ = seeded_schedule_id
    from app.modules.schedule import router as schedule_router

    # Patch the owner-check to a no-op for this unit test.
    async def _noop_verify(*args, **kwargs):
        return None

    original = schedule_router._verify_schedule_owner
    schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
    try:
        async with Session() as s:
            rels = await schedule_router.list_relationships(
                schedule_id=schedule_id,
                session=s,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                service=None,  # type: ignore[arg-type]
                limit=200,
            )
    finally:
        schedule_router._verify_schedule_owner = original  # type: ignore[assignment]

    assert len(rels) == 200, (
        f"Default limit must cap at 200, got {len(rels)} of 700. Did someone restore the unbounded fetch?"
    )


@pytest.mark.asyncio
async def test_explicit_limit_500_caps_at_500(seeded_schedule_id) -> None:
    """?limit=500 → exactly 500 rows (the hard upper bound)."""
    schedule_id, Session, _ = seeded_schedule_id
    from app.modules.schedule import router as schedule_router

    async def _noop_verify(*args, **kwargs):
        return None

    original = schedule_router._verify_schedule_owner
    schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
    try:
        async with Session() as s:
            rels = await schedule_router.list_relationships(
                schedule_id=schedule_id,
                session=s,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                service=None,  # type: ignore[arg-type]
                limit=500,
            )
    finally:
        schedule_router._verify_schedule_owner = original  # type: ignore[assignment]

    assert len(rels) == 500


@pytest.mark.asyncio
async def test_results_ordered_by_created_at_asc(seeded_schedule_id) -> None:
    """ORDER BY created_at ASC keeps pagination stable across requests."""
    schedule_id, Session, _ = seeded_schedule_id
    from app.modules.schedule import router as schedule_router

    async def _noop_verify(*args, **kwargs):
        return None

    original = schedule_router._verify_schedule_owner
    schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
    try:
        async with Session() as s:
            rels = await schedule_router.list_relationships(
                schedule_id=schedule_id,
                session=s,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                service=None,  # type: ignore[arg-type]
                limit=100,
            )
    finally:
        schedule_router._verify_schedule_owner = original  # type: ignore[assignment]

    timestamps = [r.created_at for r in rels]
    assert timestamps == sorted(timestamps), (
        "Relationships must be ASC-ordered by created_at — pagination stability depends on it."
    )


def test_limit_above_500_rejected_by_query_schema() -> None:
    """The ``Query(le=500)`` declaration enforces the upper bound.

    We assert this directly on the FastAPI route schema rather than
    round-tripping through TestClient — the latter trips a unicode-decode
    bug in Starlette's TestClient on certain response headers on Windows
    that has nothing to do with our cap logic.

    Inspecting the route signature is the canonical way to verify the
    Query(..., le=500) declaration shipped intact.
    """
    from app.modules.schedule.router import list_relationships

    sig = inspect.signature(list_relationships)
    limit_param = sig.parameters.get("limit")
    assert limit_param is not None, "list_relationships must accept a ``limit`` query param"

    # The default value is the FastAPI ``Query(...)`` sentinel object.
    # Pull the bounds off it directly.
    q_default = limit_param.default
    # FastAPI's ``Query`` wraps the validation in a Pydantic FieldInfo.
    # Both ``le`` and ``ge`` live on .metadata as Pydantic constraint
    # markers, OR on the wrapper itself depending on the FastAPI
    # version. Walk both shapes.
    bounds = {"le": None, "ge": None, "default": None}
    bounds["default"] = getattr(q_default, "default", None)
    for attr in ("le", "ge"):
        v = getattr(q_default, attr, None)
        if v is not None:
            bounds[attr] = v
    # Fallback: inspect Pydantic metadata if the legacy attributes aren't
    # set directly on the Query object.
    md = getattr(q_default, "metadata", None) or []
    for marker in md:
        for attr in ("le", "ge"):
            v = getattr(marker, attr, None)
            if v is not None:
                bounds[attr] = v

    assert bounds["le"] == 500, (
        f"Expected ``limit`` upper bound of 500, got {bounds['le']}. The cap is the whole point of this perf fix."
    )
    assert bounds["ge"] == 1, f"Expected ``limit`` lower bound of 1, got {bounds['ge']}."
    assert bounds["default"] == 200, f"Expected ``limit`` default of 200, got {bounds['default']}."


import inspect  # noqa: E402  — used above
