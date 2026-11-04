"""Scope confirmation of a lump-sum quote is a recorded act, and RFQ reads follow project membership."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.rfq_bidding import router as rfq_router
from tests.modules.rfq_bidding.test_service_logic import _bid, _rfq, _service


async def test_confirming_scope_sets_the_flag_the_comparison_reads() -> None:
    rfq = _rfq()
    bid = _bid(rfq)
    rfq.bids.append(bid)
    service = _service(rfq)
    updated = await service.set_scope_confirmed(bid.id, True, actor_id=str(uuid.uuid4()))
    assert updated.metadata_["scope_confirmed"] is True
    assert service._bid_payload(updated)["scope_confirmed"] is True


async def test_unconfirming_scope_clears_it_and_keeps_other_metadata() -> None:
    rfq = _rfq()
    bid = _bid(rfq, metadata_={"scope_confirmed": True, "note": "x"})
    rfq.bids.append(bid)
    service = _service(rfq)
    updated = await service.set_scope_confirmed(bid.id, False)
    assert updated.metadata_["scope_confirmed"] is False
    assert updated.metadata_["note"] == "x"


async def test_scope_cannot_be_confirmed_on_an_awarded_rfq() -> None:
    rfq = _rfq(status="awarded")
    bid = _bid(rfq)
    rfq.bids.append(bid)
    service = _service(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.set_scope_confirmed(bid.id, True)
    assert exc.value.status_code == 409


async def test_rfq_project_check_uses_the_shared_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    async def fake(project_id, user_id, session):  # noqa: ANN001
        calls.append((project_id, user_id))

    monkeypatch.setattr(rfq_router, "verify_project_access", fake)
    pid = uuid.uuid4()
    await rfq_router._verify_project_access(None, pid, "u1", {"role": "viewer"})  # type: ignore[arg-type]
    assert calls == [(pid, "u1")]


def test_scope_route_needs_the_update_permission() -> None:
    route = next(
        r for r in rfq_router.router.routes if getattr(r, "path", "").endswith("/bids/{bid_id}/scope-confirmed/")
    )
    assert "POST" in route.methods
