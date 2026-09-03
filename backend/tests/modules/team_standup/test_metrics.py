# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Team metrics tests (PostgreSQL, py3.12).

1. A presence ping accumulates into ONE slot per (user, day, module, job)
   and a single ping can never add more than the cap.
2. The rollup counts a completed task, an open task, an overdue task,
   standups and blockers per person, and presence by module and by job.
3. Session events: login/logout/end are recorded and de-duplicated, the
   first ping of a day mints one 'start' (later pings refresh last_seen),
   and the attendance rows carry first/last/active/still_on + the online
   flag on each person.
4. The metrics router is reachable through the module router the loader
   mounts (the package init includes it) - otherwise the endpoints 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.team_standup import board_service, metrics_service
from app.modules.team_standup.models import StandupEntry, StandupTask
from app.modules.team_standup.presence_models import PresenceSlot, SessionEvent
from app.modules.users.models import User
from tests._pg import transactional_session

TODAY = date.today().isoformat()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, *, name: str) -> User:
    user = User(
        email=f"tm-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name=name,
        role="editor",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, *, name: str) -> Project:
    owner = await _user(session, name=f"owner-{name}")
    proj = Project(
        name=name,
        owner_id=owner.id,
        currency="AUD",
        status="active",
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj


def _person(payload: dict, user_id: str) -> dict:
    return next(p for p in payload["people"] if p["user_id"] == user_id)


def _job(payload: dict, project_id: str) -> dict:
    return next(j for j in payload["jobs"] if j["project_id"] == project_id)


# ── 1. Presence pings ────────────────────────────────────────────────────


def test_module_key_is_the_first_path_segment() -> None:
    assert metrics_service.module_key_from_path("/team-standup/metrics?x=1") == "team-standup"
    assert metrics_service.module_key_from_path("/projects/abc") == "projects"
    assert metrics_service.module_key_from_path("/") == "dashboard"
    assert metrics_service.module_key_from_path("") == "dashboard"
    assert metrics_service.module_key_from_path("/<script>/x") == "other"
    assert metrics_service.module_key_from_path("/" + "a" * 80) == "other"


@pytest.mark.asyncio
async def test_ping_accumulates_into_one_slot_and_caps_each_ping(
    session: AsyncSession,
) -> None:
    user = await _user(session, name="Sam Rivera")
    proj = await _project(session, name="Northbank - Plant upgrade")
    uid, pid = str(user.id), str(proj.id)

    await metrics_service.record_ping(session, user_id=uid, path="/team-standup", project_id=pid, seconds=60)
    await metrics_service.record_ping(session, user_id=uid, path="/team-standup/metrics", project_id=pid, seconds=45)
    # A tab that slept for an hour claims at most the cap.
    slot = await metrics_service.record_ping(session, user_id=uid, path="/team-standup", project_id=pid, seconds=3600)
    assert slot.seconds == 60 + 45 + metrics_service.MAX_SECONDS_PER_PING

    # Negative / junk never subtracts.
    slot = await metrics_service.record_ping(session, user_id=uid, path="/team-standup", project_id=pid, seconds=-500)
    assert slot.seconds == 60 + 45 + metrics_service.MAX_SECONDS_PER_PING

    # A different module, and no job, are separate slots.
    await metrics_service.record_ping(session, user_id=uid, path="/projects", project_id=None, seconds=30)
    await metrics_service.record_ping(session, user_id=uid, path="/projects", project_id=None, seconds=30)
    rows = list(
        await session.scalars(select(PresenceSlot).where(PresenceSlot.user_id == uid, PresenceSlot.day == TODAY))
    )
    assert len(rows) == 2
    by_key = {(r.module_key, r.project_id): r.seconds for r in rows}
    assert by_key[("team-standup", pid)] == 60 + 45 + metrics_service.MAX_SECONDS_PER_PING
    assert by_key[("projects", None)] == 60


# ── 2. The rollup ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_aggregate_tasks_standups_and_presence(
    session: AsyncSession,
) -> None:
    await board_service.ensure_seeded(session)
    stages = await board_service.stages_ordered(session)
    todo = next(s for s in stages if not s.is_done)
    done = next(s for s in stages if s.is_done)

    sam = await _user(session, name="Sam Rivera")
    lee = await _user(session, name="Lee Okafor")
    proj_a = await _project(session, name="Northbank - Plant upgrade")
    proj_b = await _project(session, name="Riverside - Switchroom")
    sid, lid, pa, pb = str(sam.id), str(lee.id), str(proj_a.id), str(proj_b.id)

    now = datetime.now(UTC)
    session.add_all(
        [
            # Sam: one closed 2 days ago that took 4 days, one open, one overdue.
            StandupTask(
                title="Closed one",
                project_id=pa,
                stage_id=done.id,
                assignee_id=sid,
                assignee_name="Sam Rivera",
                created_at=now - timedelta(days=6),
                completed_at=now - timedelta(days=2),
                created_by=sid,
            ),
            StandupTask(
                title="Open one",
                project_id=pa,
                stage_id=todo.id,
                assignee_id=sid,
                assignee_name="Sam Rivera",
                due=(date.today() + timedelta(days=3)).isoformat(),
                created_by=sid,
            ),
            StandupTask(
                title="Late one",
                project_id=pb,
                stage_id=todo.id,
                assignee_id=sid,
                assignee_name="Sam Rivera",
                due=(date.today() - timedelta(days=1)).isoformat(),
                created_by=sid,
            ),
            # Closed long before the window - must not count.
            StandupTask(
                title="Ancient",
                project_id=pa,
                stage_id=done.id,
                assignee_id=sid,
                assignee_name="Sam Rivera",
                created_at=now - timedelta(days=400),
                completed_at=now - timedelta(days=200),
                created_by=sid,
            ),
            # Deleted - never counts.
            StandupTask(
                title="Gone",
                project_id=pa,
                stage_id=todo.id,
                assignee_id=lid,
                assignee_name="Lee Okafor",
                deleted=True,
                created_by=lid,
            ),
            StandupEntry(
                user_id=sid,
                author_name="Sam Rivera",
                day=TODAY,
                today="Cable pulls",
                blockers="Waiting on the switchboard drawings",
            ),
            StandupEntry(
                user_id=sid,
                author_name="Sam Rivera",
                day=(date.today() - timedelta(days=1)).isoformat(),
                today="Site walk",
            ),
            StandupEntry(
                user_id=lid,
                author_name="Lee Okafor",
                day=(date.today() - timedelta(days=60)).isoformat(),
                today="Old news",
                blockers="ancient blocker",
            ),
        ]
    )
    await session.flush()

    await metrics_service.record_ping(session, user_id=sid, path="/team-standup", project_id=pa, seconds=100)
    await metrics_service.record_ping(session, user_id=sid, path="/rfi/123", project_id=pb, seconds=40)
    await metrics_service.record_ping(session, user_id=lid, path="/rfi", project_id=pa, seconds=20)
    # Presence from before the window is invisible at 30 days.
    session.add(
        PresenceSlot(
            user_id=lid,
            day=(date.today() - timedelta(days=45)).isoformat(),
            module_key="projects",
            project_id=None,
            seconds=999,
        )
    )
    await session.flush()

    out = await metrics_service.team_metrics(session, days=30, include_user_id=sid)
    assert out["window_days"] == 30

    sam_row = _person(out, sid)
    assert sam_row["name"] == "Sam Rivera"
    assert sam_row["tasks_completed"] == 1
    assert sam_row["tasks_open"] == 2
    assert sam_row["tasks_overdue"] == 1
    assert sam_row["avg_days_to_close"] == 4.0
    assert sam_row["standups_posted"] == 2
    assert sam_row["blockers_raised"] == 1
    assert sam_row["seconds_by_module"] == {"team-standup": 100, "rfi": 40}
    assert [(j["project_id"], j["seconds"]) for j in sam_row["seconds_by_job"]] == [
        (pa, 100),
        (pb, 40),
    ]

    lee_row = _person(out, lid)
    assert lee_row["tasks_open"] == 0
    assert lee_row["standups_posted"] == 0
    assert lee_row["blockers_raised"] == 0
    assert lee_row["seconds_by_module"] == {"rfi": 20}

    job_a = _job(out, pa)
    assert job_a["code"] == proj_a.project_code
    assert job_a["name"] == "Northbank - Plant upgrade"
    assert job_a["open_tasks"] == 1
    assert job_a["completed"] == 1
    assert job_a["overdue"] == 0
    assert job_a["seconds_total"] == 120
    assert [(p["user_id"], p["seconds"]) for p in job_a["people"]] == [(sid, 100), (lid, 20)]

    job_b = _job(out, pb)
    assert job_b["open_tasks"] == 1
    assert job_b["overdue"] == 1
    assert job_b["seconds_total"] == 40
    # Jobs rank by time first.
    assert out["jobs"].index(job_a) < out["jobs"].index(job_b)

    modules = {m["module_key"]: m["seconds"] for m in out["modules"]}
    assert modules == {"team-standup": 100, "rfi": 60}

    # The window really is a window.
    wide = await metrics_service.team_metrics(session, days=90, include_user_id=sid)
    lee_wide = _person(wide, lid)
    assert lee_wide["standups_posted"] == 1
    assert lee_wide["blockers_raised"] == 1
    assert lee_wide["seconds_by_module"] == {"rfi": 20, "projects": 999}


