"""Every message key the record rule sets use exists in every validation locale."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import app.core.validation.messages as bundle

KEYS = {
    "phonelog": ["call_in_future", "call_ends_before_start", "logged_without_content", "instruction_without_party"],
    "reconciliation": [
        "endpoints_missing",
        "link_to_itself",
        "record_type_unknown",
        "confidence_out_of_range",
        "confirmed_below_threshold",
    ],
    "methodology": [
        "cascade_rate_out_of_range",
        "cascade_base_unknown",
        "vat_rate_out_of_range",
        "funding_code_duplicate",
        "dimension_value_duplicate",
        "dimension_parent_unknown",
    ],
    "reporting": [
        "snapshot_date_invalid",
        "snapshot_date_future",
        "index_invalid",
        "percent_out_of_range",
        "budget_overrun",
        "count_negative",
        "recipient_invalid",
        "schedule_without_recipients",
    ],
}
HERE = Path(bundle.__file__).parent
LOCALES = sorted(p.stem for p in HERE.glob("*.json"))


def _load(locale: str) -> dict:
    return json.loads((HERE / f"{locale}.json").read_text(encoding="utf-8"))


def _placeholders(text: str) -> list[str]:
    return sorted(re.findall(r"\{(\w+)\}", text))


@pytest.mark.parametrize("locale", LOCALES)
def test_every_locale_has_every_key_with_the_english_placeholders(locale):
    base, mine = _load("en"), _load(locale)
    for section, keys in KEYS.items():
        for key in keys:
            for part in ("fail", "suggestion"):
                text = mine[section][key][part]
                assert text.strip()
                assert _placeholders(text) == _placeholders(base[section][key][part])


@pytest.mark.parametrize("locale", [loc for loc in LOCALES if loc != "en"])
def test_non_english_locales_are_translated(locale):
    base, mine = _load("en"), _load(locale)
    same = [(s, k) for s, keys in KEYS.items() for k in keys if mine[s][k]["fail"] == base[s][k]["fail"]]
    assert not same


def test_uzbek_uses_the_modifier_letter_not_a_quote():
    text = json.dumps({s: _load("uz")[s] for s in KEYS}, ensure_ascii=False)
    assert "ʻ" in text
    assert "o'" not in text and "g'" not in text


@pytest.mark.parametrize("section", sorted(KEYS))
def test_every_key_the_rules_emit_is_in_the_bundle(section):
    source = (Path(bundle.__file__).parents[3] / "modules" / section / "validators.py").read_text(encoding="utf-8")
    used = set(re.findall(r'self\.fail\(\s*context,\s*"(\w+)"', source))
    assert used == set(KEYS[section])
