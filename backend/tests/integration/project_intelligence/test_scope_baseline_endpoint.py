# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration test for POST /api/v1/project_intelligence/scope-baseline/.

Drives the scope-baseline capture end to end through the ASGI app:

    register+login an owner -> seed their project + a BOQ with priced leaves
    -> POST /scope-baseline/ (persists the leaf count into project metadata)
    -> GET /summary/ (the BOQ state now reports baseline_source='metadata'
       and the captured baseline_position_count).

Also pins the failure modes: a baseline-less BOQ returns 400, and a
cross-tenant caller is blocked by the IDOR guard (404/403) before any write.

Run:
    cd backend
    python -m pytest tests/integration/project_intelligence/test_scope_baseline_endpoint.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    fastapi_app = create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_login(client: AsyncClient, *, tenant: str, role: str = "admin") -> tuple[str, dict[str, str]]:
    """Register, activate, set role, log in. Returns (user_id, headers)."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"{tenant}-{uuid.uuid4().hex[:8]}@scope-baseline.io"
    password = f"Scope{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": tenant},
    )
    assert reg.status_code in (200, 201), reg.text
    user_id = reg.json()["id"]
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_project_with_boq(*, owner_id: str, leaf_count: int) -> uuid.UUID:
    """Seed a project owned by owner_id with one BOQ holding a section + leaves."""
    from app.database import async_session_factory
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        project = Project(
            id=uuid.uuid4(),
            name=f"Scope-{uuid.uuid4().hex[:6]}",
            owner_id=uuid.UUID(owner_id),
            currency="EUR",
            region="DACH",
            classification_standard="din276",
            metadata_={},
            fx_rates=[],
        )
        s.add(project)
        # Flush the project FIRST so its row exists before the BOQ FK insert.
        await s.flush()
        pid = project.id
        boq = BOQ(project_id=project.id, name="Main")
        s.add(boq)
        await s.flush()
        s.add(
            Position(
                boq_id=boq.id,
                parent_id=None,
                ordinal="01",
                description="Sec",
                unit="",
                quantity="0",
                unit_rate="0",
                total="0",
            )
        )
        await s.flush()
        section_id = (
            await s.execute(
                __import__("sqlalchemy").text("SELECT id FROM oe_boq_position WHERE boq_id = :b AND parent_id IS NULL"),
                {"b": str(boq.id)},
            )
        ).scalar()
        for i in range(leaf_count):
            s.add(
                Position(
                    boq_id=boq.id,
                    parent_id=section_id,
                    ordinal=f"01.{i:03d}",
                    description=f"L{i}",
                    unit="m3",
                    quantity="10",
                    unit_rate="100",
                    total="1000",
                )
            )
        await s.commit()
    return pid


@pytest.mark.asyncio
async def test_scope_baseline_persists_and_summary_reflects_it(http_client: AsyncClient) -> None:
    owner_id, headers = await _register_login(http_client, tenant="owner")
    pid = await _seed_project_with_boq(owner_id=owner_id, leaf_count=7)

    # Before capture: coverage baseline derives from the live count (source=current).
    pre = await http_client.get(f"/api/v1/project_intelligence/summary/?project_id={pid}&refresh=true", headers=headers)
    assert pre.status_code == 200, pre.text
    pre_boq = pre.json()["state"]["boq"]
    assert pre_boq["position_count"] == 7
    assert pre_boq["baseline_source"] == "current"

    # Capture the baseline.
    cap = await http_client.post(f"/api/v1/project_intelligence/scope-baseline/?project_id={pid}", headers=headers)
    assert cap.status_code == 200, cap.text
    body = cap.json()
    assert body["baseline_position_count"] == 7
    assert body["captured_at"]

    # After capture: the summary reports the metadata-sourced baseline.
    post = await http_client.get(
        f"/api/v1/project_intelligence/summary/?project_id={pid}&refresh=true", headers=headers
    )
    assert post.status_code == 200, post.text
    post_boq = post.json()["state"]["boq"]
    assert post_boq["baseline_position_count"] == 7
    assert post_boq["baseline_source"] == "metadata"


@pytest.mark.asyncio
async def test_scope_baseline_rejects_empty_boq(http_client: AsyncClient) -> None:
    owner_id, headers = await _register_login(http_client, tenant="empty")
    pid = await _seed_project_with_boq(owner_id=owner_id, leaf_count=0)
    resp = await http_client.post(f"/api/v1/project_intelligence/scope-baseline/?project_id={pid}", headers=headers)
    assert resp.status_code == 400, resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_scope_baseline_blocks_cross_tenant(http_client: AsyncClient) -> None:
    """A non-admin who does not own the project is blocked before any write."""
    owner_id, _ = await _register_login(http_client, tenant="ownerB")
    # The intruder is a non-admin editor (so RequirePermission passes) but does
    # not own the project, so the IDOR guard must reject them with 403.
    _, intruder_headers = await _register_login(http_client, tenant="intruder", role="editor")
    pid = await _seed_project_with_boq(owner_id=owner_id, leaf_count=3)
    resp = await http_client.post(
        f"/api/v1/project_intelligence/scope-baseline/?project_id={pid}", headers=intruder_headers
    )
    assert resp.status_code in (403, 404), resp.text
