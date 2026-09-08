# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""HSE Advanced write-IDOR suite for the incident-keyed rows.

Most of ``/api/v1/hse-advanced/`` hangs off a model that carries its own
``project_id``, and every one of those routes resolves it through the
module's ``_guard_project`` helper. Two families do not: investigations
(``HSEIncidentInvestigation``) and the slim corrective actions
(``HSECorrectiveAction``) are keyed to a safety incident instead, and the
project has to be resolved through that link. The read routes did it. The
mutators did not, so they enforced the caller's *role* and nothing about
*whose project* the row belonged to:

* ``POST   /investigations/``                    - file a probe against
  another project's incident.
* ``PATCH  /investigations/{id}``                - overwrite another
  project's findings and recommendations.
* ``POST   /investigations/{id}/complete``       - close another project's
  regulatory record.
* ``POST   /investigations/{id}/abandon``        - kill it instead.
* ``POST   /corrective-actions/``                - inject an action into
  another project's incident.
* ``POST   /corrective-actions/{id}/transition`` - drive another project's
  action along the FSM.

Row level security is a deliberate no-op in this product, so
``verify_project_access`` is the only boundary between projects and its
absence is the whole vulnerability.

Two ways a suite like this reads green while proving nothing, both
addressed below:

* **The attacker is under-privileged.** ``hse_advanced.close_investigation``
  is MANAGER while ``hse_advanced.update`` is EDITOR, so an editor attacker
  is turned away by ``RequirePermission`` on ``/complete`` and ``/abandon``
  with a 403 - which is in the accepted set. B is therefore a *manager*: it
  outranks every permission under test, and it is not an admin, so the
  admin-bypass branch inside ``verify_project_access`` cannot stand in for
  the guard being measured.
* **The route is not mounted.** 404 is both the expected cross-project
  answer and what a mis-typed prefix returns. Every fixed route therefore
  also carries an owner-success control at the bottom of the file, run by B
  against B's *own* project so it exercises the non-admin owner path rather
  than the admin bypass.

Convention (matches the rest of the IDOR sweep): cross-project access
returns 403/404, never 2xx, so no endpoint becomes a UUID-existence oracle.

Scaffolding mirrors ``test_inspections_idor.py``: the suite runs on the
PostgreSQL cluster provisioned by ``tests/conftest.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

HSE = "/api/v1/hse-advanced"


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.hse_advanced import models as _hse_models  # noqa: F401
        from app.modules.safety import models as _safety_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_user_fields(email: str, **values) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(**values))
        await s.commit()


