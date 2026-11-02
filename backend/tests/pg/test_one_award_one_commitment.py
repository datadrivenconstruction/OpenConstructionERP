# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG data guard: one award becomes exactly one commitment.

Every award subscriber (the contract draft, the purchase order draft, the
subcontract agreement) is run for the same award, and the cost position must
show the awarded amount once. A subcontract package yields the contract twin
plus the agreement that carries the commitment and no order; a supply package
yields the order and no contract. An approved subcontract change then moves
the same commitment by its amount, once.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.bid_management.models import Bidder, BidPackage, BidPackageLineItem
from app.modules.contracts.models import Contract
from app.modules.finance.cost_position import load_cost_position
from app.modules.notifications import _wave5_cross_module_subscribers as w5
from app.modules.procurement import events as proc_events
from app.modules.procurement.models import PurchaseOrder
from app.modules.projects.models import Project
from app.modules.subcontractors.award_bridge import agreement_from_award
from app.modules.subcontractors.change_chain import SubcontractChangeCreate, SubcontractChangeService
from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

AWARD = Decimal("95000.00")


class _NonCommittingSession:
    """The real session with ``commit`` demoted to ``flush``, so the test can roll back."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def commit(self) -> None:
        await self._inner.flush()

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _NonCommittingSession:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False


async def _world(session, package_type: str) -> tuple[Project, BidPackage, Bidder]:
    owner = User(email=f"one-award-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Owner")
    session.add(owner)
    await session.flush()
    project = Project(name="One award", owner_id=owner.id)
    session.add(project)
    await session.flush()
    package = BidPackage(
        project_id=project.id,
        code=f"BP-{uuid.uuid4().hex[:8]}",
        title="Concrete",
        currency="EUR",
        status="awarded",
        package_type=package_type,
    )
    session.add(package)
    await session.flush()
    session.add(BidPackageLineItem(package_id=package.id, code="C.01", description="Slab", unit="m3", quantity="100"))
    sub = Subcontractor(legal_name="Rheinbeton GmbH")
    session.add(sub)
    await session.flush()
    bidder = Bidder(package_id=package.id, company_name="Rheinbeton", status="active", subcontractor_id=sub.id)
    session.add(bidder)
    await session.flush()
    return project, package, bidder


async def _award(session, monkeypatch, package: BidPackage, bidder: Bidder) -> list[dict]:
    """Run every award subscriber for one award; return the events they publish."""
    published: list[dict] = []
    factory = lambda: _NonCommittingSession(session)  # noqa: E731
    monkeypatch.setattr(w5, "async_session_factory", factory)
    monkeypatch.setattr(proc_events, "async_session_factory", factory)
    monkeypatch.setattr(w5.event_bus, "publish_detached", lambda name, data, **_kw: published.append(data))
    event = w5.Event(
        name="bid_management.package.awarded",
        data={
            "package_id": str(package.id),
            "project_id": str(package.project_id),
            "awarded_bidder_id": str(bidder.id),
            "awarded_amount": str(AWARD),
            "currency": "EUR",
        },
        source_module="bid_management",
    )
    for _ in range(2):  # a replayed award must change nothing
        await w5._on_bid_package_awarded(event)
        await proc_events._create_po_from_bid_award(event)
        for drafted in list(published):
            await agreement_from_award(
                session,
                contract_id=uuid.UUID(drafted["contract_id"]),
                package_id=package.id,
                bidder_id=bidder.id,
            )
    return published


async def _rows(session, model, project_id):
    return list((await session.execute(select(model).where(model.project_id == project_id))).scalars().all())


async def _go_live(session, project_id) -> None:
    for model in (Contract, SubcontractAgreement):
        for row in await _rows(session, model, project_id):
            row.status = "active"
    for po in await _rows(session, PurchaseOrder, project_id):
        po.status = "approved"
    await session.flush()


async def test_a_subcontract_award_commits_once_through_the_agreement(pg_session, monkeypatch) -> None:
    project, package, bidder = await _world(pg_session, "subcontract")
    await _award(pg_session, monkeypatch, package, bidder)

    contracts = await _rows(pg_session, Contract, project.id)
    agreements = await _rows(pg_session, SubcontractAgreement, project.id)
    assert await _rows(pg_session, PurchaseOrder, project.id) == []
    assert len(contracts) == 1 and len(agreements) == 1
    assert agreements[0].contract_id == contracts[0].id
    assert agreements[0].metadata_["bid_package_id"] == str(package.id)

    await _go_live(pg_session, project.id)
    position = await load_cost_position(pg_session, project_id=project.id)
    assert position.committed.get("EUR") == AWARD, position.committed

    change = await SubcontractChangeService(pg_session).create(
        SubcontractChangeCreate(agreement_id=agreements[0].id, title="Extra slab", amount=Decimal("2500.00"))
    )
    svc = SubcontractChangeService(pg_session)
    await svc.transition(change.id, "submitted")
    await svc.transition(change.id, "approved")
    await svc.transition(change.id, "approved")
    position = await load_cost_position(pg_session, project_id=project.id)
    assert position.committed.get("EUR") == AWARD + Decimal("2500.00"), position.committed


async def test_a_supply_award_commits_once_through_the_order(pg_session, monkeypatch) -> None:
    project, package, bidder = await _world(pg_session, "supply")
    published = await _award(pg_session, monkeypatch, package, bidder)

    assert published == []
    assert await _rows(pg_session, Contract, project.id) == []
    assert await _rows(pg_session, SubcontractAgreement, project.id) == []
    assert len(await _rows(pg_session, PurchaseOrder, project.id)) == 1
