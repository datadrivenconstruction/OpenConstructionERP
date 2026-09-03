# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The compare column when a supplier replied WITHOUT a document.

"No quote document received" in the document slot beside a reply that DID
arrive read as "nothing came". The column must carry the reply itself -
the formatted original when the sweep kept one (metadata source_html,
sanitised on write) - so the panel can put the email where the document
would have been.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

RFQ_FIELDS = {
    "Package": "Distribution boards",
    "Delivery to": "12 Site Rd, Wetherill Park",
    "Site contact": "Alex Example 0400 000 000",
    "Delivery window / site hours": "Site hours 06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2099-01-01",
}


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"cmp-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CMP",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"CMP {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="AUD",
        project_code=f"C{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_a_docless_reply_hands_its_email_to_the_column(session: AsyncSession) -> None:
    from app.modules.contacts.models import Contact
    from app.modules.correspondence.models import Correspondence
    from app.modules.register_workflow import comparing, emailing, service

    pid = await _project(session)
    supplier = Contact(
        contact_type="supplier",
        company_name="Northbank Electrical",
        primary_email="sam@northbank.example",
    )
    session.add(supplier)
    await session.flush()

    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfq",
        title="Boards",
        fields=RFQ_FIELDS,
        recipient_contact_ids=[str(supplier.id)],
    )
    built = await emailing.build_item_email(session, item, contact_id=str(supplier.id))
    await emailing.record_send(
        session,
        item,
        contact_id=str(supplier.id),
        contact_name="Northbank Electrical",
        subject=built["subject"],
        channel="outlook",
        user_id="u1",
        email_ref="REG-MSG-000001",
    )

    row = Correspondence(
        project_id=pid,
        reference_number="COR-777",
        direction="incoming",
        subject=f"RE: {item.reference}",
        from_contact_id=str(supplier.id),
        to_contact_ids=[],
        correspondence_type="email",
        notes="Happy to help. Total $9,350.00 ex GST",
        status="received",
        metadata_={
            "register_item_id": str(item.id),
            # What the inbox sweep stores: already sanitised on write.
            "source_html": "<table><tr><td><b>Total $9,350.00</b></td></tr></table>",
        },
    )
    session.add(row)
    await session.flush()

    out = await comparing.quotes_side_by_side(session, item)
    col = next(c for c in out["columns"] if c["name"] == "Northbank Electrical")
    assert col["documents"] == [], "this reply carried no attachment"
    assert col["reply_body"], "the plain text must still be there as the fallback"
    assert "<b>Total $9,350.00</b>" in (col["reply_html"] or ""), (
        "the formatted original never reached the column - the panel has "
        "nothing to show where the document would have been"
    )
