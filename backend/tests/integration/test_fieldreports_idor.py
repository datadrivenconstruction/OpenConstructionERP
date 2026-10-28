"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Field Reports IDOR regression suite.

The ``/api/v1/fieldreports/`` router exposes several endpoints keyed off
an unscoped resource id (``entry_id`` for workforce / equipment logs,
``report_id`` for the parent report).  Several of them historically
skipped the project-ownership gate that ``verify_project_access``
applies on the report-CRUD endpoints, letting one tenant enumerate (and
in some cases mutate) another tenant's site-log entries:

* ``GET    /reports/{report_id}/workforce/``         — list-leak via
  parent ``report_id`` (no ownership check at all).
* ``POST   /reports/{report_id}/workforce/``         — write-IDOR
  (creates rows on another tenant's report).
* ``PATCH  /workforce/{entry_id}``                    — write-IDOR via
  unscoped row id.
* ``DELETE /workforce/{entry_id}``                    — destructive
  cross-tenant delete via unscoped row id.
* ``GET    /reports/{report_id}/equipment/``         — equipment-side
  twin of the workforce list-leak.
* ``POST   /reports/{report_id}/equipment/``         — write-IDOR.
* ``PATCH  /equipment/{entry_id}``                    — write-IDOR.
* ``DELETE /equipment/{entry_id}``                    — destructive
  cross-tenant delete.

Convention: cross-tenant access returns **403/404**, never a 2xx —
matching ``verify_project_access`` so endpoints can't be turned into a
UUID-existence oracle.

Scaffolding mirrors ``test_schedule_idor.py``: the engine is bound to the
shared PostgreSQL cluster that ``conftest.py`` provisions before any test
module imports.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.fieldreports import models as _fr_models  # noqa: F401

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


async def _promote_admin(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()


async def _promote_editor(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="editor", is_active=True))
        await s.commit()


async def _register_and_login(
    client: AsyncClient,
    *,
    tenant: str,
) -> tuple[str, str, str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@fieldreports-idor.io"
    password = f"FieldReportsIdor{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    user_id = reg.json()["id"]

    await _activate_user(email)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {tenant}: {login.text}"
    token = login.json()["access_token"]
    return user_id, email, password, {"Authorization": f"Bearer {token}"}


async def _refresh_token(
    client: AsyncClient,
    *,
    email: str,
    password: str,
) -> dict[str, str]:
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def two_fr_tenants(http_client):
    """A owns a project + report + workforce + equipment entries; B is the attacker.

    Tenant B is promoted to ``editor`` so they hold every
    ``fieldreports.*`` permission used by the audited endpoints; that
    way the IDOR test exercises the ownership gate, not the role gate.
    """
    a_uid, a_email, a_password, _a_headers0 = await _register_and_login(
        http_client,
        tenant="a",
    )
    b_uid, b_email, b_password, _b_headers0 = await _register_and_login(
        http_client,
        tenant="b",
    )

    await _promote_admin(a_email)
    await _promote_editor(b_email)

    a_headers = await _refresh_token(http_client, email=a_email, password=a_password)
    b_headers = await _refresh_token(http_client, email=b_email, password=b_password)

    # A creates a project. B has its own project so the role gate sees a
    # legitimate workspace if it ever checked one.
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"FR-A {uuid.uuid4().hex[:6]}",
            "description": "owned by A — used by fieldreports IDOR tests",
            "currency": "EUR",
        },
        headers=a_headers,
    )
    assert proj.status_code == 201, f"project create failed: {proj.text}"
    project_id = proj.json()["id"]

    # A creates a field report.
    report = await http_client.post(
        "/api/v1/fieldreports/reports/",
        json={
            "project_id": project_id,
            "report_date": "2026-05-22",
            "work_performed": "A confidential foundation pour",
        },
        headers=a_headers,
    )
    assert report.status_code == 201, f"report create failed: {report.text}"
    report_id = report.json()["id"]

    # A creates a workforce log entry on that report.
    wf = await http_client.post(
        f"/api/v1/fieldreports/reports/{report_id}/workforce/",
        json={
            "field_report_id": report_id,
            "worker_type": "Concrete-A-secret",
            "company": "A Confidential GmbH",
            "headcount": 7,
            "hours_worked": "8",
            "overtime_hours": "1",
        },
        headers=a_headers,
    )
    assert wf.status_code == 201, f"workforce create failed: {wf.text}"
    workforce_id = wf.json()["id"]

    # A creates an equipment log entry on that report.
    eq = await http_client.post(
        f"/api/v1/fieldreports/reports/{report_id}/equipment/",
        json={
            "field_report_id": report_id,
            "equipment_description": "A confidential Liebherr crane",
            "equipment_type": "crane",
            "hours_operational": "6",
            "hours_standby": "1",
            "hours_breakdown": "0",
        },
        headers=a_headers,
    )
    assert eq.status_code == 201, f"equipment create failed: {eq.text}"
    equipment_id = eq.json()["id"]

    return {
        "a": {
            "headers": a_headers,
            "project_id": project_id,
            "report_id": report_id,
            "workforce_id": workforce_id,
            "equipment_id": equipment_id,
        },
        "b": {
            "user_id": b_uid,
            "email": b_email,
            "headers": b_headers,
        },
    }


