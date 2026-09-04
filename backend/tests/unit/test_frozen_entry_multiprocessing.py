# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The frozen sidecar has to answer the command lines multiprocessing sends it.

Why this file exists
--------------------

``multiprocessing.freeze_support()`` was called, correctly, in
``backend/app/__main__.py``. ``desktop/pyinstaller.spec`` freezes
``backend/app/cli.py``. So the guard was present in the repository, right in
every detail, and absent from every artifact we shipped. It had never been
observed to fail because it had never been observed to run.

What that cost, measured on macos-latest in run 33834902654: the sidecar
served a cold start and then died on a restart over its own data with

    openconstructionerp: error: argument command: invalid choice:
    'from multiprocessing.resource_tracker import main;main(18)'
    Abort trap: 6

Second launch of the desktop app, first launch having worked.

The first two tests below are the ones that would have caught it. They do not
ask whether some file calls the guard; they ask whether the file the spec
actually freezes calls it, and whether it is called before the parser that
rejected the line above. Everything after them tests the argument scan, which
is the part that can be proved without a runner.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from app.cli import _answer_multiprocessing_re_execution, interpreter_code_argument

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC = REPO_ROOT / "desktop" / "pyinstaller.spec"


def _frozen_entry_script() -> Path:
    """The script ``desktop/pyinstaller.spec`` hands to PyInstaller.

    Read out of the spec rather than hard-coded here, because the whole point
    of this file is that the entry point moved once already and nothing
    noticed.
    """
    spec_source = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(spec_source)

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Analysis"
    ]
    assert len(calls) == 1, f"expected one Analysis() call in {SPEC.name}, found {len(calls)}"

    scripts_arg = calls[0].args[0]
    # Source order, not ast.walk order. The spec spells the path as
    # ``BACKEND / "app" / "cli.py"``, and walk is breadth-first, so it hands
    # back the last fragment first and builds backend/cli.py/app.
    constants = [
        node for node in ast.walk(scripts_arg) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    parts = [node.value for node in sorted(constants, key=lambda node: (node.lineno, node.col_offset))]
    assert parts, (
        f"could not read the entry script out of {SPEC.name}. The spec is built from path fragments and this "
        f"test collects the string literals in the first argument of Analysis(). If the spec now names its "
        f"script some other way, teach this function the new spelling - do not delete the test."
    )

    entry = REPO_ROOT / "backend" / Path(*parts)
    assert entry.is_file(), f"{SPEC.name} names {entry}, which does not exist"
    return entry


def test_the_script_pyinstaller_freezes_calls_freeze_support() -> None:
    """The guard has to live in the file that gets frozen, not next to it."""
    entry = _frozen_entry_script()
    source = entry.read_text(encoding="utf-8")

    assert "freeze_support()" in source, (
        f"{entry.relative_to(REPO_ROOT)} is the script desktop/pyinstaller.spec freezes and it does not call "
        f"multiprocessing.freeze_support(). A spawned child is started as '<exe> --multiprocessing-fork ...' "
        f"and will reach argparse instead."
    )


def test_the_frozen_entry_answers_multiprocessing_before_it_parses_arguments() -> None:
    """Order is the whole defect: argparse sees the line first and exits 2."""
    entry = _frozen_entry_script()
    tree = ast.parse(entry.read_text(encoding="utf-8"))

    main_fn = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"),
        None,
    )
    assert main_fn is not None, f"{entry.name} has no main()"

    def _called_names(node: ast.AST) -> list[str]:
        return [
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        ]

    order: list[str] = []
    for statement in main_fn.body:
        for name in _called_names(statement):
            if name in ("_answer_multiprocessing_re_execution", "_build_parser"):
                order.append(name)

    assert "_answer_multiprocessing_re_execution" in order, "main() never answers the multiprocessing command lines"
    assert "_build_parser" in order, "main() no longer builds a parser; this test needs rewriting"
    assert order.index("_answer_multiprocessing_re_execution") < order.index("_build_parser"), (
        "the multiprocessing guard runs after the parser is built. argparse rejects "
        "'-c from multiprocessing.resource_tracker import main;main(N)' with exit 2 before the guard is reached."
    )


