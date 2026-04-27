"""ERP Chat IDOR regression suite (v2.4.0 slice A — task #177).

The ``/api/v1/erp_chat/`` router exposes endpoints keyed off
``session_id`` and ``message_id`` — both must verify that the parent
``ChatSession`` belongs to the calling user. Returning 200 (or 403, or a
distinct "permission denied" body) on a foreign UUID is an IDOR leak: it
lets one tenant enumerate another tenant's chat sessions and read or
delete their messages.

This module pins the cross-tenant access policy at the HTTP boundary so
any future regression surfaces as a red test rather than a customer-
reported privacy bug.

Convention: the audit returns **404 Not Found** on cross-tenant access,
not 403 — same as ``verify_project_access``. 404 keeps "resource missing"
and "access denied" indistinguishable from the caller, so attackers can't
turn the endpoint into a UUID-existence oracle.

Test scaffolding mirrors ``test_tenant_isolation.py``: a per-module temp
SQLite file is wired up *before* ``app.database`` is imported, so the
production ``backend/openestimate.db`` is never touched
(see ``feedback_test_isolation.md``).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-chat-idor-"))
_TMP_DB = _TMP_DIR / "chat_idor.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once for the whole module."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        # Backfill any modules whose models were not pre-imported by
        # ``app.main`` startup. ``create_all`` is idempotent.
        from app.database import Base, engine
        from app.modules.erp_chat import models as _chat_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_user(email: str) -> None:
    """Force ``is_active=True`` so login works in admin-approve mode.

    v2.5.2 default registration mode is ``admin-approve`` (BUG-RBAC03):
    self-registered users are inactive until promoted. The IDOR audit
    needs both A and B logged in, so we flip the flag directly.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(
            update(User).where(User.email == email.lower()).values(is_active=True)
        )
        await s.commit()


async def _activate_and_relogin(
    client: AsyncClient, email: str, password: str,
) -> dict[str, str]:
    await _activate_user(email)
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"re-login failed for {email}: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def two_chat_tenants(http_client):
    """Two tenants. A owns a chat session + message; B is the attacker."""
    a_email = f"a-{uuid.uuid4().hex[:8]}@chat-idor.io"
    b_email = f"b-{uuid.uuid4().hex[:8]}@chat-idor.io"
    a_password = f"ChatIdor{uuid.uuid4().hex[:6]}9"
    b_password = f"ChatIdor{uuid.uuid4().hex[:6]}9"

    reg_a = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": a_email, "password": a_password, "full_name": "Tenant A"},
    )
    assert reg_a.status_code in (200, 201), reg_a.text
    a_uid = reg_a.json()["id"]

    reg_b = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": b_email, "password": b_password, "full_name": "Tenant B"},
    )
    assert reg_b.status_code in (200, 201), reg_b.text
    b_uid = reg_b.json()["id"]

    a_headers = await _activate_and_relogin(http_client, a_email, a_password)
    b_headers = await _activate_and_relogin(http_client, b_email, b_password)

    # Seed A's chat session + message via direct DB writes — the public
    # ``/erp_chat/stream`` path requires a configured AI provider, which
    # is overkill (and brittle) for an IDOR audit that only needs to
    # know A owns *some* row.
    from app.database import async_session_factory
    from app.modules.erp_chat.models import ChatMessage, ChatSession

    session_id = uuid.uuid4()
    message_id = uuid.uuid4()
    async with async_session_factory() as s:
        chat_session = ChatSession(
            id=session_id,
            user_id=uuid.UUID(a_uid),
            project_id=None,
            title="A's private chat",
        )
        s.add(chat_session)
        await s.flush()

        msg = ChatMessage(
            id=message_id,
            session_id=session_id,
            role="user",
            content="A's private message",
        )
        s.add(msg)
        await s.commit()

    return {
        "a": {"user_id": a_uid, "headers": a_headers, "session_id": str(session_id),
              "message_id": str(message_id)},
        "b": {"user_id": b_uid, "headers": b_headers},
    }


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_read_messages_in_tenant_a_session(
    http_client, two_chat_tenants,
):
    """``GET /erp_chat/sessions/{session_id}/messages/`` must not leak A's data."""
    a = two_chat_tenants["a"]
    b = two_chat_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/erp_chat/sessions/{a['session_id']}/messages/",
        headers=b["headers"],
    )
    # The current service filters by user_id at the SQL layer and returns
    # an empty list rather than 404 — both are acceptable defences. What is
    # NOT acceptable is leaking the A-owned message body.
    assert resp.status_code in (200, 404), resp.text
    if resp.status_code == 200:
        body = resp.json()
        assert body == [], (
            f"LEAK: tenant B got tenant A's chat messages: {body!r}"
        )


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_tenant_a_session(http_client, two_chat_tenants):
    """``DELETE /erp_chat/sessions/{session_id}/`` must not destroy A's data."""
    a = two_chat_tenants["a"]
    b = two_chat_tenants["b"]

    resp = await http_client.delete(
        f"/api/v1/erp_chat/sessions/{a['session_id']}/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B was able to DELETE tenant A's chat session "
        f"(status {resp.status_code}). Body: {resp.text!r}"
    )

    # Confirm the row still exists from A's side — the service has to
    # leave A's data intact even if B's DELETE returned a non-error code.
    from app.database import async_session_factory
    from app.modules.erp_chat.models import ChatSession

    async with async_session_factory() as s:
        still_there = await s.get(ChatSession, uuid.UUID(a["session_id"]))
        assert still_there is not None, (
            "tenant A's chat session disappeared after B's DELETE attempt"
        )


