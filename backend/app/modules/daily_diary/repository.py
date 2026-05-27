"""‌⁠‍Daily Site Diary data-access layer.

One repository class per entity. Repositories are pure SQLAlchemy
adapters — no business logic — and exposed to service.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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

_M = TypeVar("_M")


class _BaseRepository:
    """‌⁠‍Shared CRUD helpers."""

    model: type

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, obj_id: uuid.UUID) -> object | None:
        return await self.session.get(self.model, obj_id)

    async def create(self, obj: object) -> object:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update_fields(self, obj_id: uuid.UUID, **fields: object) -> None:
        stmt = update(self.model).where(self.model.id == obj_id).values(**fields)  # type: ignore[attr-defined]
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, obj_id: uuid.UUID) -> None:
        obj = await self.get_by_id(obj_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()


class DailyDiaryRepository(_BaseRepository):
    """‌⁠‍Data access for DailyDiary."""

    model = DailyDiary

    async def get_by_date_and_project(
        self,
        project_id: uuid.UUID,
        diary_date: str,
    ) -> DailyDiary | None:
        stmt = select(DailyDiary).where(
            DailyDiary.project_id == project_id,
            DailyDiary.diary_date == diary_date,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_project_in_range(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> tuple[list[DailyDiary], int]:
        base = select(DailyDiary).where(DailyDiary.project_id == project_id)
        if date_from is not None:
            base = base.where(DailyDiary.diary_date >= date_from)
        if date_to is not None:
            base = base.where(DailyDiary.diary_date <= date_to)
        if status is not None:
            base = base.where(DailyDiary.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(DailyDiary.diary_date.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class WeatherRecordRepository(_BaseRepository):
    """Data access for WeatherRecord."""

    model = WeatherRecord

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[WeatherRecord], int]:
        base = select(WeatherRecord).where(WeatherRecord.project_id == project_id)
        if from_ts is not None:
            base = base.where(WeatherRecord.captured_at >= from_ts)
        if to_ts is not None:
            base = base.where(WeatherRecord.captured_at <= to_ts)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(WeatherRecord.captured_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def for_project_on_day(
        self,
        project_id: uuid.UUID,
        day_start: datetime,
        day_end: datetime,
    ) -> list[WeatherRecord]:
        """Weather records captured within ``[day_start, day_end)``.

        Bounds are a half-open UTC interval so a record captured at exactly
        midnight of the next day is not double-counted into both days.
        """
        stmt = (
            select(WeatherRecord)
            .where(WeatherRecord.project_id == project_id)
            .where(WeatherRecord.captured_at >= day_start)
            .where(WeatherRecord.captured_at < day_end)
            .order_by(WeatherRecord.captured_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class DiaryEntryRepository(_BaseRepository):
    """Data access for DiaryEntry."""

    model = DiaryEntry

    async def list_for_diary(
        self,
        diary_id: uuid.UUID,
        *,
        entry_type: str | None = None,
    ) -> list[DiaryEntry]:
        stmt = select(DiaryEntry).where(DiaryEntry.diary_id == diary_id)
        if entry_type is not None:
            stmt = stmt.where(DiaryEntry.entry_type == entry_type)
        stmt = stmt.order_by(DiaryEntry.entry_time.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def entries_by_source_module(
        self,
        diary_id: uuid.UUID,
        source_module: str,
    ) -> list[DiaryEntry]:
        stmt = (
            select(DiaryEntry)
            .where(DiaryEntry.diary_id == diary_id)
            .where(DiaryEntry.source_module == source_module)
            .order_by(DiaryEntry.entry_time.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_create(self, entries: list[DiaryEntry]) -> list[DiaryEntry]:
        self.session.add_all(entries)
        await self.session.flush()
        return entries


class DiaryPhotoRepository(_BaseRepository):
    """Data access for DiaryPhoto."""

    model = DiaryPhoto

    async def photos_for_project_in_range(
        self,
        project_id: uuid.UUID,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> tuple[list[DiaryPhoto], int]:
        base = select(DiaryPhoto).where(DiaryPhoto.project_id == project_id)
        if date_from is not None:
            base = base.where(DiaryPhoto.taken_at >= date_from)
        if date_to is not None:
            base = base.where(DiaryPhoto.taken_at <= date_to)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(DiaryPhoto.taken_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def photos_for_diary(
        self,
        diary_id: uuid.UUID,
    ) -> list[DiaryPhoto]:
        """Return all photos linked to a specific diary.

        Used by the sign / immutable-payload-hash paths. Previously these
        callers loaded every photo in the entire project (limit=10 000)
        and filtered in Python — wasteful and a P2 latency hit on large
        projects. A single indexed ``WHERE diary_id = ?`` is enough.
        """
        stmt = select(DiaryPhoto).where(DiaryPhoto.diary_id == diary_id).order_by(DiaryPhoto.taken_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class DiaryVideoRepository(_BaseRepository):
    """Data access for DiaryVideo."""

    model = DiaryVideo

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[DiaryVideo], int]:
        base = select(DiaryVideo).where(DiaryVideo.project_id == project_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = base.order_by(DiaryVideo.recorded_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class DroneSurveyRepository(_BaseRepository):
    """Data access for DroneSurvey."""

    model = DroneSurvey

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[DroneSurvey], int]:
        base = select(DroneSurvey).where(DroneSurvey.project_id == project_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = base.order_by(DroneSurvey.flown_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class RealityCaptureRepository(_BaseRepository):
    """Data access for RealityCaptureDataset."""

    model = RealityCaptureDataset

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[RealityCaptureDataset], int]:
        base = select(RealityCaptureDataset).where(RealityCaptureDataset.project_id == project_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = base.order_by(RealityCaptureDataset.captured_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class DiaryArchiveSignatureRepository(_BaseRepository):
    """Data access for DiaryArchiveSignature."""

    model = DiaryArchiveSignature

    async def signatures_for_diary(
        self,
        diary_id: uuid.UUID,
    ) -> list[DiaryArchiveSignature]:
        stmt = (
            select(DiaryArchiveSignature)
            .where(DiaryArchiveSignature.diary_id == diary_id)
            .order_by(DiaryArchiveSignature.revision.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def latest_for_diary(
        self,
        diary_id: uuid.UUID,
    ) -> DiaryArchiveSignature | None:
        stmt = (
            select(DiaryArchiveSignature)
            .where(DiaryArchiveSignature.diary_id == diary_id)
            .order_by(DiaryArchiveSignature.revision.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
