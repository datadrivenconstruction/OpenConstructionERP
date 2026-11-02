# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Post-calculation books a timesheet line to its direct BOQ position first.

Field-time productivity resolves a line by ``boq_position_id`` before cost code
and WBS; post-calculation must resolve the same line to the same position, or
the two screens show different hours for one position.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.field_time import counted, repository
from app.modules.postcalc.service import PostCalcService


def _line(**kw: object) -> SimpleNamespace:
    base = {"cost_code": "", "wbs": "", "boq_position_id": None, "resource_id": uuid.uuid4(), "equipment_id": None}
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_direct_position_link_wins_over_cost_code(monkeypatch: pytest.MonkeyPatch) -> None:
    pos_a, pos_b, foreign = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    lines = [
        _line(cost_code="A", boq_position_id=pos_b, hours=Decimal("8")),  # direct link beats code A
        _line(cost_code="A", hours=Decimal("2")),  # no link: cost code
        _line(cost_code="A", boq_position_id=foreign, hours=Decimal("1")),  # link outside the report: fall back
    ]
    ts = SimpleNamespace(lines=lines)

    async def _list(self: object, project_id: uuid.UUID, limit: int) -> tuple[list[SimpleNamespace], int]:
        return [ts], 1

    async def _rates(self: object, project_id: uuid.UUID, approved: list[object]) -> tuple[dict, dict]:
        return {}, {}

    monkeypatch.setattr(repository.FieldTimeRepository, "list_for_project", _list)
    monkeypatch.setattr(counted, "is_counted_timesheet", lambda _ts: True)
    monkeypatch.setattr(PostCalcService, "_resolve_rates", _rates)

    svc = PostCalcService.__new__(PostCalcService)
    svc.session = None
    actuals = await svc._load_field_actuals(uuid.uuid4(), {"A": pos_a, "B": pos_b}, {})

    assert actuals[pos_b]["labour_hours"] == Decimal("8")
    assert actuals[pos_a]["labour_hours"] == Decimal("3")
    assert foreign not in actuals
