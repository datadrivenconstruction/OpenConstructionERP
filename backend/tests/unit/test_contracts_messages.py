# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The contracts findings exist for every key the source can ask for.

``translate`` falls back to English and then to the raw key, so a missing
message never raises: it shows up as ``pay_application.period_gap.fail``
printed to a project accountant. The keys are read out of the rule and service
source rather than listed here, so a rule that starts emitting a new message is
covered the day it is written.

The bundle ships in English, German and Russian first. The other languages
arrive in one pass once the billing rules stop gaining keys; until then the
test that wants every language is a strict expected failure, so it turns red
the day the translations land and has to be switched on rather than forgotten.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

from app.core.i18n import SUPPORTED_LOCALES
from app.modules.contracts import messages as message_bundle
from app.modules.contracts import service as contracts_service
from app.modules.contracts import validators as contracts_validators
from app.modules.contracts.messages import is_key_present, translate

MESSAGES_DIR = pathlib.Path(str(message_bundle.__file__)).parent
SOURCES = [pathlib.Path(str(contracts_validators.__file__)), pathlib.Path(str(contracts_service.__file__))]
SHIPPED_LOCALES = sorted(path.stem for path in MESSAGES_DIR.glob("*.json"))
TRANSLATED_LOCALES = [locale for locale in SHIPPED_LOCALES if locale != "en"]

#: Top-level segments of every key this bundle answers. The contracts source
#: carries many other dotted strings (permission names, event names), and only
#: these prefixes are message keys.
#:
#: A prefix missing from here is invisible in both directions, and one of them
#: is quiet in a way the other is not. A key the source asks for and the bundle
#: lacks goes unchecked, so the raw key reaches a reader. A key the bundle
#: carries and this list cannot see is reported as unused, which is a red test
#: about a key that is fine. The certificate label arrived under "aia." and was
#: read as the second of those. Add the prefix with the first key that uses it.
KEY_PREFIXES = ("aia.", "pay_application.", "retention_release.")


def message_keys() -> set[str]:
    """Every message key the rule and service source can ask for.

    Walks the syntax tree rather than grepping, because the calls are spread
    over several lines. Rule ids share the ``pay_application.`` prefix and are
    one segment short of a message, so a key needs at least three segments.
    """
    found: set[str] = set()
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(KEY_PREFIXES):
                if node.value.count(".") >= 2 and " " not in node.value:
                    found.add(node.value)
    return found


def _flat_keys(data: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        out |= _flat_keys(value, path) if isinstance(value, dict) else {path}
    return out


def test_the_source_really_yields_the_keys_this_file_then_checks() -> None:
    """A scanner that quietly finds nothing would make every test below vacuous."""
    keys = message_keys()
    assert "pay_application.period_order.fail" in keys
    assert "pay_application.line_overbilled.suggestion" in keys
    assert "pay_application.period_unparsed.fields.claim_date" in keys
    # The service's half, so a scan that lost the second file fails here.
    assert "pay_application.errors.submission_blocked" in keys
    assert "pay_application.errors.rules_unavailable" in keys
    # The retention release gate, and the document names read from a table.
    assert "retention_release.errors.approval_blocked" in keys
    assert "retention_release.document_roles.consent_of_surety" in keys
    # The certificate's own labels, so dropping the prefix that carries them
    # fails here rather than showing up as a key nobody asks for.
    assert "aia.g703.billed_not_on_a_schedule_line" in keys


@pytest.mark.parametrize("locale", SHIPPED_LOCALES)
def test_every_message_the_source_can_ask_for_exists_in_every_shipped_locale(locale: str) -> None:
    missing = sorted(key for key in message_keys() | {"common.ok"} if not is_key_present(key, locale))
    assert missing == [], f"{locale} answers none of these: {missing}"


def test_every_bundle_carries_exactly_the_same_keys() -> None:
    reference = _flat_keys(json.loads((MESSAGES_DIR / "en.json").read_text("utf-8")))
    assert reference, "en.json carries no contracts messages at all"
    for locale in SHIPPED_LOCALES:
        keys = _flat_keys(json.loads((MESSAGES_DIR / f"{locale}.json").read_text("utf-8")))
        assert keys == reference, f"{locale} differs by {sorted(keys ^ reference)}"


def test_no_message_is_left_unused() -> None:
    """A key nothing asks for is a sentence translated 38 times for no reader."""
    reference = _flat_keys(json.loads((MESSAGES_DIR / "en.json").read_text("utf-8")))
    unused = sorted(reference - message_keys() - {"common.ok"})
    assert unused == []


def test_the_rendered_messages_fill_every_placeholder() -> None:
    """A placeholder the caller does not pass prints as a literal brace in the finding."""
    for key in sorted(message_keys()):
        template = translate(key, locale="en")
        assert template != key, f"en falls through on {key}"
        names = set(re.findall(r"{(\w+)}", template))
        rendered = translate(key, locale="en", **dict.fromkeys(names, "x"))
        assert "{" not in rendered, f"{key} renders as {rendered!r}"


@pytest.mark.parametrize("locale", TRANSLATED_LOCALES)
def test_no_translation_is_the_english_sentence_copied_over(locale: str) -> None:
    """A file that carries the key with the English text passes every presence check above."""
    copied = sorted(key for key in message_keys() if translate(key, locale=locale) == translate(key, locale="en"))
    assert copied == [], f"{locale} ships the English sentence for {copied}"


def test_the_translated_messages_keep_the_placeholders_the_source_fills() -> None:
    """A dropped placeholder loses the date or amount that makes a finding actionable."""
    for key in sorted(message_keys()):
        expected = set(re.findall(r"{(\w+)}", translate(key, locale="en")))
        for locale in TRANSLATED_LOCALES:
            actual = set(re.findall(r"{(\w+)}", translate(key, locale=locale)))
            assert actual == expected, f"{locale} on {key}: expected {sorted(expected)}, got {sorted(actual)}"


@pytest.mark.xfail(
    strict=True,
    reason="The contracts findings ship in English, German and Russian until the billing rule keys settle; "
    "the other languages land in one pass and this test is then switched on.",
)
def test_the_bundle_answers_every_language_a_request_can_resolve_to() -> None:
    assert set(SHIPPED_LOCALES) == set(SUPPORTED_LOCALES)
