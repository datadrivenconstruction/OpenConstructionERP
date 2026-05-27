# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Customer & Partner Portal data access layer."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.portal.models import (
    PortalAccessRule,
    PortalDocumentAccessLog,
    PortalMagicLink,
    PortalNotification,
    PortalSession,
    PortalUser,
)


class PortalUserRepository:
    """‌⁠‍CRUD + lookup helpers for :class:`PortalUser`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> PortalUser | None:
        return await self.session.get(PortalUser, user_id)

    async def get_by_email(self, email: str) -> PortalUser | None:
        stmt = select(PortalUser).where(PortalUser.email == email.strip().lower())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, user: PortalUser) -> PortalUser:
        self.session.add(user)
        await self.session.flush()
        return user

    async def list_users(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        portal_role: str | None = None,
        status: str | None = None,
    ) -> tuple[list[PortalUser], int]:
        base = select(PortalUser)
        if portal_role is not None:
            base = base.where(PortalUser.portal_role == portal_role)
        if status is not None:
            base = base.where(PortalUser.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(PortalUser.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update_fields(self, user_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(PortalUser).where(PortalUser.id == user_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()


class PortalAccessRuleRepository:
    """‌⁠‍CRUD + lookup helpers for :class:`PortalAccessRule`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, rule_id: uuid.UUID) -> PortalAccessRule | None:
        return await self.session.get(PortalAccessRule, rule_id)

    async def get_one(
        self,
        portal_user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> PortalAccessRule | None:
        stmt = select(PortalAccessRule).where(
            and_(
                PortalAccessRule.portal_user_id == portal_user_id,
                PortalAccessRule.resource_type == resource_type,
                PortalAccessRule.resource_id == resource_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        portal_user_id: uuid.UUID,
        *,
        resource_type: str | None = None,
    ) -> list[PortalAccessRule]:
        stmt = select(PortalAccessRule).where(
            PortalAccessRule.portal_user_id == portal_user_id,
        )
        if resource_type is not None:
            stmt = stmt.where(PortalAccessRule.resource_type == resource_type)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_rules(
        self,
        *,
        portal_user_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[PortalAccessRule], int]:
        """Admin-facing paginated list of access rules (optionally filtered).

        Counting is done with a SQL aggregate over the filtered query rather
        than materialising every row, matching the pattern used by the other
        repositories in this module.
        """
        base = select(PortalAccessRule)
        if portal_user_id is not None:
            base = base.where(
                PortalAccessRule.portal_user_id == portal_user_id,
            )
        if resource_type is not None:
            base = base.where(
                PortalAccessRule.resource_type == resource_type,
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(PortalAccessRule.granted_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total)

    async def create(self, rule: PortalAccessRule) -> PortalAccessRule:
        self.session.add(rule)
        await self.session.flush()
        return rule

    async def update_fields(self, rule_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(PortalAccessRule).where(PortalAccessRule.id == rule_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, rule_id: uuid.UUID) -> None:
        rule = await self.get_by_id(rule_id)
        if rule is not None:
            await self.session.delete(rule)
            await self.session.flush()

    async def delete_match(
        self,
        portal_user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> None:
        rule = await self.get_one(portal_user_id, resource_type, resource_id)
        if rule is not None:
            await self.session.delete(rule)
            await self.session.flush()


class PortalSessionRepository:
    """CRUD + lookup helpers for :class:`PortalSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_token_hash(self, token_hash: str) -> PortalSession | None:
        stmt = select(PortalSession).where(
            PortalSession.session_token_hash == token_hash,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, sess: PortalSession) -> PortalSession:
        self.session.add(sess)
        await self.session.flush()
        return sess

    async def update_fields(self, session_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(PortalSession).where(PortalSession.id == session_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def revoke_all_for_user(
        self,
        portal_user_id: uuid.UUID,
        *,
        revoked_at: datetime,
    ) -> int:
        stmt = (
            update(PortalSession)
            .where(
                and_(
                    PortalSession.portal_user_id == portal_user_id,
                    PortalSession.revoked_at.is_(None),
                )
            )
            .values(revoked_at=revoked_at)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)


class PortalMagicLinkRepository:
    """CRUD + lookup helpers for :class:`PortalMagicLink`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, link: PortalMagicLink) -> PortalMagicLink:
        self.session.add(link)
        await self.session.flush()
        return link

    async def get_by_token_hash(
        self,
        token_hash: str,
    ) -> PortalMagicLink | None:
        stmt = select(PortalMagicLink).where(
            PortalMagicLink.token_hash == token_hash,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_fields(self, link_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(PortalMagicLink).where(PortalMagicLink.id == link_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()


class PortalNotificationRepository:
    """CRUD + lookup helpers for :class:`PortalNotification`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, notif: PortalNotification) -> PortalNotification:
        self.session.add(notif)
        await self.session.flush()
        return notif

    async def get_by_id(self, notif_id: uuid.UUID) -> PortalNotification | None:
        return await self.session.get(PortalNotification, notif_id)

    async def list_for_user(
        self,
        portal_user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PortalNotification], int]:
        base = select(PortalNotification).where(
            PortalNotification.portal_user_id == portal_user_id,
        )
        if unread_only:
            base = base.where(PortalNotification.read_at.is_(None))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(PortalNotification.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def unread_count(self, portal_user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(PortalNotification)
            .where(
                and_(
                    PortalNotification.portal_user_id == portal_user_id,
                    PortalNotification.read_at.is_(None),
                )
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def update_fields(self, notif_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(PortalNotification).where(PortalNotification.id == notif_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()


class PortalDocumentAccessLogRepository:
    """Append-only audit log of portal document accesses."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        entry: PortalDocumentAccessLog,
    ) -> PortalDocumentAccessLog:
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_entries(
        self,
        *,
        portal_user_id: uuid.UUID | None = None,
        document_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[PortalDocumentAccessLog], int]:
        base = select(PortalDocumentAccessLog)
        if portal_user_id is not None:
            base = base.where(
                PortalDocumentAccessLog.portal_user_id == portal_user_id,
            )
        if document_type is not None:
            base = base.where(
                PortalDocumentAccessLog.document_type == document_type,
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(PortalDocumentAccessLog.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


__all__ = [
    "PortalAccessRuleRepository",
    "PortalDocumentAccessLogRepository",
    "PortalMagicLinkRepository",
    "PortalNotificationRepository",
    "PortalSessionRepository",
    "PortalUserRepository",
]
