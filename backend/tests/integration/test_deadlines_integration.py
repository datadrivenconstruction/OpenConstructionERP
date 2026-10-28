"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cross-module deadline register + sweep integration suite (item #18).

Exercises the real aggregation path end to end against the shared
``tests/conftest.py`` embedded-PostgreSQL cluster:

* the register endpoint aggregates overdue/approaching items from
  correspondence + NCR actions + punch items, scoped to one project;
* the status filter and empty/steady-state behaviour;
* IDOR: a stranger cannot read a foreign project's register;
* the sweep notifies the owner once and dedups within the renotify window.

NOTE: this suite requires a database (it boots the embedded cluster via the
shared conftest). It was authored alongside the DB-free unit tests
(``tests/unit/test_deadlines_logic.py`` + ``tests/unit/test_deadlines_imports.py``)
but, per the build constraints, only the DB-free unit tests were executed by the
author; run this suite with the embedded cluster to validate the query layer.

Run:
    cd backend
    python -m pytest tests/integration/test_deadlines_integration.py -q
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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

        # Import every model we seed so create_all sees the tables (the module
        # loader already imports these at startup; belt-and-suspenders here).
        from app.modules.correspondence import models as _corr  # noqa: F401
        from app.modules.notifications import models as _notif  # noqa: F401
        from app.modules.projects import models as _proj  # noqa: F401
        from app.modules.punchlist import models as _punch  # noqa: F401
        from app.modules.qms import models as _qms  # noqa: F401
        from app.modules.users import models as _users  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Auth + project helpers (mirror test_service_idor) ───────────────────────


async def _register(client: AsyncClient, label: str) -> tuple[str, str]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@deadlines.io"
    password = f"Deadl{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _user_id(email: str) -> uuid.UUID:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        return (await s.execute(select(User.id).where(User.email == email.lower()))).scalar_one()


async def _make_project(client: AsyncClient, headers: dict[str, str], label: str) -> str:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"{label}-{uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return proj.json()["id"]


# ── Source seeding helpers (direct ORM, the models we read in full) ─────────


def _iso_days_from_now(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).date().isoformat()


async def _seed_punch(project_id: str, *, due_days: int, status: str = "open", assigned_to: str | None = None) -> str:
    from app.database import async_session_factory
    from app.modules.punchlist.models import PunchItem

    async with async_session_factory() as s:
        item = PunchItem(
            project_id=uuid.UUID(project_id),
            title="Seal roof penetration",
            description="",
            status=status,
            assigned_to=assigned_to,
            due_date=datetime.now(UTC) + timedelta(days=due_days),
        )
        s.add(item)
        await s.commit()
        return str(item.id)


async def _seed_correspondence(project_id: str, *, due_days: int, status: str = "open") -> str:
    from app.database import async_session_factory
    from app.modules.correspondence.models import Correspondence

    async with async_session_factory() as s:
        item = Correspondence(
            project_id=uuid.UUID(project_id),
            reference_number=f"COR-{uuid.uuid4().hex[:6]}",
            direction="incoming",
            subject="Reply to variation notice",
            correspondence_type="notice",
            status=status,
            response_required_by=_iso_days_from_now(due_days),
        )
        s.add(item)
        await s.commit()
        return str(item.id)


async def _seed_ncr_action(
    project_id: str, *, due_days: int, status: str = "assigned", responsible_user_id: str | None = None
) -> str:
    from app.database import async_session_factory
    from app.modules.qms.models import QMSNCR, QMSNCRAction

    async with async_session_factory() as s:
        ncr = QMSNCR(
            project_id=uuid.UUID(project_id),
            title="Rebar cover non-conformance",
            description="Cover below tolerance",
            status="action_pending",
        )
        s.add(ncr)
        await s.flush()
        action = QMSNCRAction(
            ncr_id=ncr.id,
            description="Re-pour affected section",
            responsible_user_id=uuid.UUID(responsible_user_id) if responsible_user_id else None,
            status=status,
            due_date=(datetime.now(UTC) + timedelta(days=due_days)).isoformat(),
        )
        s.add(action)
        await s.commit()
        return str(action.id)


