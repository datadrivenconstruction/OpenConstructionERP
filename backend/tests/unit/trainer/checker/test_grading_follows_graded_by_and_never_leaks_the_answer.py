# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``grade_task`` on the fixture course, with probe results handed in (pure).

The PG suite proves the probes read what the UI writes; this file proves what
the grader does with what they read:

* the item list and its order match the API fixtures the frontend is built on;
* ``panel``, ``probe:<i>``, ``both`` and ``gate`` mean what decisions 11 and 19
  say, and the graded readback set is the course rules' own set;
* the discriminating case: the right numbers typed into the panel with the
  ERP untouched FAIL, the same answers with the ERP right PASS;
* nothing returned gives the expected value away.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.trainer.checker.grading import (
    GradeOutcome,
    PanelAnswer,
    grade_task,
    readback_values,
)
from app.modules.trainer.checker.matching import UNIT_SLIP_DIAGNOSIS_ID
from app.modules.trainer.checker.registry import ProbeResult
from app.modules.trainer.schemas import AttemptResult, CourseProgress, ProgressRings, RingProgress
from app.modules.trainer.spec import CourseSpec, TaskSpec, normalise_course_dict
from app.modules.trainer.validators import build_ledger, graded_readback_indexes

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "trainer"
COURSE_PATH = FIXTURES / "course_fixture_v1.json"
CURRENCY = "GBP"


