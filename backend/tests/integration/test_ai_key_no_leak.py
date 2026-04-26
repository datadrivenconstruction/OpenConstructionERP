"""Regression tests for AI provider key leakage (BUG-AI-CRYPTO01).

User-supplied OpenAI/Anthropic/etc API keys must never come back out of
the platform in plaintext. The settings endpoint returns booleans
(``*_api_key_set``) instead of the keys themselves, and at-rest storage
is Fernet-encrypted.

These tests drive the AI service against a per-test temp SQLite file
(no shared ``openestimate.db``, see ``feedback_test_isolation``) so the
encryption path is exercised end-to-end without hitting real LLM
providers or the production database.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    """Per-test fresh SQLite DB — never touches backend/openestimate.db."""
    tmp_db = Path(tempfile.mkdtemp()) / "ai_key_leak.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    # Register the AI tables so create_all picks them up.
    import app.modules.ai.models  # noqa: F401
    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


@pytest.fixture
def user_id() -> str:
    return str(uuid.uuid4())


# ── Helpers ──────────────────────────────────────────────────────────────────


# Fixed plaintext keys used across the tests. Each one is unique enough
# to find with a substring search across the response payload.
ANTHROPIC_KEY = "sk-ant-api03-NEVER-SHOW-ME-IN-RESPONSE-12345"
OPENAI_KEY = "sk-proj-OPENAI-NEVER-SHOW-ME-IN-RESPONSE-67890"
GEMINI_KEY = "AIza-GEMINI-NEVER-SHOW-ME-IN-RESPONSE-abcdef"


def _payload_with_keys() -> "AISettingsUpdate":  # type: ignore[name-defined]  # forward ref
    from app.modules.ai.schemas import AISettingsUpdate

    return AISettingsUpdate(
        anthropic_api_key=ANTHROPIC_KEY,
        openai_api_key=OPENAI_KEY,
        gemini_api_key=GEMINI_KEY,
        preferred_model="claude-sonnet",
    )


def _serialize(response) -> str:
    """Render a Pydantic response as JSON the way FastAPI would."""
    return response.model_dump_json()


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_response_does_not_contain_plaintext_key(session, user_id):
    """PATCH /ai/settings response must not echo the saved API keys."""
    from app.modules.ai.service import AIService

    svc = AIService(session)
    response = await svc.update_ai_settings(user_id, _payload_with_keys())
    await session.commit()

    payload = _serialize(response)

    for secret in (ANTHROPIC_KEY, OPENAI_KEY, GEMINI_KEY):
        assert secret not in payload, f"Plaintext key leaked in update response: {secret[:10]}…"

    # The booleans should faithfully report which providers are configured.
    assert response.anthropic_api_key_set is True
    assert response.openai_api_key_set is True
    assert response.gemini_api_key_set is True


@pytest.mark.asyncio
async def test_get_response_does_not_contain_plaintext_key(session, user_id):
    """Subsequent GET /ai/settings round-trip must also stay redacted."""
    from app.modules.ai.service import AIService

    svc = AIService(session)
    await svc.update_ai_settings(user_id, _payload_with_keys())
    await session.commit()

    fetched = await svc.get_ai_settings(user_id)
    payload = _serialize(fetched)

    for secret in (ANTHROPIC_KEY, OPENAI_KEY, GEMINI_KEY):
        assert secret not in payload, f"Plaintext key leaked in get response: {secret[:10]}…"

    parsed = json.loads(payload)
    # Schema must NOT expose any *_api_key field — only *_api_key_set.
    leaky_fields = [k for k in parsed if k.endswith("_api_key")]
    assert leaky_fields == [], f"Response schema exposes raw key fields: {leaky_fields}"


@pytest.mark.asyncio
async def test_db_row_is_encrypted_at_rest(session, user_id):
    """Reading the underlying ORM row must yield a Fernet token, not plaintext."""
    from app.core.crypto import decrypt_secret, is_encrypted
    from app.modules.ai.repository import AISettingsRepository
    from app.modules.ai.service import AIService

    svc = AIService(session)
    await svc.update_ai_settings(user_id, _payload_with_keys())
    await session.commit()

    repo = AISettingsRepository(session)
    row = await repo.get_by_user_id(uuid.UUID(user_id))
    assert row is not None

    # On disk: Fernet-prefixed ciphertext, not the raw user-supplied key.
    assert row.anthropic_api_key != ANTHROPIC_KEY
    assert is_encrypted(row.anthropic_api_key)
    assert is_encrypted(row.openai_api_key)
    assert is_encrypted(row.gemini_api_key)

    # And the platform can recover the original at the moment of an LLM call.
    assert decrypt_secret(row.anthropic_api_key) == ANTHROPIC_KEY
    assert decrypt_secret(row.openai_api_key) == OPENAI_KEY
    assert decrypt_secret(row.gemini_api_key) == GEMINI_KEY


@pytest.mark.asyncio
async def test_partial_update_does_not_clobber_other_keys(session, user_id):
    """Updating one provider key must not drop or leak the others."""
    from app.modules.ai.schemas import AISettingsUpdate
    from app.modules.ai.service import AIService

    svc = AIService(session)
    await svc.update_ai_settings(user_id, _payload_with_keys())
    await session.commit()

    # Now update only the OpenAI key.
    new_openai = "sk-proj-OPENAI-ROTATED-99999"
    response = await svc.update_ai_settings(
        user_id, AISettingsUpdate(openai_api_key=new_openai)
    )
    await session.commit()

    payload = _serialize(response)
    # No flavour of plaintext key may surface.
    for secret in (ANTHROPIC_KEY, OPENAI_KEY, GEMINI_KEY, new_openai):
        assert secret not in payload, f"Plaintext key leaked after partial update: {secret[:10]}…"

    assert response.anthropic_api_key_set is True
    assert response.openai_api_key_set is True
    assert response.gemini_api_key_set is True


@pytest.mark.asyncio
async def test_resolve_provider_returns_decrypted_key_for_llm_call(session, user_id):
    """The only legitimate plaintext access point — the LLM dispatcher.

    ``resolve_provider_and_key`` is what the AI service calls right
    before hitting the provider HTTP API. It MUST return the original
    plaintext (otherwise the LLM rejects the request) — but this is
    the *only* place plaintext is allowed to exist, and it never lands
    in any response body.
    """
    from app.modules.ai.ai_client import resolve_provider_and_key
    from app.modules.ai.repository import AISettingsRepository
    from app.modules.ai.service import AIService

    svc = AIService(session)
    await svc.update_ai_settings(user_id, _payload_with_keys())
    await session.commit()

    repo = AISettingsRepository(session)
    row = await repo.get_by_user_id(uuid.UUID(user_id))

    provider, key = resolve_provider_and_key(row, preferred_model="claude-sonnet")
    assert provider == "anthropic"
    assert key == ANTHROPIC_KEY  # decrypted for the outbound HTTP call
