# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The transmittal, correspondence, temporary works and commissioning sections exist in every locale."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import app.core.validation.messages as messages_pkg
from app.modules.commissioning.validators import COMMISSIONING_RULES
from app.modules.correspondence.validators import CORRESPONDENCE_RULES
from app.modules.temporary_works.validators import TEMPORARY_WORKS_RULES
from app.modules.transmittals.validators import TRANSMITTALS_RULES

DIR = Path(messages_pkg.__file__).parent
LOCALES = sorted(p.stem for p in DIR.glob("*.json"))
SECTIONS = ("transmittals", "correspondence", "temporary_works", "commissioning")


def _flat(node: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in node.items():
        name = f"{prefix}.{key}" if prefix else key
        out.update(_flat(value, name) if isinstance(value, dict) else {name: value})
    return out


def _load(locale: str) -> dict[str, str]:
    data = json.loads((DIR / f"{locale}.json").read_text(encoding="utf-8"))
    return {k: v for s in SECTIONS for k, v in _flat(data[s], s).items()}


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_answers_every_section_key(locale: str) -> None:
    en, got = _load("en"), _load(locale)
    assert got.keys() == en.keys()
    for key, text in got.items():
        assert text.strip()
        assert set(re.findall(r"\{(\w+)\}", text)) == set(re.findall(r"\{(\w+)\}", en[key]))
        if locale != "en":
            assert text != en[key]


def test_every_rule_has_a_message_for_each_of_its_failures() -> None:
    en = _load("en")
    for rules in (TRANSMITTALS_RULES, CORRESPONDENCE_RULES, TEMPORARY_WORKS_RULES, COMMISSIONING_RULES):
        section = rules[0].message_section
        assert f"{section}.suggestion" in en
    keys = {k.rsplit(".", 1)[0] for k in en if k.endswith(".fail")}
    assert len(keys) == 21
