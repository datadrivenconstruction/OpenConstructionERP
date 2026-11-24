"""What the cold-start gate requires of each leg, and what it tolerates from one.

``cold-start-gate`` in ``.github/workflows/ci.yml`` is the one stable check that
says "a fresh install works", so a reader of a run does not have to count matrix
legs. It judged the two lanes by their aggregates, ``needs.<job>.result``, because
that is all a ``needs`` expression can see - and an aggregate cannot say WHICH leg
never ran. At ``68c4f4f7`` that cost a false red: the macOS leg of the CLI matrix
was never acquired by a hosted runner, the aggregate read ``abandoned``, and the
gate failed on a run where everything that ran had passed. The fix tolerated the
three values that mean "no verdict" on either lane.

Tolerating them on either lane is too much, and this is the correction. The two
lanes are not the same shape. The CLI matrix carries three legs, and the macOS one
is the leg this repository has a recorded history of losing to capacity, so a
missing runner there is an event about GitHub. The browser matrix carries two
legs, ubuntu and windows, and both of them are legs the gate exists for: a lane
whose ubuntu or windows leg did not run has not shown that a fresh install works,
whatever the reason it did not run. An aggregate of ``skipped`` or ``abandoned``
over a two-leg matrix says one of those two legs is missing and cannot say which,
so it has to fail.

So the gate reads what each leg concluded from this run's own job list, the way
``ci-full.yml`` reads its own, and requires:

* ``CLI cold start (ubuntu-latest)`` and ``(windows-latest)`` to have succeeded;
* ``Browser cold start (ubuntu-latest)`` and ``(windows-latest)`` to have
  succeeded, with no tolerated value for either;
* ``CLI cold start (macos-latest)`` to have succeeded, or to report ``skipped``,
  ``cancelled`` or ``abandoned``, which is a runner that never arrived and is
  published as a warning naming the leg;
* at least one leg to have run at all, because a run with no cold-start job in it
  has earned no verdict either way;
* and, when every leg it knows of succeeded, the lane's aggregate to agree - which
  is what catches a leg added to a matrix that this gate was never told about.

When the job list cannot be read the gate says so and falls back to the two
aggregates, tolerating nothing there, because a fallback that cannot see the legs
cannot tell a macOS runner that never arrived from a leg that failed. The one case
that fallback still passes is both aggregates reading ``success``, which cannot be
true unless every leg ran and passed.

These cases run the step's own script rather than a copy of it: the copy is what
would drift. The script is parsed out of the YAML, the two ``needs`` expressions
are filled in, ``gh`` is stubbed with the leg table under test, and the result is
executed under ``bash -e -o pipefail``, which is what ``shell: bash`` runs on a
GitHub runner.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"

#: The step's name, which is how the script is found. Pinned rather than taken by
#: index so that a step added above it in the job cannot silently change what this
#: file executes.
GATE_STEP = "Require both cold-start lanes to pass"

CLI_UBUNTU = "CLI cold start (ubuntu-latest)"
CLI_WINDOWS = "CLI cold start (windows-latest)"
CLI_MACOS = "CLI cold start (macos-latest)"
BROWSER_UBUNTU = "Browser cold start (ubuntu-latest)"
BROWSER_WINDOWS = "Browser cold start (windows-latest)"

#: Every leg both lanes have, all of them green: the ordinary run.
ALL_GREEN = (
    (CLI_UBUNTU, "success"),
    (CLI_WINDOWS, "success"),
    (CLI_MACOS, "success"),
    (BROWSER_UBUNTU, "success"),
    (BROWSER_WINDOWS, "success"),
)

_BASH = shutil.which("bash")


def _legs(*rows: tuple[str, str]) -> tuple[tuple[str, str], ...]:
    return rows


#: (what the CLI matrix aggregated to, what the browser matrix aggregated to,
#: whether this run's job list could be read, the leg table the read returned, and
#: the exit code the gate must give). An aggregate of ``abandoned`` or ``skipped``
#: over the two-leg browser matrix means one of the two legs the gate exists for is
#: missing, and cannot say which, so it fails; over the three-leg CLI matrix it
#: fails too unless the leg table says the missing one was macOS.
CASES: tuple[tuple[str, str, bool, tuple[tuple[str, str], ...], int], ...] = (
    # The ordinary run: every leg ran and passed.
    ("success", "success", True, ALL_GREEN, 0),
    # The macOS runner never arrived, and the three values that say so are the
    # only ones this gate tolerates, on the only leg it tolerates them from.
    (
        "abandoned",
        "success",
        True,
        _legs(
            (CLI_UBUNTU, "success"),
            (CLI_WINDOWS, "success"),
            (CLI_MACOS, "cancelled"),
            (BROWSER_UBUNTU, "success"),
            (BROWSER_WINDOWS, "success"),
        ),
        0,
    ),
    (
        "abandoned",
        "success",
        True,
        _legs(
            (CLI_UBUNTU, "success"),
            (CLI_WINDOWS, "success"),
            (CLI_MACOS, "skipped"),
            (BROWSER_UBUNTU, "success"),
            (BROWSER_WINDOWS, "success"),
        ),
        0,
    ),
    (
        "abandoned",
        "success",
        True,
        _legs(
            (CLI_UBUNTU, "success"),
            (CLI_WINDOWS, "success"),
            (CLI_MACOS, "abandoned"),
            (BROWSER_UBUNTU, "success"),
            (BROWSER_WINDOWS, "success"),
        ),
        0,
    ),
    # A macOS leg that FAILED is a verdict about the product, not a missing runner.
    (
        "failure",
        "success",
        True,
        _legs(
            (CLI_UBUNTU, "success"),
            (CLI_WINDOWS, "success"),
            (CLI_MACOS, "failure"),
            (BROWSER_UBUNTU, "success"),
            (BROWSER_WINDOWS, "success"),
        ),
        1,
    ),
    # A leg the gate requires, failing.
    (
        "failure",
        "success",
        True,
        _legs(
            (CLI_UBUNTU, "failure"),
            (CLI_WINDOWS, "success"),
            (CLI_MACOS, "success"),
            (BROWSER_UBUNTU, "success"),
            (BROWSER_WINDOWS, "success"),
        ),
        1,
    ),
    (
        "success",
        "failure",
        True,
        _legs(
            (CLI_UBUNTU, "success"),
            (CLI_WINDOWS, "success"),
            (CLI_MACOS, "success"),
            (BROWSER_UBUNTU, "success"),
            (BROWSER_WINDOWS, "failure"),
        ),
        1,
    ),
    # The ubuntu leg never arrived and the macOS one did. Same aggregate as the
    # tolerated case above, opposite verdict: this is what an aggregate cannot say.
    (
        "abandoned",
        "success",
        True,
        _legs(
            (CLI_UBUNTU, "cancelled"),
            (CLI_WINDOWS, "success"),
            (CLI_MACOS, "success"),
            (BROWSER_UBUNTU, "success"),
            (BROWSER_WINDOWS, "success"),
        ),
        1,
    ),
    (
        "abandoned",
        "success",
        True,
        _legs(
            (CLI_UBUNTU, "success"),
            (CLI_WINDOWS, "abandoned"),
            (CLI_MACOS, "success"),
            (BROWSER_UBUNTU, "success"),
            (BROWSER_WINDOWS, "success"),
        ),
        1,
    ),
    # A required leg missing from the run entirely.
    (
        "success",
        "abandoned",
        True,
        _legs((CLI_UBUNTU, "success"), (CLI_WINDOWS, "success"), (CLI_MACOS, "success"), (BROWSER_UBUNTU, "success")),
        1,
    ),
    # The browser lane skipped whole, which after the lane's own fix can only mean
    # its frontend failed or never ran. Both of its legs are absent, so there is no
    # evidence that a fresh install works, and the gate says so.
    ("success", "skipped", True, _legs((CLI_UBUNTU, "success"), (CLI_WINDOWS, "success"), (CLI_MACOS, "success")), 1),
    # Zero legs ran: a run with no cold-start job in it earned no verdict.
    ("abandoned", "skipped", True, _legs(), 1),
    # The job list could not be read. Both aggregates success is the one shape that
    # still passes, because it cannot be true unless every leg ran and passed.
    ("success", "success", False, _legs(), 0),
    # The job list could not be read and an aggregate is not success, so the gate
    # cannot tell which leg is missing and tolerates nothing.
    ("abandoned", "success", False, _legs(), 1),
    ("success", "skipped", False, _legs(), 1),
    # A leg this gate requires by name, missing from a run whose aggregate says
    # everything passed. Not a shape a run produces on its own: it is what a leg
    # renamed or added to a matrix looks like from here, and the aggregate cannot
    # see it. The gate requires the leg by name, so it fails.
    (
        "success",
        "success",
        True,
        _legs((CLI_UBUNTU, "success"), (CLI_WINDOWS, "success"), (CLI_MACOS, "success"), (BROWSER_UBUNTU, "success")),
        1,
    ),
    # A browser leg whose runner never arrived. Same three values the macOS leg is
    # tolerated for, opposite verdict: the browser matrix has no macOS leg, so
    # there is no leg in it that a missing runner explains.
    (
        "success",
        "abandoned",
        True,
        _legs(
            (CLI_UBUNTU, "success"),
            (CLI_WINDOWS, "success"),
            (CLI_MACOS, "success"),
            (BROWSER_UBUNTU, "success"),
            (BROWSER_WINDOWS, "cancelled"),
        ),
        1,
    ),
    (
        "abandoned",
        "abandoned",
        True,
        _legs(
            (CLI_UBUNTU, "success"),
            (CLI_WINDOWS, "success"),
            (CLI_MACOS, "cancelled"),
            (BROWSER_UBUNTU, "skipped"),
            (BROWSER_WINDOWS, "success"),
        ),
        1,
    ),
    # The macOS leg missing from the job list entirely is not one of the three
    # values tolerated for it: a matrix that stopped carrying the leg should be a
    # decision made in this gate as well, not one it finds out about silently.
    (
        "success",
        "success",
        True,
        _legs(
            (CLI_UBUNTU, "success"), (CLI_WINDOWS, "success"), (BROWSER_UBUNTU, "success"), (BROWSER_WINDOWS, "success")
        ),
        1,
    ),
    # Drift: every leg this gate knows of succeeded but the matrix disagrees, so
    # the matrix has a leg this gate was never told about.
    ("failure", "success", True, ALL_GREEN, 1),
    ("success", "failure", True, ALL_GREEN, 1),
    (
        "abandoned",
        "success",
        True,
        _legs(
            (CLI_UBUNTU, "success"),
            (CLI_WINDOWS, "success"),
            (CLI_MACOS, "success"),
            (BROWSER_UBUNTU, "success"),
            (BROWSER_WINDOWS, "success"),
        ),
        1,
    ),
)


def _gate_script() -> str:
    """The gate step's script, read out of the workflow it lives in."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["cold-start-gate"]
    steps = job["steps"]
    matching = [step for step in steps if step.get("name") == GATE_STEP]
    assert len(matching) == 1, f"expected one gate step named {GATE_STEP!r}, found {[s.get('name') for s in steps]}"
    script = matching[0]["run"]
    assert isinstance(script, str)
    return script


