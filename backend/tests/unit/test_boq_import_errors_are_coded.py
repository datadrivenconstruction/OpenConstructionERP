# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every refusal of a bill import reaches the reader as a code, never as a sentence the server wrote.

The import dialog words a refused file from ``boq.import_error.<code>`` in the
reader's language. A raise without a code would fall back to the English
message, so each one in the importers the ``/import/auto/`` route dispatches
to is checked for a literal ``code=``. The frontend walks the same sources
(``importFailureText.test.ts``) and checks it has a wording for each code, so
a new code cannot ship untranslated.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from app.modules.boq.importers import ImporterParseError
from app.modules.boq.importers.xpwe import XpweImporter

IMPORTERS = Path(__file__).resolve().parents[2] / "app" / "modules" / "boq" / "importers"
_ERRORS = {"ImporterParseError", "XpweNativeFileError"}


def _raises() -> list[tuple[str, int, ast.Call]]:
    found = []
    paths = [*IMPORTERS.glob("*.py"), *(IMPORTERS.parent / name for name in (
        "gaeb_common.py", "gaeb_x31.py", "gaeb_x89.py",
    ))]
    for path in sorted(paths):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                func = node.exc.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name in _ERRORS:
                    found.append((path.name, node.lineno, node.exc))
    return found


def test_the_walk_finds_the_raises() -> None:
    files = {name for name, _line, _call in _raises()}
    assert {"xpwe.py", "excel.py", "gaeb_xml.py", "bc3.py", "_workbook.py", "gaeb_common.py", "gaeb_x31.py", "gaeb_x89.py"} <= files


def test_every_importer_refusal_names_a_literal_code() -> None:
    uncoded = []
    for name, line, call in _raises():
        code = next((kw.value for kw in call.keywords if kw.arg == "code"), None)
        if not (isinstance(code, ast.Constant) and isinstance(code.value, str) and code.value):
            uncoded.append(f"{name}:{line}")
    assert uncoded == [], f"raise these with code=...: {uncoded}"


def test_a_refusal_carries_its_values_and_its_fallback() -> None:
    with pytest.raises(ImporterParseError) as caught:
        asyncio.run(XpweImporter.parse(b"<?xml version='1.0'?><Altro/>", locale="en"))
    assert caught.value.as_detail() == {
        "code": "xpwe_wrong_root",
        "params": {"root": "Altro"},
        "message": str(caught.value),
    }


def test_a_malformed_file_says_where_it_broke() -> None:
    with pytest.raises(ImporterParseError) as caught:
        asyncio.run(XpweImporter.parse(b"<PweDocumento>\n<broken", locale="en"))
    assert caught.value.code == "xpwe_not_well_formed"
    assert caught.value.params["line"] == 2
