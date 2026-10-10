# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A BOQ line the copilot wrote before 16.3.0 stops claiming a person typed it.

The old write path left ``source="manual"`` on every copilot edit. The line's
copilot thread still records each proposal with its status and confidence, and
the ``boq_copilot_provenance`` repair reads it on boot, because the product
never runs ``alembic upgrade``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.boq.repairs import _run_copilot_provenance

pytestmark = pytest.mark.asyncio


def _proposal(status: str, confidence: float) -> dict:
    return {
        "action_type": "set_unit_rate",
        "payload": {"unit_rate": 42},
        "before": {"unit_rate": "40"},
        "confidence": confidence,
        "source": None,
        "status": status,
    }


async def test_the_thread_decides_and_a_second_boot_changes_nothing(pg_session) -> None:
    from app.modules.boq.copilot_models import PositionCopilotMessage
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"copilot-{uuid.uuid4().hex[:8]}@site.example",
        hashed_password="x",
        full_name="Estimator",
    )
    project = Project(id=uuid.uuid4(), name="Copilot provenance", owner_id=owner.id, currency="EUR")
    boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="Shell")

    def line(ordinal: str, source: str = "manual") -> Position:
        return Position(
            id=uuid.uuid4(), boq_id=boq.id, ordinal=ordinal, description="Concrete", unit="m3", source=source
        )

    auto, accepted, dismissed, typed, already = line("01"), line("02"), line("03"), line("04"), line("05", "cad_import")

    def thread(pos: Position, *proposals: dict) -> PositionCopilotMessage:
        return PositionCopilotMessage(
            position_id=pos.id,
            boq_id=boq.id,
            project_id=project.id,
            role="assistant",
            content="",
            actions=list(proposals),
        )

    for row in (owner, project, boq, auto, accepted, dismissed, typed, already):
        pg_session.add(row)
        await pg_session.flush()
    for row in (
        thread(auto, _proposal("auto_applied", 0.9137254901960784)),
        thread(accepted, _proposal("needs_review", 0.7), _proposal("applied", 0.7)),
        thread(dismissed, _proposal("dismissed", 0.5)),
        thread(already, _proposal("applied", 0.8)),
    ):
        pg_session.add(row)
    await pg_session.flush()

    assert await _run_copilot_provenance(pg_session) == 2

    async def state(pos: Position) -> tuple:
        row = await pg_session.execute(select(Position.source, Position.confidence).where(Position.id == pos.id))
        return tuple(row.one())

    assert await state(auto) == ("ai_copilot_auto", "0.914"), "rounded to fit String(10)"
    assert await state(accepted) == ("ai_copilot_accepted", "0.7")
    assert await state(dismissed) == ("manual", None), "a dismissed proposal never touched the line"
    assert await state(typed) == ("manual", None), "a line with no thread was typed by a person"
    assert (await state(already))[0] == "cad_import", "only lines still claiming 'manual' are rewritten"

    assert await _run_copilot_provenance(pg_session) == 0
