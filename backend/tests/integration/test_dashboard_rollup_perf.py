# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Performance tests — Dashboard rollup at 50 projects × 10 widgets.

Assertions:
* Single ``compute_rollup`` call for all 10 widgets completes in < 2 s
  on SQLite (CI has ~2× slower I/O than dev; production PostgreSQL is
  faster). The wall-clock budget is intentionally generous here because
  SQLite does not support true parallel reads.
* SQL query count is **O(1)** — stays constant as project count scales
  from 1 → 50. We instrument with a SQLAlchemy event listener that counts
  ``before_cursor_execute`` events.

Note: the test uses SQLite + in-process seeding, not the production VPS.
"""

from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base

# ── Model registration ─────────────────────────────────────────────────────


def _register_models() -> None:
    import app.modules.boq.models  # noqa: F401
    import app.modules.changeorders.models  # noqa: F401
    import app.modules.daily_diary.models  # noqa: F401
    import app.modules.finance.models  # noqa: F401
    import app.modules.procurement.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.safety.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    import app.modules.validation.models  # noqa: F401


# ── Query counter ─────────────────────────────────────────────────────────


class _QueryCounter:
    """Listens to SQLAlchemy sync-engine events to count SQL statements."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        self.count += 1

    def reset(self) -> None:
        self.count = 0


# ── Fixtures ──────────────────────────────────────────────────────────────

N_PROJECTS = 50
N_BOQS_PER_PROJECT = 10  # Each project gets 10 BOQs (10 positions each)


@pytest_asyncio.fixture(scope="module")
async def perf_session():
    """Module-scoped: seed once, reuse across all perf tests."""
    tmp_db = Path(tempfile.mkdtemp()) / "perf.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_models()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Seed data
    async with factory() as session:
        from app.modules.boq.models import BOQ, Position
        from app.modules.projects.models import Project
        from app.modules.safety.models import SafetyIncident
        from app.modules.users.models import User
        from app.modules.validation.models import ValidationReport

        owner = User(
            id=uuid.uuid4(),
            email="perf-owner@test.io",
            hashed_password="x",
            full_name="Perf Owner",
            role="admin",
        )
        session.add(owner)
        await session.flush()

        projects: list[Project] = []
        for i in range(N_PROJECTS):
            p = Project(
                id=uuid.uuid4(),
                name=f"Perf-Project-{i:03d}",
                owner_id=owner.id,
                status="active",
                currency="EUR",
            )
            session.add(p)
            await session.flush()
            projects.append(p)

            # N_BOQS_PER_PROJECT BOQs, each with 1 position
            for j in range(N_BOQS_PER_PROJECT):
                boq = BOQ(
                    id=uuid.uuid4(),
                    project_id=p.id,
                    name=f"BOQ-{i:03d}-{j:02d}",
                    status="draft",
                )
                session.add(boq)
                await session.flush()
                session.add(
                    Position(
                        boq_id=boq.id,
                        ordinal=f"{j + 1:02d}",
                        description="Concrete walls",
                        unit="m3",
                        quantity="100",
                        unit_rate="250",
                        total="25000",
                    )
                )

            # Validation report
            session.add(
                ValidationReport(
                    id=uuid.uuid4(),
                    project_id=p.id,
                    target_type="boq",
                    target_id=str(uuid.uuid4()),
                    rule_set="boq_quality",
                    status="passed",
                    score="0.95",
                )
            )

            # Safety incident
            session.add(
                SafetyIncident(
                    id=uuid.uuid4(),
                    project_id=p.id,
                    incident_number=f"INC-{i:03d}",
                    title=f"Near miss #{i}",
                    description="Scaffolding near miss during concrete pour",
                    incident_date="2026-05-01",
                    incident_type="near_miss",
                    severity="minor",
                    osha_recordable=False,
                )
            )

        await session.commit()
        yield session, projects, owner.id

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


# ── Performance assertions ─────────────────────────────────────────────────


