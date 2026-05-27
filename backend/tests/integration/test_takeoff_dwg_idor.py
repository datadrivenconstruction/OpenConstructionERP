# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests pinning the DWG-takeoff IDOR sweep.

Round-6 audit caught that *every* endpoint in
``backend/app/modules/dwg_takeoff/router.py`` trusted the path / query
``drawing_id`` / ``annotation_id`` / ``group_id`` without verifying the
caller owns the underlying project. Any user with the basic
``dwg_takeoff.read`` permission could enumerate UUIDs and exfiltrate
foreign tenants' drawings, layers, entities, thumbnails, annotations
(which include measurement values feeding into BOQ totals), and saved
entity groups.

These tests fail on the pre-fix code (HTTP 200 returned) and pass after
the router calls ``verify_project_access`` on each resource. We assert
*404* (not 403) so the gate matches the "no leakage of UUID existence"
policy used elsewhere in the codebase.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _register_user(
    client: AsyncClient,
    *,
    admin: bool,
    role: str | None = None,
) -> tuple[dict[str, str], str]:
    """Register a fresh user with a specific role (or admin), return
    ``(Bearer headers, user_id)``.

    By default we register as ``manager`` so the user holds every
    permission needed by the dwg_takeoff endpoints (``create`` / ``read``
    / ``update`` / ``delete``) — that lets us assert IDOR behaviour
    against the gate itself rather than against an earlier perm-block.
    ``admin=True`` engages the admin-bypass branch of
    ``verify_project_access`` for the test that exercises it explicitly.
    """
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"dwgidor-{unique}@smoke.io"
    password = f"DwgIdor{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "DWG IDOR"},
    )
    assert reg.status_code == 201, reg.text
    user_id = reg.json()["id"]

    effective_role = "admin" if admin else (role or "manager")
    async with async_session_factory() as session:
        await session.execute(
            sa_update(User).where(User.email == email.lower()).values(role=effective_role, is_active=True),
        )
        await session.commit()

    token = ""
    for _ in range(2):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in (data.get("detail") or ""):
            await asyncio.sleep(2)
            continue
        break
    assert token, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {token}"}, user_id


async def _create_project(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "DWG IDOR project",
) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": name,
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _seed_drawing_directly(project_id: str, *, created_by: str = "") -> str:
    """Insert a DwgDrawing row directly. We skip the upload endpoint so the
    test stays deterministic (no ezdxf parse, no disk writes).
    """
    from app.database import async_session_factory
    from app.modules.dwg_takeoff.models import DwgDrawing

    async with async_session_factory() as session:
        drawing = DwgDrawing(
            project_id=uuid.UUID(project_id),
            name="A's plan",
            filename="a.dxf",
            file_format="dxf",
            file_path="/tmp/nonexistent.dxf",
            size_bytes=0,
            status="uploaded",
            created_by=created_by,
            metadata_={},
        )
        session.add(drawing)
        await session.flush()
        drawing_id = str(drawing.id)
        await session.commit()
        return drawing_id


async def _seed_annotation_directly(
    project_id: str,
    drawing_id: str,
    *,
    created_by: str = "",
) -> str:
    from app.database import async_session_factory
    from app.modules.dwg_takeoff.models import DwgAnnotation

    async with async_session_factory() as session:
        ann = DwgAnnotation(
            project_id=uuid.UUID(project_id),
            drawing_id=uuid.UUID(drawing_id),
            annotation_type="rectangle",
            geometry={"x": 0, "y": 0, "width": 10, "height": 10},
            color="#3b82f6",
            line_width=2,
            measurement_unit="m",
            metadata_={},
            created_by=created_by,
        )
        session.add(ann)
        await session.flush()
        ann_id = str(ann.id)
        await session.commit()
        return ann_id


async def _seed_group_directly(drawing_id: str, *, created_by: str = "") -> str:
    from app.database import async_session_factory
    from app.modules.dwg_takeoff.models import DwgEntityGroup

    async with async_session_factory() as session:
        grp = DwgEntityGroup(
            drawing_id=uuid.UUID(drawing_id),
            name="Group A",
            entity_ids=["e1", "e2"],
            metadata_={},
            created_by=created_by,
        )
        session.add(grp)
        await session.flush()
        gid = str(grp.id)
        await session.commit()
        return gid


