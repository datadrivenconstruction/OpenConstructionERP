# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service rules exercised against in-memory repositories.

The ORM objects here are real and detached: no session, no database, no HTTP
app. That is enough to cover the decisions this layer owns - what a late quote
does, who may admit or disqualify one, and the gate that stops an award being
taken from a quote the comparison could not place beside the others - and it
covers the path from ORM row to comparison payload, which is where a column
rename would otherwise go unnoticed until it reached a user.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.modules.rfq_bidding import comparison as cmp
from app.modules.rfq_bidding.models import RFQ, RFQAward, RFQBid, RFQBidAdjustment, RFQBidLine, RFQLine
from app.modules.rfq_bidding.schemas import BidAdjustmentCreate, BidCreate, BidLineCreate, RFQLineCreate
from app.modules.rfq_bidding.service import RFQService

TODAY = date(2026, 7, 10)


# ── In-memory repositories ──────────────────────────────────────────────────


class _FakeRFQRepo:
    """Holds one RFQ, the way a session holds one loaded aggregate."""

    def __init__(self, rfq: RFQ) -> None:
        self.rfq = rfq

    async def get(self, rfq_id: UUID) -> RFQ | None:
        return self.rfq if str(self.rfq.id) == str(rfq_id) else None

    async def update(self, rfq_id: UUID, **fields: Any) -> None:
        if str(self.rfq.id) != str(rfq_id):
            return
        for name, value in fields.items():
            setattr(self.rfq, name, value)


class _FakeBidRepo:
    """Quotes indexed by id, kept on the RFQ the way the loader would."""

    def __init__(self, rfq: RFQ) -> None:
        self.rfq = rfq
        self.bids: dict[UUID, RFQBid] = {bid.id: bid for bid in rfq.bids}

    async def get(self, bid_id: UUID) -> RFQBid | None:
        return self.bids.get(bid_id)

    async def create(self, bid: RFQBid) -> RFQBid:
        if bid.id is None:
            bid.id = uuid4()
        self.bids[bid.id] = bid
        self.rfq.bids.append(bid)
        return bid

    async def update(self, bid_id: UUID, **fields: Any) -> None:
        bid = self.bids[bid_id]
        for name, value in fields.items():
            setattr(bid, name, value)

    async def add_adjustment(self, adjustment: RFQBidAdjustment) -> RFQBidAdjustment:
        adjustment.id = adjustment.id or uuid4()
        self.bids[adjustment.bid_id].adjustments.append(adjustment)
        return adjustment


class _FakeLineRepo:
    """Scope lines of the one RFQ under test."""

    def __init__(self, rfq: RFQ) -> None:
        self.rfq = rfq

    async def get(self, line_id: UUID) -> RFQLine | None:
        return next((line for line in self.rfq.lines if line.id == line_id), None)

    async def list_for_rfq(self, rfq_id: UUID) -> list[RFQLine]:
        return [line for line in self.rfq.lines if str(line.rfq_id) == str(rfq_id)]

    async def create(self, line: RFQLine) -> RFQLine:
        line.id = line.id or uuid4()
        self.rfq.lines.append(line)
        return line

    async def update(self, line_id: UUID, **fields: Any) -> None:
        line = await self.get(line_id)
        for name, value in fields.items():
            setattr(line, name, value)

    async def delete(self, line: RFQLine) -> None:
        self.rfq.lines.remove(line)

    async def next_line_no(self, rfq_id: UUID) -> int:
        numbers = [line.line_no for line in self.rfq.lines if str(line.rfq_id) == str(rfq_id)]
        return max(numbers, default=0) + 1


class _FakeAwardRepo:
    """The single award record this RFQ may end up with."""

    def __init__(self) -> None:
        self.award: RFQAward | None = None

    async def get_for_rfq(self, rfq_id: UUID) -> RFQAward | None:
        del rfq_id
        return self.award

    async def create(self, award: RFQAward) -> RFQAward:
        award.id = award.id or uuid4()
        self.award = award
        return award


# ── Fixtures ────────────────────────────────────────────────────────────────


