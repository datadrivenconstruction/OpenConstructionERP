# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The constants validation mirrors stay equal to their sources.

Course validation never imports the ORM or a service, because both pull in the
database engine and the loader must also run in a plain script. It mirrors
the few numbers it needs instead; these tests read the source files as text,
so they run without a database too, and fail the moment a source moves.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from app.modules.trainer.spec import COLUMN_LIMITS
from app.modules.trainer.validators import VARIATION_APPROVAL_THRESHOLD

APP_DIR = Path(__file__).resolve().parents[3] / "app"


def _string_lengths(path: Path, class_name: str) -> dict[str, int]:
    """``{column: n}`` for every ``mapped_column(String(n), ...)`` of one model."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    out: dict[str, int] = {}
    for stmt in cls.body:
        if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
            continue
        call = stmt.value
        if not (isinstance(call, ast.Call) and call.args and isinstance(call.args[0], ast.Call)):
            continue
        type_call = call.args[0]
        if getattr(type_call.func, "id", None) == "String" and type_call.args:
            out[stmt.target.id] = type_call.args[0].value  # type: ignore[attr-defined]
    return out


def test_column_limits_match_the_trainer_models() -> None:
    models = APP_DIR / "modules" / "trainer" / "models.py"
    course = _string_lengths(models, "TrainerCourse")
    task_state = _string_lengths(models, "TrainerTaskState")
    answer = _string_lengths(models, "TrainerAnswer")
    assert course, "the parser found no String column; it is reading the wrong thing"
    assert {
        "course_key": course["course_key"],
        "version": course["version"],
        "title": course["title"],
        "language": course["language"],
        "task_id": task_state["task_id"],
        "answer_name": answer["answer_name"],
    } == COLUMN_LIMITS
    assert answer["task_id"] == task_state["task_id"]


def test_the_approval_threshold_matches_the_variations_service() -> None:
    tree = ast.parse((APP_DIR / "modules" / "variations" / "service.py").read_text(encoding="utf-8"))
    values = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign | ast.AnnAssign)
        and any(
            getattr(t, "id", None) == "HIGH_VALUE_APPROVAL_THRESHOLD"
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    assert len(values) == 1
    call = values[0]
    assert isinstance(call, ast.Call) and getattr(call.func, "id", None) == "Decimal"
    assert Decimal(call.args[0].value) == VARIATION_APPROVAL_THRESHOLD  # type: ignore[attr-defined]
