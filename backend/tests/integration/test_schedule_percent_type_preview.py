# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Preview a percent-complete type change without applying it (T3.2).

The progress panel shows the EVM-distortion warnings of a type while the user
hovers it, before anything is committed. It called a preview route the backend
did not serve, and the only route that computed those warnings was the PUT that
also changes the type, so a hover would have rewritten the activity. This suite
drives the preview route end to end and proves it leaves the stored type alone,
and that the typed-progress response carries the unit quantities the panel
prefills its inputs from.
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

    email = f"pct-preview-{uuid.uuid4().hex[:8]}@schedule.io"
    password = f"PctPreview{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Percent Type Owner"},
    )
    assert reg.status_code in (200, 201), reg.text

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()

    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def activity(http_client):
    """One physical-type activity with no budgeted units, and its auth headers."""
    headers = await _register_login_admin(http_client)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Pct Preview {uuid.uuid4().hex[:6]}", "description": "percent type", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text

    sched = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": proj.json()["id"],
            "name": "Percent Type Schedule",
            "start_date": "2026-05-01",
            "end_date": "2026-09-30",
        },
        headers=headers,
    )
    assert sched.status_code == 201, sched.text

    act = await http_client.post(
        f"/api/v1/schedule/schedules/{sched.json()['id']}/activities/",
        json={
            "name": "Pour slab",
            "wbs_code": "01.01",
            "start_date": "2026-05-04",
            "end_date": "2026-05-15",
            "activity_type": "task",
        },
        headers=headers,
    )
    assert act.status_code == 201, act.text
    assert act.json()["percent_complete_type"] == "physical"
    return act.json()["id"], headers


async def _stored_type(client: AsyncClient, activity_id: str, headers: dict[str, str]) -> str:
    # The typed-progress PATCH with an empty body echoes the stored type back.
    resp = await client.patch(f"/api/v1/schedule/activities/{activity_id}/typed-progress/", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["percent_complete_type"]


@pytest.mark.asyncio
async def test_preview_returns_the_warnings_and_leaves_the_type_alone(http_client, activity):
    activity_id, headers = activity

    resp = await http_client.post(
        f"/api/v1/schedule/activities/{activity_id}/percent-type/preview/",
        json={"percent_complete_type": "units"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["percent_complete_type"] == "units"
    assert "units_type_without_budgeted_units" in body["evm_warnings"]

    assert await _stored_type(http_client, activity_id, headers) == "physical"


@pytest.mark.asyncio
async def test_the_put_still_commits_the_type_the_preview_did_not(http_client, activity):
    activity_id, headers = activity

    resp = await http_client.put(
        f"/api/v1/schedule/activities/{activity_id}/percent-type/",
        json={"percent_complete_type": "duration"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert await _stored_type(http_client, activity_id, headers) == "duration"


@pytest.mark.asyncio
async def test_preview_refuses_an_unknown_type(http_client, activity):
    activity_id, headers = activity

    resp = await http_client.post(
        f"/api/v1/schedule/activities/{activity_id}/percent-type/preview/",
        json={"percent_complete_type": "weighted"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_typed_progress_reports_the_stored_units(http_client, activity):
    activity_id, headers = activity

    resp = await http_client.patch(
        f"/api/v1/schedule/activities/{activity_id}/typed-progress/",
        json={"percent_complete_type": "units", "installed_units": "25", "budgeted_units": "100"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["percent_complete"] == 25.0
    # Decimal-as-string, so the panel can prefill both inputs and a later save
    # that edits only "installed" does not send "budgeted" back as zero.
    assert body["installed_units"] is not None and float(body["installed_units"]) == 25.0
    assert body["budgeted_units"] is not None and float(body["budgeted_units"]) == 100.0
    assert isinstance(body["budgeted_units"], str)
    assert body["suspended_at"] is None
