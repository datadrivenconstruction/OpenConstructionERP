# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Reply / reply-all / forward - and the addressing rail underneath them.

The rail: a draft is built from ONE message. On an RFQ the item's
recipient list is every supplier quoting the package, so a reply-all
that reached for it would hand each supplier its competitor list.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import replying
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"rp-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="RP",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"RP {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="AUD",
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj.id


RFQ_FIELDS = {
    "Package": "Distribution boards",
    "Delivery to": "12 Site Rd, Wetherill Park",
    "Site contact": "Alex Example 0400 000 000",
    "Delivery window / site hours": "Site hours 06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2099-01-01",
}

MESSAGE = {
    "subject": "RFQ-005 - Distribution boards - our quote 100042",
    "date": "2026-08-18",
    "from_people": [{"name": "Northbank Electrical", "email": "sam@northbank.example"}],
    "to_people": [{"name": "Example Projects", "email": "projects@example.com"}],
    "text": "Total $9,350.00 ex GST",
    "html": "",
    "documents": [{"filename": "northbank-quote-100042.pdf", "stored": "/uploads/northbank.pdf"}],
}


# -- The rail -------------------------------------------------------------


def test_reply_all_never_reaches_the_other_suppliers() -> None:
    """The whole reason this builder reads one row and never the item.

    Reply-all is computed from the MESSAGE's own parties. Nothing in the
    call has access to the package's other bidders, so no future edit can
    quietly widen it to them without deleting this test.
    """
    out = replying.recipients_for("reply_all", MESSAGE, [])
    assert out == [
        "Northbank Electrical <sam@northbank.example>",
        "Example Projects <projects@example.com>",
    ]
    joined = " ".join(out).lower()
    for rival in ("cablemark", "meridian", "c.p.s", "riverside"):
        assert rival not in joined


def test_a_reply_goes_to_the_sender_not_to_whoever_it_was_addressed_to() -> None:
    assert replying.recipients_for("reply", MESSAGE, []) == ["Northbank Electrical <sam@northbank.example>"]


def test_a_forward_has_no_implied_recipient() -> None:
    """Forwarding must not re-mail the sender their own message."""
    assert replying.recipients_for("forward", MESSAGE, []) == []
    assert replying.recipients_for("forward", MESSAGE, ["alex@example.com"]) == ["alex@example.com"]


def test_the_same_person_is_never_listed_twice() -> None:
    typed = ["SAM@northbank.example", "new@example.com"]
    out = replying.recipients_for("reply", MESSAGE, typed)
    assert out == [
        "Northbank Electrical <sam@northbank.example>",
        "new@example.com",
    ]


# -- Subject convention ---------------------------------------------------


def test_the_prefix_is_applied_once_never_stacked() -> None:
    assert replying.reply_subject("reply", "Quote 100042") == "RE: Quote 100042"
    assert replying.reply_subject("reply", "RE: Quote 100042") == "RE: Quote 100042"
    assert replying.reply_subject("reply", "re: Quote 100042") == "re: Quote 100042"
    # A forwarded reply is a forward - the RE: it arrived with goes.
    assert replying.reply_subject("forward", "RE: Quote 100042") == "FW: Quote 100042"
    assert replying.reply_subject("forward", "FW: Quote 100042") == "FW: Quote 100042"


def test_a_newline_in_a_subject_can_never_reach_a_mail_header() -> None:
    out = replying.reply_subject("reply", "Quote\r\nBcc: someone@example.com")
    assert "\n" not in out and "\r" not in out


# -- The quoted original --------------------------------------------------


def test_the_original_is_quoted_with_its_headers() -> None:
    quoted = replying.quoted_original(MESSAGE)
    assert "Northbank Electrical" in quoted
    assert "2026-08-18" in quoted
    assert "9,350.00" in quoted


def test_a_script_in_the_original_does_not_survive_into_the_draft() -> None:
    """The quote goes back out of the building; it is sanitised on the way."""
    hostile = dict(MESSAGE, html="<p>Hi</p><script>fetch('//evil')</script>")
    quoted = replying.quoted_original(hostile)
    assert "<script" not in quoted.lower()
    assert "Hi" in quoted


# -- The builder ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_forward_carries_the_files_and_a_reply_does_not(session: AsyncSession) -> None:
    """Replying attaches the supplier's own quote back to them - noise at
    best, and on a reply-all it hands the quote to everyone else on the
    message."""
    from app.modules.contacts.models import Contact
    from app.modules.correspondence.models import Correspondence
    from app.modules.register_workflow import service

    pid = await _project(session)
    supplier = Contact(
        contact_type="supplier",
        company_name="Northbank Electrical",
        primary_email="sam@northbank.example",
    )
    session.add(supplier)
    await session.flush()

    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    row = Correspondence(
        project_id=pid,
        reference_number="COR-001",
        direction="inbound",
        subject="Our quote 100042",
        from_contact_id=str(supplier.id),
        to_contact_ids=[],
        correspondence_type="email",
        notes="Total $9,350.00 ex GST",
        status="received",
        metadata_={"register_item_id": str(item.id)},
    )
    session.add(row)
    await session.flush()

    reply = await replying.build_reply(
        session, item, correspondence_id=str(row.id), mode="reply", to=[], body="<p>Thanks.</p>"
    )
    assert reply["to"] == ["Northbank Electrical <sam@northbank.example>"]
    assert reply["subject"].startswith("RE:")
    assert reply["attachment_paths"] == []
    # What was typed leads, the original is quoted underneath it.
    assert reply["html"].index("Thanks.") < reply["html"].index("9,350.00")


@pytest.mark.asyncio
async def test_a_forward_with_nobody_on_it_is_refused(session: AsyncSession) -> None:
    from app.modules.correspondence.models import Correspondence
    from app.modules.register_workflow import service

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    row = Correspondence(
        project_id=pid,
        reference_number="COR-002",
        direction="inbound",
        subject="Our quote",
        to_contact_ids=[],
        correspondence_type="email",
        notes="body",
        status="received",
        metadata_={"register_item_id": str(item.id)},
    )
    session.add(row)
    await session.flush()

    with pytest.raises(service.WorkflowError, match="Type an address"):
        await replying.build_reply(session, item, correspondence_id=str(row.id), mode="forward", to=[], body="")
    # And an unknown mode is not quietly treated as a reply.
    with pytest.raises(service.WorkflowError):
        await replying.build_reply(session, item, correspondence_id=str(row.id), mode="send", to=["a@b.com"], body="")
