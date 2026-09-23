# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An RFQ that has gone out keeps what vendors priced, and a decided one keeps its record.

The service already refuses two things. ``_require_editable_scope`` stops the
scope lines changing once vendors have been asked to price them, and
``_bid_for_open_rfq`` stops a quote's standing changing once the RFQ is
decided. Three writers went around both:

* ``update_rfq`` wrote any status it was sent, so a PATCH to ``draft`` reopened
  the scope of an awarded RFQ and a PATCH to ``published`` reopened bidding on
  one, and it rewrote the scope text, the currency and the evaluation basis of
  an RFQ whose quotes were already in;
* ``delete_rfq`` removed an awarded RFQ, and with it every quote and the award
  record (all of them cascade), although the screen only offers delete on a
  draft;
* ``evaluate_bid`` rescored a quote on an awarded RFQ, which moves the ranking
  the award was made on.

Each refusal sits next to the same call in the state where it must still work.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.modules.rfq_bidding.schemas import BidEvaluation, RFQLineCreate, RFQUpdate
from app.modules.rfq_bidding.service import RFQService
from tests.modules.rfq_bidding.test_service_logic import _bid, _FakeRFQRepo, _rfq, _service


class _DeletableRFQRepo(_FakeRFQRepo):
    """The one-RFQ repository, able to forget its RFQ the way a delete would."""

    def __init__(self, rfq: Any) -> None:
        super().__init__(rfq)
        self.deleted = False

    async def get(self, rfq_id: UUID) -> Any:
        if self.deleted:
            return None
        return await super().get(rfq_id)

    async def delete(self, rfq_id: UUID) -> None:
        if str(self.rfq.id) == str(rfq_id):
            self.deleted = True


def _wired(rfq: Any) -> tuple[RFQService, _DeletableRFQRepo]:
    service = _service(rfq)
    repo = _DeletableRFQRepo(rfq)
    service.rfqs = repo  # type: ignore[assignment]
    return service, repo


# ── The guards that already worked ──────────────────────────────────────────