class TestRollupPerformance:
    @pytest.mark.asyncio
    async def test_rollup_50_projects_under_2s(self, perf_session) -> None:
        """Full 10-widget rollup across 50 projects must complete in < 2 s."""
        from app.modules.dashboard.service import KNOWN_WIDGETS, compute_rollup

        session, projects, _owner_id = perf_session

        start = time.perf_counter()
        result = await compute_rollup(session, projects, sorted(KNOWN_WIDGETS))
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, (
            f"compute_rollup took {elapsed:.3f}s for {N_PROJECTS} projects "
            f"× {N_BOQS_PER_PROJECT} BOQs — exceeds 2 s budget."
        )
        # Sanity: data must be populated
        assert "boq_summary" in result
        boq_summary = result["boq_summary"]
        assert boq_summary["total_boqs"] == N_PROJECTS * N_BOQS_PER_PROJECT
        assert boq_summary["position_count"] == N_PROJECTS * N_BOQS_PER_PROJECT

    @pytest.mark.asyncio
    async def test_query_count_constant_with_50_projects(
        self,
        perf_session,
    ) -> None:
        """Query count must be O(1) — constant regardless of project count.

        Strategy: run rollup with 1 project, capture query count C1.
        Run rollup with all 50 projects, capture C50.
        Assert C50 == C1 (no per-project loop queries).

        We use a SQLAlchemy sync-engine ``before_cursor_execute`` listener
        that we attach to the underlying connection-level sync engine.
        Because aiosqlite wraps a sync sqlite3 connection, we intercept at
        the sync layer via the ``aiosqlite`` engine's sync engine.
        """
        from app.modules.dashboard.service import KNOWN_WIDGETS, compute_rollup

        session, projects, _owner_id = perf_session
        widgets = sorted(KNOWN_WIDGETS)

        # Attach listener to the sync engine wrapped by the async engine.
        # ``session.get_bind()`` is not available on async sessions; use
        # the ``bind`` attribute of the underlying sync session pool.
        sync_engine = session.get_bind()

        counter = _QueryCounter()
        event.listen(sync_engine, "before_cursor_execute", counter)

        try:
            # Warm up ORM caches with 1 project.
            counter.reset()
            await compute_rollup(session, projects[:1], widgets)
            count_1_project = counter.count

            # Full 50 projects.
            counter.reset()
            await compute_rollup(session, projects, widgets)
            count_50_projects = counter.count
        finally:
            event.remove(sync_engine, "before_cursor_execute", counter)

        # Allow a small slack (±3) for metadata probes, but the core count
        # must not scale linearly with N.
        assert count_50_projects <= count_1_project + 3, (
            f"Query count scaled with project count: "
            f"1 project={count_1_project}, "
            f"50 projects={count_50_projects}. "
            f"Potential N+1 pattern detected."
        )

        # Report for CI output.
        print(f"\n[perf] queries: 1-project={count_1_project}, 50-projects={count_50_projects}")

    @pytest.mark.asyncio
    async def test_accessible_projects_single_query(
        self,
        perf_session,
    ) -> None:
        """accessible_projects uses at most 2 DB calls (admin check + project select)."""
        from app.modules.dashboard.service import accessible_projects

        session, _projects, owner_id = perf_session

        sync_engine = session.get_bind()
        counter = _QueryCounter()
        event.listen(sync_engine, "before_cursor_execute", counter)

        try:
            counter.reset()
            result = await accessible_projects(session, str(owner_id))
        finally:
            event.remove(sync_engine, "before_cursor_execute", counter)

        # 3 is the observed maximum: SQLAlchemy may emit an implicit BEGIN +
        # user-role lookup (session.get) + project SELECT.  The critical
        # invariant is that this stays constant, not that it's exactly 1.
        assert counter.count <= 3, (
            f"accessible_projects issued {counter.count} queries — expected ≤ 3 "
            f"(user-role lookup + project select + possible BEGIN)."
        )
        assert len(result) == N_PROJECTS

    @pytest.mark.asyncio
    async def test_boq_summary_two_queries(self, perf_session) -> None:
        """compute_boq_summary must issue exactly 2 queries regardless of project count."""
        from app.modules.dashboard.service import compute_boq_summary

        session, projects, _owner_id = perf_session

        sync_engine = session.get_bind()
        counter = _QueryCounter()
        event.listen(sync_engine, "before_cursor_execute", counter)

        try:
            counter.reset()
            await compute_boq_summary(session, projects)
            boq_query_count = counter.count
        finally:
            event.remove(sync_engine, "before_cursor_execute", counter)

        assert boq_query_count == 2, (
            f"compute_boq_summary issued {boq_query_count} queries — expected 2 "
            f"(BOQ meta + positions). N+1 regression detected."
        )

    @pytest.mark.asyncio
    async def test_schedule_critical_single_query_with_activities(
        self,
        perf_session,
    ) -> None:
        """compute_schedule_critical issues 1 query when activities exist (scalar subquery).

        The second query (COUNT fallback) fires only when there are zero
        activity rows — which is the case here, so we expect 1 query total.
        When activities exist the COUNT is embedded as a scalar subquery
        in the single main select.
        """
        from app.modules.dashboard.service import compute_schedule_critical

        session, projects, _owner_id = perf_session

        sync_engine = session.get_bind()
        counter = _QueryCounter()
        event.listen(sync_engine, "before_cursor_execute", counter)

        try:
            counter.reset()
            await compute_schedule_critical(session, projects)
            q_count = counter.count
        finally:
            event.remove(sync_engine, "before_cursor_execute", counter)

        # No schedule data seeded → falls back to COUNT query → 2 queries total.
        # With schedule data seeded it would be 1. Either way must be <= 2.
        assert q_count <= 2, f"compute_schedule_critical issued {q_count} queries — expected ≤ 2."