@pytest.mark.asyncio
async def test_metrics_empty_board_still_lists_the_caller(session: AsyncSession) -> None:
    me = await _user(session, name="Only Me")
    out = await metrics_service.team_metrics(session, days=7, include_user_id=str(me.id))
    row = _person(out, str(me.id))
    assert row["tasks_open"] == 0 and row["seconds_by_module"] == {}
    assert out["modules"] == []


# ── 3. Session events and attendance ─────────────────────────────────────


def _events(session_rows: list[SessionEvent], kind: str) -> list[SessionEvent]:
    return [e for e in session_rows if e.event == kind]


async def _all_events(session: AsyncSession, uid: str) -> list[SessionEvent]:
    return list(
        await session.scalars(select(SessionEvent).where(SessionEvent.user_id == uid).order_by(SessionEvent.at))
    )


@pytest.mark.asyncio
async def test_login_and_logout_are_recorded_and_deduplicated(session: AsyncSession) -> None:
    user = await _user(session, name="Sam Rivera")
    uid = str(user.id)
    # In the past: a client 'at' from the future is replaced by now.
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=6)

    row, created = await metrics_service.record_session_event(session, user_id=uid, event="login", at=t0)
    assert created and row.event == "login" and row.source == "auth"
    # The login page double-fires 20 s later: one login.
    twin, created = await metrics_service.record_session_event(
        session, user_id=uid, event="login", at=t0 + timedelta(seconds=20)
    )
    assert not created and twin.id == row.id
    # A genuine second sign-in an hour later is a new event.
    _, created = await metrics_service.record_session_event(
        session, user_id=uid, event="login", at=t0 + timedelta(hours=1)
    )
    assert created

    _, created = await metrics_service.record_session_event(
        session, user_id=uid, event="logout", at=t0 + timedelta(hours=2)
    )
    assert created
    _, created = await metrics_service.record_session_event(
        session, user_id=uid, event="logout", at=t0 + timedelta(hours=2, seconds=5)
    )
    assert not created
    # An 'end' (tab close) is its own kind, never merged with a logout.
    end, created = await metrics_service.record_session_event(
        session, user_id=uid, event="end", at=t0 + timedelta(hours=2, seconds=5), source="window"
    )
    assert created and end.source == "window"

    rows = await _all_events(session, uid)
    assert [e.event for e in rows] == ["login", "login", "logout", "end"]
    assert all(e.day == TODAY for e in rows)

    # The service refuses junk kinds and a client 'at' from the future.
    with pytest.raises(ValueError):
        await metrics_service.record_session_event(session, user_id=uid, event="teleport")
    future, _ = await metrics_service.record_session_event(
        session, user_id=uid, event="end", at=datetime.now(UTC) + timedelta(days=3)
    )
    assert future.at <= datetime.now(UTC) + timedelta(seconds=5)


