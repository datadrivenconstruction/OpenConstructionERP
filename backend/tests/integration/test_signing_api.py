# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-signature registry - integration tests.

Covers the API contract end to end:

    1. Create a session with two required signatories -> awaiting_signatures.
    2. Attest as one required signatory              -> partially_signed.
    3. Attest as the second required signatory        -> fully_signed.
    4. Decline moves a fresh session to declined and blocks further attests.
    5. Re-issue (PATCH document_content_hash) marks the earlier signature stale
       via /stale (delta-by-hash).
    6. /expiring-certs surfaces a signature with expired certificate metadata.
    7. /manifest returns the issued-set hash manifest.
    8. Cross-project IDOR: user B cannot read/list A's sessions.
    9. /meta returns localized labels for the requested locale.
   10. Owner can DELETE.

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
        from app.modules.signing import models as _sign_models  # noqa: F401

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
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@signing.io"
    password = f"Sign{uuid.uuid4().hex[:6]}9"
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


def _two_party_body(project_id: str, *, content_hash: str = "hashv1") -> dict:
    return {
        "project_id": project_id,
        "document_ref": "contract/main-agreement",
        "document_content_hash": content_hash,
        "provider_capability": "qualified_electronic",
        "signatory_map": [
            {"name": "Contractor Rep", "role": "contractor", "required": True},
            {"name": "Client Rep", "role": "client", "required": True},
        ],
    }


