# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The task panel the service builds matches what the checker grades.

The service never stores a task view: it derives the panel fields from the
spec on every read. If that derivation and ``grade_task`` disagree on a single
answer name, the learner has no field to type the value the grader waits for,
and the task can never pass. These tests compare the two over every task of
the fixture course, and over the real courses when ``OE_TRAINER_COURSES_DIR``
names a directory.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.trainer.checker.grading import PanelAnswer, grade_task, ledger_labels
from app.modules.trainer.checker.registry import ProbeResult
from app.modules.trainer.loader import parse_course_bytes
from app.modules.trainer.schemas import ChoiceCheckView, FieldResult, NumbersCheckView
from app.modules.trainer.service import (
    _given_view,
    answer_names,
    check_views,
    readback_views,
    rings_of,
    task_status,
)
from app.modules.trainer.spec import CourseSpec, TaskSpec
from app.modules.trainer.validators import build_ledger

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "trainer" / "course_fixture_v1.json"


def _spec(path: Path) -> CourseSpec:
    parsed = parse_course_bytes(path.read_bytes(), path.name)
    assert parsed.errors == [], parsed.errors
    assert parsed.spec is not None
    return CourseSpec.model_validate(parsed.spec)


def _course_paths() -> list[Path]:
    paths = [FIXTURE]
    directory = os.environ.get("OE_TRAINER_COURSES_DIR", "")
    if directory and Path(directory).is_dir():
        paths.extend(sorted(Path(directory).glob("course_*_v*.json")))
    return paths


COURSE_PATHS = _course_paths()


def _loadable(path: Path) -> CourseSpec | None:
    parsed = parse_course_bytes(path.read_bytes(), path.name)
    return CourseSpec.model_validate(parsed.spec) if parsed.spec is not None and not parsed.errors else None


@pytest.mark.parametrize("path", COURSE_PATHS, ids=[p.name for p in COURSE_PATHS])
def test_every_course_file_in_scope_loads(path: Path) -> None:
    # A course that does not load is a failure here, never a silent skip: the
    # parity below would read green without it.
    parsed = parse_course_bytes(path.read_bytes(), path.name)
    assert parsed.errors == [], parsed.errors


def _courses() -> list[CourseSpec]:
    return [spec for spec in (_loadable(p) for p in COURSE_PATHS) if spec is not None]


def _graded_panel_names(task: TaskSpec) -> set[str]:
    """Every name ``grade_task`` reads from the stored answers."""
    names = {a.name for a in task.answer_key if a.grading.has_panel_field}
    names |= {c.id for c in task.checks if c.kind in ("trace", "explain")}
    return names


TASKS = [(spec, task) for spec in _courses() for task in spec.tasks]


@pytest.mark.parametrize(("spec", "task"), TASKS, ids=[f"{s.id}:{t.id}" for s, t in TASKS])
def test_every_name_the_grader_reads_has_exactly_one_panel_field(spec: CourseSpec, task: TaskSpec) -> None:
    views = check_views(task, spec.currency)
    names = answer_names(views)
    assert set(names) == _graded_panel_names(task)
    keys = [f.key for v in views if isinstance(v, NumbersCheckView) for f in v.fields]
    keys += [v.id for v in views if isinstance(v, ChoiceCheckView)]
    assert len(keys) == len(set(keys)), "an answer name repeats across checks"


@pytest.mark.parametrize(("spec", "task"), TASKS, ids=[f"{s.id}:{t.id}" for s, t in TASKS])
def test_the_panel_carries_no_correct_flag_and_no_expected_value(spec: CourseSpec, task: TaskSpec) -> None:
    views = check_views(task, spec.currency)
    dumped = json.dumps(
        [v.model_dump(mode="json") for v in views] + [r.model_dump(mode="json") for r in readback_views(task)]
    )
    assert '"correct"' not in dumped
    for question in (task.trace_question, task.explain_question):
        for option in question.options:
            if option.feedback:
                assert option.feedback not in dumped
    for answer in task.answer_key:
        value = format(answer.value, "f")
        if len(value.replace(".", "").lstrip("0")) >= 3:  # short numbers collide with ordinary text
            assert value not in dumped, f"{answer.name} = {value} leaks into the panel"


