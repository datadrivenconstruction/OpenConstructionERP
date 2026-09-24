# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The chat's own Anthropic call sends an API model id, never the UI alias.

Settings > AI stores the dropdown choice ("claude-sonnet", "claude-opus",
"claude-haiku"), and ``resolve_provider_key_model`` hands that choice back as
the model when the user typed no id of their own. ``ai_client.call_anthropic``
maps it through ``resolve_anthropic_model``. ``ERPChatService._call_anthropic``
posts with its own HTTP client, so it has to do the same mapping, or the alias
itself goes on the wire.

Only the transport is faked (``httpx.MockTransport``), so the request body read
here is the one the real client would send.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

import app.modules.erp_chat.service as chat_service
from app.modules.ai.ai_client import ANTHROPIC_MODEL, ANTHROPIC_MODELS
from app.modules.erp_chat.service import ERPChatService


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Bodies of the requests the chat posts to Anthropic, answered with a short reply."""
    bodies: list[dict[str, Any]] = []

    def _answer(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 3, "output_tokens": 2}},
        )

    real_client = httpx.AsyncClient

    def _client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(_answer)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(chat_service.httpx, "AsyncClient", _client)
    return bodies


async def _call(model: str | None) -> None:
    service = ERPChatService(session=object())  # type: ignore[arg-type]
    await service._call_anthropic("sk-ant-test", [{"role": "user", "content": "hi"}], model)


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", sorted(ANTHROPIC_MODELS))
async def test_the_settings_alias_is_sent_as_an_api_model_id(sent: list[dict[str, Any]], alias: str) -> None:
    await _call(alias)

    assert sent[0]["model"] == ANTHROPIC_MODELS[alias]
    assert sent[0]["model"] != alias


@pytest.mark.asyncio
async def test_a_model_id_the_user_typed_passes_through_unchanged(sent: list[dict[str, Any]]) -> None:
    await _call("claude-3-5-haiku-latest")

    assert sent[0]["model"] == "claude-3-5-haiku-latest"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [None, "", "   "])
async def test_no_model_falls_back_to_the_default(sent: list[dict[str, Any]], model: str | None) -> None:
    await _call(model)

    assert sent[0]["model"] == ANTHROPIC_MODEL
