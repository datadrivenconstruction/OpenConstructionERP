# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pin which test trees the workflow files say they run.

A test that no lane names does not fail. It reports nothing at all, and an
absent signal is indistinguishable from a green one when you are reading a
list of check marks. Several trees under ``backend/tests`` are in exactly
that position: they are reached only by the bare ``pytest`` in the nightly
full suite, so a break in them is invisible on the commit that caused it.

This does not argue that every tree belongs in the push lane. Some of them
genuinely should not be there, because the push lane has a time budget. What
it argues is that the split should be a decision somebody wrote down, not an
accident of which paths happened to get typed into a workflow file. So the
map below is pinned. Moving a tree between classes is allowed and is
sometimes the right change, but it has to be an edit to this file, which
means it shows up in review instead of drifting.

The workflow files are read as text. Asking GitHub what it ran would be a
better source and is not available from a test, so the honest limit of this
guard is that it checks the configuration and not the runner.

The larger limit is below, in ``REQUIRED_STATUS_CHECKS``. Nothing any of these
classifications describes stops a push to main today, and this file cannot see
that for itself: branch protection lives in the repository settings and leaves
no artefact in the tree, so turning required checks on or off changes nothing
here and no test can go red on it. What is recorded instead is the measurement,
with its date, so that a reader is told rather than left to infer, and so that
whoever writes the change down is sent back to re-read the map.

Every class below is named for the question it answers, which is what the
workflow files declare. That is deliberate and it is the second thing this file
learned about itself: the paragraph above used to explain at length that a
class called ``PUSH_FULL`` did not mean anybody acts on a break, and a reader
of this repository was misled by the label anyway, having never opened the
header. A caveat in a docstring loses to a label in the output, because the
label is what gets quoted.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[2]
TESTS = BACKEND / "tests"
WORKFLOWS = BACKEND.parent / ".github" / "workflows"

# Trees the release and tag workflows own are out of scope here: this is
# about what gates a commit to main, not about what publishes an artifact.
RELEASE_WORKFLOWS = frozenset(
    {
        "release.yml",
        "release-signing.yml",
        "desktop-release.yml",
        "pypi-publish.yml",
    }
)

ROOT_FILES = "tests (root files)"

DECLARED_FULL = "workflow declares: on push, whole tree"
DECLARED_FILTERED = "workflow declares: on push, selector filtered"
DECLARED_NAMED_FILES = "workflow declares: on push, only the files it names"
DECLARED_PATH_FILTERED = "workflow declares: on push, only when its own paths change"
DECLARED_ON_DEMAND = "workflow declares: nightly or manual only"
DECLARED_NOWHERE = "no workflow names it"

#: What actually stops a push to main, read from the repository ruleset on
#: 2026-08-26 rather than from the workflow files this test parses. main is
#: protected by three rules, deletion, non-fast-forward and linear history, and
#: carries no required status checks at all. So no job in any workflow here
#: blocks a merge, whatever its own comments say about itself, and several of
#: them do say it. Recorded as a frozen set rather than fetched, because a
#: guard that queries GitHub is a guard about network conditions: it fails in an
#: offline clone, fails without a token, and fails differently in CI than on a
#: laptop. Re-measure with ``gh api repos/{owner}/{repo}/rulesets``.
REQUIRED_STATUS_CHECKS: frozenset[str] = frozenset()

# DECLARED_NAMED_FILES sits below DECLARED_FILTERED rather than beside it, and the
# reason is what happens to a file added tomorrow. A -k or -m runs against the
# tree as it stands at the time, so a new test file is at least a candidate
# for the filter. A step that lists its files by name cannot pick one up at all
# until somebody edits the workflow, which makes it the weaker promise about
# a tree even when it happens to name a lot of files today.