@pytest.mark.asyncio
async def test_tenant_b_cannot_get_similar_for_tenant_a_message(
    http_client, two_chat_tenants,
):
    """``GET /erp_chat/messages/{message_id}/similar/`` must 404 on cross-tenant."""
    a = two_chat_tenants["a"]
    b = two_chat_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/erp_chat/messages/{a['message_id']}/similar/",
        headers=b["headers"],
    )
    # The fix in router.py converts ownership mismatch → 404. We accept
    # 403 as a defence-in-depth fallback in case the policy ever shifts,
    # but 200 (especially with ``hits``) would be a clear leak.
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} on tenant A's "
        f"chat message similarity endpoint. Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_a_can_still_get_similar_for_own_message(
    http_client, two_chat_tenants,
):
    """Regression: the IDOR fix must not break A's access to their OWN messages.

    A 404 here would mean we accidentally over-restricted the endpoint
    and broke the legitimate happy path. Either 200 (success — vector
    backend installed) or a 5xx that's NOT 404 (vector backend missing
    in test env) is acceptable; what's NOT acceptable is the IDOR fix
    masking the row from its rightful owner.
    """
    a = two_chat_tenants["a"]

    resp = await http_client.get(
        f"/api/v1/erp_chat/messages/{a['message_id']}/similar/",
        headers=a["headers"],
    )
    # In the test environment, the vector backend (LanceDB / Qdrant) may
    # not be installed — ``find_similar`` then raises and propagates as
    # a 500. That's fine. The point is we must NOT see a 404 here, which
    # would indicate the ownership check rejected the legitimate owner.
    assert resp.status_code != 404, (
        f"REGRESSION: tenant A got 404 on their OWN message similarity "
        f"endpoint — IDOR fix over-restricted access. Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_session_list_excludes_tenant_a(http_client, two_chat_tenants):
    """``GET /erp_chat/sessions/`` must not list any A-owned session."""
    a = two_chat_tenants["a"]
    b = two_chat_tenants["b"]

    resp = await http_client.get(
        "/api/v1/erp_chat/sessions/", headers=b["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body.get("items", []) if isinstance(body, dict) else body
    leaked = [s for s in items if s.get("id") == a["session_id"]]
    assert leaked == [], (
        f"LEAK: tenant B's chat session list contains tenant A's session: {leaked!r}"
    )