def _date(days_from_now: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_signing_flow(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/signing/sessions/",
        json=_two_party_body(a["project_id"]),
        headers=a["headers"],
    )
    assert create.status_code == 201, create.text
    data = create.json()
    assert data["status"] == "awaiting_signatures"
    assert data["required_count"] == 2
    cid = data["id"]

    # First required signatory signs -> partially_signed.
    r1 = await http_client.post(
        f"/api/v1/signing/sessions/{cid}/attest",
        json={
            "signatory_name": "Contractor Rep",
            "signatory_role": "contractor",
            "content_hash": "hashv1",
            "cert_subject": "CN=Contractor Rep",
            "cert_valid_until": _date(400),
        },
        headers=a["headers"],
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["status"] == "partially_signed"
    assert r1.json()["signed_count"] == 1

    # Second required signatory signs -> fully_signed.
    r2 = await http_client.post(
        f"/api/v1/signing/sessions/{cid}/attest",
        json={
            "signatory_name": "Client Rep",
            "signatory_role": "client",
            "content_hash": "hashv1",
        },
        headers=a["headers"],
    )
    assert r2.status_code == 201, r2.text
    body = r2.json()
    assert body["status"] == "fully_signed"
    assert body["signed_count"] == 2


@pytest.mark.asyncio
async def test_required_capability_is_not_reported_as_delivered(http_client, two_tenants):
    """A session may require more than the platform can deliver, and must say so.

    ``_two_party_body`` asks for ``qualified_electronic`` - eIDAS QES and the
    like. No adapter for it exists in this tree, so the registry resolves to the
    built-in provider, which performs no cryptography and delivers
    ``simple_electronic``. The session is still created and can still reach
    fully_signed: refusing here is a separate product decision and would break
    existing sessions on upgrade. What must not happen is the record and the
    interface repeating the requirement as though it had been met.

    The assertions are deliberately on the delivered value being DIFFERENT from
    the required one rather than merely present. A later ``delivered or
    required`` fallback anywhere between the column and the response would make
    the two agree, which reads as correct everywhere except here.
    """
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/signing/sessions/",
        json=_two_party_body(a["project_id"], content_hash="hash-capability"),
        headers=a["headers"],
    )
    assert create.status_code == 201, create.text
    data = create.json()

    assert data["provider_capability"] == "qualified_electronic"
    assert data["delivered_capability"] == "simple_electronic"
    assert data["delivered_capability"] != data["provider_capability"]

    # Signing it through does not upgrade the claim.
    for name, role in (("Contractor Rep", "contractor"), ("Client Rep", "client")):
        attest = await http_client.post(
            f"/api/v1/signing/sessions/{data['id']}/attest",
            json={
                "signatory_name": name,
                "signatory_role": role,
                "content_hash": "hash-capability",
            },
            headers=a["headers"],
        )
        assert attest.status_code == 201, attest.text
    assert attest.json()["status"] == "fully_signed"
    assert attest.json()["delivered_capability"] == "simple_electronic"

    # The manifest is the closest thing to a legal record here, so it carries
    # both values too.
    manifest = await http_client.get(
        f"/api/v1/signing/sessions/{data['id']}/manifest",
        headers=a["headers"],
    )
    assert manifest.status_code == 200, manifest.text
    body = manifest.json()
    assert body["provider_capability"] == "qualified_electronic"
    assert body["delivered_capability"] == "simple_electronic"


@pytest.mark.asyncio
async def test_decline_is_terminal(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/signing/sessions/",
        json=_two_party_body(a["project_id"]),
        headers=a["headers"],
    )
    cid = create.json()["id"]

    declined = await http_client.post(
        f"/api/v1/signing/sessions/{cid}/decline",
        json={"signatory_name": "Client Rep", "signatory_role": "client", "reason": "terms"},
        headers=a["headers"],
    )
    assert declined.status_code == 201, declined.text
    assert declined.json()["status"] == "declined"

    # A declined session rejects further attestations.
    blocked = await http_client.post(
        f"/api/v1/signing/sessions/{cid}/attest",
        json={"signatory_name": "Contractor Rep", "signatory_role": "contractor", "content_hash": "hashv1"},
        headers=a["headers"],
    )
    assert blocked.status_code == 400, blocked.text


@pytest.mark.asyncio
async def test_reissue_marks_signature_stale(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/signing/sessions/",
        json=_two_party_body(a["project_id"], content_hash="orig"),
        headers=a["headers"],
    )
    cid = create.json()["id"]

    await http_client.post(
        f"/api/v1/signing/sessions/{cid}/attest",
        json={"signatory_name": "Contractor Rep", "signatory_role": "contractor", "content_hash": "orig"},
        headers=a["headers"],
    )

    # Re-issue the content: bump the session's content hash.
    patch = await http_client.patch(
        f"/api/v1/signing/sessions/{cid}/",
        json={"document_content_hash": "reissued"},
        headers=a["headers"],
    )
    assert patch.status_code == 200, patch.text

    stale = await http_client.get(f"/api/v1/signing/sessions/{cid}/stale", headers=a["headers"])
    assert stale.status_code == 200, stale.text
    assert "Contractor Rep" in stale.json()["stale_signatories"]

    # The nested signature carries the stale flag too.
    detail = await http_client.get(f"/api/v1/signing/sessions/{cid}/", headers=a["headers"])
    sig = detail.json()["signatures"][0]
    assert sig["stale"] is True


@pytest.mark.asyncio
async def test_expiring_certs(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/signing/sessions/",
        json=_two_party_body(a["project_id"]),
        headers=a["headers"],
    )
    cid = create.json()["id"]
    await http_client.post(
        f"/api/v1/signing/sessions/{cid}/attest",
        json={
            "signatory_name": "Contractor Rep",
            "signatory_role": "contractor",
            "content_hash": "hashv1",
            "cert_subject": "CN=Expiring",
            "cert_valid_until": _date(-3),
        },
        headers=a["headers"],
    )

    r = await http_client.get(
        "/api/v1/signing/expiring-certs",
        params={"project_id": a["project_id"], "within_days": 30},
        headers=a["headers"],
    )
    assert r.status_code == 200, r.text
    subjects = {row["cert_subject"] for row in r.json()}
    assert "CN=Expiring" in subjects
    expired_rows = [row for row in r.json() if row["cert_subject"] == "CN=Expiring"]
    assert expired_rows[0]["expired"] is True


@pytest.mark.asyncio
async def test_manifest(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/signing/sessions/",
        json=_two_party_body(a["project_id"], content_hash="manifesthash"),
        headers=a["headers"],
    )
    cid = create.json()["id"]
    r = await http_client.get(f"/api/v1/signing/sessions/{cid}/manifest", headers=a["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["manifest"]["contract/main-agreement"] == "manifesthash"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_project_idor_blocked(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    created = await http_client.post(
        "/api/v1/signing/sessions/",
        json=_two_party_body(a["project_id"]),
        headers=a["headers"],
    )
    # A 403 here means the arrange step failed, not the isolation check.
    # Without this the next line dies as KeyError: 'id' and hides the cause.
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    got = await http_client.get(f"/api/v1/signing/sessions/{cid}/", headers=b["headers"])
    assert got.status_code in (403, 404), got.text

    listed = await http_client.get(
        "/api/v1/signing/sessions/",
        params={"project_id": a["project_id"]},
        headers=b["headers"],
    )
    assert listed.status_code in (403, 404), listed.text


@pytest.mark.asyncio
async def test_meta_localized_labels(http_client, two_tenants):
    a = two_tenants["a"]
    r = await http_client.get("/api/v1/signing/meta", params={"locale": "ru"}, headers=a["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    caps = {row["code"]: row["label"] for row in body["capabilities"]}
    assert caps["qualified_electronic"] == "Квалифицированная электронная подпись"
    statuses = {row["code"]: row["label"] for row in body["statuses"]}
    assert statuses["fully_signed"] == "Полностью подписан"
    # The default provider is attestation-only and never accepts keys/passwords.
    assert body["default_provider"]["accepts_keys_or_passwords"] is False


@pytest.mark.asyncio
async def test_delete_session(http_client, two_tenants):
    a = two_tenants["a"]
    created = await http_client.post(
        "/api/v1/signing/sessions/",
        json=_two_party_body(a["project_id"]),
        headers=a["headers"],
    )
    cid = created.json()["id"]
    deleted = await http_client.delete(f"/api/v1/signing/sessions/{cid}/", headers=a["headers"])
    assert deleted.status_code == 204, deleted.text
    gone = await http_client.get(f"/api/v1/signing/sessions/{cid}/", headers=a["headers"])
    assert gone.status_code == 404