# What the workflow files declare about each tree today. Read this as the
# current contract, not as an endorsement of it: DECLARED_FILTERED in particular
# means the tree is named but that a -k or -m narrows it to a small slice, which
# is much closer to DECLARED_ON_DEMAND than the workflow file makes it look.
#
# tests/unit reads DECLARED_FULL because ci.yml runs the tree whole and declares
# no continue-on-error. That is a statement about the file and nothing else.
#
# What used to follow that sentence has been remeasured and was wrong. It said
# the job had been red for a long time for an unrelated reason and was treated
# as advisory, and it offered that as the reason the PostgreSQL lane names unit
# files one at a time. Remeasured 2026-08-29: the unrelated reason was the Node
# heap ceiling on the frontend type check and build, fixed on 2026-06-05 and
# 2026-06-06 by d33d9bebf and 9b2007ba7. The type program outgrew that 9216
# ceiling again at e03fcee77, and on 2026-09-21 it went to 12288 in
# frontend/package.json and the ci.yml Type check and Build steps, with the
# architecture manifest taken out of the type program. Either way a red
# Backend CI is a real failure that has to be read rather than discounted.
# Leaving the old sentence in place would have handed the next reader a
# retired reason to go on ignoring the lane.
#
# A second cause of that silence was fixed on the day this was remeasured.
# ci.yml cancelled in progress unconditionally, and this repository pushes
# straight to main, so each push killed the run from the push before it: 28 of
# the last 30 runs on main were cancelled. The block now excludes main. A
# cancelled run reaches no conclusion, nothing goes red, and that silence had
# been standing in for a green.
#
# One reason survives both measurements: no status check is required on main,
# so a full declaration is still not a break anybody is forced to act on, and
# that alone is why the PostgreSQL lane keeps naming unit files one at a time.
# One reason where this comment claimed three, and the two it lost were both
# instruments that had stopped reporting rather than facts about the tests.
EXPECTED: dict[str, str] = {
    "tests/unit": DECLARED_FULL,
    "tests/pg": DECLARED_FULL,
    "tests/integration": DECLARED_FILTERED,
    "tests/modules": DECLARED_FULL,
    "tests/eval": DECLARED_PATH_FILTERED,
    "tests/benchmarks": DECLARED_ON_DEMAND,
    "tests/perf": DECLARED_ON_DEMAND,
    ROOT_FILES: DECLARED_ON_DEMAND,
}

_PYTEST_CALL = re.compile(r"(?:^|\s|&&|\|\||;)(?:python\s+-m\s+)?pytest\b(?P<args>.*)")


def _test_trees() -> set[str]:
    """Every tree under ``backend/tests`` that holds at least one test file.

    Root-level test modules are reported under a single synthetic name,
    because they are gated as a group and there is no directory to name.
    """
    trees: set[str] = set()
    if any(TESTS.glob("test_*.py")):
        trees.add(ROOT_FILES)
    for child in sorted(TESTS.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "__")):
            continue
        if any(child.rglob("test_*.py")) or any(child.rglob("*_test.py")):
            trees.add(f"tests/{child.name}")
    return trees


# The directory a step's ``pytest tests`` is relative to. Anything else is a
# different suite that happens to use the same word: tools/costbase_pipeline
# has its own tests/ directory and its own conftest, and reading its step as a
# bare run of backend/tests marks every backend tree as fully gated by a job
# that never collects a single file from them.
BACKEND_DIR = "backend"


def _working_directory(doc: dict, job: dict, step: dict) -> str:
    """Resolve the directory a step runs in, innermost declaration winning."""
    for scope in (step, job.get("defaults", {}).get("run", {}), doc.get("defaults", {}).get("run", {})):
        if isinstance(scope, dict):
            declared = scope.get("working-directory")
            if isinstance(declared, str) and declared:
                return declared.strip("./")
    return ""


class Invocation:
    """One ``pytest`` command found in one workflow step."""

    def __init__(self, workflow: str, job: str, args: list[str], *, blocking: bool) -> None:
        self.workflow = workflow
        self.job = job
        self.blocking = blocking
        self.paths = [a for a in args if a.startswith("tests")]
        # A lane is filtered whether it narrows by keyword or by marker. The
        # tenant-isolation lane moved from -k to -m, and reading only -k would
        # have promoted it to DECLARED_FULL, recording full coverage of two trees
        # that are still narrowed to a slice.
        self.filtered = "-k" in args or "-m" in args

    @property
    def whole_tree(self) -> bool:
        """A pytest with no path argument collects everything under testpaths."""
        return not self.paths

    @property
    def names_only_files(self) -> bool:
        """True when every path this step gives pytest is narrower than a directory.

        A step that writes out ``tests/integration`` hands pytest the tree and
        collects whatever is in it. A step that lists thirty two files by name
        collects those thirty two, and the difference is invisible if you only
        look at whether the tree's name appears somewhere in the command. That
        is how the access control step came to be read as full coverage of two
        trees it names a handful of files from.

        A path that does not resolve to a directory on disk is counted as the
        narrower case, including one that resolves to nothing at all. The two
        mistakes are not symmetric: reading a tree as narrower than it is makes
        this guard fail and somebody reads it, while reading a file list as a
        whole tree is the silence that had to be noticed by hand.
        """
        return bool(self.paths) and not any((BACKEND / p.split("::")[0]).is_dir() for p in self.paths)


def _split_args(raw: str) -> list[str]:
    """Tokenise a shell argument string, tolerating GitHub expressions."""
    # ${{ matrix.shard }} is not shell syntax and shlex would keep the braces
    # as an opaque token, which is harmless: we only look at paths and -k.
    try:
        return shlex.split(raw, posix=True)
    except ValueError:
        return raw.split()