def _stub_gh(directory: Path, readable: bool, legs: tuple[tuple[str, str], ...]) -> None:
    """A `gh` that answers the one call this step makes, or fails to answer it.

    The fixture is what the real call's ``--jq`` would have printed: one line per
    leg, the job name and its conclusion separated by a tab.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / "gh"
    if not readable:
        stub.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    else:
        rows = "".join(f"{name}\t{conclusion}\n" for name, conclusion in legs)
        stub.write_text(f"#!/usr/bin/env bash\ncat <<'ROWS'\n{rows}ROWS\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)


def _run_gate(
    tmp_path: Path, probe: str, browser: str, readable: bool, legs: tuple[tuple[str, str], ...]
) -> subprocess.CompletedProcess[str]:
    """Execute the step the way a runner would, with its needs and its API filled in."""
    script = _gate_script()
    filled = script.replace("${{ needs.cli-cold-start.result }}", probe).replace(
        "${{ needs.cli-browser-cold-start.result }}", browser
    )
    # A gate that reads an expression this test did not substitute would be
    # executing a literal `${{ ... }}` and answering a question about nothing.
    assert "${{" not in filled, "the gate reads an expression this test does not fill in"

    stub_dir = tmp_path / "bin"
    _stub_gh(stub_dir, readable, legs)
    assert _BASH is not None
    return subprocess.run(
        [_BASH, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", filled],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{stub_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "GITHUB_REPOSITORY": "example-owner/example-repo",
            "GITHUB_RUN_ID": "1",
        },
    )


pytestmark = pytest.mark.skipif(_BASH is None, reason="the gate is a bash script and this machine has no bash")


@pytest.mark.parametrize(("probe", "browser", "readable", "legs", "expected"), CASES)
def test_the_gate_answers_with_the_legs_it_was_given(
    tmp_path: Path, probe: str, browser: str, readable: bool, legs: tuple[tuple[str, str], ...], expected: int
) -> None:
    finished = _run_gate(tmp_path, probe, browser, readable, legs)

    assert finished.returncode == expected, finished.stdout + finished.stderr


@pytest.mark.parametrize(("probe", "browser", "readable", "legs", "expected"), CASES)
def test_the_gate_says_which_leg_it_tolerated_and_which_it_required(
    tmp_path: Path, probe: str, browser: str, readable: bool, legs: tuple[tuple[str, str], ...], expected: int
) -> None:
    """The annotations are the part a reader of the run sees, so they are the contract.

    A tolerated leg has to be named, with the value it reported: "green on the legs
    that did run" without saying which leg earned it is a gate that hides its own
    reasoning. A required leg that did not succeed has to be named too, and the two
    must not be reported in the same words.
    """
    finished = _run_gate(tmp_path, probe, browser, readable, legs)
    out = finished.stdout

    tolerated = {"skipped", "cancelled", "abandoned"}
    for name, value in legs:
        if value == "success":
            continue
        if name == CLI_MACOS and value in tolerated:
            assert f"::warning::{name} reported {value}" in out, out
        elif name == CLI_MACOS and value == "absent":
            assert f"::error::{name} is not in this run's job list at all" in out, out
        else:
            # The error has to name THIS leg and the value it reported. A gate that
            # only said the matrix disagreed would be making a different claim, and
            # one that echoed the leg and then errored about something else would be
            # reporting a required leg as though it were the tolerated one.
            assert f"::error::{name} reported {value}" in out, out

    missing = {CLI_UBUNTU, CLI_WINDOWS, BROWSER_UBUNTU, BROWSER_WINDOWS} - {name for name, _ in legs}
    if readable:
        for name in missing:
            assert f"::error::{name} reported absent" in out, f"the gate did not require {name} by name: {out}"

    if expected == 0:
        assert "::error::" not in out, "a gate that passed should not have errored on the way"
    if not readable:
        assert "::warning::" in out, "an unreadable job list has to be said out loud"


def test_a_run_with_no_cold_start_leg_in_it_says_so(tmp_path: Path) -> None:
    """Zero legs ran is named as that, and not only as four legs that are missing.

    The exit code is the same either way, because every required leg is absent, but
    a reader of the run should be told that nothing ran at all rather than having to
    count four errors to find that out - and a run with no cold-start job in it is a
    different event from a run whose legs failed.
    """
    finished = _run_gate(tmp_path, "abandoned", "skipped", True, ())

    assert finished.returncode == 1, finished.stdout + finished.stderr
    assert "zero cold-start legs ran" in finished.stdout, finished.stdout


def test_the_gate_is_still_attached_to_both_lanes_and_can_read_this_run() -> None:
    """Tolerating a leg that never ran is not detaching the gate from the legs that did.

    ``actions: read`` is what lets the step read this run's own job list, and it is
    the same permission, for the same reason, that ``ci-full.yml``'s gate carries.
    """
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["cold-start-gate"]

    assert job["needs"] == ["cli-cold-start", "cli-browser-cold-start"]
    assert job["if"] == "${{ !cancelled() }}"
    assert job["permissions"] == {"actions": "read", "contents": "read"}


def test_the_legs_the_gate_requires_by_name_are_the_legs_the_lanes_run() -> None:
    """The gate names five jobs, so the matrices that produce them are load-bearing.

    A leg renamed or dropped in a matrix would leave the gate requiring a job that
    does not exist, and a leg added would leave the gate green about a leg it never
    asked for - which the drift guard in the step catches by comparing the legs it
    read against the aggregate the matrix reported. macOS stays in the CLI matrix
    on purpose: a leg that is sometimes not allocated still covers an installer
    platform when it is, and the gate is what keeps a missing runner there from
    being read as a broken install. The browser matrix carries no macOS leg, which
    is why both of its legs are required and neither is tolerated.
    """
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]

    assert jobs["cli-cold-start"]["strategy"]["matrix"]["os"] == ["ubuntu-latest", "windows-latest", "macos-latest"]
    assert jobs["cli-cold-start"]["strategy"]["fail-fast"] is False
    assert jobs["cli-browser-cold-start"]["strategy"]["matrix"]["os"] == ["ubuntu-latest", "windows-latest"]
    assert jobs["cli-browser-cold-start"]["strategy"]["fail-fast"] is False
    assert jobs["cli-cold-start"]["name"] == "CLI cold start (${{ matrix.os }})"
    assert jobs["cli-browser-cold-start"]["name"] == "Browser cold start (${{ matrix.os }})"