def test_choice_options_are_indexed_in_order_and_number_kinds_follow_the_course() -> None:
    spec = _spec(FIXTURE)
    t2 = next(t for t in spec.tasks if t.n == 2)
    views = check_views(t2, spec.currency)
    numbers = next(v for v in views if isinstance(v, NumbersCheckView))
    field = next(f for f in numbers.fields if f.key == "overheads_amount")
    assert (field.kind, field.currency) == ("money", "GBP")
    for view in views:
        if isinstance(view, ChoiceCheckView):
            assert [o.index for o in view.options] == list(range(len(view.options)))


def test_a_rate_given_as_a_fraction_is_shown_in_percent() -> None:
    spec = _spec(FIXTURE)
    ledger = build_ledger(spec.model_dump(mode="python", by_alias=True, exclude_unset=True))
    t2 = next(t for t in spec.tasks if t.n == 2)
    shown = {g.name: _given_view(g, ledger, spec.currency) for g in t2.given}
    overheads = shown["Overheads rate"]
    assert overheads is not None
    assert (overheads.kind, Decimal(overheads.value)) == ("percent", Decimal("8"))


@pytest.mark.parametrize("passing", [True, False])
def test_rings_rebuilt_from_stored_fields_match_the_grader(passing: bool) -> None:
    spec = _spec(FIXTURE)
    t1 = next(t for t in spec.tasks if t.n == 1)
    answers: dict[str, PanelAnswer] = {}
    for check in t1.checks:
        if check.kind in ("trace", "explain"):
            question = t1.trace_question if check.kind == "trace" else t1.explain_question
            correct = next(i for i, o in enumerate(question.options) if o.correct)
            answers[check.id] = PanelAnswer(option_index=correct if passing else (correct + 1) % len(question.options))
    outcome = grade_task(t1, answers, {}, currency=spec.currency)
    stored = [FieldResult.model_validate(f.model_dump(mode="json")) for f in outcome.fields]
    assert rings_of(t1, stored) == outcome.rings


class _State:
    def __init__(self, state: str) -> None:
        self.state = state


@pytest.mark.parametrize(
    ("state", "last_passed", "has_answers", "expected"),
    [
        ("locked", None, False, "locked"),
        ("passed", False, True, "passed"),
        ("unlocked", False, True, "needs_revision"),
        ("unlocked", None, True, "in_progress"),
        ("unlocked", None, False, "not_started"),
    ],
)
def test_task_status_follows_the_state_and_the_last_own_check(
    state: str, last_passed: bool | None, has_answers: bool, expected: str
) -> None:
    assert task_status(_State(state), last_passed, has_answers) == expected  # type: ignore[arg-type]


def test_a_related_value_takes_its_spec_label_then_the_course_fallback_then_none() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    spec = _spec(FIXTURE)
    labels = ledger_labels(spec.tasks)
    assert labels["fx_direct_cost"] == "Direct cost in the bill footer"
    assert labels["fx_overheads_rate"] == "Overheads rate"
    assert "fx_block_amount" not in labels

    untouched = {
        0: ProbeResult(value=Decimal("16092.00"), unit="money", status="mismatch"),
        1: ProbeResult(value=Decimal(0), unit="money", status="mismatch"),
    }

    def related(task: TaskSpec, fallback: dict[str, str] | None) -> list[tuple[str, str | None]]:
        outcome = grade_task(task, {}, untouched, currency=spec.currency, labels=fallback)
        return [(r.name, r.label) for f in outcome.fields if f.diagnosis for r in f.diagnosis.related]

    t1 = next(t for t in spec.tasks if t.n == 1)
    assert related(t1, {"fx_block_amount": "Fallback"}) == [("fx_block_amount", "Blockwork amount")], "spec wins"

    del raw["tasks"][0]["diagnoses"][0]["related"][0]["label"]
    bare = TaskSpec.model_validate(
        CourseSpec.model_validate(parse_course_bytes(json.dumps(raw).encode(), FIXTURE.name).spec).tasks[0]
    )
    assert related(bare, {"fx_block_amount": "Fallback"}) == [("fx_block_amount", "Fallback")]
    assert related(bare, None) == [("fx_block_amount", None)]
