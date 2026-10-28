# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Work-type route classifier - integration tests.

Covers the API contract end to end:

    1. POST /classify is stateless and returns a route + rationale + confidence.
    2. Create a new_build assessment  -> auto-classified full_permit, draft.
    3. Create a major new_build        -> expertise_required.
    4. PATCH the criteria re-classifies and returns the row to draft.
    5. Confirm sets status=confirmed; an undetermined route cannot be confirmed.
    6. Cross-project IDOR: user B cannot list/read A's assessments.
    7. /meta and /work-types return localized labels for the requested locale.
    8. Owner can DELETE.

Scaffolding mirrors ``test_credentials_api.py`` - the engine is bound to the
conftest-provisioned PostgreSQL cluster before any test module imports.
"""

from __future__ import annotations

import uuid

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
        from app.modules.project_route import models as _route_models  # noqa: F401
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


async def _promote(client: AsyncClient, email: str, password: str, role: str) -> dict[str, str]:
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
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@projectroute.io"
    password = f"Route{uuid.uuid4().hex[:6]}9"
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
    # Tenant A owns the project under test and has to be able to create in it.
    # Registration cannot be relied on for that: self-registration only hands out
    # admin to the very first account on a fresh install, and every module in this
    # job shares one database, so exactly one of them wins that slot and the rest
    # get a viewer with no <module>.create permission. A was then refused 403 in
    # its own project and the cross-tenant probe below never ran. Promote it the
    # same way B is promoted. Manager, not admin, so A passes verify_project_access
    # on the ownership branch a real tenant would use rather than an admin bypass.
    # Manager rather than editor because project_route.delete sits at manager
    # while create and update sit at editor, and A exercises all three.
    a_uid, a_email, a_pw, _a_hdr = await _register_login(http_client, tenant="a")
    a_hdr = await _promote(http_client, a_email, a_pw, "manager")
    b_uid, b_email, b_pw, _b_hdr = await _register_login(http_client, tenant="b")
    b_hdr = await _promote(http_client, b_email, b_pw, "editor")
    a_project = await _create_project(a_uid, "A's project")
    b_project = await _create_project(b_uid, "B's project")
    return {
        "a": {"uid": a_uid, "headers": a_hdr, "project_id": a_project},
        "b": {"uid": b_uid, "headers": b_hdr, "project_id": b_project},
    }


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classify_is_stateless(http_client, two_tenants):
    a = two_tenants["a"]
    r = await http_client.post(
        "/api/v1/project-route/classify",
        json={"work_type": "capital_repair", "criteria": {"affects_structure": True}},
        headers=a["headers"],
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["determined_route"] == "full_permit"
    assert data["rationale"]
    assert 0.0 <= data["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_create_new_build_auto_classifies(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "work_type": "new_build",
        "criteria": {},
    }
    r = await http_client.post("/api/v1/project-route/assessments", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["determined_route"] == "full_permit"
    assert data["status"] == "draft"
    assert data["classified_at"] is not None


@pytest.mark.asyncio
async def test_create_major_new_build_needs_expertise(http_client, two_tenants):
    a = two_tenants["a"]
    body = {
        "project_id": a["project_id"],
        "work_type": "new_build",
        "criteria": {"scale": "major"},
    }
    r = await http_client.post("/api/v1/project-route/assessments", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    assert r.json()["determined_route"] == "expertise_required"


@pytest.mark.asyncio
async def test_patch_criteria_reclassifies_and_resets_to_draft(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/project-route/assessments",
        json={"project_id": a["project_id"], "work_type": "reconstruction", "criteria": {}},
        headers=a["headers"],
    )
    aid = create.json()["id"]
    assert create.json()["determined_route"] == "notification"

    # Confirm, then patch criteria - it should re-classify and drop back to draft.
    confirm = await http_client.post(
        f"/api/v1/project-route/assessments/{aid}/confirm",
        headers=a["headers"],
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "confirmed"

    patch = await http_client.patch(
        f"/api/v1/project-route/assessments/{aid}",
        json={"criteria": {"affects_structure": True}},
        headers=a["headers"],
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["determined_route"] == "full_permit"
    assert patch.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_undetermined_cannot_be_confirmed(http_client, two_tenants):
    a = two_tenants["a"]
    create = await http_client.post(
        "/api/v1/project-route/assessments",
        json={"project_id": a["project_id"], "work_type": "other", "criteria": {}},
        headers=a["headers"],
    )
    aid = create.json()["id"]
    assert create.json()["determined_route"] == "undetermined"

    confirm = await http_client.post(
        f"/api/v1/project-route/assessments/{aid}/confirm",
        headers=a["headers"],
    )
    assert confirm.status_code == 400, confirm.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_project_idor_blocked(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    created = await http_client.post(
        "/api/v1/project-route/assessments",
        json={"project_id": a["project_id"], "work_type": "demolition", "criteria": {}},
        headers=a["headers"],
    )
    # A 403 here means the arrange step failed, not the isolation check.
    # Without this the next line dies as KeyError: 'id' and hides the cause.
    assert created.status_code == 201, created.text
    aid = created.json()["id"]

    got = await http_client.get(f"/api/v1/project-route/assessments/{aid}", headers=b["headers"])
    assert got.status_code in (403, 404), got.text

    listed = await http_client.get(
        "/api/v1/project-route/assessments",
        params={"project_id": a["project_id"]},
        headers=b["headers"],
    )
    assert listed.status_code in (403, 404), listed.text


@pytest.mark.asyncio
async def test_meta_and_work_types_localized(http_client, two_tenants):
    a = two_tenants["a"]
    meta = await http_client.get("/api/v1/project-route/meta", params={"locale": "ru"}, headers=a["headers"])
    assert meta.status_code == 200, meta.text
    body = meta.json()
    work_types = {row["code"]: row["label"] for row in body["work_types"]}
    assert work_types["new_build"] == "Новое строительство"
    routes = {row["code"]: row["label"] for row in body["route_options"]}
    assert routes["full_permit"] == "Полное разрешение"

    wt = await http_client.get("/api/v1/project-route/work-types", params={"locale": "de"}, headers=a["headers"])
    assert wt.status_code == 200, wt.text
    de = {row["code"]: row["label"] for row in wt.json()}
    assert de["new_build"] == "Neubau"

    ro = await http_client.get("/api/v1/project-route/route-options", headers=a["headers"])
    assert ro.status_code == 200, ro.text
    assert any(row["code"] == "exempt" for row in ro.json())


@pytest.mark.asyncio
async def test_confirm_and_delete(http_client, two_tenants):
    a = two_tenants["a"]
    created = await http_client.post(
        "/api/v1/project-route/assessments",
        json={"project_id": a["project_id"], "work_type": "maintenance", "criteria": {}},
        headers=a["headers"],
    )
    aid = created.json()["id"]
    assert created.json()["determined_route"] == "exempt"

    confirm = await http_client.post(
        f"/api/v1/project-route/assessments/{aid}/confirm",
        headers=a["headers"],
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "confirmed"

    deleted = await http_client.delete(f"/api/v1/project-route/assessments/{aid}", headers=a["headers"])
    assert deleted.status_code == 204, deleted.text
    gone = await http_client.get(f"/api/v1/project-route/assessments/{aid}", headers=a["headers"])
    assert gone.status_code == 404
