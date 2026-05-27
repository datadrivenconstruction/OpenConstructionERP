"""Bulk-guard + N+1 contract for ``ProjectService._generate_project_code``.

The generator runs inside ``create_project`` and is invoked once per
new project. It opens with a stale-reservation prune that USED TO call
``ProjectRepository.project_code_exists`` once per entry in the
in-process ``_PROJECT_CODE_RESERVED`` set — pure N+1 against the DB.

Under normal load that's fine (the set rarely exceeds 1-2 entries
because each successful commit GCs its own slot). But two pathological
patterns surface the bug:

1. Long-running uvicorn workers under sustained ``create_project``
   pressure where the prune loop quietly grows the per-acquire DB cost.
2. Batch importers that spin up thousands of ``create_project``
   coroutines without yielding to let earlier commits GC — the set
   bloats unbounded, every acquire then issues N+1 SELECT queries
   AND the bloat itself keeps growing without backpressure.

The fix:

* Batch the prune into a single ``WHERE project_code IN (...)`` query
  (was N point queries).
* Hard cap the reservation set at 500; over-cap creates fail with 422
  instead of letting latency creep silently.

These tests pin:

* The cap fires at the threshold (422, not OOM).
* The prune issues a single SELECT regardless of set size (N+1 → 1).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Per-module DB isolation BEFORE any app imports ─────────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-projects-bulk-guard-"))
_TMP_DB = _TMP_DIR / "session.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

# Project carries FKs to oe_users_user / oe_teams_team etc; the tests
# only need the projects table for codegen but the FK referent must
# exist when SQLite parses the CREATE TABLE. Pulling Base.metadata
# entirely avoids the missing-referent class of error.
import app.modules.users.models  # noqa: E402,F401
from app.config import Settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.modules.projects import service as project_service_module  # noqa: E402
from app.modules.projects.models import Project  # noqa: E402
from app.modules.projects.service import ProjectService  # noqa: E402


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    db_path = _TMP_DIR / f"test-{uuid.uuid4().hex[:8]}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
def _clear_reservation_set():
    """Per-test isolation of the module-level reservation set.

    The set is process-global by design (cross-session race protection),
    so tests would otherwise bleed state into each other.
    """
    project_service_module._PROJECT_CODE_RESERVED.clear()
    yield
    project_service_module._PROJECT_CODE_RESERVED.clear()


# ── Cap test ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reservation_cap_fires_at_500(session: AsyncSession) -> None:
    """At >= 500 reservations, ``_generate_project_code`` raises 422.

    Pinned because the cap is the only thing standing between us and
    unbounded memory growth + O(N) acquire latency on the prune loop.
    """
    settings = Settings(_env_file=None)
    service = ProjectService(session, settings)

    # Pre-fill the reservation set right at the threshold.
    cap = project_service_module._PROJECT_CODE_RESERVED_HARD_CAP
    fake_reservations = {f"PRJ-2026-{i:04d}-fake" for i in range(cap)}
    project_service_module._PROJECT_CODE_RESERVED.update(fake_reservations)

    with pytest.raises(HTTPException) as exc:
        await service._generate_project_code()

    assert exc.value.status_code == 422
    detail = exc.value.detail.lower()
    assert "reservation set" in detail or "reservation" in detail
    assert str(cap) in exc.value.detail


@pytest.mark.asyncio
async def test_cap_value_is_500_for_visibility(session: AsyncSession) -> None:
    """The cap is exactly 500 — keep documented + asserted so future
    tunings show up in code review instead of as silent behaviour change."""
    assert project_service_module._PROJECT_CODE_RESERVED_HARD_CAP == 500


# ── N+1 → 1 test ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prune_loop_issues_single_query_not_n_plus_1(
    session: AsyncSession,
) -> None:
    """Stale-prune issues ONE SELECT regardless of reservation count.

    Pre-fix this was N point queries (one ``project_code_exists`` per
    reservation). With 50 reservations that's 50 DB round-trips per
    ``create_project`` acquire — pure N+1 and the very pattern the
    perf wave is killing project-wide.

    We count SELECT statements via ``before_cursor_execute`` and assert
    the prune phase is ≤ 1 query against ``oe_projects_project``.
    """
    settings = Settings(_env_file=None)
    service = ProjectService(session, settings)

    # Seed 50 in-flight reservations matching this year's prefix.
    from datetime import UTC, datetime

    year = datetime.now(UTC).year
    prefix = f"PRJ-{year}-"
    reservations = {f"{prefix}{i:04d}" for i in range(50)}
    project_service_module._PROJECT_CODE_RESERVED.update(reservations)

    select_count = {"oe_projects_project": 0}
    sync_engine = session.bind.sync_engine  # type: ignore[union-attr]

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _count_selects(conn, cursor, statement, parameters, context, executemany):
        normalised = statement.lower().lstrip()
        if normalised.startswith("select") and "oe_projects_project" in normalised:
            select_count["oe_projects_project"] += 1

    try:
        code = await service._generate_project_code()
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count_selects)

    # Generator does: 1 prune query (bulk IN) + 1 max_project_code_seq +
    # 1 final project_code_exists for the candidate = 3 SELECTs total.
    # Pre-fix path: 50 prune queries (1 per reservation) + 1 max_seq +
    # 1 final candidate check = 52 SELECTs. Anything over 5 means the
    # batched prune got reverted to N+1.
    assert select_count["oe_projects_project"] <= 5, (
        f"Generator must issue ≤ 5 SELECTs (was N+1 with 50 reservations, "
        f"now batched). Observed: {select_count['oe_projects_project']}. "
        f"Did someone re-introduce the per-reservation point query in "
        f"the prune loop?"
    )
    assert code.startswith(prefix)


@pytest.mark.asyncio
async def test_batched_prune_removes_committed_codes(
    session: AsyncSession,
) -> None:
    """Bulk prune semantically equivalent to the legacy per-row loop:
    reservations whose code is now in the DB get evicted, the rest stay."""
    from datetime import UTC, datetime

    year = datetime.now(UTC).year
    prefix = f"PRJ-{year}-"

    # Commit two real projects with codes that mirror reservations.
    # FK to oe_users_user requires a real user — seed one minimal row.
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"owner-{uuid.uuid4().hex[:6]}@test.local",
        hashed_password="x",
        is_active=True,
    )
    session.add(owner)
    await session.flush()

    committed_codes = [f"{prefix}{i:04d}" for i in (1, 2)]
    for code in committed_codes:
        session.add(
            Project(
                id=uuid.uuid4(),
                name=f"committed-{code}",
                description="",
                status="active",
                owner_id=owner.id,
                project_code=code,
                currency="EUR",
                region="DE_BERLIN",
                classification_standard="DIN276",
                locale="en",
                validation_rule_sets=[],
            )
        )
    await session.commit()

    # Seed reservations: 2 that are now committed + 3 that are still in-flight.
    in_flight = [f"{prefix}{i:04d}" for i in (3, 4, 5)]
    project_service_module._PROJECT_CODE_RESERVED.update(committed_codes + in_flight)

    settings = Settings(_env_file=None)
    service = ProjectService(session, settings)
    await service._generate_project_code()

    # Committed codes evicted; in-flight ones stay; the freshly minted
    # code (PRJ-...-0006 or similar — whichever the gen returned) is now
    # also in the set.
    for code in committed_codes:
        assert code not in project_service_module._PROJECT_CODE_RESERVED, (
            f"Committed code {code} should have been pruned out."
        )
    for code in in_flight:
        assert code in project_service_module._PROJECT_CODE_RESERVED, (
            f"In-flight reservation {code} must NOT be evicted by the prune."
        )
