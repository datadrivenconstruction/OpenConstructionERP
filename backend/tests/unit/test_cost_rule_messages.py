# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The ``cost_rules`` message section exists in every locale with the same placeholders."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import app.core.validation.messages as messages_pkg

DIR = Path(messages_pkg.__file__).parent
LOCALES = sorted(p.stem for p in DIR.glob("*.json"))
KEYS = (
    "duplicate_line",
    "burden_high",
    "empty_assembly",
    "unit_mismatch",
    "link_without_measurement",
    "scale_unit_not_length",
    "measurement_without_scale",
    "unallocated_share",
    "gifa_missing",
    "markup_load",
)


def _load(locale: str) -> dict:
    return json.loads((DIR / f"{locale}.json").read_text(encoding="utf-8"))["cost_rules"]


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_answers_every_cost_rule_key(locale: str) -> None:
    en, got = _load("en"), _load(locale)
    assert set(got) == set(KEYS)
    for key in KEYS:
        for part in ("fail", "suggestion"):
            text = got[key][part]
            assert text.strip()
            assert set(re.findall(r"\{(\w+)\}", text)) == set(re.findall(r"\{(\w+)\}", en[key][part]))
            if locale != "en":
                assert text != en[key][part]


def test_uzbek_uses_modifier_letter_turned_comma() -> None:
    text = json.dumps(_load("uz"), ensure_ascii=False)
    assert "ʻ" in text
    assert not re.search(r"[oOgG'‘’`ʼ]['‘’`ʼ]|ʼ", text)
