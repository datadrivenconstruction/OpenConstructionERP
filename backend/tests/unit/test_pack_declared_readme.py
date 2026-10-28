# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A pack that declares a readme has to ship one.

``readme = "README.md"`` in ``pyproject.toml`` is not documentation, it is a
build input: setuptools reads the file to fill the distribution's long
description, and a missing file fails the sdist outright. Six packs carried
that declaration with no such file, so their distributions could not be built
at all, and nothing said so until someone tried.

Nothing in the repository builds these packs on every push, which is why the
breakage survived. This test is the cheap standing check that replaces the
build: it costs a stat call per pack and catches the next pack that declares a
readme it does not ship.

Pure filesystem work, no database and no imports from ``app``, so it cannot be
skipped by a database marker.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# backend/tests/unit/<this file> -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKS_DIR = _REPO_ROOT / "packs"

# ``readme = "README.md"``. The table form (``readme = {file = "..."}``) is not
# used anywhere in this tree; if a pack adopts it, the declaration stops
# matching and _declared_readme returns None, which this module's own coverage
# test turns into a failure rather than a silent pass.
_README_RX = re.compile(r"""^\s*readme\s*=\s*["'](?P<path>[^"']+)["']""", re.MULTILINE)
_README_TABLE_RX = re.compile(r"""^\s*readme\s*=\s*\{""", re.MULTILINE)


def _pack_pyprojects() -> list[Path]:
    return sorted(_PACKS_DIR.glob("*/pyproject.toml"))


def _declared_readme(text: str) -> str | None:
    match = _README_RX.search(text)
    return match.group("path") if match else None


def test_pack_pyprojects_exist_to_scan() -> None:
    """A sweep that reached no pack is not a clean sweep."""
    assert _pack_pyprojects(), f"no pack pyproject.toml found under {_PACKS_DIR}"


@pytest.mark.parametrize("pyproject", _pack_pyprojects(), ids=lambda p: p.parent.name)
def test_declared_readme_file_exists(pyproject: Path) -> None:
    """Every declared readme path resolves to a real file next to the pyproject."""
    text = pyproject.read_text(encoding="utf-8")

    assert not _README_TABLE_RX.search(text), (
        f"{pyproject.parent.name} declares its readme in table form, which the "
        "string-form check above cannot read. Extend _README_RX before using it."
    )

    declared = _declared_readme(text)
    if declared is None:
        pytest.skip("pack declares no readme")

    target = pyproject.parent / declared
    assert target.is_file(), (
        f"packs/{pyproject.parent.name}/pyproject.toml declares readme "
        f"{declared!r} but no such file exists, so the sdist cannot be built"
    )
