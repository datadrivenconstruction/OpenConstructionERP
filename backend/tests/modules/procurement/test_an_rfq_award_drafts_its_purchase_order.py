# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An awarded RFQ drafts its purchase order, once, for the right supplier and money.

``rfq.awarded`` was published and nothing listened, so every award was retyped
as an order by hand. ``procurement/rfq_award.py`` now drafts it. What is pinned
here is what the reviewer of that draft relies on:

* the money is the awarded quote's own total in the quote's own currency, not
  the basis-currency figure the ranking used, and the lines add up to it to the
  cent whichever way the quote was priced;
* the supplier is the directory contact the quote was entered against, and
  only when that contact exists and belongs to the awarding user's tenant;
* the same award delivered twice is one order, and a re-award retires the
  earlier draft instead of leaving two live orders;
* a delivery that names a quote or an award that no longer stands writes
  nothing, and the order always lands in the RFQ's own project.

The tests drive ``draft_po_from_rfq_award`` with the rolled-back test session
lent to it, as ``test_award_cost_spine.py`` does for the tender path: the
subscriber itself only detaches the coroutine, so awaiting it proves nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.events import Event
from app.modules.contacts.models import Contact
from app.modules.costmodel.models import CostLine
from app.modules.procurement import rfq_award
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from app.modules.rfq_bidding.models import RFQ, RFQAward, RFQBid, RFQBidAdjustment, RFQBidLine, RFQLine
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


