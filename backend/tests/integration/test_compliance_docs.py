"""Compliance documents tracker — integration tests.

Covers the 8 scenarios in the spec:

    1. insurance + 60d expiry + notify=30  → status ``active``
    2. permit    + 15d expiry + notify=30  → status ``expiring_soon``
    3. cert      − 1d  expiry              → status ``expired``
    4. Non-owner cannot list (cross-project IDOR — 403 or 404 accepted;
       the router uses ``verify_project_access`` which currently returns
       404 to avoid UUID-existence oracles; either is acceptable here).
    5. PATCH ``expires_at`` recomputes status.
    6. Owner can DELETE; non-owner gets 403/404.
    7. Cross-project IDOR: user with project A can't list project B.
    8. ``attachment_document_id`` must belong to the same project.

Test scaffolding mirrors ``test_erp_chat_idor.py`` — the engine is bound to
the conftest-provisioned PostgreSQL cluster before any test module imports.
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
    """Boot the FastAPI app once per module."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.compliance_docs import models as _docs_models  # noqa: F401
        from app.modules.documents import models as _doc_module  # noqa: F401
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
    """Force ``is_active=True`` (admin-approve mode is the default)."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _register_login(
    client: AsyncClient,
    *,
    tenant: str,
) -> tuple[str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@compliance-docs.io"
    password = f"CompDocs{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Tenant {tenant}",
        },
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"
    user_id = reg.json()["id"]
    await _activate_user(email)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    token = login.json()["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}


async def _create_project(owner_user_id: str, name: str) -> str:
    """Seed a Project row owned by ``owner_user_id``. Returns ID."""
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    async with async_session_factory() as s:
        p = Project(
            id=pid,
            name=name,
            description="",
            owner_id=uuid.UUID(owner_user_id),
        )
        s.add(p)
        await s.commit()
    return str(pid)


async def _promote_to_role(client: AsyncClient, email: str, password: str, role: str) -> dict[str, str]:
    """Force ``role`` on a freshly registered user and re-issue its JWT.

    Default registration role is ``viewer``, which carries none of the
    ``compliance_docs`` write permissions. Registration only hands out
    ``admin`` to the very first account in the database, so a fixture that
    wants a privileged actor has to say so rather than hope it registered
    first: this module shares one database with every other module in the
    shard, and whichever one runs first takes the bootstrap admin.

    The role goes straight into the users table and then the user logs in
    again, because the role travels in the JWT claims and the token issued
    before the promotion still carries the old one.
    """
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


async def _register_login_with_creds(
    client: AsyncClient,
    *,
    tenant: str,
) -> tuple[str, str, str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@compliance-docs.io"
    password = f"CompDocs{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Tenant {tenant}",
        },
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"
    user_id = reg.json()["id"]
    await _activate_user(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    token = login.json()["access_token"]
    return user_id, email, password, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """A owns one project, B owns another. Both authenticated.

    A is promoted to admin so it can create and delete its own docs, and B
    to editor so B can create rows in B's *own* project. The IDOR audit then
    checks that B cannot reach into A's project.

    Both promotions are explicit. A used to rely on being the first
    registered account and getting admin from the bootstrap path, which held
    only while this module happened to run before every other module that
    registers a user against the same database.
    """
    a_uid, a_email, a_password, _a_hdr_initial = await _register_login_with_creds(
        http_client,
        tenant="a",
    )
    a_hdr = await _promote_to_role(http_client, a_email, a_password, "admin")
    b_uid, b_email, b_password, _b_hdr_initial = await _register_login_with_creds(
        http_client,
        tenant="b",
    )
    b_hdr = await _promote_to_role(http_client, b_email, b_password, "editor")

    a_project = await _create_project(a_uid, "A's project")
    b_project = await _create_project(b_uid, "B's project")
    return {
        "a": {"uid": a_uid, "headers": a_hdr, "project_id": a_project},
        "b": {"uid": b_uid, "headers": b_hdr, "project_id": b_project},
    }


def _today() -> datetime:
    return datetime.now(UTC)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_insurance_60d_is_active(http_client, two_tenants):
    """expires in 60d, notify=30 → status ``active``."""
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "doc_type": "insurance_general_liability",
        "name": "GL Insurance — Acme Underwriters",
        "issuer": "Acme",
        "policy_number": "GL-2026-001",
        "coverage_amount": "1000000.00",
        "currency": "EUR",
        "effective_date": _iso(_today()),
        "expires_at": _iso(_today() + timedelta(days=60)),
        "notify_days_before": 30,
    }
    resp = await http_client.post(
        "/api/v1/compliance_docs/",
        json=body,
        headers=a["headers"],
    )
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["status"] == "active", out
    assert out["days_until_expiry"] in (59, 60), out


@pytest.mark.asyncio
async def test_create_permit_15d_is_expiring_soon(http_client, two_tenants):
    """expires in 15d, notify=30 → status ``expiring_soon``."""
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "doc_type": "permit_building",
        "name": "Building permit — district 7",
        "effective_date": _iso(_today()),
        "expires_at": _iso(_today() + timedelta(days=15)),
        "notify_days_before": 30,
    }
    resp = await http_client.post(
        "/api/v1/compliance_docs/",
        json=body,
        headers=a["headers"],
    )
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["status"] == "expiring_soon", out


@pytest.mark.asyncio
async def test_create_cert_already_expired(http_client, two_tenants):
    """expires_at < today → status ``expired``."""
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "doc_type": "certification_safety",
        "name": "Safety cert 2025",
        "effective_date": _iso(_today() - timedelta(days=400)),
        "expires_at": _iso(_today() - timedelta(days=1)),
        "notify_days_before": 30,
    }
    resp = await http_client.post(
        "/api/v1/compliance_docs/",
        json=body,
        headers=a["headers"],
    )
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["status"] == "expired", out
    assert out["days_until_expiry"] < 0, out


@pytest.mark.asyncio
async def test_create_cover_starting_in_the_future_is_not_yet_effective(http_client, two_tenants):
    """``effective_date`` after today → status ``not_yet_effective``.

    Next year's policy is filed the day it is issued, months before cover
    starts. The status came off ``expires_at`` alone, so the row was
    persisted ``active`` from that day and the project read as covered for
    the whole interval before the cover began. Asserted through the request
    path, because the new value also has to pass the create schema's status
    pattern and come back out of ``ComplianceDocResponse``.
    """
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "doc_type": "insurance_general_liability",
        "name": "GL Insurance — next policy year",
        "issuer": "Acme",
        "policy_number": "GL-FUTURE-001",
        "coverage_amount": "1000000.00",
        "currency": "EUR",
        "effective_date": _iso(_today() + timedelta(days=116)),
        "expires_at": _iso(_today() + timedelta(days=485)),
        "notify_days_before": 30,
    }
    resp = await http_client.post(
        "/api/v1/compliance_docs/",
        json=body,
        headers=a["headers"],
    )
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["status"] == "not_yet_effective", out

    # The other direction. Same window, cover already running, still
    # ``active`` — a ladder that answered ``not_yet_effective`` for
    # everything would pass the assertion above and fail this one.
    in_force = dict(
        body,
        policy_number="GL-INFORCE-001",
        effective_date=_iso(_today() - timedelta(days=30)),
    )
    resp_in_force = await http_client.post(
        "/api/v1/compliance_docs/",
        json=in_force,
        headers=a["headers"],
    )
    assert resp_in_force.status_code == 201, resp_in_force.text
    assert resp_in_force.json()["status"] == "active", resp_in_force.text

    # The register can be asked which documents are not live cover yet.
    listing = await http_client.get(
        f"/api/v1/compliance_docs/?project_id={a['project_id']}&status=not_yet_effective",
        headers=a["headers"],
    )
    assert listing.status_code == 200, listing.text
    listed = listing.json()
    rows = listed["items"] if isinstance(listed, dict) else listed
    ids = {row["id"] for row in rows}
    assert out["id"] in ids, rows
    assert resp_in_force.json()["id"] not in ids, rows


@pytest.mark.asyncio
async def test_project_widget_counts_unstarted_cover_in_its_own_bucket(http_client, two_tenants):
    """The dashboard tile buckets a future start date separately.

    The widget re-derives its buckets on read instead of trusting the
    persisted ``status``, and it did not select ``effective_date`` at all,
    so repairing the service ladder alone would have left the tiles calling
    unstarted cover ``active``. A project of its own keeps the counts exact
    rather than at the mercy of what the other tests in this module filed.
    """
    a = two_tenants["a"]
    project_id = await _create_project(a["uid"], "Tile bucket project")

    for policy_number, effective_offset in (("TILE-FUTURE-1", 200), ("TILE-INFORCE-1", -10)):
        resp = await http_client.post(
            "/api/v1/compliance_docs/",
            json={
                "project_id": project_id,
                "doc_type": "insurance_general_liability",
                "name": f"GL Insurance {policy_number}",
                "policy_number": policy_number,
                "effective_date": _iso(_today() + timedelta(days=effective_offset)),
                "expires_at": _iso(_today() + timedelta(days=500)),
                "notify_days_before": 30,
            },
            headers=a["headers"],
        )
        assert resp.status_code == 201, resp.text

    rollup = await http_client.get(
        f"/api/v1/dashboard/rollup/?widgets=project_compliance_summary&project_ids={project_id}",
        headers=a["headers"],
    )
    assert rollup.status_code == 200, rollup.text
    payload = rollup.json()["project_compliance_summary"]

    assert payload["not_yet_effective"] == 1, payload
    assert payload["active"] == 1, payload
    assert payload["expiring"] == 0, payload
    assert payload["expired"] == 0, payload
    # Four buckets, two documents on file. Counting the unstarted one
    # nowhere would make the project's cover look smaller than the
    # register says it is, which is a different wrong answer.
    assert sum(payload[k] for k in ("active", "not_yet_effective", "expiring", "expired")) == 2, payload
    assert {item["effective_date"] for item in payload["items"]} != {None}, payload["items"]


@pytest.mark.asyncio
async def test_patch_expires_at_recomputes_status(http_client, two_tenants):
    """PATCH ``expires_at`` flips ``active`` → ``expiring_soon``."""
    a = two_tenants["a"]
    create_body = {
        "project_id": a["project_id"],
        "doc_type": "bond_performance",
        "name": "Perf bond — Section 4",
        "effective_date": _iso(_today()),
        "expires_at": _iso(_today() + timedelta(days=90)),
        "notify_days_before": 30,
    }
    created = await http_client.post(
        "/api/v1/compliance_docs/",
        json=create_body,
        headers=a["headers"],
    )
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]
    assert created.json()["status"] == "active"

    # Pull the expiry inward.
    patch = await http_client.patch(
        f"/api/v1/compliance_docs/{doc_id}/",
        json={"expires_at": _iso(_today() + timedelta(days=10))},
        headers=a["headers"],
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] == "expiring_soon", patch.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_non_owner_cannot_list(http_client, two_tenants):
    """Cross-project IDOR — B asks for A's project's docs."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    resp = await http_client.get(
        "/api/v1/compliance_docs/",
        params={"project_id": a["project_id"]},
        headers=b["headers"],
    )
    # Router uses verify_project_access → 404 (not a UUID-existence oracle).
    # Either 403 or 404 is acceptable as a denial.
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B was able to list A's compliance docs (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_non_owner_cannot_delete(http_client, two_tenants):
    """Cross-project IDOR — B tries to delete A's doc."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    # First seed a doc as A.
    created = await http_client.post(
        "/api/v1/compliance_docs/",
        json={
            "project_id": a["project_id"],
            "doc_type": "permit_electrical",
            "name": "Elec permit",
            "effective_date": _iso(_today()),
            "expires_at": _iso(_today() + timedelta(days=120)),
            "notify_days_before": 30,
        },
        headers=a["headers"],
    )
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]

    # B's DELETE must be rejected.
    resp = await http_client.delete(
        f"/api/v1/compliance_docs/{doc_id}/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B was able to delete A's doc (status {resp.status_code}). Body: {resp.text!r}"
    )

    # The owner can still see + delete it (proves the row wasn't wiped).
    still_there = await http_client.get(
        f"/api/v1/compliance_docs/{doc_id}/",
        headers=a["headers"],
    )
    assert still_there.status_code == 200, still_there.text

    final = await http_client.delete(
        f"/api/v1/compliance_docs/{doc_id}/",
        headers=a["headers"],
    )
    assert final.status_code == 204, final.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_project_list_returns_only_own_project(
    http_client,
    two_tenants,
):
    """A's GET for A's project must NOT include B's rows."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    # B seeds one row in B's project.
    b_row = await http_client.post(
        "/api/v1/compliance_docs/",
        json={
            "project_id": b["project_id"],
            "doc_type": "insurance_auto",
            "name": "B's auto policy",
            "effective_date": _iso(_today()),
            "expires_at": _iso(_today() + timedelta(days=30)),
            "notify_days_before": 30,
        },
        headers=b["headers"],
    )
    assert b_row.status_code == 201, b_row.text
    b_doc_id = b_row.json()["id"]

    # A lists A's project.
    a_list = await http_client.get(
        "/api/v1/compliance_docs/",
        params={"project_id": a["project_id"]},
        headers=a["headers"],
    )
    assert a_list.status_code == 200, a_list.text
    ids = {row["id"] for row in a_list.json()}
    assert b_doc_id not in ids, "LEAK: A's project listing returned B-owned compliance doc"