async def test_control_scope_lines_are_refused_once_the_rfq_is_out() -> None:
    rfq = _rfq(status="published")
    service, _repo = _wired(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.add_line(rfq.id, RFQLineCreate(description="Ductwork", unit="m2", quantity="10"))
    assert exc.value.status_code == 409


async def test_control_a_quote_on_an_awarded_rfq_cannot_be_withdrawn() -> None:
    rfq = _rfq(status="awarded")
    bid = _bid(rfq)
    rfq.bids.append(bid)
    service, _repo = _wired(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.withdraw_bid(bid.id, reason="Too late to matter")
    assert exc.value.status_code == 409


# ── Delete ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rfq_status", ["published", "bids_received", "awarded", "po_issued", "cancelled"])
async def test_an_rfq_that_went_out_is_not_deleted(rfq_status: str) -> None:
    rfq = _rfq(status=rfq_status)
    rfq.bids.append(_bid(rfq, is_awarded=rfq_status in ("awarded", "po_issued")))
    service, repo = _wired(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.delete_rfq(rfq.id)
    assert exc.value.status_code == 409
    assert repo.deleted is False


async def test_a_draft_rfq_can_still_be_deleted() -> None:
    rfq = _rfq(status="draft")
    service, repo = _wired(rfq)
    await service.delete_rfq(rfq.id)
    assert repo.deleted is True


# ── Status through PATCH ────────────────────────────────────────────────────


async def test_an_awarded_rfq_cannot_be_patched_back_to_draft() -> None:
    rfq = _rfq(status="awarded")
    service, _repo = _wired(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.update_rfq(rfq.id, RFQUpdate(status="draft"))
    assert exc.value.status_code == 409
    assert rfq.status == "awarded"


async def test_an_awarded_rfq_cannot_be_patched_back_open_for_bids() -> None:
    rfq = _rfq(status="awarded")
    service, _repo = _wired(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.update_rfq(rfq.id, RFQUpdate(status="published"))
    assert exc.value.status_code == 409
    assert rfq.status == "awarded"


async def test_award_is_not_reachable_through_patch() -> None:
    """``award_bid`` checks the role, the comparison and writes the award record."""
    rfq = _rfq(status="bids_received")
    service, _repo = _wired(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.update_rfq(rfq.id, RFQUpdate(status="awarded"))
    assert exc.value.status_code == 409
    assert rfq.status == "bids_received"


async def test_publishing_is_not_reachable_through_patch() -> None:
    """``issue_rfq`` runs the issue rule set; a PATCH would skip it."""
    rfq = _rfq(status="draft")
    service, _repo = _wired(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.update_rfq(rfq.id, RFQUpdate(status="published"))
    assert exc.value.status_code == 409
    assert rfq.status == "draft"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("published", "bids_received"),
        ("bids_received", "cancelled"),
        ("awarded", "po_issued"),
        ("po_issued", "completed"),
        ("draft", "cancelled"),
        ("cancelled", "draft"),
    ],
)
async def test_the_lifecycle_moves_that_have_no_verb_of_their_own_still_work(current: str, target: str) -> None:
    rfq = _rfq(status=current)
    service, _repo = _wired(rfq)
    updated = await service.update_rfq(rfq.id, RFQUpdate(status=target))
    assert updated.status == target


async def test_sending_the_current_status_again_is_not_a_transition() -> None:
    rfq = _rfq(status="awarded")
    service, _repo = _wired(rfq)
    updated = await service.update_rfq(rfq.id, RFQUpdate(status="awarded", title="Mechanical fit-out, rev B"))
    assert updated.title == "Mechanical fit-out, rev B"


# ── What vendors priced, and how their quotes are judged ────────────────────


@pytest.mark.parametrize(
    "change",
    [
        {"scope_of_work": "Ductwork only"},
        {"currency_code": "USD"},
        {"evaluation_method": "best_value"},
        {"technical_weight": Decimal("40")},
        {"require_full_scope": False},
    ],
)
async def test_the_basis_of_an_rfq_that_went_out_is_frozen(change: dict[str, Any]) -> None:
    rfq = _rfq(status="bids_received")
    before = {name: getattr(rfq, name) for name in change}
    service, _repo = _wired(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.update_rfq(rfq.id, RFQUpdate(**change))
    assert exc.value.status_code == 409
    assert {name: getattr(rfq, name) for name in change} == before


async def test_the_basis_of_a_draft_can_still_be_edited() -> None:
    rfq = _rfq(status="draft")
    service, _repo = _wired(rfq)
    updated = await service.update_rfq(
        rfq.id,
        RFQUpdate(scope_of_work="Ductwork only", technical_weight=Decimal("40"), evaluation_method="best_value"),
    )
    assert updated.scope_of_work == "Ductwork only"
    assert updated.technical_weight == Decimal("40")


async def test_resending_an_unchanged_basis_on_a_sent_rfq_is_allowed() -> None:
    """A client that PATCHes the whole form back must not be refused for a no-op."""
    rfq = _rfq(status="published")
    service, _repo = _wired(rfq)
    updated = await service.update_rfq(
        rfq.id,
        RFQUpdate(
            title="Mechanical fit-out, rev B",
            scope_of_work=rfq.scope_of_work,
            currency_code=rfq.currency_code,
            technical_weight=rfq.technical_weight,
        ),
    )
    assert updated.title == "Mechanical fit-out, rev B"


async def test_the_deadline_and_the_title_of_a_sent_rfq_can_still_change() -> None:
    rfq = _rfq(status="published")
    service, _repo = _wired(rfq)
    updated = await service.update_rfq(rfq.id, RFQUpdate(title="Extended", submission_deadline="2099-01-31"))
    assert updated.title == "Extended"
    assert updated.submission_deadline == "2099-01-31"


# ── Scoring a quote ─────────────────────────────────────────────────────────


async def test_a_quote_on_an_awarded_rfq_cannot_be_rescored() -> None:
    rfq = _rfq(status="awarded")
    bid = _bid(rfq, technical_score="60")
    rfq.bids.append(bid)
    service, _repo = _wired(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.evaluate_bid(bid.id, BidEvaluation(technical_score="95"))
    assert exc.value.status_code == 409
    assert bid.technical_score == "60"


async def test_a_quote_on_an_open_rfq_can_be_scored() -> None:
    rfq = _rfq(status="bids_received")
    bid = _bid(rfq)
    rfq.bids.append(bid)
    service, _repo = _wired(rfq)
    updated = await service.evaluate_bid(bid.id, BidEvaluation(technical_score="80", commercial_score="70"))
    assert updated.technical_score == "80"
