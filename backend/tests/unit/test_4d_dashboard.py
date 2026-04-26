"""Unit tests for the 4D dashboard service (Section 6 / FR-6.9).

Locks down: SPI/CPI computation, S-curve generation, by_wbs breakdown and
the no-cost-data graceful path.

Per ``feedback_test_isolation.md`` every test owns its own temp SQLite file.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.schedule.models import Activity, Schedule
from app.modules.schedule.service_4d import ScheduleDashboardService


PROJECT_ID = uuid.uuid4()


def _register_minimal_models() -> None:
    """Pull FK-target modules into Base.metadata before create_all."""
    import app.modules.users.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.schedule.models  # noqa: F401


async def _seed_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        email=f"owner-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x",
        full_name="Owner",
    )
    session.add(owner)
    await session.flush()
    session.add(Project(id=project_id, name="Dashboard Test", owner_id=owner.id))
    await session.flush()


@pytest_asyncio.fixture
async def session():
    """Per-test isolated SQLite DB."""
    tmp_db = Path(tempfile.mkdtemp()) / "dashboard.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        await _seed_project(s, PROJECT_ID)
        await s.commit()
        yield s

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


def _activity(
    *,
    schedule_id: uuid.UUID,
    name: str,
    start: str,
    end: str,
    progress: float = 0.0,
    cost_planned: float | None = None,
    cost_actual: float | None = None,
    wbs_code: str = "1",
    duration_days: int | None = None,
) -> Activity:
    if duration_days is None:
        duration_days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    return Activity(
        schedule_id=schedule_id,
        name=name,
        wbs_code=wbs_code,
        start_date=start,
        end_date=end,
        duration_days=duration_days,
        progress_pct=str(progress),
        cost_planned=Decimal(str(cost_planned)) if cost_planned is not None else None,
        cost_actual=Decimal(str(cost_actual)) if cost_actual is not None else None,
    )


@pytest.mark.asyncio
async def test_spi_cpi_computation(session: AsyncSession):
    """SPI = EV/PV; CPI = EV/AC. Two activities make the math non-trivial."""
    schedule = Schedule(project_id=PROJECT_ID, name="SPI/CPI")
    session.add(schedule)
    await session.flush()

    # Activity A: 50% progress, PV=1000, AC=600 → EV=500
    # Activity B: 100% progress, PV=2000, AC=1800 → EV=2000
    # Totals: PV=3000, EV=2500, AC=2400
    # SPI = 2500/3000 ≈ 0.8333
    # CPI = 2500/2400 ≈ 1.0417
    session.add_all(
        [
            _activity(
                schedule_id=schedule.id,
                name="A",
                start="2026-01-01",
                end="2026-02-01",
                progress=50.0,
                cost_planned=1000.0,
                cost_actual=600.0,
            ),
            _activity(
                schedule_id=schedule.id,
                name="B",
                start="2026-01-01",
                end="2026-02-01",
                progress=100.0,
                cost_planned=2000.0,
                cost_actual=1800.0,
            ),
        ]
    )
    await session.flush()

    service = ScheduleDashboardService(session)
    out = await service.dashboard(schedule.id, date(2026, 4, 1))

    assert out.has_cost_data is True
    assert out.spi == pytest.approx(2500.0 / 3000.0, rel=1e-3)
    assert out.cpi == pytest.approx(2500.0 / 2400.0, rel=1e-3)
    assert out.activity_count == 2
    # Both activities have equal duration so the weighted progress is the
    # straight average: (50 + 100) / 2 = 75.
    assert out.overall_progress_percent == pytest.approx(75.0, rel=1e-3)


@pytest.mark.asyncio
async def test_s_curve_emits_points_across_days(session: AsyncSession):
    schedule = Schedule(project_id=PROJECT_ID, name="S-curve")
    session.add(schedule)
    await session.flush()

    session.add(
        _activity(
            schedule_id=schedule.id,
            name="Long task",
            start="2026-01-01",
            end="2026-01-11",
            progress=50.0,
            cost_planned=1000.0,
            cost_actual=400.0,
        )
    )
    await session.flush()

    service = ScheduleDashboardService(session)
    out = await service.dashboard(schedule.id, date(2026, 1, 11))

    # 10-day span, daily granularity → 11 inclusive points (Jan 1 .. Jan 11).
    assert len(out.s_curve_data) == 11
    # First point: PV / EV / AC are 0 at project start.
    assert out.s_curve_data[0]["planned_value"] == pytest.approx(0.0)
    # Last point: PV must be the full planned value.
    assert out.s_curve_data[-1]["planned_value"] == pytest.approx(1000.0, rel=1e-3)
    # PV must be monotonic non-decreasing across the span.
    pvs = [p["planned_value"] for p in out.s_curve_data]
    assert pvs == sorted(pvs)


@pytest.mark.asyncio
async def test_by_wbs_breakdown_groups_by_top_level_prefix(session: AsyncSession):
    schedule = Schedule(project_id=PROJECT_ID, name="WBS")
    session.add(schedule)
    await session.flush()

    # Three top-level WBS buckets: "1.1", "1.2" both roll up to "1"; "2.1"
    # rolls up to "2".
    session.add_all(
        [
            _activity(
                schedule_id=schedule.id,
                name="A1",
                wbs_code="1.1",
                start="2026-01-01",
                end="2026-01-11",
                progress=80.0,
                cost_planned=500.0,
                cost_actual=400.0,
            ),
            _activity(
                schedule_id=schedule.id,
                name="A2",
                wbs_code="1.2",
                start="2026-01-01",
                end="2026-01-11",
                progress=20.0,
                cost_planned=500.0,
                cost_actual=100.0,
            ),
            _activity(
                schedule_id=schedule.id,
                name="A3",
                wbs_code="2.1",
                start="2026-01-01",
                end="2026-01-11",
                progress=100.0,
                cost_planned=200.0,
                cost_actual=180.0,
            ),
        ]
    )
    await session.flush()

    service = ScheduleDashboardService(session)
    out = await service.dashboard(schedule.id, date(2026, 4, 1))

    assert "1" in out.by_wbs and "2" in out.by_wbs
    bucket1 = out.by_wbs["1"]
    bucket2 = out.by_wbs["2"]
    assert bucket1["activity_count"] == 2
    assert bucket2["activity_count"] == 1
    # Bucket 1 progress is the duration-weighted mean of 80% + 20% = 50%.
    assert bucket1["progress_percent"] == pytest.approx(50.0, rel=1e-3)
    # Bucket 2 has a single 100% activity.
    assert bucket2["progress_percent"] == pytest.approx(100.0, rel=1e-3)
    assert bucket1["planned_value"] == pytest.approx(1000.0)
    assert bucket2["planned_value"] == pytest.approx(200.0)


@pytest.mark.asyncio
async def test_no_cost_data_returns_none_for_spi_cpi(session: AsyncSession):
    """When no activity carries cost_planned / cost_actual, SPI/CPI are None."""
    schedule = Schedule(project_id=PROJECT_ID, name="No cost")
    session.add(schedule)
    await session.flush()

    session.add(
        _activity(
            schedule_id=schedule.id,
            name="Cost-less",
            start="2026-01-01",
            end="2026-02-01",
            progress=40.0,
            cost_planned=None,
            cost_actual=None,
        )
    )
    await session.flush()

    service = ScheduleDashboardService(session)
    out = await service.dashboard(schedule.id, date(2026, 4, 1))

    assert out.has_cost_data is False
    assert out.spi is None
    assert out.cpi is None
    # Overall progress still computes from progress_pct.
    assert out.overall_progress_percent == pytest.approx(40.0, rel=1e-3)


@pytest.mark.asyncio
async def test_empty_schedule_returns_zeroed_dashboard(session: AsyncSession):
    schedule = Schedule(project_id=PROJECT_ID, name="Empty")
    session.add(schedule)
    await session.flush()

    service = ScheduleDashboardService(session)
    out = await service.dashboard(schedule.id, date(2026, 4, 1))

    assert out.activity_count == 0
    assert out.overall_progress_percent == 0.0
    assert out.spi is None
    assert out.cpi is None
    assert out.s_curve_data == []
    assert out.by_wbs == {}
