"""The demo RFQ register: one package with three comparable quotes, one draft."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact
from app.modules.projects.models import Project
from app.modules.rfq_bidding.models import RFQ, RFQBid
from app.modules.rfq_bidding.seed import seed_rfq_demo
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio
OWNER = uuid.UUID("00000000-0000-4000-8000-00000000f13e")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def test_project_gets_two_rfqs_and_three_quotes(session: AsyncSession) -> None:
    project = Project(id=uuid.uuid4(), name="Demo", currency="GBP", status="active", owner_id=OWNER)
    session.add(project)
    for n in range(3):
        session.add(
            Contact(
                id=uuid.uuid4(),
                contact_type="subcontractor",
                company_name=f"Firm {n}",
                metadata_={"project_id": str(project.id)},
            )
        )
    await session.flush()

    first = await seed_rfq_demo(session, [project.id])
    assert (first["rfqs"], first["bids"]) == (2, 3)
    rfqs = (await session.execute(select(RFQ).where(RFQ.project_id == project.id))).scalars().all()
    assert {r.status for r in rfqs} == {"issued", "draft"}
    assert {r.currency_code for r in rfqs} == {"GBP"}
    bids = (await session.execute(select(RFQBid))).scalars().all()
    amounts = sorted(Decimal(b.bid_amount) for b in bids)
    assert amounts[0] > 0 and amounts[0] < amounts[-1]

    assert (await seed_rfq_demo(session, [project.id]))["rfqs"] == 0
