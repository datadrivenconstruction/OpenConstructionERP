"""Inspections IDOR regression suite.

The ``/api/v1/inspections/`` router exposes endpoints keyed off
``inspection_id``. Pre-fix several mutating endpoints fetched the
inspection by primary key and acted on it (state mutation, defect /
NCR creation in the inspection's parent project) without verifying
that the caller has access to the inspection's project. That lets
one tenant:

* ``POST /{id}/complete/``       — mutate another tenant's inspection
  (write IDOR — flips status to ``completed`` + sets the result).
* ``POST /{id}/create-defect/``  — inject a punchlist item into
  another tenant's project (write IDOR).
* ``POST /{id}/create-ncr/``     — inject an NCR into another
  tenant's project (write IDOR).

Convention (matches R5 sweep): cross-tenant access returns
**403/404**, never 2xx — so endpoints cannot be turned into a
UUID-existence oracle.

Read endpoints (``GET /{id}``, ``GET /``, ``GET /export/``) and
``PATCH``/``DELETE /{id}`` already call ``verify_project_access``;
regression guards live alongside the write-IDOR tests below to lock
the boundary in.

Scaffolding mirrors ``test_schedule_idor.py``: per-module temp
SQLite, registered BEFORE any ``from app...`` import (see
``feedback_test_isolation.md``).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-inspections-idor-"))
_TMP_DB = _TMP_DIR / "inspections_idor.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.inspections import models as _inspections_models  # noqa: F401
        from app.modules.ncr import models as _ncr_models  # noqa: F401
        from app.modules.punchlist import models as _punchlist_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_user(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _register_login_and_promote(
    client: AsyncClient,
    *,
    tenant: str,
    role: str = "viewer",
) -> tuple[str, str, str, dict[str, str]]:
    """Register a user, activate, optionally promote, return auth headers."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@inspections-idor.io"
    password = f"InspIdor{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), reg.text
    user_id = reg.json()["id"]

    await _activate_user(email)

    if role != "viewer":
        from sqlalchemy import update

        from app.database import async_session_factory
        from app.modules.users.models import User

        async with async_session_factory() as s:
            await s.execute(update(User).where(User.email == email.lower()).values(role=role))
            await s.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return user_id, email, password, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """A owns a project + inspection; B is the attacker."""
    _a_uid, _a_email, _a_password, a_headers = await _register_login_and_promote(
        http_client,
        tenant="a",
        role="admin",
    )
    # B is promoted to "editor" — it has inspections.update permission
    # (so the IDOR probe gets past ``RequirePermission`` and actually
    # exercises ``verify_project_access``) but is NOT admin (so the
    # admin-bypass branch inside ``verify_project_access`` doesn't
    # mask the cross-tenant guard we're testing).
    _b_uid, _b_email, _b_password, b_headers = await _register_login_and_promote(
        http_client,
        tenant="b",
        role="editor",
    )

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Inspections-A {uuid.uuid4().hex[:6]}",
            "description": "owned by A — used by inspections IDOR tests",
            "currency": "EUR",
        },
        headers=a_headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    ins = await http_client.post(
        "/api/v1/inspections/",
        json={
            "project_id": project_id,
            "inspection_type": "concrete_pour",
            "title": "A confidential foundation pour",
            "description": "A secret notes",
            "location": "A secret site",
            "checklist_data": [
                {"question": "Rebar OK?", "response": "fail", "critical": True},
            ],
        },
        headers=a_headers,
    )
    assert ins.status_code == 201, ins.text
    inspection_id = ins.json()["id"]

    return {
        "a": {
            "headers": a_headers,
            "project_id": project_id,
            "inspection_id": inspection_id,
        },
        "b": {"headers": b_headers},
    }


