# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the change-provability service (PostgreSQL, py3.12).

Seeds change-family records and checks that the gathered evidence signals map
onto the pure provability engine the way the per-signal docstrings promise: a
timely notice earns full notice credit, a linked instruction earns its signal,
a bare change scores weak with the expected cure list, and a subject is fenced
to its own project (and an unknown kind is rejected).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.claims_evidence.provability import (
    BAND_WEAK,
    WEAKNESS_NO_ACKNOWLEDGEMENT,
    WEAKNESS_NO_DATED_RECORD,
    WEAKNESS_NO_LINKED_INSTRUCTION,
    WEAKNESS_NO_OWNERSHIP_CHAIN,
    WEAKNESS_NOTICE_MISSING,
)
from app.modules.claims_evidence.provability_service import (
    KIND_CHANGE_ORDER,
    KIND_VARIATION_NOTICE,
    SubjectNotFound,
    UnknownSubjectKind,
    score_subject_provability,
)
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from app.modules.variations.models import Notice
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"pv-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Pv",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Pv {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_timely_notice_earns_full_notice_credit(session: AsyncSession) -> None:
    pid = await _project(session)
    served = datetime(2026, 1, 10, tzinfo=UTC)
    due = served + timedelta(days=3)
    notice = Notice(
        project_id=pid,
        code="NOT-T1",
        title="Early warning",
        raised_at=served.isoformat(),
        response_due_date=due.isoformat(),
    )
    session.add(notice)
    await session.flush()

    result = await score_subject_provability(
        session,
        project_id=pid,
        subject_kind=KIND_VARIATION_NOTICE,
        subject_id=notice.id,
    )

    by_signal = {s.signal: s for s in result.score.sub_scores}
    # Served on or before a known due date -> full notice-timeliness credit.
    assert by_signal["notice_timeliness"].fraction == 1.0
    assert by_signal["notice_timeliness"].earned == by_signal["notice_timeliness"].weight
    tokens = {w.token for w in result.score.weaknesses}
    assert WEAKNESS_NOTICE_MISSING not in tokens
    assert result.subject_ref == "NOT-T1"


@pytest.mark.asyncio
async def test_bare_change_scores_weak_with_full_cure_list(session: AsyncSession) -> None:
    pid = await _project(session)
    co = ChangeOrder(project_id=pid, code="CO-W1", title="Scope add", status="submitted")
    session.add(co)
    await session.flush()

    result = await score_subject_provability(
        session,
        project_id=pid,
        subject_kind=KIND_CHANGE_ORDER,
        subject_id=co.id,
    )

    # No notice, no acknowledgement, no instruction, no custody chain and no
    # dated record -> the engine's weak band with every major cure listed.
    assert result.score.band == BAND_WEAK
    tokens = {w.token for w in result.score.weaknesses}
    assert WEAKNESS_NOTICE_MISSING in tokens
    assert WEAKNESS_NO_ACKNOWLEDGEMENT in tokens
    assert WEAKNESS_NO_LINKED_INSTRUCTION in tokens
    assert WEAKNESS_NO_OWNERSHIP_CHAIN in tokens
    assert WEAKNESS_NO_DATED_RECORD in tokens


@pytest.mark.asyncio
async def test_linked_clause_earns_instruction_signal(session: AsyncSession) -> None:
    pid = await _project(session)
    # A change order with an acknowledgement (approved_at) on the record and a
    # linked RFI anchoring it to a basis earns both of those signals. The CO
    # families carry the instruction anchor as a linked RFI rather than a
    # contract clause reference.
    co = ChangeOrder(
        project_id=pid,
        code="CO-L1",
        title="Anchored change",
        status="approved",
        approved_at=datetime(2026, 2, 1, tzinfo=UTC).isoformat(),
        linked_rfi_ids=[str(uuid.uuid4())],
    )
    session.add(co)
    await session.flush()

    result = await score_subject_provability(
        session,
        project_id=pid,
        subject_kind=KIND_CHANGE_ORDER,
        subject_id=co.id,
    )

    by_signal = {s.signal: s for s in result.score.sub_scores}
    assert by_signal["linked_instruction"].fraction == 1.0
    assert by_signal["acknowledgement"].fraction == 1.0
    tokens = {w.token for w in result.score.weaknesses}
    assert WEAKNESS_NO_LINKED_INSTRUCTION not in tokens
    assert WEAKNESS_NO_ACKNOWLEDGEMENT not in tokens


@pytest.mark.asyncio
async def test_present_flag_tracks_full_credit(session: AsyncSession) -> None:
    pid = await _project(session)
    notice = Notice(
        project_id=pid,
        code="NOT-P1",
        title="N",
        raised_at=datetime(2026, 3, 1, tzinfo=UTC).isoformat(),
        response_due_date=datetime(2026, 3, 5, tzinfo=UTC).isoformat(),
    )
    session.add(notice)
    await session.flush()

    result = await score_subject_provability(
        session,
        project_id=pid,
        subject_kind=KIND_VARIATION_NOTICE,
        subject_id=notice.id,
    )

    # A fully satisfied signal reconstructs its weight exactly; a UI "present"
    # flag is just earned >= weight, which the router derives from these.
    for s in result.score.sub_scores:
        fully = s.earned >= s.weight
        assert (s.fraction == 1.0) == fully


@pytest.mark.asyncio
async def test_subject_is_fenced_to_project(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    theirs = ChangeOrder(project_id=other, code="CO-X", title="Theirs", status="submitted")
    session.add(theirs)
    await session.flush()

    # Asking for another project's subject id under my project is "not found"
    # so the endpoint never leaks the existence of their record.
    with pytest.raises(SubjectNotFound):
        await score_subject_provability(
            session,
            project_id=pid,
            subject_kind=KIND_CHANGE_ORDER,
            subject_id=theirs.id,
        )


@pytest.mark.asyncio
async def test_unknown_kind_is_rejected(session: AsyncSession) -> None:
    pid = await _project(session)
    with pytest.raises(UnknownSubjectKind):
        await score_subject_provability(
            session,
            project_id=pid,
            subject_kind="not_a_change_family",
            subject_id=uuid.uuid4(),
        )
