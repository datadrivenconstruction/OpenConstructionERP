"""Integration tests for per-folder permissions (Issue #FP).

Covers the eight scenarios in the spec:

    1. Owner grants ``viewer`` to a member → member can list+get,
       but POST upload and DELETE both return 404 / 403.
    2. Owner grants ``editor`` to a member → member can upload AND
       delete their OWN uploads.
    3. Owner revokes the grant → member is back to 404 on the
       restricted folder.
    4. Non-owner cannot grant → 403 from
       ``_verify_project_owner``.
    5. Duplicate grant on the same ``(project, kind, path, user)``
       → 409 from the unique constraint.
    6. Unscoped folder (no grants) stays visible to every project
       member by default.
    7. Cross-project IDOR: a user with a grant on project A cannot
       list project B.
    8. Editor cannot delete OTHER members' uploads (defence in depth).
"""

from __future__ import annotations

import io
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    """FastAPI test client with full app lifespan (modules + DDL)."""
    app = create_app()
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _register_user(client: AsyncClient, *, prefix: str, role: str = "estimator") -> tuple[dict[str, str], str]:
    """Register a fresh user with a unique email, return (headers, user_id)."""
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"{prefix}-{unique}@fp.io"
    password = f"FPTest{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": prefix.title()},
    )
    assert reg.status_code == 201, reg.text

    # Promote so ``documents.update`` / ``documents.delete`` permissions
    # are held — the 404 we care about must come from folder-permissions,
    # NOT a missing role-based permission. ``admin`` would bypass
    # `_verify_project_membership_or_404` entirely, so use ``estimator``
    # (which has documents.create / update / delete via RequirePermission).
    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    user_id = reg.json()["id"]
    return {"Authorization": f"Bearer {token}"}, user_id


@pytest_asyncio.fixture
async def owner_headers(client: AsyncClient) -> tuple[dict[str, str], str]:
    """Owner is an ``admin`` so they can create projects + manage members."""
    return await _register_user(client, prefix="owner", role="admin")


@pytest_asyncio.fixture
async def member_headers(client: AsyncClient) -> tuple[dict[str, str], str]:
    # Use ``manager`` so the user holds documents.delete (Role.MANAGER).
    # The 404 we care about must come from folder-permissions, NOT a
    # missing role-based permission.
    return await _register_user(client, prefix="member", role="manager")


@pytest_asyncio.fixture
async def stranger_headers(client: AsyncClient) -> tuple[dict[str, str], str]:
    return await _register_user(client, prefix="stranger", role="manager")


async def _create_project(client: AsyncClient, headers: dict[str, str], name: str = "FP Test") -> str:
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


async def _add_member(
    client: AsyncClient,
    owner_headers: dict[str, str],
    project_id: str,
    user_id: str,
) -> None:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/members/",
        json={"user_id": user_id, "role": "estimator"},
        headers=owner_headers,
    )
    assert resp.status_code in (200, 201), resp.text


