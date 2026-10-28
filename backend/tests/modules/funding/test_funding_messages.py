# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The funding findings say the same thing in every language the product offers.

A missing message does not raise. ``translate`` falls back to English and then
to the raw key, so a hole shows up as an English sentence inside a German
report, or as ``funding.own_share_is_covered.fail`` printed to a funding
officer. Neither is visible to any other gate we own, because there is no
value to compare against.

The findings used to live in the shared validation bundle, which answers four
languages, so a reader in any of the other thirty-four got English sentences
on an otherwise translated funding screen. They now live in the module's own
bundle, and these tests hold it to every language a request can resolve to.

The keys are read out of the rule source rather than listed here, so a rule
that starts emitting a sixth message is covered the day it is written instead
of the day somebody remembers to extend this file.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

from app.core.i18n import SUPPORTED_LOCALES
from app.core.validation import messages as shared_bundle
from app.modules.funding import messages as message_bundle
from app.modules.funding import router as funding_router
from app.modules.funding import validators as funding_validators
from app.modules.funding.messages import available_locales, is_key_present, translate

# Both are found through the modules themselves rather than through a relative
# path, so the tests pass wherever pytest was started from.
MESSAGES_DIR = pathlib.Path(str(message_bundle.__file__)).parent
SHARED_DIR = pathlib.Path(str(shared_bundle.__file__)).parent
#: The rules write the findings and the router writes the errors a reader of
#: the funding screens can meet. Both ask the same bundle.
SOURCES = [pathlib.Path(str(funding_validators.__file__)), pathlib.Path(str(funding_router.__file__))]

#: Read off the directory, so a language that gains a file is checked the day
#: it lands. The test below pins that this is every language a request can
#: resolve to, which is what stops the list from shrinking unnoticed.
SHIPPED_LOCALES = sorted(path.stem for path in MESSAGES_DIR.glob("*.json"))
TRANSLATED_LOCALES = [locale for locale in SHIPPED_LOCALES if locale != "en"]

#: Substituted into the one message key the rules build at runtime.
FAULTS = ["before", "after", "spans"]

#: Languages written in a script other than Latin. A run of Latin letters in
#: one of their findings is an English word left in the sentence.
NON_LATIN = {"ar", "bg", "bn", "el", "fa", "he", "hi", "ja", "kk", "ko", "ky", "ru", "th", "uk", "ur", "zh"}


