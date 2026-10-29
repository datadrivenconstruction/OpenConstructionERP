# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The party backfill on PostgreSQL: a clear match is linked, a doubtful one waits, a rerun changes nothing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.contacts.models import Contact, PartyLinkReview
from app.modules.contacts.parties import backfill
from app.modules.projects.models import Project
from app.modules.tendering.models import TenderBidInvitation, TenderPackage
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"parties-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


def _invitation(package_id, company: str, email: str) -> TenderBidInvitation:
    return TenderBidInvitation(
        id=uuid.uuid4(),
        package_id=package_id,
        recipient_id=uuid.uuid4().hex,
        company_name=company,
        email=email,
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(days=7),
        created_by=str(OWNER_ID),
    )


async def test_backfill_is_idempotent_and_never_merges(session):
    tag = uuid.uuid4().hex[:6]
    project = Project(id=uuid.uuid4(), name=f"P {tag}", owner_id=OWNER_ID, currency="EUR", status="active")
    session.add(project)
    await session.flush()
    package = TenderPackage(id=uuid.uuid4(), project_id=project.id, name=f"Pkg {tag}")
    session.add(package)
    by_mail = Contact(
        id=uuid.uuid4(),
        contact_type="subcontractor",
        company_name="Mail Co",
        primary_email=f"m-{tag}@x.test",
        is_active=True,
        created_by=str(OWNER_ID),
    )
    by_name = Contact(
        id=uuid.uuid4(),
        contact_type="subcontractor",
        company_name=f"Name Co {tag}",
        is_active=True,
        created_by=str(OWNER_ID),
    )
    session.add_all([by_mail, by_name])
    await session.flush()
    clear = _invitation(package.id, "Other spelling", f"M-{tag}@x.test")
    doubtful = _invitation(package.id, f"name co {tag}", f"n-{tag}@x.test")
    unknown = _invitation(package.id, "Nobody", f"z-{tag}@x.test")
    session.add_all([clear, doubtful, unknown])
    await session.flush()

    first = await backfill(session, actor_id=str(OWNER_ID), entity_types={"tender_invitation"})
    assert first["tender_invitation"] == {"linked": 1, "queued": 1, "unmatched": 1}
    assert clear.contact_id == by_mail.id and clear.contact_match_method == "email"
    assert doubtful.contact_id is None and unknown.contact_id is None

    second = await backfill(session, actor_id=str(OWNER_ID), entity_types={"tender_invitation"})
    assert second["tender_invitation"]["linked"] == 0
    reviews = (await session.execute(select(func.count()).select_from(PartyLinkReview))).scalar_one()
    assert reviews == 1
    assert await session.get(Contact, by_mail.id) is not None and await session.get(Contact, by_name.id) is not None