@pytest.mark.asyncio
async def test_attachment_must_belong_to_same_project(http_client, two_tenants):
    """attachment_document_id from a different project → 400."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    # Seed a Document directly into B's project (skips the upload pipeline).
    from app.database import async_session_factory
    from app.modules.documents.models import Document

    doc_id = uuid.uuid4()
    async with async_session_factory() as s:
        d = Document(
            id=doc_id,
            project_id=uuid.UUID(b["project_id"]),
            name="B's contract.pdf",
            description="",
            category="document",
            file_size=10,
            mime_type="application/pdf",
            file_path="/tmp/b-contract.pdf",
            uploaded_by=b["uid"],
        )
        s.add(d)
        await s.commit()

    # A tries to attach B's document to a doc in A's project.
    resp = await http_client.post(
        "/api/v1/compliance_docs/",
        json={
            "project_id": a["project_id"],
            "doc_type": "other",
            "name": "Sneaky doc",
            "effective_date": _iso(_today()),
            "expires_at": _iso(_today() + timedelta(days=10)),
            "notify_days_before": 30,
            "attachment_document_id": str(doc_id),
        },
        headers=a["headers"],
    )
    assert resp.status_code == 400, f"Cross-project attachment was accepted (status {resp.status_code}): {resp.text!r}"


@pytest.mark.asyncio
async def test_expiring_soon_endpoint(http_client, two_tenants):
    """The dashboard convenience endpoint returns only expired/expiring rows."""
    a = two_tenants["a"]
    resp = await http_client.get(
        "/api/v1/compliance_docs/expiring-soon/",
        params={"project_id": a["project_id"]},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    # Must contain only expiring_soon | expired rows. (The earlier test
    # cases created at least one of each.)
    assert all(r["status"] in ("expiring_soon", "expired") for r in rows), rows
    assert len(rows) >= 1, rows
