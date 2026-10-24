# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Menu badge counts: what each badge counts, and whose projects it may count.

The access part is the one that matters: a project id the caller cannot open
answers 404 exactly like a missing one, and the unscoped call never counts
another person's project.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.nav_badges import compute_nav_badges, parse_deadline, tender_due_days
from app.modules.dashboard.router import get_nav_badges
from app.modules.finance.models import Invoice
from app.modules.ncr.models import NCR
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.rfi.models import RFI
from app.modules.tasks.models import Task
from app.modules.tendering.models import TenderPackage
from app.modules.users.models import User
from tests._pg import transactional_session

TODAY = date(2026, 10, 24)


def test_parse_deadline_reads_dates_and_timestamps() -> None:
    assert parse_deadline("2026-10-25") == date(2026, 10, 25)
    assert parse_deadline("2026-10-25T17:00:00Z") == date(2026, 10, 25)
    assert parse_deadline("next Friday") is None
    assert parse_deadline(None) is None


def test_tender_due_window_counts_today_to_two_days_ahead() -> None:
    due, nearest = tender_due_days(["2026-10-23", "2026-10-25", "2026-10-26", "2026-10-27", "soon", None], TODAY)
    assert (due, nearest) == (2, 1)
    assert tender_due_days([], TODAY) == (0, None)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, tag: str) -> User:
    user = User(
        email=f"badge-{tag}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Badge",
        role="estimator",
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_project(session: AsyncSession, owner: User) -> Project:
    proj = Project(name=f"Badges {uuid.uuid4().hex[:6]}", owner_id=owner.id)
    session.add(proj)
    await session.flush()
    pid = proj.id
    session.add_all(
        [
            Invoice(
                project_id=pid,
                invoice_direction="payable",
                invoice_number="INV-1",
                invoice_date="2026-10-01",
                status="pending",
            ),
            Invoice(
                project_id=pid,
                invoice_direction="payable",
                invoice_number="INV-2",
                invoice_date="2026-10-01",
                status="paid",
            ),
            RFI(project_id=pid, rfi_number="RFI-1", subject="s", question="q", raised_by=owner.id, status="open"),
            RFI(project_id=pid, rfi_number="RFI-2", subject="s", question="q", raised_by=owner.id, status="closed"),
            PunchItem(project_id=pid, title="p1", status="open"),
            PunchItem(project_id=pid, title="p2", status="in_progress"),
            PunchItem(project_id=pid, title="p3", status="closed"),
            NCR(
                project_id=pid,
                ncr_number="NCR-1",
                title="n",
                description="d",
                ncr_type="material",
                severity="minor",
                status="identified",
            ),
            Task(project_id=pid, task_type="task", title="mine", status="open", responsible_id=owner.id),
            Task(project_id=pid, task_type="task", title="done", status="completed", responsible_id=owner.id),
            TenderPackage(project_id=pid, name="Shell", status="issued", deadline="2026-10-25"),
            TenderPackage(project_id=pid, name="Late", status="issued", deadline="2026-12-01"),
        ]
    )
    await session.flush()
    return proj


@pytest.mark.asyncio
async def test_counts_per_badge(session: AsyncSession) -> None:
    owner = await _user(session, "own")
    proj = await _seed_project(session, owner)

    badges = await compute_nav_badges(session, {proj.id}, str(owner.id), today=TODAY)

    assert badges["/finance"] == {"count": 1, "kind": "awaiting", "tone": "warning"}
    assert badges["/rfi"]["count"] == 1
    assert badges["/punchlist"]["count"] == 2
    assert badges["/ncr"]["count"] == 1
    assert badges["/issues"]["count"] == 4
    assert badges["/tasks"]["count"] == 1
    assert badges["/tendering"] == {"count": 1, "kind": "due", "tone": "warning", "due_in_days": 1}


@pytest.mark.asyncio
async def test_zero_counts_are_left_out(session: AsyncSession) -> None:
    owner = await _user(session, "empty")
    proj = Project(name="Empty", owner_id=owner.id)
    session.add(proj)
    await session.flush()
    assert await compute_nav_badges(session, {proj.id}, str(owner.id), today=TODAY) == {}
    assert await compute_nav_badges(session, set(), str(owner.id), today=TODAY) == {}


@pytest.mark.asyncio
async def test_foreign_project_answers_404(session: AsyncSession) -> None:
    owner = await _user(session, "owner")
    stranger = await _user(session, "stranger")
    proj = await _seed_project(session, owner)

    with pytest.raises(HTTPException) as caught:
        await get_nav_badges(user_id=str(stranger.id), session=session, project_id=proj.id)
    assert caught.value.status_code == 404

    with pytest.raises(HTTPException) as missing:
        await get_nav_badges(user_id=str(stranger.id), session=session, project_id=uuid.uuid4())
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_unscoped_call_counts_only_own_projects(session: AsyncSession) -> None:
    owner = await _user(session, "a")
    stranger = await _user(session, "b")
    await _seed_project(session, owner)

    theirs = await get_nav_badges(user_id=str(stranger.id), session=session, project_id=None)
    assert theirs == {"project_id": None, "badges": {}}

    mine = await get_nav_badges(user_id=str(owner.id), session=session, project_id=None)
    assert mine["badges"]["/issues"]["count"] == 4