def _invocations() -> list[Invocation]:
    """Every pytest call in every workflow that a commit to main can trigger."""
    found: list[Invocation] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name in RELEASE_WORKFLOWS:
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        for job_name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            job_blocking = job.get("continue-on-error") is not True
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                run = step.get("run")
                if not isinstance(run, str):
                    continue
                if _working_directory(doc, job, step) != BACKEND_DIR:
                    continue
                blocking = job_blocking and step.get("continue-on-error") is not True
                for line in run.splitlines():
                    # A shell comment is prose, not coverage. Without this, a
                    # step whose comment happens to say `pytest tests/...` reads
                    # as a bare run over every tree, and each one it names is
                    # recorded as fully gated on the strength of a sentence.
                    # That is the false green this file exists to prevent, so
                    # the parser must not be able to manufacture it.
                    if line.lstrip().startswith("#"):
                        continue
                    match = _PYTEST_CALL.search(line)
                    if match is None:
                        continue
                    found.append(
                        Invocation(
                            path.name,
                            job_name,
                            _split_args(match.group("args")),
                            blocking=blocking,
                        )
                    )
    return found


def _push_triggered(name: str) -> tuple[bool, bool]:
    """Whether a workflow runs on push to main, and whether paths narrow it."""
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML resolves an unquoted `on:` key to the boolean True.
    triggers = doc.get("on", doc.get(True)) or {}
    if isinstance(triggers, str):
        triggers = {triggers: None}
    if isinstance(triggers, list):
        triggers = dict.fromkeys(triggers)
    push = triggers.get("push")
    if push is None and "push" not in triggers:
        return False, False
    narrowed = isinstance(push, dict) and bool(push.get("paths") or push.get("paths-ignore"))
    return True, narrowed


def _classify(tree: str, invocations: list[Invocation]) -> str:
    """Rank a tree by the strongest coverage any blocking push lane gives it."""
    best = DECLARED_NOWHERE
    rank = {
        DECLARED_NOWHERE: 0,
        DECLARED_ON_DEMAND: 1,
        DECLARED_PATH_FILTERED: 2,
        DECLARED_NAMED_FILES: 3,
        DECLARED_FILTERED: 4,
        DECLARED_FULL: 5,
    }
    target = "tests" if tree == ROOT_FILES else tree
    for call in invocations:
        if not call.whole_tree and not any(
            target == p or target.startswith(f"{p}/") or p.startswith(f"{target}/") for p in call.paths
        ):
            continue
        # The root modules sit beside the tree directories, so a lane naming
        # tests/unit does not reach them. Only a bare pytest does.
        if tree == ROOT_FILES and not call.whole_tree:
            continue
        if not call.blocking:
            found = DECLARED_ON_DEMAND
        else:
            on_push, narrowed = _push_triggered(call.workflow)
            if not on_push:
                found = DECLARED_ON_DEMAND
            elif call.filtered:
                found = DECLARED_FILTERED
            elif narrowed:
                found = DECLARED_PATH_FILTERED
            elif call.names_only_files:
                found = DECLARED_NAMED_FILES
            else:
                found = DECLARED_FULL
        if rank[found] > rank[best]:
            best = found
    return best


@pytest.fixture(scope="module")
def invocations() -> list[Invocation]:
    return _invocations()


def test_no_class_in_this_file_describes_enforcement() -> None:
    """The pin, and the one thing that can make it come back for review.

    Every class here answers what the workflow files declare. None of them
    answers what stops a push, because as measured nothing does. This file
    cannot notice the setting changing, so it cannot go red on its own the day
    somebody turns required checks on. What it can do is make the person who
    writes that change down re-read the map instead of adding a name to a list
    and moving on, since the moment a check is required these classifications
    stop being the whole story and some of them will need a second column.
    """
    assert not REQUIRED_STATUS_CHECKS, (
        f"main now requires {sorted(REQUIRED_STATUS_CHECKS)}, so this file is no longer only "
        f"describing declarations. Re-read EXPECTED against what is enforced: a tree recorded "
        f"as {DECLARED_FULL!r} in a workflow nobody requires is in a different position from "
        f"the same tree in a workflow that is now required, and the labels here cannot tell "
        f"them apart. Then update this pin with the new measurement and its date."
    )


def test_the_workflows_were_actually_parsed(invocations: list[Invocation]) -> None:
    """A broken parse would make every assertion below vacuously agree."""
    assert len(invocations) >= 5, (
        f"only {len(invocations)} pytest invocations found in {WORKFLOWS}. "
        "The workflow parse is broken, so the coverage map below means nothing."
    )
    assert any(c.whole_tree for c in invocations), "no lane runs the whole tree"
    assert any(c.paths for c in invocations), "no lane names an explicit test path"


