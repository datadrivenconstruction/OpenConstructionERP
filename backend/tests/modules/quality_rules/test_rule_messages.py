"""Every message key the quality rule sets use exists in every validation locale."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import app.core.validation.messages as bundle

KEYS = {
    "requirements": ["value_missing", "value_invalid", "unit_missing", "verification_missing", "locked_set_empty"],
    "bim_requirements": ["property_missing", "filter_empty", "bounds_inverted", "pattern_invalid"],
    "qms": [
        "cost_currency_missing",
        "root_cause_missing",
        "punch_due_before_raised",
        "calibration_window",
        "calibration_lapsed",
    ],
    "construction_control": [
        "band_inverted",
        "nominal_outside",
        "certificate_window",
        "certificate_expired",
        "test_before_sample",
        "lab_unaccredited",
        "date_in_future",
    ],
    "site_prep": ["completed_in_future", "ready_undated", "gate_item_unowned", "plan_start_missing"],
    "site_supervision": ["visit_undated", "visit_in_future", "observation_missing", "hidden_works_unidentified"],
}
RULE_FILES = {"site_supervision": "rules.py"}
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
    same = [
        (s, k)
        for s, keys in KEYS.items()
        for k in keys
        if mine[s][k]["fail"] == base[s][k]["fail"] and k != "date_invalid"
    ]
    assert not same


def test_uzbek_uses_the_modifier_letter_not_a_quote():
    text = json.dumps({s: _load("uz")[s] for s in KEYS}, ensure_ascii=False)
    assert "ʻ" in text
    assert "o'" not in text and "g'" not in text


@pytest.mark.parametrize("section", sorted(KEYS))
def test_every_key_the_rules_emit_is_in_the_bundle(section):
    source = (
        Path(bundle.__file__).parents[3] / "modules" / section / RULE_FILES.get(section, "validators.py")
    ).read_text(encoding="utf-8")
    used = set(re.findall(r'self\.fail\(\s*context,\s*"(\w+)"', source))
    assert used == set(KEYS[section])
    assert used <= set(_load("en")[section])
