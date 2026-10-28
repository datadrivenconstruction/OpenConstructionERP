# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the coordination and correspondence-digest co-pilots.

PostgreSQL, py3.12. Seeds change-family records and correspondence directly and
drives the two services that feed the pure :mod:`coordination` and
:mod:`thread_digest` engines, checking urgency ranking and the awaiting verdict
against a fixed clock.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.change_intelligence.service import (
    build_comms_digest_for_project,
    build_coordination_plan,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.correspondence.models import Correspondence
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session

NOW = datetime(2026, 6, 24, tzinfo=UTC)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"cc-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CC",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"CC {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_coordination_ranks_by_urgency(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            ChangeOrder(
                project_id=pid,
                code="CO-OVERDUE",
                title="Overdue",
                status="submitted",
                ball_in_court="alice",
                response_due_date="2026-06-20",
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-SOON",
                title="Due soon",
                status="submitted",
                ball_in_court="bob",
                response_due_date="2026-06-25",
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-UPCOMING",
                title="Upcoming",
                status="submitted",
                ball_in_court="carol",
                response_due_date="2026-07-30",
            ),
            ChangeOrder(
                project_id=pid,
                code="CO-NODATE",
                title="No date",
                status="submitted",
                ball_in_court="dave",
            ),
            # Closed - excluded from the plan entirely.
            ChangeOrder(project_id=pid, code="CO-DONE", title="Done", status="executed"),
        ]
    )
    await session.flush()

    plan = await build_coordination_plan(session, pid, now=NOW)

    assert plan.total == 4
    assert plan.overdue_count == 1
    assert plan.due_soon_count == 1
    # Bands order overdue, then due soon, then upcoming, then no date.
    assert [s.urgency for s in plan.steps] == ["overdue", "due_soon", "upcoming", "no_date"]
    assert [s.recommended_action for s in plan.steps] == ["escalate", "nudge", "review", "await"]
    assert plan.steps[0].ball_in_court == "alice"


@pytest.mark.asyncio
async def test_comms_digest_awaiting(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add_all(
        [
            # Thread A: their letter, then our reply -> ball with them.
            Correspondence(
                project_id=pid,
                reference_number="COR-1",
                direction="incoming",
                subject="Site access",
                correspondence_type="letter",
                from_contact_id="ext",
                date_sent="2026-06-20",
            ),
            Correspondence(
                project_id=pid,
                reference_number="COR-2",
                direction="outgoing",
                subject="Re: Site access",
                correspondence_type="letter",
                from_contact_id="us",
                date_sent="2026-06-21",
            ),
            # Thread B: their query, unanswered -> ball with us.
            Correspondence(
                project_id=pid,
                reference_number="COR-3",
                direction="incoming",
                subject="Invoice query",
                correspondence_type="email",
                from_contact_id="ext",
                date_sent="2026-06-22",
            ),
            # Thread C: informational notice, no reply needed -> closed.
            Correspondence(
                project_id=pid,
                reference_number="COR-4",
                direction="outgoing",
                subject="Notice of completion",
                correspondence_type="letter",
                from_contact_id="us",
                date_sent="2026-06-19",
                metadata_={"requires_reply": False},
            ),
        ]
    )
    await session.flush()

    digest = await build_comms_digest_for_project(session, pid, now=NOW)

    assert digest.thread_count == 3
    assert digest.open_count == 2
    assert digest.awaiting_us_count == 1

    by_subject = {t.subject.lower(): t for t in digest.threads}
    # The reply chain folds into one thread keyed by the normalized subject.
    assert by_subject["site access"].message_count == 2
    assert by_subject["site access"].awaiting == "them"
    assert by_subject["invoice query"].awaiting == "us"
    assert by_subject["notice of completion"].is_open is False


@pytest.mark.asyncio
async def test_coordination_empty_when_all_closed(session: AsyncSession) -> None:
    pid = await _project(session)
    session.add(ChangeOrder(project_id=pid, code="CO-X", title="Closed", status="executed"))
    await session.flush()

    plan = await build_coordination_plan(session, pid, now=NOW)
    assert plan.total == 0
    assert plan.steps == ()
