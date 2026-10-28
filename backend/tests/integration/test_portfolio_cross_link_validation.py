# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cross-link activity/schedule consistency guard - T3.3 portfolio.

``PortfolioService.create_cross_link`` verifies the caller can reach BOTH
projects (IDOR defence, 404 on deny). On top of that it must also reject a
WELL-FORMED but inconsistent request from a caller who CAN reach both
projects: an ``*_activity_id`` that does not actually live in the
``*_schedule_id`` it is filed under. Without that guard the bogus pair was
accepted at create time and only silently dropped later at CPM compute time.

This suite drives the real ``POST /api/v1/portfolio/cross-links/`` route end to
end - real registration / login / RBAC, the throwaway PostgreSQL DB - against an
admin tenant that owns both projects, so the access gate passes and the only
thing under test is the new consistency check (HTTP 422, never a 2xx).

Scaffolding mirrors ``test_schedule_idor.py``: the engine is bound to the shared
PostgreSQL cluster by ``conftest.py`` before any ``from app...`` import runs
(see ``feedback_test_isolation.md``).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.portfolio import models as _portfolio_models  # noqa: F401
        from app.modules.schedule import models as _schedule_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_admin(client: AsyncClient) -> dict[str, str]:
    """Register one tenant, promote to admin, and return auth headers.

    Admin bypasses both RBAC (``portfolio.manage``) and ``verify_project_access``,
    so the request reaches the new consistency check with both projects reachable
    - exactly the path the 422 guards.
    """
    email = f"x-{uuid.uuid4().hex[:8]}@portfolio-xlink.io"
    password = f"XLink{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Cross-link tenant"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.status_code} {reg.text}"

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_schedule_with_activity(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    label: str,
) -> tuple[str, str]:
    """Create a project + schedule + one activity; return (schedule_id, activity_id)."""
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"XLink-{label} {uuid.uuid4().hex[:6]}",
            "description": "cross-link validation fixture",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, f"project create failed: {proj.text}"
    project_id = proj.json()["id"]

    sched = await client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": project_id,
            "name": f"{label} schedule",
            "start_date": "2026-05-01",
            "end_date": "2026-09-30",
        },
        headers=headers,
    )
    assert sched.status_code == 201, f"schedule create failed: {sched.text}"
    schedule_id = sched.json()["id"]

    act = await client.post(
        f"/api/v1/schedule/schedules/{schedule_id}/activities/",
        json={
            "name": f"{label} activity",
            "wbs_code": "01.01",
            "start_date": "2026-05-04",
            "end_date": "2026-05-15",
            "activity_type": "task",
        },
        headers=headers,
    )
    assert act.status_code == 201, f"activity create failed: {act.text}"
    return schedule_id, act.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def two_schedules(http_client):
    """One admin owning two projects, each with a schedule and one activity."""
    headers = await _register_admin(http_client)
    pred_sched, pred_act = await _make_schedule_with_activity(http_client, headers, label="pred")
    succ_sched, succ_act = await _make_schedule_with_activity(http_client, headers, label="succ")
    return {
        "headers": headers,
        "pred_schedule_id": pred_sched,
        "pred_activity_id": pred_act,
        "succ_schedule_id": succ_sched,
        "succ_activity_id": succ_act,
    }


async def _count_links(predecessor_schedule_id: str) -> int:
    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.portfolio.models import PortfolioCrossLink

    async with async_session_factory() as s:
        total = await s.scalar(
            select(func.count())
            .select_from(PortfolioCrossLink)
            .where(PortfolioCrossLink.predecessor_schedule_id == uuid.UUID(predecessor_schedule_id))
        )
    return int(total or 0)


# ── Happy path: matched activities are accepted ──────────────────────────────


@pytest.mark.asyncio
async def test_cross_link_with_matching_activities_is_created(http_client, two_schedules):
    """Both activities genuinely live in their schedules -> 201 + a row written."""
    s = two_schedules
    resp = await http_client.post(
        "/api/v1/portfolio/cross-links/",
        json={
            "predecessor_schedule_id": s["pred_schedule_id"],
            "predecessor_activity_id": s["pred_activity_id"],
            "successor_schedule_id": s["succ_schedule_id"],
            "successor_activity_id": s["succ_activity_id"],
            "dep_type": "FS",
            "lag_days": 0,
        },
        headers=s["headers"],
    )
    assert resp.status_code == 201, f"valid cross-link rejected: {resp.status_code} {resp.text}"
    body = resp.json()
    assert body["predecessor_activity_id"] == s["pred_activity_id"]
    assert body["successor_activity_id"] == s["succ_activity_id"]


# ── 422: an activity that does not belong to its schedule is rejected ─────────


@pytest.mark.asyncio
async def test_predecessor_activity_in_wrong_schedule_is_422(http_client, two_schedules):
    """Predecessor activity actually lives in the SUCCESSOR schedule -> 422.

    The caller can reach both projects (admin), so this is a well-formed but
    inconsistent request: it must be a 422, not a 404 and never a 2xx, and no
    link row may be written.
    """
    s = two_schedules
    before = await _count_links(s["pred_schedule_id"])

    resp = await http_client.post(
        "/api/v1/portfolio/cross-links/",
        json={
            "predecessor_schedule_id": s["pred_schedule_id"],
            # This activity belongs to the SUCCESSOR schedule, not the predecessor.
            "predecessor_activity_id": s["succ_activity_id"],
            "successor_schedule_id": s["succ_schedule_id"],
            "successor_activity_id": s["succ_activity_id"],
        },
        headers=s["headers"],
    )
    assert resp.status_code == 422, f"expected 422 for mismatched predecessor: {resp.status_code} {resp.text}"
    assert "predecessor_activity_id" in resp.text

    after = await _count_links(s["pred_schedule_id"])
    assert after == before, "a bogus cross-link must not be persisted"


@pytest.mark.asyncio
async def test_successor_activity_in_wrong_schedule_is_422(http_client, two_schedules):
    """Successor activity actually lives in the PREDECESSOR schedule -> 422."""
    s = two_schedules
    resp = await http_client.post(
        "/api/v1/portfolio/cross-links/",
        json={
            "predecessor_schedule_id": s["pred_schedule_id"],
            "predecessor_activity_id": s["pred_activity_id"],
            "successor_schedule_id": s["succ_schedule_id"],
            # This activity belongs to the PREDECESSOR schedule, not the successor.
            "successor_activity_id": s["pred_activity_id"],
        },
        headers=s["headers"],
    )
    assert resp.status_code == 422, f"expected 422 for mismatched successor: {resp.status_code} {resp.text}"
    assert "successor_activity_id" in resp.text


@pytest.mark.asyncio
async def test_nonexistent_activity_is_422(http_client, two_schedules):
    """A predecessor activity id that does not exist at all -> 422 (not 500/404)."""
    s = two_schedules
    resp = await http_client.post(
        "/api/v1/portfolio/cross-links/",
        json={
            "predecessor_schedule_id": s["pred_schedule_id"],
            "predecessor_activity_id": str(uuid.uuid4()),  # never created
            "successor_schedule_id": s["succ_schedule_id"],
            "successor_activity_id": s["succ_activity_id"],
        },
        headers=s["headers"],
    )
    assert resp.status_code == 422, f"expected 422 for unknown activity: {resp.status_code} {resp.text}"
    assert "predecessor_activity_id" in resp.text
