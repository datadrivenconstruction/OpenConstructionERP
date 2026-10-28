# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Smoke test for the Transmittals module (test-coverage audit 5).

Proves end-to-end wiring of the `oe_transmittals` module surface:

1. GET   /api/v1/transmittals/?project_id=...           (empty list)
2. POST  /api/v1/transmittals/                          (create draft)
3. GET   /api/v1/transmittals/{id}                      (happy path)
4. GET   /api/v1/transmittals/{missing-uuid}            (404)
5. PATCH /api/v1/transmittals/{id}                      (subject update)
6. POST  /api/v1/transmittals/{id}/issue/               (lock & 'issued')
7. PATCH /api/v1/transmittals/{id}                      (409 after lock)
8. DELETE on issued transmittal                         (409 audit guard)
9. RBAC: viewer role → 403 on the list endpoint
       (transmittals.* not registered in permission_registry,
        so non-admin roles must be denied)
10. DELETE a fresh DRAFT transmittal                    (204)
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _login_as(client: AsyncClient, role: str) -> tuple[str, dict[str, str]]:
    """Register a user, force the requested role + activate, log in.

    Returns (email, auth-header).
    """
    tag = uuid.uuid4().hex[:8]
    email = f"trn-{role}-{tag}@test.io"
    password = f"TrnTest{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Trn {role} {tag}",
            "role": role,
        },
    )
    assert reg.status_code in (200, 201), reg.text

    # Force-activate + force the requested role (registration may demote).
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            update(User).where(User.email == email.lower()).values(role=role, is_active=True),
        )
        await session.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return email, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_transmittals_smoke_full_lifecycle(client: AsyncClient):
    # Admin user for the happy-path CRUD lifecycle.
    _, header = await _login_as(client, "admin")

    # Create a project for the transmittal (FK target).
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "Transmittals Smoke", "description": "test-coverage audit 5"},
        headers=header,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    # ── 1. GET list — empty ──────────────────────────────────────────────
    empty = await client.get(
        "/api/v1/transmittals/",
        params={"project_id": project_id},
        headers=header,
    )
    assert empty.status_code == 200, empty.text
    body = empty.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["offset"] == 0
    assert body["limit"] == 50

    # ── 2. POST create — happy path ──────────────────────────────────────
    create_resp = await client.post(
        "/api/v1/transmittals/",
        json={
            "project_id": project_id,
            "subject": "Issued for Construction — L01 Walls",
            "purpose_code": "for_construction",
            "issued_date": "2026-05-28",
            "cover_note": "Please find attached the IFC drawings for L01.",
            "recipients": [
                {"action_required": "review"},
            ],
            "items": [
                {"item_number": 1, "description": "L01-A101 Floor Plan"},
            ],
        },
        headers=header,
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    transmittal_id = created["id"]
    assert created["status"] == "draft"
    assert created["is_locked"] is False
    assert created["transmittal_number"]  # auto-generated
    assert created["subject"] == "Issued for Construction — L01 Walls"
    assert len(created["recipients"]) == 1
    assert len(created["items"]) == 1

    # ── 3. GET by id — happy path ────────────────────────────────────────
    got = await client.get(
        f"/api/v1/transmittals/{transmittal_id}",
        headers=header,
    )
    assert got.status_code == 200, got.text
    assert got.json()["id"] == transmittal_id

    # ── 4. GET by id — 404 on bogus uuid ─────────────────────────────────
    missing = await client.get(
        f"/api/v1/transmittals/{uuid.uuid4()}",
        headers=header,
    )
    assert missing.status_code == 404, missing.text

    # ── 5. PATCH update — happy path on a draft transmittal ──────────────
    patched = await client.patch(
        f"/api/v1/transmittals/{transmittal_id}",
        json={"subject": "Revised subject — IFC drawings L01"},
        headers=header,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["subject"] == "Revised subject — IFC drawings L01"

    # ── 6. POST /issue — locks the transmittal ───────────────────────────
    issued = await client.post(
        f"/api/v1/transmittals/{transmittal_id}/issue/",
        headers=header,
    )
    assert issued.status_code == 200, issued.text
    issued_body = issued.json()
    assert issued_body["status"] == "issued"
    assert issued_body["is_locked"] is True

    # ── 7. PATCH after issue → 409 (locked) ──────────────────────────────
    locked_patch = await client.patch(
        f"/api/v1/transmittals/{transmittal_id}",
        json={"subject": "Should not be allowed"},
        headers=header,
    )
    assert locked_patch.status_code == 409, locked_patch.text

    # ── 8. DELETE issued transmittal → 409 (audit-trail guard) ───────────
    locked_delete = await client.delete(
        f"/api/v1/transmittals/{transmittal_id}",
        headers=header,
    )
    assert locked_delete.status_code == 409, locked_delete.text

    # ── 10. DELETE a fresh DRAFT — should succeed with 204 ───────────────
    fresh = await client.post(
        "/api/v1/transmittals/",
        json={
            "project_id": project_id,
            "subject": "Draft to delete",
            "purpose_code": "for_information",
        },
        headers=header,
    )
    assert fresh.status_code == 201, fresh.text
    fresh_id = fresh.json()["id"]
    deleted = await client.delete(
        f"/api/v1/transmittals/{fresh_id}",
        headers=header,
    )
    assert deleted.status_code == 204, deleted.text

    # And confirm it's gone.
    gone = await client.get(
        f"/api/v1/transmittals/{fresh_id}",
        headers=header,
    )
    assert gone.status_code == 404, gone.text


@pytest.mark.asyncio
async def test_transmittals_rbac_viewer_cannot_create(client: AsyncClient):
    """A viewer is refused the write surface, and only the write surface.

    This used to assert 403 on the read route too, on the premise that the
    module shipped no ``permissions.py`` and every non-admin role fell through
    ``RequirePermission``'s unknown-permission deny. The module registers its
    permissions now - ``transmittals.read`` at VIEWER, create and update at
    EDITOR, delete at MANAGER - so a viewer passes the read gate and the
    answer is then decided by project access: 404 for a project id that
    belongs to nobody, which is the no-leak answer rather than an RBAC
    verdict. Create is the gate that still refuses a viewer outright.
    """
    _, viewer_hdr = await _login_as(client, "viewer")

    # Read gate passes at VIEWER, so the random project id decides this one.
    unknown_project = await client.get(
        "/api/v1/transmittals/",
        params={"project_id": str(uuid.uuid4())},
        headers=viewer_hdr,
    )
    assert unknown_project.status_code == 404, unknown_project.text

    # Same for write surface — create attempt must also 403.
    forbidden_create = await client.post(
        "/api/v1/transmittals/",
        json={
            "project_id": str(uuid.uuid4()),
            "subject": "Forbidden create",
            "purpose_code": "for_information",
        },
        headers=viewer_hdr,
    )
    assert forbidden_create.status_code == 403, forbidden_create.text


@pytest.mark.asyncio
async def test_transmittals_named_recipients_and_issue(client: AsyncClient):
    """Create with a free-text recipient, add/remove one, then issue.

    Mirrors exactly what the UI now sends. The create form used to drop the
    typed recipients into metadata, so a UI-created transmittal had zero
    recipients and issuing always failed with 422. This proves the whole flow:
    a named recipient is stored with its name and email, recipients can be
    added and removed on the draft, and the transmittal issues once it has a
    recipient and an item.
    """
    _, header = await _login_as(client, "admin")

    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "Transmittals Recipients", "description": "recipients regression"},
        headers=header,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    # Create with a free-text recipient (name + email), exactly like the form.
    create_resp = await client.post(
        "/api/v1/transmittals/",
        json={
            "project_id": project_id,
            "subject": "For review - structural set",
            "purpose_code": "for_review",
            "recipients": [
                {"recipient_name": "Jane Site", "recipient_email": "jane@builder.example"},
            ],
            "items": [
                {"item_number": 1, "description": "S-101 General Arrangement"},
            ],
        },
        headers=header,
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    transmittal_id = created["id"]
    assert len(created["recipients"]) == 1
    assert created["recipients"][0]["recipient_name"] == "Jane Site"
    assert created["recipients"][0]["recipient_email"] == "jane@builder.example"

    # Add a second recipient through the post-hoc endpoint.
    add_resp = await client.post(
        f"/api/v1/transmittals/{transmittal_id}/recipients/",
        json={"recipient_name": "Sam Client"},
        headers=header,
    )
    assert add_resp.status_code == 201, add_resp.text
    added_recipient_id = add_resp.json()["id"]

    listed = await client.get(f"/api/v1/transmittals/{transmittal_id}", headers=header)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["recipients"]) == 2

    # Remove the second recipient again.
    remove_resp = await client.delete(
        f"/api/v1/transmittals/{transmittal_id}/recipients/{added_recipient_id}",
        headers=header,
    )
    assert remove_resp.status_code == 204, remove_resp.text

    after_remove = await client.get(f"/api/v1/transmittals/{transmittal_id}", headers=header)
    assert len(after_remove.json()["recipients"]) == 1

    # Removing a recipient that does not exist is a clean 404.
    missing_remove = await client.delete(
        f"/api/v1/transmittals/{transmittal_id}/recipients/{uuid.uuid4()}",
        headers=header,
    )
    assert missing_remove.status_code == 404, missing_remove.text

    # The remaining named recipient plus the item are enough to issue.
    issued = await client.post(
        f"/api/v1/transmittals/{transmittal_id}/issue/",
        headers=header,
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == "issued"

    # Once issued, recipients are frozen: adding one returns 409.
    frozen_add = await client.post(
        f"/api/v1/transmittals/{transmittal_id}/recipients/",
        json={"recipient_name": "Too Late"},
        headers=header,
    )
    assert frozen_add.status_code == 409, frozen_add.text
