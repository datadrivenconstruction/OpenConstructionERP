"""Tests for AI prompt templates.

Verifies that all prompts exist, are non-empty, and contain
required placeholders for runtime string formatting.
"""

from app.modules.ai.prompts import (
    CAD_IMPORT_PROMPT,
    PHOTO_ESTIMATE_PROMPT,
    SMART_IMPORT_PROMPT,
    SMART_IMPORT_VISION_PROMPT,
    SYSTEM_PROMPT,
    TEXT_ESTIMATE_PROMPT,
)


class TestTextEstimatePrompt:
    def test_is_non_empty_string(self):
        assert isinstance(TEXT_ESTIMATE_PROMPT, str)
        assert len(TEXT_ESTIMATE_PROMPT) > 100

    def test_contains_description_placeholder(self):
        assert "{description}" in TEXT_ESTIMATE_PROMPT

    def test_contains_currency_placeholder(self):
        assert "{currency}" in TEXT_ESTIMATE_PROMPT

    def test_contains_standard_placeholder(self):
        assert "{standard}" in TEXT_ESTIMATE_PROMPT

    def test_contains_extra_context_placeholder(self):
        assert "{extra_context}" in TEXT_ESTIMATE_PROMPT

    def test_can_format_without_error(self):
        """Verify the prompt can be formatted with all placeholders."""
        result = TEXT_ESTIMATE_PROMPT.format(
            description="Test building",
            currency="EUR",
            standard="din276",
            extra_context="",
        )
        assert "Test building" in result
        assert "EUR" in result


class TestPhotoEstimatePrompt:
    def test_is_non_empty_string(self):
        assert isinstance(PHOTO_ESTIMATE_PROMPT, str)
        assert len(PHOTO_ESTIMATE_PROMPT) > 100

    def test_contains_currency_placeholder(self):
        assert "{currency}" in PHOTO_ESTIMATE_PROMPT

    def test_contains_standard_placeholder(self):
        assert "{standard}" in PHOTO_ESTIMATE_PROMPT

    def test_contains_location_placeholder(self):
        assert "{location}" in PHOTO_ESTIMATE_PROMPT

    def test_can_format_without_error(self):
        result = PHOTO_ESTIMATE_PROMPT.format(
            location="Berlin, Germany",
            currency="EUR",
            standard="din276",
        )
        assert "Berlin, Germany" in result


class TestSmartImportPrompt:
    def test_exists_and_non_empty(self):
        assert isinstance(SMART_IMPORT_PROMPT, str)
        assert len(SMART_IMPORT_PROMPT) > 50

    def test_contains_filename_placeholder(self):
        assert "{filename}" in SMART_IMPORT_PROMPT

    def test_contains_text_placeholder(self):
        assert "{text}" in SMART_IMPORT_PROMPT


class TestSmartImportVisionPrompt:
    def test_exists_and_non_empty(self):
        assert isinstance(SMART_IMPORT_VISION_PROMPT, str)
        assert len(SMART_IMPORT_VISION_PROMPT) > 50

    def test_contains_filename_placeholder(self):
        assert "{filename}" in SMART_IMPORT_VISION_PROMPT


class TestCadImportPrompt:
    def test_exists_and_non_empty(self):
        assert isinstance(CAD_IMPORT_PROMPT, str)
        assert len(CAD_IMPORT_PROMPT) > 50

    def test_contains_text_placeholder(self):
        assert "{text}" in CAD_IMPORT_PROMPT

    def test_contains_currency_placeholder(self):
        assert "{currency}" in CAD_IMPORT_PROMPT


class TestSystemPrompt:
    def test_exists_and_non_empty(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 20

    def test_mentions_json(self):
        assert "JSON" in SYSTEM_PROMPT
