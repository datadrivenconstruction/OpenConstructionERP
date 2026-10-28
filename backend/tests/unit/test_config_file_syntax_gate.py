# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The categorical config-syntax gate has to be able to fail.

scripts/check_config_file_syntax.py parses every tracked YAML and JSON file. A
gate whose good outcome is an empty list is worth nothing until it has been
shown finding something, so this plants a broken file of each kind and requires
the refusal, then requires the real tree to be clean.

The gate exists for the category, not for the files. Both kinds are already
parsed in plenty of places, five unit tests over the workflows and 25 scripts
over the JSON trees they own, but every one of those readers is addressed at a
named file or a single directory, so a malformed file written anywhere else is
read by nothing. For a workflow that is the quiet failure rather than the loud
one: GitHub declines to run a workflow it cannot parse and reports nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "check_config_file_syntax.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_config_file_syntax", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = _load_guard()


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("broken.yaml", "a: [1, 2\nb: :\n"),
        ("broken.yml", "key: value\n\tindented with a tab\n"),
        ("broken.json", '{"a": 1,}\n'),
        ("empty.json", ""),
    ],
)
def test_the_gate_refuses_a_malformed_file(tmp_path: Path, name: str, body: str) -> None:
    """Each planted defect has to come back as a failure, not as silence."""
    planted = tmp_path / name
    planted.write_text(body, encoding="utf-8")

    failures = GUARD.check_paths([str(planted)])

    assert len(failures) == 1, f"{name} parsed cleanly and it should not have: {failures}"
    assert failures[0][0] == str(planted)
    assert failures[0][1], f"{name} was reported with an empty message, which tells the reader nothing"


def test_the_gate_accepts_what_is_actually_valid(tmp_path: Path) -> None:
    """The complement, so a gate that fails everything cannot pass the test above."""
    good_yaml = tmp_path / "fine.yml"
    good_yaml.write_text("on:\n  push:\n    branches: [main]\n---\nsecond: document\n", encoding="utf-8")
    good_json = tmp_path / "fine.json"
    good_json.write_text('{"a": [1, 2], "b": {"c": null}}\n', encoding="utf-8")

    assert GUARD.check_paths([str(good_yaml), str(good_json)]) == []


def test_the_jsonc_exemption_is_scoped_to_tsconfig() -> None:
    """Only tsconfig files are skipped, and every tsconfig file is skipped."""
    assert GUARD.is_jsonc("frontend/tsconfig.json")
    assert GUARD.is_jsonc("frontend/tsconfig.e2e-root.json")
    assert not GUARD.is_jsonc("frontend/package.json")
    assert not GUARD.is_jsonc("some/tsconfig.yaml")
    assert not GUARD.is_jsonc("some/dir/tsconfig-ish/settings.json")


def test_the_tree_itself_parses() -> None:
    """The live verdict, with the population beside it rather than behind it."""
    tracked = GUARD._tracked()
    assert tracked, "git ls-files returned nothing, so this test proved nothing at all"

    jsonc = [path for path in tracked if GUARD.is_jsonc(path)]
    checked = [path for path in tracked if not GUARD.is_jsonc(path)]
    assert len(jsonc) == GUARD.EXPECTED_JSONC, (
        f"{len(jsonc)} tsconfig*.json files, {GUARD.EXPECTED_JSONC} expected: {jsonc}. A new one is a "
        "decision about whether tsc really reads it, not a silent widening."
    )

    failures = GUARD.check_paths(checked)
    assert not failures, f"{len(failures)} of {len(checked)} tracked config files will not parse: {failures}"
