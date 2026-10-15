# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A gate already decided is not shown as the next milestone of the demo schedule."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from app.modules.engineering_brief import seed as brief_seed


class _Svc:
    def __init__(self, gates: list[dict], rows: list[dict]) -> None:
        self.gates, self.rows = gates, rows

    async def _gates(self, project_id: uuid.UUID) -> list[dict]:
        return self.gates

    async def milestone_views(self, project_id: uuid.UUID) -> list[dict]:
        return self.rows


class _Session:
    def __init__(self, acts: dict) -> None:
        self.acts = acts

    async def get(self, model: object, key: uuid.UUID) -> object:
        return self.acts.get(key)

    async def flush(self) -> None:
        return None


def test_only_the_milestone_of_a_decided_gate_is_completed() -> None:
    decided_act, open_act = uuid.uuid4(), uuid.uuid4()
    acts = {
        decided_act: SimpleNamespace(status="not_started", progress_pct="0"),
        open_act: SimpleNamespace(status="not_started", progress_pct="0"),
    }
    svc = _Svc(
        [{"code": "g1", "status": "decided"}, {"code": "g2", "status": "not_started"}],
        [
            {"gate_code": "g1", "activity_id": decided_act},
            {"gate_code": "g2", "activity_id": open_act},
            {"gate_code": None, "activity_id": uuid.uuid4()},
        ],
    )
    done = asyncio.run(brief_seed._complete_decided_gate_milestones(_Session(acts), svc, uuid.uuid4()))
    assert done == 1
    assert (acts[decided_act].status, acts[decided_act].progress_pct) == ("completed", "100")
    assert acts[open_act].status == "not_started"
