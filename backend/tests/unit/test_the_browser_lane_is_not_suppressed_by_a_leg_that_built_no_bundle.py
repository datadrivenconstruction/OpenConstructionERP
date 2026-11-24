"""Which legs of the frontend matrix are allowed to stop the browser cold-start lane.

``cli-browser-cold-start`` downloads ``frontend-dist`` and opens it in a browser
against a cold server, because the numbers it publishes - request counts, console
errors, the time to a first healthy response - are properties of the running
product and a test that mocked any of them would have measured the mock. Only the
``ubuntu-latest`` leg of the ``frontend`` matrix uploads that artifact: the bundle
does not depend on the OS, and building it three times would spend ten minutes
answering a question the build already answered. So ``needs.frontend.result`` was
an aggregate of three legs that this lane read as one verdict about a bundle one
of them made.

At ``07d623f7`` the macOS leg was never acquired by a hosted runner. The
aggregate came back ``cancelled``, the lane's ``if`` asked for ``success``, and
the whole lane skipped: no browser evidence at that head, on a run whose
``frontend-dist`` was sitting in the same run's artifacts unexpired at 66,351,876
bytes, uploaded by the ubuntu leg that had passed with the windows leg passed
beside it. A skip is worse than a red here. A red lane is read; a green run with
the evidence absent is only noticed by someone who goes looking for the lane.

So the lane now refuses ``failure`` and ``skipped`` - a frontend that genuinely
broke is already red on the run, and twenty minutes of browser work against its
bundle answers nothing - and tolerates every other value. Naming the tolerated
ones instead took a second run: the first fix accepted ``success`` and
``cancelled``, and at ``ca8efd9e`` the lane skipped again on the same three legs,
ubuntu passed, windows passed, macOS never acquired. The gate on that same run
published the value a matrix really aggregates to when one of its legs is
cancelled for capacity, ``abandoned``, which is not one of the four results GitHub
documents and is what the CLI matrix reported at ``68c4f4f7`` too. An allow list
here has to guess the next undocumented value; a deny list does not.

The asymmetry about the leg that actually matters moved into the refusal step: if
ubuntu is the leg that never ran then there is no artifact, and that step names
the leg that owed it instead of letting the download action report that it could
not find any artifact for the workflow.

``ca8efd9e`` also caught this file, on macOS, in the one backend shard that was
given a runner: ``built interface: 2 entries`` came back as ``built interface:
       2 entries``, because BSD ``wc -l`` pads its count to a fixed width and GNU
does not. One test of 16,288 collected failed, and it was this one. The step now
strips the padding and these cases compare against whitespace-collapsed output
while still asserting that no padding was printed, so the sentence stays portable
without the portability going untested.

The cases below evaluate the lane's own ``if`` expression and execute the refusal
step's own script, both read out of the workflow rather than copied into this
file, so a change there cannot leave these passing against wiring that is no
longer there.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"

LANE = "cli-browser-cold-start"
BUILDER = "frontend"

#: Step names, pinned rather than taken by index so that a step added above one of
#: them cannot silently change what this file reads or executes.
UPLOAD_STEP = "Upload the built bundle"
RECORD_STEP = "Record what the frontend matrix reported"
DOWNLOAD_STEP = "Download the built interface"
REFUSAL_STEP = "Refuse to run against an interface that was not built"
BROWSER_STEP = "Start it through the CLI and drive a browser through the first session"

ARTIFACT = "frontend-dist"
UPLOADED_BY = "ubuntu-latest"

_BASH = shutil.which("bash")

#: (the frontend matrix's aggregate result, whether the run itself was cancelled,
#: whether the lane runs). ``abandoned`` and ``cancelled`` beside ``success`` are
#: the fix: those are what a matrix reports when a leg was never given a runner,
#: and two of the three legs build nothing this lane downloads. ``failure`` and
#: ``skipped`` stay refused, because a frontend that genuinely broke is already red
#: on the run and twenty minutes of browser work on its bundle answers nothing.
IF_CASES = [
    ("success", False, True),
    ("cancelled", False, True),
    # The value a matrix really reports when a leg was never acquired, published
    # by the gate's own warning at ca8efd9e. The allow list this replaced did not
    # contain it, which is why the lane skipped a second time.
    ("abandoned", False, True),
    ("failure", False, False),
    ("skipped", False, False),
    ("success", True, False),
    ("cancelled", True, False),
    ("abandoned", True, False),
    ("failure", True, False),
]

#: (what the download reported, whether a bundle is on disk, the exit code the
#: refusal step must give, and the sentence it must leave on the run). The two
#: failures are not one event wearing two messages: a download that failed means
#: no leg ever uploaded the artifact, while a download that succeeded and produced
#: nothing means an empty bundle was uploaded.
REFUSAL_CASES = [
    ("success", True, 0, "built interface: 2 entries"),
    ("failure", False, 1, "only the ubuntu-latest leg of Frontend CI builds and uploads it"),
    ("success", False, 1, "frontend/dist/index.html is missing; the downloaded bundle is empty"),
]

#: What an ``if`` this file can evaluate is made of. Anything else - a function
#: this translation does not know, a ``contains()``, a context other than the two
#: named here - fails the case loudly rather than being guessed at, which is the
#: point: the day the expression outgrows the translation is the day someone has
#: to say what the new shape means.
_EVALUABLE = re.compile(r"^[A-Za-z_0-9' ()=!<>]*$")

_TRANSLATED = (
    ("!cancelled()", "not RUN_CANCELLED"),
    ("needs.frontend.result", "FRONTEND_RESULT"),
    ("&&", " and "),
    ("||", " or "),
)

_needs_bash = pytest.mark.skipif(_BASH is None, reason="the refusal step is a bash script and this machine has no bash")


def _jobs() -> dict:
    """The workflow's jobs, read fresh so a change on disk is what gets judged."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]