def _rfq(**overrides: Any) -> RFQ:
    """A published RFQ with no scope lines and no quotes yet.

    The deadline is relative to now on purpose. It used to be the literal
    ``2026-08-15``, which read as "still open" while it was written and turned
    into a closed RFQ on 16 August: the service refuses a quote past the
    deadline before it ever looks at the quote, so every test here that expected
    a different refusal started reporting 409 instead. A default that means
    "open" has to be stated as a distance from today.
    """
    values: dict[str, Any] = {
        "id": uuid4(),
        "project_id": uuid4(),
        "rfq_number": "RFQ-014",
        "title": "Mechanical fit-out",
        "description": "Supply and install to levels 1-4",
        "scope_of_work": "Ductwork, AHU, commissioning",
        # Future-relative: a hardcoded date here rotted past and made every
        # default-fixture submission read as late once the calendar caught up.
        "submission_deadline": (datetime.now(UTC) + timedelta(days=14)).date().isoformat(),
        "currency_code": "EUR",
        "status": "published",
        "issued_to_contacts": ["alpha", "beta", "gamma"],
        "evaluation_method": "lowest_price",
        "technical_weight": Decimal("0"),
        "require_full_scope": True,
        "metadata_": {},
    }
    values.update(overrides)
    return RFQ(**values)


def _bid(rfq: RFQ, **overrides: Any) -> RFQBid:
    """One quote against ``rfq``, defaulted to a clean on-time submission."""
    values: dict[str, Any] = {
        "id": uuid4(),
        "rfq_id": rfq.id,
        "bidder_contact_id": "alpha",
        "bid_amount": "1000",
        "currency_code": "EUR",
        "submitted_at": "2026-07-01",
        "validity_days": 60,
        "is_awarded": False,
        "status": "received",
        "is_late": False,
        "metadata_": {},
    }
    values.update(overrides)
    return RFQBid(**values)


def _line(rfq: RFQ, **overrides: Any) -> RFQLine:
    values: dict[str, Any] = {
        "id": uuid4(),
        "rfq_id": rfq.id,
        "line_no": 1,
        "code": "A1",
        "description": "Ductwork",
        "unit": "m2",
        "quantity": Decimal("100"),
        "is_optional": False,
        "metadata_": {},
    }
    values.update(overrides)
    return RFQLine(**values)


def _service(rfq: RFQ) -> RFQService:
    """A service wired to in-memory repositories over one RFQ."""
    service = RFQService(None)  # type: ignore[arg-type]
    service.rfqs = _FakeRFQRepo(rfq)  # type: ignore[assignment]
    service.bids_repo = _FakeBidRepo(rfq)  # type: ignore[assignment]
    service.lines_repo = _FakeLineRepo(rfq)  # type: ignore[assignment]
    service.awards = _FakeAwardRepo()  # type: ignore[assignment]
    return service


# ── From ORM rows to a comparison ───────────────────────────────────────────


class TestComparisonPayload:
    def test_the_payload_carries_what_the_comparison_needs(self) -> None:
        rfq = _rfq()
        rfq.lines.append(_line(rfq))
        bid = _bid(rfq, exchange_rate=Decimal("1.15"), currency_code="GBP")
        bid.lines.append(
            RFQBidLine(
                id=uuid4(),
                bid_id=bid.id,
                rfq_line_id=rfq.lines[0].id,
                unit="m2",
                quantity=Decimal("100"),
                unit_rate=Decimal("10"),
                amount=Decimal("1000"),
                is_excluded=False,
            )
        )
        bid.adjustments.append(
            RFQBidAdjustment(
                id=uuid4(),
                bid_id=bid.id,
                kind="freight",
                amount=Decimal("200"),
                currency_code="GBP",
                included_in_bid=False,
                source="bidder",
            )
        )
        rfq.bids.append(bid)

        payload = RFQService._validation_payload(rfq, as_of=TODAY)
        assert payload["as_of"] == "2026-07-10"
        assert payload["lines"][0]["quantity"] == "100"
        assert payload["bids"][0]["exchange_rate"] == "1.15"
        assert payload["bids"][0]["lines"][0]["amount"] == "1000"
        assert payload["bids"][0]["adjustments"][0]["currency_code"] == "GBP"
        # Nothing in the payload is a float; money crosses as a string.
        assert not any(isinstance(value, float) for value in payload["bids"][0].values())

    def test_the_orm_path_produces_the_same_ranking_as_the_pure_one(self) -> None:
        rfq = _rfq()
        rfq.bids.append(_bid(rfq, bidder_contact_id="alpha", bid_amount="1200"))
        rfq.bids.append(_bid(rfq, bidder_contact_id="beta", bid_amount="900"))
        result = RFQService.compare_payload(rfq, as_of=TODAY)
        assert [quote.bidder_contact_id for quote in result.ranked] == ["beta", "alpha"]
        assert result.recommended_bid_id == str(rfq.bids[1].id)

    def test_an_rfq_with_no_scope_lines_still_compares_on_headline_amounts(self) -> None:
        """The register predates scope lines; a lump-sum package must still rank."""
        rfq = _rfq()
        rfq.bids.append(_bid(rfq, bid_amount="500"))
        result = RFQService.compare_payload(rfq, as_of=TODAY)
        assert result.lines_required == 0
        assert result.ranked[0].normalised_amount == Decimal("500")


