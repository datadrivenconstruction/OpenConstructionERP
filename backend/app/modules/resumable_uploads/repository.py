# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Resumable Uploads data access layer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.resumable_uploads.models import ResumableUploadSession


class ResumableUploadRepository:
    """Data access for :class:`ResumableUploadSession` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, session_id: uuid.UUID) -> ResumableUploadSession | None:
        return await self.session.get(ResumableUploadSession, session_id)

    async def add(self, upload: ResumableUploadSession) -> ResumableUploadSession:
        self.session.add(upload)
        await self.session.flush()
        return upload

    async def save(self, upload: ResumableUploadSession) -> ResumableUploadSession:
        """Flush pending mutations on an attached session row."""
        await self.session.flush()
        return upload

    async def remove(self, upload: ResumableUploadSession) -> None:
        await self.session.delete(upload)
        await self.session.flush()

    async def list_expired(self, *, now: datetime, limit: int = 500) -> list[ResumableUploadSession]:
        """Return in-flight sessions whose ``expires_at`` has passed.

        Only ``in_progress`` / ``assembling`` rows are reaped; terminal
        rows (complete / failed / expired) are left for any audit reader.
        """
        stmt = (
            select(ResumableUploadSession)
            .where(
                ResumableUploadSession.expires_at < now,
                ResumableUploadSession.status.in_(("in_progress", "assembling")),
            )
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete_terminal_before(self, *, cutoff: datetime) -> int:
        """Hard-delete terminal session rows older than ``cutoff``.

        Returns the number of rows removed. Used by the GC sweep to keep
        the table from growing without bound once a session has finished.
        """
        stmt = delete(ResumableUploadSession).where(
            ResumableUploadSession.created_at < cutoff,
            ResumableUploadSession.status.in_(("complete", "failed", "expired")),
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)