# ── Write IDOR vectors ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_complete_inspection(http_client, two_tenants):
    """``POST /{id}/complete/`` must NOT mutate A's inspection."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        f"/api/v1/inspections/{a['inspection_id']}/complete/",
        json={"result": "pass"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B completed A's inspection: {resp.status_code} {resp.text!r}"

    # Confirm A's inspection still in scheduled state (not flipped to completed by B).
    after = await http_client.get(
        f"/api/v1/inspections/{a['inspection_id']}",
        headers=a["headers"],
    )
    assert after.status_code == 200, after.text
    assert after.json()["status"] != "completed", (
        f"A's inspection was mutated by B's IDOR call: status={after.json()['status']}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_create_defect_from_inspection(http_client, two_tenants):
    """``POST /{id}/create-defect/`` must NOT inject into A's punchlist."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    # Owner first marks the inspection failed so the defect-creation path
    # would be allowed for the owner. Use a fresh failed inspection so the
    # earlier "still-scheduled" guard above stays valid.
    fresh = await http_client.post(
        "/api/v1/inspections/",
        json={
            "project_id": a["project_id"],
            "inspection_type": "concrete_pour",
            "title": "A failed pour — used for defect IDOR test",
            "checklist_data": [
                {"question": "Rebar OK?", "response": "fail", "critical": True},
            ],
        },
        headers=a["headers"],
    )
    assert fresh.status_code == 201, fresh.text
    fresh_id = fresh.json()["id"]

    # walk it scheduled → in_progress → completed/fail
    p1 = await http_client.patch(
        f"/api/v1/inspections/{fresh_id}",
        json={"status": "in_progress"},
        headers=a["headers"],
    )
    assert p1.status_code == 200, p1.text
    p2 = await http_client.post(
        f"/api/v1/inspections/{fresh_id}/complete/",
        json={"result": "fail"},
        headers=a["headers"],
    )
    assert p2.status_code == 200, p2.text

    resp = await http_client.post(
        f"/api/v1/inspections/{fresh_id}/create-defect/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B created punchlist item from A's inspection: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_create_ncr_from_inspection(http_client, two_tenants):
    """``POST /{id}/create-ncr/`` must NOT inject into A's NCR list."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    # Create a second fresh failed inspection so this test is independent
    # of the defect test above.
    fresh = await http_client.post(
        "/api/v1/inspections/",
        json={
            "project_id": a["project_id"],
            "inspection_type": "concrete_pour",
            "title": "A failed pour — used for NCR IDOR test",
            "checklist_data": [
                {"question": "Rebar OK?", "response": "fail", "critical": True},
            ],
        },
        headers=a["headers"],
    )
    assert fresh.status_code == 201, fresh.text
    fresh_id = fresh.json()["id"]
    p1 = await http_client.patch(
        f"/api/v1/inspections/{fresh_id}",
        json={"status": "in_progress"},
        headers=a["headers"],
    )
    assert p1.status_code == 200, p1.text
    p2 = await http_client.post(
        f"/api/v1/inspections/{fresh_id}/complete/",
        json={"result": "fail"},
        headers=a["headers"],
    )
    assert p2.status_code == 200, p2.text

    resp = await http_client.post(
        f"/api/v1/inspections/{fresh_id}/create-ncr/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B created NCR from A's inspection: {resp.status_code} {resp.text!r}"
    )


# ── Regression guards: cross-tenant read+list must remain blocked ──────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_read_inspection(http_client, two_tenants):
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/inspections/{a['inspection_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B read A's inspection: {resp.status_code} {resp.text!r}"
    assert "confidential" not in resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_list_a_inspections(http_client, two_tenants):
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/inspections/?project_id={a['project_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B listed A's inspections: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_export_a_inspections(http_client, two_tenants):
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/inspections/export/?project_id={a['project_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B exported A's inspections: {resp.status_code} {resp.text!r}"


# ── Owner regression: A must still be able to do everything ───────────────


@pytest.mark.asyncio
async def test_owner_can_still_complete_inspection(http_client, two_tenants):
    """End-to-end: A walks the FSM and completes their own inspection."""
    a = two_tenants["a"]

    # Use a fresh inspection so we don't depend on the order of other tests.
    fresh = await http_client.post(
        "/api/v1/inspections/",
        json={
            "project_id": a["project_id"],
            "inspection_type": "general",
            "title": "A owner-flow inspection",
        },
        headers=a["headers"],
    )
    assert fresh.status_code == 201, fresh.text
    fresh_id = fresh.json()["id"]

    p1 = await http_client.patch(
        f"/api/v1/inspections/{fresh_id}",
        json={"status": "in_progress"},
        headers=a["headers"],
    )
    assert p1.status_code == 200, p1.text

    p2 = await http_client.post(
        f"/api/v1/inspections/{fresh_id}/complete/",
        json={"result": "pass"},
        headers=a["headers"],
    )
    assert p2.status_code == 200, p2.text
    body = p2.json()
    assert body["status"] == "completed"
    assert body["result"] == "pass"
