"""Integration: CDE ↔ Transmittals revision backlink (RFC 33).

End-to-end:
    Create project → create container → create revision → create transmittal
    with ``revision_id`` on its item → ``GET /v1/cde/containers/{id}/transmittals``
    returns the link.

Uses the same module-scoped fixtures as the cross-module suite to avoid the
login rate limiter.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client():
    """Module-scoped client — full lifespan wired up once."""
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


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    """Register a user, promote to admin, and return auth headers.

    Registration assigns ``editor`` to every user except the first, so we
    elevate the user's role directly in the DB after registration (tests
    only, obviously) — then log in so the freshly-issued JWT carries the
    new role.
    """
    unique = uuid.uuid4().hex[:8]
    email = f"cde-audit-{unique}@test.io"
    password = f"CdeAudit{unique}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "CDE Audit Tester",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    # Promote to admin so gate checks in the CDE service pass.
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(
            sa_update(User).where(User.email == email).values(role="admin")
        )
        await s.commit()

    token = ""
    for attempt in range(3):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed after retries: {data}"
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"CDE Audit Project {uuid.uuid4().hex[:6]}",
            "description": "RFC 33 integration test",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Project create failed: {resp.text}"
    return resp.json()["id"]


# ── Tests ────────────────────────────────────────────────────────────────


class TestCDETransmittalBacklink:
    """RFC 33 §3.3 — revision link shows up on the container transmittal view."""

    async def test_revision_linked_via_transmittal_appears_in_backlink(
        self,
        client: AsyncClient,
        auth: dict[str, str],
        project_id: str,
    ) -> None:
        # 1. Create container.
        container_payload = {
            "project_id": project_id,
            "container_code": f"AUDIT-{uuid.uuid4().hex[:6]}",
            "title": "Integration test container",
        }
        r = await client.post(
            "/api/v1/cde/containers/",
            json=container_payload,
            headers=auth,
        )
        assert r.status_code == 201, r.text
        container_id = r.json()["id"]

        # 2. Create revision on it.
        r = await client.post(
            f"/api/v1/cde/containers/{container_id}/revisions/",
            json={
                "file_name": "drawing-rev-01.pdf",
                "storage_key": "uploads/audit/drawing.pdf",
                "mime_type": "application/pdf",
                "file_size": "12345",
            },
            headers=auth,
        )
        assert r.status_code == 201, r.text
        revision = r.json()
        revision_id = revision["id"]
        # Document cross-link must be populated now that storage_key was set.
        assert revision["document_id"] is not None, (
            "Expected document_id to be set after revision upload with storage_key"
        )

        # 3. Create transmittal with an item linked to the revision.
        tr_payload = {
            "project_id": project_id,
            "subject": "Issue drawings for coordination",
            "purpose_code": "for_information",
            "items": [
                {
                    "revision_id": revision_id,
                    "item_number": 1,
                    "description": "Drawing rev 01",
                },
            ],
        }
        r = await client.post(
            "/api/v1/transmittals/",
            json=tr_payload,
            headers=auth,
        )
        assert r.status_code == 201, r.text
        transmittal = r.json()
        transmittal_number = transmittal["transmittal_number"]
        # Item carries the revision_id too.
        assert transmittal["items"][0]["revision_id"] == revision_id

        # 4. Backlink endpoint returns the transmittal.
        r = await client.get(
            f"/api/v1/cde/containers/{container_id}/transmittals/",
            headers=auth,
        )
        assert r.status_code == 200, r.text
        links = r.json()
        assert len(links) == 1
        link = links[0]
        assert link["transmittal_number"] == transmittal_number
        assert link["revision_id"] == revision_id
        assert link["revision_code"] == revision["revision_code"]

    async def test_history_endpoint_returns_audit_row_after_promote(
        self,
        client: AsyncClient,
        auth: dict[str, str],
        project_id: str,
    ) -> None:
        # Fresh container to avoid interference with previous test.
        r = await client.post(
            "/api/v1/cde/containers/",
            json={
                "project_id": project_id,
                "container_code": f"AUDIT-HIST-{uuid.uuid4().hex[:6]}",
                "title": "History test container",
            },
            headers=auth,
        )
        assert r.status_code == 201, r.text
        container_id = r.json()["id"]

        # Promote WIP → SHARED (Gate A) — admin bypasses all role checks.
        r = await client.post(
            f"/api/v1/cde/containers/{container_id}/transition/",
            json={"target_state": "shared", "reason": "ready to share"},
            headers=auth,
        )
        assert r.status_code == 200, r.text

        # History must have exactly one row.
        r = await client.get(
            f"/api/v1/cde/containers/{container_id}/history/",
            headers=auth,
        )
        assert r.status_code == 200, r.text
        history = r.json()
        assert len(history) == 1
        row = history[0]
        assert row["from_state"] == "wip"
        assert row["to_state"] == "shared"
        assert row["gate_code"] == "A"
        assert row["reason"] == "ready to share"

    async def test_suitability_codes_endpoint(
        self,
        client: AsyncClient,
        auth: dict[str, str],
    ) -> None:
        r = await client.get("/api/v1/cde/suitability-codes/", headers=auth)
        assert r.status_code == 200
        body = r.json()
        assert "by_state" in body
        assert "codes" in body
        # WIP only has S0.
        wip_codes = [e["code"] for e in body["by_state"]["wip"]]
        assert wip_codes == ["S0"]
        # SHARED has S1-S4, S6, S7.
        shared_codes = [e["code"] for e in body["by_state"]["shared"]]
        assert "S1" in shared_codes
        assert "S2" in shared_codes
        # PUBLISHED has A1-A5.
        pub_codes = [e["code"] for e in body["by_state"]["published"]]
        assert "A1" in pub_codes
        assert "A5" in pub_codes

    async def test_gate_b_requires_signature(
        self,
        client: AsyncClient,
        auth: dict[str, str],
        project_id: str,
    ) -> None:
        # Create container starting in 'shared' so we're at Gate B.
        r = await client.post(
            "/api/v1/cde/containers/",
            json={
                "project_id": project_id,
                "container_code": f"AUDIT-GB-{uuid.uuid4().hex[:6]}",
                "title": "Gate B test",
                "cde_state": "shared",
            },
            headers=auth,
        )
        assert r.status_code == 201, r.text
        container_id = r.json()["id"]

        # Without signature → 400.
        r = await client.post(
            f"/api/v1/cde/containers/{container_id}/transition/",
            json={"target_state": "published"},
            headers=auth,
        )
        assert r.status_code == 400
        assert "approver_signature" in r.text

        # With signature → 200.
        r = await client.post(
            f"/api/v1/cde/containers/{container_id}/transition/",
            json={
                "target_state": "published",
                "approver_signature": "Integration Tester",
                "approval_comments": "Looks fine",
            },
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["cde_state"] == "published"
        last_approval = body["metadata"].get("last_approval")
        assert last_approval is not None
        assert last_approval["signature"] == "Integration Tester"
        assert last_approval["comments"] == "Looks fine"
