"""Every message key the coordination rule sets use exists in every validation locale."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import app.core.validation.messages as bundle

KEYS = {
    "plan_room": ["photo_ref_path", "file_version_invalid", "pin_bare"],
    "compliance_docs": ["coverage_missing", "currency_invalid", "status_contradicts_dates", "policy_number_missing"],
    "file_transmittals": [
        "send_without_items",
        "send_without_recipients",
        "item_duplicate",
        "construction_unversioned",
    ],
    "approval_routes": ["approver_role_unknown", "step_sla_missing", "delegation_ended", "delegation_open_ended"],
    "coordination_hub": ["threshold_inverted", "threshold_value_invalid", "threshold_disabled"],
    "clash": ["due_date_invalid", "due_date_past", "severe_unassigned", "clearance_distance_missing"],
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
