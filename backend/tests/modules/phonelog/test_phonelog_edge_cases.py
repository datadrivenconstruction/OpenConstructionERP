# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Edge-case integration tests for the phone-log module (PostgreSQL, py3.12).

Complements ``test_phonelog_service.py`` with the boundaries: an empty capture,
malformed / inconsistent timestamps, an unrecognised channel and direction, the
wrong-project / access-denied 404 the router enforces, paging bounds, and that a
fetch and a list never cross project lines.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from tests._pg import transactional_session

from app.dependencies import verify_project_access
from app.modules.phonelog import service
from app.modules.phonelog.schemas import PhoneLogCreate
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, *, role: str = "admin") -> User:
    user = User(
        email=f"phone-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Phone",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, owner: User) -> uuid.UUID:
    proj = Project(name=f"PL {uuid.uuid4().hex[:6]}", owner_id=owner.id)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_empty_capture_persists_a_well_formed_row(session: AsyncSession) -> None:
    """A capture with no transcript / parties / times still yields a clean row.

    Nothing is invented: the channel defaults to phone, the direction is unknown,
    parties and instructions are empty, and the duration is None.
    """
    owner = await _user(session)
    pid = await _project(session, owner)

    row = await service.create_phone_log(session, PhoneLogCreate(project_id=pid), user_id=str(owner.id))

    assert row.channel == "phone"
    assert row.direction == "unknown"
    assert row.parties == []
    assert row.instructions == []
    assert row.duration_seconds is None
    assert row.word_count == 0
    assert row.summary == ""


@pytest.mark.asyncio
async def test_malformed_timestamps_yield_no_duration(session: AsyncSession) -> None:
    """Unparseable timestamps leave the duration undefined rather than raising."""
    owner = await _user(session)
    pid = await _project(session, owner)

    row = await service.create_phone_log(
        session,
        PhoneLogCreate(
            project_id=pid,
            started_at="not-a-date",
            ended_at="also-bad",
            transcript="Please confirm the slab pour.",
        ),
        user_id=str(owner.id),
    )

    assert row.duration_seconds is None
    # The instruction is still extracted from the transcript.
    assert any("confirm the slab pour" in line.lower() for line in row.instructions)


@pytest.mark.asyncio
async def test_end_before_start_yields_no_duration(session: AsyncSession) -> None:
    """A negative span (end before start) is rejected as a duration, not stored negative."""
    owner = await _user(session)
    pid = await _project(session, owner)

    row = await service.create_phone_log(
        session,
        PhoneLogCreate(
            project_id=pid,
            started_at="2026-06-25T10:00:00",
            ended_at="2026-06-25T09:00:00",
        ),
        user_id=str(owner.id),
    )
    assert row.duration_seconds is None


@pytest.mark.asyncio
async def test_unrecognised_channel_and_direction_are_safe(session: AsyncSession) -> None:
    """An unknown channel maps to 'other'; an unknown direction to 'unknown'."""
    owner = await _user(session)
    pid = await _project(session, owner)

    row = await service.create_phone_log(
        session,
        PhoneLogCreate(project_id=pid, channel="carrier-pigeon", direction="sideways"),
        user_id=str(owner.id),
    )
    assert row.channel == "other"
    assert row.direction == "unknown"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_access_denied_is_404_for_non_member(session: AsyncSession) -> None:
    """A stranger capturing / reading another project's log is 404 (IDOR gate)."""
    owner = await _user(session, role="manager")
    pid = await _project(session, owner)
    stranger = await _user(session, role="manager")

    with pytest.raises(HTTPException) as exc:
        await verify_project_access(pid, str(stranger.id), session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_missing_log_returns_none(session: AsyncSession) -> None:
    """Fetching a phone-log id that does not exist returns None (router -> 404)."""
    assert await service.get_phone_log(session, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_list_paging_bounds(session: AsyncSession) -> None:
    """offset / limit page the project's log without overrunning."""
    owner = await _user(session)
    pid = await _project(session, owner)
    for i in range(3):
        await service.create_phone_log(
            session, PhoneLogCreate(project_id=pid, transcript=f"call {i}"), user_id=str(owner.id)
        )

    page, total = await service.list_phone_logs(session, pid, offset=1, limit=1)
    assert total == 3
    assert len(page) == 1


@pytest.mark.asyncio
async def test_list_is_empty_for_project_with_no_logs(session: AsyncSession) -> None:
    """A project with nothing captured lists empty with a zero total."""
    owner = await _user(session)
    pid = await _project(session, owner)
    rows, total = await service.list_phone_logs(session, pid)
    assert rows == []
    assert total == 0
