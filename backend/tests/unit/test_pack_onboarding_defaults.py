"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every pack onboarding default must be one of the options it sits next to.

A default that is only a prefix of an option ("Deemed-to-Satisfy" next to
"Deemed-to-Satisfy (DTS)") preselects nothing, so the question starts
unanswered even though the script says it has a default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

PACKS_DIR = Path(__file__).resolve().parents[3] / "packs"
SCRIPTS = sorted(PACKS_DIR.glob("*/src/*/onboarding.yaml"))


def _option_values(options: list[Any]) -> list[Any]:
    return [o.get("value") if isinstance(o, dict) else o for o in options]


def _mismatches(node: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        options = node.get("options")
        default = node.get("default")
        if isinstance(options, list) and default is not None:
            values = _option_values(options)
            picked = default if isinstance(default, list) else [default]
            found += [f"{path}: {d!r}" for d in picked if d not in values]
        for key, value in node.items():
            found += _mismatches(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += _mismatches(value, f"{path}[{i}]")
    return found


def test_scripts_are_found() -> None:
    assert len(SCRIPTS) > 30


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.parts[-4])
def test_every_default_is_one_of_its_options(script: Path) -> None:
    data = yaml.safe_load(script.read_text(encoding="utf-8"))
    assert _mismatches(data) == []