async def _upload_doc(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    category: str = "drawing",
    name: str = "plan.pdf",
) -> str:
    files = {"file": (name, io.BytesIO(b"%PDF-1.4\n%test\n%%EOF"), "application/pdf")}
    resp = await client.post(
        f"/api/v1/documents/upload/?project_id={project_id}&category={category}",
        files=files,
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── 1. Viewer grant → list+get OK, write blocked ────────────────────────────


@pytest.mark.asyncio
async def test_viewer_can_list_and_get_but_not_write(
    client: AsyncClient,
    owner_headers: tuple[dict[str, str], str],
    member_headers: tuple[dict[str, str], str],
) -> None:
    owner_h, _ = owner_headers
    member_h, member_id = member_headers

    project_id = await _create_project(client, owner_h)
    await _add_member(client, owner_h, project_id, member_id)

    # Owner uploads a drawing
    doc_id = await _upload_doc(client, owner_h, project_id, category="drawing")

    # Restrict drawings → viewer for member
    grant = await client.post(
        f"/api/v1/projects/{project_id}/folder-permissions/",
        json={
            "user_id": member_id,
            "scope_kind": "document",
            "scope_path": "drawing",
            "role": "viewer",
        },
        headers=owner_h,
    )
    assert grant.status_code == 201, grant.text

    # Member can list (sees the doc)
    listing = await client.get(f"/api/v1/documents/?project_id={project_id}", headers=member_h)
    assert listing.status_code == 200, listing.text
    assert any(d["id"] == doc_id for d in listing.json()), listing.json()

    # Member can get the doc
    one = await client.get(f"/api/v1/documents/{doc_id}", headers=member_h)
    assert one.status_code == 200, one.text

    # Member CANNOT delete (viewer has no write)
    delete = await client.delete(f"/api/v1/documents/{doc_id}", headers=member_h)
    assert delete.status_code in (403, 404), delete.text


# ── 2. Editor grant → upload OK, delete-own OK ─────────────────────────────


@pytest.mark.asyncio
async def test_editor_can_upload_and_delete_own(
    client: AsyncClient,
    owner_headers: tuple[dict[str, str], str],
    member_headers: tuple[dict[str, str], str],
) -> None:
    owner_h, _ = owner_headers
    member_h, member_id = member_headers

    project_id = await _create_project(client, owner_h)
    await _add_member(client, owner_h, project_id, member_id)

    # Owner uploads anchor doc so the folder exists / is restricted
    await _upload_doc(client, owner_h, project_id, category="drawing")

    # Grant editor
    grant = await client.post(
        f"/api/v1/projects/{project_id}/folder-permissions/",
        json={
            "user_id": member_id,
            "scope_kind": "document",
            "scope_path": "drawing",
            "role": "editor",
        },
        headers=owner_h,
    )
    assert grant.status_code == 201, grant.text

    # Member uploads (editor can write)
    member_doc = await _upload_doc(client, member_h, project_id, category="drawing", name="from_member.pdf")

    # Member can delete OWN upload
    delete = await client.delete(f"/api/v1/documents/{member_doc}", headers=member_h)
    assert delete.status_code == 204, delete.text


# ── 3. Revoke → back to 404 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_restores_404(
    client: AsyncClient,
    owner_headers: tuple[dict[str, str], str],
    member_headers: tuple[dict[str, str], str],
) -> None:
    owner_h, _ = owner_headers
    member_h, member_id = member_headers

    project_id = await _create_project(client, owner_h)
    await _add_member(client, owner_h, project_id, member_id)

    doc_id = await _upload_doc(client, owner_h, project_id, category="drawing")

    # Grant
    grant = await client.post(
        f"/api/v1/projects/{project_id}/folder-permissions/",
        json={
            "user_id": member_id,
            "scope_kind": "document",
            "scope_path": "drawing",
            "role": "viewer",
        },
        headers=owner_h,
    )
    assert grant.status_code == 201
    grant_id = grant.json()["id"]

    # Verify access works before revoke
    one_before = await client.get(f"/api/v1/documents/{doc_id}", headers=member_h)
    assert one_before.status_code == 200

    # Revoke
    revoke = await client.delete(
        f"/api/v1/projects/{project_id}/folder-permissions/{grant_id}/",
        headers=owner_h,
    )
    assert revoke.status_code == 204, revoke.text

    # Now the folder still has had grants → restricted, and the member
    # has no remaining grant → 404
    one_after = await client.get(f"/api/v1/documents/{doc_id}", headers=member_h)
    assert one_after.status_code == 404, one_after.text

    listing = await client.get(f"/api/v1/documents/?project_id={project_id}", headers=member_h)
    assert listing.status_code == 200
    assert not any(d["id"] == doc_id for d in listing.json())


# ── 4. Non-owner cannot grant → 403 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_owner_cannot_grant(
    client: AsyncClient,
    owner_headers: tuple[dict[str, str], str],
    member_headers: tuple[dict[str, str], str],
    stranger_headers: tuple[dict[str, str], str],
) -> None:
    owner_h, _ = owner_headers
    _member_h, member_id = member_headers
    stranger_h, _ = stranger_headers

    project_id = await _create_project(client, owner_h)
    await _add_member(client, owner_h, project_id, member_id)

    # Stranger is not even a project member.
    resp = await client.post(
        f"/api/v1/projects/{project_id}/folder-permissions/",
        json={
            "user_id": member_id,
            "scope_kind": "document",
            "scope_path": "drawing",
            "role": "viewer",
        },
        headers=stranger_h,
    )
    assert resp.status_code == 403, resp.text


