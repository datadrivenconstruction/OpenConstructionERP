"""Reporting IDOR regression suite (v2.4.0 slice A — task #177).

The ``/api/v1/reporting/`` router exposes endpoints keyed off
``project_id``, ``template_id``, and ``report_id``. Every endpoint that
returns or mutates project-scoped data MUST verify the requesting user
has access to the parent project — otherwise one tenant can enumerate
KPI snapshots, download reports, or hijack scheduled templates that
belong to another tenant.

Convention: cross-tenant access returns **404 Not Found**, not 403 —
matching ``verify_project_access`` so endpoints can't be turned into a
UUID-existence oracle.

This module pins the boundary at the HTTP layer so any future
regression surfaces as a red test rather than a customer-reported leak.

Coverage
~~~~~~~~

* ``GET /reports/{report_id}`` — primary IDOR vector. Pre-fix the
  router fetched the report by primary key with no project gate, so
  tenant B could download tenant A's PDF if they guessed (or
  enumerated) the UUID.
* ``GET /kpi/?project_id=X`` — query-param vector; gate is on
  ``verify_project_access``.
* ``POST /templates/{template_id}/schedule/`` — write IDOR. Pre-fix
  the router only validated the *new* ``project_id_scope``, leaving a
  hole where an attacker could re-target someone else's template by
  cleared their schedule.
* ``GET /templates/scheduled/`` — list-leak vector. Pre-fix the router
  returned every scheduled template regardless of ownership.

Test scaffolding mirrors ``test_tenant_isolation.py``: per-module temp
SQLite, registered before any ``from app...`` import (see
``feedback_test_isolation.md``).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-reporting-idor-"))
_TMP_DB = _TMP_DIR / "reporting_idor.db"
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
        # Reporting tables are wired by ``app.main`` startup but we
        # backfill defensively in case the import-order ever shifts.
        from app.database import Base, engine
        from app.modules.reporting import models as _reporting_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_user(email: str) -> None:
    """Flip ``is_active=True`` on a registered user.

    Self-registered accounts default to inactive in admin-approve mode
    (v2.5.2+, BUG-RBAC03). Tests bypass the policy via direct DB write
    to stay focused on the cross-tenant access invariant.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(
            update(User).where(User.email == email.lower()).values(is_active=True)
        )
        await s.commit()