# ── IDOR — drawings ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_drawing_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)

    project_a = await _create_project(client, a_headers, name="A project")
    drawing_id = await _seed_drawing_directly(project_a, created_by=a_id)

    # Confirm A can read it
    own = await client.get(f"/api/v1/dwg-takeoff/drawings/{drawing_id}", headers=a_headers)
    assert own.status_code == 200, own.text

    # B (foreign tenant) must NOT see it
    resp = await client.get(f"/api/v1/dwg-takeoff/drawings/{drawing_id}", headers=b_headers)
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_list_drawings_with_foreign_project_id_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A list")
    await _seed_drawing_directly(project_a, created_by=a_id)

    resp = await client.get(
        f"/api/v1/dwg-takeoff/drawings/?project_id={project_a}",
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_delete_drawing_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A del")
    drawing_id = await _seed_drawing_directly(project_a, created_by=a_id)

    resp = await client.delete(
        f"/api/v1/dwg-takeoff/drawings/{drawing_id}",
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_get_drawing_entities_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A ent")
    drawing_id = await _seed_drawing_directly(project_a, created_by=a_id)

    resp = await client.get(
        f"/api/v1/dwg-takeoff/drawings/{drawing_id}/entities/",
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_get_drawing_thumbnail_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A thumb")
    drawing_id = await _seed_drawing_directly(project_a, created_by=a_id)

    resp = await client.get(
        f"/api/v1/dwg-takeoff/drawings/{drawing_id}/thumbnail/",
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_patch_scale_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A scale")
    drawing_id = await _seed_drawing_directly(project_a, created_by=a_id)

    resp = await client.patch(
        f"/api/v1/dwg-takeoff/drawings/{drawing_id}/scale/",
        json={"scale_denominator": 50.0, "scale_mode": "preset"},
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_patch_layers_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A layers")
    drawing_id = await _seed_drawing_directly(project_a, created_by=a_id)

    resp = await client.patch(
        f"/api/v1/dwg-takeoff/drawings/{drawing_id}/layers",
        json={"layers": {"0": False}},
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


# ── IDOR — annotations ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_annotation_with_foreign_project_id_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A annCreate")
    drawing_a = await _seed_drawing_directly(project_a, created_by=a_id)

    resp = await client.post(
        "/api/v1/dwg-takeoff/annotations/",
        json={
            "project_id": project_a,
            "drawing_id": drawing_a,
            "annotation_type": "rectangle",
            "geometry": {"x": 0, "y": 0, "width": 10, "height": 10},
        },
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_list_annotations_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A annList")
    drawing_a = await _seed_drawing_directly(project_a, created_by=a_id)
    await _seed_annotation_directly(project_a, drawing_a, created_by=a_id)

    resp = await client.get(
        f"/api/v1/dwg-takeoff/annotations/?drawing_id={drawing_a}",
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_update_annotation_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A annU")
    drawing_a = await _seed_drawing_directly(project_a, created_by=a_id)
    ann_id = await _seed_annotation_directly(project_a, drawing_a, created_by=a_id)

    resp = await client.patch(
        f"/api/v1/dwg-takeoff/annotations/{ann_id}",
        json={"text": "should not write"},
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_delete_annotation_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A annD")
    drawing_a = await _seed_drawing_directly(project_a, created_by=a_id)
    ann_id = await _seed_annotation_directly(project_a, drawing_a, created_by=a_id)

    resp = await client.delete(
        f"/api/v1/dwg-takeoff/annotations/{ann_id}",
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_link_annotation_to_boq_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A annLink")
    drawing_a = await _seed_drawing_directly(project_a, created_by=a_id)
    ann_id = await _seed_annotation_directly(project_a, drawing_a, created_by=a_id)

    resp = await client.post(
        f"/api/v1/dwg-takeoff/annotations/{ann_id}/link-boq/",
        json={"position_id": "fake-position"},
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


# ── IDOR — entity groups ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_entity_group_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A grpC")
    drawing_a = await _seed_drawing_directly(project_a, created_by=a_id)

    resp = await client.post(
        "/api/v1/dwg-takeoff/groups/",
        json={"drawing_id": drawing_a, "entity_ids": ["e1"], "name": "X"},
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_list_entity_groups_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A grpL")
    drawing_a = await _seed_drawing_directly(project_a, created_by=a_id)
    await _seed_group_directly(drawing_a, created_by=a_id)

    resp = await client.get(
        f"/api/v1/dwg-takeoff/groups/?drawing_id={drawing_a}",
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_delete_entity_group_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A grpD")
    drawing_a = await _seed_drawing_directly(project_a, created_by=a_id)
    gid = await _seed_group_directly(drawing_a, created_by=a_id)

    resp = await client.delete(
        f"/api/v1/dwg-takeoff/groups/{gid}",
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_get_pins_cross_tenant_is_404(client: AsyncClient) -> None:
    a_headers, a_id = await _register_user(client, admin=False)
    b_headers, _ = await _register_user(client, admin=False)
    project_a = await _create_project(client, a_headers, name="A pins")
    drawing_a = await _seed_drawing_directly(project_a, created_by=a_id)

    resp = await client.get(
        f"/api/v1/dwg-takeoff/pins/?drawing_id={drawing_a}",
        headers=b_headers,
    )
    assert resp.status_code == 404, resp.text
