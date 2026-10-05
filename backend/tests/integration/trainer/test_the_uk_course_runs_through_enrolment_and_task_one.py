# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP: the real UK course loads, seeds and opens task 1 (skipped without the files).

Real course files never enter the repository (decision 17). Point
``OE_TRAINER_COURSES_DIR`` at them to run this. A UK course that is stored
invalid fails here with its error list rather than skipping, so an author
error never reads as green.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

COURSES_DIR = os.environ.get("OE_TRAINER_COURSES_DIR", "")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not COURSES_DIR or not Path(COURSES_DIR).is_dir(), reason="OE_TRAINER_COURSES_DIR is not set"),
]

API = "/api/v1/trainer"


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncIterator[AsyncClient]:
    from app.config import get_settings

    previous = os.environ.get("OE_ACADEMY_MODE")
    os.environ["OE_ACADEMY_MODE"] = "true"
    get_settings.cache_clear()
    try:
        from app.main import create_app

        app = create_app()
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac,
        ):
            yield ac
    finally:
        if previous is None:
            os.environ.pop("OE_ACADEMY_MODE", None)
        else:
            os.environ["OE_ACADEMY_MODE"] = previous
        get_settings.cache_clear()


async def _uk_course() -> Any:
    from app.database import async_session_factory
    from app.modules.trainer.models import TrainerCourse

    names = {p.name for p in Path(COURSES_DIR).glob("course_*_v*.json")}
    async with async_session_factory() as session:
        rows = (await session.execute(select(TrainerCourse).where(TrainerCourse.country == "GB"))).scalars().all()
    rows = [r for r in rows if r.source_file in names]
    assert rows, f"no GB course among {sorted(names)}"
    row = max(rows, key=lambda r: r.loaded_at)
    assert row.status == "active", f"{row.source_file} is stored invalid: {row.validation_report.get('error_list')}"
    return row


async def _token(email: str) -> dict[str, str]:
    from app.config import get_settings
    from app.database import async_session_factory
    from app.modules.users.models import User
    from app.modules.users.service import create_access_token

    async with async_session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        return {"Authorization": f"Bearer {create_access_token(user, get_settings())}"}


async def test_the_uk_course_enrols_and_task_one_fails_on_the_untouched_project(client: AsyncClient) -> None:
    from app.database import async_session_factory
    from app.modules.users.models import User

    course = await _uk_course()
    admin_email = f"uk-admin-{uuid.uuid4().hex[:8]}@test.io"
    async with async_session_factory() as session:
        session.add(User(id=uuid.uuid4(), email=admin_email, hashed_password="x", role="admin", is_active=True))
        await session.commit()
    admin = await _token(admin_email)

    email = f"uk-learner-{uuid.uuid4().hex[:8]}@test.io"
    created = await client.post(
        f"{API}/admin/enrolments/",
        json={"email": email, "full_name": "UK Learner", "course_key": course.course_key, "locale": "en"},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "active", created.json()
    auth = await _token(email)

    me = await client.get(f"{API}/me", headers=auth)
    assert me.status_code == 200, me.text
    first = me.json()["tasks"][0]
    assert first["status"] == "not_started"
    assert first["target"] is not None

    view = await client.get(f"{API}/tasks/{first['id']}", headers=auth)
    assert view.status_code == 200, view.text
    assert '"correct"' not in view.text
    readback = await client.get(f"{API}/tasks/{first['id']}/readback", headers=auth)
    assert readback.status_code == 200, readback.text

    choice = next(c for c in view.json()["checks"] if c["kind"] in ("trace", "explain"))
    saved = await client.put(
        f"{API}/tasks/{first['id']}/answers",
        json={"revision": 0, "answers": [{"name": choice["id"], "option_index": 0}]},
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    checked = await client.post(
        f"{API}/tasks/{first['id']}/check",
        json={"client_attempt_id": str(uuid.uuid4()), "revision": saved.json()["revision"]},
        headers=auth,
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["graded_items"] > 0
    assert checked.json()["verdict"] == "fail", "the seeded project alone must not pass task 1"
