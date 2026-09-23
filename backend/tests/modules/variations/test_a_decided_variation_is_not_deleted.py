# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A decided variation is kept: the edit guards now hold against delete as well.

``update_order`` refuses a completed or voided variation order because its money
has already moved: completing a VO bumps the contract sum and the final account
counts its ``final_cost_impact``. ``update_request`` refuses an approved,
rejected or converted variation request because it is the frozen commercial
record of that decision. Neither delete looked at the status, so the same rows
could be removed outright, which rewrites more than any edit: the final account
drops the completed VO on its next recompute while the contract sum it bumped
stays bumped, and the VO converted from a deleted request loses the link to the
decision it came from.

Each refusal is paired with the edit guard that already held (the control) and
with the same delete on a record that is still open, which must keep working.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.variations.schemas import VariationOrderUpdate, VariationRequestUpdate
from tests.modules.variations.test_variations_fsm_money import _make_service


def _seed_vo(svc: object, status: str) -> SimpleNamespace:
    vo = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        code="VO-0001",
        status=status,
        final_cost_impact=Decimal("5000.00"),
        currency="EUR",
        ball_in_court=None,
    )
    svc.vo_repo.rows[vo.id] = vo  # type: ignore[attr-defined]
    return vo


def _seed_vr(svc: object, status: str) -> SimpleNamespace:
    vr = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        code="VR-0001",
        status=status,
        estimated_cost_impact=Decimal("5000.00"),
        ball_in_court=None,
    )
    svc.vr_repo.rows[vr.id] = vr  # type: ignore[attr-defined]
    return vr


# ── Variation orders ────────────────────────────────────────────────────────


async def test_control_a_completed_vo_cannot_be_edited() -> None:
    svc = _make_service()
    vo = _seed_vo(svc, "completed")
    with pytest.raises(HTTPException) as exc:
        await svc.update_order(vo.id, VariationOrderUpdate(final_cost_impact=Decimal("1")))
    assert exc.value.status_code == 409
    assert vo.final_cost_impact == Decimal("5000.00")


@pytest.mark.parametrize("vo_status", ["completed", "voided"])
async def test_a_closed_vo_cannot_be_deleted(vo_status: str) -> None:
    svc = _make_service()
    vo = _seed_vo(svc, vo_status)
    with pytest.raises(HTTPException) as exc:
        await svc.delete_order(vo.id)
    assert exc.value.status_code == 409
    assert vo.id in svc.vo_repo.rows


@pytest.mark.parametrize("vo_status", ["issued", "in_progress"])
async def test_an_open_vo_can_still_be_deleted(vo_status: str) -> None:
    svc = _make_service()
    vo = _seed_vo(svc, vo_status)
    await svc.delete_order(vo.id)
    assert vo.id not in svc.vo_repo.rows


# ── Variation requests ──────────────────────────────────────────────────────


async def test_control_an_approved_request_cannot_be_edited() -> None:
    svc = _make_service()
    vr = _seed_vr(svc, "approved")
    with pytest.raises(HTTPException) as exc:
        await svc.update_request(vr.id, VariationRequestUpdate(estimated_cost_impact=Decimal("1")))
    assert exc.value.status_code == 409


@pytest.mark.parametrize("vr_status", ["approved", "rejected", "converted_to_vo"])
async def test_a_decided_request_cannot_be_deleted(vr_status: str) -> None:
    svc = _make_service()
    vr = _seed_vr(svc, vr_status)
    with pytest.raises(HTTPException) as exc:
        await svc.delete_request(vr.id)
    assert exc.value.status_code == 409
    assert vr.id in svc.vr_repo.rows


@pytest.mark.parametrize("vr_status", ["draft", "submitted", "under_review"])
async def test_an_undecided_request_can_still_be_deleted(vr_status: str) -> None:
    svc = _make_service()
    vr = _seed_vr(svc, vr_status)
    await svc.delete_request(vr.id)
    assert vr.id not in svc.vr_repo.rows


async def test_deleting_an_unknown_variation_order_is_still_a_404() -> None:
    svc = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc.delete_order(uuid.uuid4())
    assert exc.value.status_code == 404
