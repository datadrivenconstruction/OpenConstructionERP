# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠One evidence collection asks the governance port each question once, not once per provider and area."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.project_governance import evidence as ev
from app.modules.project_governance import public


@pytest.mark.asyncio
async def test_port_calls_are_answered_once_per_collection(monkeypatch) -> None:
    calls = {"model": 0}

    class _Repo:
        def __init__(self, session):
            pass

        async def get_model(self, project_id):
            calls["model"] += 1
            return

    monkeypatch.setattr(public, "GovernanceRepository", _Repo)
    saved = dict(ev._REGISTRY)
    ev._REGISTRY.clear()
    pid = uuid.uuid4()
    session = SimpleNamespace()
    seen = []

    async def provider(sess, project_id, attempt, area):
        seen.append(await public.project_catalogue(sess, project_id))
        return []

    try:
        ev.register_evidence_provider("*", provider, name="memo_probe", blocking=False)
        areas = [SimpleNamespace(code=f"a{i}", applicable=True, retired=False) for i in range(10)]
        await ev.collect_evidence(
            session, pid, ev.GateAttempt(gate_id=uuid.uuid4(), gate_code="g", attempt_no=1), areas
        )
        assert len(seen) == 10
        assert calls["model"] == 1
        # Outside a collection nothing is remembered.
        await public.project_catalogue(session, pid)
        await public.project_catalogue(session, pid)
        assert calls["model"] == 3
    finally:
        ev._REGISTRY.clear()
        ev._REGISTRY.update(saved)
