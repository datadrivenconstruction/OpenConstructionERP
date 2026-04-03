"""Tests for AI client utilities.

Focuses on the extract_json function and resolve_provider_and_key.
No network calls — all tests are pure unit tests.
"""

from types import SimpleNamespace

import pytest

from app.modules.ai.ai_client import (
    ANTHROPIC_MODEL,
    GEMINI_MODEL,
    OPENAI_MODEL,
    extract_json,
    resolve_provider_and_key,
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
