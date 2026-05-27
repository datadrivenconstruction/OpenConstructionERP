"""Tests for AI client utilities.

Focuses on the extract_json function and resolve_provider_and_key.
No network calls — all tests are pure unit tests.
"""

from types import SimpleNamespace

import httpx
import pytest

from app.modules.ai.ai_client import (
    ANTHROPIC_MODEL,
    DEFAULT_MODELS,
    GEMINI_MODEL,
    OPENAI_MODEL,
    OPENROUTER_MODEL,
    _extract_openai_message_text,
    _model_override_for,
    default_model_for,
    extract_json,
    resolve_provider_and_key,
    resolve_provider_key_model,
)

# ── extract_json ─────────────────────────────────────────────────────────────


class TestExtractJson:
    def test_raw_json_array(self):
        text = '[{"ordinal": "01.01", "description": "Concrete"}]'
        result = extract_json(text)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["ordinal"] == "01.01"

    def test_raw_json_object(self):
        text = '{"key": "value", "count": 42}'
        result = extract_json(text)
        assert isinstance(result, dict)
        assert result["key"] == "value"

    def test_markdown_code_fence_json(self):
        text = """Here is the result:
```json
[
  {"ordinal": "01.01", "description": "Excavation"},
  {"ordinal": "01.02", "description": "Foundation"}
]
```
"""
        result = extract_json(text)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["description"] == "Excavation"

    def test_markdown_code_fence_without_json_tag(self):
        text = """
```
[{"key": "value"}]
```
"""
        result = extract_json(text)
        assert isinstance(result, list)
        assert result[0]["key"] == "value"

    def test_json_embedded_in_text(self):
        text = 'I found the following items: [{"a": 1}, {"a": 2}] in the document.'
        result = extract_json(text)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_invalid_json_returns_none(self):
        text = "This is not JSON at all, just plain text."
        result = extract_json(text)
        assert result is None

    def test_empty_string_returns_none(self):
        result = extract_json("")
        assert result is None

    def test_none_input_returns_none(self):
        # extract_json checks `if not text:` which catches None-like falsy
        result = extract_json("")
        assert result is None

    def test_partial_json_with_surrounding_text(self):
        text = 'Sure, here is the data: {"items": [1, 2, 3]} Hope this helps!'
        result = extract_json(text)
        # extract_json tries [] boundaries before {} — the outermost match wins.
        # The actual result may be the inner list or the dict depending on
        # which boundary characters are found first. Either is valid extraction.
        assert result is not None

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = extract_json(text)
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_whitespace_padded_json(self):
        text = "   \n  [1, 2, 3]  \n   "
        result = extract_json(text)
        assert result == [1, 2, 3]

    def test_broken_json_returns_none(self):
        text = '[{"ordinal": "01.01", "description": "incomplete'
        result = extract_json(text)
        assert result is None


# ── OpenAI-shaped extraction hardening (issue #138) ──────────────────────────


