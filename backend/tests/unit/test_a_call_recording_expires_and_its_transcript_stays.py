# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A call recording expires after the retention window; its transcript stays.

Recordings were stored with no time limit. They now expire after
``OE_PHONELOG_AUDIO_RETENTION_DAYS`` (default 90): the object is deleted from
storage and the row's key cleared, while the phone log and transcript remain.
``0`` turns expiry off.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.phonelog import retention
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


class _Storage:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.deleted: list[str] = []
        self.failing = failing or set()

    async def delete(self, key: str) -> None:
        if key in self.failing:
            raise OSError("unreachable")
        self.deleted.append(key)


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _log(session: AsyncSession, *, age_days: int, key: str) -> uuid.UUID:
    from app.modules.phonelog.models import PhoneLog
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(email=f"pl-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="U")
    session.add(user)
    await session.flush()
    project = Project(name="Calls", owner_id=user.id)
    session.add(project)
    await session.flush()
    row = PhoneLog(project_id=project.id, transcript="hello", audio_storage_key=key)
    session.add(row)
    await session.flush()
    row.created_at = datetime.now(UTC) - timedelta(days=age_days)
    await session.flush()
    return row.id


async def _key_of(session: AsyncSession, row_id: uuid.UUID) -> str:
    from app.modules.phonelog.models import PhoneLog

    row = await session.get(PhoneLog, row_id)
    assert row is not None
    assert row.transcript == "hello"
    return row.audio_storage_key


async def test_an_old_recording_is_deleted_and_a_recent_one_kept(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = _Storage()
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: storage)
    old = await _log(session, age_days=120, key="phonelog/a/old.mp3")
    recent = await _log(session, age_days=10, key="phonelog/a/new.mp3")

    removed = await retention.prune_expired_recordings(session, retention_days=90)

    assert removed == 1
    assert storage.deleted == ["phonelog/a/old.mp3"]
    assert await _key_of(session, old) == ""
    assert await _key_of(session, recent) == "phonelog/a/new.mp3"


async def test_a_failed_delete_keeps_the_key_for_the_next_sweep(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = _Storage(failing={"phonelog/a/stuck.mp3"})
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: storage)
    stuck = await _log(session, age_days=200, key="phonelog/a/stuck.mp3")

    assert await retention.prune_expired_recordings(session, retention_days=90) == 0
    assert await _key_of(session, stuck) == "phonelog/a/stuck.mp3"


async def test_zero_days_keeps_every_recording(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _Storage()
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: storage)
    await _log(session, age_days=1000, key="phonelog/a/ancient.mp3")

    assert await retention.prune_expired_recordings(session, retention_days=0) == 0
    assert storage.deleted == []


@pytest.mark.parametrize(("value", "days"), [(None, 90), ("30", 30), ("0", 0), ("-5", 0), ("soon", 90)])
async def test_the_window_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, value: str | None, days: int
) -> None:
    if value is None:
        monkeypatch.delenv("OE_PHONELOG_AUDIO_RETENTION_DAYS", raising=False)
    else:
        monkeypatch.setenv("OE_PHONELOG_AUDIO_RETENTION_DAYS", value)

    assert retention.audio_retention_days() == days