@pytest.mark.asyncio
async def test_first_ping_of_the_day_mints_start_and_later_pings_refresh_last_seen(
    session: AsyncSession,
) -> None:
    user = await _user(session, name="Lee Okafor")
    uid = str(user.id)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=6)

    await metrics_service.record_ping(session, user_id=uid, path="/projects", project_id=None, seconds=60, now=t0)
    await metrics_service.record_ping(
        session, user_id=uid, path="/rfi", project_id=None, seconds=60, now=t0 + timedelta(minutes=1)
    )
    await metrics_service.record_ping(
        session, user_id=uid, path="/rfi", project_id=None, seconds=60, now=t0 + timedelta(minutes=9)
    )
    starts = _events(await _all_events(session, uid), "start")
    assert len(starts) == 1
    assert starts[0].at == t0
    assert starts[0].source == "beacon"
    assert starts[0].meta == {"last_seen": (t0 + timedelta(minutes=9)).isoformat()}

    # A late-arriving older ping never moves last_seen backwards.
    await metrics_service.record_ping(
        session, user_id=uid, path="/rfi", project_id=None, seconds=10, now=t0 + timedelta(minutes=2)
    )
    starts = _events(await _all_events(session, uid), "start")
    assert starts[0].meta == {"last_seen": (t0 + timedelta(minutes=9)).isoformat()}

    # Another day is another start.
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    await metrics_service.record_ping(
        session,
        user_id=uid,
        path="/rfi",
        project_id=None,
        seconds=10,
        today=yesterday,
        now=t0 - timedelta(days=1),
    )
    assert len(_events(await _all_events(session, uid), "start")) == 2


