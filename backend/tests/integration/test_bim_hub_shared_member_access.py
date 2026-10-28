# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠BIM Hub shared-member read access regression (issue #271).

Pins the access policy for opening a BIM model in the viewer: a non-admin
user the project has been SHARED with (added via ``add_project_member``)
must be able to fetch the model through ``GET /api/v1/bim-hub/{model_id}`` -
the endpoint the viewer calls to load a model by id.

The reported defect: a shared non-admin project member could SEE a BIM file
in the project's documents list, but opening it in the viewer returned
"model not found"; granting that member admin made the same model open. The
cause was the BIM router's local ``_verify_project_access`` checking only
owner-or-admin, while the documents / BOQ / schedule read paths authorize
via the central ``verify_project_access`` (owner OR admin OR team-member).
The fix aligns the BIM helper with that central rule, so this suite proves:

* B (shared, non-admin VIEWER) CAN open the model        -> 200
* C (no relationship to the project) CANNOT              -> 404 (IDOR-safe)
* A (owner / admin) still CAN                            -> 200

Scaffolding mirrors ``test_bim_hub_idor.py`` (boot the app once, register /
activate / login real users over HTTP) and the sharing flow in
``test_team_member_project_access.py`` (``POST /projects/{id}/members/``).
The BIM model row is seeded directly via the DB because a real upload needs
the CAD converter; access control does not depend on how the row was created.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

# -- Fixtures ----------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.bim_hub import models as _bim_models  # noqa: F401
        from app.modules.projects import models as _project_models  # noqa: F401
        from app.modules.teams import models as _team_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, *, role: str) -> None:
    """Force ``role`` and ``is_active=True`` on a user via a direct DB write.

    New accounts are inactive under admin-approve registration; we flip the
    flag directly to keep the test focused on access control rather than the
    registration policy.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register(client: AsyncClient, *, tenant: str) -> tuple[str, str, str]:
    """Register a fresh user. Returns ``(uid, email, password)``."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@bim-share.io"
    password = f"BimShare{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    return reg.json()["id"], email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    """(Re-)login and return a fresh Bearer header carrying the current role claim."""
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {email}: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def shared_bim_scenario(http_client):
    """A owns a project + BIM model and shares it with B; C is unrelated.

    * A: admin owner (creates the project, seeds the model).
    * B: plain (non-admin) user added to the project as a ``viewer`` member -
      the legitimately-shared member who must be able to open the model.
    * C: plain (non-admin) user with no membership - the IDOR control.
    """
    a_uid, a_email, a_password = await _register(http_client, tenant="a")
    b_uid, b_email, b_password = await _register(http_client, tenant="b")
    c_uid, c_email, c_password = await _register(http_client, tenant="c")

    # A is admin (owner + seeder). B and C are deliberately NON-admin: B holds
    # the default role and gains access only through project membership, so a
    # 200 for B proves the shared-member authorization path, not an admin
    # bypass. They are activated so login works under admin-approve mode.
    await _set_role(a_email, role="admin")
    await _set_role(b_email, role="viewer")
    await _set_role(c_email, role="viewer")

    a_headers = await _login(http_client, a_email, a_password)
    b_headers = await _login(http_client, b_email, b_password)
    c_headers = await _login(http_client, c_email, c_password)

    # A creates the project over HTTP so it owns it the normal way.
    proj_resp = await http_client.post(
        "/api/v1/projects/",
        json={"name": "Shared-BIM-Project", "currency": "EUR"},
        headers=a_headers,
    )
    assert proj_resp.status_code in (200, 201), f"create project failed: {proj_resp.text}"
    project_id = proj_resp.json()["id"]

    # A shares the project with B (this is the "shared with another user" step
    # from the bug report) - B becomes a team member, C does not.
    add_resp = await http_client.post(
        f"/api/v1/projects/{project_id}/members/",
        json={"user_id": b_uid, "role": "viewer"},
        headers=a_headers,
    )
    assert add_resp.status_code in (200, 201), f"add member failed: {add_resp.text}"

    # Seed a ready BIM model under A's project (a real upload would require the
    # CAD converter; the access check is independent of how the row got there).
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMModel

    model_id = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            BIMModel(
                id=model_id,
                project_id=uuid.UUID(project_id),
                name="Shared-Tower.ifc",
                model_format="ifc",
                status="ready",
                created_by=uuid.UUID(a_uid),
                metadata_={},
            )
        )
        await s.commit()

    return {
        "project_id": project_id,
        "model_id": str(model_id),
        "a": {"user_id": a_uid, "headers": a_headers},
        "b": {"user_id": b_uid, "headers": b_headers},
        "c": {"user_id": c_uid, "headers": c_headers},
    }


# -- Tests -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_member_can_open_bim_model(http_client, shared_bim_scenario):
    """B (shared, non-admin) must be able to open the model in the viewer.

    This is the issue #271 regression: before the fix the BIM router only
    accepted owner/admin, so this returned 404 ("model not found") for a
    legitimately-shared member.
    """
    b = shared_bim_scenario["b"]
    model_id = shared_bim_scenario["model_id"]

    resp = await http_client.get(f"/api/v1/bim-hub/{model_id}", headers=b["headers"])
    assert resp.status_code == 200, (
        f"REGRESSION (issue #271): shared non-admin member could not open the BIM model "
        f"(status {resp.status_code}). Body: {resp.text!r}"
    )
    assert resp.json()["id"] == model_id


@pytest.mark.asyncio
async def test_unrelated_user_cannot_open_bim_model(http_client, shared_bim_scenario):
    """C (no membership) must still be denied - 404, not 403 (IDOR defence).

    Guards against the fix over-opening: only owner/admin/member may read the
    model. The 404 keeps "missing" and "denied" indistinguishable so a UUID
    cannot be probed for existence.
    """
    c = shared_bim_scenario["c"]
    model_id = shared_bim_scenario["model_id"]

    resp = await http_client.get(f"/api/v1/bim-hub/{model_id}", headers=c["headers"])
    assert resp.status_code == 404, (
        f"LEAK: unrelated user C could reach a BIM model they have no access to "
        f"(status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_owner_admin_can_open_bim_model(http_client, shared_bim_scenario):
    """A (owner / admin) can still open the model (positive control)."""
    a = shared_bim_scenario["a"]
    model_id = shared_bim_scenario["model_id"]

    resp = await http_client.get(f"/api/v1/bim-hub/{model_id}", headers=a["headers"])
    assert resp.status_code == 200, f"owner/admin A should be able to open the model: {resp.text}"
    assert resp.json()["id"] == model_id
