"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the progress-reporter agent (item 15).

Pure unit tests - no DB, no network. They exercise:

* Prompt assembly embeds the real snapshot figures so the model writes
  only from given data.
* The graceful no-key path: when no AI provider key is configured the
  enrichment returns ``None`` (the report renders without a narrative)
  rather than raising.
* The happy path: with an injected LLM call (never a real API) the
  enrichment returns a narrative dict flagged AI-generated with a
  confidence value.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.ai_agents.agents.progress_reporter import (
    NARRATIVE_CONFIDENCE,
    build_narrative_prompt,
    generate_progress_narrative,
)

SNAPSHOT: dict[str, Any] = {
    "currency": "USD",
    "progress": {
        "overall_pct": 42.5,
        "as_of_date": "2026-06-05",
        "milestone_status": [{"period": "2026-W23", "percent": 42.5}],
    },
    "schedule": {"progress_pct": 40.0},
    "risk": {"top_risks": ["Foundation rebar delivery slipped two weeks"]},
}


class TestPromptAssembly:
    def test_prompt_embeds_snapshot_figures(self):
        prompt = build_narrative_prompt(SNAPSHOT)
        # Real figures from the snapshot must appear verbatim so the model
        # can ground the narrative without inventing numbers.
        assert "42.5" in prompt
        assert "USD" in prompt
        assert "Foundation rebar delivery slipped two weeks" in prompt
        assert "2026-W23" in prompt

    def test_prompt_handles_empty_snapshot(self):
        # No crash on an empty snapshot; still produces a JSON object body.
        prompt = build_narrative_prompt({})
        assert "{}" in prompt


class TestGracefulNoKey:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_key_configured(self, monkeypatch):
        """No provider key -> ``None`` (render without narrative), never raises."""

        def _raise_no_key(*_args, **_kwargs):
            raise ValueError("No AI API key configured")

        monkeypatch.setattr(
            "app.modules.ai.ai_client.resolve_provider_key_model",
            _raise_no_key,
        )

        async def _must_not_call(**_kwargs):  # pragma: no cover - asserts non-call
            raise AssertionError("LLM must not be called when no key is configured")

        result = await generate_progress_narrative(
            SNAPSHOT,
            call_llm=_must_not_call,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_snapshot(self):
        assert await generate_progress_narrative({}) is None


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_flagged_narrative_with_injected_llm(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.ai.ai_client.resolve_provider_key_model",
            lambda *_a, **_k: ("anthropic", "test-key", "claude-sonnet"),
        )

        captured: dict[str, Any] = {}

        async def _fake_llm(**kwargs):
            captured.update(kwargs)
            return ("The project is on schedule at 42.5% complete.", 123)

        result = await generate_progress_narrative(
            SNAPSHOT,
            call_llm=_fake_llm,
        )

        assert result is not None
        assert result["ai_generated"] is True
        assert result["confidence"] == NARRATIVE_CONFIDENCE
        assert result["provider"] == "anthropic"
        assert "42.5% complete" in result["text"]
        # The injected call received the resolved key + model, never a real key.
        assert captured["api_key"] == "test-key"
        assert captured["model"] == "claude-sonnet"

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_raises(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.ai.ai_client.resolve_provider_key_model",
            lambda *_a, **_k: ("anthropic", "test-key", None),
        )

        async def _boom(**_kwargs):
            raise RuntimeError("provider 500")

        # A transport failure degrades to no narrative, never propagates.
        assert await generate_progress_narrative(SNAPSHOT, call_llm=_boom) is None

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_returns_blank(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.ai.ai_client.resolve_provider_key_model",
            lambda *_a, **_k: ("anthropic", "test-key", None),
        )

        async def _blank(**_kwargs):
            return ("   ", 0)

        assert await generate_progress_narrative(SNAPSHOT, call_llm=_blank) is None