@pytest.mark.asyncio
async def test_attendance_rows_aggregate_first_last_active_and_still_on(
    session: AsyncSession,
) -> None:
    sam = await _user(session, name="Sam Rivera")
    lee = await _user(session, name="Lee Okafor")
    sid, lid = str(sam.id), str(lee.id)
    now = datetime.now(UTC).replace(microsecond=0)
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # Sam today: signed in 3 h ago, pinged until a minute ago -> still on.
    await metrics_service.record_session_event(session, user_id=sid, event="login", at=now - timedelta(hours=3))
    await metrics_service.record_ping(
        session,
        user_id=sid,
        path="/rfi",
        project_id=None,
        seconds=120,
        now=now - timedelta(hours=3, seconds=-30),
    )
    await metrics_service.record_ping(
        session, user_id=sid, path="/rfi", project_id=None, seconds=90, now=now - timedelta(minutes=1)
    )
    # Lee today: on at 8, closed the tab and signed out an hour ago -> off.
    await metrics_service.record_session_event(session, user_id=lid, event="login", at=now - timedelta(hours=5))
    await metrics_service.record_ping(
        session, user_id=lid, path="/projects", project_id=None, seconds=60, now=now - timedelta(hours=5)
    )
    await metrics_service.record_session_event(
        session, user_id=lid, event="end", at=now - timedelta(hours=1), source="window"
    )
    await metrics_service.record_session_event(session, user_id=lid, event="logout", at=now - timedelta(hours=1))
    # Lee yesterday: a login with no beacon at all still makes a row.
    await metrics_service.record_session_event(
        session, user_id=lid, event="login", at=now - timedelta(days=1), today=yesterday
    )

    out = await metrics_service.team_metrics(session, days=7, include_user_id=sid, now=now)
    rows = out["attendance"]
    assert [(r["name"], r["day"]) for r in rows] == [
        ("Lee Okafor", TODAY),
        ("Sam Rivera", TODAY),
        ("Lee Okafor", yesterday),
    ]

    sam_row = rows[1]
    assert sam_row["first_seen"] == (now - timedelta(hours=3)).isoformat()
    assert sam_row["last_seen"] == (now - timedelta(minutes=1)).isoformat()
    assert sam_row["active_seconds"] == 210
    assert sam_row["logins"] == [(now - timedelta(hours=3)).isoformat()]
    assert sam_row["logouts"] == [] and sam_row["ends"] == []
    assert sam_row["still_on"] is True

    lee_row = rows[0]
    assert lee_row["first_seen"] == (now - timedelta(hours=5)).isoformat()
    assert lee_row["last_seen"] == (now - timedelta(hours=1)).isoformat()
    assert lee_row["active_seconds"] == 60
    assert lee_row["logouts"] == [(now - timedelta(hours=1)).isoformat()]
    assert lee_row["ends"] == [(now - timedelta(hours=1)).isoformat()]
    assert lee_row["still_on"] is False

    lee_yday = rows[2]
    assert lee_yday["active_seconds"] == 0
    assert lee_yday["logins"] == [(now - timedelta(days=1)).isoformat()]
    assert lee_yday["still_on"] is False

    # The People rows carry today's summary + the online flag.
    assert _person(out, sid)["today"] == {
        "first_seen": sam_row["first_seen"],
        "last_seen": sam_row["last_seen"],
        "online": True,
    }
    assert _person(out, lid)["today"]["online"] is False

    # Four minutes of silence and Sam is no longer online.
    later = await metrics_service.team_metrics(session, days=7, include_user_id=sid, now=now + timedelta(minutes=4))
    assert _person(later, sid)["today"]["online"] is False
    assert next(r for r in later["attendance"] if r["user_id"] == sid)["still_on"] is False

    # A one-day window drops yesterday.
    narrow = await metrics_service.team_metrics(session, days=1, include_user_id=sid, now=now)
    assert all(r["day"] == TODAY for r in narrow["attendance"])
    assert len(narrow["attendance"]) == 2


