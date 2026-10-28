# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``--version`` must answer, and answer the same thing the subcommand does.

``openconstructionerp --version`` used to exit 2 with "unrecognized arguments"
because the only spelling wired up was the ``version`` subcommand. It is the
first thing most people type at a tool they have just installed, so the first
thing the tool said to them was an argparse error.

The flag now hands the work to ``cmd_version``, and these tests are what keeps
it that way: they run the CLI both ways in a real process and compare the whole
report, so a change that touches one spelling and not the other fails here
rather than in front of a new user.

The version string is pinned to ``backend/pyproject.toml`` rather than to
``importlib.metadata``. That is deliberate and it is the same rule
``test_cli_version_matches_the_running_code`` enforces: the metadata reports
whatever distribution happens to be installed in the environment, which on a
source checkout that has ever seen ``pip install openconstructionerp`` is not
the code being executed. Measured on the machine this was written on, the
metadata said 14.6.0 while the tree said 16.1.0. Asserting against it would
encode the exact bug ``_resolve_version`` exists to prevent.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.cli import _build_parser

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = BACKEND_ROOT / "pyproject.toml"


def _declared_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    assert match, "backend/pyproject.toml has no version line where this test looks for it"
    return match.group(1)


def _run_cli(*argv: str) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI the way a user does, in its own interpreter.

    A subprocess rather than a call to ``main()``, because the exit code is half
    of what is being asserted and an in-process call can only ever report on a
    ``SystemExit`` the test itself unwrapped. The environment is inherited
    untouched: nothing here needs a database, and ``version`` reaches for none.
    """
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *argv],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_the_flag_prints_what_the_subcommand_prints(flag: str) -> None:
    """The regression. Both spellings, one report, exit 0 from each."""
    subcommand = _run_cli("version")
    flagged = _run_cli(flag)

    assert subcommand.returncode == 0, subcommand.stderr
    assert flagged.returncode == 0, f"{flag} exited {flagged.returncode}: {flagged.stderr}"
    assert flagged.stdout == subcommand.stdout, (
        f"{flag} and the version subcommand no longer print the same report:\n"
        f"--- {flag} ---\n{flagged.stdout}\n--- version ---\n{subcommand.stdout}"
    )


@pytest.mark.parametrize("argv", [("version",), ("--version",), ("-V",)])
def test_the_version_printed_is_the_version_of_this_source_tree(argv: tuple[str, ...]) -> None:
    """Exit 0 alone would pass on a report naming any version at all."""
    proc = _run_cli(*argv)

    assert proc.returncode == 0, proc.stderr
    first_line = proc.stdout.splitlines()[0]
    assert first_line == f"OpenConstructionERP v{_declared_version()}", first_line


def test_the_upgrade_pin_still_belongs_to_upgrade() -> None:
    """The control for the flag's dest, and the reason it is not the default one.

    ``upgrade --version 2.6.10`` pins a release to install. A subparser parses
    into its own namespace and copies every key of it onto the parent, so a
    top-level flag sharing that dest would turn this invocation into a version
    print and silently skip the upgrade. Asserted on the parsed namespace and
    not by running it, because running it would run pip.
    """
    args = _build_parser().parse_args(["upgrade", "--version", "2.6.10"])

    assert args.version == "2.6.10"
    assert args.show_version is False


def test_the_flag_is_documented_in_the_help() -> None:
    """It is only discoverable if the help lists it."""
    proc = _run_cli("--help")

    assert proc.returncode == 0, proc.stderr
    assert "--version" in proc.stdout
    assert "-V" in proc.stdout
