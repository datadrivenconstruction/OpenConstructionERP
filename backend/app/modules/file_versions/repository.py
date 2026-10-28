# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠File Versioning data access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_versions.models import FileVersion


class FileVersionRepository:
    """Data access for :class:`FileVersion` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, version_id: uuid.UUID) -> FileVersion | None:
        return await self.session.get(FileVersion, version_id)

    async def get_current(
        self,
        *,
        project_id: uuid.UUID,
        file_kind: str,
        canonical_name: str,
        for_update: bool = False,
    ) -> FileVersion | None:
        """Return the active ``is_current=True`` row in the chain, or ``None``.

        When ``for_update`` is set, take an exclusive row lock on the
        current row so two concurrent writers on the same
        ``(project_id, file_kind, canonical_name)`` chain are serialised
        at the DB level: the second transaction blocks here until the
        first commits, then re-reads the (now superseded) row and sees
        ``is_current=False``. This prevents two requests from both
        leaving an ``is_current=True`` row and both superseding the same
        prior current row. Mirrors the ``with_for_update`` pattern used
        in cde/repository.py and approval_routes/service.py. ``FOR
        UPDATE`` is honoured on PostgreSQL (the only supported backend).
        """
        stmt = (
            select(FileVersion)
            .where(
                FileVersion.project_id == project_id,
                FileVersion.file_kind == file_kind,
                FileVersion.canonical_name == canonical_name,
                FileVersion.is_current.is_(True),
            )
            .order_by(FileVersion.version_number.desc())
            .limit(1)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_chain(
        self,
        *,
        project_id: uuid.UUID,
        file_kind: str,
        canonical_name: str,
    ) -> list[FileVersion]:
        """Return the full chain newest-version-first."""
        stmt = (
            select(FileVersion)
            .where(
                FileVersion.project_id == project_id,
                FileVersion.file_kind == file_kind,
                FileVersion.canonical_name == canonical_name,
            )
            .order_by(FileVersion.version_number.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_file_id(self, file_id: str, file_kind: str) -> list[FileVersion]:
        """List every chain row that points at ``file_id``.

        Useful for the preview-pane dropdown which knows the row id of
        the file the user just clicked but not the canonical name.
        """
        stmt = (
            select(FileVersion)
            .where(
                FileVersion.file_id == file_id,
                FileVersion.file_kind == file_kind,
            )
            .order_by(FileVersion.version_number.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def next_version_number(
        self,
        *,
        project_id: uuid.UUID,
        file_kind: str,
        canonical_name: str,
    ) -> int:
        """Compute the next ``version_number`` for the chain (1-based)."""
        stmt = select(func.coalesce(func.max(FileVersion.version_number), 0)).where(
            FileVersion.project_id == project_id,
            FileVersion.file_kind == file_kind,
            FileVersion.canonical_name == canonical_name,
        )
        current = (await self.session.execute(stmt)).scalar_one()
        return int(current) + 1

    async def add(self, version: FileVersion) -> FileVersion:
        self.session.add(version)
        await self.session.flush()
        return version
