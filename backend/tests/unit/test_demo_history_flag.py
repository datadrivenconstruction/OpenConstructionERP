# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo-history flag lifts the permits and design binding guards only while a seed runs."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.demo_history import RECORDING_DEMO_HISTORY, recording_demo_history
from app.modules.design_management.service import DesignService
from app.modules.permits.errors import PermitError
from app.modules.permits.service import PermitService


def _permit_service(monkeypatch) -> tuple[PermitService, SimpleNamespace]:
    svc = PermitService.__new__(PermitService)
    roadmap = SimpleNamespace(status="agreed", governance_document_id=uuid.uuid4(), project_id=uuid.uuid4())

    async def mirror(self, r):
        return None

    monkeypatch.setattr(PermitService, "_mirror_binding", mirror)
    return svc, roadmap


@pytest.mark.asyncio
async def test_permits_guard_refuses_outside_and_after_a_seed(monkeypatch) -> None:
    svc, roadmap = _permit_service(monkeypatch)
    with pytest.raises(PermitError):
        await svc._structural_guard(roadmap, None)
    with recording_demo_history():
        assert RECORDING_DEMO_HISTORY.get() is True
        assert await svc._structural_guard(roadmap, None) is None
    assert RECORDING_DEMO_HISTORY.get() is False
    with pytest.raises(PermitError):
        await svc._structural_guard(roadmap, None)


@pytest.mark.asyncio
async def test_flag_is_reset_when_the_seed_raises() -> None:
    with pytest.raises(RuntimeError), recording_demo_history():
        raise RuntimeError("seed failed")
    assert RECORDING_DEMO_HISTORY.get() is False


@pytest.mark.asyncio
async def test_design_guard_refuses_outside_and_after_a_seed(monkeypatch) -> None:
    svc = DesignService.__new__(DesignService)

    class _Refused(Exception):
        pass

    async def refuse(self, project_id):
        return _Refused("binding_requires_change_request")

    monkeypatch.setattr(DesignService, "binding_refusal", refuse)
    pid = uuid.uuid4()
    with pytest.raises(_Refused):
        await svc.assert_not_binding(pid)
    with recording_demo_history():
        await svc.assert_not_binding(pid)
    with pytest.raises(_Refused):
        await svc.assert_not_binding(pid)
