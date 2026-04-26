"""Integration tests for the 4D module HTTP surface (Section 6 — MVP slice).

Stands up a minimal FastAPI app with the 4D v2 routers mounted plus the
session/user dependencies overridden to point at a per-test temp SQLite
file (``feedback_test_isolation.md``).  The EAC predicate resolver is
monkeypatched to a deterministic stub so we don't need a populated BIM
model.

Coverage:

* CSV import (FR-6.1)
* Create + dry-run an EAC schedule link (FR-6.3 / FR-6.4)
* Record a progress entry (FR-6.7) and read history
* GET snapshot (FR-6.6)
* GET dashboard (FR-6.9)
"""

from __future__ import annotations

import io
import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.dependencies import get_current_user_id, get_session


PROJECT_ID = uuid.uuid4()
TEST_USER_ID = str(uuid.uuid4())


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
    session.add(
        Project(id=project_id, name="4D API Test Project", owner_id=owner.id)
    )
    await session.flush()


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    """Spin up a per-test SQLite file and return engine + session factory."""
    tmp_db = Path(tempfile.mkdtemp()) / "fourd_api.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    yield engine, factory, tmp_db

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


@pytest_asyncio.fixture
async def app(temp_engine_and_factory) -> AsyncGenerator[FastAPI, None]:
    """Minimal FastAPI app: only the 4D routers + auth/session overrides."""
    _engine, factory, _tmp = temp_engine_and_factory

    from app.modules.schedule.router_4d import (
        eac_schedule_links_router,
        schedules_v2_router,
    )

    app = FastAPI()
    app.include_router(schedules_v2_router, prefix="/api/v2")
    app.include_router(eac_schedule_links_router, prefix="/api/v2")

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_user() -> str:
        return TEST_USER_ID

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user_id] = _override_user

    yield app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def schedule_id(temp_engine_and_factory) -> str:
    """Seed a project + an empty schedule row directly in the test DB."""
    _engine, factory, _tmp = temp_engine_and_factory
    from app.modules.schedule.models import Schedule

    async with factory() as session:
        await _seed_project(session, PROJECT_ID)
        sched = Schedule(project_id=PROJECT_ID, name="4D Integration Schedule")
        session.add(sched)
        await session.commit()
        await session.refresh(sched)
        return str(sched.id)


# ── Stub resolver: bind to the EAC engine entry the service uses ──────────


@pytest.fixture(autouse=True)
def _stub_resolver(monkeypatch: pytest.MonkeyPatch):
    """Replace the default resolver so we don't need real BIM elements."""

    async def _stub_resolve(self, *, rule_id, predicate_json, model_version_id):
        # Echo a deterministic set so dry-runs return non-empty matches.
        # The set varies by predicate so distinct links resolve distinctly.
        if predicate_json and "selector" in predicate_json:
            return [f"E-{predicate_json['selector']}-1", f"E-{predicate_json['selector']}-2"]
        if rule_id is not None:
            return [f"E-rule-{str(rule_id)[:6]}"]
        return []

    from app.modules.schedule.service_4d import DefaultEacResolver

    monkeypatch.setattr(DefaultEacResolver, "resolve", _stub_resolve)


# ── Tests ─────────────────────────────────────────────────────────────────


SAMPLE_CSV = (
    "wbs_code,name,start,end,duration,predecessors,progress\n"
    "1.1,Excavation,2026-01-01,2026-01-15,14,,100\n"
    "1.2,Foundations,2026-01-16,2026-02-15,30,1.1,40\n"
    "1.3,Walls,2026-02-16,2026-03-31,43,1.2,0\n"
)