async def _register_login_and_promote(
    client: AsyncClient,
    *,
    tenant: str,
    role: str,
) -> dict[str, str]:
    """Register a user, activate it, promote it, return its auth headers."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@hse-idor.io"
    password = f"HseIdor{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), reg.text

    await _set_user_fields(email, is_active=True, role=role)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_project_with_incident(
    client: AsyncClient,
    headers: dict[str, str],
    label: str,
) -> tuple[str, str]:
    """A project plus one safety incident on it, both owned by ``headers``."""
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"HSE-{label} {uuid.uuid4().hex[:6]}",
            "description": f"owned by {label}, used by the HSE write-IDOR suite",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    inc = await client.post(
        "/api/v1/safety/incidents/",
        json={
            "project_id": project_id,
            "title": f"{label} scaffold collapse",
            "incident_date": "2026-05-04",
            "incident_type": "near_miss",
            "severity": "moderate",
            "description": f"{label} confidential incident narrative",
        },
        headers=headers,
    )
    assert inc.status_code == 201, inc.text
    return project_id, inc.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """A owns a project and an incident; B is a manager on a project of its own."""
    a_headers = await _register_login_and_promote(http_client, tenant="a", role="admin")
    # B is a manager, not an admin. Manager outranks every permission these
    # routes require (``hse_advanced.update`` is EDITOR,
    # ``hse_advanced.close_investigation`` is MANAGER) so each probe reaches
    # the project check instead of stopping at ``RequirePermission``, and it
    # misses the admin bypass inside ``verify_project_access``.
    b_headers = await _register_login_and_promote(http_client, tenant="b", role="manager")

    _a_project, a_incident = await _make_project_with_incident(http_client, a_headers, "A")
    _b_project, b_incident = await _make_project_with_incident(http_client, b_headers, "B")

    return {
        "a": {"headers": a_headers, "incident_id": a_incident},
        "b": {"headers": b_headers, "incident_id": b_incident},
    }


# ── Row builders ───────────────────────────────────────────────────────────


async def _new_investigation(
    client: AsyncClient,
    headers: dict[str, str],
    incident_id: str,
    findings: str,
) -> str:
    """A fresh in-progress investigation, minted by the incident's own tenant.

    Fresh per probe on purpose: ``/complete`` and ``/abandon`` both reject a
    terminal investigation with a 409, which is neither 2xx nor in the
    accepted (403, 404) set, so a shared row would let one probe decide the
    verdict of the next.
    """
    resp = await client.post(
        f"{HSE}/investigations/",
        json={
            "incident_ref": incident_id,
            "started_at": datetime.now(UTC).isoformat(),
            "method": "5_whys",
            "findings": findings,
            "recommendations": "Toolbox talk before the next lift.",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_corrective_action(
    client: AsyncClient,
    headers: dict[str, str],
    incident_id: str,
    description: str,
) -> str:
    resp = await client.post(
        f"{HSE}/corrective-actions/",
        json={"incident_id": incident_id, "description": description},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _read_investigation(client: AsyncClient, headers: dict[str, str], item_id: str) -> dict:
    resp = await client.get(f"{HSE}/investigations/{item_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Write IDOR vectors ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_b_cannot_open_an_investigation_on_a_incident(http_client, two_tenants):
    """``POST /investigations/`` must not accept another project's incident."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        f"{HSE}/investigations/",
        json={
            "incident_ref": a["incident_id"],
            "started_at": datetime.now(UTC).isoformat(),
            "method": "5_whys",
            "findings": "planted by B",
        },
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B opened an investigation on A's incident: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_b_cannot_patch_an_investigation_of_a(http_client, two_tenants):
    """``PATCH /investigations/{id}`` must not overwrite A's findings."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    original = "A confidential root cause: anchor bolts under-torqued"
    item_id = await _new_investigation(http_client, a["headers"], a["incident_id"], original)

    resp = await http_client.patch(
        f"{HSE}/investigations/{item_id}",
        json={"findings": "overwritten by B", "recommendations": "overwritten by B"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B patched A's investigation: {resp.status_code} {resp.text!r}"
    assert "confidential" not in resp.text

    after = await _read_investigation(http_client, a["headers"], item_id)
    assert after["findings"] == original, f"A's findings were overwritten by B: {after['findings']!r}"


@pytest.mark.asyncio
async def test_b_cannot_complete_an_investigation_of_a(http_client, two_tenants):
    """``POST /investigations/{id}/complete`` must not close A's record."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    item_id = await _new_investigation(http_client, a["headers"], a["incident_id"], "A completion probe")

    resp = await http_client.post(
        f"{HSE}/investigations/{item_id}/complete",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B completed A's investigation: {resp.status_code} {resp.text!r}"
    )

    after = await _read_investigation(http_client, a["headers"], item_id)
    assert after["status"] == "in_progress", f"A's investigation was closed by B: status={after['status']}"