def message_keys() -> set[str]:
    """Every ``funding.`` message key the rule and router source can ask for.

    Walks the syntax tree rather than grepping, because a call spread over
    four lines is invisible to a single-line pattern and that is exactly how
    these calls are formatted. The one key assembled from an f-string is
    expanded over the three values its branch can produce.
    """
    body = [statement for path in SOURCES for statement in ast.parse(path.read_text("utf-8")).body]
    tree = ast.Module(body=body, type_ignores=[])

    # The literal halves of an f-string are Constant nodes in their own right,
    # so walking the tree would otherwise collect the bare prefix alongside the
    # three keys that prefix actually produces, and then report the prefix as a
    # missing translation in every locale.
    literal_halves = {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in ast.walk(node)
        if isinstance(part, ast.Constant)
    }

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            prefix = "".join(
                part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            if prefix.startswith("funding."):
                found.update(prefix + fault for fault in FAULTS)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in literal_halves:
            if node.value.startswith("funding."):
                found.add(node.value)
    # ``funding`` on its own is the rule set name, and the rule ids are not
    # message keys. Both are three segments short of a message.
    return {key for key in found if key.count(".") >= 2}


def _flat_keys(data: dict, prefix: str = "") -> set[str]:
    """Every dotted key a nested locale file carries."""
    out: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        out |= _flat_keys(value, path) if isinstance(value, dict) else {path}
    return out


def test_the_source_really_yields_the_keys_this_file_then_checks() -> None:
    """A scanner that quietly finds nothing would make every test below vacuous."""
    keys = message_keys()
    assert len(keys) >= 15, sorted(keys)
    assert "funding.measure_starts_after_application.fail" in keys
    assert "funding.own_share_is_covered.suggestion" in keys
    # The runtime-assembled key, expanded.
    for fault in FAULTS:
        assert f"funding.costs_fall_in_the_award_period.{fault}" in keys
    # And the router's half, so a scan that silently lost the second file fails here.
    assert "funding.errors.programme_code_taken" in keys


def test_the_bundle_answers_every_language_a_request_can_resolve_to() -> None:
    """The reason the module has a bundle of its own.

    ``SUPPORTED_LOCALES`` is the set the backend clamps a request's language
    to, one base language per language the interface offers. A language on
    that list without a file here reads the findings in English.
    """
    assert set(SHIPPED_LOCALES) == set(SUPPORTED_LOCALES), (
        f"no findings file for {sorted(set(SUPPORTED_LOCALES) - set(SHIPPED_LOCALES))}, "
        f"a file nothing can reach for {sorted(set(SHIPPED_LOCALES) - set(SUPPORTED_LOCALES))}"
    )
    assert available_locales() == SHIPPED_LOCALES


def test_the_shared_bundle_no_longer_keeps_a_second_copy() -> None:
    """Two copies of one sentence drift, and the shared one would win nothing but confusion."""
    for path in sorted(SHARED_DIR.glob("*.json")):
        assert "funding" not in json.loads(path.read_text("utf-8")), f"{path.name} still carries funding messages"


@pytest.mark.parametrize("locale", SHIPPED_LOCALES)
def test_every_message_the_rules_can_ask_for_exists_in_every_shipped_locale(locale: str) -> None:
    missing = sorted(key for key in message_keys() | {"common.ok"} if not is_key_present(key, locale))
    assert missing == [], f"{locale} answers none of these: {missing}"


def test_every_bundle_carries_exactly_the_same_keys() -> None:
    """One locale gaining a key alone is how a translation silently drifts."""
    reference = _flat_keys(json.loads((MESSAGES_DIR / "en.json").read_text("utf-8")))
    assert reference, "en.json carries no funding messages at all"
    for locale in TRANSLATED_LOCALES:
        keys = _flat_keys(json.loads((MESSAGES_DIR / f"{locale}.json").read_text("utf-8")))
        assert keys == reference, f"{locale} differs by {sorted(keys ^ reference)}"


@pytest.mark.parametrize("locale", SHIPPED_LOCALES)
def test_no_funding_message_is_left_as_its_english_placeholder(locale: str) -> None:
    """Every message is a real sentence, not a key and not an empty string."""
    for key in sorted(message_keys()):
        rendered = translate(key, locale=locale)
        assert rendered != key, f"{locale} falls through on {key}"
        assert rendered.strip(), f"{locale} answers {key} with whitespace"


@pytest.mark.parametrize("locale", TRANSLATED_LOCALES)
def test_no_translation_is_the_english_sentence_copied_over(locale: str) -> None:
    """A file that carries the key with the English text passes every presence check above."""
    copied = sorted(key for key in message_keys() if translate(key, locale=locale) == translate(key, locale="en"))
    assert copied == [], f"{locale} ships the English sentence for {copied}"


@pytest.mark.parametrize("locale", sorted(NON_LATIN & set(SHIPPED_LOCALES)))
def test_a_non_latin_language_carries_no_english_words(locale: str) -> None:
    """The mixing a reader sees at once: a Latin-script word inside a Cyrillic or Arabic sentence."""
    mixed = {}
    for key in sorted(message_keys()):
        template = re.sub(r"{\w+}", " ", translate(key, locale=locale))
        words = re.findall(r"[A-Za-z]{3,}", template)
        if words:
            mixed[key] = words
    assert mixed == {}, f"{locale} leaves Latin-script words in {mixed}"


def test_the_translated_messages_keep_the_placeholders_the_rules_fill() -> None:
    """A dropped placeholder loses the date or amount that makes a finding actionable."""
    for key in sorted(message_keys()):
        expected = set(re.findall(r"{(\w+)}", translate(key, locale="en")))
        for locale in TRANSLATED_LOCALES:
            actual = set(re.findall(r"{(\w+)}", translate(key, locale=locale)))
            assert actual == expected, f"{locale} on {key}: expected {sorted(expected)}, got {sorted(actual)}"


def test_the_german_wording_uses_the_domains_own_terms() -> None:
    """German funding administration has settled words, and a literal translation is wrong.

    These are the terms a Zuwendungsempfaenger reads on the notice itself. A
    finding that invents its own vocabulary reads as a software message rather
    than as something the authority would recognise, and the reader cannot map
    it onto the paperwork in front of them.
    """
    german = " ".join(translate(key, locale="de") for key in sorted(message_keys()))
    for term in ["Bewilligungszeitraum", "Eigenanteil", "Verwendungsnachweis", "Beihilfeintensit"]:
        assert term in german, f"the German bundle never says {term}"


def test_a_regional_request_reads_its_base_language() -> None:
    """The interface sends ``pt-BR`` or ``es-MX`` as the reader picked it, not the base code."""
    key = "funding.proof_of_use_is_on_time.suggestion"
    assert translate(key, locale="pt-BR") == translate(key, locale="pt")
    assert translate(key, locale="es-MX") == translate(key, locale="es")
    assert translate(key, locale="pt") != translate(key, locale="en")
