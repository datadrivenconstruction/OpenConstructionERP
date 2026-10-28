"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project schedule rollup: ``GET /api/v1/schedule/stats/``.

The project-dashboard "Schedule summary" widget reads this endpoint for
progress, completed/delayed counts, and the next milestone. This pins:

* an empty project returns zeros (and ``next_milestone`` is null), so the
  widget shows its empty state rather than a fake 0 % bar;
* a populated project reports the right counts and surfaces the earliest
  unfinished milestone.

Milestone dates are far-future so the "upcoming preferred" pick is stable
regardless of the day the suite runs; the delayed task uses a far-past date
for the same reason.

Runs against the PostgreSQL cluster provisioned by ``tests/conftest.py``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.schedule import models as _schedule_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_login_admin(client: AsyncClient) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"sched-stats-{uuid.uuid4().hex[:8]}@schedule.io"
    password = f"SchedStat{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Stats Owner"},
    )
    assert reg.status_code in (200, 201), reg.text

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_project(client: AsyncClient, headers: dict[str, str]) -> str:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"Stats {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return proj.json()["id"]


@pytest.mark.asyncio
async def test_stats_empty_project_returns_zeros(http_client):
    headers = await _register_login_admin(http_client)
    project_id = await _make_project(http_client, headers)

    res = await http_client.get(
        f"/api/v1/schedule/stats/?project_id={project_id}",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total_activities"] == 0
    assert body["completed"] == 0
    assert body["delayed"] == 0
    assert body["next_milestone"] is None


@pytest.mark.asyncio
async def test_stats_counts_and_next_milestone(http_client):
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.schedule.models import Activity

    headers = await _register_login_admin(http_client)
    project_id = await _make_project(http_client, headers)

    sched = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": project_id,
            "name": "Main Schedule",
            "start_date": "2026-05-01",
            "end_date": "2099-12-31",
        },
        headers=headers,
    )
    assert sched.status_code == 201, sched.text
    schedule_id = sched.json()["id"]

    async def _add(name: str, start: str, end: str, kind: str) -> str:
        res = await http_client.post(
            f"/api/v1/schedule/schedules/{schedule_id}/activities/",
            json={
                "name": name,
                "start_date": start,
                "end_date": end,
                "activity_type": kind,
            },
            headers=headers,
        )
        assert res.status_code == 201, res.text
        return res.json()["id"]

    # One far-overdue task (delayed), one in-progress task, plus two future
    # milestones. A third task is force-completed below.
    overdue_id = await _add("Demolition", "2019-12-01", "2020-01-01", "task")
    await _add("Framing", "2026-05-04", "2099-01-01", "task")
    done_id = await _add("Sitework", "2026-05-04", "2099-01-01", "task")
    await _add("Topping out", "2099-08-01", "2099-08-01", "milestone")
    await _add("Foundation complete", "2099-06-15", "2099-06-15", "milestone")

    # Force one task to 100 % so it counts as completed; the overdue task
    # stays at 0 % so it counts as delayed.
    async with async_session_factory() as s:
        await s.execute(
            update(Activity).where(Activity.id == uuid.UUID(done_id)).values(progress_pct="100", status="completed")
        )
        await s.execute(
            update(Activity).where(Activity.id == uuid.UUID(overdue_id)).values(progress_pct="0", status="in_progress")
        )
        await s.commit()

    res = await http_client.get(
        f"/api/v1/schedule/stats/?project_id={project_id}",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["total_activities"] == 5
    assert body["completed"] == 1
    assert body["delayed"] == 1
    assert isinstance(body["progress_pct"], (int, float))

    # Earliest unfinished milestone wins (both are future, so the earlier
    # date 2099-06-15 is preferred over 2099-08-01).
    assert body["next_milestone"] is not None
    assert body["next_milestone"]["name"] == "Foundation complete"
    assert body["next_milestone"]["date"] == "2099-06-15"
