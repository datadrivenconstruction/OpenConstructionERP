# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The shared ``quality`` message section exists in every locale with the same placeholders."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import app.core.validation.messages as messages_pkg

DIR = Path(messages_pkg.__file__).parent
LOCALES = sorted(p.stem for p in DIR.glob("*.json"))
KEYS = ("field_required_for_state", "overdue", "result_contradicts_checklist")


def _load(locale: str) -> dict:
    return json.loads((DIR / f"{locale}.json").read_text(encoding="utf-8"))["quality"]


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_answers_every_quality_key(locale: str) -> None:
    en, got = _load("en"), _load(locale)
    for key in KEYS:
        for part in ("fail", "suggestion"):
            text = got[key][part]
            assert text.strip()
            assert set(re.findall(r"\{(\w+)\}", text)) == set(re.findall(r"\{(\w+)\}", en[key][part]))
            if locale != "en":
                assert text != en[key][part]
