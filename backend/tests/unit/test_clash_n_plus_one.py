# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""N+1 query audit for the clash list endpoint.

Verifies that listing many clash results uses a bounded, fixed number of
queries (not one query per result row). Specifically:

* ``GET /clash/projects/{pid}/runs/{rid}/results`` with N results must
  issue at most 2 SQL statements per page request:
    1. COUNT(*) for total
    2. SELECT … LIMIT/OFFSET for the page

  The repository never issues a per-result SELECT or a lazy-load
  relationship traversal — all data is on the ClashResult row itself
  (names, disciplines, model_ids, comments … are all plain columns or
  JSON — no ORM relationship expansion needed for the list serialiser).

Strategy
--------
We instrument SQLAlchemy's ``before_cursor_execute`` event on the engine
to count actual SQL statements issued during the service call. The guard
threshold is set to 5 (accounting for the IDOR project-access queries and
the two result queries) — anything above that flags an N+1 regression.

This test does NOT use the HTTP layer — it calls the service directly so
we get a clean SQL count without auth overhead queries.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-clash-n1-"))
_TMP_DB = _TMP_DIR / "clash_n1.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from collections.abc import AsyncIterator  # noqa: E402

import pytest_asyncio  # noqa: E402

# ── Fixture ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def db_engine():
    from app.config import get_settings

    get_settings.cache_clear()
    # Import all models so Base.metadata is fully populated before create_all.
    import app.modules.clash.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine


@pytest_asyncio.fixture
async def session(db_engine) -> AsyncIterator:
    from app.database import async_session_factory

    async with async_session_factory() as s:
        yield s


# ── Seeding helpers ────────────────────────────────────────────────────────


