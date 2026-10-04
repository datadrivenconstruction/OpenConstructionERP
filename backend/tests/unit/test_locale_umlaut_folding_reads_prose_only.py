# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The umlaut-folding guard counts words a reader sees, not identifiers.

A key and an interpolation placeholder are both names the code looks up, so
`{{gross}}` next to the German `Bruttofläche groß` is not the word spelled two
ways: renaming the placeholder would print raw braces at runtime.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_locale_umlaut_folding.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_locale_umlaut_folding", _SCRIPT)
    assert spec and spec.loader, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def test_a_placeholder_is_not_counted_as_a_word(tmp_path: Path) -> None:
    locale = tmp_path / "de.ts"
    locale.write_text(
        'export default {\n    "wall.net": "{{gross}} - {{openings}} Öffnungen =",\n    "wall.big": "groß",\n};\n',
        encoding="utf-8",
    )
    words = guard._words(str(locale))
    assert "gross" not in words
    assert words["groß"] == 1
    assert words["Öffnungen"] == 1


def test_the_same_word_in_prose_is_still_counted(tmp_path: Path) -> None:
    locale = tmp_path / "de.ts"
    locale.write_text('export default {\n    "a": "gross",\n    "b": "groß",\n};\n', encoding="utf-8")
    words = guard._words(str(locale))
    assert words["gross"] == 1
    assert words["groß"] == 1
