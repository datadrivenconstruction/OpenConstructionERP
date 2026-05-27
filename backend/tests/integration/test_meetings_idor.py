"""Meetings IDOR regression suite.

The ``/api/v1/meetings/`` router exposes endpoints keyed off
``meeting_id`` and ``project_id``. Most endpoints already gate access
via ``verify_project_access`` — but the transcript-import endpoint
historically accepted a ``project_id`` query parameter and went
straight to file parsing / meeting create without any project-ownership
verification. A viewer in tenant B could therefore POST a fake
transcript at tenant A's ``project_id`` and silently inject a fully
populated meeting into A's project.

Convention: cross-tenant access returns **404 Not Found**, not 403 —
matching ``verify_project_access`` so endpoints can't be used as a
UUID-existence oracle.

Scaffolding mirrors ``test_schedule_idor.py``: per-module temp SQLite
registered BEFORE any ``from app...`` import (see
``feedback_test_isolation.md``).
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-meetings-idor-"))
_TMP_DB = _TMP_DIR / "meetings_idor.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.meetings import models as _meetings_models  # noqa: F401

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


async def _register_and_login(
    client: AsyncClient,
    *,
    tenant: str,
) -> tuple[str, str, str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@meetings-idor.io"
    password = f"MeetingsIdor{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    user_id = reg.json()["id"]

    await _activate_user(email)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {tenant}: {login.text}"
    token = login.json()["access_token"]
    return user_id, email, password, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def two_meetings_tenants(http_client):
    """A owns a project; B is the attacker."""
    a_uid, a_email, a_password, _a_headers = await _register_and_login(
        http_client,
        tenant="a",
    )
    b_uid, b_email, _b_password, b_headers = await _register_and_login(
        http_client,
        tenant="b",
    )

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == a_email.lower()).values(role="admin", is_active=True))
        # Promote B to editor so they pass the meetings.create RBAC gate.
        # The IDOR we're hunting is at the project-ownership layer, not
        # the role-based one — B has the role, just not A's project.
        await s.execute(update(User).where(User.email == b_email.lower()).values(role="editor", is_active=True))
        await s.commit()

    a_login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": a_email, "password": a_password},
    )
    assert a_login.status_code == 200, a_login.text
    a_headers = {"Authorization": f"Bearer {a_login.json()['access_token']}"}

    # Re-login B so the editor role lands in the JWT.
    b_login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": b_email, "password": _b_password},
    )
    assert b_login.status_code == 200, b_login.text
    b_headers = {"Authorization": f"Bearer {b_login.json()['access_token']}"}

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Meetings-A {uuid.uuid4().hex[:6]}",
            "description": "owned by A — used by meetings IDOR tests",
            "currency": "EUR",
        },
        headers=a_headers,
    )
    assert proj.status_code == 201, f"project create failed: {proj.text}"
    project_id = proj.json()["id"]

    # Seed a meeting owned by A so cross-tenant reads have a target.
    mtg = await http_client.post(
        "/api/v1/meetings/",
        json={
            "project_id": project_id,
            "meeting_type": "progress",
            "title": "A confidential kickoff",
            "meeting_date": "2026-05-04",
            "status": "scheduled",
        },
        headers=a_headers,
    )
    assert mtg.status_code == 201, f"meeting create failed: {mtg.text}"
    meeting_id = mtg.json()["id"]

    return {
        "a": {
            "headers": a_headers,
            "project_id": project_id,
            "meeting_id": meeting_id,
        },
        "b": {"user_id": b_uid, "email": b_email, "headers": b_headers},
    }


# ── Read-leak vectors ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_get_tenant_a_meeting(http_client, two_meetings_tenants):
    a = two_meetings_tenants["a"]
    b = two_meetings_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/meetings/{a['meeting_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B read A's meeting: {resp.status_code} {resp.text!r}"
    assert "confidential kickoff" not in resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_list_tenant_a_meetings(http_client, two_meetings_tenants):
    a = two_meetings_tenants["a"]
    b = two_meetings_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/meetings/?project_id={a['project_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B listed A's meetings: {resp.status_code} {resp.text!r}"
    assert "confidential kickoff" not in resp.text


# ── Write IDOR vectors ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_import_summary_into_a_project(
    http_client,
    two_meetings_tenants,
):
    """``POST /import-summary/?project_id=A`` must NOT inject into A's project.

    Pre-fix the router skipped ``verify_project_access`` entirely — a
    viewer in tenant B could craft a transcript and silently create a
    completed meeting (with attendees + action items) in tenant A's
    project. This is a write-IDOR with permanent side effects.
    """
    a = two_meetings_tenants["a"]
    b = two_meetings_tenants["b"]

    # Transcript deliberately avoids weekday keywords ("Friday", "Monday", ...)
    # because the heuristic extractor stuffs them into ``due_date`` which
    # then fails ``ActionItemEntry``'s ISO-date regex with a 500 — masking
    # the IDOR vector we're actually probing for.
    transcript = (
        "Alice Attacker: This meeting was secretly injected by tenant B.\n"
        "Bob Co-Conspirator: We will leak the secrets.\n"
    )
    files = {"file": ("attack.txt", io.BytesIO(transcript.encode()), "text/plain")}

    resp = await http_client.post(
        f"/api/v1/meetings/import-summary/?project_id={a['project_id']}",
        files=files,
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B injected a meeting into A's project: {resp.status_code} {resp.text!r}"
    )

    # Belt-and-braces: nothing B-authored should have landed in A's
    # project listing.
    listing = await http_client.get(
        f"/api/v1/meetings/?project_id={a['project_id']}",
        headers=a["headers"],
    )
    assert listing.status_code == 200, listing.text
    titles = [m["title"] for m in listing.json()]
    assert all("attack" not in t.lower() for t in titles), (
        f"WRITE-IDOR: B's injected meeting appears in A's project: {titles!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_tenant_a_meeting(http_client, two_meetings_tenants):
    a = two_meetings_tenants["a"]
    b = two_meetings_tenants["b"]

    resp = await http_client.delete(
        f"/api/v1/meetings/{a['meeting_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B deleted A's meeting: {resp.status_code} {resp.text!r}"


# ── Regression guards ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_can_still_import_summary(http_client, two_meetings_tenants):
    """Regression: the IDOR fix must not break A's own import path."""
    a = two_meetings_tenants["a"]

    # Same caveat as the cross-tenant test — keep the transcript free of
    # weekday tokens so the heuristic doesn't poison ``ActionItemEntry``.
    transcript = (
        "Alice: Discussed foundation pour schedule for next week.\nBob: Action: order rebar before the deadline.\n"
    )
    files = {"file": ("ok.txt", io.BytesIO(transcript.encode()), "text/plain")}

    resp = await http_client.post(
        f"/api/v1/meetings/import-summary/?project_id={a['project_id']}",
        files=files,
        headers=a["headers"],
    )
    assert resp.status_code in (200, 201), (
        f"REGRESSION: owner A blocked from importing into own project: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_import_summary_handles_nonstandard_due_date_hints(
    http_client,
    two_meetings_tenants,
):
    """Transcript heuristic must NOT crash the endpoint when the speaker
    says "by Friday" / "by next week" / "by end of month".

    Pre-fix the heuristic extractor matched these phrases via
    ``_DUE_DATE_PATTERN`` and stuffed the captured weekday/keyword
    straight into ``ActionItemEntry.due_date`` — which enforces a
    strict ``^\\d{4}-\\d{2}-\\d{2}$`` regex.  The pydantic validation
    error escaped as a 500, leaving the project with a half-imported
    transcript (the heuristic step had already cross-linked the file
    into Documents before the crash).

    The fix coerces any non-ISO due_date hint to ``None`` and parks
    the raw phrase on metadata for downstream review.
    """
    a = two_meetings_tenants["a"]

    transcript = (
        "Alice: Update on foundation works.\n"
        "Bob: Action: order rebar by Friday.\n"
        "Alice: Action: send drawings by next week.\n"
        "Bob: Action: file permit by end of month.\n"
    )
    files = {
        "file": (
            "weekday-actions.txt",
            io.BytesIO(transcript.encode()),
            "text/plain",
        )
    }

    resp = await http_client.post(
        f"/api/v1/meetings/import-summary/?project_id={a['project_id']}",
        files=files,
        headers=a["headers"],
    )
    assert resp.status_code in (200, 201), (
        f"CRASH: heuristic-extracted weekday due_date crashed import: {resp.status_code} {resp.text!r}"
    )
    body = resp.json()
    # All action items must round-trip; none can have a non-ISO due_date.
    for ai in body.get("action_items", []):
        due = ai.get("due_date")
        if due is not None:
            assert isinstance(due, str) and len(due) == 10 and due[4] == "-" and due[7] == "-", (
                f"non-ISO due_date leaked into response: {due!r}"
            )


