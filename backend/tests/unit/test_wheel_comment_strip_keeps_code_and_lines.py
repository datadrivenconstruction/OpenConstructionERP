"""scripts/strip_wheel_comments.py may only drop comments from what the wheel ships."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

SOURCE = '''# Copyright header stays
# SPDX-License-Identifier: AGPL-3.0
"""Module docstring with # not a comment."""

PROMPT = """
# Heading inside a string stays
"""
x = 1  # inline comment goes
    # marked comment stays ⁠
def f(a):
    # body comment goes
    return a + 1  # noqa: E501
'''


def _strip():
    spec = importlib.util.spec_from_file_location("strip_wheel_comments", REPO / "scripts" / "strip_wheel_comments.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.strip_source


def test_only_comments_go_and_lines_stay() -> None:
    src = SOURCE.replace("    # marked", "# marked")
    out = _strip()(src)
    assert ast.dump(ast.parse(out)) == ast.dump(ast.parse(src))
    assert out.count("\n") == src.count("\n")
    assert out.startswith("# Copyright header stays\n# SPDX-License-Identifier: AGPL-3.0\n")
    assert "# Heading inside a string stays" in out
    assert "⁠" in out
    assert "inline comment" not in out
    assert "body comment" not in out
    assert "noqa" not in out
    assert "x = 1\n" in out


def test_shipped_sources_strip_to_the_same_program() -> None:
    strip = _strip()
    for rel in ("backend/app/cli_static.py", "backend/app/core/i18n.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        out = strip(src)
        assert ast.dump(ast.parse(out)) == ast.dump(ast.parse(src))
        assert out.count("\n") == src.count("\n")
        assert len(out) < len(src)