def _steps(job: str) -> dict[str, dict]:
    return {step["name"]: step for step in _jobs()[job]["steps"]}


def _step_order(job: str) -> list[str]:
    return [step["name"] for step in _jobs()[job]["steps"]]


def _lane_runs(frontend_result: str, run_cancelled: bool) -> bool:
    """Evaluate the lane's own ``if`` for one frontend outcome.

    The expression is translated into the equivalent Python and run, rather than
    compared as a string, so that what is being judged is the condition's meaning
    and not its punctuation.
    """
    expression = _jobs()[LANE]["if"]
    assert isinstance(expression, str), f"the lane's if is {expression!r}"
    assert expression.startswith("${{ ") and expression.endswith(" }}"), expression

    python = expression[len("${{ ") : -len(" }}")]
    for github, local in _TRANSLATED:
        python = python.replace(github, local)
    assert _EVALUABLE.fullmatch(python), f"the lane's if uses something this test cannot evaluate: {expression}"

    namespace = {"FRONTEND_RESULT": frontend_result, "RUN_CANCELLED": run_cancelled}
    return bool(eval(python, {"__builtins__": {}}, namespace))


def _run_refusal(cwd: Path, outcome: str, *, bundle_on_disk: bool) -> subprocess.CompletedProcess[str]:
    """Execute the refusal step the way a runner would, with its env filled in."""
    script = _steps(LANE)[REFUSAL_STEP]["run"]
    assert isinstance(script, str)
    # The step's one expression is the download's outcome, handed to it through
    # the environment; a second one would be executed here as a literal.
    assert "${{" not in script, "the refusal step's script reads an expression this test does not fill in"

    dist = cwd / "frontend" / "dist"
    dist.mkdir(parents=True)
    if bundle_on_disk:
        (dist / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
        (dist / "assets").mkdir()
        (dist / "assets" / "app.js").write_text("export {}\n", encoding="utf-8")

    assert _BASH is not None
    return subprocess.run(
        [_BASH, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=cwd,
        env={**os.environ, "DIST_OUTCOME": outcome},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(("frontend_result", "run_cancelled", "expected"), IF_CASES)
def test_the_lane_runs_on_a_bundle_built_beside_a_leg_that_never_ran(
    frontend_result: str, run_cancelled: bool, expected: bool
) -> None:
    assert _lane_runs(frontend_result, run_cancelled) is expected


@_needs_bash
@pytest.mark.parametrize(("outcome", "bundle_on_disk", "expected_code", "expected_line"), REFUSAL_CASES)
def test_the_lane_says_which_leg_owed_it_a_bundle_it_did_not_get(
    tmp_path: Path, outcome: str, bundle_on_disk: bool, expected_code: int, expected_line: str
) -> None:
    finished = _run_refusal(tmp_path, outcome, bundle_on_disk=bundle_on_disk)

    printed = finished.stdout
    assert finished.returncode == expected_code, printed + finished.stderr
    # Collapsed, because BSD `wc -l` pads its count and GNU does not, and this
    # file runs on all three while the step it executes runs on two.
    assert expected_line in " ".join(printed.split()), printed
    if expected_code == 0:
        assert "::error::" not in printed, "a lane that found its bundle should not have errored on the way"
        # Collapsing would also hide the padding, so forbid it outright: a count
        # only comparable on one platform is a count nobody can put in a ceiling.
        assert "  " not in printed.strip(), printed
    else:
        assert "::error::" in printed, printed
        if outcome != "success":
            # A leg that never uploaded has to be reported with the outcome that
            # says so, or a reader cannot tell this from an empty bundle.
            assert outcome in printed, "the annotation has to carry the outcome it was given"


def test_the_bundle_still_comes_from_one_leg_and_that_leg_still_builds_it() -> None:
    """The tolerance above is not bought with platform coverage.

    Read together with the cases: a lane that needed nothing would run on every
    one of them and measure nothing, and a ``frontend`` matrix narrowed to the one
    leg that uploads would make the aggregate honest by deleting the two legs that
    catch path-separator, case-sensitivity and CRLF breakage on the platforms the
    product ships installers for.
    """
    jobs = _jobs()

    upload = _steps(BUILDER)[UPLOAD_STEP]
    assert upload["uses"] == "actions/upload-artifact@v4"
    assert upload["with"]["name"] == ARTIFACT
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["if"] == f"matrix.os == '{UPLOADED_BY}'"

    assert jobs[BUILDER]["strategy"]["matrix"]["os"] == ["ubuntu-latest", "windows-latest", "macos-latest"]
    assert jobs[BUILDER]["strategy"]["fail-fast"] is False
    assert jobs[LANE]["needs"] == [BUILDER]
    assert "macos-latest" not in jobs[LANE]["strategy"]["matrix"]["os"]


def test_the_refusal_reads_the_download_s_real_outcome_and_is_not_gated_on_it() -> None:
    """``continue-on-error`` on the download, and a refusal step that runs anyway.

    Gating the refusal on ``steps.dist.outcome == 'success'`` was what let a
    missing artifact go unnamed: the download's own failure was the only thing
    left to report it, and it reports that it could not find an artifact for the
    workflow, not that the leg which builds it never ran. Tolerating the download
    without the refusal would be worse still - the lane would go on to start a
    server with no interface in it, which serves its own 404 for every route and
    gives the browser a clean, quiet, almost-empty first boot to report as a pass.
    """
    download = _steps(LANE)[DOWNLOAD_STEP]
    refusal = _steps(LANE)[REFUSAL_STEP]

    assert download["id"] == "dist"
    assert download["with"]["name"] == ARTIFACT
    assert download["continue-on-error"] is True
    assert refusal["if"] == "${{ !cancelled() }}"
    assert refusal["env"]["DIST_OUTCOME"] == "${{ steps.dist.outcome }}"
    assert refusal["shell"] == "bash"


def test_the_refusal_happens_before_anything_can_measure_the_missing_bundle() -> None:
    """Order is part of the claim: naming a gap only helps if the lane stops at it."""
    order = _step_order(LANE)

    assert order.index(RECORD_STEP) < order.index(DOWNLOAD_STEP)
    assert order.index(DOWNLOAD_STEP) < order.index(REFUSAL_STEP) < order.index(BROWSER_STEP)


def test_the_lane_publishes_the_aggregate_it_was_given() -> None:
    """The one number a reader of the run cannot otherwise see.

    GitHub publishes each leg's conclusion and publishes nothing about the
    aggregate it computed from them, so at ``ca8efd9e`` the value this lane's
    ``if`` had been given was unknowable from the run page and had to be deduced
    from a warning the gate over a different matrix happened to print. An
    annotation is on the run page; a log line is not, and logs are what nobody
    downloads.
    """
    record = _steps(LANE)[RECORD_STEP]

    assert record["if"] == "${{ !cancelled() }}"
    assert record["shell"] == "bash"
    assert "${{ needs.frontend.result }}" in record["run"]
    assert "::notice::" in record["run"]