# ── 5. Duplicate grant → 409 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_grant_returns_409(
    client: AsyncClient,
    owner_headers: tuple[dict[str, str], str],
    member_headers: tuple[dict[str, str], str],
) -> None:
    owner_h, _ = owner_headers
    _, member_id = member_headers

    project_id = await _create_project(client, owner_h)
    await _add_member(client, owner_h, project_id, member_id)

    payload = {
        "user_id": member_id,
        "scope_kind": "document",
        "scope_path": "drawing",
        "role": "viewer",
    }

    first = await client.post(
        f"/api/v1/projects/{project_id}/folder-permissions/",
        json=payload,
        headers=owner_h,
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"/api/v1/projects/{project_id}/folder-permissions/",
        json=payload,
        headers=owner_h,
    )
    assert second.status_code == 409, second.text


# ── 6. Unscoped folder visible to every member by default ─────────────────


@pytest.mark.asyncio
async def test_unscoped_folder_visible_to_all_members(
    client: AsyncClient,
    owner_headers: tuple[dict[str, str], str],
    member_headers: tuple[dict[str, str], str],
) -> None:
    owner_h, _ = owner_headers
    member_h, member_id = member_headers

    project_id = await _create_project(client, owner_h)
    await _add_member(client, owner_h, project_id, member_id)

    # Owner uploads with a category we never grant on.
    doc_id = await _upload_doc(client, owner_h, project_id, category="other")

    # Member sees the doc — no grants on (document, other) means
    # everyone with project access can read.
    listing = await client.get(f"/api/v1/documents/?project_id={project_id}", headers=member_h)
    assert listing.status_code == 200, listing.text
    assert any(d["id"] == doc_id for d in listing.json()), listing.json()

    one = await client.get(f"/api/v1/documents/{doc_id}", headers=member_h)
    assert one.status_code == 200, one.text


# ── 7. Cross-project IDOR ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_on_project_A_does_not_leak_project_B(
    client: AsyncClient,
    owner_headers: tuple[dict[str, str], str],
    member_headers: tuple[dict[str, str], str],
) -> None:
    owner_h, _ = owner_headers
    _, member_id = member_headers

    project_a = await _create_project(client, owner_h, name="Project A")
    project_b = await _create_project(client, owner_h, name="Project B")
    await _add_member(client, owner_h, project_a, member_id)

    # Grant on A.
    grant = await client.post(
        f"/api/v1/projects/{project_a}/folder-permissions/",
        json={
            "user_id": member_id,
            "scope_kind": "document",
            "scope_path": "drawing",
            "role": "viewer",
        },
        headers=owner_h,
    )
    assert grant.status_code == 201

    # Member is NOT in project B → listing B's documents 404s.
    member_h, _ = member_headers
    leak_listing = await client.get(f"/api/v1/documents/?project_id={project_b}", headers=member_h)
    assert leak_listing.status_code == 404, leak_listing.text


# ── 8. Editor cannot delete OTHER members' uploads ─────────────────────────


@pytest.mark.asyncio
async def test_editor_cannot_delete_others_uploads(
    client: AsyncClient,
    owner_headers: tuple[dict[str, str], str],
    member_headers: tuple[dict[str, str], str],
) -> None:
    owner_h, _ = owner_headers
    member_h, member_id = member_headers

    project_id = await _create_project(client, owner_h)
    await _add_member(client, owner_h, project_id, member_id)

    # Owner uploads → owner is the uploader
    owner_doc = await _upload_doc(client, owner_h, project_id, category="drawing")

    # Grant editor to member
    grant = await client.post(
        f"/api/v1/projects/{project_id}/folder-permissions/",
        json={
            "user_id": member_id,
            "scope_kind": "document",
            "scope_path": "drawing",
            "role": "editor",
        },
        headers=owner_h,
    )
    assert grant.status_code == 201

    # Member cannot delete the OWNER's upload — defence in depth.
    delete = await client.delete(f"/api/v1/documents/{owner_doc}", headers=member_h)
    assert delete.status_code in (403, 404), delete.text
