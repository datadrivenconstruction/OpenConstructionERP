# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The ``site_records`` message section (accommodation, field reports, field diary) exists in every locale with the same placeholders."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import app.core.validation.messages as messages_pkg

DIR = Path(messages_pkg.__file__).parent
LOCALES = sorted(p.stem for p in DIR.glob("*.json"))
KEYS = (
    "dates_not_ordered",
    "period_outside_stay",
    "currency_missing",
    "capacity_exceeded",
    "camp_room_charged",
    "nothing_recorded",
    "delay_unexplained",
    "date_in_future",
    "hours_exceed_day",
    "hours_without_crew",
    "incident_undescribed",
    "delay_undescribed",
    "hours_exceed_window",
    "crew_without_record",
)


def _load(locale: str) -> dict:
    return json.loads((DIR / f"{locale}.json").read_text(encoding="utf-8"))["site_records"]


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_answers_every_site_records_key(locale: str) -> None:
    en, got = _load("en"), _load(locale)
    for key in KEYS:
        for part in ("fail", "suggestion"):
            text = got[key][part]
            assert text.strip()
            assert set(re.findall(r"\{(\w+)\}", text)) == set(re.findall(r"\{(\w+)\}", en[key][part]))
            if locale != "en":
                assert text != en[key][part]


@pytest.mark.parametrize("locale", [loc for loc in LOCALES if loc == "uz"])
def test_uzbek_uses_modifier_apostrophes(locale: str) -> None:
    for key in KEYS:
        assert "'" not in _load(locale)[key]["fail"]
