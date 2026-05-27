# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Async SQLAlchemy repositories for the Field Diary module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.field_diary.models import (
    DiaryActivity,
    DiaryAttachment,
    DiaryEntry,
    FieldMagicLink,
    FieldModuleGrant,
    FieldSession,
)


class _BaseRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session


# ── Diary entries ─────────────────────────────────────────────────────────


class DiaryEntryRepository(_BaseRepo):
    async def create(self, entry: DiaryEntry) -> DiaryEntry:
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)
        return entry

    async def get_by_id(self, entry_id: uuid.UUID) -> DiaryEntry | None:
        return await self.session.get(DiaryEntry, entry_id)

    async def get_by_unique(
        self,
        project_id: uuid.UUID,
        author_id: uuid.UUID,
        entry_date: str,
    ) -> DiaryEntry | None:
        stmt = select(DiaryEntry).where(
            DiaryEntry.project_id == project_id,
            DiaryEntry.author_id == author_id,
            DiaryEntry.entry_date == entry_date,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[DiaryEntry]:
        stmt = select(DiaryEntry).where(DiaryEntry.project_id == project_id)
        if date_from is not None:
            stmt = stmt.where(DiaryEntry.entry_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(DiaryEntry.entry_date <= date_to)
        stmt = (
            stmt.order_by(
                DiaryEntry.entry_date.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_fields(self, entry_id: uuid.UUID, **fields: Any) -> None:
        entry = await self.session.get(DiaryEntry, entry_id)
        if entry is None:
            return
        for k, v in fields.items():
            # Map ``metadata`` keyword onto the ORM attribute name.
            attr = "metadata_" if k == "metadata" else k
            setattr(entry, attr, v)
        await self.session.flush()


# ── Activities ────────────────────────────────────────────────────────────


class DiaryActivityRepository(_BaseRepo):
    async def create(self, activity: DiaryActivity) -> DiaryActivity:
        self.session.add(activity)
        await self.session.flush()
        await self.session.refresh(activity)
        return activity

    async def list_for_entry(
        self,
        entry_id: uuid.UUID,
    ) -> list[DiaryActivity]:
        stmt = select(DiaryActivity).where(DiaryActivity.entry_id == entry_id).order_by(DiaryActivity.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ── Attachments ───────────────────────────────────────────────────────────


class DiaryAttachmentRepository(_BaseRepo):
    async def create(self, attachment: DiaryAttachment) -> DiaryAttachment:
        self.session.add(attachment)
        await self.session.flush()
        await self.session.refresh(attachment)
        return attachment

    async def list_for_entry(
        self,
        entry_id: uuid.UUID,
    ) -> list[DiaryAttachment]:
        stmt = select(DiaryAttachment).where(DiaryAttachment.entry_id == entry_id).order_by(DiaryAttachment.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ── Field module grants ───────────────────────────────────────────────────


class FieldModuleGrantRepository(_BaseRepo):
    async def create(self, grant: FieldModuleGrant) -> FieldModuleGrant:
        self.session.add(grant)
        await self.session.flush()
        await self.session.refresh(grant)
        return grant

    async def get_by_id(
        self,
        grant_id: uuid.UUID,
    ) -> FieldModuleGrant | None:
        return await self.session.get(FieldModuleGrant, grant_id)

    async def get_active(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        module_key: str,
    ) -> FieldModuleGrant | None:
        """Return the live grant row (non-revoked) for the given tuple.

        Used to enforce uniqueness *and* by the access check. Expiry is
        evaluated by the caller against current UTC ``now()``.
        """
        stmt = select(FieldModuleGrant).where(
            and_(
                FieldModuleGrant.user_id == user_id,
                FieldModuleGrant.project_id == project_id,
                FieldModuleGrant.module_key == module_key,
                FieldModuleGrant.revoked_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        include_revoked: bool = False,
    ) -> list[FieldModuleGrant]:
        stmt = select(FieldModuleGrant).where(
            FieldModuleGrant.project_id == project_id,
        )
        if not include_revoked:
            stmt = stmt.where(FieldModuleGrant.revoked_at.is_(None))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def revoke(
        self,
        grant_id: uuid.UUID,
        *,
        revoked_at: datetime,
    ) -> bool:
        grant = await self.session.get(FieldModuleGrant, grant_id)
        if grant is None or grant.revoked_at is not None:
            return False
        grant.revoked_at = revoked_at
        await self.session.flush()
        return True


# ── Magic links ───────────────────────────────────────────────────────────


class FieldMagicLinkRepository(_BaseRepo):
    async def create(self, link: FieldMagicLink) -> FieldMagicLink:
        self.session.add(link)
        await self.session.flush()
        await self.session.refresh(link)
        return link

    async def get_by_token_hash(
        self,
        token_hash: str,
    ) -> FieldMagicLink | None:
        stmt = select(FieldMagicLink).where(
            FieldMagicLink.token_hash == token_hash,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_fields(
        self,
        link_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        link = await self.session.get(FieldMagicLink, link_id)
        if link is None:
            return
        for k, v in fields.items():
            setattr(link, k, v)
        await self.session.flush()


# ── Sessions ──────────────────────────────────────────────────────────────


class FieldSessionRepository(_BaseRepo):
    async def create(self, sess: FieldSession) -> FieldSession:
        self.session.add(sess)
        await self.session.flush()
        await self.session.refresh(sess)
        return sess

    async def get_by_token_hash(
        self,
        token_hash: str,
    ) -> FieldSession | None:
        stmt = select(FieldSession).where(
            FieldSession.session_token_hash == token_hash,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_fields(
        self,
        session_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        sess = await self.session.get(FieldSession, session_id)
        if sess is None:
            return
        for k, v in fields.items():
            setattr(sess, k, v)
        await self.session.flush()
