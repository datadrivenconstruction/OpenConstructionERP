# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A client sees the next milestones a person marked for them.

Surface (portal-session-gated):
    GET /api/v1/portal/projects/{project_id}/milestones

Tests:
* Only milestones marked ``client_visible`` are listed; an internal one with
  the same dates is not.
* A late milestone stays listed and says so; a done one in the past drops out.
* A milestone beyond the window, a task, and an archived schedule's milestone
  are not listed.
* The expected date is the live finish; the planned date comes from the
  active baseline, so a slipped milestone shows both.
* Another project's milestones answer 404, like a project that does not exist.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _no_detached_events(monkeypatch):
    from app.core import events

    monkeypatch.setattr(events.event_bus, "publish_detached", lambda *a, **k: None)


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.portal import models as _portal_models  # noqa: F401
        from app.modules.schedule import models as _schedule_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _iso(offset_days: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset_days)).isoformat()


@pytest_asyncio.fixture(scope="module")
async def seeded(http_client):
    from app.database import async_session_factory
    from app.modules.portal.models import PortalAccessRule, PortalSession, PortalUser
    from app.modules.portal.service import generate_token, hash_token
    from app.modules.projects.models import Project
    from app.modules.schedule.models import Activity, Schedule, ScheduleBaseline
    from app.modules.schedule.snapshot_envelope import live_envelope
    from app.modules.users.models import User

    now = datetime.now(UTC)
    async with async_session_factory() as s:
        owner = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:8]}@milestones.io",
            full_name="Builder",
            hashed_password="x" * 60,
            role="admin",
            is_active=True,
        )
        s.add(owner)
        await s.flush()
        mine = Project(name=f"Milestones-{uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="USD")
        other = Project(name=f"Milestones-other-{uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="USD")
        s.add_all([mine, other])
        await s.flush()

        live = Schedule(project_id=mine.id, name="Main", status="draft")
        archived = Schedule(project_id=mine.id, name="Old", status="archived")
        foreign = Schedule(project_id=other.id, name="Other", status="active")
        s.add_all([live, archived, foreign])
        await s.flush()

        def act(schedule, name, offset, *, visible=True, kind="milestone", status="not_started", early=None):
            return Activity(
                schedule_id=schedule.id,
                name=name,
                start_date=_iso(offset),
                end_date=_iso(offset),
                activity_type=kind,
                status=status,
                client_visible=visible,
                # CPM stores a day offset here, not a date.
                early_finish=str(early) if early is not None else None,
            )

        # Agreed for day 6, moved to day 10 when the work before it slipped.
        windows = act(live, "Windows in", 10, early=42)
        windows.id = uuid.uuid4()

        s.add_all(
            [
                act(live, "Foundation poured", 3),
                act(live, "Steel supplier paid", 3, visible=False),
                act(live, "Framing complete", -2),
                act(live, "Permit issued", -5, status="completed"),
                act(live, "Roof on", 40),
                act(live, "Drywall", 5, kind="task"),
                windows,
                act(archived, "Old plan milestone", 4),
                act(foreign, "Their milestone", 2),
            ]
        )

        def frozen(finish_offset):
            # The shape the schedule snapshot endpoint hands out for a baseline.
            agreed = SimpleNamespace(id=windows.id, name=windows.name, start_date=_iso(0), end_date=_iso(finish_offset))
            return live_envelope([agreed], [])

        s.add_all(
            [
                ScheduleBaseline(
                    schedule_id=live.id,
                    project_id=mine.id,
                    name="Contract programme",
                    baseline_date=_iso(-30),
                    snapshot_data=frozen(6),
                    is_active=True,
                ),
                # Superseded baselines never speak for the plan.
                ScheduleBaseline(
                    schedule_id=live.id,
                    project_id=mine.id,
                    name="Draft programme",
                    baseline_date=_iso(-60),
                    snapshot_data=frozen(1),
                    is_active=False,
                ),
            ]
        )

        client = PortalUser(
            id=uuid.uuid4(),
            email=f"client-{uuid.uuid4().hex[:6]}@milestones.io",
            portal_role="client",
            full_name="Home Owner",
            status="active",
        )
        s.add(client)
        await s.flush()
        s.add(
            PortalAccessRule(portal_user_id=client.id, resource_type="project", resource_id=mine.id, permission="view")
        )
        token = generate_token()
        s.add(
            PortalSession(
                portal_user_id=client.id,
                session_token_hash=hash_token(token),
                ip_address="127.0.0.1",
                user_agent="pytest",
                started_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        await s.commit()
    return {"project_id": str(mine.id), "other_id": str(other.id), "headers": {"Authorization": f"Bearer {token}"}}


@pytest.mark.asyncio
async def test_the_client_sees_marked_upcoming_and_late_milestones_only(http_client, seeded):
    resp = await http_client.get(
        f"/api/v1/portal/projects/{seeded['project_id']}/milestones", headers=seeded["headers"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["window_days"] == 14
    by_name = {m["name"]: m for m in body["items"]}
    assert list(by_name) == ["Framing complete", "Foundation poured", "Windows in"]

    late = by_name["Framing complete"]
    assert late["is_late"] is True
    assert late["days_until"] == -2

    slipped = by_name["Windows in"]
    assert slipped["planned_date"] == _iso(6)
    assert slipped["expected_date"] == _iso(10)
    assert slipped["days_until"] == 10
    assert date.fromisoformat(slipped["expected_date"]) > date.fromisoformat(slipped["planned_date"])

    # Without a baseline the client sees one date, the live one.
    on_time = by_name["Foundation poured"]
    assert on_time["planned_date"] == on_time["expected_date"] == _iso(3)


@pytest.mark.asyncio
async def test_a_wider_window_reaches_further(http_client, seeded):
    resp = await http_client.get(
        f"/api/v1/portal/projects/{seeded['project_id']}/milestones?days=60", headers=seeded["headers"]
    )
    assert resp.status_code == 200
    assert "Roof on" in {m["name"] for m in resp.json()["items"]}


@pytest.mark.asyncio
async def test_another_projects_milestones_read_as_missing(http_client, seeded):
    resp = await http_client.get(f"/api/v1/portal/projects/{seeded['other_id']}/milestones", headers=seeded["headers"])
    assert resp.status_code == 404
    missing = await http_client.get(f"/api/v1/portal/projects/{uuid.uuid4()}/milestones", headers=seeded["headers"])
    assert missing.status_code == 404
    assert resp.json() == missing.json()
