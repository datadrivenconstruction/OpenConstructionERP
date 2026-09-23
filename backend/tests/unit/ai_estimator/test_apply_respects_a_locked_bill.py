# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Applying an AI estimate to an existing bill respects that bill's lock.

The BOQ service refuses every position write on a locked bill
(``_ensure_not_locked`` and ``_ensure_boq_writable`` both read ``is_locked``)
and tells the user to create a revision. ``apply`` with a ``target_boq_id``
loaded the bill, checked only that it belonged to the run's project, and then
wrote one priced position per confirmed group into it, so a locked bill could
gain lines and value through the AI estimator that it refuses everywhere else.

The run is stubbed to the point just past the checkpoint and preview gates.
Reaching ``_count_positions`` is the first step of the write, so the tests
observe whether the apply stopped before it.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.ai_estimator import schemas
from app.modules.ai_estimator.service import AiEstimatorService


class _ReachedTheWrite(Exception):
    """Raised by the stub for the first step that writes into the bill."""


class _Session:
    def __init__(self, boq: Any) -> None:
        self.boq = boq
        self.added: list[Any] = []

    async def get(self, _model: Any, ident: Any) -> Any:
        return self.boq if self.boq is not None and ident == self.boq.id else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def _service_and_run(*, is_locked: bool) -> tuple[AiEstimatorService, Any, Any]:
    project_id = uuid.uuid4()
    boq = SimpleNamespace(id=uuid.uuid4(), project_id=project_id, is_locked=is_locked)
    run = SimpleNamespace(id=uuid.uuid4(), project_id=project_id, checkpoints={"assembly": {"accepted": True}})

    service = AiEstimatorService.__new__(AiEstimatorService)
    service.session = _Session(boq)  # type: ignore[assignment]

    async def _preview(_run: Any) -> Any:
        return SimpleNamespace(can_apply=True)

    async def _currency(_run: Any) -> tuple[str, dict[str, Any]]:
        return "EUR", {}

    async def _count(_boq_id: Any) -> int:
        raise _ReachedTheWrite

    service.build_preview = _preview  # type: ignore[method-assign]
    service._project_currency_context = _currency  # type: ignore[method-assign]
    service._count_positions = _count  # type: ignore[method-assign]
    return service, run, boq


async def test_an_estimate_is_not_applied_to_a_locked_bill() -> None:
    service, run, boq = _service_and_run(is_locked=True)
    with pytest.raises(HTTPException) as exc:
        await service.apply(run, schemas.ApplyRequest(target_boq_id=boq.id), uuid.uuid4())
    assert exc.value.status_code == 409
    assert service.session.added == []  # type: ignore[attr-defined]


async def test_an_estimate_still_goes_into_an_open_bill() -> None:
    service, run, boq = _service_and_run(is_locked=False)
    with pytest.raises(_ReachedTheWrite):
        await service.apply(run, schemas.ApplyRequest(target_boq_id=boq.id), uuid.uuid4())


async def test_a_bill_in_another_project_is_still_not_found() -> None:
    service, run, _boq = _service_and_run(is_locked=False)
    with pytest.raises(HTTPException) as exc:
        await service.apply(run, schemas.ApplyRequest(target_boq_id=uuid.uuid4()), uuid.uuid4())
    assert exc.value.status_code == 404
