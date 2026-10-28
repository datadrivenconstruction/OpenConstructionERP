"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for ``ProjectRepository``.

Focus: the SQL-MAX aggregate that replaced the in-memory scan in
``max_project_code_seq``. Two contracts pinned here:

1. The aggregate returns the correct next-sequence value for the given
   prefix when many rows already exist (functional contract).
2. It issues *exactly one* ``session.execute`` call regardless of how
   many matching rows exist — i.e. the entire scan happens inside the
   database, not in Python (performance contract).

The performance assertion is what protects us from a future refactor
silently slipping back to the O(n) fetch-then-filter pattern.

All tests use a transaction-isolated PostgreSQL session (rolled back on
teardown) via ``tests._pg.transactional_session``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def owner_id(session: AsyncSession) -> uuid.UUID:
    """Insert a single owner User row and return its id."""
    from app.modules.users.models import User

    user = User(
        email=f"owner-{uuid.uuid4().hex}@test.local",
        hashed_password="x",
        full_name="Owner",
    )
    session.add(user)
    await session.flush()
    return user.id


async def _seed_projects(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    prefix: str,
    count: int,
    extra_codes: tuple[str, ...] = (),
) -> None:
    """Insert ``count`` projects with codes ``{prefix}{N:04d}`` plus
    any rows from ``extra_codes`` (used to inject noise like wrong-prefix
    rows or NULL codes).
    """
    from app.modules.projects.models import Project

    for i in range(1, count + 1):
        session.add(
            Project(
                name=f"P{i}",
                owner_id=owner_id,
                project_code=f"{prefix}{i:04d}",
            ),
        )
    for code in extra_codes:
        session.add(
            Project(
                name=f"N-{code or 'null'}",
                owner_id=owner_id,
                project_code=code or None,
            ),
        )
    # Also one with NULL code — must be filtered out by the WHERE clause.
    session.add(
        Project(
            name="no-code",
            owner_id=owner_id,
            project_code=None,
        ),
    )
    await session.flush()


@pytest.mark.asyncio
async def test_max_project_code_seq_returns_none_when_empty(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    from app.modules.projects.repository import ProjectRepository

    repo = ProjectRepository(session)
    assert await repo.max_project_code_seq(f"PRJ-{datetime.now(UTC).year}-") is None


@pytest.mark.asyncio
async def test_max_project_code_seq_finds_max_with_50_rows(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    from app.modules.projects.repository import ProjectRepository

    prefix = "PRJ-2026-"
    await _seed_projects(session, owner_id, prefix=prefix, count=50)

    repo = ProjectRepository(session)
    assert await repo.max_project_code_seq(prefix) == 50


@pytest.mark.asyncio
async def test_max_project_code_seq_ignores_other_prefix(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """Codes from other prefixes (e.g. last year) must not leak in."""
    from app.modules.projects.repository import ProjectRepository

    await _seed_projects(session, owner_id, prefix="PRJ-2025-", count=30)
    await _seed_projects(session, owner_id, prefix="PRJ-2026-", count=12)

    repo = ProjectRepository(session)
    assert await repo.max_project_code_seq("PRJ-2026-") == 12
    assert await repo.max_project_code_seq("PRJ-2025-") == 30


@pytest.mark.asyncio
async def test_max_project_code_seq_handles_60_plus_rows_single_query(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """Performance contract: the scan must hit the DB exactly once,
    regardless of how many matching rows exist.

    Counts SELECTs issued via SQLAlchemy's ``do_execute`` event so the
    assertion captures every round-trip the repo method emits — not just
    the rows it materialises in Python.
    """
    from app.modules.projects.repository import ProjectRepository

    prefix = "PRJ-2026-"
    # 60 matching rows + 5 wrong-prefix + 1 NULL via _seed_projects.
    await _seed_projects(
        session,
        owner_id,
        prefix=prefix,
        count=60,
        extra_codes=("OTHER-0001", "OTHER-0002", "ARCH-9999"),
    )

    repo = ProjectRepository(session)

    # Wire a SELECT counter onto the underlying sync engine. ``before_cursor_execute``
    # fires on every statement the driver sends, so it captures both the
    # function-call aggregate and any accidental N+1 follow-ups.
    select_count = 0
    bind = session.get_bind()
    # AsyncSession exposes the sync engine directly when the bind is
    # already sync (SQLAlchemy 2.x test-fixture path).
    sync_engine = getattr(bind, "sync_engine", bind)

    def _count_selects(  # noqa: PLR0913
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,  # type: ignore[no-untyped-def]
    ) -> None:
        nonlocal select_count
        normalised = statement.lstrip().upper()
        if normalised.startswith("SELECT"):
            select_count += 1

    event.listen(sync_engine, "before_cursor_execute", _count_selects)
    try:
        result = await repo.max_project_code_seq(prefix)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count_selects)

    assert result == 60
    # The aggregate must be a single SELECT. If a future refactor regresses
    # to a SELECT * + Python loop, this assertion catches it.
    assert select_count == 1, (
        f"Expected exactly 1 SELECT for max_project_code_seq with 60 rows, "
        f"got {select_count}. A future refactor likely reintroduced the "
        f"O(n) Python-side scan."
    )


@pytest.mark.asyncio
async def test_max_project_code_seq_picks_max_with_sparse_numbering(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """Gaps in the sequence must still resolve to the true max."""
    from app.modules.projects.models import Project
    from app.modules.projects.repository import ProjectRepository

    prefix = "PRJ-2026-"
    for n in (1, 2, 5, 47, 99):
        session.add(
            Project(
                name=f"P{n}",
                owner_id=owner_id,
                project_code=f"{prefix}{n:04d}",
            ),
        )
    await session.flush()

    repo = ProjectRepository(session)
    assert await repo.max_project_code_seq(prefix) == 99
