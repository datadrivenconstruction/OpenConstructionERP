# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The project advisor's answer cache is not shared between credentials.

The cache is a module-level dict, so it lives as long as the worker and every
user's requests read it. Its key was the provider, model, system prompt and
prompt, which left out whose key, or whose self-hosted endpoint, would answer.
Two users sending the same prompt within a minute got one answer, produced by
the first user's provider account or runtime, and the second user's own
endpoint was never called. That is the same shape as GHSA-wfpw-cv5v-64j5, one
user's AI configuration standing in for another's, at a smaller scale. The key
now includes the credential and, for a self-hosted runtime, the endpoint.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.modules.project_intelligence import advisor


async def _ask(api_key: str) -> str:
    return await advisor._call_ai_logged(
        operation="recommendations",
        provider="anthropic",
        api_key=api_key,
        model="claude-test",
        system="system",
        prompt="identical prompt",
        max_tokens=100,
    )


@pytest.mark.asyncio
async def test_a_second_credential_is_not_answered_from_the_first_ones_cache() -> None:
    advisor._llm_cache.clear()
    with patch(
        "app.modules.ai.ai_client.call_ai",
        new=AsyncMock(side_effect=[("answer for A", 1), ("answer for B", 1)]),
    ) as call:
        first = await _ask("key-of-user-a")
        second = await _ask("key-of-user-b")

    assert first == "answer for A"
    assert second == "answer for B"
    assert call.await_count == 2


@pytest.mark.asyncio
async def test_the_same_credential_still_hits_the_cache() -> None:
    advisor._llm_cache.clear()
    with patch("app.modules.ai.ai_client.call_ai", new=AsyncMock(return_value=("answer", 1))) as call:
        await _ask("key-of-user-a")
        await _ask("key-of-user-a")
    assert call.await_count == 1


def test_the_key_never_stores_the_credential_in_clear() -> None:
    key = advisor._llm_cache_key(
        provider="anthropic", model="m", system="s", prompt="p", max_tokens=1, credential="sk-secret-value"
    )
    assert "sk-secret-value" not in key