# ── Scope lines ─────────────────────────────────────────────────────────────


class TestScopeLines:
    async def test_a_line_can_only_be_added_while_the_rfq_is_a_draft(self) -> None:
        rfq = _rfq(status="published")
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.add_line(rfq.id, RFQLineCreate(description="Ductwork", unit="m2", quantity="10"))
        assert exc.value.status_code == 409
        assert "already been asked to price" in exc.value.detail

    async def test_a_line_added_to_a_draft_takes_the_next_number(self) -> None:
        rfq = _rfq(status="draft")
        rfq.lines.append(_line(rfq, line_no=7))
        service = _service(rfq)
        created = await service.add_line(rfq.id, RFQLineCreate(description="Commissioning", unit="item", quantity="1"))
        assert created.line_no == 8
        assert created.quantity == Decimal("1")

    async def test_a_repeated_line_number_is_refused(self) -> None:
        rfq = _rfq(status="draft")
        rfq.lines.append(_line(rfq, line_no=2))
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.add_line(rfq.id, RFQLineCreate(line_no=2, description="Again", unit="m2", quantity="1"))
        assert exc.value.status_code == 409

    def test_duplicate_numbers_in_one_payload_are_refused(self) -> None:
        rfq = _rfq(status="draft")
        with pytest.raises(HTTPException) as exc:
            RFQService._reject_duplicate_line_numbers([_line(rfq, line_no=1), _line(rfq, line_no=1)])
        assert exc.value.status_code == 400

    async def test_a_line_can_be_removed_from_a_draft(self) -> None:
        rfq = _rfq(status="draft")
        line = _line(rfq)
        rfq.lines.append(line)
        service = _service(rfq)
        await service.delete_line(rfq.id, line.id)
        assert rfq.lines == []


# ── Recording a quote ───────────────────────────────────────────────────────


