"""Tests for the i18n (internationalization) system.

Tests cover locale definitions, the flatten helper, and the t() translation
function including fallback and interpolation behavior.
"""

import json
import tempfile
from pathlib import Path

from app.core.i18n import (
    LOCALE_NAMES,
    SUPPORTED_LOCALES,
    _flatten_dict,
    _translations,
    get_locale,
    load_translations,
    set_locale,
    t,
)

# ── Supported locales ────────────────────────────────────────────────────────


class TestSupportedLocales:
    def test_20_locales_defined(self):
        assert len(SUPPORTED_LOCALES) == 20

    def test_en_is_first(self):
        assert SUPPORTED_LOCALES[0] == "en"

    def test_de_is_present(self):
        assert "de" in SUPPORTED_LOCALES

    def test_ru_is_present(self):
        assert "ru" in SUPPORTED_LOCALES

    def test_all_locales_are_two_char_codes(self):
        for locale in SUPPORTED_LOCALES:
            assert isinstance(locale, str)
            assert len(locale) == 2

    def test_no_duplicates(self):
        assert len(SUPPORTED_LOCALES) == len(set(SUPPORTED_LOCALES))


# ── LOCALE_NAMES ─────────────────────────────────────────────────────────────


class TestLocaleNames:
    def test_every_locale_has_name(self):
        for locale in SUPPORTED_LOCALES:
            assert locale in LOCALE_NAMES, f"LOCALE_NAMES missing entry for '{locale}'"

    def test_names_are_non_empty_strings(self):
        for locale, name in LOCALE_NAMES.items():
            assert isinstance(name, str)
            assert len(name) > 0

    def test_en_name_is_english(self):
        assert LOCALE_NAMES["en"] == "English"

    def test_de_name_is_deutsch(self):
        assert LOCALE_NAMES["de"] == "Deutsch"


# ── _flatten_dict ────────────────────────────────────────────────────────────


class TestFlattenDict:
    def test_single_level(self):
        result = _flatten_dict({"key": "value"})
        assert result == {"key": "value"}

    def test_nested(self):
        result = _flatten_dict({"a": {"b": "c"}})
        assert result == {"a.b": "c"}

    def test_deep_nesting(self):
        result = _flatten_dict({"a": {"b": {"c": "deep"}}})
        assert result == {"a.b.c": "deep"}

    def test_mixed_nesting(self):
        result = _flatten_dict(
            {
                "flat": "value",
                "nested": {"inner": "data"},
            }
        )
        assert result == {"flat": "value", "nested.inner": "data"}

    def test_empty_dict(self):
        result = _flatten_dict({})
        assert result == {}

    def test_numeric_values_converted_to_string(self):
        result = _flatten_dict({"count": 42})
        assert result == {"count": "42"}

    def test_multiple_siblings(self):
        result = _flatten_dict(
            {
                "validation": {
                    "error": "Error occurred",
                    "warning": "Warning issued",
                }
            }
        )
        assert result == {
            "validation.error": "Error occurred",
            "validation.warning": "Warning issued",
        }


# ── t() translation function ────────────────────────────────────────────────


class TestTranslationFunction:
    @classmethod
    def setup_class(cls):
        """Load test translations into the global store."""
        cls._saved = dict(_translations)
        _translations.clear()
        _translations["en"] = {
            "greeting": "Hello",
            "farewell": "Goodbye",
            "welcome": "Welcome, {name}!",
            "count": "You have {count} items",
        }
        _translations["de"] = {
            "greeting": "Hallo",
            "farewell": "Auf Wiedersehen",
            "welcome": "Willkommen, {name}!",
        }

    @classmethod
    def teardown_class(cls):
        """Restore original translations."""
        _translations.clear()
        _translations.update(cls._saved)

    def test_returns_key_if_not_found(self):
        result = t("nonexistent.key", locale="en")
        assert result == "nonexistent.key"

    def test_english_translation(self):
        result = t("greeting", locale="en")
        assert result == "Hello"

    def test_german_translation(self):
        result = t("greeting", locale="de")
        assert result == "Hallo"

    def test_fallback_to_english(self):
        # "count" is only in English, not in German
        result = t("count", locale="de", count=5)
        assert result == "You have 5 items"

    def test_interpolation(self):
        result = t("welcome", locale="en", name="Alice")
        assert result == "Welcome, Alice!"

    def test_interpolation_german(self):
        result = t("welcome", locale="de", name="Bob")
        assert result == "Willkommen, Bob!"

    def test_missing_interpolation_key_returns_template(self):
        """If kwargs don't match placeholders, return the unformatted template."""
        result = t("welcome", locale="en", wrong_key="value")
        assert result == "Welcome, {name}!"

    def test_unknown_locale_falls_back_to_english(self):
        result = t("greeting", locale="xx")
        assert result == "Hello"


# ── load_translations / set_locale / get_locale ──────────────────────────────


class TestLoadTranslations:
    def test_load_from_temp_directory(self):
        saved = dict(_translations)
        _translations.clear()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                en_file = Path(tmpdir) / "en.json"
                en_file.write_text(
                    json.dumps({"test": {"key": "Test Value"}}),
                    encoding="utf-8",
                )
                load_translations(Path(tmpdir))
                assert "en" in _translations
                assert _translations["en"]["test.key"] == "Test Value"
        finally:
            _translations.clear()
            _translations.update(saved)


class TestSetAndGetLocale:
    def test_set_locale_and_get(self):
        set_locale("de")
        assert get_locale() in ("de", "en")  # "de" if loaded, "en" if fallback

    def test_set_unknown_locale_falls_back_to_en(self):
        set_locale("xx_unknown")
        assert get_locale() == "en"
