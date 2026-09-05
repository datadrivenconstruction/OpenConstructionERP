# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Source-data register - integration tests.

Covers the API contract end to end:

    1. Create a permit received & valid 200d ahead  -> status ``received``.
    2. Create one received & valid 15d ahead        -> status ``expiring_soon``.
    3. Create one received & already lapsed         -> status ``expired``.
    4. Create a perpetual document (no valid_until) -> status ``received``,
       days_until_expiry is null.
    5. Default status on create is ``requested``.
    6. PATCH valid_until recomputes status; POST /verify marks verified.
    7. Superseded is terminal: cannot be patched back to received.
    8. blocking-schedule surfaces a flagged & expired document.
    9. Checklist CRUD + completeness summary; defective-inputs notice.
   10. Cross-project IDOR: user B cannot list/read A's documents.
   11. ``/meta`` returns localized labels for the requested locale.

Scaffolding mirrors ``test_credentials_api.py`` - the engine is bound to the
conftest-provisioned PostgreSQL cluster before any test module imports.
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
        from app.modules.projects import models as _proj_models  # noqa: F401
        from app.modules.source_data import models as _sd_models  # noqa: F401

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


async def _promote_to_role(client: AsyncClient, email: str, password: str, role: str) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role))
        await s.commit()

    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _register_login(client: AsyncClient, *, tenant: str) -> tuple[str, str, str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@sourcedata.io"
    password = f"Srcd{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"
    user_id = reg.json()["id"]
    await _activate_user(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    return user_id, email, password, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _create_project(owner_user_id: str, name: str) -> str:
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    async with async_session_factory() as s:
        p = Project(id=pid, name=name, description="", owner_id=uuid.UUID(owner_user_id))
        s.add(p)
        await s.commit()
    return str(pid)


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    # Tenant A owns the project under test and has to be able to run every verb
    # these tests exercise in it. Registration cannot be relied on for that:
    # self-registration only hands out admin to the very first account on a fresh
    # install, and every module in this job shares one database, so exactly one of
    # them wins that slot and the rest get a viewer with no <module>.create
    # permission. A was then refused 403 in its own project and the cross-tenant
    # probe below never ran.
    #
    # Manager rather than editor, because this module registers <module>.create at
    # editor and <module>.delete one rank above it, and the delete tests below are
    # A's as well. Pinning A at editor left those refused on a permission the
    # product has required since the module shipped. Manager is still not admin, so
    # A keeps passing verify_project_access on the ownership branch a real tenant
    # would use rather than on the admin bypass, and RequirePermission still makes
    # a real rank comparison instead of short-circuiting.
    #
    # B stays editor. It is the attacker in the isolation probe and has to reach
    # the isolation check rather than be turned away by a role check first.
    a_uid, a_email, a_pw, _a_hdr = await _register_login(http_client, tenant="a")
    a_hdr = await _promote_to_role(http_client, a_email, a_pw, "manager")
    b_uid, b_email, b_pw, _b_hdr = await _register_login(http_client, tenant="b")
    b_hdr = await _promote_to_role(http_client, b_email, b_pw, "editor")
    a_project = await _create_project(a_uid, "A's project")
    b_project = await _create_project(b_uid, "B's project")
    return {
        "a": {"uid": a_uid, "headers": a_hdr, "project_id": a_project},
        "b": {"uid": b_uid, "headers": b_hdr, "project_id": b_project},
    }


def _iso(days_from_now: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_received_document(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "name": "Building permit",
        "doc_type": "permit",
        "authority": "Building authority",
        "identifier": "BP-2026-001",
        "status": "received",
        "valid_until": _iso(200),
        "notify_days_before": 30,
    }
    r = await http_client.post("/api/v1/source-data/documents", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "received"
    assert data["days_until_expiry"] >= 199


@pytest.mark.asyncio
async def test_default_status_is_requested(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "name": "Geotech report to procure",
        "doc_type": "geotech",
    }
    r = await http_client.post("/api/v1/source-data/documents", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "requested"
    assert data["days_until_expiry"] is None


@pytest.mark.asyncio
async def test_create_expiring_soon(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "name": "Technical conditions",
        "doc_type": "tech_conditions",
        "status": "received",
        "valid_until": _iso(15),
        "notify_days_before": 30,
    }
    r = await http_client.post("/api/v1/source-data/documents", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "expiring_soon"


@pytest.mark.asyncio
async def test_create_expired(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "name": "Old survey",
        "doc_type": "survey",
        "status": "received",
        "valid_until": _iso(-1),
    }
    r = await http_client.post("/api/v1/source-data/documents", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "expired"


@pytest.mark.asyncio
async def test_perpetual_document_has_null_days(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "name": "Title deed",
        "doc_type": "title_deed",
        "status": "verified",
        # no valid_until -> perpetual
    }
    r = await http_client.post("/api/v1/source-data/documents", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "verified"
    assert data["days_until_expiry"] is None


@pytest.mark.asyncio
async def test_patch_recomputes_and_verify(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/source-data/documents",
        json={
            "project_id": a["project_id"],
            "name": "Renewable approval",
            "doc_type": "approval",
            "status": "received",
            "valid_until": _iso(200),
        },
        headers=a["headers"],
    )
    did = create.json()["id"]
    assert create.json()["status"] == "received"

    patch = await http_client.patch(
        f"/api/v1/source-data/documents/{did}",
        json={"valid_until": _iso(10)},
        headers=a["headers"],
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] == "expiring_soon"

    verify = await http_client.post(
        f"/api/v1/source-data/documents/{did}/verify",
        headers=a["headers"],
    )
    assert verify.status_code == 200, verify.text
    # Still inside the reminder window, so verification lands on expiring_soon.
    assert verify.json()["status"] == "expiring_soon"


@pytest.mark.asyncio
async def test_superseded_is_terminal(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/source-data/documents",
        json={
            "project_id": a["project_id"],
            "name": "Replaced spec",
            "doc_type": "technical_spec",
            "status": "superseded",
        },
        headers=a["headers"],
    )
    assert create.status_code == 201, create.text
    did = create.json()["id"]
    assert create.json()["status"] == "superseded"

    patch = await http_client.patch(
        f"/api/v1/source-data/documents/{did}",
        json={"status": "received"},
        headers=a["headers"],
    )
    assert patch.status_code == 400, patch.text


@pytest.mark.asyncio
async def test_blocking_schedule(http_client, two_tenants):
    a = two_tenants["a"]
    await http_client.post(
        "/api/v1/source-data/documents",
        json={
            "project_id": a["project_id"],
            "name": "Critical expired permit",
            "doc_type": "permit",
            "status": "received",
            "valid_until": _iso(-3),
            "blocks_schedule": True,
        },
        headers=a["headers"],
    )
    r = await http_client.get(
        "/api/v1/source-data/blocking-schedule",
        params={"project_id": a["project_id"]},
        headers=a["headers"],
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert any(d["name"] == "Critical expired permit" for d in rows)
    assert all(d["status"] == "expired" and d["blocks_schedule"] for d in rows)


@pytest.mark.asyncio
async def test_checklist_and_defective_notice(http_client, two_tenants):
    a = two_tenants["a"]
    # A required item, left pending.
    item = await http_client.post(
        "/api/v1/source-data/checklist",
        json={
            "project_id": a["project_id"],
            "label": "Environmental permit",
            "required": True,
            "doc_type": "permit",
        },
        headers=a["headers"],
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]
    assert item.json()["status"] == "pending"

    # List + summary shows it incomplete.
    listing = await http_client.get(
        "/api/v1/source-data/checklist",
        params={"project_id": a["project_id"]},
        headers=a["headers"],
    )
    assert listing.status_code == 200, listing.text
    assert any(i["id"] == item_id for i in listing.json())

    summary = await http_client.get(
        "/api/v1/source-data/checklist/summary",
        params={"project_id": a["project_id"]},
        headers=a["headers"],
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["complete"] is False
    assert "Environmental permit" in summary.json()["missing_required"]

    # Defective-inputs notice reports defects (this pending item + earlier expired docs).
    notice = await http_client.get(
        "/api/v1/source-data/defective-inputs-notice",
        params={"project_id": a["project_id"]},
        headers=a["headers"],
    )
    assert notice.status_code == 200, notice.text
    nbody = notice.json()
    assert nbody["has_defects"] is True
    assert "Environmental permit" in nbody["missing_items"]

    # Waive it -> checklist complete.
    waive = await http_client.patch(
        f"/api/v1/source-data/checklist/{item_id}",
        json={"status": "waived"},
        headers=a["headers"],
    )
    assert waive.status_code == 200, waive.text
    assert waive.json()["status"] == "waived"

    # Delete it.
    deleted = await http_client.delete(
        f"/api/v1/source-data/checklist/{item_id}",
        headers=a["headers"],
    )
    assert deleted.status_code == 204, deleted.text


@pytest.mark.asyncio
async def test_expiring_soon_widget_and_delete(http_client, two_tenants):
    a = two_tenants["a"]
    r = await http_client.get(
        "/api/v1/source-data/expiring-soon",
        params={"project_id": a["project_id"]},
        headers=a["headers"],
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)

    created = await http_client.post(
        "/api/v1/source-data/documents",
        json={
            "project_id": a["project_id"],
            "name": "Temp doc",
            "doc_type": "other",
            "status": "received",
            "valid_until": _iso(5),
        },
        headers=a["headers"],
    )
    did = created.json()["id"]
    deleted = await http_client.delete(f"/api/v1/source-data/documents/{did}", headers=a["headers"])
    assert deleted.status_code == 204, deleted.text
    gone = await http_client.get(f"/api/v1/source-data/documents/{did}", headers=a["headers"])
    assert gone.status_code == 404


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_project_idor_blocked(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    created = await http_client.post(
        "/api/v1/source-data/documents",
        json={
            "project_id": a["project_id"],
            "name": "Private doc",
            "doc_type": "survey",
            "status": "received",
            "valid_until": _iso(50),
        },
        headers=a["headers"],
    )
    # A 403 here means the arrange step failed, not the isolation check.
    # Without this the next line dies as KeyError: 'id' and hides the cause.
    assert created.status_code == 201, created.text
    did = created.json()["id"]

    got = await http_client.get(f"/api/v1/source-data/documents/{did}", headers=b["headers"])
    assert got.status_code in (403, 404), got.text

    listed = await http_client.get(
        "/api/v1/source-data/documents",
        params={"project_id": a["project_id"]},
        headers=b["headers"],
    )
    assert listed.status_code in (403, 404), listed.text


@pytest.mark.asyncio
async def test_meta_localized_labels(http_client, two_tenants):
    a = two_tenants["a"]
    r = await http_client.get("/api/v1/source-data/meta", params={"locale": "ru"}, headers=a["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    types = {row["code"]: row["label"] for row in body["doc_types"]}
    assert types["geotech"] == "Геотехнический отчёт"
    statuses = {row["code"]: row["label"] for row in body["statuses"]}
    assert statuses["expired"] == "Истёк"
