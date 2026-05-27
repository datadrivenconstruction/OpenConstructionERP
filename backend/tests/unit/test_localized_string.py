"""Tests for LocalizedStr utility and resolve_localized helper."""

from unittest.mock import patch

from app.core.localized_string import LocalizedStr, resolve_localized

# ── Construction ─────────────────────────────────────────────────────────────


class TestConstruction:
    def test_basic_construction(self):
        ls = LocalizedStr(translations={"en": "Hello", "de": "Hallo"})
        assert ls.translations == {"en": "Hello", "de": "Hallo"}

    def test_empty_dict(self):
        ls = LocalizedStr(translations={})
        assert ls.translations == {}


# ── resolve() ────────────────────────────────────────────────────────────────


class TestResolve:
    def test_exact_locale(self):
        ls = LocalizedStr(translations={"en": "Hello", "de": "Hallo", "ru": "Привет"})
        assert ls.resolve("de") == "Hallo"

    def test_fallback_locale(self):
        ls = LocalizedStr(translations={"en": "Hello", "de": "Hallo"})
        assert ls.resolve("fr") == "Hello"  # falls back to "en"

    def test_custom_fallback(self):
        ls = LocalizedStr(translations={"de": "Hallo", "fr": "Bonjour"})
        assert ls.resolve("ja", fallback="fr") == "Bonjour"

    def test_first_available_when_no_fallback(self):
        ls = LocalizedStr(translations={"de": "Hallo", "fr": "Bonjour"})
        # Neither "ja" nor default fallback "en" present → first alphabetically = "de"
        assert ls.resolve("ja") == "Hallo"

    def test_empty_translations(self):
        ls = LocalizedStr(translations={})
        assert ls.resolve("en") == ""

    def test_default_locale_is_en(self):
        ls = LocalizedStr(translations={"en": "Hello", "de": "Hallo"})
        assert ls.resolve() == "Hello"


# ── get() ────────────────────────────────────────────────────────────────────


class TestGet:
    def test_existing_locale(self):
        ls = LocalizedStr(translations={"en": "Hello"})
        assert ls.get("en") == "Hello"

    def test_missing_locale_returns_none(self):
        ls = LocalizedStr(translations={"en": "Hello"})
        assert ls.get("de") is None

    def test_empty_translations(self):
        ls = LocalizedStr(translations={})
        assert ls.get("en") is None


# ── set() ────────────────────────────────────────────────────────────────────


class TestSet:
    def test_set_new_locale(self):
        ls = LocalizedStr(translations={"en": "Hello"})
        updated = ls.set("de", "Hallo")
        assert updated.translations == {"en": "Hello", "de": "Hallo"}

    def test_set_returns_new_instance(self):
        ls = LocalizedStr(translations={"en": "Hello"})
        updated = ls.set("de", "Hallo")
        assert updated is not ls
        # Original is not mutated
        assert "de" not in ls.translations

    def test_set_overwrites_existing(self):
        ls = LocalizedStr(translations={"en": "Hello"})
        updated = ls.set("en", "Hi")
        assert updated.translations["en"] == "Hi"
        assert ls.translations["en"] == "Hello"


# ── locales() ────────────────────────────────────────────────────────────────


class TestLocales:
    def test_sorted_output(self):
        ls = LocalizedStr(translations={"ru": "Привет", "de": "Hallo", "en": "Hello"})
        assert ls.locales() == ["de", "en", "ru"]

    def test_empty(self):
        ls = LocalizedStr(translations={})
        assert ls.locales() == []


# ── is_complete() ────────────────────────────────────────────────────────────


class TestIsComplete:
    def test_all_non_empty(self):
        ls = LocalizedStr(translations={"en": "Hello", "de": "Hallo"})
        assert ls.is_complete() is True

    def test_has_empty_value(self):
        ls = LocalizedStr(translations={"en": "Hello", "de": ""})
        assert ls.is_complete() is False

    def test_empty_translations_is_incomplete(self):
        ls = LocalizedStr(translations={})
        assert ls.is_complete() is False

    def test_required_locales_all_present(self):
        ls = LocalizedStr(translations={"en": "Hello", "de": "Hallo", "fr": "Bonjour"})
        assert ls.is_complete(required_locales=["en", "de"]) is True

    def test_required_locales_missing(self):
        ls = LocalizedStr(translations={"en": "Hello"})
        assert ls.is_complete(required_locales=["en", "de"]) is False

    def test_required_locales_present_but_empty(self):
        ls = LocalizedStr(translations={"en": "Hello", "de": ""})
        assert ls.is_complete(required_locales=["en", "de"]) is False


# ── __str__() ────────────────────────────────────────────────────────────────


class TestStr:
    def test_str_uses_get_locale(self):
        ls = LocalizedStr(translations={"en": "Hello", "de": "Hallo"})
        with patch("app.core.i18n.get_locale", return_value="de"):
            assert str(ls) == "Hallo"

    def test_str_falls_back(self):
        ls = LocalizedStr(translations={"en": "Hello"})
        with patch("app.core.i18n.get_locale", return_value="ja"):
            assert str(ls) == "Hello"

    def test_str_empty(self):
        ls = LocalizedStr(translations={})
        with patch("app.core.i18n.get_locale", return_value="en"):
            assert str(ls) == ""


# ── __len__() ────────────────────────────────────────────────────────────────


class TestLen:
    def test_length(self):
        ls = LocalizedStr(translations={"en": "Hello", "de": "Hallo", "ru": "Привет"})
        assert len(ls) == 3

    def test_length_empty(self):
        ls = LocalizedStr(translations={})
        assert len(ls) == 0


# ── from_single() ────────────────────────────────────────────────────────────


class TestFromSingle:
    def test_default_locale(self):
        ls = LocalizedStr.from_single("Hello")
        assert ls.translations == {"en": "Hello"}

    def test_custom_locale(self):
        ls = LocalizedStr.from_single("Hallo", locale="de")
        assert ls.translations == {"de": "Hallo"}


# ── empty() ──────────────────────────────────────────────────────────────────


class TestEmpty:
    def test_empty_factory(self):
        ls = LocalizedStr.empty()
        assert ls.translations == {}
        assert len(ls) == 0


# ── resolve_localized() standalone function ──────────────────────────────────


class TestResolveLocalized:
    def test_dict_exact_match(self):
        assert resolve_localized({"en": "Hello", "de": "Hallo"}, locale="de") == "Hallo"

    def test_dict_fallback(self):
        assert resolve_localized({"en": "Hello", "de": "Hallo"}, locale="fr") == "Hello"

    def test_dict_custom_fallback(self):
        assert resolve_localized({"de": "Hallo", "fr": "Bonjour"}, locale="ja", fallback="fr") == "Bonjour"

    def test_dict_first_available(self):
        result = resolve_localized({"de": "Hallo", "fr": "Bonjour"}, locale="ja")
        assert result == "Hallo"  # "de" is first alphabetically

    def test_dict_empty(self):
        assert resolve_localized({}, locale="en") == ""

    def test_str_passthrough(self):
        assert resolve_localized("plain text") == "plain text"

    def test_none_returns_empty(self):
        assert resolve_localized(None) == ""

    def test_default_locale_is_en(self):
        assert resolve_localized({"en": "Hello", "de": "Hallo"}) == "Hello"