@pytest.mark.asyncio
async def test_b_cannot_abandon_an_investigation_of_a(http_client, two_tenants):
    """``POST /investigations/{id}/abandon`` must not kill A's record."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    item_id = await _new_investigation(http_client, a["headers"], a["incident_id"], "A abandonment probe")

    resp = await http_client.post(
        f"{HSE}/investigations/{item_id}/abandon",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B abandoned A's investigation: {resp.status_code} {resp.text!r}"
    )

    after = await _read_investigation(http_client, a["headers"], item_id)
    assert after["status"] == "in_progress", f"A's investigation was abandoned by B: status={after['status']}"


@pytest.mark.asyncio
async def test_b_cannot_open_a_corrective_action_on_a_incident(http_client, two_tenants):
    """``POST /corrective-actions/`` must not accept another project's incident."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        f"{HSE}/corrective-actions/",
        json={"incident_id": a["incident_id"], "description": "planted by B"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B opened a corrective action on A's incident: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_b_cannot_transition_a_corrective_action_of_a(http_client, two_tenants):
    """``POST /corrective-actions/{id}/transition`` must not drive A's FSM.

    ``pending -> in_progress`` is the one legal hop from a fresh action, so a
    refusal here cannot be the FSM's 409 wearing the guard's clothes.
    """
    a = two_tenants["a"]
    b = two_tenants["b"]
    ca_id = await _new_corrective_action(
        http_client,
        a["headers"],
        a["incident_id"],
        "A confidential remedy: re-torque every anchor on level 3",
    )

    resp = await http_client.post(
        f"{HSE}/corrective-actions/{ca_id}/transition",
        json={"to_status": "in_progress"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B transitioned A's corrective action: {resp.status_code} {resp.text!r}"
    )
    assert "confidential" not in resp.text

    listed = await http_client.get(
        f"{HSE}/corrective-actions/?incident_id={a['incident_id']}",
        headers=a["headers"],
    )
    assert listed.status_code == 200, listed.text
    mine = [row for row in listed.json() if row["id"] == ca_id]
    assert mine and mine[0]["status"] == "pending", f"A's corrective action was moved by B: {mine}"


# ── Regression guard: the read boundary must stay shut ─────────────────────


@pytest.mark.asyncio
async def test_b_cannot_read_an_investigation_of_a(http_client, two_tenants):
    a = two_tenants["a"]
    b = two_tenants["b"]
    item_id = await _new_investigation(
        http_client,
        a["headers"],
        a["incident_id"],
        "A confidential read probe",
    )

    resp = await http_client.get(f"{HSE}/investigations/{item_id}", headers=b["headers"])
    assert resp.status_code in (403, 404), f"LEAK: B read A's investigation: {resp.status_code} {resp.text!r}"
    assert "confidential" not in resp.text


# ── Owner controls: every fixed route still works for its own project ──────
#
# These run as B, a plain manager on a project it owns, so they walk the
# owner branch of ``verify_project_access`` rather than the admin bypass.
# Without them a mis-typed prefix would answer 404 to every probe above and
# the whole suite would read as a pass.


@pytest.mark.asyncio
async def test_owner_can_open_and_patch_its_own_investigation(http_client, two_tenants):
    b = two_tenants["b"]

    item_id = await _new_investigation(http_client, b["headers"], b["incident_id"], "B own findings")

    patched = await http_client.patch(
        f"{HSE}/investigations/{item_id}",
        json={"findings": "B revised findings", "recommendations": "Re-brief the crew."},
        headers=b["headers"],
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["findings"] == "B revised findings"


@pytest.mark.asyncio
async def test_owner_can_complete_its_own_investigation(http_client, two_tenants):
    b = two_tenants["b"]
    item_id = await _new_investigation(http_client, b["headers"], b["incident_id"], "B completion flow")

    resp = await http_client.post(f"{HSE}/investigations/{item_id}/complete", headers=b["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_owner_can_abandon_its_own_investigation(http_client, two_tenants):
    b = two_tenants["b"]
    item_id = await _new_investigation(http_client, b["headers"], b["incident_id"], "B abandonment flow")

    resp = await http_client.post(f"{HSE}/investigations/{item_id}/abandon", headers=b["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "abandoned"


@pytest.mark.asyncio
async def test_owner_can_open_and_transition_its_own_corrective_action(http_client, two_tenants):
    b = two_tenants["b"]
    ca_id = await _new_corrective_action(http_client, b["headers"], b["incident_id"], "B own remedy")

    resp = await http_client.post(
        f"{HSE}/corrective-actions/{ca_id}/transition",
        json={"to_status": "in_progress"},
        headers=b["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "in_progress"
