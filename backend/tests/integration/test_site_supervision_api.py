# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site-supervision module - integration tests.

Covers the API contract end to end:

    1. Create a planned visit, conduct it (planned -> conducted), report it
       (conducted -> reported); reporting before conducting is rejected.
    2. Raise entries on a visit; motivated refusal requires a reason.
    3. plan-vs-fact reports overdue planned visits and a completion ratio.
    4. hidden-works register reflects acceptance status.
    5. Structured export uses neutral keys and lists the visit's entries.
    6. Cross-project IDOR: user B cannot read A's visit / entry.
    7. /meta returns localized labels for the requested locale.
    8. Owner can DELETE.

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
        from app.modules.site_supervision import models as _sup_models  # noqa: F401

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
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@supervision.io"
    password = f"Super{uuid.uuid4().hex[:6]}9"
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


async def _create_visit(client: AsyncClient, headers, project_id, **fields) -> dict:
    body = {"project_id": project_id, **fields}
    r = await client.post("/api/v1/site-supervision/visits/", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_visit_lifecycle_conduct_then_report(http_client, two_tenants):
    a = two_tenants["a"]
    visit = await _create_visit(
        http_client,
        a["headers"],
        a["project_id"],
        planned_date=_iso(-2),
        visitor="A. Inspector",
        discipline="structure",
    )
    assert visit["status"] == "planned"
    vid = visit["id"]

    # Cannot report before conducting.
    early = await http_client.post(f"/api/v1/site-supervision/visits/{vid}/report", headers=a["headers"])
    assert early.status_code == 400, early.text

    conducted = await http_client.post(f"/api/v1/site-supervision/visits/{vid}/conduct", headers=a["headers"])
    assert conducted.status_code == 200, conducted.text
    assert conducted.json()["status"] == "conducted"
    assert conducted.json()["actual_date"] is not None

    reported = await http_client.post(f"/api/v1/site-supervision/visits/{vid}/report", headers=a["headers"])
    assert reported.status_code == 200, reported.text
    assert reported.json()["status"] == "reported"


@pytest.mark.asyncio
async def test_entries_and_motivated_refusal(http_client, two_tenants):
    a = two_tenants["a"]
    visit = await _create_visit(http_client, a["headers"], a["project_id"], actual_date=_iso(0), status="conducted")
    vid = visit["id"]

    entry = await http_client.post(
        "/api/v1/site-supervision/entries/",
        json={
            "visit_id": vid,
            "ordinal": "1.1",
            "observation": "Cover to rebar below spec",
            "category": "deviation",
            "structured_fields": {"element": "Slab S1", "norm_ref": "EC2"},
        },
        headers=a["headers"],
    )
    assert entry.status_code == 201, entry.text
    eid = entry.json()["id"]
    assert entry.json()["status"] == "open"

    # Motivated refusal requires a reason.
    empty = await http_client.post(
        f"/api/v1/site-supervision/entries/{eid}/refuse",
        json={"reason": "   "},
        headers=a["headers"],
    )
    assert empty.status_code == 422, empty.text  # schema rejects blank reason

    refused = await http_client.post(
        f"/api/v1/site-supervision/entries/{eid}/refuse",
        json={"reason": "Does not meet EC2 cover requirement."},
        headers=a["headers"],
    )
    assert refused.status_code == 200, refused.text
    body = refused.json()
    assert body["status"] == "refused_motivated"
    assert body["structured_fields"]["refusal_reason"] == "Does not meet EC2 cover requirement."
    assert body["resolved_at"] is not None


@pytest.mark.asyncio
async def test_plan_vs_fact_reports_overdue(http_client, two_tenants):
    a = two_tenants["a"]
    project_id = await _create_project(a["uid"], "plan-vs-fact project")
    # One overdue planned visit, one conducted-on-plan.
    await _create_visit(http_client, a["headers"], project_id, planned_date=_iso(-5))
    await _create_visit(
        http_client, a["headers"], project_id, planned_date=_iso(-3), actual_date=_iso(-3), status="conducted"
    )

    r = await http_client.get(
        "/api/v1/site-supervision/plan-vs-fact",
        params={"project_id": project_id},
        headers=a["headers"],
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["planned_count"] == 2
    assert data["overdue_count"] == 1
    assert data["defined"] is True


@pytest.mark.asyncio
async def test_hidden_works_register(http_client, two_tenants):
    a = two_tenants["a"]
    project_id = await _create_project(a["uid"], "hidden-works project")
    visit = await _create_visit(http_client, a["headers"], project_id, actual_date=_iso(0), status="conducted")
    vid = visit["id"]
    await http_client.post(
        "/api/v1/site-supervision/entries/",
        json={"visit_id": vid, "category": "hidden_works", "observation": "Rebar", "status": "closed"},
        headers=a["headers"],
    )
    await http_client.post(
        "/api/v1/site-supervision/entries/",
        json={"visit_id": vid, "category": "hidden_works", "observation": "Waterproofing", "status": "open"},
        headers=a["headers"],
    )

    r = await http_client.get(
        "/api/v1/site-supervision/hidden-works",
        params={"project_id": project_id},
        headers=a["headers"],
    )
    assert r.status_code == 200, r.text
    reg = r.json()
    assert len(reg) == 2
    assert {row["accepted"] for row in reg} == {True, False}


@pytest.mark.asyncio
async def test_visit_export_structured(http_client, two_tenants):
    a = two_tenants["a"]
    visit = await _create_visit(
        http_client, a["headers"], a["project_id"], actual_date=_iso(0), status="conducted", discipline="mep"
    )
    vid = visit["id"]
    await http_client.post(
        "/api/v1/site-supervision/entries/",
        json={
            "visit_id": vid,
            "ordinal": "2.1",
            "category": "hidden_works",
            "observation": "Duct route",
            "structured_fields": {"element": "AHU-1", "location": "Roof", "norm_ref": "N/A", "required_action": "OK"},
        },
        headers=a["headers"],
    )

    r = await http_client.get(f"/api/v1/site-supervision/visits/{vid}/export", headers=a["headers"])
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["visit"]["discipline"] == "mep"
    assert len(doc["entries"]) == 1
    assert doc["entries"][0]["element"] == "AHU-1"
    assert doc["entries"][0]["required_action"] == "OK"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_project_idor_blocked(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    visit = await _create_visit(http_client, a["headers"], a["project_id"], planned_date=_iso(3))
    vid = visit["id"]

    got = await http_client.get(f"/api/v1/site-supervision/visits/{vid}/", headers=b["headers"])
    assert got.status_code in (403, 404), got.text

    listed = await http_client.get(
        "/api/v1/site-supervision/visits/",
        params={"project_id": a["project_id"]},
        headers=b["headers"],
    )
    assert listed.status_code in (403, 404), listed.text


@pytest.mark.asyncio
async def test_meta_localized_labels(http_client, two_tenants):
    a = two_tenants["a"]
    r = await http_client.get("/api/v1/site-supervision/meta", params={"locale": "ru"}, headers=a["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    categories = {row["code"]: row["label"] for row in body["entry_categories"]}
    assert categories["hidden_works"] == "Скрытые работы"
    disciplines = {row["code"]: row["label"] for row in body["disciplines"]}
    assert disciplines["structure"] == "Конструкции"


@pytest.mark.asyncio
async def test_delete_visit(http_client, two_tenants):
    a = two_tenants["a"]
    visit = await _create_visit(http_client, a["headers"], a["project_id"], planned_date=_iso(1))
    vid = visit["id"]
    deleted = await http_client.delete(f"/api/v1/site-supervision/visits/{vid}/", headers=a["headers"])
    assert deleted.status_code == 204, deleted.text
    gone = await http_client.get(f"/api/v1/site-supervision/visits/{vid}/", headers=a["headers"])
    assert gone.status_code == 404
