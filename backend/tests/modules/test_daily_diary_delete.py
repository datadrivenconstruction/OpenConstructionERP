# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""W22 audit follow-up — diary delete happy-path + immutability gate.

The W22 sweep flagged ``daily_diary.delete_diary`` as orphan: the
backend endpoint and service method existed, the frontend exposed
``deleteDiary(id)`` in api.ts, but no UI surface was wired and no test
exercised the full create → delete → 404 round trip.

This module pins the contract:

1. **Happy path** — an open diary can be deleted by a user holding
   ``daily_diary.delete``; the service runs cleanly and a subsequent
   ``get_diary`` raises 404 (``diary_not_found``). Mirrors the
   ``DELETE /diaries/{id}`` → 204 + GET → 404 sequence the new UI
   confirm-dialog exercises.

2. **Sealed-immutable** — once signed (or archived) the same call
   surfaces 409 with the structured ``diary_signed_immutable`` code,
   matching the rest of the daily-diary write-gate (parity with
   ``update_diary`` / ``create_entry`` / ``register_photo``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.daily_diary.models import (
    DailyDiary,
    DiaryArchiveSignature,
    DiaryEntry,
    DiaryPhoto,
    DiaryVideo,
    DroneSurvey,
    RealityCaptureDataset,
    WeatherRecord,
)
from app.modules.daily_diary.schemas import DailyDiaryCreate
from app.modules.daily_diary.service import DailyDiaryService

# Import projects + users so the FK targets exist when create_all runs.
from app.modules.projects.models import Project  # noqa: F401
from app.modules.users.models import User  # noqa: F401

_DD_TABLES = [
    Project.__table__,
    User.__table__,
    DailyDiary.__table__,
    WeatherRecord.__table__,
    DiaryEntry.__table__,
    DiaryPhoto.__table__,
    DiaryVideo.__table__,
    DroneSurvey.__table__,
    RealityCaptureDataset.__table__,
    DiaryArchiveSignature.__table__,
]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """‌⁠‍Per-test in-memory SQLite session with the daily-diary tables.

    FK pragma OFF — see test_daily_diary_security.py for rationale.
    The cross-module FK integrity is checked by the alembic-migration
    tests against PostgreSQL, not here.
    """
    from sqlalchemy import text

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = OFF"))
        await conn.run_sync(Base.metadata.create_all, tables=_DD_TABLES)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        await sess.execute(text("PRAGMA foreign_keys = OFF"))
        yield sess
        await sess.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def svc(session: AsyncSession) -> DailyDiaryService:
    return DailyDiaryService(session)


def _yesterday_iso() -> str:
    return (datetime.now(UTC).date() - timedelta(days=1)).isoformat()


# ── 1. Happy path: create → delete → 404 ─────────────────────────────────


@pytest.mark.asyncio
async def test_delete_diary_then_get_raises_404(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Open diary deletes cleanly; a subsequent fetch is 404."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    diary_id = diary.id
    # Sanity: it exists right now.
    fetched = await svc.get_diary(diary_id)
    assert fetched.id == diary_id

    # The router maps this to HTTP 204 (no body) — the service call
    # itself returns None.
    result = await svc.delete_diary(diary_id)
    assert result is None

    # Re-fetch must now 404. The service raises HTTPException(404)
    # (mapped 1:1 from FastAPI dependency handler) so the assertion is
    # against the exception's status_code, not a response object.
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_diary(diary_id)
    assert exc_info.value.status_code == 404


# ── 2. Sealed-immutable gate ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_signed_diary_returns_409(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Signed diaries cannot be deleted — same immutability shield as PATCH."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    diary_id = diary.id
    await svc.close_diary(diary_id)
    await svc.sign_diary(diary_id, signer_role="supervisor", signer_name="Bob")

    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_diary(diary_id)
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "diary_signed_immutable"
    assert detail["status"] == "signed"
    assert detail["diary_id"] == str(diary_id)

    # And the diary still exists — the 409 is non-destructive.
    still_there = await svc.get_diary(diary_id)
    assert still_there.id == diary_id


@pytest.mark.asyncio
async def test_delete_archived_diary_returns_409(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Archived (terminal) diaries also rejected from delete."""
    project_id = uuid.uuid4()
    diary = await svc.create_diary(
        DailyDiaryCreate(project_id=project_id, diary_date=_yesterday_iso()),
    )
    diary_id = diary.id
    await svc.close_diary(diary_id)
    await svc.sign_diary(diary_id, signer_role="supervisor")
    await svc.archive_diary(diary_id)

    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_diary(diary_id)
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "diary_signed_immutable"
    assert detail["status"] == "archived"


# ── 3. Unknown id → 404 (not 500) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_unknown_diary_returns_404(
    svc: DailyDiaryService,
) -> None:
    """‌⁠‍Deleting a non-existent diary surfaces 404, not a 500."""
    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_diary(uuid.uuid4())
    assert exc_info.value.status_code == 404
