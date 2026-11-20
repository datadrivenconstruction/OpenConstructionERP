# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: tendering packages and RFQs are copied into the one tender model without loss.

Covers the copy (S3), the write-through and visibility listeners (S4), and the
award characterisation (S0): with the mirror switched on, one tender award still
drafts exactly one contract and no purchase order, because the copy never emits
an award event and never links itself through ``BidPackage.tender_id``.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.bid_management import legacy_mirror
from app.modules.bid_management.legacy_copy import LegacyCopier, copy_all, reconcile
from app.modules.bid_management.models import (
    BidAward,
    Bidder,
    BidInvitation,
    BidPackage,
    BidPackageLineItem,
    BidQA,
    BidRejection,
    BidSubmission,
    BidSubmissionAdjustment,
    BidSubmissionLine,
    TenderLegacyMap,
)
from app.modules.projects.models import Project
from app.modules.rfq_bidding.models import RFQ, RFQAward, RFQBid, RFQBidAdjustment, RFQBidLine, RFQLine
from app.modules.tendering.models import TenderBid, TenderBidInvitation, TenderClarification, TenderPackage
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

_ALL = {legacy_mirror.INCLUDE_MIRRORS: True, "populate_existing": True}


@pytest.fixture
def mirror_on():
    legacy_mirror.install()
    yield
    legacy_mirror.uninstall()


