# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠File Trash data access layer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_trash.models import FileTrash


class FileTrashRepository:
    """Data access for :class:`FileTrash` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, trash_id: uuid.UUID) -> FileTrash | None:
        return await self.session.get(FileTrash, trash_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        include_restored: bool = False,
        include_purged: bool = False,
    ) -> tuple[list[FileTrash], int]:
        """List trash rows for a project, sorted by ``trashed_at`` desc."""
        base = select(FileTrash).where(FileTrash.project_id == project_id)
        if not include_restored:
            base = base.where(FileTrash.restored_at.is_(None))
        if not include_purged:
            base = base.where(FileTrash.purged_at.is_(None))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(FileTrash.trashed_at.desc()).offset(offset).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, int(total)

    async def add(self, row: FileTrash) -> FileTrash:
        self.session.add(row)
        await self.session.flush()
        return row

    async def stats_for_project(
        self, project_id: uuid.UUID
    ) -> tuple[int, list[FileTrash], datetime | None, datetime | None]:
        """Return (count, rows, oldest_at, newest_at).

        Rows are returned so the caller can sum ``file_size`` (which is
        derived from ``payload_json`` and not stored as a column).
        """
        stmt = select(FileTrash).where(
            FileTrash.project_id == project_id,
            FileTrash.restored_at.is_(None),
            FileTrash.purged_at.is_(None),
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        if not rows:
            return 0, [], None, None
        oldest = min(r.trashed_at for r in rows)
        newest = max(r.trashed_at for r in rows)
        return len(rows), rows, oldest, newest

    async def expired(self, now: datetime) -> list[FileTrash]:
        """Return non-restored / non-purged rows whose retention has lapsed.

        Computes ``trashed_at + retention_days < now`` in Python (instead
        of via a SQL date-math expression) so the query stays portable
        across SQLite and PostgreSQL without per-dialect ``DATEADD`` /
        ``INTERVAL`` shimming. Trash sets are small enough (cap ~10k
        rows per nightly purge) that the in-process filter is fine.
        """
        stmt = select(FileTrash).where(
            FileTrash.restored_at.is_(None),
            FileTrash.purged_at.is_(None),
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        out: list[FileTrash] = []
        for r in rows:
            # Normalise tz: SQLite returns naive datetimes; treat them as UTC.
            ts = r.trashed_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=now.tzinfo)
            delta = now - ts
            if delta.total_seconds() >= r.retention_days * 86400:
                out.append(r)
        return out

    async def delete(self, trash_id: uuid.UUID) -> None:
        row = await self.get_by_id(trash_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()
