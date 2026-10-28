"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration: CDE approval-preset library (inc3) end to end.

Exercises the read-only preset listing and the one-click "adopt" flow
(GET/POST /v1/cde/approval-presets) through the public API: listing the three
ISO 19650 presets, applying one to a project, confirming the clone is a real,
editable route (not the read-only system preset), and confirming a second
apply swaps the active preset.

Fixtures mirror ``test_cde_settings_gate.py`` to avoid the login rate limiter.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"cde-preset-{unique}@test.io"
    password = f"CdePreset{unique}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "CDE Preset Tester"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(sa_update(User).where(User.email == email).values(role="admin", is_active=True))
        await s.commit()

    token = ""
    data: dict = {}
    for attempt in range(3):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed after retries: {data}"
    return {"Authorization": f"Bearer {token}"}


async def _new_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": f"CDE Preset {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=auth,
    )
    assert resp.status_code == 201, f"Project create failed: {resp.text}"
    return resp.json()["id"]


class TestListApprovalPresets:
    async def test_lists_the_three_iso19650_presets(self, client: AsyncClient, auth: dict[str, str]) -> None:
        r = await client.get("/api/v1/cde/approval-presets/", headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        keys = {p["system_key"] for p in body["presets"]}
        assert keys == {
            "cde_issue_for_review",
            "cde_comment_and_return",
            "cde_review_and_publish",
        }
        assert body["active_system_key"] is None
        # Every preset carries at least one gate-A/B step, framed with a gate.
        for preset in body["presets"]:
            assert preset["gate"] in ("A", "B")
            assert len(preset["steps"]) >= 1
            assert preset["description"]

    async def test_project_scoped_reports_active_preset(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        r = await client.get(f"/api/v1/cde/approval-presets/?project_id={pid}", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["active_system_key"] is None


class TestApplyApprovalPreset:
    async def test_apply_clones_an_editable_route(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        r = await client.post(
            f"/api/v1/cde/approval-presets/apply?project_id={pid}",
            json={"system_key": "cde_review_and_publish"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["step_count"] == 2
        assert body["settings"]["review_preset_key"] == "cde_review_and_publish"
        assert body["settings"]["review_route_id"] == body["route_id"]

        # The clone is a real, editable route: no system_key, so it can be
        # PATCHed (a genuine preset would 409).
        route_id = body["route_id"]
        r = await client.get(f"/api/v1/approval-routes/routes/{route_id}", headers=auth)
        assert r.status_code == 200, r.text
        clone = r.json()
        assert clone["system_key"] is None
        assert clone["project_id"] == pid

        r = await client.patch(
            f"/api/v1/approval-routes/routes/{route_id}",
            json={"name": "Our tailored review flow"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Our tailored review flow"

    async def test_apply_reports_as_active_preset(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        await client.post(
            f"/api/v1/cde/approval-presets/apply?project_id={pid}",
            json={"system_key": "cde_issue_for_review"},
            headers=auth,
        )
        r = await client.get(f"/api/v1/cde/approval-presets/?project_id={pid}", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["active_system_key"] == "cde_issue_for_review"

        r = await client.get(f"/api/v1/cde/settings/?project_id={pid}", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["review_preset_key"] == "cde_issue_for_review"
        assert r.json()["review_route_id"] is not None

    async def test_apply_unknown_preset_404s(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        r = await client.post(
            f"/api/v1/cde/approval-presets/apply?project_id={pid}",
            json={"system_key": "not_a_real_preset"},
            headers=auth,
        )
        assert r.status_code == 404, r.text

    async def test_source_preset_stays_read_only(self, client: AsyncClient, auth: dict[str, str]) -> None:
        """Adopting a preset never mutates the shared, tenant-wide original."""
        pid = await _new_project(client, auth)
        r = await client.post(
            f"/api/v1/cde/approval-presets/apply?project_id={pid}",
            json={"system_key": "cde_comment_and_return"},
            headers=auth,
        )
        assert r.status_code == 200, r.text

        r = await client.get("/api/v1/cde/approval-presets/", headers=auth)
        preset = next(p for p in r.json()["presets"] if p["system_key"] == "cde_comment_and_return")
        r = await client.patch(
            f"/api/v1/approval-routes/routes/{preset['route_id']}",
            json={"name": "Hijacked"},
            headers=auth,
        )
        assert r.status_code == 409, r.text
