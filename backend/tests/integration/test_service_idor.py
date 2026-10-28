"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service (field-service / PPM) schedule IDOR regression suite (issue #29).

PPM schedules do not carry a ``project_id`` of their own; they inherit their
tenant scope from a chain: ``ServiceSchedule -> ServiceAsset -> ServiceContract``
where the contract may be project-scoped. Pre-fix, the five schedule endpoints

    GET    /api/v1/service/schedules/?asset_id=<A>
    GET    /api/v1/service/schedules/{schedule_id}
    PATCH  /api/v1/service/schedules/{schedule_id}
    DELETE /api/v1/service/schedules/{schedule_id}
    POST   /api/v1/service/schedules/            (body carries asset_id)

trusted the supplied id and never walked that chain, so a caller from another
tenant could read, edit, delete or attach a maintenance schedule against a
competitor's asset just by knowing (or guessing) the id.

The fix gates each endpoint through ``_verify_contract_project`` on the asset's
contract, mirroring the asset endpoints. When the contract has no project
(customer-only contract) it falls back to tenant scope and does not gate, so
those rows stay reachable exactly as before.

Attacker B is a manager: the ``manager`` role clears every ``service.*`` RBAC
gate (create=editor, read=viewer, update=editor, delete=manager), so a denial
is the IDOR guard talking, not a premature 403. B is not an admin, so
``accessible_project_ids`` still scopes it.

Runs against the shared ``tests/conftest.py`` PostgreSQL cluster.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

# Markers that must never surface in a denied response body.
_SECRET_ASSET = "secret-asset-marker"

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.service import models as _svc_models  # noqa: F401

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
    email = f"{label}-{uuid.uuid4().hex[:8]}@svc-idor.io"
    password = f"SvcIdor{uuid.uuid4().hex[:6]}9!"
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


async def _make_contract(client: AsyncClient, headers: dict[str, str], *, project_id: str, title: str) -> str:
    res = await client.post(
        "/api/v1/service/contracts/",
        json={
            "customer_id": str(uuid.uuid4()),
            "project_id": project_id,
            "title": title,
            "period_start": "2026-01-01",
            "period_end": "2027-12-31",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert res.status_code == 201, f"contract create failed: {res.text}"
    return res.json()["id"]


async def _make_asset(client: AsyncClient, headers: dict[str, str], *, contract_id: str, name: str) -> str:
    res = await client.post(
        "/api/v1/service/assets/",
        json={"contract_id": contract_id, "asset_type": "boiler", "name": name},
        headers=headers,
    )
    assert res.status_code == 201, f"asset create failed: {res.text}"
    return res.json()["id"]


async def _make_schedule(client: AsyncClient, headers: dict[str, str], *, asset_id: str) -> str:
    res = await client.post(
        "/api/v1/service/schedules/",
        json={"asset_id": asset_id, "frequency": "quarterly", "next_due_date": "2027-03-01"},
        headers=headers,
    )
    assert res.status_code == 201, f"schedule create failed: {res.text}"
    return res.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """A owns a full project -> contract -> asset -> schedule chain; B is a stranger.

    B (manager) owns its own parallel chain so the positive controls can prove
    the guard does not over-block a legitimate owner.
    """
    a_email, a_password = await _register(http_client, "a")
    await _set_role(a_email, "admin")
    a_headers = await _login(http_client, a_email, a_password)

    b_email, b_password = await _register(http_client, "b")
    await _set_role(b_email, "manager")
    b_headers = await _login(http_client, b_email, b_password)

    project_a = await _make_project(http_client, a_headers, "Svc-A")
    contract_a = await _make_contract(http_client, a_headers, project_id=project_a, title="A confidential PPM")
    asset_a = await _make_asset(http_client, a_headers, contract_id=contract_a, name=_SECRET_ASSET)
    schedule_a = await _make_schedule(http_client, a_headers, asset_id=asset_a)

    project_b = await _make_project(http_client, b_headers, "Svc-B")
    contract_b = await _make_contract(http_client, b_headers, project_id=project_b, title="B own PPM")
    asset_b = await _make_asset(http_client, b_headers, contract_id=contract_b, name="b-own-asset")

    return {
        "a": {
            "headers": a_headers,
            "asset_id": asset_a,
            "schedule_id": schedule_a,
        },
        "b": {
            "headers": b_headers,
            "asset_id": asset_b,
        },
    }


# ── IDOR vectors (all five schedule endpoints) ─────────────────────────────


@pytest.mark.asyncio
async def test_stranger_cannot_read_foreign_schedule(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    resp = await http_client.get(f"/api/v1/service/schedules/{a['schedule_id']}", headers=b["headers"])
    assert resp.status_code == 404, resp.text
    assert _SECRET_ASSET not in resp.text


@pytest.mark.asyncio
async def test_stranger_cannot_list_schedules_for_foreign_asset(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    resp = await http_client.get(
        f"/api/v1/service/schedules/?asset_id={a['asset_id']}",
        headers=b["headers"],
    )
    assert resp.status_code == 404, resp.text
    assert a["schedule_id"] not in resp.text


@pytest.mark.asyncio
async def test_stranger_cannot_update_foreign_schedule(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    resp = await http_client.patch(
        f"/api/v1/service/schedules/{a['schedule_id']}",
        json={"frequency": "monthly"},
        headers=b["headers"],
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_stranger_cannot_delete_foreign_schedule(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    resp = await http_client.delete(f"/api/v1/service/schedules/{a['schedule_id']}", headers=b["headers"])
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_stranger_cannot_create_schedule_on_foreign_asset(http_client, two_tenants):
    """The create guard (POST body carries asset_id) is the write-IDOR closure."""
    a, b = two_tenants["a"], two_tenants["b"]
    resp = await http_client.post(
        "/api/v1/service/schedules/",
        json={"asset_id": a["asset_id"], "frequency": "quarterly", "next_due_date": "2027-06-01"},
        headers=b["headers"],
    )
    assert resp.status_code == 404, resp.text


# ── Positive controls (the guard must not over-block) ──────────────────────


@pytest.mark.asyncio
async def test_owner_can_read_own_schedule(http_client, two_tenants):
    a = two_tenants["a"]
    resp = await http_client.get(f"/api/v1/service/schedules/{a['schedule_id']}", headers=a["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == a["schedule_id"]


@pytest.mark.asyncio
async def test_owner_can_list_own_schedules(http_client, two_tenants):
    a = two_tenants["a"]
    resp = await http_client.get(
        f"/api/v1/service/schedules/?asset_id={a['asset_id']}",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert a["schedule_id"] in {row["id"] for row in resp.json()}


@pytest.mark.asyncio
async def test_manager_can_create_schedule_on_own_asset(http_client, two_tenants):
    """B is a manager and owns asset_b, so creating a schedule on it must pass."""
    b = two_tenants["b"]
    resp = await http_client.post(
        "/api/v1/service/schedules/",
        json={"asset_id": b["asset_id"], "frequency": "quarterly", "next_due_date": "2027-09-01"},
        headers=b["headers"],
    )
    assert resp.status_code == 201, resp.text
