"""What the browser cold-start lane publishes when a test inside it does not pass.

The lane's verdict used to be an exit code. Its first Windows failure read, on
the run page, as ``browser cold start failed: the browser lane exited 1`` beside
a notice saying ``expected=3 unexpected=1``: three of four tests had passed, one
had not, and nothing reachable named it or said why. The job log comes back as an
empty body from the results receiver and the artifact holding the traces is on a
blob host, so the two places that knew were both unreadable from the machine that
had to diagnose it. The lane now reads the failures out of Playwright's own JSON
report and annotates each one.

These cases pin that reading, and the report shape they pin it against is a
measurement rather than a guess: ``FAILED_REPORT`` below is what Playwright
1.63.0 wrote for a spec that printed a metrics line and then failed an
expectation, run with ``--reporter=list,json``, trimmed of the keys this lane
never reads (``config``, ``attachments``, ``startTime``). A walker that was
written against an imagined shape would publish nothing at all and look exactly
like a lane with no failures.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# The lane lives one directory down, in scripts/ci/, and this file does not: the
# step that runs the tests beside the scripts they cover globs `scripts/test_*.py`
# and does not recurse, so a test filed next to this script would be read by
# people and run by nothing.
_SPEC = importlib.util.spec_from_file_location(
    "browser_cold_start_lane", Path(__file__).parent / "ci" / "browser_cold_start_lane.py"
)
assert _SPEC is not None and _SPEC.loader is not None
lane = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = lane
_SPEC.loader.exec_module(lane)

#: Playwright's own colour codes, as they appear in the message it reports.
_RED = "\x1b[31m"
_GREEN = "\x1b[32m"
_DIM = "\x1b[2m"
_RESET = "\x1b[22m"
_OFF = "\x1b[39m"

#: The assertion message exactly as Playwright 1.63.0 wrote it into its report:
#: the sentence, a blank line, the coloured expectation, then the source frame
#: and the stack appended in the ``errors`` list form.
_MESSAGE = (
    "Error: the probe failed on purpose with a message\n\n"
    f"{_DIM}expect({_RESET}{_RED}received{_OFF}{_DIM}).{_RESET}toBe{_DIM}({_RESET}{_GREEN}expected{_OFF}"
    f"{_DIM}) // Object.is equality{_RESET}\n\n"
    f"Expected: {_GREEN}2{_RESET}\nReceived: {_RED}1{_RESET}"
)

#: The same message with the frame and the stack, which is the form the report's
#: ``errors`` list carries and the form a reader cannot use: flattened onto one
#: annotation line, the frame alone is longer than the sentence it came from.
_MESSAGE_WITH_FRAME = (
    _MESSAGE + "\n\n"
    "   6 |     await new Promise((r) => setTimeout(r, 120));\n"
    "   7 |   });\n"
    ">  8 |   expect(1, 'the probe failed on purpose with a message').toBe(2);\n"
    "     |                                                           ^\n"
    "   9 | });\n"
    "  10 |\n"
    "  11 | test('a probe that passes', async () => {\n"
    "    at /runner/e2e/_probe.spec.ts:8:59"
)

FAILED_REPORT: dict[str, object] = {
    "suites": [
        {
            "title": "e2e/_probe.spec.ts",
            "file": "e2e/_probe.spec.ts",
            "line": 0,
            "column": 0,
            "specs": [
                {
                    "title": "a probe that prints then fails",
                    "ok": False,
                    "tags": [],
                    "tests": [
                        {
                            "timeout": 30000,
                            "annotations": [],
                            "expectedStatus": "passed",
                            "projectName": "chromium",
                            "results": [
                                {
                                    "workerIndex": 0,
                                    "status": "failed",
                                    "duration": 130,
                                    "error": {"message": _MESSAGE, "stack": _MESSAGE},
                                    "errors": [{"message": _MESSAGE_WITH_FRAME}],
                                    # The line the spec printed before it asserted,
                                    # which is the whole reason it could print it.
                                    "stdout": [{"text": 'OE-COLD-START-METRICS {"name":"probe","n":1}\n'}],
                                    "stderr": [],
                                    "retry": 0,
                                    "steps": [{"title": "a slow step", "duration": 122}],
                                    "errorLocation": {"file": "/runner/e2e/_probe.spec.ts", "line": 8, "column": 59},
                                }
                            ],
                            "status": "unexpected",
                        }
                    ],
                    "id": "4017c1a587fb7353e638-ba7f12792ba6ae4fa291",
                    "file": "e2e/_probe.spec.ts",
                    "line": 3,
                    "column": 5,
                },
                {
                    "title": "a probe that passes",
                    "ok": True,
                    "tags": [],
                    "tests": [
                        {
                            "timeout": 30000,
                            "expectedStatus": "passed",
                            "projectName": "chromium",
                            "results": [
                                {
                                    "status": "passed",
                                    "duration": 7,
                                    "errors": [],
                                    "stdout": [{"text": 'OE-COLD-START-METRICS {"name":"second","n":2}\n'}],
                                    "steps": [],
                                }
                            ],
                            "status": "expected",
                        }
                    ],
                    "file": "e2e/_probe.spec.ts",
                    "line": 11,
                    "column": 5,
                },
            ],
        }
    ],
    "errors": [],
    "stats": {
        "startTime": "2026-11-23T12:17:29.639Z",
        "duration": 1232.286,
        "expected": 1,
        "skipped": 0,
        "unexpected": 1,
        "flaky": 0,
    },
}


def test_the_test_that_stopped_is_named_by_its_file_its_line_and_its_title() -> None:
    """The annotation has to say which test stopped, or it is not an answer."""
    failures = lane._failures_from(FAILED_REPORT)

    assert len(failures) == 1
    failure = failures[0]
    assert failure["file"] == "e2e/_probe.spec.ts"
    # The attempt's own location, which is where the test stopped, rather than
    # the line the spec declared it on - the two are 3 and 8 here.
    assert failure["line"] == 8
    assert failure["title"] == "a probe that prints then fails"
    assert failure["attempt_status"] == "failed"
    assert failure["duration_ms"] == 130


def test_the_passing_test_in_the_same_report_is_not_a_failure() -> None:
    """A walker that reported every test would drown the one that matters."""
    failures = lane._failures_from(FAILED_REPORT)

    assert [failure["title"] for failure in failures] == ["a probe that prints then fails"]


def test_a_report_in_which_everything_passed_publishes_no_failure() -> None:
    """The quiet case, because a walker that always answers is worse than none."""
    passing = {
        "suites": [
            {
                "file": "e2e/_probe.spec.ts",
                "specs": [
                    {
                        "title": "a probe that passes",
                        "line": 11,
                        "tests": [{"status": "expected", "results": [{"status": "passed", "duration": 7}]}],
                    }
                ],
            }
        ],
        "errors": [],
        "stats": {"expected": 2, "unexpected": 0},
    }

    assert lane._failures_from(passing) == []


def test_the_message_is_the_assertion_and_not_the_frame_or_the_stack() -> None:
    """Flattened onto one line, the frame would push the sentence past the cap."""
    failure = lane._failures_from(FAILED_REPORT)[0]
    message = str(failure["message"])

    assert "the probe failed on purpose with a message" in message
    assert "Expected: 2" in message
    assert "Received: 1" in message
    # The three shapes that are not the message.
    assert "await new Promise" not in message
    assert "^" not in message
    assert "at /runner/e2e/_probe.spec.ts:8:59" not in message
    # And no colour left in it: an annotation is plain text on a web page.
    assert "\x1b" not in message


def test_a_wait_that_ran_out_names_the_innermost_step_that_was_slow() -> None:
    """The outer step is slow because the inner one is, and says nothing else."""
    report = {
        "suites": [
            {
                "file": "e2e/cold-start-first-boot.spec.ts",
                "specs": [
                    {
                        "title": "settings shows support and legal",
                        "line": 315,
                        "tests": [
                            {
                                "status": "unexpected",
                                "results": [
                                    {
                                        "status": "timedOut",
                                        "duration": 240000,
                                        "errors": [{"message": "Test timeout of 240000ms exceeded."}],
                                        "steps": [
                                            {
                                                "title": "Before Hooks",
                                                "duration": 3,
                                                "steps": [{"title": "page.goto", "duration": 1200}],
                                            },
                                            {
                                                "title": "expect.toBeVisible",
                                                "duration": 239000,
                                            },
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    failure = lane._failures_from(report)[0]
    assert failure["attempt_status"] == "timedOut"
    # Ordered by duration, longest first, so the step that consumed the wait is
    # the one a reader meets first. "Before Hooks" is in the list and last: it
    # took 3ms of its own, and it is only long in a report where the step inside
    # it is long, which is exactly the case this ordering has to survive.
    assert failure["slowest_steps"] == [
        "expect.toBeVisible 239000ms",
        "page.goto 1200ms",
        "Before Hooks 3ms",
    ]


def test_a_failure_nested_in_a_describe_block_is_found_exactly_once() -> None:
    """The report is a tree whose depth is whatever the spec's nesting makes it."""
    inner = {
        "title": "the first session",
        "specs": [
            {
                "title": "a test two levels down",
                "file": "e2e/nested.spec.ts",
                "line": 40,
                "tests": [
                    {
                        "status": "unexpected",
                        "results": [{"status": "failed", "duration": 12, "errors": [{"message": "Error: no"}]}],
                    }
                ],
            }
        ],
    }
    report = {"suites": [{"file": "e2e/nested.spec.ts", "suites": [{"title": "outer", "suites": [inner]}]}]}

    failures = lane._failures_from(report)
    assert [failure["title"] for failure in failures] == ["a test two levels down"]
    assert failures[0]["line"] == 40