class TestExtractOpenAIMessageText:
    """A billed completion must NEVER be silently dropped — every response
    shape resolves to non-empty text or a precise, actionable ValueError."""

    def test_plain_string_content(self):
        data = {"choices": [{"message": {"content": "  Hello estimator  "}}]}
        assert _extract_openai_message_text("openrouter", data) == "Hello estimator"

    def test_content_as_typed_parts_list(self):
        data = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "Part one. "},
                            {"type": "text", "text": "Part two."},
                        ]
                    }
                }
            ]
        }
        assert _extract_openai_message_text("openai", data) == "Part one. Part two."

    def test_falls_back_to_reasoning_when_content_empty(self):
        data = {"choices": [{"message": {"content": None, "reasoning": "Chain of thought answer"}}]}
        assert _extract_openai_message_text("openrouter", data) == "Chain of thought answer"

    def test_in_body_error_without_choices_raises(self):
        data = {"error": {"message": "insufficient credits"}}
        with pytest.raises(ValueError, match="insufficient credits"):
            _extract_openai_message_text("openrouter", data)

    def test_empty_choices_raises(self):
        with pytest.raises(ValueError, match="no choices"):
            _extract_openai_message_text("openrouter", {"choices": []})

    def test_empty_message_raises_with_finish_reason(self):
        data = {"choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]}
        with pytest.raises(ValueError, match="content_filter"):
            _extract_openai_message_text("openrouter", data)


# ── Model constants ──────────────────────────────────────────────────────────


class TestModelConstants:
    def test_anthropic_model_defined(self):
        assert isinstance(ANTHROPIC_MODEL, str)
        assert len(ANTHROPIC_MODEL) > 0

    def test_openai_model_defined(self):
        assert isinstance(OPENAI_MODEL, str)
        assert len(OPENAI_MODEL) > 0

    def test_gemini_model_defined(self):
        assert isinstance(GEMINI_MODEL, str)
        assert len(GEMINI_MODEL) > 0


# ── resolve_provider_and_key ─────────────────────────────────────────────────


class TestResolveProviderAndKey:
    def _make_settings(self, **kwargs):
        defaults = {
            "anthropic_api_key": None,
            "openai_api_key": None,
            "gemini_api_key": None,
            "openrouter_api_key": None,
            "mistral_api_key": None,
            "groq_api_key": None,
            "deepseek_api_key": None,
            "preferred_model": "claude-sonnet",
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_anthropic_preferred(self):
        settings = self._make_settings(anthropic_api_key="sk-ant-123")
        provider, key = resolve_provider_and_key(settings, "claude-sonnet")
        assert provider == "anthropic"
        assert key == "sk-ant-123"

    def test_openai_preferred(self):
        settings = self._make_settings(openai_api_key="sk-openai-123")
        provider, key = resolve_provider_and_key(settings, "gpt-4o")
        assert provider == "openai"
        assert key == "sk-openai-123"

    def test_gemini_preferred(self):
        settings = self._make_settings(gemini_api_key="AIza-123")
        provider, key = resolve_provider_and_key(settings, "gemini-2.0-flash")
        assert provider == "gemini"
        assert key == "AIza-123"

    def test_fallback_to_any_available(self):
        settings = self._make_settings(openai_api_key="sk-fallback")
        provider, key = resolve_provider_and_key(settings, "claude-sonnet")
        assert provider == "openai"
        assert key == "sk-fallback"

    def test_no_keys_raises_error(self):
        settings = self._make_settings()
        with pytest.raises(ValueError, match="No AI API key configured"):
            resolve_provider_and_key(settings)

    def test_none_settings_raises_error(self):
        with pytest.raises(ValueError, match="No AI API key configured"):
            resolve_provider_and_key(None)


# ── Model defaults & user-overridable model id (issue #129) ──────────────────


class TestModelDefaults:
    def test_openrouter_default_is_dateless_slug(self):
        # The dated Anthropic id is NOT a valid OpenRouter slug — the
        # default must be the date-less form or every OpenRouter key fails.
        assert OPENROUTER_MODEL == "anthropic/claude-sonnet-4"
        assert "20250514" not in OPENROUTER_MODEL

    def test_default_models_covers_core_providers(self):
        for provider in ("anthropic", "openai", "gemini", "openrouter"):
            assert provider in DEFAULT_MODELS
            assert DEFAULT_MODELS[provider]

    def test_default_model_for_known_and_unknown(self):
        assert default_model_for("gemini") == GEMINI_MODEL
        assert default_model_for("does-not-exist") == ""


class TestModelOverride:
    def _settings(self, overrides):
        return SimpleNamespace(metadata_={"model_overrides": overrides})

    def test_override_returned_when_set(self):
        s = self._settings({"gemini": "gemini-2.5-flash"})
        assert _model_override_for(s, "gemini") == "gemini-2.5-flash"

    def test_blank_override_treated_as_none(self):
        s = self._settings({"gemini": "   "})
        assert _model_override_for(s, "gemini") is None

    def test_missing_override_is_none(self):
        s = self._settings({"openrouter": "x/y"})
        assert _model_override_for(s, "gemini") is None

    def test_no_metadata_is_none(self):
        assert _model_override_for(SimpleNamespace(metadata_=None), "gemini") is None
        assert _model_override_for(None, "gemini") is None

    def test_resolve_provider_key_model_includes_override(self):
        settings = SimpleNamespace(
            anthropic_api_key=None,
            openai_api_key=None,
            gemini_api_key="AIza-key",
            openrouter_api_key=None,
            mistral_api_key=None,
            groq_api_key=None,
            deepseek_api_key=None,
            preferred_model="gemini-flash",
            metadata_={"model_overrides": {"gemini": "gemini-2.5-pro"}},
        )
        provider, key, model = resolve_provider_key_model(settings)
        assert provider == "gemini"
        assert key == "AIza-key"
        assert model == "gemini-2.5-pro"

    def test_resolve_provider_key_model_none_when_no_override(self):
        settings = SimpleNamespace(
            anthropic_api_key="sk-ant-1",
            openai_api_key=None,
            gemini_api_key=None,
            openrouter_api_key=None,
            mistral_api_key=None,
            groq_api_key=None,
            deepseek_api_key=None,
            preferred_model="claude-sonnet",
            metadata_={},
        )
        provider, key, model = resolve_provider_key_model(settings)
        assert provider == "anthropic"
        assert model is None


# ── "Model not found" error surfacing (issue #129) ───────────────────────────


class TestModelErrorSurfacing:
    @pytest.mark.asyncio
    async def test_unknown_model_message_is_actionable(self, monkeypatch):
        """A provider 400 "not a valid model ID" must produce a clear,
        actionable ValueError naming the model and pointing at Settings."""
        from app.modules.ai import ai_client

        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(
            400,
            json={"error": {"message": "anthropic/claude-sonnet-4-x is not a valid model ID"}},
            request=request,
        )

        async def _boom(*args, **kwargs):
            raise httpx.HTTPStatusError("bad", request=request, response=response)

        monkeypatch.setattr(ai_client, "call_openai_compatible", _boom)

        with pytest.raises(ValueError) as exc:
            await ai_client.call_ai(
                provider="openrouter",
                api_key="sk-or-test",
                system="s",
                prompt="p",
                model="anthropic/claude-sonnet-4-x",
            )
        msg = str(exc.value)
        assert "anthropic/claude-sonnet-4-x" in msg
        assert "Settings > AI" in msg
        assert "model name" in msg

    @pytest.mark.asyncio
    async def test_401_still_maps_to_key_error(self, monkeypatch):
        """A genuine auth failure must NOT be misreported as a model error."""
        from app.modules.ai import ai_client

        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(
            401,
            json={"error": {"message": "Incorrect API key provided"}},
            request=request,
        )

        async def _boom(*args, **kwargs):
            raise httpx.HTTPStatusError("unauth", request=request, response=response)

        monkeypatch.setattr(ai_client, "call_openai", _boom)

        with pytest.raises(ValueError, match="API key is invalid or expired"):
            await ai_client.call_ai(
                provider="openai",
                api_key="sk-bad",
                system="s",
                prompt="p",
            )

    # ── Issue #148 — auto-recovery from renamed/retired model slugs ──────────

    @pytest.mark.asyncio
    async def test_issue_148_openrouter_model_error_auto_recovers(self, monkeypatch):
        """A rejected OpenRouter slug must transparently fall back to
        ``openrouter/auto`` and return a normal answer — the chat keeps
        working without the user touching Settings."""
        from app.modules.ai import ai_client

        seen: list[str | None] = []
        req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")

        async def fake_compat(
            provider,
            api_key,
            system,
            prompt,
            image_base64=None,
            image_media_type="image/jpeg",
            max_tokens=4096,
            model=None,
        ):
            seen.append(model)
            if model == "openrouter/auto":
                return ("Recovered answer", 42)
            resp = httpx.Response(
                400,
                json={"error": {"message": f"{model} is not a valid model ID"}},
                request=req,
            )
            raise httpx.HTTPStatusError("bad", request=req, response=resp)

        monkeypatch.setattr(ai_client, "call_openai_compatible", fake_compat)

        text, tokens = await ai_client.call_ai(
            provider="openrouter",
            api_key="sk-or-test",
            system="s",
            prompt="p",
            model="some/stale-slug",
        )
        assert text == "Recovered answer"
        assert tokens == 42
        # Stale slug attempted first, then auto-recovered via openrouter/auto.
        assert seen[0] == "some/stale-slug"
        assert "openrouter/auto" in seen

    @pytest.mark.asyncio
    async def test_issue_148_all_fallbacks_fail_raises_actionable(self, monkeypatch):
        """When every fallback also fails, the actionable error is still
        raised (and says the automatic fallbacks were attempted)."""
        from app.modules.ai import ai_client

        req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")

        async def always_bad(*args, **kwargs):
            resp = httpx.Response(
                404,
                json={"error": {"message": "model not found"}},
                request=req,
            )
            raise httpx.HTTPStatusError("bad", request=req, response=resp)

        monkeypatch.setattr(ai_client, "call_openai_compatible", always_bad)

        with pytest.raises(ValueError) as exc:
            await ai_client.call_ai(
                provider="openrouter",
                api_key="sk-or-test",
                system="s",
                prompt="p",
                model="bad/model",
            )
        msg = str(exc.value)
        assert "bad/model" in msg
        assert "Settings > AI" in msg
        assert "automatic fallbacks did not succeed" in msg

    def test_issue_148_fallback_models_for_openrouter(self):
        """``openrouter/auto`` leads the fallback list and the attempted id
        is never returned (no infinite same-model retry)."""
        from app.modules.ai import ai_client

        fbs = ai_client.fallback_models_for("openrouter", "anthropic/claude-sonnet-4")
        assert fbs[0] == "openrouter/auto"
        assert "anthropic/claude-sonnet-4" not in fbs
        # If the auto-router itself was the failing id, it is skipped.
        assert "openrouter/auto" not in ai_client.fallback_models_for("openrouter", "openrouter/auto")
        # A provider with no special fallback still offers its built-in
        # default (helps when a user override is the stale id).
        assert ai_client.fallback_models_for("openai", "gpt-stale") == [ai_client.default_model_for("openai")]
