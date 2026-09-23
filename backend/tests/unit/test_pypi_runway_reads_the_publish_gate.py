# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The pre-tag PyPI check can still find the gate it runs.

``scripts/check_pypi_runway.py`` does not carry its own copy of the size
arithmetic. It pulls the Python out of the publish workflow's size step and
runs that, so the two can never disagree. The price is a dependency on the
step's shape: its name, the heredoc that opens it and the indentation it sits
at. Rename the step or reindent the job and the pre-tag check stops working,
and it stops on the one day somebody runs it, a few minutes before a tag.

So this pins the extraction without touching the network: the step is found,
the source parses, and it is the gate rather than some neighbouring step.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "check_pypi_runway.py"


def _load_runway_script():
    spec = importlib.util.spec_from_file_location("check_pypi_runway", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_runway_script_extracts_the_publish_size_gate() -> None:
    runway = _load_runway_script()

    source = runway.extract_gate()

    tree = ast.parse(source)
    constants = {
        node.targets[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    # The per-file budget, the per-file hard cap and the project-total limit are
    # what make this the size gate rather than a neighbouring step. The runway
    # warning threshold is the part the pre-tag run exists to show.
    missing = {"LIMIT_MIB", "HARD_CAP_MIB", "LIMIT_BYTES", "WARN_DAYS"} - constants
    assert not missing, f"the extracted step is not the size gate, it lacks {sorted(missing)}"
