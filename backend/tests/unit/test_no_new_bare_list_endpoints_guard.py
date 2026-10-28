"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The guard that stops the tree adding bare-list endpoints faster than waves remove them.

The pagination programme had a metering problem rather than an effort problem.
Each wave migrated a batch of registers from ``list[...]`` to ``{items, total,
offset, limit}`` and counted them, and nothing counted the routes arriving in
new modules meanwhile. The census fell from 516 to 496 across one wave, which
looks like progress and would look identical if forty had been migrated and
twenty added. ``scripts/check_no_new_bare_list_endpoints.py`` closes that by
naming every bare-list route that existed when it was written, so the count is
a fact rather than a claim.

What is worth testing here is not that it finds a list annotation. It is the
four shapes around the edge that decide whether the guard is usable at all.

A writer that returns rows is not a truncated read. ``POST /things/`` answering
with the created rows tells nobody anything about a register, and a guard that
flagged it would push authors into wrapping creates in an envelope for no
reason. Only ``get`` is examined.

A single-item read is not a list. ``GET /things/{id}`` returning one row shares
a router and a file with the register beside it, and both are matched by any
scan looking for routes rather than for shapes.

An entry that no longer names a live route is a failure, not a leftover. This
is the one deliberate piece of friction: the allowlist is also the census, and
a census that keeps entries it has outgrown stops counting anything. Worse, the
freed name silently re-permits whatever route later takes it, which is the
failure mode the guard exists to prevent, arriving through the guard's own
front door.

The scanner is asserted against the live tree at the end, because a guard whose
own self-test passes while its scan reads nothing is the exact shape of a
gate that has quietly stopped working.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_no_new_bare_list_endpoints.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_no_new_bare_list_endpoints", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


@pytest.mark.parametrize(
    ("label", "source", "expected"),
    [
        (
            "a list response_model",
            '@router.get("/x/", response_model=list[R])\nasync def list_x(): ...',
            ["list_x"],
        ),
        (
            "no response_model and a list return annotation",
            '@router.get("/x/")\nasync def list_x() -> list[R]: ...',
            ["list_x"],
        ),
        (
            "the typing.List spelling",
            '@router.get("/x/", response_model=List[R])\nasync def list_x(): ...',
            ["list_x"],
        ),
        (
            "a decorator split over several lines",
            '@router.get(\n    "/x/",\n    response_model=list[R],\n)\nasync def list_x(): ...',
            ["list_x"],
        ),
        (
            "an envelope",
            '@router.get("/x/", response_model=XListResponse)\nasync def list_x(): ...',
            [],
        ),
        (
            "a single-item read",
            '@router.get("/x/{i}", response_model=R)\nasync def get_x(i): ...',
            [],
        ),
        (
            "a writer that answers with rows",
            '@router.post("/x/", response_model=list[R])\nasync def bulk(): ...',
            [],
        ),
        (
            "an envelope whose response_model is only the return annotation",
            '@router.get("/x/")\nasync def list_x() -> XListResponse: ...',
            [],
        ),
    ],
)
def test_the_scanner_reads_the_shape_not_the_name(script, label, source, expected):
    """A route is judged by what it answers with, not by what it is called."""
    assert script.bare_list_routes(ast.parse(source)) == expected, label


def test_a_response_model_wins_over_the_return_annotation(script):
    """FastAPI serialises through ``response_model``, so that is what the reader gets.

    A route can declare the envelope to FastAPI and still annotate itself as
    returning rows, or the reverse. The wire shape is the one that matters, and
    reading the annotation when a ``response_model`` is present would judge a
    migrated route by a line FastAPI ignores.
    """
    declared_envelope = '@router.get("/x/", response_model=XListResponse)\nasync def list_x() -> list[R]: ...'
    declared_list = '@router.get("/x/", response_model=list[R])\nasync def list_x() -> XListResponse: ...'
    assert script.bare_list_routes(ast.parse(declared_envelope)) == []
    assert script.bare_list_routes(ast.parse(declared_list)) == ["list_x"]


