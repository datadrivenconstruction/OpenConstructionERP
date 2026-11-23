"""What the cold-start gate does with a lane that never ran, and with one that failed.

``cold-start-gate`` in ``.github/workflows/ci.yml`` is the one stable check that
says "a fresh install works", so a reader of a run does not have to count matrix
legs. At ``68c4f4f7`` it said the opposite of the truth. The macOS leg of the CLI
matrix was never given a runner, the aggregate the gate read was ``abandoned``,
and the gate failed with ``the CLI cold start lane did not pass: abandoned`` on a
run where both browser legs, both CLI legs that ran and the PostgreSQL suite had
all passed. The macOS hosted runners in this repository have a recorded history of
that, which is why the browser matrix next to it has no macOS leg at all.

A leg that never ran is not evidence about the product, and the step already held
that reasoning for one value: ``skipped``, which the browser lane reports when the
frontend build it downloads did not happen. What changed is that the same reading
now covers the two values that mean a runner never arrived, for both lanes, and
that ``failure`` - the one value that is a verdict - still stops the gate.

These cases run the step's own script rather than a copy of it. The copy is what
would drift: a gate weakened or tightened in the workflow would leave a test here
passing against the reasoning it was written with. So the script is parsed out of
the YAML, the two ``needs`` expressions are filled in with the value under test,
and the result is executed under ``bash -e -o pipefail``, which is what
``shell: bash`` runs on a GitHub runner.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"

#: The step's name, which is how the script is found. Pinned rather than taken by
#: index so that a step added above it in the job cannot silently change what this
#: file executes.
GATE_STEP = "Require both cold-start lanes to pass"

_BASH = shutil.which("bash")

#: (CLI lane, browser lane, exit code the gate must give). The three outcomes that
#: mean "no verdict" are tolerated on either lane; every other value, ``failure``
#: above all, is not - and a tolerated value beside a failed lane still fails,
#: because one lane saying nothing is not both lanes saying nothing.
CASES = [
    ("success", "success", 0),
    ("failure", "success", 1),
    ("success", "failure", 1),
    ("failure", "failure", 1),
    ("abandoned", "success", 0),
    ("cancelled", "success", 0),
    ("success", "abandoned", 0),
    ("success", "cancelled", 0),
    ("success", "skipped", 0),
    ("abandoned", "failure", 1),
    ("failure", "abandoned", 1),
]


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


def _run_gate(probe: str, browser: str) -> subprocess.CompletedProcess[str]:
    """Execute the step the way a runner would, with the two needs filled in."""
    script = _gate_script()
    filled = script.replace("${{ needs.cli-cold-start.result }}", probe).replace(
        "${{ needs.cli-browser-cold-start.result }}", browser
    )
    # A gate that reads an expression this test did not substitute would be
    # executing a literal `${{ ... }}` and answering a question about nothing.
    assert "${{" not in filled, "the gate reads an expression this test does not fill in"
    assert _BASH is not None
    return subprocess.run(
        [_BASH, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", filled],
        capture_output=True,
        text=True,
        check=False,
    )


pytestmark = pytest.mark.skipif(_BASH is None, reason="the gate is a bash script and this machine has no bash")


@pytest.mark.parametrize(("probe", "browser", "expected"), CASES)
def test_the_gate_answers_with_the_verdict_it_was_given(probe: str, browser: str, expected: int) -> None:
    finished = _run_gate(probe, browser)

    assert finished.returncode == expected, finished.stdout + finished.stderr


@pytest.mark.parametrize(("probe", "browser", "expected"), CASES)
def test_the_gate_says_which_lane_it_tolerated_and_which_it_failed(probe: str, browser: str, expected: int) -> None:
    """The annotation is the part a reader of the run sees, so it is part of the contract.

    A tolerated outcome has to name the lane and the value it was given: "green on
    the legs that did run" without saying which value earned it is a gate that
    hides its own reasoning, and the value is what lets a reader check the legs on
    the run page against it.
    """
    finished = _run_gate(probe, browser)
    out = finished.stdout

    tolerated = {"skipped", "cancelled", "abandoned"}
    for lane, value in (("CLI cold start", probe), ("browser cold start", browser)):
        if value in tolerated:
            assert f"::warning::the {lane} lane reported {value}" in out
        elif value != "success":
            assert f"::error::the {lane} lane did not pass: {value}" in out

    if expected == 0:
        assert "::error::" not in out, "a gate that passed should not have errored on the way"


def test_the_gate_is_still_attached_to_both_lanes() -> None:
    """Tolerating a leg that never ran is not detaching the gate from the legs that did.

    Read together with the cases above, because a gate whose ``needs`` were
    dropped would pass every one of them and mean nothing.
    """
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["cold-start-gate"]

    assert job["needs"] == ["cli-cold-start", "cli-browser-cold-start"]
    assert job["if"] == "${{ !cancelled() }}"


def test_the_lanes_the_gate_reads_are_the_ones_that_run_the_product() -> None:
    """The two needs are the cold-start lanes, and the CLI one keeps all three platforms.

    macOS stays in the CLI matrix on purpose: a leg that is sometimes not
    allocated is still a leg that covers an installer platform when it is, and the
    gate above is what keeps that from being read as a broken install. What the
    browser matrix does not carry is a macOS leg, and the reason is recorded in
    the job's own comment.
    """
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]

    assert jobs["cli-cold-start"]["strategy"]["matrix"]["os"] == [
        "ubuntu-latest",
        "windows-latest",
        "macos-latest",
    ]
    assert jobs["cli-cold-start"]["strategy"]["fail-fast"] is False
    assert "macos-latest" not in jobs["cli-browser-cold-start"]["strategy"]["matrix"]["os"]