@pytest.mark.asyncio
async def test_create_meeting_rejects_foreign_document_ids(
    http_client,
    two_meetings_tenants,
):
    """A meeting's ``document_ids`` array must NOT cross project boundaries.

    Pre-fix the meetings router accepted any UUID in the
    ``document_ids`` list and stored it verbatim — meaning tenant A
    could attach a document_id that resolves to a confidential
    document inside tenant B's project. The document fetch endpoint
    is itself IDOR-safe (separate gate) so the file body never
    actually leaks, but the *reference* persisted on A's meeting
    sticks around forever and (a) leaks the existence of B's
    documents into A's meeting payload, and (b) breaks data integrity
    by allowing dangling cross-project FKs that no team can clean up
    without superuser DB access.

    The fix validates every document_id at create + update time and
    rejects the request with 422 if any document_id belongs to a
    different project. The integrity rule is symmetric — neither
    tenant can cross-link.
    """
    a = two_meetings_tenants["a"]

    # Spin up a second project owned by A and create a document inside
    # it. Then try to attach that document_id to a meeting in the
    # FIRST project (also owned by A). Even within a single tenant
    # this must be rejected because the integrity invariant is
    # per-project, not per-tenant.
    proj2 = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Meetings-A-2 {uuid.uuid4().hex[:6]}",
            "description": "second project of A — used for cross-project FK test",
            "currency": "EUR",
        },
        headers=a["headers"],
    )
    assert proj2.status_code == 201, proj2.text
    project_b = proj2.json()["id"]

    # Stuff a Document into project_b directly via the ORM (going
    # through the upload endpoint pulls in MIME / magic-byte
    # detection which is overkill for this audit).
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.documents.models import Document

    async with async_session_factory() as s:
        # owner uid: pull from A's first meeting to keep test
        # self-contained without depending on the fixture's user_id.
        doc = Document(
            project_id=uuid.UUID(project_b),
            name="confidential.pdf",
            description="document inside project_b — must not be linkable from project_a meeting",
            category="correspondence",
            file_size=100,
            mime_type="application/pdf",
            file_path="/tmp/never-read.pdf",
            version=1,
            uploaded_by="",
            tags=[],
        )
        s.add(doc)
        await s.commit()
        # Read back to get the assigned UUID.
        row = (await s.execute(select(Document).where(Document.project_id == uuid.UUID(project_b)))).scalars().first()
        foreign_document_id = str(row.id)

    # Try to create a meeting in project_a referencing the foreign doc.
    resp = await http_client.post(
        "/api/v1/meetings/",
        json={
            "project_id": a["project_id"],
            "meeting_type": "progress",
            "title": "Tries to cross-link a foreign doc",
            "meeting_date": "2026-05-08",
            "status": "scheduled",
            "document_ids": [foreign_document_id],
        },
        headers=a["headers"],
    )
    assert resp.status_code in (400, 404, 422), (
        f"INTEGRITY: meeting accepted foreign-project document_id: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_owner_can_still_read_own_meeting(http_client, two_meetings_tenants):
    a = two_meetings_tenants["a"]
    resp = await http_client.get(
        f"/api/v1/meetings/{a['meeting_id']}",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == a["meeting_id"]