def test_the_self_test_runs_before_the_scan_and_can_fail(script, monkeypatch):
    """The guard proves it can refuse before it is believed when it accepts."""
    script.self_test()

    monkeypatch.setattr(script, "bare_list_routes", lambda tree: [])
    with pytest.raises(SystemExit) as excinfo:
        script.self_test()
    assert excinfo.value.code == 2, "a scanner that cannot refuse must stop the run, not report a clean tree"


def test_the_failure_message_names_the_class_to_write(script):
    """A gate that only says no costs the next author the same hour every time."""
    advice = script.envelope_advice("daily_diary/router.py::list_entries")
    assert "DailyDiaryListResponse" in advice
    assert "backend/app/modules/daily_diary/schemas.py" in advice
    assert "total: int" in advice
    # The ordering trap that cost this programme a debugging session: the field
    # annotation is a string under `from __future__ import annotations`, so a
    # forward reference parses and then fails when Pydantic builds the model.
    assert "after" in advice and "annotations" in advice


def test_a_stale_allowlist_entry_fails_rather_than_lingering(script, monkeypatch, capsys):
    """A migrated route must leave the list, or the count stops being a count."""
    monkeypatch.setattr(script, "ALLOWED", frozenset(script.ALLOWED | {"ghost/router.py::list_ghosts"}))
    monkeypatch.setattr(script.sys, "argv", ["check_no_new_bare_list_endpoints.py"])
    assert script.main() == 1
    assert "ghost/router.py::list_ghosts" in capsys.readouterr().err


def test_a_new_bare_list_route_fails(script, monkeypatch, capsys):
    """The whole point: a route nobody allowed is refused."""
    trimmed = frozenset(sorted(script.ALLOWED)[1:])
    dropped = sorted(script.ALLOWED)[0]
    monkeypatch.setattr(script, "ALLOWED", trimmed)
    monkeypatch.setattr(script.sys, "argv", ["check_no_new_bare_list_endpoints.py"])
    assert script.main() == 1
    err = capsys.readouterr().err
    assert dropped in err
    assert "ListResponse" in err, "the finding has to say what to write instead"


def test_a_scan_that_reads_too_little_refuses_to_report_success(script, monkeypatch, tmp_path):
    """A walk over nothing prints a clean tree, which is the worst possible pass.

    This has bitten this repository before, in a guard that traversed with the
    wrong working directory, visited zero files and printed OK in under a
    second. The floor is what makes that loud.
    """
    monkeypatch.setattr(script, "MODULES_DIR", tmp_path)
    monkeypatch.setattr(script.sys, "argv", ["check_no_new_bare_list_endpoints.py"])
    assert script.main() == 2


def test_the_live_tree_has_no_unallowed_bare_list_route(script):
    """Asserted here, not only in CI, so a red gate is visible from the test suite.

    Through ``classify``, the function ``main`` calls, rather than by subtracting
    the lists a second time here. The hand-written version knew only about
    ``ALLOWED``; the day the first ``CANNOT_TRUNCATE`` entry landed it reported a
    route the gate itself was happy with, and the finding was about this test
    rather than about the tree. Two copies of the same arithmetic are two things
    to keep in step, and this copy had already drifted.

    ``classify`` also answers a third question the hand-written pair never asked:
    an exempt entry that no longer names a bare-list route. ``--dump`` does not
    print that list and so cannot prune it, which leaves nothing else to say so.
    """
    found, files = script.scan()
    assert files >= script.MIN_FILES_SCANNED, f"only {files} files read, the scan is broken rather than the tree clean"
    added, departed, stale_exempt = script.classify(found, script.ALLOWED, script.CANNOT_TRUNCATE)
    assert added == [], "a new bare-list GET route landed without an envelope"
    assert departed == [], "ALLOWED names routes that no longer exist, prune it with --dump"
    assert stale_exempt == [], "CANNOT_TRUNCATE names a route that is no longer bare, edit it by hand"
