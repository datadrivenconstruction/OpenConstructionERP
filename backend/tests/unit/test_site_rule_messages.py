# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The shared ``site`` message section exists in every locale with the same placeholders."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import app.core.validation.messages as messages_pkg

DIR = Path(messages_pkg.__file__).parent
LOCALES = sorted(p.stem for p in DIR.glob("*.json"))
KEYS = ("future_date", "contradiction", "required_when", "limit_exceeded", "suggestion")


def _load(locale: str) -> dict:
    return json.loads((DIR / f"{locale}.json").read_text(encoding="utf-8"))["site"]


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_answers_every_site_key(locale: str) -> None:
    en, got = _load("en"), _load(locale)
    assert set(got) == set(KEYS)
    for key in KEYS:
        assert got[key].strip()
        assert set(re.findall(r"\{(\w+)\}", got[key])) == set(re.findall(r"\{(\w+)\}", en[key]))
        if locale != "en":
            assert got[key] != en[key]


def test_uzbek_uses_modifier_turned_comma() -> None:
    text = " ".join(_load("uz").values())
    assert "ʻ" in text
    assert "o'" not in text and "g'" not in text
