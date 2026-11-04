# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The estimating rule messages exist, with the same placeholders, in every validation locale."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core.validation import messages

DIR = Path(messages.__file__).parent
LOCALES = sorted(p.stem for p in DIR.glob("*.json"))
KEYS = [
    "mass_basis_needs_mass",
    "mass_needs_basis",
    "geometry_too_few_points",
    "link_needs_confirmed",
    "scale_missing",
    "unit_mismatch",
    "count_not_whole",
    "scale_unusual",
    "scale_uncalibrated",
    "accuracy_band_invalid",
    "price_date_stale",
]


def _section(locale: str) -> dict:
    return json.loads((DIR / f"{locale}.json").read_text(encoding="utf-8"))["estimating"]


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_carries_every_estimating_message(locale: str) -> None:
    en, own = _section("en"), _section(locale)
    assert sorted(own) == sorted(KEYS)
    for key in KEYS:
        for part in ("fail", "suggestion"):
            assert own[key][part].strip()
            assert sorted(re.findall(r"\{(\w+)\}", own[key][part])) == sorted(re.findall(r"\{(\w+)\}", en[key][part]))


def test_uzbek_uses_the_modifier_apostrophe() -> None:
    text = json.dumps(_section("uz"), ensure_ascii=False)
    assert "ʻ" in text
    assert "o'" not in text
    assert "g'" not in text
