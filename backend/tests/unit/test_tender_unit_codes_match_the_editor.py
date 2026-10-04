# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The tender workbooks spell trade units the way the BOQ editor does.

The editor's per-language unit spellings (``LOCALE_UNIT_CODES`` in
``frontend/src/shared/lib/unitLabels.ts``) are copied into the workbook
renderer, because the sheet is built on the server. Two copies drift: a
spelling changed on one side would make the downloaded sheet disagree with the
screen it was downloaded from. This reads the editor's table as text and holds
the server's copy to it.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.modules.tendering.workbooks import _LOCALE_UNIT_CODES

_UNIT_LABELS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "shared" / "lib" / "unitLabels.ts"

_LANGUAGE = re.compile(r"^\s*([a-z]{2,3})\s*:\s*\{(.*)\}\s*,?\s*$")
_ENTRY = re.compile(r"""([A-Za-z_]\w*)\s*:\s*(?:'([^']*)'|"([^"]*)")""")


def _editor_table() -> dict[str, dict[str, str]]:
    source = _UNIT_LABELS.read_text(encoding="utf-8")
    block = re.search(r"const LOCALE_UNIT_CODES[^=]*=\s*\{(.*?)\n\};", source, re.S)
    assert block, f"LOCALE_UNIT_CODES not found in {_UNIT_LABELS}"
    table: dict[str, dict[str, str]] = {}
    for line in block.group(1).splitlines():
        match = _LANGUAGE.match(line)
        if match:
            table[match.group(1)] = {k: single or double for k, single, double in _ENTRY.findall(match.group(2))}
    return table


def test_the_editor_table_is_read() -> None:
    """A parser that read nothing would make the comparison below pass on two empty tables."""
    table = _editor_table()
    assert {"de", "hr"} <= set(table)
    assert table["de"]["lsum"] == "psch"
    assert table["hr"]["lm"] == "m'"


def test_the_workbook_units_match_the_editor() -> None:
    assert _editor_table() == _LOCALE_UNIT_CODES