async def _project(session) -> Project:
    owner = User(email=f"tmm-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Buyer")
    session.add(owner)
    await session.flush()
    project = Project(name="Tender merge", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


async def _tender(session, project, *, status="evaluating", metadata=None) -> tuple[TenderPackage, list[TenderBid]]:
    pos_a, pos_b = str(uuid.uuid4()), str(uuid.uuid4())
    package = TenderPackage(
        project_id=project.id, name="Drywall", description="Partitions", status=status, metadata_=metadata or {}
    )
    session.add(package)
    await session.flush()
    bids = []
    for company, total, rate in (("Trockenbau Nord", "148200.00", "28.50"), ("Ausbau Sued", "151999.99", "29.10")):
        bid = TenderBid(
            package_id=package.id,
            company_name=company,
            contact_email=f"bids@{company.split()[0].lower()}.test",
            total_amount=total,
            currency="EUR",
            status="submitted",
            line_items=[
                {
                    "position_id": pos_a,
                    "description": "Partition 100 mm",
                    "unit": "m2",
                    "quantity": 5200.0,
                    "unit_rate": rate,
                    "total": 148200.0,
                },
                {
                    "position_id": pos_b,
                    "description": "Corner bead",
                    "unit": "m",
                    "quantity": 10.0,
                    "unit_rate": "0",
                    "total": 0.0,
                },
                {
                    "position_id": "not-a-position",
                    "description": "Night shift surcharge",
                    "unit": "ls",
                    "quantity": 1.0,
                    "unit_rate": "0",
                    "total": 0.0,
                },
            ],
        )
        session.add(bid)
        bids.append(bid)
    await session.flush()
    return package, bids


async def _rfq(session, project, number="RFQ-2027-001") -> RFQ:
    rfq = RFQ(
        project_id=project.id,
        rfq_number=number,
        title="Ready-mix 4000 psi",
        description="Concrete supply",
        scope_of_work="Delivered to site, pumped",
        currency_code="USD",
        status="bids_received",
        issued_to_contacts=[str(uuid.uuid4())],
        technical_weight=Decimal("30"),
        evaluation_method="best_value",
    )
    session.add(rfq)
    await session.flush()
    concrete = RFQLine(
        rfq_id=rfq.id, line_no=1, code="03 31 00", description="Concrete", unit="CY", quantity=Decimal("1800")
    )
    pump = RFQLine(
        rfq_id=rfq.id,
        line_no=2,
        code="PUMP",
        description="Pump",
        unit="CY",
        quantity=Decimal("1800"),
        is_optional=True,
        notes="only when the crane is busy",
    )
    session.add_all([concrete, pump])
    await session.flush()
    bid = RFQBid(
        rfq_id=rfq.id,
        bidder_contact_id=str(uuid.uuid4()),
        bid_amount="328500.00",
        currency_code="USD",
        validity_days=45,
        technical_score="80",
        commercial_score="90",
        is_late=True,
        late_reason="truck strike",
        metadata_={"company_name": "Lone Star Ready Mix"},
    )
    session.add(bid)
    await session.flush()
    session.add_all(
        [
            RFQBidLine(
                bid_id=bid.id,
                rfq_line_id=concrete.id,
                quantity=Decimal("1800"),
                unit_rate=Decimal("168.00"),
                amount=Decimal("302400.00"),
            ),
            RFQBidLine(
                bid_id=bid.id,
                rfq_line_id=pump.id,
                quantity=Decimal("1800"),
                unit_rate=Decimal("14.50"),
                amount=Decimal("26100.00"),
                is_excluded=True,
            ),
            RFQBidLine(
                bid_id=bid.id,
                rfq_line_id=None,
                description="Winter heating",
                unit="CY",
                quantity=Decimal("100"),
                unit_rate=Decimal("3.00"),
                amount=Decimal("300.00"),
            ),
            RFQBidAdjustment(
                bid_id=bid.id,
                kind="exclusion",
                description="Testing by others",
                amount=Decimal("1200.00"),
                currency_code="USD",
            ),
        ]
    )
    await session.flush()
    session.add(
        RFQAward(
            rfq_id=rfq.id,
            bid_id=bid.id,
            awarded_at="2027-01-10T09:00:00+00:00",
            awarded_amount=Decimal("328500.00"),
            awarded_currency="USD",
            method="best_value",
            reason="Best value",
            basis={"weights": [70, 30]},
        )
    )
    await session.flush()
    return rfq


async def _copy(session, **kw):
    return await session.run_sync(lambda s: copy_all(s.connection(), **kw))


async def _mirror(session, source_table: str, source_id) -> BidPackage:
    target = (
        await session.execute(
            select(TenderLegacyMap.target_id).where(
                TenderLegacyMap.source_table == source_table, TenderLegacyMap.source_id == source_id
            )
        )
    ).scalar_one()
    return (
        await session.execute(select(BidPackage).where(BidPackage.id == target).execution_options(**_ALL))
    ).scalar_one()


async def _count(session, model, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for clause in where:
        stmt = stmt.where(clause)
    return (await session.execute(stmt.execution_options(**_ALL))).scalar_one()


async def _submissions(session, package_id) -> list[BidSubmission]:
    inv_ids = select(BidInvitation.id).where(BidInvitation.package_id == package_id)
    rows = await session.execute(
        select(BidSubmission).where(BidSubmission.invitation_id.in_(inv_ids)).execution_options(**_ALL)
    )
    return list(rows.scalars().all())


async def test_a_tender_package_is_copied_with_every_bid_and_its_money(pg_session) -> None:
    project = await _project(pg_session)
    package, bids = await _tender(pg_session, project)
    pg_session.add(
        TenderBidInvitation(
            package_id=package.id,
            company_name="Trockenbau Nord",
            email="bids@trockenbau.test",
            token_hash=uuid.uuid4().hex,
            expires_at=__import__("datetime").datetime(2027, 1, 1, tzinfo=__import__("datetime").UTC),
            bid_id=bids[0].id,
        )
    )
    pg_session.add(
        TenderClarification(
            package_id=package.id,
            number=1,
            question="Fire rating?",
            asked_at=__import__("datetime").datetime(2026, 12, 1, tzinfo=__import__("datetime").UTC),
            answer="EI 30",
        )
    )
    await pg_session.flush()

    report = await _copy(pg_session)
    line = next(p for p in report.packages if p.source_id == str(package.id))
    assert line.outcome == "copied" and line.ok, line.line()

    mirror = await _mirror(pg_session, "oe_tendering_package", package.id)
    assert mirror.legacy_source == "tendering"
    assert mirror.status == "closed"  # evaluating
    assert mirror.code.startswith("TND-")
    assert mirror.tender_id is None  # never a link: the tender award must keep drafting its own contract
    assert mirror.metadata_["legacy"]["source_id"] == str(package.id)

    subs = await _submissions(pg_session, mirror.id)
    assert sorted(str(s.total_amount) for s in subs) == ["148200.00", "151999.99"]
    assert all(s.envelope_payload["legacy_line_items"] for s in subs)
    # Two bill positions became scope lines; the line without a position stays a free line.
    assert await _count(pg_session, BidPackageLineItem, BidPackageLineItem.package_id == mirror.id) == 2
    free = await _count(
        pg_session,
        BidSubmissionLine,
        BidSubmissionLine.submission_id.in_([s.id for s in subs]),
        BidSubmissionLine.line_item_id.is_(None),
    )
    assert free == 2
    # The real portal invitation carries the first bid; the second bid got a synthetic one.
    assert await _count(pg_session, BidInvitation, BidInvitation.package_id == mirror.id) == 2
    assert await _count(pg_session, BidQA, BidQA.package_id == mirror.id) == 1
    # The source is untouched.
    assert await _count(pg_session, TenderBid, TenderBid.package_id == package.id) == 2


async def test_a_second_copy_keeps_ids_and_counts(pg_session) -> None:
    project = await _project(pg_session)
    package, _ = await _tender(pg_session, project)
    await _copy(pg_session)
    mirror = await _mirror(pg_session, "oe_tendering_package", package.id)
    first = sorted(str(s.id) for s in await _submissions(pg_session, mirror.id))
    maps = await _count(pg_session, TenderLegacyMap, TenderLegacyMap.package_id == mirror.id)

    again = await _copy(pg_session, only_unmapped=True)
    assert all(p.source_id != str(package.id) for p in again.packages)
    refreshed = await _copy(pg_session)
    assert next(p for p in refreshed.packages if p.source_id == str(package.id)).outcome == "refreshed"
    assert sorted(str(s.id) for s in await _submissions(pg_session, mirror.id)) == first
    assert await _count(pg_session, TenderLegacyMap, TenderLegacyMap.package_id == mirror.id) == maps
    assert (
        await _count(
            pg_session, BidPackage, BidPackage.legacy_source == "tendering", BidPackage.project_id == project.id
        )
        == 1
    )


async def test_an_rfq_is_copied_as_a_supply_package(pg_session) -> None:
    project = await _project(pg_session)
    taken = BidPackage(project_id=project.id, code="RFQ-2027-001", title="Native", currency="USD")
    pg_session.add(taken)
    await pg_session.flush()
    rfq = await _rfq(pg_session, project)

    await _copy(pg_session)
    mirror = await _mirror(pg_session, "oe_rfq_rfq", rfq.id)
    assert mirror.package_type == "supply"
    assert mirror.status == "open"  # bids_received
    assert mirror.code == "RFQ-RFQ-2027-001"  # the plain number was taken
    assert mirror.evaluation_method == "best_value"
    assert mirror.metadata_["legacy"]["line_notes"]

    lines = (
        (
            await pg_session.execute(
                select(BidPackageLineItem)
                .where(BidPackageLineItem.package_id == mirror.id)
                .order_by(BidPackageLineItem.order_index)
                .execution_options(**_ALL)
            )
        )
        .scalars()
        .all()
    )
    assert [(ln.code, ln.is_mandatory) for ln in lines] == [("03 31 00", True), ("PUMP", False)]

    (sub,) = await _submissions(pg_session, mirror.id)
    assert sub.total_amount == Decimal("328500.00")
    assert sub.validity_days == 45 and sub.open_after_deadline and sub.late_reason == "truck strike"
    priced = (
        (
            await pg_session.execute(
                select(BidSubmissionLine).where(BidSubmissionLine.submission_id == sub.id).execution_options(**_ALL)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(p.inclusion_status for p in priced) == ["excluded", "included", "included"]
    assert [p.description for p in priced if p.line_item_id is None] == ["Winter heating"]
    assert await _count(pg_session, BidSubmissionAdjustment, BidSubmissionAdjustment.submission_id == sub.id) == 1

    award = (
        await pg_session.execute(select(BidAward).where(BidAward.package_id == mirror.id).execution_options(**_ALL))
    ).scalar_one()
    bidder = (
        await pg_session.execute(select(Bidder).where(Bidder.id == award.awarded_bidder_id).execution_options(**_ALL))
    ).scalar_one()
    assert award.awarded_amount == Decimal("328500.00") and award.method == "best_value"
    assert bidder.company_name == "Lone Star Ready Mix"


async def test_a_tender_package_linked_to_a_bid_package_is_mapped_not_copied(pg_session) -> None:
    project = await _project(pg_session)
    package, _ = await _tender(pg_session, project)
    linked = BidPackage(
        project_id=project.id, code=f"BP-{uuid.uuid4().hex[:6]}", title="Linked", currency="EUR", tender_id=package.id
    )
    pg_session.add(linked)
    await pg_session.flush()

    report = await _copy(pg_session)
    assert next(p for p in report.packages if p.source_id == str(package.id)).outcome == "linked"
    target = await _mirror(pg_session, "oe_tendering_package", package.id)
    assert target.id == linked.id
    assert await _count(pg_session, BidPackage, BidPackage.project_id == project.id) == 1


async def test_mirrors_stay_out_of_ordinary_reads(pg_session, mirror_on) -> None:
    project = await _project(pg_session)
    native = BidPackage(project_id=project.id, code=f"BP-{uuid.uuid4().hex[:6]}", title="Native", currency="EUR")
    pg_session.add(native)
    await _tender(pg_session, project)
    await pg_session.flush()
    await _copy(pg_session)

    from app.modules.bid_management.repository import BidPackageRepository

    rows, total = await BidPackageRepository(pg_session).list_for_project(project.id)
    assert [r.id for r in rows] == [native.id]
    assert total == 1
    assert await _count(pg_session, BidPackage, BidPackage.project_id == project.id) == 2
    hidden_bidders = (
        await pg_session.execute(
            select(func.count(Bidder.id))
            .join(BidPackage, Bidder.package_id == BidPackage.id)
            .where(BidPackage.project_id == project.id)
        )
    ).scalar_one()
    assert hidden_bidders == 0


async def test_a_write_to_the_old_module_refreshes_its_mirror_on_commit(pg_session, mirror_on) -> None:
    project = await _project(pg_session)
    package, _ = await _tender(pg_session, project)
    await pg_session.commit()
    mirror = await _mirror(pg_session, "oe_tendering_package", package.id)
    assert len(await _submissions(pg_session, mirror.id)) == 2

    pg_session.add(
        TenderBid(
            package_id=package.id,
            company_name="Late GmbH",
            total_amount="99.10",
            currency="EUR",
            status="pending",
            line_items=[],
        )
    )
    await pg_session.commit()
    assert len(await _submissions(pg_session, mirror.id)) == 3

    from app.modules.tendering.repository import TenderingRepository

    await TenderingRepository(pg_session).update_package_fields(package.id, name="Drywall, phase 2")
    await pg_session.commit()
    assert (await _mirror(pg_session, "oe_tendering_package", package.id)).title == "Drywall, phase 2"

    await pg_session.delete(package)
    await pg_session.commit()
    assert await _count(pg_session, BidPackage, BidPackage.id == mirror.id) == 0
    assert await _count(pg_session, TenderLegacyMap, TenderLegacyMap.package_id == mirror.id) == 0


async def test_a_mirror_cannot_be_edited_through_the_canonical_service(pg_session, mirror_on) -> None:
    from fastapi import HTTPException

    from app.modules.bid_management.schemas import BidPackageUpdate
    from app.modules.bid_management.service import BidManagementService

    project = await _project(pg_session)
    package, _ = await _tender(pg_session, project)
    await pg_session.commit()
    mirror = await _mirror(pg_session, "oe_tendering_package", package.id)
    pg_session.expunge_all()
    with pytest.raises(HTTPException) as err:
        await BidManagementService(pg_session).update_package(mirror.id, BidPackageUpdate(title="Edited"))
    assert err.value.status_code == 404


async def test_one_tender_award_drafts_one_contract_and_no_order_with_the_mirror_on(
    pg_session, mirror_on, monkeypatch
) -> None:
    from app.modules.bid_management import events as bm_events
    from app.modules.bid_management.award_route import CONTRACT, tender_award_route
    from app.modules.contracts.models import Contract
    from app.modules.procurement import events as po_events
    from app.modules.procurement.models import PurchaseOrder

    from .tender_award_fixtures import _NonCommittingSession

    project = await _project(pg_session)
    package, bids = await _tender(
        pg_session, project, status="awarded", metadata={"awarded_bid_id": "", "currency": "EUR"}
    )
    package.metadata_ = {"awarded_bid_id": str(bids[0].id), "currency": "EUR"}
    bids[0].status = "accepted"
    bids[1].status = "rejected"
    await pg_session.commit()

    mirror = await _mirror(pg_session, "oe_tendering_package", package.id)
    assert await _count(pg_session, BidAward, BidAward.package_id == mirror.id) == 1
    assert await _count(pg_session, BidRejection, BidRejection.package_id == mirror.id) == 1
    assert await tender_award_route(pg_session, package) == CONTRACT

    monkeypatch.setattr(bm_events, "async_session_factory", lambda: _NonCommittingSession(pg_session))
    monkeypatch.setattr(po_events, "async_session_factory", lambda: _NonCommittingSession(pg_session))
    event = bm_events.Event(
        name="tendering.package.awarded",
        data={"package_id": str(package.id), "bid_id": str(bids[0].id), "project_id": str(project.id)},
        source_module="oe_tendering",
    )
    await bm_events._draft_contract_from_tender_award(event)
    await po_events._on_tender_awarded(event)

    contracts = await _count(pg_session, Contract, Contract.project_id == project.id)
    orders = await _count(pg_session, PurchaseOrder, PurchaseOrder.project_id == project.id)
    assert (contracts, orders) == (1, 0)


async def test_reconcile_flags_a_copy_that_lost_a_bid(pg_session) -> None:
    project = await _project(pg_session)
    package, _ = await _tender(pg_session, project)
    await _copy(pg_session)
    mirror = await _mirror(pg_session, "oe_tendering_package", package.id)
    victim = (await _submissions(pg_session, mirror.id))[0]
    await pg_session.delete(victim)
    await pg_session.flush()

    report = await pg_session.run_sync(lambda s: reconcile(s.connection()))
    line = next(p for p in report.packages if p.source_id == str(package.id))
    assert not line.ok
    assert line.bids_source == 2 and line.bids_target == 1


async def test_a_failing_package_does_not_stop_the_batch(pg_session, monkeypatch) -> None:
    project = await _project(pg_session)
    good, _ = await _tender(pg_session, project)
    bad, _ = await _tender(pg_session, project)
    original = LegacyCopier.copy_tender_package

    def _boom(self, source_id, *, apply=True):
        if source_id == str(bad.id):
            raise RuntimeError("broken row")
        return original(self, source_id, apply=apply)

    monkeypatch.setattr(LegacyCopier, "copy_tender_package", _boom)
    report = await _copy(pg_session)
    outcomes = {p.source_id: p.outcome for p in report.packages}
    assert outcomes[str(good.id)] == "copied"
    assert outcomes[str(bad.id)] == "failed"
    assert not report.ok


async def test_the_tender_card_reads_a_copy_with_every_tab(pg_session) -> None:
    from app.modules.bid_management.tenders import get_tender, list_tenders

    project = await _project(pg_session)
    package, _ = await _tender(pg_session, project)
    pg_session.add(
        TenderClarification(
            package_id=package.id, number=1, question="Fire rating?", asked_at=datetime(2026, 12, 1, tzinfo=UTC)
        )
    )
    await pg_session.flush()
    await _copy(pg_session)
    owner = str(project.owner_id)

    rows = await list_tenders(
        pg_session,
        owner,
        project_id=project.id,
        kind=None,
        source=None,
        status_filter=None,
        offset=0,
        limit=100,
        _perm=None,
    )
    (row,) = rows
    assert (row.source, row.bid_count, row.lowest_total) == ("tendering", 2, Decimal("148200.00"))

    card = await get_tender(row.id, pg_session, owner, _perm=None)
    assert card.read_only and card.source_id == str(package.id)
    assert (len(card.line_items), len(card.bidders), len(card.submissions)) == (2, 2, 2)
    assert [q.question for q in card.questions] == ["Fire rating?"]


async def test_readers_count_the_copies_with_the_native_tenders(pg_session) -> None:
    from app.core.validation.project_context import _tender_count
    from app.modules.bi_dashboards.kpis import bid_win_rate_kpi

    project = await _project(pg_session)
    package, bids = await _tender(pg_session, project, status="awarded")
    package.metadata_ = {"awarded_bid_id": str(bids[0].id)}
    await pg_session.flush()
    await _rfq(pg_session, project, number=f"RFQ-{uuid.uuid4().hex[:6]}")
    await _copy(pg_session)

    kpi = await bid_win_rate_kpi(pg_session, project_id=project.id)
    assert kpi.breakdown == {"won": 2, "total": 3}  # one award per copy; 2 tender bids + 1 quote
    assert await _tender_count(pg_session, project.id) == 1  # the RFQ is supply, not a trade tender