async def _count_notifications(user_id: uuid.UUID, entity_id: str, ntype: str) -> int:
    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.notifications.models import Notification

    async with async_session_factory() as s:
        return (
            await s.execute(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.entity_id == entity_id,
                    Notification.notification_type == ntype,
                )
            )
        ).scalar_one()


@pytest_asyncio.fixture(scope="module")
async def admin(http_client):
    email, password = await _register(http_client, "owner")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, password)
    return {"email": email, "headers": headers, "id": await _user_id(email)}


# ── Register endpoint ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_aggregates_overdue_across_sources(http_client, admin):
    project_id = await _make_project(http_client, admin["headers"], "agg")
    await _seed_punch(project_id, due_days=-2)
    await _seed_correspondence(project_id, due_days=-5)
    await _seed_ncr_action(project_id, due_days=-3)

    resp = await http_client.get(f"/api/v1/deadlines/?project_id={project_id}", headers=admin["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    modules = {it["module"] for it in body["items"]}
    assert modules == {"correspondence", "qms_ncr_action", "punchlist"}
    assert body["overdue_count"] == 3
    assert all(it["classification"] == "overdue" for it in body["items"])


@pytest.mark.asyncio
async def test_status_filter_returns_only_overdue(http_client, admin):
    project_id = await _make_project(http_client, admin["headers"], "filter")
    await _seed_punch(project_id, due_days=-1)  # overdue
    await _seed_punch(project_id, due_days=2)  # approaching (within default 3d)

    resp = await http_client.get(f"/api/v1/deadlines/?project_id={project_id}&status=overdue", headers=admin["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [it["classification"] for it in body["items"]] == ["overdue"]
    # Counts stay stable (pre-filter) so the KPI chips do not jump.
    assert body["overdue_count"] == 1
    assert body["approaching_count"] == 1


@pytest.mark.asyncio
async def test_empty_project_returns_200(http_client, admin):
    project_id = await _make_project(http_client, admin["headers"], "empty")
    resp = await http_client.get(f"/api/v1/deadlines/?project_id={project_id}", headers=admin["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["overdue_count"] == 0


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_project_scope_excludes_other_project(http_client, admin):
    project_a = await _make_project(http_client, admin["headers"], "scope-a")
    project_b = await _make_project(http_client, admin["headers"], "scope-b")
    punch_b = await _seed_punch(project_b, due_days=-4)

    resp = await http_client.get(f"/api/v1/deadlines/?project_id={project_a}", headers=admin["headers"])
    assert resp.status_code == 200, resp.text
    assert punch_b not in resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_stranger_cannot_read_foreign_register(http_client, admin):
    project_id = await _make_project(http_client, admin["headers"], "idor")
    await _seed_punch(project_id, due_days=-2)

    s_email, s_password = await _register(http_client, "stranger")
    await _set_role(s_email, "manager")  # clears RBAC; denial must be the scope guard
    s_headers = await _login(http_client, s_email, s_password)

    resp = await http_client.get(f"/api/v1/deadlines/?project_id={project_id}", headers=s_headers)
    assert resp.status_code == 404, resp.text


# ── Sweep endpoint ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sweep_notifies_owner_and_dedups(http_client, admin):
    project_id = await _make_project(http_client, admin["headers"], "sweep")
    owner_id = admin["id"]
    punch_id = await _seed_punch(project_id, due_days=-2, assigned_to=str(owner_id))

    first = await http_client.post("/api/v1/deadlines/sweep", json={}, headers=admin["headers"])
    assert first.status_code == 200, first.text
    assert await _count_notifications(owner_id, punch_id, "deadline_overdue") == 1

    # Second tick within the renotify window creates no second notification.
    second = await http_client.post("/api/v1/deadlines/sweep", json={}, headers=admin["headers"])
    assert second.status_code == 200, second.text
    assert await _count_notifications(owner_id, punch_id, "deadline_overdue") == 1
