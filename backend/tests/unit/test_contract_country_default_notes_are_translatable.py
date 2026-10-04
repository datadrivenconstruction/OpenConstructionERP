# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A country default's note reaches the reader through a locale key, in step with the table.

Each figure in ``contracts.country_defaults`` carries a ``note``, an English
sentence a person reads in the tooltip beside "Default for Germany". It used to
be shown as served, so a reader on any other locale got English. The client now
renders it through ``contracts.country_defaults.<CC>.<field>.note`` and falls
back to the server's English only where a locale has no entry.

That arrangement fails silently in two ways, and these tests hold both:

* **The table and the locale file drift.** A note edited in the table while
  ``en.ts`` keeps the old sentence leaves the English reader and every
  translator working from different text. Nothing renders wrongly, so nothing
  shows it. Every note must sit in ``en.ts`` under its key, word for word.
* **A key outlives its figure.** A country or field dropped from the table
  leaves a key no figure answers, which a translator keeps translating.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.modules.contracts.country_defaults import (
    CONTRACT_DEFAULT_FIELDS,
    COUNTRY_CONTRACT_DEFAULTS,
    NOTE_KEY_PREFIX,
    note_key,
    resolve_contract_defaults,
)

_EN_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "locales" / "en.ts"
_ENTRY = re.compile(r'^\s*"(' + re.escape(NOTE_KEY_PREFIX) + r'[^"]+)"\s*:\s*("(?:[^"\\]|\\.)*")\s*,?\s*$')


def _en_notes() -> dict[str, str]:
    if not _EN_TS.is_file():
        pytest.skip(f"no frontend tree beside the backend at {_EN_TS}")
    found: dict[str, str] = {}
    for line in _EN_TS.read_text(encoding="utf-8").splitlines():
        match = _ENTRY.match(line)
        if match:
            found[match.group(1)] = json.loads(match.group(2))
    return found


def _table_notes() -> dict[str, str]:
    return {
        note_key(country, field): row[field]["note"]
        for country, row in COUNTRY_CONTRACT_DEFAULTS.items()
        for field in CONTRACT_DEFAULT_FIELDS
    }


def test_every_note_is_in_en_ts_word_for_word() -> None:
    en = _en_notes()
    table = _table_notes()
    missing = sorted(set(table) - set(en))
    assert not missing, f"notes with no en.ts key: {missing}"
    drifted = sorted(key for key, note in table.items() if en[key] != note)
    assert not drifted, f"en.ts text differs from the table for: {drifted}"


def test_no_en_ts_note_outlives_its_figure() -> None:
    stale = sorted(set(_en_notes()) - set(_table_notes()))
    assert not stale, f"en.ts keys no figure answers any more: {stale}"


def test_the_parser_reads_the_file_rather_than_nothing() -> None:
    # A regex that matched no line would pass the stale-key test vacuously.
    assert len(_en_notes()) == len(COUNTRY_CONTRACT_DEFAULTS) * len(CONTRACT_DEFAULT_FIELDS)


@pytest.mark.parametrize("country", sorted(COUNTRY_CONTRACT_DEFAULTS))
def test_the_served_source_names_the_key_its_note_is_under(country: str) -> None:
    resolved = resolve_contract_defaults(country)
    for field in CONTRACT_DEFAULT_FIELDS:
        source = resolved["sources"][field]
        assert source["note_key"] == f"contracts.country_defaults.{country}.{field}.note"
        assert source["note"] == COUNTRY_CONTRACT_DEFAULTS[country][field]["note"]
