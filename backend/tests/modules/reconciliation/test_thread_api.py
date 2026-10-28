# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for event reconciliation (PostgreSQL, py3.12).

Exercises the persistence + gather layer end to end on real PostgreSQL: gathering
a project's heterogeneous records, scoring them with the pure engine into an
assembled cross-channel thread, the confirm / reject decision round-trip
(including that a rejected link is cut from the thread), and that both the thread
and the persisted decisions are fenced to one project (IDOR-safe).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.correspondence.models import Correspondence
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.reconciliation.correlate import (
    DEFAULT_THRESHOLD,
    W_SUBJECT,
    find_links,
)
from app.modules.reconciliation.models import (
    STATUS_CONFIRMED,
    STATUS_REJECTED,
    RecordLink,
)
from app.modules.reconciliation.service import (
    TYPE_CHANGE_ORDER,
    TYPE_CORRESPONDENCE,
    build_event_thread,
    decide_record_link,
    get_record_link,
    list_record_links,
)
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, *, currency: str = "USD") -> uuid.UUID:
    user = User(
        email=f"rec-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="REC",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"REC {uuid.uuid4().hex[:6]}", owner_id=user.id, currency=currency)
    session.add(proj)
    await session.flush()
    return proj.id


async def _change_order(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    code: str,
    title: str = "Relocate the site access gate",
) -> uuid.UUID:
    co = ChangeOrder(
        project_id=project_id,
        code=code,
        title=title,
        description="Owner instruction to relocate the access gate.",
        submitted_at="2026-05-30T10:00:00+00:00",
    )
    session.add(co)
    await session.flush()
    return co.id


async def _correspondence(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    reference_number: str,
    subject: str,
) -> uuid.UUID:
    cor = Correspondence(
        project_id=project_id,
        reference_number=reference_number,
        direction="incoming",
        subject=subject,
        correspondence_type="letter",
        date_sent="2026-05-31",
    )
    session.add(cor)
    await session.flush()
    return cor.id


@pytest.mark.asyncio
async def test_thread_links_change_order_and_correspondence(session: AsyncSession) -> None:
    """A shared tracked code stitches a change order and a letter into one thread."""
    pid = await _project(session)
    co_id = await _change_order(session, pid, code="CO-14")
    # The letter cites CO-14 in its subject, so the engine's shared-reference
    # signal (alone enough to clear the threshold) links the two records.
    cor_id = await _correspondence(
        session,
        pid,
        reference_number="COR-001",
        subject="Re: CO-14 relocate access gate",
    )

    thread = await build_event_thread(session, pid, f"{TYPE_CHANGE_ORDER}:{co_id}")

    # The seed resolved to the change order row.
    assert thread.seed_type == TYPE_CHANGE_ORDER
    assert thread.seed_id == str(co_id)

    endpoints = {(tr.record.record_type, tr.record.record_id) for tr in thread.records}
    assert (TYPE_CHANGE_ORDER, str(co_id)) in endpoints
    assert (TYPE_CORRESPONDENCE, str(cor_id)) in endpoints

    # Exactly one scored link, on the shared reference, still only a suggestion.
    assert len(thread.links) == 1
    # A ThreadLink is the decision state wrapped AROUND the scored link, so the
    # score and its reasons live one level down, on ``.link`` - which is how the
    # router reads them too. ``status`` and ``link_id`` are the wrapper's own.
    scored = thread.links[0]
    assert "shared_reference" in scored.link.reasons
    assert scored.link.confidence >= 0.5
    assert scored.status == "suggested"
    assert scored.link_id is None
    assert thread.confirmed_count == 0
    assert thread.rejected_count == 0

    # The seed record is flagged.
    seeds = [tr for tr in thread.records if tr.is_seed]
    assert len(seeds) == 1
    assert seeds[0].record.record_id == str(co_id)


@pytest.mark.asyncio
async def test_thread_by_subject_key(session: AsyncSession) -> None:
    """A normalized-subject key gathers same-subject records with no single seed."""
    pid = await _project(session)
    co_id = await _change_order(session, pid, code="CO-20", title="Temporary works design")
    cor_id = await _correspondence(
        session,
        pid,
        reference_number="COR-010",
        subject="Fwd: Temporary works design",
    )

    # No "type:id" -> interpreted as a subject key matching both records.
    thread = await build_event_thread(session, pid, "Temporary works design")

    assert thread.seed_type is None
    assert thread.seed_id is None
    endpoints = {(tr.record.record_type, tr.record.record_id) for tr in thread.records}
    assert (TYPE_CHANGE_ORDER, str(co_id)) in endpoints
    assert (TYPE_CORRESPONDENCE, str(cor_id)) in endpoints
    # Gathering is one thing, asserting a link is another. These two records
    # share a normalized subject and nothing else, and a bare subject match is
    # deliberately calibrated below the bar: W_SUBJECT is under
    # DEFAULT_THRESHOLD so a shared subject line alone never claims a link -
    # it has to combine with a second signal. So the thread carries none.
    assert W_SUBJECT < DEFAULT_THRESHOLD
    assert thread.links == []
    # The signal is still live, which is the half worth proving: score the same
    # gathered records at the subject weight and subject_match is what fires.
    scored = find_links([tr.record for tr in thread.records], threshold=W_SUBJECT)
    assert any("subject_match" in link.reasons for link in scored)


@pytest.mark.asyncio
async def test_confirm_round_trip(session: AsyncSession) -> None:
    """Confirming a suggested link persists it and surfaces in the thread."""
    pid = await _project(session)
    co_id = await _change_order(session, pid, code="CO-14")
    cor_id = await _correspondence(
        session,
        pid,
        reference_number="COR-001",
        subject="Re: CO-14 relocate access gate",
    )

    row = await decide_record_link(
        session,
        pid,
        left=(TYPE_CHANGE_ORDER, str(co_id)),
        right=(TYPE_CORRESPONDENCE, str(cor_id)),
        relation="same_event",
        status=STATUS_CONFIRMED,
        confidence=0.6,
    )
    assert row.status == STATUS_CONFIRMED
    assert row.confidence == Decimal("0.6000")

    # The decision is reflected in the assembled thread.
    thread = await build_event_thread(session, pid, f"{TYPE_CHANGE_ORDER}:{co_id}")
    assert thread.confirmed_count == 1
    assert len(thread.links) == 1
    link = thread.links[0]
    assert link.status == STATUS_CONFIRMED
    assert link.link_id == str(row.id)


@pytest.mark.asyncio
async def test_decide_is_idempotent_upsert(session: AsyncSession) -> None:
    """Re-deciding the same link updates the one row rather than duplicating it."""
    pid = await _project(session)
    co_id = await _change_order(session, pid, code="CO-14")
    cor_id = await _correspondence(
        session,
        pid,
        reference_number="COR-001",
        subject="Re: CO-14",
    )
    left = (TYPE_CHANGE_ORDER, str(co_id))
    right = (TYPE_CORRESPONDENCE, str(cor_id))

    first = await decide_record_link(
        session, pid, left=left, right=right, relation="same_event", status=STATUS_CONFIRMED
    )
    # Re-decide with the endpoints in the OTHER order: still the same canonical
    # link, so the same row is updated.
    second = await decide_record_link(
        session, pid, left=right, right=left, relation="same_event", status=STATUS_REJECTED
    )
    assert first.id == second.id
    assert second.status == STATUS_REJECTED
    rows = await list_record_links(session, pid)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_rejected_link_is_cut_from_thread(session: AsyncSession) -> None:
    """A rejected link no longer stitches its endpoints into the seed's thread."""
    pid = await _project(session)
    co_id = await _change_order(session, pid, code="CO-14")
    cor_id = await _correspondence(
        session,
        pid,
        reference_number="COR-001",
        subject="Re: CO-14 relocate access gate",
    )
    await decide_record_link(
        session,
        pid,
        left=(TYPE_CHANGE_ORDER, str(co_id)),
        right=(TYPE_CORRESPONDENCE, str(cor_id)),
        relation="same_event",
        status=STATUS_REJECTED,
    )

    thread = await build_event_thread(session, pid, f"{TYPE_CHANGE_ORDER}:{co_id}")
    # Only the lone seed remains; the rejected link did not pull in the letter.
    endpoints = {(tr.record.record_type, tr.record.record_id) for tr in thread.records}
    assert endpoints == {(TYPE_CHANGE_ORDER, str(co_id))}
    assert thread.links == []


@pytest.mark.asyncio
async def test_decide_invalid_status_raises(session: AsyncSession) -> None:
    """A status outside confirmed / rejected is rejected with ValueError (-> 422)."""
    pid = await _project(session)
    co_id = await _change_order(session, pid, code="CO-14")
    with pytest.raises(ValueError):
        await decide_record_link(
            session,
            pid,
            left=(TYPE_CHANGE_ORDER, str(co_id)),
            right=(TYPE_CORRESPONDENCE, str(uuid.uuid4())),
            relation="same_event",
            status="maybe",
        )


@pytest.mark.asyncio
async def test_links_and_thread_scoped_to_project(session: AsyncSession) -> None:
    """A decision and a thread are fenced to their project (IDOR defence)."""
    pid = await _project(session)
    other = await _project(session)
    co_id = await _change_order(session, pid, code="CO-14")
    cor_id = await _correspondence(
        session,
        pid,
        reference_number="COR-001",
        subject="Re: CO-14 relocate access gate",
    )
    left = (TYPE_CHANGE_ORDER, str(co_id))
    right = (TYPE_CORRESPONDENCE, str(cor_id))
    await decide_record_link(session, pid, left=left, right=right, relation="same_event", status=STATUS_CONFIRMED)

    # The same link read under another project returns nothing.
    assert await get_record_link(session, other, left, right, "same_event") is None
    assert await list_record_links(session, other) == []

    # The other project's thread for the same seed key sees neither the records
    # (they belong to pid) nor the decision - it is empty.
    other_thread = await build_event_thread(session, other, f"{TYPE_CHANGE_ORDER}:{co_id}")
    assert other_thread.records == []
    assert other_thread.links == []
    assert other_thread.confirmed_count == 0


@pytest.mark.asyncio
async def test_unknown_event_key_yields_empty_thread(session: AsyncSession) -> None:
    """A seed key matching no record yields an empty, well-formed thread."""
    pid = await _project(session)
    await _change_order(session, pid, code="CO-14")
    thread = await build_event_thread(session, pid, f"{TYPE_CHANGE_ORDER}:{uuid.uuid4()}")
    assert thread.records == []
    assert thread.links == []
    # A "type:id" key that matches nothing reports no resolved seed.
    assert thread.seed_type is None
    assert thread.seed_id is None


@pytest.mark.asyncio
async def test_decision_persisted_row_shape(session: AsyncSession) -> None:
    """A persisted decision carries the canonical endpoints and creator."""
    pid = await _project(session)
    co_id = await _change_order(session, pid, code="CO-14")
    cor_id = await _correspondence(session, pid, reference_number="COR-001", subject="Re: CO-14")
    row = await decide_record_link(
        session,
        pid,
        left=(TYPE_CORRESPONDENCE, str(cor_id)),  # deliberately non-canonical order
        right=(TYPE_CHANGE_ORDER, str(co_id)),
        relation="same_event",
        status=STATUS_CONFIRMED,
        created_by="user-123",
    )
    assert isinstance(row, RecordLink)
    # change_order < correspondence, so the change order is stored as the left.
    assert (row.left_type, row.left_id) == (TYPE_CHANGE_ORDER, str(co_id))
    assert (row.right_type, row.right_id) == (TYPE_CORRESPONDENCE, str(cor_id))
    assert row.created_by == "user-123"
    assert row.project_id == pid
