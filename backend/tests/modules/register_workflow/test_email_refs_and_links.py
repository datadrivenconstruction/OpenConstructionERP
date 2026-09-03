# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Per-email identifiers and cross-links.

The email ref is the document-control discipline: every mail carries ITS OWN
number, stamped on the document and logged, so "what was REG-MSG-000042"
has exactly one answer six weeks later. Links are what an item is
CONNECTED to - reciprocal for item↔item, refused for anything that
would render as an executable link.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import emailing, linking, service
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"el-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="EL",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"EL {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="AUD",
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj.id


RFQ_FIELDS = {
    "Package": "Switchboards",
    "Delivery to": "12 Site Rd",
    "Site contact": "Alex Example",
    "Delivery window / site hours": "06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2099-01-01",
}


# ── Email refs ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_email_gets_its_own_number(session: AsyncSession) -> None:
    a = await service.next_email_reference(session)
    b = await service.next_email_reference(session)
    assert a == "REG-MSG-000001"
    assert b == "REG-MSG-000002"
    assert a != b


@pytest.mark.asyncio
async def test_peeking_never_burns_an_email_number(session: AsyncSession) -> None:
    peek1 = await service.peek_email_reference(session)
    peek2 = await service.peek_email_reference(session)
    assert peek1 == peek2
    minted = await service.next_email_reference(session)
    assert minted == peek1, "the preview promised a different number to the one minted"


@pytest.mark.asyncio
async def test_the_ref_is_on_the_email_and_in_the_log(session: AsyncSession) -> None:
    """Stamped on the document AND logged - an identifier only one side
    knows about identifies nothing."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    ref = await service.next_email_reference(session)
    built = await emailing.build_item_email(session, item, contact_id=None, email_ref=ref)
    assert ref in built["html"], "the email does not show its own number"
    assert built["email_ref"] == ref

    await emailing.record_send(
        session,
        item,
        contact_id=None,
        contact_name="Alpha",
        subject=built["subject"],
        channel="outlook",
        user_id="u1",
        email_ref=ref,
    )
    log = emailing.send_log(item)
    assert log and log[-1]["email_ref"] == ref


@pytest.mark.asyncio
async def test_a_reply_quoting_only_the_email_ref_files_onto_the_item(
    session: AsyncSession,
) -> None:
    from app.modules.correspondence.models import Correspondence
    from app.modules.register_workflow import tracking

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    ref = await service.next_email_reference(session)
    await emailing.record_send(
        session,
        item,
        contact_id=None,
        contact_name="Alpha",
        subject="RFQ",
        channel="outlook",
        user_id="u1",
        email_ref=ref,
    )
    session.add(
        Correspondence(
            project_id=pid,
            reference_number="COR-100",
            direction="incoming",
            subject=f"RE: your {ref}",  # ONLY the mail number, not the item ref
            to_contact_ids=[],
            correspondence_type="email",
            notes="see attached",
            status="received",
        )
    )
    await session.flush()
    replies = await tracking._replies_for(session, item)
    assert any(r.subject == f"RE: your {ref}" for r in replies)


# ── Links ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_item_link_lands_on_both_ends(session: AsyncSession) -> None:
    pid = await _project(session)
    rfq = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    rfi = await service.raise_item(session, project_id=pid, kind="rfi", title="Grid?", fields={})

    links = await linking.add_link(session, rfq, link_type="item", value=rfi.reference)
    assert any(x["reference"] == rfi.reference for x in links)
    # The far end shows this one without being asked.
    back = linking.links_of(rfi)
    assert any(x["reference"] == rfq.reference for x in back)


@pytest.mark.asyncio
async def test_removing_a_link_takes_the_reciprocal_with_it(session: AsyncSession) -> None:
    """A one-way "linked" is a broken promise on the far end."""
    pid = await _project(session)
    rfq = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    rfi = await service.raise_item(session, project_id=pid, kind="rfi", title="Grid?", fields={})
    await linking.add_link(session, rfq, link_type="item", value=rfi.reference)

    await linking.remove_link(session, rfq, index=0)
    assert linking.links_of(rfq) == []
    assert linking.links_of(rfi) == []


@pytest.mark.asyncio
async def test_a_link_cannot_reach_another_project(session: AsyncSession) -> None:
    """A typo'd reference must not stitch two clients' jobs together."""
    mine = await _project(session)
    theirs = await _project(session)
    other = await service.raise_item(session, project_id=theirs, kind="rfi", title="X", fields={})
    item = await service.raise_item(session, project_id=mine, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    with pytest.raises(service.WorkflowError, match="No item on this job"):
        await linking.add_link(session, item, link_type="item", value=other.reference)


@pytest.mark.asyncio
async def test_a_hostile_url_is_refused(session: AsyncSession) -> None:
    """The link renders as clickable on everyone's screen."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    with pytest.raises(service.WorkflowError, match="http"):
        await linking.add_link(session, item, link_type="url", value="javascript:alert(1)")


@pytest.mark.asyncio
async def test_cost_centre_and_deliverable_links_hold(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    await linking.add_link(session, item, link_type="cost_centre", value="CC-1204 Electrical")
    links = await linking.add_link(session, item, link_type="deliverable", value="MSB room fit-off")
    assert [x["type"] for x in links] == ["cost_centre", "deliverable"]


@pytest.mark.asyncio
async def test_an_edit_cannot_forge_the_links(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    await service.update_item(
        session,
        item,
        fields=dict(RFQ_FIELDS, _links=[{"type": "item", "label": "forged", "target_id": "x"}]),
    )
    assert linking.links_of(item) == []


@pytest.mark.asyncio
async def test_responsible_and_the_court_both_reach_the_email(
    session: AsyncSession,
) -> None:
    """The person answering for this item, and whose desk it sits on, are
    both ON the document.

    Both used to be card-only, so a supplier reading an RFI could not see
    whose name to answer to or who was holding it up. Neither is money and
    neither is a competitor's position, so both are ordinary fields now.
    """
    pid = await _project(session)
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Earth bar detail",
        fields={"Question": "Which detail applies?", "Responsible": "Sam Rivera", "Ball in court": "Site engineer"},
    )
    built = await emailing.build_item_email(session, item, contact_id=None)
    assert "Sam Rivera" in built["html"], "Responsible is missing from the email"
    # Ball in court is emailed too now - A deliberate call, 19 Aug: the reader
    # should be able to see whose desk it is on without asking.
    assert "Ball in court" in built["html"], "the court assignment is missing from the email"
    assert "Site engineer" in built["html"], "the court assignment is missing from the email"


@pytest.mark.asyncio
async def test_the_court_assignment_rides_the_payload(session: AsyncSession) -> None:
    """Assigning a court must be readable by every surface.

    The derived us/them still drives the tracking maths; the named
    assignment is carried beside it rather than overwriting it, so the
    counters keep meaning what they meant.
    """
    pid = await _project(session)
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Q",
        fields={"Responsible": "Sam Rivera", "Ball in court": "Denver Building Control"},
    )
    payload = await service.item_payload_enriched(session, item)
    assert payload["ball_in_court_name"] == "Denver Building Control"
    assert payload["responsible"] == "Sam Rivera"
    assert payload["ball_in_court"] in ("us", "them")


@pytest.mark.asyncio
async def test_the_send_log_keeps_the_document_it_sent(session: AsyncSession) -> None:
    """What went out is kept verbatim, not rebuilt on demand.

    Regenerating the body from today's fields would show a document the
    supplier was never sent the moment anything on the item is corrected -
    and the whole point of a mail record is settling what was actually
    said. Drop the ``html`` on record_send and this fails.
    """
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    built = await emailing.build_item_email(session, item, contact_id=None)
    await emailing.record_send(
        session,
        item,
        contact_id=None,
        contact_name="Alpha",
        subject=built["subject"],
        channel="outlook",
        user_id="u1",
        email_ref="REG-MSG-000001",
        html=built["html"],
    )
    kept = emailing.send_log(item)[-1]["html"]
    assert kept == built["html"], "the sent document was not kept"

    # The item moves on - the record must not move with it.
    fields = dict(item.fields)
    fields["Package"] = "Something else entirely"
    item.fields = fields
    await session.flush()
    assert emailing.send_log(item)[-1]["html"] == built["html"], "the record was rewritten by a later edit"


@pytest.mark.asyncio
async def test_a_send_logged_after_the_fact_claims_no_document(
    session: AsyncSession,
) -> None:
    """Mail sent from somebody's own Outlook has no body here.

    An empty string is the honest answer; inventing one would put words
    in an email we never composed.
    """
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    await emailing.record_send(
        session,
        item,
        contact_id=None,
        contact_name="Alpha",
        subject="Sent from my phone",
        channel="manual",
        user_id="u1",
    )
    assert emailing.send_log(item)[-1]["html"] == ""
