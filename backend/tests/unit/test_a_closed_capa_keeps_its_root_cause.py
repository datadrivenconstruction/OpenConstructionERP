"""HSE: the root-cause category of a closed CAPA is part of its closure record.

``set_capa_five_whys`` refuses to rewrite the 5-Whys chain, and with it the
root-cause category, of a completed or cancelled CAPA. ``update_capa`` froze
the status and the verification notes of such a CAPA but still wrote a new
``root_cause_category``, so the same closure record could be changed through
the PATCH. It now refuses a real change the same way; echoing the stored value
back still saves the other fields.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from app.modules.hse_advanced.models import CorrectiveAction
from app.modules.hse_advanced.schemas import CAPAUpdate
from app.modules.hse_advanced.service import HSEAdvancedService
from tests.unit.test_hse_advanced import _make_service  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


async def _capa(svc: HSEAdvancedService, status: str, root_cause: str | None = "method") -> CorrectiveAction:
    capa = CorrectiveAction(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        source_type="audit",
        title="Replace damaged edge protection",
        target_date=date.today(),
        status=status,
        verification_notes="Edge protection replaced.",
        root_cause_category=root_cause,
    )
    return await svc.capa_repo.create(capa)


@pytest.mark.parametrize("current", ["completed", "cancelled"])
@pytest.mark.parametrize("new_value", ["material", None])
async def test_a_closed_capa_does_not_take_a_new_root_cause(current: str, new_value: str | None) -> None:
    svc = _make_service()
    capa = await _capa(svc, current)

    with pytest.raises(HTTPException) as exc:
        await svc.update_capa(capa.id, CAPAUpdate(root_cause_category=new_value))

    assert exc.value.status_code == 409
    assert "closure record" in str(exc.value.detail)
    assert capa.root_cause_category == "method"


async def test_echoing_the_stored_root_cause_still_saves_the_rest() -> None:
    svc = _make_service()
    capa = await _capa(svc, "completed")
    blank = await _capa(svc, "cancelled", root_cause=None)

    echoed = await svc.update_capa(capa.id, CAPAUpdate(root_cause_category="method", title="Edge protection, L3"))
    blank_echoed = await svc.update_capa(blank.id, CAPAUpdate(root_cause_category=None, title="Edge protection, L4"))

    assert (echoed.root_cause_category, echoed.title) == ("method", "Edge protection, L3")
    assert (blank_echoed.root_cause_category, blank_echoed.title) == (None, "Edge protection, L4")


@pytest.mark.parametrize("current", ["open", "in_progress", "overdue"])
async def test_an_open_capa_can_still_change_its_root_cause(current: str) -> None:
    svc = _make_service()
    capa = await _capa(svc, current)

    updated = await svc.update_capa(capa.id, CAPAUpdate(root_cause_category="material"))

    assert updated.root_cause_category == "material"