def test_a_result_that_carries_only_the_singular_error_key_is_still_read() -> None:
    """Both spellings occur, and a lane that knew one would publish an empty why."""
    report = {
        "suites": [
            {
                "file": "e2e/one.spec.ts",
                "specs": [
                    {
                        "title": "only the singular key",
                        "line": 5,
                        "tests": [
                            {
                                "status": "unexpected",
                                "results": [
                                    {"status": "failed", "duration": 9, "error": {"message": "Error: singular"}}
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    assert "singular" in str(lane._failures_from(report)[0]["message"])


def test_a_failure_with_no_message_at_all_says_so_rather_than_publishing_nothing() -> None:
    report = {
        "suites": [
            {
                "file": "e2e/one.spec.ts",
                "specs": [
                    {
                        "title": "no message",
                        "line": 5,
                        "tests": [{"status": "unexpected", "results": [{"status": "failed", "duration": 1}]}],
                    }
                ],
            }
        ]
    }

    assert "carried no message" in str(lane._failures_from(report)[0]["message"])


def test_the_metrics_of_a_test_that_then_failed_are_still_collected() -> None:
    """Why the spec prints before it asserts, pinned from the report's own shape.

    Playwright keeps the stdout of a failed result, so a line printed before the
    assertion survives the failure that follows it. A spec that printed after its
    assertions would publish nothing in exactly the run that needed publishing.
    """
    metrics = lane._metrics_from(FAILED_REPORT)

    assert [item["name"] for item in metrics] == ["probe", "second"]


def test_one_annotation_per_failure_and_a_said_number_past_the_cap(capsys) -> None:
    """GitHub keeps ten of a level per step; the eleventh must not vanish quietly."""
    failures: list[dict[str, object]] = [
        {
            "file": "e2e/many.spec.ts",
            "line": index,
            "title": f"test number {index}",
            "attempt_status": "failed",
            "duration_ms": 10,
            "message": f"Error: failure {index}",
            "further_messages": 0,
            "slowest_steps": [],
        }
        for index in range(12)
    ]

    summary_lines = lane._annotate_failures(failures)
    emitted = [line for line in capsys.readouterr().out.splitlines() if line.startswith("::error::")]

    # Ten failures, then the one line that accounts for the two it could not send.
    assert len(emitted) == 11
    assert "2 further failing test(s)" in emitted[-1]
    # The step summary is not capped, so nothing is lost by reading it there.
    assert len(summary_lines) == 13
    assert any("test number 11" in line for line in summary_lines)


def test_an_annotation_is_one_line_however_many_the_message_had(capsys) -> None:
    """A newline ends a workflow command and the rest prints as ordinary output."""
    lane._annotate("error", lane._one_line("first line\nsecond line\n\nlast line", 900))

    emitted = capsys.readouterr().out.splitlines()
    assert emitted == ["::error::first line second line last line"]


def test_a_message_longer_than_the_cap_is_cut_and_says_it_was_cut() -> None:
    one = lane._one_line("x" * 2000, 40)

    assert len(one) == 40
    assert one.endswith("...")


def test_the_cluster_complaints_reach_the_run_page(tmp_path: Path, capsys) -> None:
    """The log tail the lane prints is not readable from everywhere; this is."""
    log_dir = tmp_path / "pgdata" / "log"
    log_dir.mkdir(parents=True)
    (log_dir / "postgresql-2026-11-23_000000.log").write_text(
        "2026-11-23 12:00:00 UTC [1] LOG:  database system is ready to accept connections\n"
        "2026-11-23 12:00:05 UTC [42] ERROR:  could not serialize access due to concurrent update\n"
        "2026-11-23 12:00:06 UTC [42] STATEMENT:  UPDATE oe_projects_project SET x = 1\n"
        "2026-11-23 12:00:09 UTC [43] FATAL:  the database system is shutting down\n",
        encoding="utf-8",
    )

    lane._annotate_database_complaints(tmp_path)
    emitted = capsys.readouterr().out

    assert emitted.count("::error::") == 1
    assert "2 complaint(s)" in emitted
    assert "could not serialize access" in emitted
    # A LOG line is not a complaint and a STATEMENT line is the query, not the
    # verdict on it; neither belongs on the run page.
    assert "ready to accept connections" not in emitted
    assert "STATEMENT" not in emitted


def test_a_cluster_with_nothing_to_complain_about_annotates_nothing(tmp_path: Path, capsys) -> None:
    log_dir = tmp_path / "pgdata" / "log"
    log_dir.mkdir(parents=True)
    (log_dir / "postgresql.log").write_text("LOG:  all is well\n", encoding="utf-8")

    lane._annotate_database_complaints(tmp_path)

    assert capsys.readouterr().out == ""


def test_a_data_directory_with_no_cluster_log_is_not_a_second_failure(tmp_path: Path, capsys) -> None:
    """The evidence is optional; a lane reporting on it must not die for want of it."""
    lane._annotate_database_complaints(tmp_path / "nothing-here")

    assert capsys.readouterr().out == ""
