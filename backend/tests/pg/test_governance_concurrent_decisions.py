# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Two decisions on one gate at the same moment: exactly one is recorded, the other is a 409.

Two independent connections to a throwaway database, each in its own
transaction, run ``decide`` concurrently. The model and gate rows are locked
``FOR UPDATE``, so the second waits for the first to commit, then finds the
gate decided and is refused with ``concurrent_decision``. Without the lock both
would pass the in-review check and the unique ``(gate_id, attempt_no)`` would
be the only thing left between the two, also mapped to 409.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.modules.project_governance.errors import GovernanceError
from app.modules.project_governance.models import GovernanceDecision
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import build_world, decide, gate, prepare_gate

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(("first", "second"), [("go", "go"), ("go", "stop"), ("stop", "recycle")])
async def test_exactly_one_of_two_concurrent_decisions_wins(
    monkeypatch: pytest.MonkeyPatch, first: str, second: str
) -> None:
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(gov_events, "async_session_factory", factory)
        world = await build_world(factory)
        g = await prepare_gate(world, "strategy_to_brief")

        results = await asyncio.gather(decide(world, g.id, first), decide(world, g.id, second), return_exceptions=True)
        wins = [r for r in results if isinstance(r, GovernanceDecision)]
        losses = [r for r in results if isinstance(r, GovernanceError)]
        assert len(wins) == 1, results
        assert len(losses) == 1, results
        assert losses[0].status_code == 409
        assert losses[0].code in {"concurrent_decision", "gate_not_in_review"}
        async with factory() as s:
            n = (await s.execute(select(func.count()).where(GovernanceDecision.gate_id == g.id))).scalar_one()
        assert n == 1
        assert (await gate(world, "strategy_to_brief")).last_outcome == wins[0].outcome