class TestSubmitBid:
    @staticmethod
    def _payload(rfq: RFQ, **overrides: Any) -> BidCreate:
        values: dict[str, Any] = {
            "rfq_id": rfq.id,
            "bidder_contact_id": "delta",
            "bid_amount": "950",
            "currency_code": "EUR",
        }
        values.update(overrides)
        return BidCreate(**values)

    async def test_an_on_time_quote_is_received(self) -> None:
        rfq = _rfq(submission_deadline=(datetime.now(UTC) + timedelta(days=5)).isoformat())
        service = _service(rfq)
        bid = await service.submit_bid(self._payload(rfq))
        assert bid.status == "received"
        assert bid.is_late is False

    async def test_a_late_quote_without_a_reason_is_refused(self) -> None:
        rfq = _rfq(submission_deadline="2026-01-01")
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.submit_bid(self._payload(rfq))
        assert exc.value.status_code == 409
        assert "deadline has passed" in exc.value.detail

    async def test_a_late_quote_with_a_reason_is_recorded_and_not_ranked(self) -> None:
        """Refusing the quote outright would lose the evidence, not clean the decision."""
        rfq = _rfq(submission_deadline="2026-01-01")
        service = _service(rfq)
        bid = await service.submit_bid(
            self._payload(rfq, bid_amount="10", late_reason="Arrived by email an hour after the close")
        )
        assert bid.is_late is True
        assert bid.status == "late"
        assert bid.late_reason
        result = RFQService.compare_payload(rfq, as_of=TODAY)
        assert result.ranked == ()
        assert cmp.REASON_LATE_NOT_ADMITTED in result.excluded[0].reasons

    async def test_an_unreadable_deadline_is_the_buyers_problem_not_the_suppliers(self) -> None:
        rfq = _rfq(submission_deadline="end of August")
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.submit_bid(self._payload(rfq))
        assert exc.value.status_code == 422

    async def test_a_quote_against_a_draft_rfq_is_refused(self) -> None:
        rfq = _rfq(status="draft")
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.submit_bid(self._payload(rfq))
        assert exc.value.status_code == 409

    async def test_a_line_amount_is_derived_when_it_is_not_sent(self) -> None:
        line = RFQService._build_bid_line(BidLineCreate(unit="m2", quantity="12.5", unit_rate="8.4"))
        assert line.amount == Decimal("105.00")
        assert isinstance(line.amount, Decimal)

    async def test_a_quoted_line_from_another_rfq_is_refused(self) -> None:
        rfq = _rfq()
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.submit_bid(
                self._payload(
                    rfq, lines=[{"rfq_line_id": str(uuid4()), "unit": "m2", "quantity": "1", "unit_rate": "1"}]
                )
            )
        assert exc.value.status_code == 400
        assert "do not belong to this RFQ" in exc.value.detail


# ── Standing ────────────────────────────────────────────────────────────────


class TestStanding:
    async def test_a_withdrawn_quote_keeps_its_reason_and_leaves_the_ranking(self) -> None:
        rfq = _rfq()
        bid = _bid(rfq)
        rfq.bids.append(bid)
        service = _service(rfq)
        updated = await service.withdraw_bid(bid.id, reason="Supplier cannot meet the programme")
        assert updated.status == "withdrawn"
        assert updated.withdrawn_reason
        assert updated.withdrawn_at
        result = RFQService.compare_payload(rfq, as_of=TODAY)
        assert cmp.REASON_WITHDRAWN in result.excluded[0].reasons

    async def test_disqualifying_a_quote_needs_an_award_level_role(self) -> None:
        rfq = _rfq()
        bid = _bid(rfq)
        rfq.bids.append(bid)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.disqualify_bid(bid.id, reason="Missing insurance", actor_role="editor")
        assert exc.value.status_code == 403

    async def test_a_manager_can_disqualify_a_quote(self) -> None:
        rfq = _rfq()
        bid = _bid(rfq)
        rfq.bids.append(bid)
        service = _service(rfq)
        updated = await service.disqualify_bid(bid.id, reason="Missing insurance", actor_role="manager")
        assert updated.status == "disqualified"
        assert updated.disqualified_reason == "Missing insurance"

    async def test_admitting_a_late_quote_lets_it_rank(self) -> None:
        rfq = _rfq()
        late = _bid(rfq, bidder_contact_id="beta", bid_amount="800", status="late", is_late=True)
        rfq.bids.append(_bid(rfq, bidder_contact_id="alpha", bid_amount="1000"))
        rfq.bids.append(late)
        service = _service(rfq)

        before = RFQService.compare_payload(rfq, as_of=TODAY)
        assert [quote.bidder_contact_id for quote in before.ranked] == ["alpha"]

        admitted = await service.admit_late_bid(
            late.id,
            reason="Buyer accepted the quote in writing before the others were opened",
            actor_id=str(uuid4()),
            actor_role="admin",
        )
        assert admitted.admitted_at
        assert admitted.admission_reason
        after = RFQService.compare_payload(rfq, as_of=TODAY)
        assert [quote.bidder_contact_id for quote in after.ranked] == ["beta", "alpha"]
        assert cmp.NOTE_LATE_ADMITTED in after.ranked[0].notes

    async def test_a_quote_that_was_not_late_cannot_be_admitted(self) -> None:
        rfq = _rfq()
        bid = _bid(rfq)
        rfq.bids.append(bid)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.admit_late_bid(bid.id, reason="No need", actor_role="admin")
        assert exc.value.status_code == 409

    async def test_admitting_a_late_quote_needs_an_award_level_role(self) -> None:
        rfq = _rfq()
        bid = _bid(rfq, status="late", is_late=True)
        rfq.bids.append(bid)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.admit_late_bid(bid.id, reason="Please", actor_role="editor")
        assert exc.value.status_code == 403

    async def test_nothing_can_be_changed_once_the_rfq_is_awarded(self) -> None:
        rfq = _rfq(status="awarded")
        bid = _bid(rfq)
        rfq.bids.append(bid)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.withdraw_bid(bid.id, reason="Too late to matter")
        assert exc.value.status_code == 409

    async def test_an_allowance_can_be_recorded_against_a_quote(self) -> None:
        rfq = _rfq()
        bid = _bid(rfq, bid_amount="1000")
        rfq.bids.append(bid)
        service = _service(rfq)
        updated = await service.add_adjustment(
            bid.id,
            BidAdjustmentCreate(kind="installation", amount="300", source="buyer", included_in_bid=False),
        )
        assert updated.adjustments[0].currency_code == "EUR"
        result = RFQService.compare_payload(rfq, as_of=TODAY)
        assert result.ranked[0].normalised_amount == Decimal("1300")


