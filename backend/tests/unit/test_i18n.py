"""Tests for the i18n (internationalization) system.

Tests cover locale definitions, the flatten helper, and the t() translation
function including fallback and interpolation behavior.
"""

import json
import logging
import re
import tempfile
from pathlib import Path

import pytest

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

#: The shape a code in SUPPORTED_LOCALES may take: ISO 639-1 where the language
#: has a two-letter code and ISO 639-2/3 where it has none, optionally followed
#: by a region. Filipino is why the three-letter case exists - there is no
#: two-letter code for it, and tl is Tagalog, a different language - and the
#: region tail is admitted because 4e376eb1e made the backend answer a regional
#: code, so a pt-BR arriving in this list would be a language being filled in
#: rather than a fault.
LOCALE_CODE = re.compile(r"[a-z]{2,3}(-[A-Z]{2})?")


class TestSupportedLocales:
    def test_the_two_lists_name_the_same_languages(self):
        """A language is held in two hand-edited lists that drift apart.

        This stood as ``len(SUPPORTED_LOCALES) == 28`` until nine languages
        were added and the count reached 37. A literal count asserts no
        property: it stays green while both lists are wrong in the same way,
        and it reds when a language is added correctly, which is the only
        thing it ever did. Identity against the JSON files on disk is held by
        tests/unit/test_backend_locale_catalogue.py, so what is left for this
        file is the pair of lists themselves, which can drift against each
        other without any file on disk changing.
        """
        gated, named = set(SUPPORTED_LOCALES), set(LOCALE_NAMES)
        assert gated == named, (
            f"gated on but unnamed, so offered to nobody: {sorted(gated - named)}; "
            f"named but not gated on, so offered and then refused: {sorted(named - gated)}"
        )

    def test_en_is_first(self):
        assert SUPPORTED_LOCALES[0] == "en"

    def test_de_is_present(self):
        assert "de" in SUPPORTED_LOCALES

    def test_ru_is_present(self):
        assert "ru" in SUPPORTED_LOCALES

    def test_all_locales_are_wellformed_language_codes(self):
        """This read ``len(locale) == 2``, and Filipino is spelled fil.

        A length was standing in for a shape, so the check could only hold
        while every language the product offered happened to have an ISO 639-1
        code. The shape is what was meant, and it is what a caller matching an
        Accept-Language header against this list depends on.
        """
        for locale in SUPPORTED_LOCALES:
            assert isinstance(locale, str)
            assert LOCALE_CODE.fullmatch(locale), f"{locale!r} is not a language code this list may hold"

    def test_the_code_shape_refuses_what_is_not_a_language_code(self):
        """A pattern widened to admit fil has to keep refusing the rest.

        Without this the previous test could be satisfied by a pattern that
        matches anything, and a locale key entered as ``en_GB`` or ``English``
        would reach the Accept-Language match unchallenged.
        """
        for bad in ["EN", "e", "engl", "en_GB", "en-gb", "en-GBR", "3n", "", "en "]:
            assert not LOCALE_CODE.fullmatch(bad), f"{bad!r} should not read as a language code"

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
            # A translator or a translation tool can leave either of these
            # behind. Both have to degrade to the template, not raise.
            "positional": "Item {0} is broken",
            "empty_field": "Item {} is broken",
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

    def test_positional_placeholder_returns_template(self):
        """A stray {0} used to raise IndexError straight out of t() and 500 the route."""
        assert t("positional", locale="en", position="01.02") == "Item {0} is broken"

    def test_empty_placeholder_returns_template(self):
        """Same for a bare pair of braces, which str.format also reads positionally."""
        assert t("empty_field", locale="en", position="01.02") == "Item {} is broken"

    def test_failed_interpolation_is_logged(self, caplog):
        """A silent fallback is indistinguishable from a correct render in production."""
        with caplog.at_level(logging.WARNING, logger="app.core.i18n"):
            t("welcome", locale="en", wrong_key="value")
        assert "welcome" in caplog.text, "the swallowed interpolation failure named no key"


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

    def test_missing_directory_raises_instead_of_regenerating(self):
        """A missing locales/ used to be silently refilled from an embedded copy.

        That copy knew 20 of the 28 languages and a much smaller key set, so the
        recovery succeeded and left the platform serving a catalogue missing most
        of its strings, with every file present and internally consistent. Losing
        the directory is now an error the operator sees.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            gone = Path(tmpdir) / "definitely-not-here"
            with pytest.raises(FileNotFoundError) as excinfo:
                load_translations(gone)

        message = str(excinfo.value)
        assert str(gone) in message, "the error did not say which directory was missing"
        assert "git checkout" in message, "the error did not say how to restore it"
        assert not gone.exists(), "load_translations created the directory it should have refused"


class TestSetAndGetLocale:
    def test_set_locale_and_get(self):
        set_locale("de")
        assert get_locale() in ("de", "en")  # "de" if loaded, "en" if fallback

    def test_set_unknown_locale_falls_back_to_en(self):
        set_locale("xx_unknown")
        assert get_locale() == "en"