@pytest.mark.asyncio
async def test_metrics_without_any_session_events_has_empty_attendance(
    session: AsyncSession,
) -> None:
    me = await _user(session, name="Only Me")
    out = await metrics_service.team_metrics(session, days=7, include_user_id=str(me.id))
    assert out["attendance"] == []
    assert _person(out, str(me.id))["today"] == {
        "first_seen": None,
        "last_seen": None,
        "online": False,
    }


# ── 4. Mounted through the module router ─────────────────────────────────


def test_metrics_routes_ride_the_module_router() -> None:
    # Mount the module router exactly as the loader does and read the
    # resolved OpenAPI paths (FastAPI nests included routers lazily, so
    # ``router.routes`` alone does not list them).
    from fastapi import FastAPI

    import app.modules.team_standup.router as router_mod

    api = FastAPI()
    api.include_router(router_mod.router, prefix="/api/v1/team-standup")
    paths = set(api.openapi()["paths"])
    assert "/api/v1/team-standup/presence/ping" in paths
    assert "/api/v1/team-standup/presence/session" in paths
    assert "/api/v1/team-standup/presence/today" in paths
    assert "/api/v1/team-standup/metrics" in paths
    assert "/api/v1/team-standup/board" in paths


# ── 5. Who may READ the rollup ───────────────────────────────────────────
#
# The rollup is management information about people (per-person task
# throughput, standup and blocker counts, hours by job and by module, and
# an attendance table of sign-ins / last-seen / still-on). It must not be
# readable by the whole team, so GET /metrics is gated on
# ``team_standup.metrics`` at MANAGER while the two presence WRITES stay
# on ``team_standup.read`` at VIEWER - every signed-in user reports their
# own presence or the table has nothing in it.


