# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``--strict-markers`` has to stay in ``addopts``, because losing it is silent.

Without the flag a misspelled marker is a ``PytestUnknownMarkWarning`` and the
run still exits 0. The test keeps passing, and it quietly leaves whatever lane
selects on that marker. Measured on a two-test fixture holding one correct and
one misspelled marker: ``pytest -m lane_marker`` reported "1 passed, 1
deselected" and exited 0. A green lane, one test short, and nothing in that
output naming what went missing. ``tenant_isolation`` is applied at 511 sites,
so there is room to lose one in.

With the flag the same fixture is a collection error, exit 2, naming the marker
it could not find. Verified for all three ways a marker reaches a test through
``pytest.mark`` attribute access: the decorator, a module level ``pytestmark``,
and ``marks=`` inside ``parametrize``.

This file does not re-check that pytest enforces the flag. That is upstream's
job, and the flag does it better than any assertion here could. It guards the
one thing the flag cannot guard, which is its own removal. ``addopts`` is a
single line that was empty until 2026-08-30, nothing else reads it, and
emptying it again would restore warning-only behaviour without failing
anything anywhere.

Two gaps, recorded so the next reader does not over-trust the flag.
``item.add_marker`` with a string literal bypasses the check completely; there
is one such call site, in ``tests/pg/conftest.py``, and it applies a builtin
skip. And a typo in an ``-m`` expression on a command line is not a marker at
all, so strictness has no opinion on it. That case does fail, by deselecting
everything and exiting 5, but it fails somewhere else for a different reason.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = BACKEND_ROOT / "pyproject.toml"


def test_strict_markers_is_enabled() -> None:
    ini_options = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    assert "--strict-markers" in ini_options["addopts"], (
        "--strict-markers is gone from addopts in backend/pyproject.toml. An unregistered marker is "
        "a warning again, which means a test carrying a misspelled one silently leaves its lane "
        "while the lane stays green."
    )