async def _register_and_login(
    client: AsyncClient,
    *,
    tenant: str,
) -> tuple[str, str, str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@reporting-idor.io"
    password = f"ReportingIdor{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), (
        f"register failed for {tenant}: {reg.status_code} {reg.text}"
    )
    user_id = reg.json()["id"]

    await _activate_user(email)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {tenant}: {login.text}"
    token = login.json()["access_token"]
    return user_id, email, password, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def two_reporting_tenants(http_client):
    """A owns a project + report + scheduled template; B is the attacker.

    A is promoted to admin so they can create projects via the public
    API (registration drops new accounts to ``viewer``, which lacks
    ``projects.create``). B is left as a viewer.
    """
    a_uid, a_email, a_password, a_headers = await _register_and_login(
        http_client, tenant="a",
    )
    b_uid, b_email, _b_password, b_headers = await _register_and_login(
        http_client, tenant="b",
    )

    # Promote A so they can hit ``POST /projects/`` (admin role grants
    # all permissions in the registry). B stays a viewer.
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(
            update(User)
            .where(User.email == a_email.lower())
            .values(role="admin", is_active=True)
        )
        await s.commit()

    # Re-login A so the JWT carries the freshly-promoted admin role.
    a_login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": a_email, "password": a_password},
    )
    assert a_login.status_code == 200, a_login.text
    a_headers = {"Authorization": f"Bearer {a_login.json()['access_token']}"}

    # ── A creates a project (HTTP path so the project owner_id matches A)
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Reporting-A {uuid.uuid4().hex[:6]}",
            "description": "owned by A — used by reporting IDOR tests",
            "currency": "EUR",
        },
        headers=a_headers,
    )
    assert proj.status_code == 201, f"project create failed: {proj.text}"
    project_id = proj.json()["id"]

    # ── Seed a generated report + a scheduled template DIRECTLY in the
    # DB. Going through ``POST /reporting/generate`` works but pulls in
    # the entire render pipeline which is overkill for an audit. The
    # important invariant is that the row exists with the right
    # ``project_id``, not how the row got there.
    from app.modules.reporting.models import GeneratedReport, ReportTemplate

    report_id = uuid.uuid4()
    template_id = uuid.uuid4()
    async with async_session_factory() as s:
        report = GeneratedReport(
            id=report_id,
            project_id=uuid.UUID(project_id),
            template_id=None,
            report_type="project_status",
            title="A's confidential status report",
            generated_at="2026-04-27T00:00:00",
            generated_by=uuid.UUID(a_uid),
            format="pdf",
            data_snapshot={"secret": "do not leak"},
            metadata_={},
        )
        s.add(report)

        template = ReportTemplate(
            id=template_id,
            name=f"A's scheduled template {uuid.uuid4().hex[:6]}",
            report_type="project_status",
            description="scoped to A's project",
            template_data={},
            is_system=False,
            created_by=uuid.UUID(a_uid),
            recipients=["a@example.com"],
            schedule_cron="0 9 * * 1",
            is_scheduled=True,
            next_run_at="2099-01-01T09:00:00Z",
            project_id_scope=uuid.UUID(project_id),
            metadata_={},
        )
        s.add(template)
        await s.commit()

    return {
        "a": {
            "user_id": a_uid,
            "email": a_email,
            "headers": a_headers,
            "project_id": project_id,
            "report_id": str(report_id),
            "template_id": str(template_id),
        },
        "b": {
            "user_id": b_uid,
            "email": b_email,
            "headers": b_headers,
        },
    }


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_get_tenant_a_report(http_client, two_reporting_tenants):
    """``GET /reporting/reports/{report_id}`` must NOT leak A's report.

    Primary IDOR fix: pre-fix the route fetched the report by primary
    key with no project gate.
    """
    a = two_reporting_tenants["a"]
    b = two_reporting_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/reporting/reports/{a['report_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} on tenant A's "
        f"generated report. Body: {resp.text!r}"
    )
    # Belt-and-braces: even if the status code is somehow a non-error
    # variant, the body must not contain A's secret payload.
    assert "do not leak" not in resp.text, (
        f"LEAK: tenant B's response contains A's confidential snapshot: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_a_can_still_get_own_report(http_client, two_reporting_tenants):
    """Regression guard: the IDOR fix must not block A's own access."""
    a = two_reporting_tenants["a"]

    resp = await http_client.get(
        f"/api/v1/reporting/reports/{a['report_id']}",
        headers=a["headers"],
    )
    assert resp.status_code == 200, (
        f"REGRESSION: tenant A got {resp.status_code} on their OWN report. "
        f"Body: {resp.text!r}"
    )
    body = resp.json()
    assert body["id"] == a["report_id"]


@pytest.mark.asyncio
async def test_tenant_b_cannot_get_tenant_a_kpi(http_client, two_reporting_tenants):
    """``GET /reporting/kpi/?project_id=X`` must reject foreign project_id."""
    a = two_reporting_tenants["a"]
    b = two_reporting_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/reporting/kpi/?project_id={a['project_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} on tenant A's "
        f"latest KPI. Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_list_tenant_a_kpi_history(
    http_client, two_reporting_tenants,
):
    """``GET /reporting/kpi/history/?project_id=X`` must reject foreign id."""
    a = two_reporting_tenants["a"]
    b = two_reporting_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/reporting/kpi/history/?project_id={a['project_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} on tenant A's "
        f"KPI history. Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_list_tenant_a_reports(
    http_client, two_reporting_tenants,
):
    """``GET /reporting/reports/?project_id=X`` must reject foreign id."""
    a = two_reporting_tenants["a"]
    b = two_reporting_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/reporting/reports/?project_id={a['project_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} listing tenant A's "
        f"reports. Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_reschedule_tenant_a_template(
    http_client, two_reporting_tenants,
):
    """``POST /reporting/templates/{id}/schedule/`` must reject foreign templates.

    Pre-fix only the *new* ``project_id_scope`` was validated, so a
    viewer could re-target any template (clearing its schedule, or
    pointing it at one of their own projects). The fix gates on the
    EXISTING ``project_id_scope`` first.
    """
    a = two_reporting_tenants["a"]
    b = two_reporting_tenants["b"]

    # Try to clear A's template schedule from B's account.
    resp = await http_client.post(
        f"/api/v1/reporting/templates/{a['template_id']}/schedule/",
        json={
            "schedule_cron": None,
            "recipients": [],
            "is_scheduled": False,
            "project_id_scope": None,
        },
        headers=b["headers"],
    )
    assert resp.status_code in (401, 403, 404), (
        f"LEAK: tenant B was able to mutate tenant A's scheduled template "
        f"(status {resp.status_code}). Body: {resp.text!r}"
    )

    # Defensive: confirm the schedule was NOT actually cleared on A's row.
    from app.database import async_session_factory
    from app.modules.reporting.models import ReportTemplate

    async with async_session_factory() as s:
        tmpl = await s.get(ReportTemplate, uuid.UUID(a["template_id"]))
        assert tmpl is not None
        assert tmpl.is_scheduled is True, (
            "tenant B's schedule call actually cleared tenant A's template"
        )
        assert tmpl.schedule_cron == "0 9 * * 1", (
            "tenant B's schedule call mutated tenant A's cron expression"
        )


@pytest.mark.asyncio
async def test_tenant_b_scheduled_templates_excludes_tenant_a(
    http_client, two_reporting_tenants,
):
    """``GET /reporting/templates/scheduled/`` must filter out A's templates.

    Pre-fix the endpoint returned every scheduled template regardless
    of ``project_id_scope`` ownership, leaking project UUIDs and
    recipient email lists across tenants.
    """
    a = two_reporting_tenants["a"]
    b = two_reporting_tenants["b"]

    resp = await http_client.get(
        "/api/v1/reporting/templates/scheduled/",
        headers=b["headers"],
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    leaked = [t for t in items if t.get("id") == a["template_id"]]
    assert leaked == [], (
        f"LEAK: tenant B's scheduled-template list contains tenant A's "
        f"project-scoped template: {leaked!r}"
    )