def test_metrics_permission_is_manager_level_and_the_rest_stay_viewer() -> None:
    import app.modules.team_standup.router  # noqa: F401 - the loader's import
    from app.core.permissions import permission_registry

    for role in ("viewer", "editor"):
        assert not permission_registry.role_has_permission(role, "team_standup.metrics"), (
            f"{role} must NOT read the team rollup - it is management information about colleagues"
        )
        # ... but the same role still writes its own presence.
        assert permission_registry.role_has_permission(role, "team_standup.read")
    for role in ("manager", "admin"):
        assert permission_registry.role_has_permission(role, "team_standup.metrics")


def _metrics_app(db_session, *, caller_id: str, role: str) -> FastAPI:  # noqa: F821
    """The module router mounted with auth/session overrides, as the loader does.

    ``permissions`` is left empty on purpose: ``RequirePermission`` falls
    back to the live registry for the caller's role, which is the path a
    real (possibly stale) token takes.
    """
    from fastapi import FastAPI

    import app.modules.team_standup.router as router_mod
    from app.dependencies import (
        get_current_user_id,
        get_current_user_payload,
        get_session,
    )

    api = FastAPI()
    api.include_router(router_mod.router, prefix="/v1/team-standup")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _payload_override() -> dict:
        return {"sub": caller_id, "role": role, "permissions": []}

    api.dependency_overrides[get_session] = _session_override
    api.dependency_overrides[get_current_user_id] = _user_override
    api.dependency_overrides[get_current_user_payload] = _payload_override
    return api


async def _call(api, method: str, path: str, **kw):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kw)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor"])
async def test_ordinary_roles_are_refused_the_team_rollup(session: AsyncSession, role: str) -> None:
    me = await _user(session, name="Alex Example")
    await session.commit()
    api = _metrics_app(session, caller_id=str(me.id), role=role)
    resp = await _call(api, "GET", "/v1/team-standup/metrics?days=7")
    assert resp.status_code == 403, resp.text
    # And nothing about anybody leaked in the body.
    assert "attendance" not in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["manager", "admin"])
async def test_managers_and_admins_read_the_team_rollup(session: AsyncSession, role: str) -> None:
    me = await _user(session, name="Alex Example")
    await session.commit()
    api = _metrics_app(session, caller_id=str(me.id), role=role)
    resp = await _call(api, "GET", "/v1/team-standup/metrics?days=7")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["window_days"] == 7
    assert isinstance(body["attendance"], list)
    assert any(p["user_id"] == str(me.id) for p in body["people"])


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor"])
async def test_an_ordinary_user_still_reports_their_own_presence(session: AsyncSession, role: str) -> None:
    """The gate is on READING the aggregate, never on writing your own row."""
    me = await _user(session, name="Alex Example")
    await session.commit()
    api = _metrics_app(session, caller_id=str(me.id), role=role)

    ping = await _call(
        api,
        "POST",
        "/v1/team-standup/presence/ping",
        json={"path": "/team-standup", "seconds": 60},
    )
    assert ping.status_code == 200, ping.text
    assert ping.json()["module_key"] == "team-standup"
    assert ping.json()["added"] == 60

    event = await _call(
        api,
        "POST",
        "/v1/team-standup/presence/session",
        json={"event": "login"},
    )
    assert event.status_code == 200, event.text
    assert event.json()["event"] == "login"


# ── 6. Nothing on the dashboard is a raw id ──────────────────────────────