def test_every_test_tree_has_a_recorded_gate(invocations: list[Invocation]) -> None:
    """A tree nobody thought about is the failure mode this guard exists for."""
    unrecorded = sorted(_test_trees() - set(EXPECTED))
    assert not unrecorded, (
        "test trees with no recorded CI classification: "
        + ", ".join(unrecorded)
        + ". Add each to EXPECTED with the class it genuinely has. If it is "
        f"{DECLARED_ON_DEMAND!r}, that is allowed, but say so on purpose."
    )


def test_the_expected_map_has_no_dead_entries() -> None:
    """A pin for a tree that no longer exists quietly stops checking anything."""
    stale = sorted(set(EXPECTED) - _test_trees())
    assert not stale, f"EXPECTED names trees that hold no tests: {stale}"


@pytest.mark.parametrize("tree", sorted(EXPECTED))
def test_tree_is_gated_as_recorded(tree: str, invocations: list[Invocation]) -> None:
    """The gate a tree has must be the gate somebody wrote down for it."""
    actual = _classify(tree, invocations)
    assert actual == EXPECTED[tree], (
        f"{tree} is gated as {actual!r}, but this file records {EXPECTED[tree]!r}. "
        "Either the workflow change was not intended, or it was and this line "
        "should change with it. Weakening a gate is a decision, not a detail."
    )


def test_a_pytest_run_in_another_directory_is_not_counted() -> None:
    """``pytest tests`` means a different tests/ in every directory.

    The cost base pipeline has its own suite under tools/costbase_pipeline and
    is attached to the PostgreSQL lane with its own working-directory. Read
    without that directory, its bare path argument matched every backend tree
    by prefix and reported all of them as fully gated by a job that collects
    nothing from them. The trees it wrongly promoted were the four that are
    genuinely filtered or on demand, which is to say exactly the ones this
    file exists to keep honest.
    """
    doc = yaml.safe_load((WORKFLOWS / "ci-postgres.yml").read_text(encoding="utf-8"))
    steps = [
        (job, step)
        for job in (doc.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if isinstance(step, dict) and "costbase_pipeline" in str(step.get("working-directory", ""))
    ]
    assert steps, "the cost base step moved; this test no longer covers what it names"

    job, step = steps[0]
    assert _working_directory(doc, job, step) != BACKEND_DIR
    assert _PYTEST_CALL.search(step["run"]) is not None, "the step no longer calls pytest"

    # The assertion that matters is about the collected set, not about the
    # helper. Checking only that the helper answers correctly would stay green
    # if the filter it feeds were removed, which is the state this test is here
    # to prevent. A bare "tests" path from that step is the fingerprint.
    leaked = [c for c in _invocations() if c.paths == ["tests"]]
    assert not leaked, (
        "a pytest run from outside backend/ is being counted as a run of the "
        f"backend tree: {[(c.workflow, c.job) for c in leaked]}"
    )


def test_the_backend_steps_are_still_counted() -> None:
    """Control. Excluding by directory must not exclude the lane itself.

    Without this, the fix above passes just as well by dropping every
    invocation, which would leave every tree classified as unnamed and the
    recorded map asserting nothing at all.
    """
    from_backend = [c for c in _invocations() if c.workflow == "ci-postgres.yml"]

    assert from_backend, "no pytest invocation survived the working-directory filter"
    assert any(c.paths == ["tests/pg"] for c in from_backend), "the PostgreSQL suite step was filtered out"


def test_naming_files_in_a_tree_is_not_running_the_tree() -> None:
    """Listing a tree's files by name must not read as coverage of the tree.

    The access control job names nineteen files under tests/integration and
    five under tests/modules, one per register it checks for cross tenant
    reads. None of those steps carries a -k, so a classifier that only asks
    whether the tree's name occurs in the command and whether a filter is
    present graded both trees as fully gated on every push. They are not: a
    twentieth integration test can be added and no push lane will ever collect
    it.

    That mistake is the one this file is least able to survive, because it
    turns the guard's answer from "nothing runs this tree" into "everything
    does" while the guard stays green.
    """
    by_file = [
        c
        for c in _invocations()
        if c.blocking and c.names_only_files and any(p.startswith("tests/integration/") for p in c.paths)
    ]
    assert by_file, "no step names integration files any more; this test no longer covers what it names"

    assert all(not c.filtered for c in by_file), (
        "these steps carry a selector, so this test would pass through the filtered "
        "branch and prove nothing about naming files"
    )


def test_a_step_that_names_the_directory_still_counts_as_the_whole_tree() -> None:
    """Control. Telling a file list apart from a directory must not demote both.

    Without this, the check above passes just as well if every path argument
    were treated as narrower than its tree, which would report tests/pg and
    tests/unit as partly gated and quietly invert the map.
    """
    whole = [c for c in _invocations() if c.paths == ["tests/pg"]]
    assert whole, "the PostgreSQL suite step moved; this control no longer covers what it names"
    assert not whole[0].names_only_files, "a directory argument is being read as a list of files"
