"""A variation record's status moves through its actions, never through an edit.

A notice of change has acknowledge, respond and close actions and a lifecycle
that leaves ``closed`` with no way out. The PATCH on the same notice wrote any
status it was given, so a closed notice was reopened by sending
``{"status": "issued"}``. Requests, daywork sheets, disruption and extension
of time claims had the same hole: an edit could approve a request, sign a
sheet or grant a claim without the action that records the decision. An edit
may still send a record back to draft where the lifecycle allows it, because
no action exists for that move.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.modules.variations.schemas import (
    DayworkSheetCreate,
    DayworkSheetUpdate,
    DisruptionClaimCreate,
    DisruptionClaimUpdate,
    ExtensionOfTimeClaimCreate,
    ExtensionOfTimeClaimUpdate,
    NoticeCreate,
    NoticeUpdate,
    VariationRequestCreate,
    VariationRequestUpdate,
)
from tests.modules.variations.test_variations_idor import _make_service

PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-00000000c105")


async def _notice(svc: Any) -> Any:
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        notice = await svc.create_notice(NoticeCreate(project_id=PROJECT_ID, title="Rock in trench"))
        return await svc.transition_notice(notice.id, "closed", user_id="u1")


@pytest.mark.asyncio
async def test_a_closed_notice_is_not_reopened_by_an_edit() -> None:
    svc = _make_service()
    notice = await _notice(svc)
    assert notice.status == "closed"
    with pytest.raises(HTTPException) as exc:
        await svc.update_notice(notice.id, NoticeUpdate(status="issued"))
    assert exc.value.status_code == 422
    assert (await svc.get_notice(notice.id)).status == "closed"


@pytest.mark.asyncio
async def test_an_edit_that_repeats_the_status_still_saves_the_other_fields() -> None:
    svc = _make_service()
    notice = await _notice(svc)
    out = await svc.update_notice(notice.id, NoticeUpdate(status="closed", recipient_name="Owner rep"))
    assert out.status == "closed"
    assert out.recipient_name == "Owner rep"


@pytest.mark.asyncio
async def test_an_edit_does_not_approve_a_variation_request() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=PROJECT_ID, title="Extra footing", estimated_cost_impact=Decimal("4200"), currency="EUR"
            )
        )
    with pytest.raises(HTTPException) as exc:
        await svc.update_request(vr.id, VariationRequestUpdate(status="approved"))
    assert exc.value.status_code == 422
    assert (await svc.get_request(vr.id)).status == "draft"


@pytest.mark.asyncio
async def test_an_edit_does_not_sign_a_daywork_sheet_but_may_return_a_dispute_to_draft() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        ds = await svc.create_daywork_sheet(DayworkSheetCreate(project_id=PROJECT_ID, currency="EUR"))
    with pytest.raises(HTTPException) as exc:
        await svc.update_daywork_sheet(ds.id, DayworkSheetUpdate(status="billed"))
    assert exc.value.status_code == 422
    ds.status = "disputed"
    out = await svc.update_daywork_sheet(ds.id, DayworkSheetUpdate(status="draft"))
    assert out.status == "draft"


@pytest.mark.asyncio
async def test_an_edit_does_not_decide_a_disruption_or_extension_of_time_claim() -> None:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        dc = await svc.submit_disruption_claim(
            DisruptionClaimCreate(project_id=PROJECT_ID, cost_amount=Decimal("9000"), currency="EUR")
        )
        eot = await svc.submit_eot_claim(ExtensionOfTimeClaimCreate(project_id=PROJECT_ID, requested_days=14))
    with pytest.raises(HTTPException):
        await svc.update_disruption_claim(dc.id, DisruptionClaimUpdate(status="agreed"))
    with pytest.raises(HTTPException):
        await svc.update_eot_claim(eot.id, ExtensionOfTimeClaimUpdate(status="granted"))
    eot.status = "rejected"
    out = await svc.update_eot_claim(eot.id, ExtensionOfTimeClaimUpdate(status="draft"))
    assert out.status == "draft"
