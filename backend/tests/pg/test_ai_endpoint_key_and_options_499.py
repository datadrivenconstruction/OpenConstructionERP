# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Issue #499 - the endpoint key, tool mode and timeouts, stored and read back on PostgreSQL.

The key of the OpenAI-compatible endpoint is kept inside ``metadata`` rather
than in a column of its own, so an upgraded install needs no schema change.
That choice is only safe if the JSON column behaves like the column it stands
in for: encrypted at rest, saved again on a second write (a JSON column that is
mutated in place is not marked dirty and silently keeps the old value), cleared
by an empty value, and seen by every reader that used to read a column - the
status flags, the resolver and the connection test.

Each test re-reads with a fresh ``select()`` of the raw column, because the
identity map would otherwise return the object still in memory and pass on a
write that never reached the database.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.ai import ai_client
from app.modules.ai.models import AISettings
from app.modules.ai.schemas import AISettingsUpdate
from app.modules.ai.service import AIService

pytestmark = pytest.mark.asyncio

GATEWAY = "http://10.20.0.5:4000/v1"


async def _raw_meta(session, user_id: str) -> dict:
    session.expire_all()
    row = (await session.execute(select(AISettings.metadata_).where(AISettings.user_id == uuid.UUID(user_id)))).one()
    return dict(row[0] or {})


async def _row(session, user_id: str) -> AISettings:
    session.expire_all()
    return (await session.execute(select(AISettings).where(AISettings.user_id == uuid.UUID(user_id)))).scalar_one()


async def test_the_key_is_encrypted_at_rest_and_round_trips(pg_session):
    user_id = str(uuid.uuid4())
    service = AIService(pg_session)
    response = await service.update_ai_settings(
        user_id, AISettingsUpdate(preferred_model="vllm", vllm_base_url=GATEWAY, vllm_api_key="sk-gateway-1")
    )
    await pg_session.commit()

    meta = await _raw_meta(pg_session, user_id)
    assert "sk-gateway-1" not in repr(meta)
    assert meta.get("vllm_api_key")
    assert response.vllm_api_key_set is True
    # The response never carries the ciphertext either.
    assert "vllm_api_key" not in response.metadata

    row = await _row(pg_session, user_id)
    assert ai_client.resolve_provider_and_key(row) == ("vllm", "sk-gateway-1")


async def test_a_second_save_replaces_the_key_and_keeps_the_rest(pg_session):
    user_id = str(uuid.uuid4())
    service = AIService(pg_session)
    await service.update_ai_settings(
        user_id,
        AISettingsUpdate(
            preferred_model="vllm",
            vllm_base_url=GATEWAY,
            vllm_api_key="sk-first",
            model_overrides={"vllm": "qwen2.5-coder"},
        ),
    )
    await pg_session.commit()
    await service.update_ai_settings(user_id, AISettingsUpdate(vllm_api_key="sk-second"))
    await pg_session.commit()

    row = await _row(pg_session, user_id)
    assert ai_client.resolve_provider_and_key(row) == ("vllm", "sk-second")
    meta = await _raw_meta(pg_session, user_id)
    assert meta["vllm_base_url"] == GATEWAY
    assert meta["model_overrides"] == {"vllm": "qwen2.5-coder"}


async def test_an_empty_key_clears_it(pg_session):
    user_id = str(uuid.uuid4())
    service = AIService(pg_session)
    await service.update_ai_settings(
        user_id, AISettingsUpdate(preferred_model="vllm", vllm_base_url=GATEWAY, vllm_api_key="sk-gateway")
    )
    await pg_session.commit()
    response = await service.update_ai_settings(user_id, AISettingsUpdate(vllm_api_key=""))
    await pg_session.commit()

    assert "vllm_api_key" not in await _raw_meta(pg_session, user_id)
    assert response.vllm_api_key_set is False
    row = await _row(pg_session, user_id)
    assert ai_client.resolve_provider_and_key(row) == ("vllm", "")


async def test_tool_mode_and_timeouts_are_stored_and_reported(pg_session):
    user_id = str(uuid.uuid4())
    service = AIService(pg_session)
    await service.update_ai_settings(
        user_id,
        AISettingsUpdate(
            preferred_model="vllm",
            vllm_base_url=GATEWAY,
            tool_calling={"vllm": "auto"},
            timeouts={"vllm": 900, "anthropic": 300},
        ),
    )
    await pg_session.commit()
    # A later save of one value leaves the others alone, and null clears one.
    response = await service.update_ai_settings(user_id, AISettingsUpdate(timeouts={"anthropic": None}))
    await pg_session.commit()

    meta = await _raw_meta(pg_session, user_id)
    assert meta["tool_calling"] == {"vllm": "auto"}
    assert meta["timeouts"] == {"vllm": 900}
    assert response.tool_calling == {"vllm": "auto"}
    assert response.timeouts == {"vllm": 900}
    assert response.default_timeout_seconds == 240.0

    row = await _row(pg_session, user_id)
    ai_client.resolve_provider_and_key(row)
    assert ai_client.tool_calling_mode("vllm") == "auto"
    assert ai_client.effective_ai_timeout() == 900.0


async def test_the_connection_test_sees_the_stored_key(pg_session, monkeypatch):
    from app.modules.ai import router as ai_router

    user_id = str(uuid.uuid4())
    service = AIService(pg_session)
    await service.update_ai_settings(
        user_id, AISettingsUpdate(preferred_model="vllm", vllm_base_url=GATEWAY, vllm_api_key="sk-gateway")
    )
    await pg_session.commit()
    pg_session.expire_all()

    seen: dict = {}

    async def _fake_call_ai(**kwargs):
        seen.update(kwargs)
        return "OK", 1

    monkeypatch.setattr(ai_router, "call_ai", _fake_call_ai)
    result = await ai_router.test_ai_connection({"provider": "vllm"}, user_id, service)
    assert result["success"] is True
    assert seen["api_key"] == "sk-gateway"
    assert seen["base_url"] == "http://10.20.0.5:4000/v1/chat/completions"