@pytest.mark.asyncio
async def test_import_csv_creates_activities(
    client: AsyncClient, schedule_id: str
):
    files = {"file": ("schedule.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")}
    resp = await client.post(
        f"/api/v2/schedules/{schedule_id}/import", files=files
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["activities_created"] == 3
    assert body["activities_failed"] == 0


@pytest.mark.asyncio
async def test_create_eac_schedule_link_runs_dry_run(
    client: AsyncClient, schedule_id: str, temp_engine_and_factory
):
    # Seed an activity directly so we have a task_id to link to.
    _engine, factory, _ = temp_engine_and_factory
    from app.modules.schedule.models import Activity

    async with factory() as session:
        activity = Activity(
            schedule_id=uuid.UUID(schedule_id),
            name="Walls L2",
            wbs_code="2",
            start_date="2026-01-01",
            end_date="2026-03-01",
            duration_days=59,
            progress_pct="0",
        )
        session.add(activity)
        await session.commit()
        await session.refresh(activity)
        task_id = str(activity.id)

    resp = await client.post(
        "/api/v2/eac/schedule-links",
        json={
            "task_id": task_id,
            "predicate_json": {"selector": "walls"},
            "mode": "partial_match",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["task_id"] == task_id
    # Stub resolver returns 2 elements for selector-based predicates.
    assert body["matched_element_count"] == 2

    # And explicit dry-run echoes the same number.
    link_id = body["id"]
    dry = await client.post(
        f"/api/v2/eac/schedule-links/{link_id}:dry-run",
        json={},
    )
    assert dry.status_code == 200
    dry_body = dry.json()
    assert dry_body["matched_count"] == 2
    assert sorted(dry_body["matched_element_ids"]) == ["E-walls-1", "E-walls-2"]


@pytest.mark.asyncio
async def test_create_link_requires_rule_or_predicate(
    client: AsyncClient, schedule_id: str, temp_engine_and_factory
):
    """Body must carry either rule_id or predicate_json — 422 otherwise."""
    _engine, factory, _ = temp_engine_and_factory
    from app.modules.schedule.models import Activity

    async with factory() as session:
        a = Activity(
            schedule_id=uuid.UUID(schedule_id),
            name="X",
            start_date="2026-01-01",
            end_date="2026-01-31",
            duration_days=30,
            progress_pct="0",
        )
        session.add(a)
        await session.commit()
        await session.refresh(a)
        task_id = str(a.id)

    resp = await client.post(
        "/api/v2/eac/schedule-links",
        json={"task_id": task_id, "mode": "partial_match"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_record_progress_and_history(
    client: AsyncClient, schedule_id: str, temp_engine_and_factory
):
    _engine, factory, _ = temp_engine_and_factory
    from app.modules.schedule.models import Activity

    async with factory() as session:
        a = Activity(
            schedule_id=uuid.UUID(schedule_id),
            name="Slab",
            start_date="2026-01-01",
            end_date="2026-01-31",
            duration_days=30,
            progress_pct="0",
        )
        session.add(a)
        await session.commit()
        await session.refresh(a)
        task_id = str(a.id)

    # First entry: 30%
    r1 = await client.post(
        f"/api/v2/schedules/tasks/{task_id}/progress",
        json={"progress_percent": 30.0, "notes": "first pour", "device": "mobile"},
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["progress_percent"] == pytest.approx(30.0)

    # Second entry: 70%
    r2 = await client.post(
        f"/api/v2/schedules/tasks/{task_id}/progress",
        json={"progress_percent": 70.0},
    )
    assert r2.status_code == 201

    history = await client.get(
        f"/api/v2/schedules/tasks/{task_id}/progress-history"
    )
    assert history.status_code == 200
    items = history.json()
    assert len(items) == 2
    assert {e["progress_percent"] for e in items} == {30.0, 70.0}


@pytest.mark.asyncio
async def test_snapshot_returns_status_map(
    client: AsyncClient, schedule_id: str, temp_engine_and_factory
):
    _engine, factory, _ = temp_engine_and_factory
    from app.modules.schedule.models import Activity, EacScheduleLink

    async with factory() as session:
        a1 = Activity(
            schedule_id=uuid.UUID(schedule_id),
            name="In-flight",
            wbs_code="1",
            start_date="2026-01-01",
            end_date="2026-12-31",
            duration_days=365,
            progress_pct="40",
        )
        a2 = Activity(
            schedule_id=uuid.UUID(schedule_id),
            name="Future",
            wbs_code="2",
            start_date="2027-01-01",
            end_date="2027-12-31",
            duration_days=365,
            progress_pct="0",
        )
        session.add_all([a1, a2])
        await session.commit()
        await session.refresh(a1)
        await session.refresh(a2)

        session.add_all(
            [
                EacScheduleLink(
                    task_id=a1.id,
                    predicate_json={"selector": "alpha"},
                    mode="partial_match",
                ),
                EacScheduleLink(
                    task_id=a2.id,
                    predicate_json={"selector": "beta"},
                    mode="partial_match",
                ),
            ]
        )
        await session.commit()

    resp = await client.get(
        f"/api/v2/schedules/{schedule_id}/snapshot",
        params={"as_of_date": "2026-04-15"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    elements = body["elements"]
    # Stub resolver: 2 elements per selector.
    assert elements["E-alpha-1"] == "in_progress"
    assert elements["E-alpha-2"] == "in_progress"
    assert elements["E-beta-1"] == "not_started"


@pytest.mark.asyncio
async def test_dashboard_returns_evm_payload(
    client: AsyncClient, schedule_id: str, temp_engine_and_factory
):
    _engine, factory, _ = temp_engine_and_factory
    from app.modules.schedule.models import Activity

    async with factory() as session:
        a = Activity(
            schedule_id=uuid.UUID(schedule_id),
            name="Cost-loaded",
            wbs_code="1",
            start_date="2026-01-01",
            end_date="2026-02-01",
            duration_days=31,
            progress_pct="50",
            cost_planned=Decimal("1000"),
            cost_actual=Decimal("400"),
        )
        session.add(a)
        await session.commit()

    resp = await client.get(
        f"/api/v2/schedules/{schedule_id}/dashboard",
        params={"as_of_date": date(2026, 4, 1).isoformat()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["activity_count"] == 1
    assert body["has_cost_data"] is True
    # 50% of 1000 PV = 500 EV; SPI=500/1000=0.5; CPI=500/400=1.25.
    assert body["spi"] == pytest.approx(0.5, rel=1e-3)
    assert body["cpi"] == pytest.approx(1.25, rel=1e-3)
    assert body["overall_progress_percent"] == pytest.approx(50.0, rel=1e-3)
