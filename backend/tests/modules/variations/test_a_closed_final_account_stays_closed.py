# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A closed final account keeps the value it was closed at.

Closing a final account is a MANAGER action that records the signer and moves
the account to ``closed``, a status the lifecycle leaves no way out of. The
PATCH on the same account had no status check at all: an EDITOR could rewrite
the original contract value or the retention of a closed account, and could
set its status to anything, back to draft included. Every PATCH then ran the
recompute, which rewrote the variation, daywork and claim totals and the final
value from whatever had changed on the project since the close.

The numbers come from ``test_recompute_final_account_aggregates_vos_and_daywork``:
1,000,000 original, 35,000 of variation orders, 3,000 of signed daywork and
2,000 of agreed claims, less 50,000 retention held, closes at 990,000.
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
    DisruptionClaimCreate,
    FinalAccountCreate,
    FinalAccountUpdate,
    VariationOrderCreate,
)
from tests.unit.test_variations import _make_service

PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-00000000fa01")
CLOSED_AT = Decimal("990000")


async def _vo(svc: Any, amount: str) -> None:
    await svc.create_order(
        VariationOrderCreate(
            project_id=PROJECT_ID, title=f"VO {amount}", final_cost_impact=Decimal(amount), currency="EUR"
        )
    )


async def _project_with_an_account(status: str) -> tuple[Any, Any]:
    svc = _make_service()
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        fa = await svc.create_final_account(
            FinalAccountCreate(
                project_id=PROJECT_ID,
                original_contract_value=Decimal("1000000"),
                currency="EUR",
                retention_held=Decimal("50000"),
                retention_released=Decimal("0"),
            ),
        )
        await _vo(svc, "20000")
        await _vo(svc, "15000")
        sheet = await svc.create_daywork_sheet(DayworkSheetCreate(project_id=PROJECT_ID, currency="EUR"), user_id="u1")
        sheet.status = "signed"
        sheet.total_amount = Decimal("3000")
        claim = await svc.submit_disruption_claim(
            DisruptionClaimCreate(
                project_id=PROJECT_ID, description="x", cost_amount=Decimal("2000"), currency="EUR", status="agreed"
            ),
        )
        claim.decided_amount = Decimal("2000")
        await svc.recompute_final_account(PROJECT_ID)
        if status == "closed":
            fa.status = "agreed"
            await svc.close_final_account(fa.id, signer_id="manager-1")
        else:
            fa.status = status
    return svc, fa


# ── The guard that already held ─────────────────────────────────────────────


async def test_control_a_closed_account_cannot_be_closed_again() -> None:
    svc, fa = await _project_with_an_account("closed")
    assert fa.final_value == CLOSED_AT
    with pytest.raises(HTTPException) as exc:
        await svc.close_final_account(fa.id, signer_id="manager-2")
    assert exc.value.status_code == 409


# ── A closed account ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "change",
    [
        {"retention_held": Decimal("0")},
        {"original_contract_value": Decimal("1200000")},
        {"status": "draft"},
        {"status": "disputed"},
    ],
)
async def test_a_closed_account_is_not_patched(change: dict[str, Any]) -> None:
    svc, fa = await _project_with_an_account("closed")
    with pytest.raises(HTTPException) as exc:
        await svc.update_final_account(fa.id, FinalAccountUpdate(**change))
    assert exc.value.status_code == 409
    assert fa.status == "closed"
    assert fa.final_value == CLOSED_AT
    assert fa.retention_held == Decimal("50000")


async def test_a_variation_completed_after_the_close_does_not_move_the_closed_value() -> None:
    svc, fa = await _project_with_an_account("closed")
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        await _vo(svc, "10000")
    again = await svc.recompute_final_account(PROJECT_ID)
    assert again is not None
    assert again.final_value == CLOSED_AT
    assert again.variations_total == Decimal("35000")


# ── Status through PATCH on an open account ─────────────────────────────────


async def test_closing_is_not_reachable_through_patch() -> None:
    """``close_final_account`` is MANAGER-only and records the signer; a PATCH would skip both."""
    svc, fa = await _project_with_an_account("agreed")
    with pytest.raises(HTTPException) as exc:
        await svc.update_final_account(fa.id, FinalAccountUpdate(status="closed"))
    assert exc.value.status_code == 409
    assert fa.status == "agreed"


async def test_a_patch_status_outside_the_lifecycle_is_refused() -> None:
    svc, fa = await _project_with_an_account("agreed")
    with pytest.raises(HTTPException) as exc:
        await svc.update_final_account(fa.id, FinalAccountUpdate(status="draft"))
    assert exc.value.status_code == 409
    assert fa.status == "agreed"


@pytest.mark.parametrize(("current", "target"), [("draft", "agreed"), ("agreed", "disputed"), ("disputed", "draft")])
async def test_the_moves_that_have_no_verb_of_their_own_still_work(current: str, target: str) -> None:
    svc, fa = await _project_with_an_account(current)
    updated = await svc.update_final_account(fa.id, FinalAccountUpdate(status=target))
    assert updated.status == target


async def test_an_open_account_still_takes_its_figures_and_recomputes() -> None:
    svc, fa = await _project_with_an_account("draft")
    updated = await svc.update_final_account(fa.id, FinalAccountUpdate(status="draft", retention_held=Decimal("0")))
    assert updated.retention_held == Decimal("0")
    assert updated.final_value == CLOSED_AT + Decimal("50000")