# ── The argument scan ─────────────────────────────────────────────────────
#
# The flags that can appear before -c are whatever
# subprocess._args_from_interpreter_flags derives from the parent's sys.flags.
# The cases below are that function's whole vocabulary, not a sample: a frozen
# build commonly carries no_site, so a scan that only handled a bare -c would
# pass on a CI runner and fail on a user's machine.


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param(["-c", "print(1)"], "print(1)", id="bare"),
        pytest.param(["-S", "-c", "print(1)"], "print(1)", id="no-site"),
        pytest.param(["-I", "-c", "print(1)"], "print(1)", id="isolated"),
        pytest.param(["-E", "-s", "-P", "-c", "print(1)"], "print(1)", id="environment-flags"),
        pytest.param(["-OO", "-BB", "-c", "print(1)"], "print(1)", id="repeated-letters"),
        pytest.param(["-X", "dev", "-c", "print(1)"], "print(1)", id="x-option-takes-a-separate-value"),
        pytest.param(["-Wignore::DeprecationWarning", "-c", "print(1)"], "print(1)", id="w-option-attaches-its-value"),
        pytest.param(
            ["-S", "-c", "from multiprocessing.resource_tracker import main;main(18)"],
            "from multiprocessing.resource_tracker import main;main(18)",
            id="the-line-that-was-measured-in-run-33834902654",
        ),
    ],
)
def test_an_interpreter_invocation_is_recognised(argv: list[str], expected: str) -> None:
    assert interpreter_code_argument(argv) == expected


@pytest.mark.parametrize(
    ("argv", "why"),
    [
        pytest.param([], "no arguments at all is the bare invocation that starts a server", id="empty"),
        pytest.param(["-c"], "-c with nothing after it is not code", id="c-without-payload"),
        pytest.param(["serve", "--port", "8741"], "the ordinary command", id="serve"),
        pytest.param(["doctor"], "the ordinary command", id="doctor"),
        pytest.param(["init-db", "--data-dir", "d"], "the ordinary command", id="init-db"),
        pytest.param(["-h"], "our own help flag", id="help"),
        pytest.param(["-V"], "our own version flag", id="version"),
        pytest.param(
            ["--host", "127.0.0.1", "-c", "x"], "our own long option, and the scan must stop at it", id="long-option"
        ),
        pytest.param(
            ["--multiprocessing-fork", "tracker_fd=18", "pipe_handle=20"],
            "the other mechanism, which freeze_support answers and this must not",
            id="spawned-child",
        ),
    ],
)
def test_an_ordinary_invocation_is_declined(argv: list[str], why: str) -> None:
    assert interpreter_code_argument(argv) is None, why


# ── The dispatcher ────────────────────────────────────────────────────────
#
# The scan above is a pure function and the tests for it prove only that it
# reads argv correctly. These two prove the thing that actually has to happen:
# the code runs, and the process stops rather than falling through into the
# server. They fake sys.frozen because that is the only difference between
# this interpreter and the artifact, and the guard is deliberately inert
# outside a frozen build - an installed console script runs under a real
# interpreter, which the standard library re-executes instead of us.


def test_a_frozen_build_runs_the_code_and_stops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    code = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('yes')"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["openconstructionerp-server", "-S", "-c", code])

    with pytest.raises(SystemExit) as exit_info:
        _answer_multiprocessing_re_execution()

    assert exit_info.value.code == 0
    assert marker.read_text() == "yes", "the code was never executed"


def test_an_unfrozen_build_does_nothing_at_all(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    code = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('yes')"

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "argv", ["openconstructionerp", "-S", "-c", code])

    assert _answer_multiprocessing_re_execution() is None
    assert not marker.exists(), "an unfrozen build executed an argument it should have left to the parser"
