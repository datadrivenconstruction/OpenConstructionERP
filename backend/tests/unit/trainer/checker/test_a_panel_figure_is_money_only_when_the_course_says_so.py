# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The kind of a figure only the panel grades comes from the course, never a default.

Money when ``display_unit`` is a currency code, or when a readback of the same
task reads the same ledger key from a money column. A number for any other
display unit and when the course says nothing: a figure of days or square
metres quantised to pence would be graded and shown as an amount.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.modules.trainer.checker.grading import PanelAnswer, answer_kind, grade_task
from app.modules.trainer.spec import AnswerKeySpec, CourseSpec, TaskSpec, normalise_course_dict

COURSE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "trainer" / "course_fixture_v1.json"


def _course() -> tuple[dict[str, Any], CourseSpec]:
    raw = json.loads(COURSE_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    course, problems = normalise_course_dict(raw)
    assert problems == []
    return course, CourseSpec.model_validate(course)


def _answer(**extra: Any) -> AnswerKeySpec:
    return AnswerKeySpec.model_validate(
        {"name": "x", "ledger_key": "fx_x", "value": "12", "tolerance": "0.5", "graded_by": "panel", **extra}
    )


def _task_with(answer: dict[str, Any], readback: list[dict[str, Any]]) -> TaskSpec:
    course, _spec = _course()
    task = dict(next(t for t in course["tasks"] if t["id"] == "t2-markups"))
    task["answer_key"] = [*task["answer_key"], answer]
    task["readback"] = [*task["readback"], *readback]
    return TaskSpec.model_validate(task)


def test_a_currency_display_unit_is_money_and_any_other_is_a_number() -> None:
    assert answer_kind(_answer(display_unit="GBP")) == "money"
    assert answer_kind(_answer(display_unit="JPY")) == "money"
    assert answer_kind(_answer(display_unit="days")) == "number"
    assert answer_kind(_answer(display_unit="m2")) == "number"


def test_a_figure_the_course_says_nothing_about_is_a_number_not_money() -> None:
    assert answer_kind(_answer()) == "number"
    assert answer_kind(_answer(unit="fraction")) == "percent"


def test_a_readback_of_the_same_ledger_key_lends_its_money_kind() -> None:
    answer = {"name": "fee", "ledger_key": "fx_fee", "value": "100", "tolerance": "0.01", "graded_by": "panel"}
    readback = {
        "what": "Overheads amount (shown, not graded)",
        "expects": ["fx_fee"],
        "probe": {
            "type": "boq.cost_breakdown",
            "args": {"boq_ref": "boq.main", "field": "markup_amount", "markup_name": "Overheads"},
        },
    }
    task = _task_with(answer, [readback])
    fee = next(a for a in task.answer_key if a.name == "fee")
    assert answer_kind(fee, task=task) == "money"


def test_the_fixture_marks_its_panel_only_amounts_as_money() -> None:
    _course_dict, course = _course()
    panel_only = [a for t in course.tasks for a in t.answer_key if a.graded_by == "panel"]
    assert {a.name for a in panel_only} == {"overheads_amount", "alderby_normalized"}
    assert all(answer_kind(a) == "money" for a in panel_only)


def test_a_number_is_not_rounded_to_the_currency() -> None:
    """42.004 m2 against 42 with no tolerance: money would round it to 42.00 and pass it."""
    answer = {"name": "area", "ledger_key": "fx_area", "value": "42", "tolerance": "0.001", "graded_by": "panel"}
    task = _task_with(answer, [])
    outcome = grade_task(task, {"area": PanelAnswer("42.004")}, {}, currency="GBP")
    area = next(f for f in outcome.fields if f.key == "area")
    assert area.verdict == "wrong"
    assert area.observed == "42.004"