# ── Awarding ────────────────────────────────────────────────────────────────


class TestAward:
    async def test_an_editor_cannot_award(self) -> None:
        rfq = _rfq()
        bid = _bid(rfq)
        rfq.bids.append(bid)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.award_bid(bid.id, actor_role="editor")
        assert exc.value.status_code == 403

    async def test_a_quote_the_comparison_could_not_place_cannot_be_awarded(self) -> None:
        """The gate the whole register is for: no award off a comparison that did not happen."""
        rfq = _rfq()
        bid = _bid(rfq, currency_code="USD", bid_amount="800")
        rfq.bids.append(bid)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.award_bid(bid.id, actor_role="manager")
        assert exc.value.status_code == 409
        assert cmp.REASON_CURRENCY_NOT_CONVERTED in exc.value.detail

    async def test_the_same_quote_can_be_awarded_once_a_rate_is_recorded(self) -> None:
        rfq = _rfq()
        bid = _bid(rfq, currency_code="USD", bid_amount="800", exchange_rate=Decimal("0.9"))
        rfq.bids.append(bid)
        service = _service(rfq)
        awarded = await service.award_bid(bid.id, actor_role="manager", reason="Only supplier who quoted")
        assert awarded.is_awarded is True
        award = service.awards.award  # type: ignore[attr-defined]
        assert award.awarded_amount == Decimal("720.0")
        assert award.awarded_currency == "EUR"

    async def test_the_award_keeps_the_ranked_table_it_was_taken_from(self) -> None:
        rfq = _rfq()
        winner = _bid(rfq, bidder_contact_id="beta", bid_amount="900")
        rfq.bids.append(_bid(rfq, bidder_contact_id="alpha", bid_amount="1200"))
        rfq.bids.append(winner)
        service = _service(rfq)
        actor = str(uuid4())
        await service.award_bid(winner.id, actor_id=actor, actor_role="manager", reason="Lowest comparable price")

        award = service.awards.award  # type: ignore[attr-defined]
        assert award is not None
        assert award.reason == "Lowest comparable price"
        assert str(award.awarded_by) == actor
        assert award.is_override is False
        assert award.basis["awarded_bid_id"] == str(winner.id)
        assert [row["bidder_contact_id"] for row in award.basis["ranked"]] == ["beta", "alpha"]
        assert rfq.status == "awarded"

    async def test_awarding_past_the_top_ranked_quote_is_recorded_as_an_override(self) -> None:
        """Allowed, because the cheapest is not always the right answer - but never silent."""
        rfq = _rfq()
        dearer = _bid(rfq, bidder_contact_id="alpha", bid_amount="1200")
        rfq.bids.append(dearer)
        rfq.bids.append(_bid(rfq, bidder_contact_id="beta", bid_amount="900"))
        service = _service(rfq)
        await service.award_bid(dearer.id, actor_role="manager", reason="Programme risk on the cheaper offer")

        award = service.awards.award  # type: ignore[attr-defined]
        assert award.is_override is True
        assert award.recommended_bid_id != dearer.id
        assert award.awarded_amount == Decimal("1200")

    async def test_a_second_award_on_the_same_rfq_is_refused(self) -> None:
        rfq = _rfq()
        first = _bid(rfq, bidder_contact_id="alpha", bid_amount="1200")
        second = _bid(rfq, bidder_contact_id="beta", bid_amount="900")
        rfq.bids.extend([first, second])
        service = _service(rfq)
        await service.award_bid(first.id, actor_role="manager", reason="Best lead time")
        with pytest.raises(HTTPException) as exc:
            await service.award_bid(second.id, actor_role="manager", reason="Best price")
        assert exc.value.status_code == 409

    async def test_a_partial_quote_cannot_be_awarded_while_full_scope_is_required(self) -> None:
        rfq = _rfq(require_full_scope=True)
        rfq.lines.append(_line(rfq, line_no=1))
        rfq.lines.append(_line(rfq, line_no=2, code="A2", description="Commissioning"))
        bid = _bid(rfq, bid_amount="900")
        bid.lines.append(
            RFQBidLine(
                id=uuid4(),
                bid_id=bid.id,
                rfq_line_id=rfq.lines[0].id,
                unit="m2",
                quantity=Decimal("100"),
                unit_rate=Decimal("9"),
                amount=Decimal("900"),
                is_excluded=False,
            )
        )
        rfq.bids.append(bid)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.award_bid(bid.id, actor_role="manager")
        assert exc.value.status_code == 409
        assert cmp.REASON_SCOPE_NOT_COVERED in exc.value.detail

    async def test_the_award_record_is_readable_afterwards(self) -> None:
        rfq = _rfq()
        bid = _bid(rfq)
        rfq.bids.append(bid)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.get_award(rfq.id)
        assert exc.value.status_code == 404

        await service.award_bid(bid.id, actor_role="admin", reason="Only supplier who quoted")
        award = await service.get_award(rfq.id)
        assert award.bid_id == bid.id


