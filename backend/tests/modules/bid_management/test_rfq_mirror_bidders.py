"""The tender mirror of a demo RFQ names its bidders and carries the levelled range.

Runs on the PostgreSQL engine the top-level ``tests/conftest.py`` provisions. The demo RFQ
has three quotes from project contacts at factors 1.00, 1.07 and 1.13 of the base rates:
205 500.00, 219 885.00 and 232 215.00 (lowest price wins, no technical weight).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.modules.bid_management import legacy_mirror
from app.modules.bid_management.legacy_copy import copy_all, refresh_stale_rfq_mirrors, stale_rfq_mirrors

pytestmark = pytest.mark.asyncio

_ALL = {legacy_mirror.INCLUDE_MIRRORS: True, "populate_existing": True}
_FIRMS = (("Stahlbau Nord GmbH", "bids@stahlbau-nord.test"), ("Metallbau Ost AG", "angebot@mbost.test"))
_FIRMS += (("Treppen & Gelaender KG", "info@treppen-kg.test"),)


@pytest_asyncio.fixture
async def session():
    import importlib

    from app.database import Base, async_session_factory, engine

    for name in ("users", "projects", "contacts", "subcontractors", "rfq_bidding", "tendering", "bid_management"):
        importlib.import_module(f"app.modules.{name}.models")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as s:
        yield s


async def _seed(session) -> uuid.UUID:
    from app.modules.contacts.models import Contact
    from app.modules.projects.models import Project
    from app.modules.rfq_bidding.models import RFQ
    from app.modules.rfq_bidding.seed import seed_rfq_demo
    from app.modules.users.models import User

    owner = User(email=f"rfqm-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Buyer")
    session.add(owner)
    await session.flush()
    project = Project(name="RFQ mirror", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    for firm, email in _FIRMS:
        session.add(
            Contact(
                contact_type="subcontractor",
                company_name=firm,
                primary_email=email,
                metadata_={"project_id": str(project.id)},
            )
        )
    await session.flush()
    await seed_rfq_demo(session, [project.id])
    await session.commit()
    return (
        await session.execute(select(RFQ.id).where(RFQ.project_id == project.id, RFQ.status == "issued"))
    ).scalar_one()


async def _mirror(session, rfq_id):
    from app.modules.bid_management.models import BidComparison, Bidder, BidPackage, TenderLegacyMap

    target = (
        await session.execute(
            select(TenderLegacyMap.target_id).where(
                TenderLegacyMap.source_table == "oe_rfq_rfq", TenderLegacyMap.source_id == str(rfq_id)
            )
        )
    ).scalar_one()
    pkg = (
        await session.execute(
            select(BidPackage).where(BidPackage.id == uuid.UUID(str(target))).execution_options(**_ALL)
        )
    ).scalar_one()
    bidders = (
        (await session.execute(select(Bidder).where(Bidder.package_id == pkg.id).execution_options(**_ALL)))
        .scalars()
        .all()
    )
    comparison = (
        await session.execute(select(BidComparison).where(BidComparison.package_id == pkg.id).execution_options(**_ALL))
    ).scalar_one()
    return pkg, list(bidders), comparison


def _assert_complete(bidders, comparison) -> None:
    assert sorted((b.company_name, b.contact_email) for b in bidders) == sorted(_FIRMS)
    assert Decimal(comparison.normalized_low) == Decimal("205500.00")
    assert Decimal(comparison.normalized_high) == Decimal("232215.00")
    lowest = next(b for b in bidders if b.company_name == _FIRMS[0][0])
    assert comparison.recommended_bidder_id == lowest.id


async def test_rfq_mirror_names_bidders_from_contacts_and_levels_the_bids(session) -> None:
    rfq_id = await _seed(session)
    await session.run_sync(lambda s: copy_all(s.connection()))
    await session.commit()

    _pkg, bidders, comparison = await _mirror(session, rfq_id)
    _assert_complete(bidders, comparison)


async def test_a_mirror_from_an_earlier_copy_is_repaired_once(session) -> None:
    from app.modules.bid_management.models import BidComparison, Bidder

    rfq_id = await _seed(session)
    await session.run_sync(lambda s: copy_all(s.connection()))
    pkg, _bidders, _comparison = await _mirror(session, rfq_id)
    # What the earlier copy wrote: no firm, no email, an empty comparison header.
    await session.execute(update(Bidder).where(Bidder.package_id == pkg.id).values(company_name="", contact_email=""))
    await session.execute(
        update(BidComparison)
        .where(BidComparison.package_id == pkg.id)
        .values(normalized_low=0, normalized_high=0, recommended_bidder_id=None)
    )
    await session.commit()

    assert str(rfq_id) in await session.run_sync(lambda s: stale_rfq_mirrors(s.connection()))
    assert await session.run_sync(lambda s: refresh_stale_rfq_mirrors(s.connection())) >= 1
    await session.commit()
    _pkg, bidders, comparison = await _mirror(session, rfq_id)
    _assert_complete(bidders, comparison)
    assert str(rfq_id) not in await session.run_sync(lambda s: stale_rfq_mirrors(s.connection()))