@pytest.mark.asyncio
async def test_a_job_without_a_code_reports_no_code_not_a_guid_slice(
    session: AsyncSession,
) -> None:
    """A job with no project_code used to arrive as the first 8 hex of its id.

    That put a raw GUID fragment on screen wearing a job number's clothes.
    An empty code lets the client say "No job number" in words instead.
    """
    owner = await _user(session, name="Alex Example")
    proj = Project(
        name="Acme Holdings - Switchroom",
        owner_id=owner.id,
        currency="AUD",
        status="active",
        project_code=None,
    )
    session.add(proj)
    await session.flush()
    me = await _user(session, name="Sam Example")
    await metrics_service.record_ping(
        session, user_id=str(me.id), path="/projects", project_id=str(proj.id), seconds=60
    )
    await session.flush()

    out = await metrics_service.team_metrics(session, days=7)
    job = _job(out, str(proj.id))
    assert job["code"] == ""
    assert str(proj.id)[:8] not in job["code"]
    assert job["name"] == "Acme Holdings - Switchroom"


# ── 7. Today's presence is viewer-safe ───────────────────────────────────
#
# Restricting /metrics to managers was right, but the project hub's team
# tile read that same endpoint for the one harmless part of it: who is on
# right now. GET /presence/today gives the team back exactly that part and
# nothing else, at team_standup.read. These tests pin the split: the key
# set is exhaustive (so no counter can be slipped in), an editor gets 200
# here and 403 on the rollup, and a manager gets both.

#: The complete key set of a presence row. Written out, and asserted with
#: ``==`` rather than ``<=``, so ADDING a field to the viewer-level payload
#: fails here and has to be argued for rather than merged in passing.
PRESENCE_KEYS = {"user_id", "name", "online", "first_seen", "last_seen"}

#: Fields that make ``/metrics`` manager-only. None may ever appear on a
#: presence row.
PERFORMANCE_KEYS = {
    "tasks_completed",
    "tasks_open",
    "tasks_overdue",
    "avg_days_to_close",
    "standups_posted",
    "blockers_raised",
    "seconds_by_module",
    "seconds_by_job",
    "active_seconds",
    "attendance",
    "day",
    "logins",
    "logouts",
    "ends",
    "still_on",
}


@pytest.mark.asyncio
async def test_presence_today_is_only_today_and_only_presence(
    session: AsyncSession,
) -> None:
    sam = await _user(session, name="Sam Rivera")
    lee = await _user(session, name="Lee Okafor")
    sid, lid = str(sam.id), str(lee.id)
    now = datetime.now(UTC).replace(microsecond=0)
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # Sam: on since 07:00-ish, pinged a minute ago -> online.
    await metrics_service.record_ping(
        session,
        user_id=sid,
        path="/rfi",
        project_id=None,
        seconds=120,
        now=now - timedelta(hours=3),
    )
    await metrics_service.record_ping(
        session,
        user_id=sid,
        path="/rfi",
        project_id=None,
        seconds=90,
        now=now - timedelta(minutes=1),
    )
    # Lee: signed in this morning, gone for an hour -> seen today, not online.
    await metrics_service.record_session_event(session, user_id=lid, event="login", at=now - timedelta(hours=5))
    await metrics_service.record_session_event(session, user_id=lid, event="logout", at=now - timedelta(hours=1))
    # Yesterday belongs to the rollup, never to this endpoint.
    await metrics_service.record_ping(
        session,
        user_id=lid,
        path="/projects",
        project_id=None,
        seconds=60,
        today=yesterday,
        now=now - timedelta(days=1),
    )
    await session.flush()

    rows = await metrics_service.presence_today(session, now=now)
    by_user = {r["user_id"]: r for r in rows}
    assert sid in by_user and lid in by_user

    for row in rows:
        assert set(row) == PRESENCE_KEYS, "a presence row grew a field"
        assert not (set(row) & PERFORMANCE_KEYS)

    assert by_user[sid]["online"] is True
    assert by_user[sid]["name"] == "Sam Rivera"
    assert by_user[sid]["first_seen"] == (now - timedelta(hours=3)).isoformat()
    assert by_user[sid]["last_seen"] == (now - timedelta(minutes=1)).isoformat()

    assert by_user[lid]["online"] is False
    assert by_user[lid]["first_seen"] == (now - timedelta(hours=5)).isoformat()
    # Yesterday's presence never reaches today's row.
    assert by_user[lid]["last_seen"] == (now - timedelta(hours=1)).isoformat()

    # Same three-minute rule as the rollup: four minutes of silence is off.
    later = await metrics_service.presence_today(session, now=now + timedelta(minutes=4))
    assert {r["user_id"]: r["online"] for r in later}[sid] is False


