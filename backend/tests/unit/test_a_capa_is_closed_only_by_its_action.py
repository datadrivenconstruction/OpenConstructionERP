"""HSE: a CAPA is completed, cancelled or escalated only through its action.

``update_capa`` wrote every field it was given. ``CAPAUpdate.status`` accepts
``completed``, ``cancelled`` and ``overdue``, so an editor could close a CAPA
with no completion time and no verification notes, past the close permission
and the state machine that ``close_capa`` checks. The same PATCH could reopen a
completed, effectiveness-verified CAPA or rewrite the verification notes that
carry its closure evidence.

Each group pairs the guard that was already there with the refusal and with
the edits that must stay possible.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.hse_advanced.models import CorrectiveAction
from app.modules.hse_advanced.schemas import CAPAUpdate
from app.modules.hse_advanced.service import HSEAdvancedService
from tests.unit.test_hse_advanced import _make_service  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


async def _capa(svc: HSEAdvancedService, status: str, notes: str = "") -> CorrectiveAction:
    capa = CorrectiveAction(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        source_type="audit",
        title="Replace damaged edge protection",
        target_date=date.today(),
        status=status,
        verification_notes=notes,
    )
    return await svc.capa_repo.create(capa)


async def _refused(call: Any) -> str:
    with pytest.raises(HTTPException) as exc:
        await call
    assert exc.value.status_code == 409
    return str(exc.value.detail)


async def test_control_closing_a_completed_capa_again_is_still_refused() -> None:
    svc = _make_service()
    capa = await _capa(svc, "completed")

    await _refused(svc.close_capa(capa.id))


@pytest.mark.parametrize(
    ("current", "target", "action"),
    [
        ("open", "completed", "complete"),
        ("in_progress", "completed", "complete"),
        ("open", "cancelled", "cancel"),
        ("in_progress", "overdue", "escalate"),
    ],
)
async def test_a_patch_cannot_do_the_work_of_an_action(current: str, target: str, action: str) -> None:
    svc = _make_service()
    capa = await _capa(svc, current)

    detail = await _refused(svc.update_capa(capa.id, CAPAUpdate(status=target)))

    assert f"{action} action" in detail
    assert capa.status == current
    assert capa.completed_at is None


@pytest.mark.parametrize(
    ("current", "target", "remedy"),
    [
        ("completed", "in_progress", "effectiveness check"),
        ("completed", "open", "effectiveness check"),
        ("cancelled", "open", "new CAPA"),
    ],
)
async def test_a_closed_capa_is_not_reopened_by_an_edit(current: str, target: str, remedy: str) -> None:
    svc = _make_service()
    capa = await _capa(svc, current)

    detail = await _refused(svc.update_capa(capa.id, CAPAUpdate(status=target)))

    assert remedy in detail
    assert capa.status == current


async def test_a_move_outside_the_state_machine_is_refused() -> None:
    svc = _make_service()
    capa = await _capa(svc, "in_progress")

    await _refused(svc.update_capa(capa.id, CAPAUpdate(status="open")))

    assert capa.status == "in_progress"


async def test_the_closure_notes_of_a_completed_capa_are_not_rewritten() -> None:
    svc = _make_service()
    capa = await _capa(svc, "completed", notes="Edge protection replaced on L3 and L4.")

    await _refused(svc.update_capa(capa.id, CAPAUpdate(verification_notes="Nothing was done.")))

    assert capa.verification_notes == "Edge protection replaced on L3 and L4."


async def test_the_edits_a_capa_keeps() -> None:
    svc = _make_service()
    started = await _capa(svc, "open")
    overdue = await _capa(svc, "overdue")
    completed = await _capa(svc, "completed", notes="Edge protection replaced.")

    moved = await svc.update_capa(started.id, CAPAUpdate(status="in_progress", verification_notes="Ordered."))
    resumed = await svc.update_capa(overdue.id, CAPAUpdate(status="in_progress"))
    echoed = await svc.update_capa(
        completed.id,
        CAPAUpdate(status="completed", verification_notes="Edge protection replaced.", title="Edge protection, L3-L4"),
    )

    assert (moved.status, moved.verification_notes) == ("in_progress", "Ordered.")
    assert resumed.status == "in_progress"
    assert (echoed.status, echoed.title) == ("completed", "Edge protection, L3-L4")
