# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the phone-log capture service (#23).

PostgreSQL, py3.12. ``create_phone_log`` runs the pure ``phonelog.normalize``
engine and persists a canonical row; these tests seed real projects and assert
the stored record (direction, channel, parties, duration, summary, instructions,
word_count, occurred_at) plus list scoping / filtering / ordering and single-row
fetch, and that the router's response mapping round-trips the row.

Under tests/modules (the single non-sharded job) so adding them never reshuffles
the pytest-split unit shards.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from tests._pg import transactional_session

from app.modules.phonelog import service
from app.modules.phonelog.router import _to_response
from app.modules.phonelog.schemas import PhoneLogCreate, PhoneLogResponse
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _owner(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"phone-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Phone",
        role="admin",
    )
    session.add(user)
    await session.flush()
    return user.id


async def _project(session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    proj = Project(name=f"PL {uuid.uuid4().hex[:6]}", owner_id=owner_id)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_create_normalizes_and_persists(session: AsyncSession) -> None:
    """A raw capture is normalized into a canonical, dispute-ready row."""
    owner = await _owner(session)
    pid = await _project(session, owner)

    row = await service.create_phone_log(
        session,
        PhoneLogCreate(
            project_id=pid,
            # Arrow + comma split, and a case-insensitive duplicate of the first name.
            raw_parties="John Doe -> Acme site office, john doe",
            direction="incoming",
            channel="",  # blank -> phone
            started_at="2026-06-25T09:00:00",
            ended_at="2026-06-25T09:05:00",
            transcript="Morning. Please change the door schedule to fire-rated.",
            summary="",
        ),
        user_id=str(owner),
    )

    assert row.direction == "inbound"
    assert row.channel == "phone"
    # The duplicate "john doe" is dropped; the first spelling is kept, order preserved.
    assert row.parties == ["John Doe", "Acme site office"]
    assert row.duration_seconds == 300
    assert row.occurred_at == "2026-06-25T09:00:00"
    # No explicit summary -> first sentence of the transcript.
    assert row.summary == "Morning"
    assert any("change the door schedule" in line.lower() for line in row.instructions)
    assert row.word_count == len(row.transcript.split())
    assert row.created_by == str(owner)
    assert row.status == "logged"


@pytest.mark.asyncio
async def test_explicit_duration_wins_over_timestamps(session: AsyncSession) -> None:
    """An explicit duration is trusted and never recomputed from the timestamps."""
    owner = await _owner(session)
    pid = await _project(session, owner)

    row = await service.create_phone_log(
        session,
        PhoneLogCreate(
            project_id=pid,
            duration_seconds=42,
            started_at="2026-06-25T09:00:00",
            ended_at="2026-06-25T09:05:00",
            channel="voice",
            direction="out",
        ),
        user_id=str(owner),
    )

    assert row.duration_seconds == 42
    assert row.channel == "voice_note"
    assert row.direction == "outbound"


@pytest.mark.asyncio
async def test_explicit_summary_is_kept(session: AsyncSession) -> None:
    """An explicit human summary wins over the transcript-derived one."""
    owner = await _owner(session)
    pid = await _project(session, owner)

    row = await service.create_phone_log(
        session,
        PhoneLogCreate(
            project_id=pid,
            transcript="A long rambling call about many things that should not be the summary.",
            summary="Agreed to revise the slab pour date.",
        ),
        user_id=str(owner),
    )

    assert row.summary == "Agreed to revise the slab pour date."


@pytest.mark.asyncio
async def test_list_is_project_scoped_and_newest_first(session: AsyncSession) -> None:
    """A project's log shows only its own rows, newest first."""
    owner = await _owner(session)
    pid_a = await _project(session, owner)
    pid_b = await _project(session, owner)

    first = await service.create_phone_log(
        session, PhoneLogCreate(project_id=pid_a, transcript="first"), user_id=str(owner)
    )
    second = await service.create_phone_log(
        session, PhoneLogCreate(project_id=pid_a, transcript="second"), user_id=str(owner)
    )
    await service.create_phone_log(session, PhoneLogCreate(project_id=pid_b, transcript="other"), user_id=str(owner))

    rows, total = await service.list_phone_logs(session, pid_a)
    assert total == 2
    ids = [r.id for r in rows]
    assert set(ids) == {first.id, second.id}
    # created_at desc: the most recently created row comes first.
    assert ids[0] == second.id


@pytest.mark.asyncio
async def test_list_filters_by_direction_and_channel(session: AsyncSession) -> None:
    """The direction and channel filters narrow the project's log."""
    owner = await _owner(session)
    pid = await _project(session, owner)

    await service.create_phone_log(
        session, PhoneLogCreate(project_id=pid, direction="incoming", channel="phone"), user_id=str(owner)
    )
    await service.create_phone_log(
        session, PhoneLogCreate(project_id=pid, direction="outgoing", channel="voice"), user_id=str(owner)
    )

    outbound, outbound_total = await service.list_phone_logs(session, pid, direction="outbound")
    assert outbound_total == 1
    assert outbound[0].channel == "voice_note"

    voice, voice_total = await service.list_phone_logs(session, pid, channel="voice_note")
    assert voice_total == 1
    assert voice[0].direction == "outbound"


@pytest.mark.asyncio
async def test_get_returns_row_or_none(session: AsyncSession) -> None:
    """get_phone_log returns the row by id, or None when it does not exist."""
    owner = await _owner(session)
    pid = await _project(session, owner)
    row = await service.create_phone_log(session, PhoneLogCreate(project_id=pid, transcript="hi"), user_id=str(owner))

    found = await service.get_phone_log(session, row.id)
    assert found is not None
    assert found.id == row.id

    missing = await service.get_phone_log(session, uuid.uuid4())
    assert missing is None


@pytest.mark.asyncio
async def test_response_mapping_round_trips(session: AsyncSession) -> None:
    """The router's _to_response builds a valid PhoneLogResponse from a row."""
    owner = await _owner(session)
    pid = await _project(session, owner)
    row = await service.create_phone_log(
        session,
        PhoneLogCreate(
            project_id=pid,
            raw_parties=["Site engineer", "Subcontractor"],
            transcript="Please confirm the rebar spacing before the pour.",
        ),
        user_id=str(owner),
    )

    out = _to_response(row)
    assert isinstance(out, PhoneLogResponse)
    assert out.id == row.id
    assert out.project_id == pid
    assert out.parties == ["Site engineer", "Subcontractor"]
    assert any("confirm the rebar spacing" in line.lower() for line in out.instructions)
    assert out.metadata == {}
