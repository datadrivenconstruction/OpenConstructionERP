# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Credentials registry - integration tests.

Covers the API contract end to end:

    1. Create a licence valid 200d ahead, notify=30  -> status ``active``.
    2. Create one valid 15d ahead                    -> status ``expiring_soon``.
    3. Create one already past valid_until           -> status ``expired``.
    4. Create a perpetual credential (no valid_until) -> status ``active``,
       days_until_expiry is null.
    5. PATCH valid_until recomputes status.
    6. Manual ``revoked`` is terminal: cannot be patched back to active.
    7. Cross-project IDOR: user B cannot list/read A's credentials.
    8. ``/meta`` returns localized labels for the requested locale.
    9. Owner can DELETE.

Scaffolding mirrors ``test_compliance_docs.py`` - the engine is bound to the
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
        from app.modules.credentials import models as _cred_models  # noqa: F401
        from app.modules.projects import models as _proj_models  # noqa: F401

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
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@credentials.io"
    password = f"Creds{uuid.uuid4().hex[:6]}9"
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
async def test_create_active_licence(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "holder_name": "Jane Engineer",
        "credential_type": "professional_license",
        "authority": "Registration board",
        "identifier": "PE-12345",
        "valid_until": _iso(200),
        "notify_days_before": 30,
    }
    r = await http_client.post("/api/v1/credentials/", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "active"
    assert data["days_until_expiry"] >= 199


@pytest.mark.asyncio
async def test_create_expiring_soon(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "holder_name": "Firm A Ltd",
        "holder_kind": "company",
        "credential_type": "professional_indemnity",
        "valid_until": _iso(15),
        "notify_days_before": 30,
    }
    r = await http_client.post("/api/v1/credentials/", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "expiring_soon"


@pytest.mark.asyncio
async def test_create_expired(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "holder_name": "Old Cert Holder",
        "credential_type": "certification",
        "valid_until": _iso(-1),
    }
    r = await http_client.post("/api/v1/credentials/", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "expired"


@pytest.mark.asyncio
async def test_perpetual_credential_has_null_days(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "holder_name": "Chartered Body Member",
        "credential_type": "statutory_membership",
        # no valid_until -> perpetual
    }
    r = await http_client.post("/api/v1/credentials/", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "active"
    assert data["days_until_expiry"] is None


@pytest.mark.asyncio
async def test_patch_valid_until_recomputes_status(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/credentials/",
        json={
            "project_id": a["project_id"],
            "holder_name": "Renewable Holder",
            "credential_type": "training",
            "valid_until": _iso(200),
        },
        headers=a["headers"],
    )
    cid = create.json()["id"]
    assert create.json()["status"] == "active"

    patch = await http_client.patch(
        f"/api/v1/credentials/{cid}/",
        json={"valid_until": _iso(10)},
        headers=a["headers"],
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] == "expiring_soon"


@pytest.mark.asyncio
async def test_revoked_is_terminal(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/credentials/",
        json={
            "project_id": a["project_id"],
            "holder_name": "Struck Off",
            "credential_type": "professional_license",
            "valid_until": _iso(100),
            "status": "revoked",
        },
        headers=a["headers"],
    )
    assert create.status_code == 201, create.text
    cid = create.json()["id"]
    assert create.json()["status"] == "revoked"

    # Cannot reinstate a revoked credential in place.
    patch = await http_client.patch(
        f"/api/v1/credentials/{cid}/",
        json={"status": "active"},
        headers=a["headers"],
    )
    assert patch.status_code == 400, patch.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_project_idor_blocked(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    created = await http_client.post(
        "/api/v1/credentials/",
        json={
            "project_id": a["project_id"],
            "holder_name": "Private Holder",
            "credential_type": "certification",
            "valid_until": _iso(50),
        },
        headers=a["headers"],
    )
    # A 403 here means the arrange step failed, not the isolation check.
    # Without this the next line dies as KeyError: 'id' and hides the cause.
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    # B cannot read A's credential.
    got = await http_client.get(f"/api/v1/credentials/{cid}/", headers=b["headers"])
    assert got.status_code in (403, 404), got.text

    # B cannot list A's project credentials.
    listed = await http_client.get(
        "/api/v1/credentials/",
        params={"project_id": a["project_id"]},
        headers=b["headers"],
    )
    assert listed.status_code in (403, 404), listed.text


@pytest.mark.asyncio
async def test_meta_localized_labels(http_client, two_tenants):
    a = two_tenants["a"]
    r = await http_client.get("/api/v1/credentials/meta", params={"locale": "ru"}, headers=a["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    types = {row["code"]: row["label"] for row in body["credential_types"]}
    assert types["professional_license"] == "Профессиональная лицензия"
    statuses = {row["code"]: row["label"] for row in body["statuses"]}
    assert statuses["expired"] == "Истекла"


@pytest.mark.asyncio
async def test_expiring_soon_widget_and_delete(http_client, two_tenants):
    a = two_tenants["a"]
    # At least the earlier expiring_soon / expired rows should surface here.
    r = await http_client.get(
        "/api/v1/credentials/expiring-soon/",
        params={"project_id": a["project_id"]},
        headers=a["headers"],
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)

    # Create then delete.
    created = await http_client.post(
        "/api/v1/credentials/",
        json={
            "project_id": a["project_id"],
            "holder_name": "Temp Holder",
            "credential_type": "other",
            "valid_until": _iso(5),
        },
        headers=a["headers"],
    )
    cid = created.json()["id"]
    deleted = await http_client.delete(f"/api/v1/credentials/{cid}/", headers=a["headers"])
    assert deleted.status_code == 204, deleted.text
    gone = await http_client.get(f"/api/v1/credentials/{cid}/", headers=a["headers"])
    assert gone.status_code == 404