async def _seed_run_with_results(session, n_results: int) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a project, a completed run, and N clash results.

    Returns (project_id, run_id).
    """
    from app.modules.clash.models import ClashResult, ClashRun
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"n1-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="N+1 Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="N+1 Audit Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    run = ClashRun(
        project_id=project.id,
        name="N+1 Audit Run",
        model_ids=[],
        status="completed",
        created_by=str(user.id),
        summary={},
    )
    session.add(run)
    await session.flush()

    results = [
        ClashResult(
            run_id=run.id,
            a_element_id=uuid.uuid4(),
            b_element_id=uuid.uuid4(),
            a_stable_id=f"a-{i}",
            b_stable_id=f"b-{i}",
            a_name=f"Wall {i}",
            b_name=f"Pipe {i}",
            a_discipline="Structural",
            b_discipline="Mechanical",
            a_model_id=uuid.uuid4(),
            b_model_id=uuid.uuid4(),
            clash_type="hard",
            penetration_m=float(i) * 0.01,
            distance_m=0.0,
            cx=float(i),
            cy=0.0,
            cz=0.0,
            status="new",
            severity="medium",
        )
        for i in range(n_results)
    ]
    session.add_all(results)
    await session.commit()
    return project.id, run.id


# ── SQL statement counter ──────────────────────────────────────────────────


class _QueryCounter:
    """Counts SQL statements issued on a SQLAlchemy async engine.

    Uses the synchronous ``before_cursor_execute`` event (which still
    fires on the underlying sync dialect layer, even in async mode).
    """

    def __init__(self) -> None:
        self.count = 0

    def _handler(self, conn, cursor, statement, parameters, context, executemany) -> None:
        # Skip PRAGMA and SAVEPOINT admin queries used by SQLite.
        stmt_upper = statement.strip().upper()
        if stmt_upper.startswith(("PRAGMA", "SAVEPOINT", "RELEASE")):
            return
        self.count += 1


# ── Tests ──────────────────────────────────────────────────────────────────


async def test_list_results_query_count_is_bounded(session):
    """Listing 50 clash results issues at most 5 SQL statements (not 50+).

    This is the core N+1 guard. The repository issues:
      - 1 COUNT query
      - 1 SELECT … LIMIT/OFFSET query
    plus at most 3 overhead queries (project lookup, run check, etc.).
    """
    from sqlalchemy import event

    from app.modules.clash.repository import ClashRepository

    _project_id, run_id = await _seed_run_with_results(session, n_results=50)

    # Attach the counter to the raw sync engine.
    from app.database import engine

    counter = _QueryCounter()
    sync_engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", counter._handler)
    try:
        repo = ClashRepository(session)
        rows, total = await repo.list_results(
            run_id,
            offset=0,
            limit=100,
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", counter._handler)

    assert total == 50, f"Expected 50 results, got {total}"
    assert len(rows) == 50, f"Expected 50 rows, got {len(rows)}"

    # The repository MUST NOT issue more than 5 queries (COUNT + SELECT +
    # at most 3 overhead). If this assertion fails an N+1 has been
    # introduced somewhere between the repo and the test.
    assert counter.count <= 5, (
        f"N+1 regression: expected ≤5 SQL statements for 50 results, "
        f"got {counter.count}. Check for lazy-load relationships or "
        "per-row SELECT in ClashRepository.list_results."
    )


async def test_list_results_query_count_stable_across_page_sizes(session):
    """Query count does NOT grow with limit — verifies no per-row fetches."""
    from sqlalchemy import event

    from app.database import engine
    from app.modules.clash.repository import ClashRepository

    _project_id, run_id = await _seed_run_with_results(session, n_results=20)
    sync_engine = engine.sync_engine

    for limit in (5, 10, 20):
        counter = _QueryCounter()
        event.listen(sync_engine, "before_cursor_execute", counter._handler)
        try:
            repo = ClashRepository(session)
            rows, _ = await repo.list_results(run_id, offset=0, limit=limit)
        finally:
            event.remove(sync_engine, "before_cursor_execute", counter._handler)

        assert len(rows) == limit, f"Expected {limit} rows"
        assert counter.count <= 5, f"Query count {counter.count} > 5 for limit={limit} — possible N+1"


async def test_all_results_single_query(session):
    """ClashRepository.all_results issues exactly 1 SQL SELECT."""
    from sqlalchemy import event

    from app.database import engine
    from app.modules.clash.repository import ClashRepository

    _project_id, run_id = await _seed_run_with_results(session, n_results=30)
    sync_engine = engine.sync_engine

    counter = _QueryCounter()
    event.listen(sync_engine, "before_cursor_execute", counter._handler)
    try:
        repo = ClashRepository(session)
        rows = await repo.all_results(run_id)
    finally:
        event.remove(sync_engine, "before_cursor_execute", counter._handler)

    assert len(rows) == 30, f"Expected 30 rows, got {len(rows)}"
    # all_results is a simple SELECT with no sub-queries or per-row fetches.
    assert counter.count == 1, f"all_results should issue exactly 1 SQL, got {counter.count}"


async def test_list_runs_single_query(session):
    """ClashRepository.list_runs issues exactly 1 SQL SELECT."""
    from sqlalchemy import event

    from app.database import engine
    from app.modules.clash.models import ClashRun
    from app.modules.clash.repository import ClashRepository
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"runs-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Runs Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Runs Project", owner_id=user.id)
    session.add(project)
    await session.flush()

    # Seed 10 runs.
    for i in range(10):
        run = ClashRun(
            project_id=project.id,
            name=f"Run {i}",
            model_ids=[],
            status="completed",
            created_by=str(user.id),
            summary={},
        )
        session.add(run)
    await session.commit()

    sync_engine = engine.sync_engine
    counter = _QueryCounter()
    event.listen(sync_engine, "before_cursor_execute", counter._handler)
    try:
        repo = ClashRepository(session)
        runs = await repo.list_runs(project.id)
    finally:
        event.remove(sync_engine, "before_cursor_execute", counter._handler)

    assert len(runs) == 10
    assert counter.count == 1, f"list_runs should issue exactly 1 SQL, got {counter.count}"
