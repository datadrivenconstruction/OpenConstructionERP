# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Adversarial pass over what was built today.

Written to BREAK the new code, not to confirm it: the supplier ranking,
the reference counter, the reply builder, field memory, the notification
sweep, editing, and adding a decision to a live workflow.

Each test names the consequence, because "it returned the wrong list" is
not a reason to keep a test and "a competitor learned who you buy from"
is.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import ranking, replying, service
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, name: str = "", code: str = "24188") -> uuid.UUID:
    user = User(
        email=f"st-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="ST",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=name or f"ST {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="AUD", project_code=code)
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


# ── The supplier ranking ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_ranking_does_not_name_another_jobs_suppliers(
    session: AsyncSession,
) -> None:
    """Who you buy from is commercially sensitive.

    "Recent" was written to reach ACROSS projects on the reasoning that a
    supplier used last week on another job is a better guess than one
    never used. That reasoning is fine for one company on one deployment
    and wrong the moment two do not share a client list: the ranking
    answers with contact ids, and the browser then fetches those contacts
    by id, so asking about MY project tells me who is on YOURS.
    """
    theirs = await _project(session, "SECRET CLIENT - their job")
    mine = await _project(session, "My job", code="24190")

    from app.modules.contacts.models import Contact

    secret = Contact(
        contact_type="supplier",
        company_name="Their Exclusive Supplier",
        primary_email="secret@example.com",
    )
    session.add(secret)
    await session.flush()

    await service.raise_item(
        session,
        project_id=theirs,
        kind="rfq",
        title="Their package",
        fields=RFQ_FIELDS,
        recipient_contact_ids=[str(secret.id)],
    )

    out = await ranking.ranking_for(session, project_id=mine, kind="rfq")
    assert str(secret.id) not in out["tiers"], "the ranking on MY project named a supplier only used on somebody else's"


@pytest.mark.asyncio
async def test_the_ranking_still_promotes_this_jobs_own_suppliers(
    session: AsyncSession,
) -> None:
    """The feature has to survive the fix - a ranking that ranks nothing
    is just an alphabetical list with extra steps."""
    from app.modules.contacts.models import Contact

    pid = await _project(session)
    used = Contact(contact_type="supplier", company_name="On This Job", primary_email="a@example.com")
    session.add(used)
    await session.flush()
    await service.raise_item(
        session,
        project_id=pid,
        kind="rfq",
        title="P",
        fields=RFQ_FIELDS,
        recipient_contact_ids=[str(used.id)],
    )

    out = await ranking.ranking_for(session, project_id=pid, kind="rfq")
    # PROMOTED - the specific tier is not the point and pinning it makes
    # this test fail every time the tiers are re-ordered. Here it earns
    # the most specific one going: it is who the last RFQ on this job
    # actually went to.
    tier = out["tiers"][str(used.id)]["tier"]
    assert tier < ranking.TIER_NONE
    assert tier == ranking.TIER_LAST_ON_KIND


# ── The reply builder ────────────────────────────────────────────────────


def test_a_display_name_cannot_smuggle_a_second_recipient() -> None:
    """A contact's NAME is user-typed and lands in an address list.

    "Dave <dave@x>, spy@evil" as a company name would add a recipient
    that nothing on screen ever showed.
    """
    hostile = {
        "from_people": [{"name": "Northbank, spy@evil.example <hidden@evil.example>", "email": "w@ok.example"}],
        "to_people": [],
    }
    out = replying.recipients_for("reply", hostile, [])
    joined = " ".join(out)
    # Whatever it renders, the ADDRESS it resolves to is the real one.
    assert "w@ok.example" in joined
    assert len(out) == 1, f"one sender became {len(out)} recipients: {out}"


def test_a_reply_subject_cannot_carry_a_header_break() -> None:
    for bad in ("A\r\nBcc: x@evil", "A\nBcc: x@evil", "A\rBcc: x@evil"):
        out = replying.reply_subject("reply", bad)
        assert "\n" not in out and "\r" not in out


def test_the_quoted_original_escapes_the_headers_it_prints() -> None:
    """The From line is attacker-controlled text going into HTML."""
    msg = {
        "from_people": [{"name": "<img src=x onerror=alert(1)>", "email": "a@b.example"}],
        "to_people": [],
        "subject": "<script>alert(2)</script>",
        "date": "2026-08-19",
        "text": "hi",
        "html": "",
    }
    quoted = replying.quoted_original(msg)
    assert "<img" not in quoted
    assert "<script" not in quoted.lower()


# ── The reference counter ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_hostile_legacy_reference_cannot_derail_the_counter(
    session: AsyncSession,
) -> None:
    """The seed reads references already in the table. A row carrying an
    absurd number would push the counter somewhere it cannot come back
    from, and every future reference on that prefix inherits it."""
    from app.modules.register_workflow.models import RegisterItem

    pid = await _project(session)
    session.add(RegisterItem(project_id=pid, kind="rfq", reference="RFQ-99999999", title="Odd", fields={}))
    await session.flush()
    nxt = await service._next_reference(session, pid, "rfq")
    # An absurd LEGACY number can no longer derail anything: it carries no
    # job, so it never seeds a job's series. What used to push this prefix
    # to 100000000 for every job on the books now cannot move 24188 at all.
    assert nxt.startswith("REG-RFQ-")
    assert nxt == "REG-RFQ-24188-0001"


@pytest.mark.asyncio
async def test_a_reference_from_another_prefix_does_not_move_this_series(
    session: AsyncSession,
) -> None:
    from app.modules.register_workflow.models import RegisterItem

    pid = await _project(session)
    session.add(RegisterItem(project_id=pid, kind="rfi", reference="RFI-000500", title="X", fields={}))
    await session.flush()
    assert await service._next_reference(session, pid, "rfq") == "REG-RFQ-24188-0001"


# ── Adding a decision ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_branch_cannot_be_used_to_smuggle_unbounded_data(
    session: AsyncSession,
) -> None:
    """``branches`` is a free-shape JSON dict straight off the request and
    into a column read on every render of the item."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    huge = {f"branch-{i}": [f"step-{j}" for j in range(50)] for i in range(200)}
    with pytest.raises(service.WorkflowError):
        await service.add_step(session, item.id, name="Which way?", step_type="route", branches=huge)


# ── Editing ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_edit_cannot_forge_the_attachment_list(session: AsyncSession) -> None:
    """``_attachments`` names files that ride the email. Forging it points
    the mailer at a path the person never uploaded."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="P", fields=RFQ_FIELDS)
    await service.update_item(
        session,
        item,
        fields=dict(
            RFQ_FIELDS,
            _attachments=[{"filename": "../../../../etc/passwd", "email": True}],
        ),
    )
    assert not (item.fields or {}).get("_attachments")
