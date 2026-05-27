"""Regression: ``/critical-path/`` must order activities by integer day offset.

The CPM engine populates ``Activity.early_start`` as integer day-offsets
serialised into a ``String(20)`` column (``"0"``, ``"1"``, ``"10"``, ``"2"``…).
A plain SQL ``ORDER BY early_start`` does a lexicographic sort, so for any
schedule with more than 9 critical activities the order is wrong:
``"0" < "1" < "10" < "11" < "2"`` instead of ``0 < 1 < 2 < … < 10 < 11``.

This test seeds a schedule with > 9 critical activities at known integer ES
values and asserts the endpoint returns them in true numeric order.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-schedule-cp-order-"))
_TMP_DB = _TMP_DIR / "schedule_cp_order.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


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

    email = f"cp-order-{uuid.uuid4().hex[:8]}@schedule.io"
    password = f"CpOrder{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "CP Order Owner"},
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


@pytest.mark.asyncio
async def test_critical_path_orders_by_integer_day_offset(http_client):
    """Critical-path endpoint must sort by *numeric* ``early_start``.

    Pre-fix: the activity with ``early_start="10"`` would appear between
    ``"1"`` and ``"2"`` (lex sort). Post-fix it must come after ``"9"``.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.schedule.models import Activity

    headers = await _register_login_admin(http_client)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"CP Order {uuid.uuid4().hex[:6]}",
            "description": "schedule critical-path ordering regression",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    sched = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": project_id,
            "name": "CP Order Schedule",
            "start_date": "2026-05-01",
            "end_date": "2026-09-30",
        },
        headers=headers,
    )
    assert sched.status_code == 201, sched.text
    schedule_id = sched.json()["id"]

    # Create 12 critical activities. Insert them with sort_order in reverse
    # so we know the SQL is actually using the early_start column, not
    # accidentally falling back to insertion order.
    es_values = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    created_ids: list[str] = []
    for i, es in enumerate(es_values):
        act = await http_client.post(
            f"/api/v1/schedule/schedules/{schedule_id}/activities/",
            json={
                "name": f"Critical ES={es}",
                "wbs_code": f"01.{i + 1:02d}",
                "start_date": "2026-05-04",
                "end_date": "2026-05-15",
                "activity_type": "task",
                "sort_order": len(es_values) - i,  # reverse
            },
            headers=headers,
        )
        assert act.status_code == 201, act.text
        created_ids.append(act.json()["id"])

    # Force-set the CPM-result fields directly. The CPM engine would
    # normally do this — we skip its compute and stamp the values we need
    # to provoke the lex-vs-numeric ordering ambiguity.
    async with async_session_factory() as s:
        for aid, es in zip(created_ids, es_values, strict=True):
            await s.execute(
                update(Activity)
                .where(Activity.id == uuid.UUID(aid))
                .values(
                    early_start=str(es),
                    early_finish=str(es + 1),
                    late_start=str(es),
                    late_finish=str(es + 1),
                    total_float=0,
                    free_float=0,
                    is_critical=True,
                )
            )
        await s.commit()

    resp = await http_client.get(
        f"/api/v1/schedule/critical-path/?schedule_id={schedule_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == len(es_values), body

    returned_es = [int(a["early_start"]) for a in body]
    assert returned_es == sorted(es_values), (
        f"critical-path order is broken: expected {sorted(es_values)} but "
        f"got {returned_es}. Lexicographic SQL sort would give "
        f"[0,1,10,11,2,3,4,5,6,7,8,9]."
    )