class _BorrowedSession:
    """Hand the handler the test session without letting it close it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@pytest.fixture(autouse=True)
def lend_session(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rfq_award, "async_session_factory", lambda: _BorrowedSession(session))


@pytest.fixture
def actor_id() -> uuid.UUID:
    return uuid.uuid4()


# ── Builders ────────────────────────────────────────────────────────────────


async def make_contact(session: AsyncSession, *, tenant: uuid.UUID | None, name: str = "Nordstahl GmbH") -> Contact:
    contact = Contact(
        contact_type="supplier",
        company_name=name,
        tenant_id=str(tenant) if tenant else None,
        created_by=str(tenant) if tenant else None,
    )
    session.add(contact)
    await session.flush()
    return contact


async def make_rfq(
    session: AsyncSession,
    *,
    scope: list[dict[str, Any]],
    currency: str = "EUR",
    status: str = "awarded",
    project_id: uuid.UUID | None = None,
) -> RFQ:
    rfq = RFQ(
        project_id=project_id or uuid.uuid4(),
        rfq_number="RFQ-014",
        title="Structural steel, level 2",
        currency_code=currency,
        status=status,
    )
    session.add(rfq)
    await session.flush()
    for no, line in enumerate(scope, start=1):
        session.add(
            RFQLine(
                rfq_id=rfq.id,
                line_no=no,
                code=line.get("code"),
                description=line["description"],
                unit=line["unit"],
                quantity=Decimal(line["quantity"]),
                cost_line_id=line.get("cost_line_id"),
                is_optional=line.get("is_optional", False),
            )
        )
    await session.flush()
    return rfq


async def scope_lines(session: AsyncSession, rfq: RFQ) -> list[RFQLine]:
    rows = await session.execute(select(RFQLine).where(RFQLine.rfq_id == rfq.id).order_by(RFQLine.line_no))
    return list(rows.scalars().all())


async def make_bid(
    session: AsyncSession,
    rfq: RFQ,
    *,
    bidder: str,
    amount: str,
    currency: str = "EUR",
    lines: list[dict[str, Any]] | None = None,
    adjustments: list[dict[str, Any]] | None = None,
    awarded: bool = True,
    exchange_rate: str | None = None,
) -> RFQBid:
    bid = RFQBid(
        rfq_id=rfq.id,
        bidder_contact_id=bidder,
        bid_amount=amount,
        currency_code=currency,
        is_awarded=awarded,
        exchange_rate=Decimal(exchange_rate) if exchange_rate else None,
    )
    session.add(bid)
    await session.flush()
    for line in lines or []:
        session.add(
            RFQBidLine(
                bid_id=bid.id,
                rfq_line_id=line.get("rfq_line_id"),
                description=line.get("description"),
                unit=line.get("unit", ""),
                quantity=Decimal(line.get("quantity", "0")),
                unit_rate=Decimal(line.get("unit_rate", "0")),
                amount=Decimal(line.get("amount", "0")),
                is_excluded=line.get("is_excluded", False),
            )
        )
    for adj in adjustments or []:
        session.add(RFQBidAdjustment(bid_id=bid.id, **adj))
    await session.flush()
    return bid


async def make_award(
    session: AsyncSession,
    rfq: RFQ,
    bid: RFQBid,
    *,
    basis_amount: str,
    basis_currency: str = "EUR",
) -> RFQAward:
    award = RFQAward(
        rfq_id=rfq.id,
        bid_id=bid.id,
        awarded_at=datetime.now(UTC).isoformat(),
        awarded_amount=Decimal(basis_amount),
        awarded_currency=basis_currency,
    )
    session.add(award)
    await session.flush()
    return award


def awarded(
    rfq: RFQ,
    bid: RFQBid,
    award: RFQAward,
    *,
    actor: uuid.UUID | None,
    project_id: uuid.UUID | None = None,
) -> Event:
    """The payload ``RFQService.award_bid`` publishes."""
    return Event(
        name="rfq.awarded",
        data={
            "rfq_id": str(rfq.id),
            "rfq_number": rfq.rfq_number,
            "bid_id": str(bid.id),
            "bidder_contact_id": bid.bidder_contact_id,
            "bid_amount": bid.bid_amount,
            "currency_code": bid.currency_code,
            "project_id": str(project_id or rfq.project_id),
            "actor_id": str(actor) if actor else None,
            "normalised_amount": str(award.awarded_amount),
            "basis_currency": award.awarded_currency,
            "award_id": str(award.id),
            "is_override": False,
        },
        source_module="rfq_bidding",
    )


async def orders(session: AsyncSession, project_id: uuid.UUID) -> list[PurchaseOrder]:
    rows = await session.execute(
        select(PurchaseOrder).where(PurchaseOrder.project_id == project_id).order_by(PurchaseOrder.po_number)
    )
    return list(rows.scalars().all())


async def items_of(session: AsyncSession, po: PurchaseOrder) -> list[PurchaseOrderItem]:
    rows = await session.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po.id).order_by(PurchaseOrderItem.sort_order)
    )
    return list(rows.scalars().all())


def _sum(items: list[PurchaseOrderItem]) -> Decimal:
    return sum((Decimal(item.amount) for item in items), Decimal("0"))


async def approval_errors(session: AsyncSession, po_id: uuid.UUID | None) -> list[str]:
    """The ERROR findings approval would refuse the stored draft on.

    The draft is read back from the database and run through the same
    ``procurement`` rule set ``approve_po`` runs, so this sees the strings the
    order lines actually hold. The run must include the line-amount rule, or
    an empty answer would only mean the rules never ran.
    """
    from app.core.validation.rules import register_builtin_rules
    from app.modules.procurement.service import ProcurementService

    assert po_id is not None
    register_builtin_rules()
    po = (
        await session.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.id == po_id)
            .options(selectinload(PurchaseOrder.items))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    report = await ProcurementService(session)._validate_po(po, operation="approve")
    assert "procurement.po_line_amount" in {r.rule_id for r in report.results}
    return [f"{r.rule_id} {r.element_ref}" for r in report.errors]


TWO_LINE_SCOPE = [
    {"code": "S-01", "description": "HEB 300 columns, S355", "unit": "t", "quantity": "12"},
    {"code": "S-02", "description": "IPE 400 beams, S355", "unit": "t", "quantity": "8"},
]


async def priced_award(
    session: AsyncSession,
    *,
    bidder: str,
    amount: str = "25000.00",
    first: tuple[str, str, str] = ("12", "1250.00", "15000.00"),
    second: tuple[str, str, str] = ("8", "1250.00", "10000.00"),
    currency: str = "EUR",
) -> tuple[RFQ, RFQBid, RFQAward]:
    """A two-line RFQ awarded to a quote that priced both lines."""
    rfq = await make_rfq(session, scope=TWO_LINE_SCOPE)
    s1, s2 = await scope_lines(session, rfq)
    bid = await make_bid(
        session,
        rfq,
        bidder=bidder,
        amount=amount,
        currency=currency,
        lines=[
            {"rfq_line_id": s1.id, "unit": "t", "quantity": first[0], "unit_rate": first[1], "amount": first[2]},
            {"rfq_line_id": s2.id, "unit": "t", "quantity": second[0], "unit_rate": second[1], "amount": second[2]},
        ],
    )
    award = await make_award(session, rfq, bid, basis_amount=amount)
    return rfq, bid, award


# ── The draft ───────────────────────────────────────────────────────────────


async def test_an_award_drafts_one_order_with_the_quoted_lines(session: AsyncSession, actor_id: uuid.UUID) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id))

    po_id = await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    assert po.id == po_id
    assert po.status == "draft"
    assert po.vendor_contact_id == str(contact.id)
    assert po.currency_code == "EUR"
    assert po.amount_subtotal == po.amount_total == "25000.00"
    md = po.metadata_
    assert md["origin"] == "rfq_award"
    assert md["rfq_id"] == str(rfq.id)
    assert md["rfq_award_id"] == str(award.id)
    assert md["rfq_bid_id"] == str(bid.id)
    assert md["rfq_number"] == "RFQ-014"
    assert md["supplier_name"] == "Nordstahl GmbH"
    assert md["pricing"] == "itemised"

    items = await items_of(session, po)
    assert [(i.description, i.quantity, i.unit, i.unit_rate, i.amount) for i in items] == [
        ("S-01 HEB 300 columns, S355", "12", "t", "1250", "15000.00"),
        ("S-02 IPE 400 beams, S355", "8", "t", "1250", "10000.00"),
    ]
    assert _sum(items) == Decimal(po.amount_total)


async def test_the_same_award_delivered_twice_is_one_order(session: AsyncSession, actor_id: uuid.UUID) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id))
    event = awarded(rfq, bid, award, actor=actor_id)

    first = await rfq_award.draft_po_from_rfq_award(event)
    second = await rfq_award.draft_po_from_rfq_award(event)

    assert first is not None
    assert second == first
    [po] = await orders(session, rfq.project_id)
    assert len(await items_of(session, po)) == 2


# ── Money ───────────────────────────────────────────────────────────────────


async def test_the_order_is_in_the_quotes_currency_at_the_quoted_total(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    """A USD quote on a EUR RFQ is ordered in USD at the USD total.

    The award record holds 9,000.00 EUR, the quote restated at the rate it was
    compared on. Ordering that figure would send the supplier a EUR order for
    a USD price; ordering the USD figure in EUR would be off by the rate.
    """
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(session, scope=[], currency="EUR")
    bid = await make_bid(session, rfq, bidder=str(contact.id), amount="10000.00", currency="USD", exchange_rate="0.9")
    award = await make_award(session, rfq, bid, basis_amount="9000.00", basis_currency="EUR")

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    assert po.currency_code == "USD"
    assert po.amount_total == "10000.00"
    assert po.metadata_["award_basis_amount"] == "9000.00"
    assert po.metadata_["award_basis_currency"] == "EUR"
    assert po.metadata_["quoted_amount"] == "10000.00"


async def test_a_quote_given_as_one_total_is_one_line(session: AsyncSession, actor_id: uuid.UUID) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(session, scope=TWO_LINE_SCOPE)
    bid = await make_bid(session, rfq, bidder=str(contact.id), amount="24750.50")
    award = await make_award(session, rfq, bid, basis_amount="24750.50")

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    [item] = await items_of(session, po)
    assert item.description == "RFQ-014 Structural steel, level 2: awarded quote, lump sum"
    assert (item.quantity, item.unit_rate, item.amount) == ("1", "24750.5", "24750.50")
    assert po.amount_total == "24750.50"
    assert po.metadata_["pricing"] == "lump_sum"
    assert "single total" in po.notes


async def test_lines_short_of_the_total_keep_their_figures_and_the_gap_is_one_line(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    """The priced lines stay exactly as quoted; only the difference is added.

    Spreading the gap over the lines would change rates the supplier quoted;
    dropping it would order less than was awarded. The test tells those apart:
    the two quoted lines are byte for byte the quote's, and the three amounts
    sum to the quoted total.
    """
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id), amount="26200.00")

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    items = await items_of(session, po)
    assert [(i.quantity, i.unit_rate, i.amount) for i in items[:2]] == [
        ("12", "1250", "15000.00"),
        ("8", "1250", "10000.00"),
    ]
    assert items[2].description == "Quoted total not itemised against the priced lines"
    assert items[2].amount == "1200.00"
    assert _sum(items) == Decimal("26200.00") == Decimal(po.amount_total)
    assert po.metadata_["pricing"] == "itemised_with_balance"


async def test_an_overall_discount_is_spread_over_the_lines_and_keeps_their_cost_lines(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    """Lines of 25,000.00 under a 24,000.00 total: a 4% discount on every line.

    One lump sum at the total would add up too, so the test tells the two
    apart on what a lump sum loses: each line keeps its scope item and its
    cost line, and comes down by the same 4%, with a rate that still gives
    its amount.
    """
    project_id = uuid.uuid4()
    columns = CostLine(
        project_id=project_id, code="CL-1", description="Columns", unit="t", currency="EUR", status="active"
    )
    beams = CostLine(project_id=project_id, code="CL-2", description="Beams", unit="t", currency="EUR", status="active")
    session.add_all([columns, beams])
    await session.flush()
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(
        session,
        project_id=project_id,
        scope=[
            {**TWO_LINE_SCOPE[0], "cost_line_id": columns.id},
            {**TWO_LINE_SCOPE[1], "cost_line_id": beams.id},
        ],
    )
    s1, s2 = await scope_lines(session, rfq)
    bid = await make_bid(
        session,
        rfq,
        bidder=str(contact.id),
        amount="24000.00",
        lines=[
            {"rfq_line_id": s1.id, "unit": "t", "quantity": "12", "unit_rate": "1250", "amount": "15000"},
            {"rfq_line_id": s2.id, "unit": "t", "quantity": "8", "unit_rate": "1250", "amount": "10000"},
        ],
    )
    award = await make_award(session, rfq, bid, basis_amount="24000.00")

    po_id = await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, project_id)
    items = await items_of(session, po)
    assert [(i.description, i.quantity, i.unit_rate, i.amount, i.cost_line_id) for i in items] == [
        ("S-01 HEB 300 columns, S355", "12", "1200", "14400.00", columns.id),
        ("S-02 IPE 400 beams, S355", "8", "1200", "9600.00", beams.id),
    ]
    assert _sum(items) == Decimal(po.amount_total) == Decimal("24000.00")
    assert po.metadata_["pricing"] == "itemised_discounted"
    assert "add up to 25000.00 EUR" in po.notes
    assert "overall discount of 4.00%" in po.notes
    assert "lump sum" not in po.notes
    assert await approval_errors(session, po_id) == []


async def test_a_discount_that_does_not_divide_evenly_still_sums_to_the_cent(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    """Three lines of 100.00 under a total of 200.00: 66.666... each.

    Rounding each share gives 66.67 three times, 200.01 in all. The extra
    cent comes off one line, so the order is 200.00 and not a cent more, and
    every line's rate still gives its amount.
    """
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(session, scope=[])
    bid = await make_bid(
        session,
        rfq,
        bidder=str(contact.id),
        amount="200.00",
        lines=[
            {"description": name, "unit": "pcs", "quantity": "1", "unit_rate": "100", "amount": "100"}
            for name in ("Anchor set A", "Anchor set B", "Anchor set C")
        ],
    )
    award = await make_award(session, rfq, bid, basis_amount="200.00")

    po_id = await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    items = await items_of(session, po)
    assert sorted(i.amount for i in items) == ["66.66", "66.67", "66.67"]
    assert _sum(items) == Decimal(po.amount_total) == Decimal("200.00")
    assert all(i.unit_rate == i.amount.rstrip("0").rstrip(".") for i in items)
    assert await approval_errors(session, po_id) == []


async def test_an_excluded_line_is_not_ordered_and_an_extra_line_is(session: AsyncSession, actor_id: uuid.UUID) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(session, scope=TWO_LINE_SCOPE)
    s1, s2 = await scope_lines(session, rfq)
    bid = await make_bid(
        session,
        rfq,
        bidder=str(contact.id),
        amount="15600.00",
        lines=[
            {
                "rfq_line_id": s2.id,
                "unit": "t",
                "quantity": "8",
                "unit_rate": "1250",
                "amount": "10000",
                "is_excluded": True,
            },
            {
                "rfq_line_id": None,
                "description": "Shop primer, 80 microns",
                "unit": "t",
                "quantity": "12",
                "unit_rate": "50",
                "amount": "600",
            },
            {"rfq_line_id": s1.id, "unit": "t", "quantity": "12", "unit_rate": "1250", "amount": "15000"},
        ],
    )
    award = await make_award(session, rfq, bid, basis_amount="15600.00")

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    items = await items_of(session, po)
    assert [i.description for i in items] == ["S-01 HEB 300 columns, S355", "Shop primer, 80 microns"]
    assert _sum(items) == Decimal(po.amount_total) == Decimal("15600.00")


OPTIONAL_COATING = {
    "code": "S-03",
    "description": "Intumescent coating, R60 (alternate)",
    "unit": "m2",
    "quantity": "400",
    "is_optional": True,
}


async def _quote_with_an_alternate(
    session: AsyncSession, contact: Contact, amount: str
) -> tuple[RFQ, RFQBid, RFQAward]:
    """Both required lines priced at 25,000.00 in all, plus an optional alternate at 4,800.00."""
    rfq = await make_rfq(session, scope=[*TWO_LINE_SCOPE, OPTIONAL_COATING])
    s1, s2, s3 = await scope_lines(session, rfq)
    bid = await make_bid(
        session,
        rfq,
        bidder=str(contact.id),
        amount=amount,
        lines=[
            {"rfq_line_id": s1.id, "unit": "t", "quantity": "12", "unit_rate": "1250", "amount": "15000"},
            {"rfq_line_id": s2.id, "unit": "t", "quantity": "8", "unit_rate": "1250", "amount": "10000"},
            {"rfq_line_id": s3.id, "unit": "m2", "quantity": "400", "unit_rate": "12", "amount": "4800"},
        ],
    )
    award = await make_award(session, rfq, bid, basis_amount=amount)
    return rfq, bid, award


async def test_an_alternate_priced_beside_the_total_is_named_not_ordered(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    """The quoted total covers the required scope; the alternate sits outside it.

    Ordering every priced line would put 29,800.00 of lines against a 25,000.00
    quote, read that as a discount and collapse the order to one lump sum.
    """
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await _quote_with_an_alternate(session, contact, "25000.00")

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    items = await items_of(session, po)
    assert [i.description for i in items] == ["S-01 HEB 300 columns, S355", "S-02 IPE 400 beams, S355"]
    assert _sum(items) == Decimal(po.amount_total) == Decimal("25000.00")
    assert po.metadata_["pricing"] == "itemised"
    assert "S-03 Intumescent coating, R60 (alternate) 4800.00 EUR" in po.notes
    assert "discount" not in po.notes


async def test_an_alternate_the_total_includes_is_ordered(session: AsyncSession, actor_id: uuid.UUID) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await _quote_with_an_alternate(session, contact, "29800.00")

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    items = await items_of(session, po)
    assert len(items) == 3
    assert _sum(items) == Decimal(po.amount_total) == Decimal("29800.00")
    assert "Optional items" not in po.notes


async def test_a_rounding_difference_stays_itemised_and_still_adds_up(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    """Three cents over the total is rounding, not a discount.

    The cents are taken up on the largest line; the other line is exactly as
    quoted, and the order still adds up to the quoted total.
    """
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(
        session,
        bidder=str(contact.id),
        amount="25000.00",
        first=("12", "1250.00", "15000.03"),
    )

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    items = await items_of(session, po)
    assert [i.amount for i in items] == ["15000.00", "10000.00"]
    assert _sum(items) == Decimal(po.amount_total) == Decimal("25000.00")
    assert po.metadata_["pricing"] == "itemised"
    assert "by 0.03 EUR through rounding" in po.notes
    assert "discount" not in po.notes


# ── The draft passes the gate it will be approved through ──────────────────


@pytest.mark.parametrize(
    ("headline", "first"),
    [
        pytest.param("25000.00", ("12", "1250", "15000"), id="as-quoted"),
        pytest.param("25000.03", ("12", "1250", "15000"), id="rounding-up"),
        pytest.param("24999.97", ("12", "1250", "15000"), id="rounding-down"),
        pytest.param("25000.00", ("12", "1250", "15000.03"), id="rounding-repairs-a-line"),
        pytest.param("26200.00", ("12", "1250", "15000"), id="balance-line"),
        pytest.param("24000.00", ("12", "1250", "15000"), id="overall-discount"),
        pytest.param("24250.00", ("12", "1250", "14250"), id="line-discount"),
        pytest.param("25000.00", ("0", "1250", "15000"), id="no-quantity"),
        pytest.param("25000.00", ("0", "1300", "15000"), id="no-quantity-rate-disagrees"),
    ],
)
async def test_every_pricing_shape_drafts_an_order_approval_accepts(
    session: AsyncSession, actor_id: uuid.UUID, headline: str, first: tuple[str, str, str]
) -> None:
    """A draft the system wrote must not be refused by the system's own gate.

    ``procurement.po_line_amount`` refuses a line whose amount is not its
    quantity times its rate. Before the rate was restated, the rounding
    shapes, the line discount and the missing quantity each wrote such a line,
    and the reviewer met a 422 on Approve.
    """
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id), amount=headline, first=first)

    po_id = await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    assert _sum(await items_of(session, po)) == Decimal(po.amount_total) == Decimal(headline)
    assert await approval_errors(session, po_id) == []


async def test_cents_of_rounding_restate_the_rate_and_name_the_quoted_one(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    """Two consistent lines under a total three cents higher.

    The cents land on the largest line as before; its rate becomes the one
    that gives 15,000.03 over 12 t, and the notes keep the 1,250 the supplier
    quoted. The other line is untouched.
    """
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id), amount="25000.03")

    po_id = await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    items = await items_of(session, po)
    assert [(i.quantity, i.unit_rate, i.amount) for i in items] == [
        ("12", "1250.0025", "15000.03"),
        ("8", "1250", "10000.00"),
    ]
    assert "S-01 HEB 300 columns, S355 (quoted 1250, ordered 1250.0025)" in po.notes
    assert "S-02" not in po.notes
    assert await approval_errors(session, po_id) == []


async def test_a_line_discount_keeps_the_amount_and_restates_the_rate(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    """10 x 100 priced at 950: the supplier charges 950, so 950 is ordered at 95."""
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(session, scope=[])
    bid = await make_bid(
        session,
        rfq,
        bidder=str(contact.id),
        amount="950.00",
        lines=[
            {"description": "Grout, non-shrink", "unit": "bag", "quantity": "10", "unit_rate": "100", "amount": "950"}
        ],
    )
    award = await make_award(session, rfq, bid, basis_amount="950.00")

    po_id = await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    [item] = await items_of(session, po)
    assert (item.quantity, item.unit_rate, item.amount) == ("10", "95", "950.00")
    assert "Grout, non-shrink (quoted 100, ordered 95)" in po.notes
    assert await approval_errors(session, po_id) == []


async def test_a_line_without_a_quantity_takes_the_one_its_rate_and_amount_imply(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    """Rate 50 and amount 500 is ten units, whatever the scope's 12 says.

    Taking the scope's quantity would order 12 at the supplier's 50 against
    an amount of 500, which approval refuses; restating the rate to 41.667
    would pass but misquote a supplier who priced ten.
    """
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(session, scope=[TWO_LINE_SCOPE[0]])
    [s1] = await scope_lines(session, rfq)
    bid = await make_bid(
        session,
        rfq,
        bidder=str(contact.id),
        amount="500.00",
        lines=[{"rfq_line_id": s1.id, "unit": "t", "quantity": "0", "unit_rate": "50", "amount": "500"}],
    )
    award = await make_award(session, rfq, bid, basis_amount="500.00")

    po_id = await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    [item] = await items_of(session, po)
    assert (item.quantity, item.unit_rate, item.amount) == ("10", "50", "500.00")
    assert "quoted 50" not in po.notes
    assert await approval_errors(session, po_id) == []


async def test_a_restated_rate_on_an_awkward_quantity_stays_short_and_exact(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    """12,345.678 m at a quoted 1.23 but priced 15,000.00.

    The exact quotient runs to 28 digits. The rate written is the shortest
    one whose product lands on the amount, and it fits the column.
    """
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(session, scope=[])
    bid = await make_bid(
        session,
        rfq,
        bidder=str(contact.id),
        amount="15000.00",
        lines=[
            {"description": "Cable tray", "unit": "m", "quantity": "12345.678", "unit_rate": "1.23", "amount": "15000"}
        ],
    )
    award = await make_award(session, rfq, bid, basis_amount="15000.00")

    po_id = await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    [item] = await items_of(session, po)
    assert item.amount == "15000.00"
    assert len(item.unit_rate) <= 20
    assert abs(Decimal(item.quantity) * Decimal(item.unit_rate) - Decimal("15000.00")) <= Decimal("0.005")
    assert await approval_errors(session, po_id) == []


async def test_charges_outside_the_quote_are_named_not_ordered(session: AsyncSession, actor_id: uuid.UUID) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(session, scope=[])
    bid = await make_bid(
        session,
        rfq,
        bidder=str(contact.id),
        amount="5000.00",
        adjustments=[
            {"kind": "freight", "description": "Delivery to site", "amount": Decimal("450"), "currency_code": "EUR"},
            {"kind": "taxes", "amount": Decimal("950"), "currency_code": "EUR", "included_in_bid": True},
        ],
    )
    award = await make_award(session, rfq, bid, basis_amount="5450.00")

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    assert po.amount_total == "5000.00"
    assert "freight (Delivery to site) 450.00 EUR" in po.notes
    assert "taxes" not in po.notes


async def test_a_scope_line_keeps_its_cost_line_only_inside_the_project(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    project_id = uuid.uuid4()
    ours = CostLine(project_id=project_id, code="CL-1", description="Steel", unit="t", currency="EUR", status="active")
    theirs = CostLine(
        project_id=uuid.uuid4(), code="CL-9", description="Steel", unit="t", currency="EUR", status="active"
    )
    session.add_all([ours, theirs])
    await session.flush()
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(
        session,
        project_id=project_id,
        scope=[
            {**TWO_LINE_SCOPE[0], "cost_line_id": ours.id},
            {**TWO_LINE_SCOPE[1], "cost_line_id": theirs.id},
        ],
    )
    s1, s2 = await scope_lines(session, rfq)
    bid = await make_bid(
        session,
        rfq,
        bidder=str(contact.id),
        amount="25000.00",
        lines=[
            {"rfq_line_id": s1.id, "unit": "t", "quantity": "12", "unit_rate": "1250", "amount": "15000"},
            {"rfq_line_id": s2.id, "unit": "t", "quantity": "8", "unit_rate": "1250", "amount": "10000"},
        ],
    )
    award = await make_award(session, rfq, bid, basis_amount="25000.00")

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, project_id)
    assert [i.cost_line_id for i in await items_of(session, po)] == [ours.id, None]


# ── Supplier ────────────────────────────────────────────────────────────────


async def test_a_bidder_id_with_no_contact_leaves_the_vendor_for_the_reviewer(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    rfq, bid, award = await priced_award(session, bidder=str(uuid.uuid4()))

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    assert po.vendor_contact_id is None
    assert po.metadata_["vendor_link"] == "not_in_directory"
    assert po.metadata_["supplier_name"] is None
    assert "Pick the vendor before approving" in po.notes
    assert po.amount_total == "25000.00"


async def test_a_supplier_typed_by_name_names_the_order_without_a_contact(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    rfq, bid, award = await priced_award(session, bidder="Baltic Steel Trading")

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    assert po.vendor_contact_id is None
    assert po.metadata_["supplier_name"] == "Baltic Steel Trading"


async def test_a_contact_from_another_tenant_is_neither_linked_nor_named(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    foreign = await make_contact(session, tenant=uuid.uuid4(), name="Someone Else's Supplier Ltd")
    rfq, bid, award = await priced_award(session, bidder=str(foreign.id))

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))

    [po] = await orders(session, rfq.project_id)
    assert po.vendor_contact_id is None
    assert po.metadata_["vendor_link"] == "not_accessible"
    assert po.metadata_["supplier_name"] is None
    assert "Someone Else" not in (po.notes or "")


async def test_the_order_lands_in_the_rfqs_project_whatever_the_payload_says(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id))
    elsewhere = uuid.uuid4()

    await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id, project_id=elsewhere))

    assert await orders(session, elsewhere) == []
    assert len(await orders(session, rfq.project_id)) == 1


# ── The award has to stand ──────────────────────────────────────────────────


async def test_an_event_naming_a_quote_the_award_is_not_for_writes_nothing(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id))
    loser = await make_bid(session, rfq, bidder=str(contact.id), amount="1.00", awarded=False)
    event = awarded(rfq, bid, award, actor=actor_id)
    event.data["bid_id"] = str(loser.id)

    assert await rfq_award.draft_po_from_rfq_award(event) is None
    assert await orders(session, rfq.project_id) == []


async def test_an_award_that_no_longer_exists_writes_nothing(session: AsyncSession, actor_id: uuid.UUID) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id))
    event = awarded(rfq, bid, award, actor=actor_id)
    await session.delete(award)
    await session.flush()

    assert await rfq_award.draft_po_from_rfq_award(event) is None
    assert await orders(session, rfq.project_id) == []


async def test_an_rfq_no_longer_awarded_writes_nothing(session: AsyncSession, actor_id: uuid.UUID) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id))
    rfq.status = "cancelled"
    await session.flush()

    assert await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id)) is None
    assert await orders(session, rfq.project_id) == []


async def _re_award(
    session: AsyncSession, rfq: RFQ, old_bid: RFQBid, old_award: RFQAward, bidder: str
) -> tuple[RFQBid, RFQAward]:
    """Take the award back and give it to another quote, as a reversal would."""
    await session.delete(old_award)
    old_bid.is_awarded = False
    await session.flush()
    new_bid = await make_bid(session, rfq, bidder=bidder, amount="23000.00")
    new_award = await make_award(session, rfq, new_bid, basis_amount="23000.00")
    return new_bid, new_award


async def test_a_re_award_retires_the_earlier_draft(session: AsyncSession, actor_id: uuid.UUID) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id))
    first = await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))
    new_bid, new_award = await _re_award(session, rfq, bid, award, str(contact.id))

    second = await rfq_award.draft_po_from_rfq_award(awarded(rfq, new_bid, new_award, actor=actor_id))

    by_id = {po.id: po for po in await orders(session, rfq.project_id)}
    assert set(by_id) == {first, second}
    assert first is not None and second is not None
    assert by_id[first].status == "cancelled"
    assert by_id[second].status == "draft"
    assert by_id[second].amount_total == "23000.00"
    live = [po for po in by_id.values() if po.status != "cancelled"]
    assert [po.metadata_["rfq_award_id"] for po in live] == [str(new_award.id)]


async def test_a_re_award_does_not_add_an_order_beside_an_approved_one(
    session: AsyncSession, actor_id: uuid.UUID
) -> None:
    contact = await make_contact(session, tenant=actor_id)
    rfq, bid, award = await priced_award(session, bidder=str(contact.id))
    first = await rfq_award.draft_po_from_rfq_award(awarded(rfq, bid, award, actor=actor_id))
    [po] = await orders(session, rfq.project_id)
    po.status = "approved"
    await session.flush()
    new_bid, new_award = await _re_award(session, rfq, bid, award, str(contact.id))

    assert await rfq_award.draft_po_from_rfq_award(awarded(rfq, new_bid, new_award, actor=actor_id)) is None

    [still] = await orders(session, rfq.project_id)
    assert still.id == first
    assert still.status == "approved"


# ── Wiring ──────────────────────────────────────────────────────────────────


async def test_a_real_award_defers_an_event_that_drafts_the_order(
    session: AsyncSession, actor_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """From ``award_bid`` itself to the draft, without a hand-built payload.

    The publish is deferred to the commit of the award's own session, and the
    payload it carries names the stored award and the awarding user in the
    shapes the subscriber reads.
    """
    from app.core import events as core_events
    from app.modules.rfq_bidding.service import RFQService

    captured: list[tuple[object, str, dict[str, Any]]] = []

    def capture(sess: object, name: str, data: dict[str, Any] | None = None, **_kw: object) -> None:
        captured.append((sess, name, dict(data or {})))

    monkeypatch.setattr(core_events, "publish_after_commit", capture)
    contact = await make_contact(session, tenant=actor_id)
    rfq = await make_rfq(session, scope=[], status="bids_received")
    bid = await make_bid(session, rfq, bidder=str(contact.id), amount="18000.00", awarded=False)

    await RFQService(session).award_bid(bid.id, actor_id=str(actor_id), actor_role="manager")

    [(published_on, name, payload)] = captured
    assert published_on is session
    assert name == "rfq.awarded"
    award = (await session.execute(select(RFQAward).where(RFQAward.rfq_id == rfq.id))).scalar_one()
    assert payload["award_id"] == str(award.id)

    po_id = await rfq_award.draft_po_from_rfq_award(Event(name=name, data=payload))

    [po] = await orders(session, rfq.project_id)
    assert po.id == po_id
    assert po.vendor_contact_id == str(contact.id)
    assert (po.amount_total, po.currency_code) == ("18000.00", "EUR")


async def test_procurement_subscribes_to_the_rfq_award() -> None:
    from app.core.events import event_bus
    from app.modules.procurement import events as procurement_events  # noqa: F401 - registers on import

    assert rfq_award.on_rfq_awarded in event_bus._handlers.get("rfq.awarded", [])
