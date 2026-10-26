# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for meeting recordings and the project meeting glossary."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meetings.models import MeetingGlossaryTerm, MeetingRecording


class RecordingRepository:
    """CRUD for :class:`MeetingRecording` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, recording_id: uuid.UUID) -> MeetingRecording | None:
        return await self.session.get(MeetingRecording, recording_id)

    async def list_for_meeting(self, meeting_id: uuid.UUID) -> list[MeetingRecording]:
        stmt = (
            select(MeetingRecording)
            .where(MeetingRecording.meeting_id == meeting_id)
            .order_by(MeetingRecording.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_project(self, project_id: uuid.UUID) -> list[MeetingRecording]:
        stmt = select(MeetingRecording).where(MeetingRecording.project_id == project_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_expired_audio(self, now: datetime) -> list[MeetingRecording]:
        stmt = select(MeetingRecording).where(
            MeetingRecording.audio_storage_key != "",
            MeetingRecording.audio_expires_at.is_not(None),
            MeetingRecording.audio_expires_at < now,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def add(self, row: MeetingRecording) -> MeetingRecording:
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete(self, row: MeetingRecording) -> None:
        await self.session.delete(row)
        await self.session.flush()


class GlossaryRepository:
    """CRUD for :class:`MeetingGlossaryTerm` rows, always project-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, term_id: uuid.UUID) -> MeetingGlossaryTerm | None:
        return await self.session.get(MeetingGlossaryTerm, term_id)

    async def list_for_project(self, project_id: uuid.UUID) -> list[MeetingGlossaryTerm]:
        stmt = (
            select(MeetingGlossaryTerm)
            .where(MeetingGlossaryTerm.project_id == project_id)
            .order_by(MeetingGlossaryTerm.kind, MeetingGlossaryTerm.term_key)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_key(self, project_id: uuid.UUID, key: str) -> MeetingGlossaryTerm | None:
        stmt = select(MeetingGlossaryTerm).where(
            MeetingGlossaryTerm.project_id == project_id,
            MeetingGlossaryTerm.term_key == key,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_many(self, rows: list[MeetingGlossaryTerm]) -> None:
        self.session.add_all(rows)
        await self.session.flush()

    async def delete(self, row: MeetingGlossaryTerm) -> None:
        await self.session.delete(row)
        await self.session.flush()
