"""End-to-end SSE rendering regression for GitHub issue #138 / task #249.

Issue #138 — "Chat IA no responde"
==================================
A user connected an OpenRouter LLM key. The OpenRouter dashboard showed
real token consumption (136 requests, 6.41M tokens) — proving the backend
reached the provider and the completion was billed — yet **no response
text ever appeared** in the OpenConstructionERP chat UI.

Two independent v3.6.1 defects produced that exact "tokens spent, UI
empty" symptom (both fixed by task #249, both pinned here):

1. ``_RejectNonFiniteJSONMiddleware.replay()`` returned a synthetic
   ``{"type": "http.disconnect"}`` on its second ``receive()`` call.
   Starlette's ``StreamingResponse`` runs ``listen_for_disconnect``
   concurrently with the body generator; the fake disconnect made that
   watcher return instantly and **cancel the SSE stream before a single
   byte was written** — HTTP 200 with a 0-byte body. The OpenRouter call
   still completed (it is ``await``-ed *inside* the generator before the
   first ``yield``), so tokens were billed while the UI got nothing.
2. The v3.6.1 frontend parser only read ``data:`` lines and switched on a
   non-existent ``chunk.type`` field. The backend ``_sse()`` puts the
   event name on a separate ``event:`` line and the payload carries NO
   ``type`` field, so even an intact stream rendered zero text.

Why this file exists
====================
``test_issue_138_model_override.py`` pins the *model-id* half of #138.
But the bug report's evidence (6.41M tokens billed across 136 requests)
proves the calls *succeeded* — a wrong/unfunded model would have errored,
not billed. The unrendered-completion failure was never covered
end-to-end. This suite drives the **real FastAPI app with the full
middleware stack** (incl. ``_RejectNonFiniteJSONMiddleware`` and the
``BaseHTTPMiddleware`` chain), a configured **OpenRouter** provider, and
a faithful port of the production ``useChatFullPage.ts`` SSE parser, then
asserts the assistant text actually renders for OpenRouter-shaped
responses — including OpenRouter's real quirks (multiline content,
reasoning-only completions).

A v3.6.1 backend would fail ``test_*_streams_nonzero_body`` (0-byte
body). A v3.6.1 frontend parser would fail ``test_*_renders_in_ui``.

No network: ``httpx.AsyncClient.post`` is monkeypatched to return canned
OpenRouter-shaped bodies. Per-module temp SQLite — the production
``backend/openestimate.db`` is never touched.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-138-sse-"))
_TMP_DB = _TMP_DIR / "issue138_sse.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ════════════════════════════════════════════════════════════════════════════
# Faithful port of the production frontend SSE parser
# (frontend/src/features/erp-chat/full-page/useChatFullPage.ts, post-#249).
#
# It tracks the ``event:`` line and resets it on a blank-line frame
# terminator, exactly like the TS code. If this port renders text from the
# captured bytes, the real browser parser does too — and a v3.6.1-style
# parser (``data:``-only + ``chunk.type``) would render nothing.
# ════════════════════════════════════════════════════════════════════════════


def _render_like_frontend(raw: str) -> dict[str, Any]:
    """Replay the streamed SSE text through the production parser logic.

    Returns the rendered assistant ``content``, the session id, any error
    text, and the ordered list of (event, payload) frames — mirroring the
    state the React hook would hold after the stream completes.
    """
    content = ""
    session_id: str | None = None
    error_text: str | None = None
    frames: list[tuple[str, dict[str, Any]]] = []

    current_event = ""
    # The hook splits the rolling buffer on "\n" and keeps the last partial
    # line. Feeding the whole captured body at once is equivalent to the
    # streamed case for assertion purposes (the hook's buffer logic only
    # affects *when* a line is seen, not *whether*).
    buffer = raw
    lines = buffer.split("\n")
    for raw_line in lines:
        line = raw_line.rstrip("\r")
        if line.strip() == "":
            current_event = ""
            continue
        if line.startswith("event:"):
            current_event = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        json_str = line[5:].strip()
        if not json_str or json_str == "[DONE]":
            continue
        try:
            payload = json.loads(json_str)
        except json.JSONDecodeError:
            continue
        frames.append((current_event, payload))
        if current_event == "session_id":
            session_id = payload.get("session_id")
        elif current_event == "text":
            chunk = payload.get("content")
            if chunk:
                content += chunk
        elif current_event == "error":
            error_text = payload.get("message", "Unknown error")

    return {
        "content": content,
        "session_id": session_id,
        "error": error_text,
        "frames": frames,
    }


# ── OpenRouter-shaped (non-stream) response bodies ──────────────────────────
#
# The backend calls OpenRouter NON-streaming (one blocking POST), then
# re-chunks the final text into ``event: text`` SSE frames. So the only
# OpenRouter-specific surface is the JSON response shape. These mirror real
# OpenRouter payloads, including the quirks that previously risked silent
# text loss.

_OPENROUTER_PLAIN = {
    "id": "gen-or-1",
    "model": "anthropic/claude-sonnet-4",
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": (
                    "Here is your construction estimate.\n\n"
                    "- Concrete C30/37: 12.5 m³\n"
                    'Quote: "two layers" of rebar.\tTab + unicode: €1.234,56'
                ),
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 1200, "completion_tokens": 340, "total_tokens": 1540},
}

# OpenRouter reasoning models (deepseek-r1, o1, ...) routinely return the
# answer ONLY in ``reasoning`` with ``content`` empty — and burn the huge
# token counts seen in the bug report (~47k tok/req × 136 ≈ 6.41M).
_OPENROUTER_REASONING_ONLY = {
    "id": "gen-or-2",
    "model": "deepseek/deepseek-r1",
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": "",
                "reasoning": "The slab area is 240 m². At 0.2 m thickness that is 48 m³ of concrete.",
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 900, "completion_tokens": 46000, "total_tokens": 46900},
}


def _install_fake_openrouter(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]) -> dict[str, Any]:
    """Monkeypatch ``httpx.AsyncClient.post`` to answer like OpenRouter.

    Records the outgoing request so we can assert the call really happened
    (tokens "billed") even though the test is offline.
    """
    import httpx

    captured: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return body

        def raise_for_status(self) -> None:
            return None

    async def _fake_post(self_client, url, *args, **kwargs):  # noqa: ANN001
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post, raising=True)
    return captured


# ── App / client fixtures ───────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.ai import models as _ai_models  # noqa: F401
        from app.modules.erp_chat import models as _chat_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


@pytest_asyncio.fixture(scope="module")
async def openrouter_user(http_client):
    """A registered user whose AISettings has an OpenRouter key + model
    override — the exact configuration from the #138 bug report. The key is
    stored through the real Fernet ``encrypt_secret`` path."""
    email = f"or-{uuid.uuid4().hex[:8]}@issue138.io"
    password = f"Issue138{uuid.uuid4().hex[:6]}9"

    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "OR User"},
    )
    assert reg.status_code in (200, 201), reg.text
    user_id = reg.json()["id"]

    await _activate(email)
    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Persist OpenRouter settings directly (real crypto, real ORM).
    from app.core.crypto import encrypt_secret
    from app.database import async_session_factory
    from app.modules.ai.models import AISettings

    async with async_session_factory() as s:
        s.add(
            AISettings(
                user_id=uuid.UUID(user_id),
                openrouter_api_key=encrypt_secret("sk-or-v1-EXAMPLE-not-real"),
                preferred_model="openrouter",
                metadata_={"model_overrides": {"openrouter": "anthropic/claude-sonnet-4"}},
            )
        )
        await s.commit()

    return {"user_id": user_id, "headers": headers}


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _post_stream(http_client, headers, message: str) -> tuple[int, str]:
    """POST the chat-stream endpoint through the full ASGI middleware stack
    and return ``(status_code, full_decoded_body)``."""
    chunks: list[bytes] = []
    async with http_client.stream(
        "POST",
        "/api/v1/erp_chat/stream/",
        headers={**headers, "Content-Type": "application/json"},
        json={"message": message},
    ) as resp:
        status = resp.status_code
        async for chunk in resp.aiter_raw():
            chunks.append(chunk)
    return status, b"".join(chunks).decode("utf-8", "replace")


# ════════════════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════════════════


class TestOpenRouterChatRendersEndToEnd:
    """The #138 acceptance criteria: an OpenRouter completion that the
    provider billed must reach the UI as visible assistant text — through
    the real middleware stack and the real frontend parser."""

    @pytest.mark.asyncio
    async def test_plain_openrouter_streams_nonzero_body(self, http_client, openrouter_user, monkeypatch):
        """#249 backend guard: the SSE body must be non-empty.

        On v3.6.1 the ``http.disconnect`` replay cancelled the stream and
        this body was 0 bytes (HTTP 200, empty) — the literal bug.
        """
        captured = _install_fake_openrouter(monkeypatch, _OPENROUTER_PLAIN)

        status, body = await _post_stream(http_client, openrouter_user["headers"], "Estimate a concrete wall")

        assert status == 200, body
        assert body, "SSE body is EMPTY — this is the v3.6.1 #138 regression"
        # The OpenRouter HTTP call really happened (tokens would be billed).
        assert "openrouter.ai" in captured["url"]
        assert captured["json"]["model"] == "anthropic/claude-sonnet-4"
        # Backend SSE framing is intact through every middleware layer.
        assert "event: session_id" in body
        assert "event: text" in body
        assert "event: done" in body
        assert "\n\n" in body  # frame delimiters survived

    @pytest.mark.asyncio
    async def test_plain_openrouter_renders_in_ui(self, http_client, openrouter_user, monkeypatch):
        """End-to-end: feed the captured bytes through the production
        ``useChatFullPage.ts`` parser port and assert text renders."""
        _install_fake_openrouter(monkeypatch, _OPENROUTER_PLAIN)

        _status, body = await _post_stream(http_client, openrouter_user["headers"], "Estimate a concrete wall")
        ui = _render_like_frontend(body)

        assert ui["error"] is None, f"unexpected error frame: {ui['error']}"
        assert ui["session_id"], "no session_id rendered"
        # The full multiline OpenRouter answer reassembled across the
        # 50-char SSE text chunks the backend emits.
        assert "Here is your construction estimate." in ui["content"]
        assert "Concrete C30/37: 12.5 m³" in ui["content"]
        assert '"two layers"' in ui["content"]  # JSON-escaped quote survived
        assert "€1.234,56" in ui["content"]  # unicode survived
        full = (
            "Here is your construction estimate.\n\n"
            "- Concrete C30/37: 12.5 m³\n"
            'Quote: "two layers" of rebar.\tTab + unicode: €1.234,56'
        )
        assert ui["content"] == full, "rendered text != provider completion"

    @pytest.mark.asyncio
    async def test_openrouter_reasoning_only_still_renders(self, http_client, openrouter_user, monkeypatch):
        """OpenRouter reasoning models (deepseek-r1/o1) return the answer
        only in ``reasoning`` with empty ``content`` — and burn the massive
        token counts from the bug report. The completion the user PAID for
        must still render, never be silently dropped."""
        _install_fake_openrouter(monkeypatch, _OPENROUTER_REASONING_ONLY)

        _status, body = await _post_stream(http_client, openrouter_user["headers"], "How much concrete for the slab?")
        ui = _render_like_frontend(body)

        assert ui["error"] is None, f"reasoning completion was dropped: {ui['error']}"
        assert "48 m³ of concrete" in ui["content"], (
            "OpenRouter reasoning-only answer was billed but not rendered — "
            "exactly the #138 'tokens spent, UI empty' symptom"
        )

    @pytest.mark.asyncio
    async def test_no_unconsumed_disconnect_truncation(self, http_client, openrouter_user, monkeypatch):
        """Direct #249 middleware guard: the FULL stream (through to the
        terminal ``done`` frame) is delivered. A reintroduced
        ``http.disconnect`` replay would truncate before ``done``."""
        _install_fake_openrouter(monkeypatch, _OPENROUTER_PLAIN)

        _status, body = await _post_stream(http_client, openrouter_user["headers"], "ping")
        # The generator yields ``done`` LAST. Its presence proves the
        # stream was not cancelled mid-flight by a synthetic disconnect.
        assert body.rstrip().endswith(["event: done", 'data: {"session_id":'][0]) is False
        assert "event: done" in body
        done_idx = body.index("event: done")
        text_idx = body.index("event: text")
        assert text_idx < done_idx, "text must arrive before the terminal done frame"