# ── Read-leak vectors ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_list_workforce_logs(http_client, two_fr_tenants):
    a = two_fr_tenants["a"]
    b = two_fr_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/fieldreports/reports/{a['report_id']}/workforce/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B listed A's workforce logs: {resp.status_code} {resp.text!r}"
    assert "A-secret" not in resp.text
    assert "Confidential" not in resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_list_equipment_logs(http_client, two_fr_tenants):
    a = two_fr_tenants["a"]
    b = two_fr_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/fieldreports/reports/{a['report_id']}/equipment/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B listed A's equipment logs: {resp.status_code} {resp.text!r}"
    assert "Liebherr" not in resp.text
    assert "confidential" not in resp.text


# ── Write-IDOR vectors ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_create_workforce_on_a_report(
    http_client,
    two_fr_tenants,
):
    a = two_fr_tenants["a"]
    b = two_fr_tenants["b"]

    resp = await http_client.post(
        f"/api/v1/fieldreports/reports/{a['report_id']}/workforce/",
        json={
            "field_report_id": a["report_id"],
            "worker_type": "B-injected",
            "headcount": 99,
            "hours_worked": "8",
            "overtime_hours": "0",
        },
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B injected workforce on A's report: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_create_equipment_on_a_report(
    http_client,
    two_fr_tenants,
):
    a = two_fr_tenants["a"]
    b = two_fr_tenants["b"]

    resp = await http_client.post(
        f"/api/v1/fieldreports/reports/{a['report_id']}/equipment/",
        json={
            "field_report_id": a["report_id"],
            "equipment_description": "B-injected excavator",
            "hours_operational": "8",
            "hours_standby": "0",
            "hours_breakdown": "0",
        },
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B injected equipment on A's report: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_update_workforce_entry(
    http_client,
    two_fr_tenants,
):
    a = two_fr_tenants["a"]
    b = two_fr_tenants["b"]

    resp = await http_client.patch(
        f"/api/v1/fieldreports/workforce/{a['workforce_id']}",
        json={"headcount": 0, "worker_type": "B-tampered"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B updated A's workforce entry: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_workforce_entry(
    http_client,
    two_fr_tenants,
):
    a = two_fr_tenants["a"]
    b = two_fr_tenants["b"]

    resp = await http_client.delete(
        f"/api/v1/fieldreports/workforce/{a['workforce_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B deleted A's workforce entry: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_update_equipment_entry(
    http_client,
    two_fr_tenants,
):
    a = two_fr_tenants["a"]
    b = two_fr_tenants["b"]

    resp = await http_client.patch(
        f"/api/v1/fieldreports/equipment/{a['equipment_id']}",
        json={"equipment_description": "B-tampered"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B updated A's equipment entry: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_equipment_entry(
    http_client,
    two_fr_tenants,
):
    a = two_fr_tenants["a"]
    b = two_fr_tenants["b"]

    resp = await http_client.delete(
        f"/api/v1/fieldreports/equipment/{a['equipment_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B deleted A's equipment entry: {resp.status_code} {resp.text!r}"
    )


# ── Regression guards: the owner must still have access ────────────────────


@pytest.mark.asyncio
async def test_owner_can_still_list_workforce(http_client, two_fr_tenants):
    a = two_fr_tenants["a"]
    resp = await http_client.get(
        f"/api/v1/fieldreports/reports/{a['report_id']}/workforce/",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) >= 1
    assert any("A-secret" in (entry.get("worker_type") or "") for entry in body)


@pytest.mark.asyncio
async def test_owner_can_still_list_equipment(http_client, two_fr_tenants):
    a = two_fr_tenants["a"]
    resp = await http_client.get(
        f"/api/v1/fieldreports/reports/{a['report_id']}/equipment/",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) >= 1
    assert any("Liebherr" in (entry.get("equipment_description") or "") for entry in body)


@pytest.mark.asyncio
async def test_owner_can_still_update_workforce(http_client, two_fr_tenants):
    a = two_fr_tenants["a"]
    resp = await http_client.patch(
        f"/api/v1/fieldreports/workforce/{a['workforce_id']}",
        json={"headcount": 8},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["headcount"] == 8


@pytest.mark.asyncio
async def test_owner_can_still_update_equipment(http_client, two_fr_tenants):
    a = two_fr_tenants["a"]
    resp = await http_client.patch(
        f"/api/v1/fieldreports/equipment/{a['equipment_id']}",
        json={"hours_operational": "7"},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["hours_operational"] == "7"


# ── Cross-project document-link vectors ─────────────────────────────────────


@pytest.mark.asyncio
async def test_link_documents_rejects_foreign_project_document(http_client, two_fr_tenants):
    """``POST /reports/{id}/link-documents/`` must reject a foreign-project doc.

    A field report's ``document_ids`` array is a cross-module reference into
    the documents table. Pre-fix ``link_documents`` stored any UUID verbatim,
    so a user who can edit a report in their own project could attach a
    document_id that resolves to a document in another project, and
    ``GET /reports/{id}/documents/`` would then echo that foreign document's
    name and metadata back. The fix rejects any document_id that does not
    belong to the report's project with 422; the rule is symmetric, so even a
    second project of the same owner cannot cross-link.
    """
    a = two_fr_tenants["a"]

    proj2 = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"FR-A-2 {uuid.uuid4().hex[:6]}",
            "description": "second project of A - used for the cross-project link test",
            "currency": "EUR",
        },
        headers=a["headers"],
    )
    assert proj2.status_code == 201, proj2.text
    other_project = proj2.json()["id"]

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.documents.models import Document

    async with async_session_factory() as s:
        s.add(
            Document(
                project_id=uuid.UUID(other_project),
                name="confidential-in-other-project.pdf",
                description="must not be linkable from a report in project A",
                category="correspondence",
                file_size=123,
                mime_type="application/pdf",
                file_path="/tmp/never-read.pdf",
                version=1,
                uploaded_by="",
                tags=[],
            )
        )
        await s.commit()
        row = (
            (await s.execute(select(Document).where(Document.project_id == uuid.UUID(other_project)))).scalars().first()
        )
        foreign_document_id = str(row.id)

    resp = await http_client.post(
        f"/api/v1/fieldreports/reports/{a['report_id']}/link-documents/",
        json={"document_ids": [foreign_document_id]},
        headers=a["headers"],
    )
    assert resp.status_code in (400, 404, 422), (
        f"LEAK: report accepted a foreign-project document_id: {resp.status_code} {resp.text!r}"
    )

    listing = await http_client.get(
        f"/api/v1/fieldreports/reports/{a['report_id']}/documents/",
        headers=a["headers"],
    )
    assert listing.status_code == 200, listing.text
    assert "confidential-in-other-project" not in listing.text, (
        f"LEAK: foreign document metadata surfaced: {listing.text!r}"
    )


@pytest.mark.asyncio
async def test_owner_can_link_and_read_same_project_document(http_client, two_fr_tenants):
    """Regression: linking a document from the report's own project still works."""
    a = two_fr_tenants["a"]

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.documents.models import Document

    async with async_session_factory() as s:
        s.add(
            Document(
                project_id=uuid.UUID(a["project_id"]),
                name="site-plan-in-own-project.pdf",
                description="lives in the report's project - linking must work",
                category="correspondence",
                file_size=456,
                mime_type="application/pdf",
                file_path="/tmp/own.pdf",
                version=1,
                uploaded_by="",
                tags=[],
            )
        )
        await s.commit()
        row = (
            (
                await s.execute(
                    select(Document).where(
                        Document.project_id == uuid.UUID(a["project_id"]),
                        Document.name == "site-plan-in-own-project.pdf",
                    )
                )
            )
            .scalars()
            .first()
        )
        own_document_id = str(row.id)

    link = await http_client.post(
        f"/api/v1/fieldreports/reports/{a['report_id']}/link-documents/",
        json={"document_ids": [own_document_id]},
        headers=a["headers"],
    )
    assert link.status_code == 200, f"REGRESSION: owner blocked from linking own-project doc: {link.text}"

    listing = await http_client.get(
        f"/api/v1/fieldreports/reports/{a['report_id']}/documents/",
        headers=a["headers"],
    )
    assert listing.status_code == 200, listing.text
    assert "site-plan-in-own-project" in listing.text, (
        f"REGRESSION: own-project document missing from linked list: {listing.text!r}"
    )
