"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Subcontractors agreements IDOR regression suite (issue #29).

A ``Subcontractor`` is a GLOBAL, tenant-shared registry entry (no
``project_id``); only its ``Agreement`` rows carry a ``project_id`` and
hold the commercial terms (title, total value, retention, notes). The
list endpoint

    GET /api/v1/subcontractors/agreements/?subcontractor_id=<S>

gates the ``project_id`` branch with ``verify_project_access`` but, pre-fix,
the ``subcontractor_id`` branch returned **every** agreement for that
subcontractor across **every** project - so any tenant that shares a
subcontractor with a competitor could read the competitor's rates and
contract values just by passing the shared subcontractor id.

The fix scopes the ``subcontractor_id`` branch to the projects the caller
may access via ``accessible_project_ids`` (admins stay unfiltered). Unlike
the by-id vectors this endpoint returns a filtered **200**, never a leak.

The attacker B is a manager (clears the subcontractors.create RBAC gate so
it can seed its own agreement, but is not an admin, so it stays scoped).

Runs against the shared ``tests/conftest.py`` PostgreSQL cluster.
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
        from app.modules.subcontractors import models as _sub_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register(client: AsyncClient, label: str) -> tuple[str, str]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@subs-idor.io"
    password = f"SubsIdor{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _make_project(client: AsyncClient, headers: dict[str, str], label: str) -> str:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"{label}-{uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return proj.json()["id"]


async def _make_agreement(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    subcontractor_id: str,
    project_id: str,
    title: str,
) -> str:
    res = await client.post(
        "/api/v1/subcontractors/agreements/",
        json={
            "subcontractor_id": subcontractor_id,
            "project_id": project_id,
            "title": title,
            "total_value": "125000.00",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert res.status_code == 201, f"agreement create failed: {res.text}"
    return res.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """A + B both hold an agreement with the SAME shared subcontractor.

    A owns project_A + agreement_A (confidential terms). B owns project_B +
    agreement_B. Both agreements reference the same global subcontractor S.
    """
    a_email, a_password = await _register(http_client, "a")
    await _set_role(a_email, "admin")
    a_headers = await _login(http_client, a_email, a_password)

    b_email, b_password = await _register(http_client, "b")
    # Manager (not admin): can seed its own agreement, stays project-scoped.
    await _set_role(b_email, "manager")
    b_headers = await _login(http_client, b_email, b_password)

    project_a = await _make_project(http_client, a_headers, "Subs-A")
    project_b = await _make_project(http_client, b_headers, "Subs-B")

    # Shared global subcontractor (created by A, referenced by both).
    sub = await http_client.post(
        "/api/v1/subcontractors/subcontractors/",
        json={"legal_name": f"Shared Trades GmbH {uuid.uuid4().hex[:6]}", "country": "DE"},
        headers=a_headers,
    )
    assert sub.status_code == 201, sub.text
    subcontractor_id = sub.json()["id"]

    agreement_a = await _make_agreement(
        http_client,
        a_headers,
        subcontractor_id=subcontractor_id,
        project_id=project_a,
        title="secret-agreement-marker A confidential rates",
    )
    agreement_b = await _make_agreement(
        http_client,
        b_headers,
        subcontractor_id=subcontractor_id,
        project_id=project_b,
        title="B own agreement",
    )

    return {
        "subcontractor_id": subcontractor_id,
        "a": {"headers": a_headers, "project_id": project_a, "agreement_id": agreement_a},
        "b": {"headers": b_headers, "project_id": project_b, "agreement_id": agreement_b},
    }


# ── IDOR vector ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stranger_cannot_see_foreign_agreements_via_subcontractor(http_client, two_tenants):
    """B listing by the SHARED subcontractor must only see B's own agreements."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/subcontractors/agreements/?subcontractor_id={two_tenants['subcontractor_id']}",
        headers=b["headers"],
    )
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()}
    assert a["agreement_id"] not in ids, f"LEAK: B saw A's agreement via shared subcontractor: {ids!r}"
    assert "secret-agreement-marker" not in resp.text, "LEAK: A's confidential terms leaked to B"
    # B still sees its own agreement (the filter must not over-block).
    assert b["agreement_id"] in ids, f"B lost its own agreement in the filtered list: {ids!r}"


# ── Regression guards ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_still_sees_all_agreements_for_subcontractor(http_client, two_tenants):
    """Admin A is unfiltered (accessible_project_ids -> None), so sees both."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/subcontractors/agreements/?subcontractor_id={two_tenants['subcontractor_id']}",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()}
    assert a["agreement_id"] in ids and b["agreement_id"] in ids, (
        f"admin should see every agreement for the subcontractor: {ids!r}"
    )


@pytest.mark.asyncio
async def test_owner_lists_own_agreement_by_project(http_client, two_tenants):
    """Regression: B can still list its own project's agreements."""
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/subcontractors/agreements/?project_id={b['project_id']}",
        headers=b["headers"],
    )
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()}
    assert b["agreement_id"] in ids, f"B cannot see its own project agreement: {ids!r}"


# ── Dashboard aggregates ───────────────────────────────────────────────────


async def _activate(*agreement_ids: str) -> None:
    """Mark agreements active straight in the database; activation itself is not under test."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.subcontractors.models import SubcontractAgreement

    async with async_session_factory() as s:
        await s.execute(
            update(SubcontractAgreement)
            .where(SubcontractAgreement.id.in_([uuid.UUID(i) for i in agreement_ids]))
            .values(status="active")
        )
        await s.commit()


@pytest.mark.asyncio
async def test_stranger_dashboard_counts_only_reachable_agreements(http_client, two_tenants):
    """The dashboard of a SHARED subcontractor must not count A's agreement for B.

    The agreement list is scoped, but the dashboard summed active agreements,
    open payment applications and retention over every project, so B could
    read A's activity and retention money from the totals.
    """
    a = two_tenants["a"]
    b = two_tenants["b"]
    await _activate(a["agreement_id"], b["agreement_id"])
    url = f"/api/v1/subcontractors/subcontractors/{two_tenants['subcontractor_id']}/dashboard"

    as_b = await http_client.get(url, headers=b["headers"])
    assert as_b.status_code == 200, as_b.text
    assert as_b.json()["active_agreements"] == 1, as_b.json()

    as_admin = await http_client.get(url, headers=a["headers"])
    assert as_admin.status_code == 200, as_admin.text
    assert as_admin.json()["active_agreements"] == 2, as_admin.json()