@pytest.fixture(scope="module")
def course_dict() -> dict[str, Any]:
    raw = json.loads(COURSE_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    normalised, problems = normalise_course_dict(raw)
    assert problems == []
    return normalised


@pytest.fixture(scope="module")
def course(course_dict: dict[str, Any]) -> CourseSpec:
    return CourseSpec.model_validate(course_dict)


@pytest.fixture(scope="module")
def ledger(course_dict: dict[str, Any]) -> dict[str, Any]:
    return build_ledger(course_dict)


def _task(course: CourseSpec, task_id: str) -> TaskSpec:
    return next(t for t in course.tasks if t.id == task_id)


def _read(value: Any, unit: str = "money") -> ProbeResult:
    return ProbeResult(value, unit, "match")  # type: ignore[arg-type]


def _unknown(reason: str, unit: str = "money") -> ProbeResult:
    return ProbeResult(None, unit, "unknown", reason)  # type: ignore[arg-type]


def _options(task: TaskSpec, trace: int = 0, explain: int = 0) -> dict[str, PanelAnswer]:
    ids = {c.kind: c.id for c in task.checks}
    return {ids["trace"]: PanelAnswer(option_index=trace), ids["explain"]: PanelAnswer(option_index=explain)}


def _grade(task: TaskSpec, answers: dict[str, PanelAnswer], results: dict[int, ProbeResult], ledger: Any):
    return grade_task(task, answers, results, currency=CURRENCY, ledger=ledger)


def _attempt(outcome: GradeOutcome, task_id: str) -> AttemptResult:
    """The service wraps the outcome like this; the schema's own checks must hold."""
    zero = RingProgress(done=0, total=5)
    return AttemptResult(
        attempt_id=uuid.uuid4(),
        client_attempt_id=None,
        task_id=task_id,
        verdict=outcome.verdict,
        graded_items=outcome.graded_items,
        passed_items=outcome.passed_items,
        fields=outcome.fields,
        task_status="passed" if outcome.passed else "needs_revision",
        rings=outcome.rings,
        progress=CourseProgress(done=0, total=5, rings=ProgressRings(numbers=zero, trace=zero, explain=zero)),
        unlocked=[],
        regressed=False,
        revealed_hint=None,
        checked_at=dt.datetime.now(dt.UTC),
    )


# ── The discriminating case (decision 6) ─────────────────────────────────────

T1_RIGHT_PANEL = {"direct_cost": PanelAnswer("30414.00")}
#: What the T1 probes read on the seeded, untouched bill: 01.002 has no rate.
T1_ERP_UNTOUCHED = {0: _read(Decimal("16092.00")), 1: _read(Decimal("0"))}
T1_ERP_RIGHT = {0: _read(Decimal("30414.00")), 1: _read(Decimal("46.20"))}


def test_right_numbers_in_the_panel_with_the_erp_untouched_fail(course: CourseSpec, ledger: Any) -> None:
    task = _task(course, "t1-direct-cost")
    outcome = _grade(task, {**T1_RIGHT_PANEL, **_options(task)}, T1_ERP_UNTOUCHED, ledger)

    assert outcome.verdict == "fail"
    wrong = {f.key: f for f in outcome.fields if f.verdict != "ok"}
    assert set(wrong) == {"blockwork_rate", "direct_cost"}
    assert all(f.source == "erp" for f in wrong.values())
    assert wrong["direct_cost"].diagnosis is not None
    assert wrong["direct_cost"].diagnosis.id == "t1-rate-left-zero"
    assert all(f.verdict == "ok" for f in outcome.fields if f.key.endswith(("trace", "explain")))
    _attempt(outcome, task.id)


def test_the_same_panel_answers_pass_once_the_erp_is_right(course: CourseSpec, ledger: Any) -> None:
    task = _task(course, "t1-direct-cost")
    untouched = _grade(task, {**T1_RIGHT_PANEL, **_options(task)}, T1_ERP_UNTOUCHED, ledger)
    right = _grade(task, {**T1_RIGHT_PANEL, **_options(task)}, T1_ERP_RIGHT, ledger)

    assert right.verdict == "pass"
    assert right.graded_items == untouched.graded_items == right.passed_items
    assert right.rings.numbers and right.rings.trace and right.rings.explain
    _attempt(right, task.id)


@pytest.mark.parametrize("task_n", [1, 2, 3, 4, 5])
def test_no_task_passes_on_panel_answers_alone(course: CourseSpec, ledger: Any, task_n: int) -> None:
    """Every task, every answer typed right, no probe read at all: never a pass."""
    task = course.tasks[task_n - 1]
    answers = {a.name: PanelAnswer(str(a.value)) for a in task.answer_key}
    outcome = _grade(task, {**answers, **_options(task)}, {}, ledger)
    assert outcome.verdict == "fail"
    assert any(f.source == "erp" and f.verdict != "ok" for f in outcome.fields)


# ── Item list, order and keys ────────────────────────────────────────────────


def _api(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / "api" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("fixture", "grand_total", "explain"),
    [("attempt_fail.json", "34489.48", 1), ("attempt_pass.json", "34367.82", 0)],
)
def test_the_t2_attempt_matches_the_api_fixture_field_for_field(
    course: CourseSpec, ledger: Any, fixture: str, grand_total: str, explain: int
) -> None:
    task = _task(course, "t2-markups")
    answers = {"overheads_amount": PanelAnswer("2433.12"), **_options(task, trace=0, explain=explain)}
    results = {0: _read(Decimal(grand_total)), 1: _read(Decimal("5.00"), "percent")}
    outcome = _grade(task, answers, results, ledger)
    expected = _api(fixture)

    assert [f.model_dump(mode="json") for f in outcome.fields] == expected["fields"]
    assert outcome.graded_items == expected["graded_items"]
    assert outcome.passed_items == expected["passed_items"]
    assert outcome.verdict == expected["verdict"]
    assert outcome.rings.model_dump() == expected["rings"]


def test_a_gated_readback_is_graded_and_an_informational_one_is_not(course: CourseSpec, ledger: Any) -> None:
    t3 = _task(course, "t3-tender")
    t3_results = {0: _read(Decimal("11250.00")), 1: _read(Decimal("11250.00")), 2: _read("Brackenfold Roofs", "text")}
    t3_answers = {"alderby_normalized": PanelAnswer("11780"), "lowest_normalized": PanelAnswer("11250"), **_options(t3)}
    keys = [f.key for f in _grade(t3, t3_answers, t3_results, ledger).fields]
    assert keys == ["alderby_normalized", "lowest_normalized", "award_amount", "rb2", "t3-trace", "t3-explain"]

    t4 = _task(course, "t4-valuation")
    t4_results = {i: _read(Decimal("1")) for i in range(4)}
    keys = [f.key for f in _grade(t4, {"retention_amount": PanelAnswer("606.90")}, t4_results, ledger).fields]
    assert "rb3" not in keys
    assert keys[:3] == ["gross_valuation", "retention_amount", "net_due"]


def test_the_wrong_awarded_bidder_fails_the_gate(course: CourseSpec, ledger: Any) -> None:
    t3 = _task(course, "t3-tender")
    results = {0: _read(Decimal("11250.00")), 1: _read(Decimal("11250.00")), 2: _read("Alderby Roofing", "text")}
    answers = {"alderby_normalized": PanelAnswer("11780"), "lowest_normalized": PanelAnswer("11250"), **_options(t3)}
    outcome = _grade(t3, answers, results, ledger)
    gate = next(f for f in outcome.fields if f.key == "rb2")
    assert outcome.verdict == "fail"
    assert (gate.verdict, gate.source, gate.observed) == ("wrong", "erp", "Alderby Roofing")


def test_optional_answers_are_never_graded(course: CourseSpec, ledger: Any) -> None:
    t2 = _task(course, "t2-markups")
    keys = [f.key for f in _grade(t2, {}, {}, ledger).fields]
    assert "profit_amount" not in keys


def test_the_graders_erp_items_are_the_course_rules_graded_set(course: CourseSpec, ledger: Any) -> None:
    for task in course.tasks:
        rules_set = graded_readback_indexes(task.model_dump(mode="python"))
        results = {i: _read(Decimal("1")) for i in range(len(task.readback))}
        outcome = _grade(task, {}, results, ledger)
        erp_keys = {f.key for f in outcome.fields if f.source == "erp"}
        graded_by_answer = {
            i
            for a in task.answer_key
            for i, r in enumerate(task.readback)
            if (a.grading.kind == "probe" and a.grading.readback_index == i)
            or (a.grading.kind == "both" and a.ledger_key in r.expects)
        }
        gate_keys = {f"rb{i}" for i in rules_set - graded_by_answer}
        assert gate_keys <= erp_keys, task.id
        probe_answers = {a.name for a in task.answer_key if a.grading.kind in ("probe", "both")}
        assert erp_keys == probe_answers | gate_keys, task.id


# ── graded_by semantics ──────────────────────────────────────────────────────


def test_both_needs_the_panel_and_the_erp(course: CourseSpec, ledger: Any) -> None:
    t4 = _task(course, "t4-valuation")
    erp = {0: _read(Decimal("12138.00")), 1: _read(Decimal("606.90")), 2: _read(Decimal("11531.10"))}
    ok = _grade(t4, {"retention_amount": PanelAnswer("606.90"), **_options(t4)}, erp, ledger)
    assert ok.verdict == "pass"

    panel_wrong = _grade(t4, {"retention_amount": PanelAnswer("364.14"), **_options(t4)}, erp, ledger)
    item = next(f for f in panel_wrong.fields if f.key == "retention_amount")
    assert (item.verdict, item.source, item.observed) == ("wrong", "panel", "364.14")
    assert item.diagnosis is not None and item.diagnosis.id == "t4-wrong-rate"

    erp_wrong = {**erp, 1: _read(Decimal("364.14"))}
    erp_side = _grade(t4, {"retention_amount": PanelAnswer("606.90"), **_options(t4)}, erp_wrong, ledger)
    item = next(f for f in erp_side.fields if f.key == "retention_amount")
    assert (item.verdict, item.source, item.observed) == ("wrong", "erp", "364.14")


def test_both_without_exactly_one_readback_is_an_error(course: CourseSpec, ledger: Any) -> None:
    t4 = _task(course, "t4-valuation").model_copy(deep=True)
    t4.readback[1].expects = []
    outcome = _grade(t4, {"retention_amount": PanelAnswer("606.90")}, {0: _read(Decimal("1"))}, ledger)
    item = next(f for f in outcome.fields if f.key == "retention_amount")
    assert item.verdict == "error"


def test_a_missing_claim_is_missing_and_a_foreign_ref_is_an_error(course: CourseSpec, ledger: Any) -> None:
    t4 = _task(course, "t4-valuation")
    results = {0: _unknown("not_found: progress claim"), 2: _unknown("ref_outside_project: contract.main")}
    outcome = _grade(t4, {}, results, ledger)
    verdicts = {f.key: f.verdict for f in outcome.fields}
    assert verdicts["gross_valuation"] == "missing"
    assert verdicts["net_due"] == "error"
    assert verdicts["retention_amount"] == "error"  # its probe never ran


def test_also_accepted_passes_with_its_convention(course: CourseSpec, ledger: Any) -> None:
    t3 = _task(course, "t3-tender")
    results = {0: _read(Decimal("11250.00")), 1: _read(Decimal("11250.00")), 2: _read("Brackenfold Roofs", "text")}
    answers = {"alderby_normalized": PanelAnswer("11788.00"), "lowest_normalized": PanelAnswer("11250"), **_options(t3)}
    assert _grade(t3, answers, results, ledger).verdict == "pass"


def test_a_profit_rate_entered_as_a_fraction_gets_the_unit_diagnosis(course: CourseSpec, ledger: Any) -> None:
    t2 = _task(course, "t2-markups")
    results = {0: _read(Decimal("34367.82")), 1: _read(Decimal("0.05"), "percent")}
    outcome = _grade(t2, {"overheads_amount": PanelAnswer("2433.12"), **_options(t2)}, results, ledger)
    item = next(f for f in outcome.fields if f.key == "profit_rate")
    assert item.verdict == "wrong"
    assert item.diagnosis is not None and item.diagnosis.id == UNIT_SLIP_DIAGNOSIS_ID
    assert item.diagnosis.message and UNIT_SLIP_DIAGNOSIS_ID not in item.diagnosis.message


def test_a_chosen_option_returns_only_its_own_feedback(course: CourseSpec, ledger: Any) -> None:
    t1 = _task(course, "t1-direct-cost")
    outcome = _grade(t1, _options(t1, trace=2, explain=0), T1_ERP_RIGHT, ledger)
    trace = next(f for f in outcome.fields if f.key == "t1-trace")
    assert trace.verdict == "wrong"
    assert trace.feedback == t1.trace_question.options[2].feedback
    assert not outcome.rings.trace and outcome.rings.explain


def test_an_option_out_of_range_is_an_error_and_none_is_missing(course: CourseSpec, ledger: Any) -> None:
    t1 = _task(course, "t1-direct-cost")
    ids = {c.kind: c.id for c in t1.checks}
    outcome = _grade(t1, {ids["trace"]: PanelAnswer(option_index=9)}, T1_ERP_RIGHT, ledger)
    verdicts = {f.key: f.verdict for f in outcome.fields}
    assert verdicts[ids["trace"]] == "error"
    assert verdicts[ids["explain"]] == "missing"


def test_a_task_with_no_graded_items_never_passes() -> None:
    bare = TaskSpec.model_validate(
        {
            "id": "t9",
            "n": 9,
            "title": "Nothing to grade",
            "module": "boq",
            "opens": "boq.markups_panel",
            "brief": "b",
            "checks": [{"id": "t9-numbers", "kind": "numbers", "prompt": "p"}],
            "trace_question": {"prompt": "p", "options": [{"text": "a", "correct": True, "feedback": "f"}] * 2},
            "explain_question": {"prompt": "p", "options": [{"text": "a", "correct": True, "feedback": "f"}] * 2},
        }
    )
    outcome = grade_task(bare, {}, {}, currency=CURRENCY)
    assert (outcome.verdict, outcome.graded_items) == ("fail", 0)
    assert not outcome.rings.numbers


# ── No leak ──────────────────────────────────────────────────────────────────


def test_a_failed_attempt_never_carries_an_expected_value(course: CourseSpec, ledger: Any) -> None:
    for task, answers, results in [
        (_task(course, "t1-direct-cost"), {"direct_cost": PanelAnswer("17524.20")}, T1_ERP_UNTOUCHED),
        (
            _task(course, "t4-valuation"),
            {"retention_amount": PanelAnswer("1")},
            {i: _read(Decimal("2")) for i in range(4)},
        ),
        (
            _task(course, "t5-variation"),
            {"vr_net": PanelAnswer("1540")},
            {0: _read(Decimal("1540")), 1: _read(Decimal("36082.82"))},
        ),
    ]:
        outcome = _grade(task, answers, results, ledger)
        dumped = _attempt(outcome, task.id).model_dump_json()
        for answer in task.answer_key:
            for text in {str(answer.value), format(answer.value, "f"), format(answer.value.normalize(), "f")}:
                assert f'"{text}"' not in dumped, (task.id, answer.name)
        # No option was chosen, so no option's feedback may appear at all.
        for option in [*task.trace_question.options, *task.explain_question.options]:
            assert option.feedback not in dumped, (task.id, option.text)
        assert '"correct"' not in dumped and "wrong_value" not in dumped and "delta" not in dumped


def test_readback_items_show_the_erp_value_and_never_the_expected_one(course: CourseSpec, ledger: Any) -> None:
    t4 = _task(course, "t4-valuation")
    results = {
        0: _read(Decimal("12138.0000")),
        1: _unknown("not_found"),
        2: _read(Decimal("11531.1")),
        3: _read(Decimal("3.00"), "percent"),
    }
    items = readback_values(t4, results, currency=CURRENCY, ledger=ledger)
    by_id = {i.id: i for i in items}
    assert [i.id for i in items] == ["rb0", "rb1", "rb2", "rb3"]
    assert (by_id["rb0"].state, by_id["rb0"].app_value, by_id["rb0"].kind) == ("match", "12138.00", "money")
    assert (by_id["rb1"].state, by_id["rb1"].app_value) == ("unknown", None)
    assert by_id["rb2"].state == "match"
    # rb3 is informational (inline expect 5, no gate): shown, never graded.
    assert (by_id["rb3"].state, by_id["rb3"].app_value, by_id["rb3"].kind) == ("mismatch", "3.00", "percent")
    dumped = json.dumps([i.model_dump(mode="json") for i in items])
    assert "606.90" not in dumped and '"5"' not in dumped
