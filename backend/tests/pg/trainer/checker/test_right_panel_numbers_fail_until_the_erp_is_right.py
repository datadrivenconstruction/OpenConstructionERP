# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the discriminating case (decision 6) end to end on the fixture course.

The T1 bill is built through ``BOQService`` from the course's own seed block,
so 01.002 starts without a rate exactly as the seeder leaves it. The learner
types the right direct cost into the panel and nothing into the ERP: the task
must FAIL, on the ERP items only. After ``update_position`` prices 01.002 the
same panel answers must PASS, with the same graded items.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.boq.schemas import BOQCreate, PositionCreate, PositionUpdate, SectionCreate
from app.modules.boq.service import BOQService
from app.modules.trainer.checker import PanelAnswer, grade_task, run_task_probes
from app.modules.trainer.spec import CourseSpec, TaskSpec, normalise_course_dict
from app.modules.trainer.validators import build_ledger

COURSE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "trainer" / "course_fixture_v1.json"
CURRENCY = "GBP"


@pytest.fixture(scope="module")
def course_dict() -> dict[str, Any]:
    raw = json.loads(COURSE_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    normalised, problems = normalise_course_dict(raw)
    assert problems == []
    return normalised


async def _seed_bill(world, seed: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    service = BOQService(world.session)
    boq = await service.create_boq(BOQCreate(project_id=world.project_id, name=seed["name"]))
    positions: dict[str, Any] = {}
    for section_seed in seed["sections"]:
        section = await service.create_section(
            boq.id, SectionCreate(ordinal=section_seed["ordinal"], description=section_seed["title"])
        )
        for p in (p for p in seed["positions"] if p["section"] == section_seed["ordinal"]):
            positions[p["code"]] = await service.add_position(
                PositionCreate(
                    boq_id=boq.id,
                    parent_id=section.id,
                    ordinal=p["code"],
                    description=p["description"],
                    unit=p["unit"],
                    quantity=p["qty"],
                    unit_rate=Decimal(str(p["rate"])) if p["rate"] is not None else Decimal(0),
                )
            )
    return boq, positions


def _panel(task: TaskSpec) -> dict[str, PanelAnswer]:
    ids = {c.kind: c.id for c in task.checks}
    return {
        "direct_cost": PanelAnswer("30414.00"),
        ids["trace"]: PanelAnswer(option_index=0),
        ids["explain"]: PanelAnswer(option_index=0),
    }


async def test_right_panel_numbers_fail_on_the_untouched_erp_and_pass_once_it_is_priced(
    world, course_dict: dict[str, Any]
) -> None:
    course = CourseSpec.model_validate(course_dict)
    ledger = build_ledger(course_dict)
    task = next(t for t in course.tasks if t.id == "t1-direct-cost")
    boq, positions = await _seed_bill(world, course_dict["seed"]["boq"])
    ctx = world.ctx({"boq.main": boq.id})

    async def attempt():
        results = await run_task_probes(world.session, task, ctx, currency=CURRENCY, ledger=ledger, mode="check")
        return results, grade_task(task, _panel(task), results, currency=CURRENCY, ledger=ledger)

    results, untouched = await attempt()
    assert results[0].value == Decimal("16092.00") and results[1].value == Decimal(0)
    assert untouched.verdict == "fail"
    wrong = {f.key: f for f in untouched.fields if f.verdict != "ok"}
    assert set(wrong) == {"blockwork_rate", "direct_cost"}
    assert all(f.source == "erp" for f in wrong.values())
    assert wrong["direct_cost"].diagnosis is not None
    assert wrong["direct_cost"].diagnosis.id == "t1-rate-left-zero"

    await BOQService(world.session).update_position(positions["01.002"].id, PositionUpdate(unit_rate=Decimal("46.20")))
    _results, priced = await attempt()
    assert priced.verdict == "pass"
    assert priced.graded_items == untouched.graded_items == priced.passed_items
