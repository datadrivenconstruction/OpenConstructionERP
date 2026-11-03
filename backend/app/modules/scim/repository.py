# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SCIM data access: users as the IdP sees them, groups and memberships."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scim.models import ScimGroup, scim_group_member
from app.modules.users.models import User, UserSession


class ScimRepository:
    """Queries only; business rules live in the service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Users ──────────────────────────────────────────────────────────

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        user = await self.session.get(User, user_id)
        return user if user is not None and user.deleted_at is None else None

    async def user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower(), User.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def user_by_external_id(self, external_id: str) -> User | None:
        stmt = select(User).where(User.external_id == external_id, User.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_users(
        self, *, email: str | None = None, external_id: str | None = None, offset: int = 0, limit: int = 100
    ) -> tuple[list[User], int]:
        cond = [User.deleted_at.is_(None)]
        if email is not None:
            cond.append(func.lower(User.email) == email.lower())
        if external_id is not None:
            cond.append(User.external_id == external_id)
        total = (await self.session.execute(select(func.count()).select_from(User).where(*cond))).scalar_one()
        stmt = select(User).where(*cond).order_by(User.created_at, User.id).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all()), int(total)

    async def count_active_admins(self) -> int:
        stmt = (
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True), User.deleted_at.is_(None))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def revoke_sessions(self, user_id: uuid.UUID) -> None:
        stmt = (
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.execute(stmt)

    async def list_known_users(self, limit: int = 200) -> list[User]:
        """Users for the admin panel: everyone, newest sync first."""
        stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.updated_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def provisioned_summary(self) -> tuple[int, datetime | None]:
        """Count of IdP-managed accounts and the last change among them and the groups."""
        managed = (User.provisioned_by == "scim") | (User.external_id.is_not(None))
        users = select(func.count(), func.max(User.updated_at)).where(managed, User.deleted_at.is_(None))
        count, last_user = (await self.session.execute(users)).one()
        last_group = (await self.session.execute(select(func.max(ScimGroup.updated_at)))).scalar_one()
        stamps = [t for t in (last_user, last_group) if t is not None]
        return int(count or 0), (max(stamps) if stamps else None)

    # ── Groups ─────────────────────────────────────────────────────────

    async def get_group(self, group_id: uuid.UUID) -> ScimGroup | None:
        return await self.session.get(ScimGroup, group_id)

    async def group_by_name(self, name: str) -> ScimGroup | None:
        stmt = select(ScimGroup).where(func.lower(ScimGroup.display_name) == name.lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def group_by_external_id(self, external_id: str) -> ScimGroup | None:
        stmt = select(ScimGroup).where(ScimGroup.external_id == external_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_groups(
        self, *, name: str | None = None, offset: int = 0, limit: int = 1000
    ) -> tuple[list[ScimGroup], int]:
        cond = []
        if name is not None:
            cond.append(func.lower(ScimGroup.display_name) == name.lower())
        total = (await self.session.execute(select(func.count()).select_from(ScimGroup).where(*cond))).scalar_one()
        stmt = select(ScimGroup).where(*cond).order_by(ScimGroup.display_name).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all()), int(total)

    async def member_ids(self, group_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = select(scim_group_member.c.user_id).where(scim_group_member.c.group_id == group_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def members(self, group_id: uuid.UUID) -> list[User]:
        stmt = (
            select(User)
            .join(scim_group_member, scim_group_member.c.user_id == User.id)
            .where(scim_group_member.c.group_id == group_id)
            .order_by(User.email)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def member_counts(self) -> dict[uuid.UUID, int]:
        stmt = select(scim_group_member.c.group_id, func.count()).group_by(scim_group_member.c.group_id)
        return {gid: int(n) for gid, n in (await self.session.execute(stmt)).all()}

    async def add_members(self, group_id: uuid.UUID, user_ids: Iterable[uuid.UUID]) -> None:
        present = set(await self.member_ids(group_id))
        rows = [{"group_id": group_id, "user_id": u} for u in dict.fromkeys(user_ids) if u not in present]
        if rows:
            await self.session.execute(insert(scim_group_member), rows)

    async def remove_members(self, group_id: uuid.UUID, user_ids: Iterable[uuid.UUID]) -> None:
        ids = list(user_ids)
        if ids:
            await self.session.execute(
                delete(scim_group_member).where(
                    scim_group_member.c.group_id == group_id, scim_group_member.c.user_id.in_(ids)
                )
            )

    async def groups_of_user(self, user_id: uuid.UUID) -> list[ScimGroup]:
        stmt = (
            select(ScimGroup)
            .join(scim_group_member, scim_group_member.c.group_id == ScimGroup.id)
            .where(scim_group_member.c.user_id == user_id)
            .order_by(ScimGroup.display_name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete_group(self, group: ScimGroup) -> None:
        await self.session.execute(delete(scim_group_member).where(scim_group_member.c.group_id == group.id))
        await self.session.delete(group)
        await self.session.flush()

    async def groups_by_user(self, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[ScimGroup]]:
        ids = list(user_ids)
        out: dict[uuid.UUID, list[ScimGroup]] = {u: [] for u in ids}
        if not ids:
            return out
        stmt = (
            select(scim_group_member.c.user_id, ScimGroup)
            .join(ScimGroup, ScimGroup.id == scim_group_member.c.group_id)
            .where(scim_group_member.c.user_id.in_(ids))
            .order_by(ScimGroup.display_name)
        )
        for uid, group in (await self.session.execute(stmt)).all():
            out[uid].append(group)
        return out
