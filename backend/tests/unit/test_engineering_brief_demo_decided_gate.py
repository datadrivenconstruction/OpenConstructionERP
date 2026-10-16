# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A demo brief whose frame document a decided gate made binding is bound, not left in review."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.modules.engineering_brief import seed
from app.modules.project_governance import public as governance

DOC, GATE = uuid.uuid4(), uuid.uuid4()
DECIDED = datetime(2026, 10, 14, 9, tzinfo=UTC)


class _Session:
    async def flush(self) -> None:
        return None


class _Svc:
    def __init__(self) -> None:
        self.mirrored: list[tuple[uuid.UUID, datetime]] = []
        self.brief: SimpleNamespace | None = None

    async def mirror_binding(self, project_id: uuid.UUID, document_id: uuid.UUID) -> bool:
        self.mirrored.append((document_id, self.brief.submitted_at))
        return True


def _patch(monkeypatch, *, status: str = "binding", gate: uuid.UUID | None = GATE, outcomes=("go_with_conditions",)):
    async def documents(_s, _pid):
        return (SimpleNamespace(id=DOC, status=status, approved_gate_id=gate),)

    async def decisions(_s, _pid, _gate):
        return tuple(SimpleNamespace(outcome=o, decided_at=DECIDED + timedelta(days=i)) for i, o in enumerate(outcomes))

    monkeypatch.setattr(governance, "project_documents", documents)
    monkeypatch.setattr(governance, "project_gate_decisions", decisions)


@pytest.mark.asyncio
async def test_a_brief_carried_by_a_document_a_go_made_binding_is_bound_as_submitted_before_it(monkeypatch) -> None:
    _patch(monkeypatch)
    svc, brief = _Svc(), SimpleNamespace(governance_document_id=DOC, submitted_at=DECIDED + timedelta(hours=3))
    svc.brief = brief
    assert await seed._bound_by_decided_gate(_Session(), svc, uuid.uuid4(), brief) is True
    assert svc.mirrored == [(DOC, DECIDED - timedelta(days=1))]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "gate", "outcomes"),
    [("in_review", GATE, ("go",)), ("binding", None, ("go",)), ("binding", GATE, ("no_go",))],
)
async def test_without_a_go_that_made_the_document_binding_the_brief_stays_in_review(
    monkeypatch, status, gate, outcomes
) -> None:
    _patch(monkeypatch, status=status, gate=gate, outcomes=outcomes)
    svc, brief = _Svc(), SimpleNamespace(governance_document_id=DOC, submitted_at=DECIDED)
    svc.brief = brief
    assert await seed._bound_by_decided_gate(_Session(), svc, uuid.uuid4(), brief) is False
    assert svc.mirrored == [] and brief.submitted_at == DECIDED