@pytest.mark.asyncio
async def test_presence_today_is_scoped_to_the_project_members(
    session: AsyncSession,
) -> None:
    """With a project id the tile only ever names people on that job."""
    from app.modules.teams.models import Team, TeamMembership

    proj = await _project(session, name="Northbank - Plant upgrade")
    member = await _user(session, name="Sam Rivera")
    outsider = await _user(session, name="Lee Okafor")
    caller = await _user(session, name="Robin Vale")

    team = Team(project_id=proj.id, name="Default Team", is_default=True)
    session.add(team)
    await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=member.id, role="member"))
    await session.flush()

    now = datetime.now(UTC).replace(microsecond=0)
    for who in (member, outsider):
        await metrics_service.record_ping(
            session,
            user_id=str(who.id),
            path="/projects",
            project_id=str(proj.id),
            seconds=60,
            now=now - timedelta(minutes=1),
        )
    await session.flush()

    rows = await metrics_service.presence_today(
        session, project_id=str(proj.id), include_user_id=str(caller.id), now=now
    )
    ids = {r["user_id"] for r in rows}
    assert str(member.id) in ids
    assert str(outsider.id) not in ids, "a non-member leaked onto the project tile"
    # The caller is always in their own list, even with no presence yet.
    assert str(caller.id) in ids

    # An unknown or malformed project scopes to nobody, never to everybody.
    for bad in (str(uuid.uuid4()), "not-a-uuid"):
        only_me = await metrics_service.presence_today(session, project_id=bad, include_user_id=str(caller.id), now=now)
        assert {r["user_id"] for r in only_me} == {str(caller.id)}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor"])
async def test_ordinary_roles_read_presence_but_not_the_rollup(session: AsyncSession, role: str) -> None:
    """The gap this endpoint closes: 200 on presence, 403 on the rollup."""
    me = await _user(session, name="Robin Vale")
    now = datetime.now(UTC).replace(microsecond=0)
    await metrics_service.record_ping(
        session,
        user_id=str(me.id),
        path="/projects",
        project_id=None,
        seconds=60,
        now=now,
    )
    await session.commit()
    api = _metrics_app(session, caller_id=str(me.id), role=role)

    rollup = await _call(api, "GET", "/v1/team-standup/metrics?days=7")
    assert rollup.status_code == 403, rollup.text

    resp = await _call(api, "GET", "/v1/team-standup/presence/today")
    assert resp.status_code == 200, resp.text
    body = resp.json()["items"]
    assert isinstance(body, list) and body
    row = next(r for r in body if r["user_id"] == str(me.id))
    assert set(row) == PRESENCE_KEYS
    assert row["name"] == "Robin Vale"
    assert row["online"] is True
    # Nothing performance-shaped anywhere in the payload, not even a key.
    for key in PERFORMANCE_KEYS:
        assert key not in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["manager", "admin"])
async def test_managers_read_presence_and_the_rollup(session: AsyncSession, role: str) -> None:
    me = await _user(session, name="Robin Vale")
    await session.commit()
    api = _metrics_app(session, caller_id=str(me.id), role=role)

    presence = await _call(api, "GET", "/v1/team-standup/presence/today")
    assert presence.status_code == 200, presence.text
    assert any(r["user_id"] == str(me.id) for r in presence.json()["items"])

    rollup = await _call(api, "GET", "/v1/team-standup/metrics?days=7")
    assert rollup.status_code == 200, rollup.text
