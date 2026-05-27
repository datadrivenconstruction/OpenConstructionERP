"""Baseline tests for the compliance_ai router (v3.9.1+).

Covers the contract a future maintainer is likely to break first:

* **Unauthenticated → 401** — the NL endpoint must never run without a
  resolved JWT subject. Closes the LLM-cost path that would otherwise
  let an anonymous scripted client burn provider tokens.
* **Happy-path pattern match → 200 with canonical envelope** — verifies
  the verdict shape (``dsl_definition`` / ``dsl_yaml`` / ``confidence``
  / ``used_method`` / ``matched_pattern``) and that a deterministic
  pattern hit returns ``used_method == "pattern"`` (the LLM was not
  consulted — no token spend).
* **Rate-limit short-circuit → 429** — overrides the rate-limit
  dependency to assert that ``check_ai_rate_limit`` is reached *before*
  the LLM caller is built. Regression guard against someone removing
  the ``Depends(check_ai_rate_limit)`` line in the future.
* **AI fallback with mocked caller** — confirms the service injects the
  ``ai_caller`` only when ``use_ai=True`` and that a broken AI reply
  (invalid YAML) degrades to a low-confidence envelope, not a 500.

Per ``feedback_test_isolation.md`` the module redirects ``DATABASE_URL``
to a fresh temp SQLite BEFORE any ``app`` import.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-compliance-ai-"))
_TMP_DB = _TMP_DIR / "compliance_ai.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest_asyncio  # noqa: E402
from fastapi import HTTPException, status  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_factory():
    """Boot the FastAPI app once per module against the temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


def _override_payload(app, user_id: uuid.UUID) -> None:
    """Inject a fake JWT payload so the route's auth gates see the caller."""
    from app.dependencies import get_current_user_payload

    async def _payload() -> dict:
        return {
            "sub": str(user_id),
            "role": "editor",
            "permissions": [],
        }

    app.dependency_overrides[get_current_user_payload] = _payload


# ── Tests ─────────────────────────────────────────────────────────────────


async def test_from_nl_requires_auth_returns_401(app_factory):
    """No JWT → 401 (FastAPI's HTTPBearer default) — never 200, never 500."""
    app = app_factory
    # Ensure no payload override is in place.
    app.dependency_overrides.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/compliance-ai/from-nl",
            json={"text": "all walls must have fire_rating"},
        )
    # FastAPI's HTTPBearer returns 403 by default when the header is
    # missing; the project's get_current_user_payload normalises to 401
    # for "no token". Accept either — both prove the route is gated.
    assert resp.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ), resp.text


async def test_from_nl_happy_path_pattern_match(app_factory):
    """Deterministic pattern hit returns the canonical verdict envelope.

    The pattern matcher is offline / LLM-free, so this asserts both the
    happy-path verdict *and* that the AI was never consulted (``used_
    method == 'pattern'``). No LLM mock is needed — the deterministic
    path is the cost-free fast path the router prefers.
    """
    app = app_factory
    user_id = uuid.uuid4()
    _override_payload(app, user_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/compliance-ai/from-nl",
                json={
                    "text": "all walls must have fire_rating",
                    "lang": "en",
                    "use_ai": False,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # Canonical envelope shape — every key the UI consumes is present.
        for key in (
            "dsl_definition",
            "dsl_yaml",
            "confidence",
            "used_method",
            "matched_pattern",
            "errors",
            "suggestions",
        ):
            assert key in body, f"missing key in verdict envelope: {key}"

        # Pattern won — LLM was not consulted (no token spend).
        assert body["used_method"] == "pattern"
        assert body["matched_pattern"] == "must_have"
        assert body["confidence"] >= 0.85
        assert body["dsl_definition"]["scope"] == "wall"
        assert body["dsl_definition"]["expression"]["forEach"] == "wall"
        # YAML render succeeded (string, not None).
        assert isinstance(body["dsl_yaml"], str)
        assert "scope: wall" in body["dsl_yaml"]
    finally:
        app.dependency_overrides.clear()


async def test_from_nl_rate_limit_returns_429(app_factory):
    """Override ``check_ai_rate_limit`` to raise — confirms the dep is wired.

    Regression guard: if a future refactor drops the
    ``Depends(check_ai_rate_limit)`` line on the route, this test fails
    because the override is never reached and the call returns 200.
    """
    app = app_factory
    user_id = uuid.uuid4()
    _override_payload(app, user_id)

    from app.dependencies import check_ai_rate_limit

    async def _always_429() -> int:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI rate limit exceeded. Please wait a moment and try again.",
            headers={"Retry-After": "60"},
        )

    app.dependency_overrides[check_ai_rate_limit] = _always_429
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/compliance-ai/from-nl",
                json={"text": "all walls must have fire_rating"},
            )
        assert resp.status_code == 429, resp.text
        assert resp.headers.get("retry-after") == "60"
    finally:
        app.dependency_overrides.clear()


async def test_from_nl_ai_fallback_invalid_yaml_does_not_500(monkeypatch):
    """Service layer must absorb a broken AI response, never bubble 500.

    Drives :func:`verify_nl_rule` directly with a mocked ``ai_caller``
    returning unparsable YAML for a sentence no pattern matches. The
    response must be a graceful 200-shaped envelope with ``used_method``
    set to "ai" or "fallback" and ``confidence == 0.0``.
    """
    from app.modules.compliance_ai.schemas import NlVerifyRequest
    from app.modules.compliance_ai.service import verify_nl_rule

    captured_calls: list[tuple[str, str]] = []

    async def _bad_ai_caller(_system: str, _prompt: str) -> str:  # noqa: ARG001
        captured_calls.append((_system, _prompt))
        return "this is not yaml: : : ["  # parse failure

    # Patch the AI-caller builder so we don't need a DB / settings row.
    import app.modules.compliance_ai.service as svc

    async def _stub_builder(_user_id, _session):  # noqa: ANN001
        return _bad_ai_caller

    monkeypatch.setattr(svc, "_build_ai_caller", _stub_builder)

    # Sentence intentionally doesn't match any deterministic pattern so
    # the AI path is exercised.
    body = NlVerifyRequest(
        text="please ensure structural integrity is professionally reviewed",
        lang="en",
        use_ai=True,
    )
    # We don't need a real session — _build_ai_caller is stubbed and
    # parse_nl_to_dsl never touches the DB.
    result = await verify_nl_rule(body, user_id="test-user", session=None)

    # Verdict came back cleanly (no exception) with honest "no rule".
    assert result.dsl_definition == {}
    assert result.confidence == 0.0
    assert result.used_method in ("ai", "fallback")
    # AI caller was actually consulted (proves use_ai wiring).
    assert len(captured_calls) == 1