# ── The quote gate ──────────────────────────────────────────────────────────


class TestQuoteGate:
    """Tiered quote minimums, enforced AT THE AWARD - the one door that
    cannot be walked around by a UI that skipped the compare step."""

    async def test_a_5k_package_with_one_quote_is_refused(self) -> None:
        rfq = _rfq()
        only = _bid(rfq, bid_amount="5000")
        rfq.bids.append(only)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.award_bid(only.id, actor_role="manager", reason="Best price")
        assert exc.value.status_code == 409
        detail = exc.value.detail
        assert detail["gate"] == "quotes"
        assert detail["can_force"] is True
        assert detail["quote_gate"]["required"] == 2
        assert detail["quote_gate"]["counted"] == 1
        assert "question does not count as a quote" in detail["error"]

    async def test_the_override_needs_a_written_reason_and_lands_on_the_record(self) -> None:
        rfq = _rfq()
        only = _bid(rfq, bid_amount="5000")
        rfq.bids.append(only)
        service = _service(rfq)
        awarded = await service.award_bid(
            only.id,
            actor_role="manager",
            reason="Only supplier who quoted",
            gate_override_reason="Two suppliers declined in writing; program cannot wait",
        )
        assert awarded.is_awarded is True
        award = service.awards.award  # type: ignore[attr-defined]
        gate = award.basis["quote_gate"]
        assert gate["passes"] is False
        assert gate["override_reason"] == "Two suppliers declined in writing; program cannot wait"

    async def test_a_junk_override_reason_is_refused_and_asked_again(self) -> None:
        """ "x" on the award file is a silent override wearing a costume.

        Found live 31 Aug: the gate accepted ANY non-empty override reason,
        while the workflow gates had rejected junk since the 19 Aug pass -
        one rail, two enforcement points, one of them decorative.
        ``reason_rejected`` is what tells the UI to re-ask instead of
        giving up.
        """
        rfq = _rfq()
        only = _bid(rfq, bid_amount="5000")
        rfq.bids.append(only)
        service = _service(rfq)
        for junk in ("x", "n/a", "override", "too short"):
            with pytest.raises(HTTPException) as exc:
                await service.award_bid(
                    only.id,
                    actor_role="manager",
                    reason="Best price",
                    gate_override_reason=junk,
                )
            assert exc.value.status_code == 409
            assert exc.value.detail["can_force"] is True
            assert exc.value.detail["reason_rejected"] is True
            assert junk in exc.value.detail["error"] or "reason" in exc.value.detail["error"]

    async def test_a_9k_package_with_two_quotes_needs_three(self) -> None:
        rfq = _rfq()
        winner = _bid(rfq, bidder_contact_id="alpha", bid_amount="9000")
        rfq.bids.append(winner)
        rfq.bids.append(_bid(rfq, bidder_contact_id="beta", bid_amount="9500"))
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.award_bid(winner.id, actor_role="manager", reason="Best price")
        assert exc.value.detail["quote_gate"]["required"] == 3

    async def test_a_small_package_awards_on_a_single_quote(self) -> None:
        rfq = _rfq()
        only = _bid(rfq, bid_amount="1800")
        rfq.bids.append(only)
        service = _service(rfq)
        awarded = await service.award_bid(only.id, actor_role="manager", reason="Only supplier who quoted")
        assert awarded.is_awarded is True
        assert service.awards.award.basis["quote_gate"]["passes"] is True  # type: ignore[attr-defined]

    async def test_withdrawn_and_disqualified_quotes_do_not_count(self) -> None:
        rfq = _rfq()
        winner = _bid(rfq, bidder_contact_id="alpha", bid_amount="5000")
        rfq.bids.append(winner)
        rfq.bids.append(_bid(rfq, bidder_contact_id="beta", bid_amount="5200", status="withdrawn"))
        rfq.bids.append(_bid(rfq, bidder_contact_id="gamma", bid_amount="5100", status="disqualified"))
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.award_bid(winner.id, actor_role="manager", reason="Best price")
        assert exc.value.detail["quote_gate"]["counted"] == 1

    async def test_the_buyers_estimate_raises_the_bar_even_when_bids_are_small(self) -> None:
        # Estimated $9,900 package that drew one cheap quote still needs three
        # prices - the value at risk is the estimate, not the lone number.
        rfq = _rfq(metadata_={"estimated_value": "9900"})
        only = _bid(rfq, bid_amount="2500")
        rfq.bids.append(only)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.award_bid(only.id, actor_role="manager", reason="Best price")
        assert exc.value.detail["quote_gate"]["required"] == 3

    async def test_an_award_without_a_reason_is_refused(self) -> None:
        rfq = _rfq()
        only = _bid(rfq, bid_amount="500")
        rfq.bids.append(only)
        service = _service(rfq)
        with pytest.raises(HTTPException) as exc:
            await service.award_bid(only.id, actor_role="manager")
        assert exc.value.status_code == 400
        assert "justification on the file" in exc.value.detail

    async def test_the_po_number_rides_the_award_record(self) -> None:
        rfq = _rfq()
        only = _bid(rfq, bid_amount="900")
        rfq.bids.append(only)
        service = _service(rfq)
        await service.award_bid(only.id, actor_role="manager", reason="Only supplier who quoted", po_number="PO-88412")
        assert service.awards.award.basis["po_number"] == "PO-88412"  # type: ignore[attr-defined]

    def test_an_unreadable_gate_override_tightens_never_loosens(self, monkeypatch) -> None:
        from app.modules.rfq_bidding.constants import quote_gate_rule

        monkeypatch.setenv("OE_RFQ_MIN_QUOTES_OVER", "not-a-number")
        rule = quote_gate_rule()
        assert rule == {"over": 0.01, "min": 3, "over3": 0.01, "min3": 3}

    def test_gate_env_overrides_apply(self, monkeypatch) -> None:
        from app.modules.rfq_bidding.constants import quote_gate_rule

        monkeypatch.setenv("OE_RFQ_MIN_QUOTES_OVER", "1000")
        monkeypatch.setenv("OE_RFQ_MIN_QUOTES", "2")
        monkeypatch.setenv("OE_RFQ_THREE_QUOTES_OVER", "5000")
        monkeypatch.setenv("OE_RFQ_THREE_QUOTES_MIN", "4")
        rule = quote_gate_rule()
        assert (rule["over"], rule["min"], rule["over3"], rule["min3"]) == (1000.0, 2, 5000.0, 4)
