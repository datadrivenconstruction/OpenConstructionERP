# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""User data access layer.

All database queries for users and API keys live here.
No business logic - pure data access.
"""

import uuid
from datetime import UTC

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.users.models import APIKey, User

# E-mail of the bootstrap workspace owner created by the desktop first-run
# flow (POST /auth/desktop-bootstrap). Excluded from "real user" checks so the
# presence of the local owner never flips ``fresh_install`` to False: a desktop
# install that has only auto-provisioned its own owner is still "fresh" from
# the point of view of real, registered users.
LOCAL_DESKTOP_OWNER_EMAIL = "owner@openestimate.local"


class UserRepository:
    """Data access for User model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Get user by ID."""
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Get user by email (case-insensitive)."""
        stmt = select(User).where(User.email == email.lower())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        is_active: bool | None = None,
    ) -> tuple[list[User], int]:
        """List users with pagination. Returns (users, total_count).

        Erased accounts (``deleted_at`` set) are never returned. Deleting a user
        anonymises the row in place instead of removing it, because projects
        point at it through ``owner_id`` and activity / audit rows through
        ``actor_id``, and the projects foreign key cascades - a hard delete would
        take the user's projects, BOQs and documents with it. The row therefore
        has to survive, but it is no longer an account: it carries no personal
        data, it cannot authenticate, and there is no administrator action left
        to take on it. Listing it put a blank-named
        ``deleted+<hash>@deleted.invalid`` row back on the management page, which
        read as a deletion that had failed, and deleting it a second time
        answered 404 because the erasure path refuses an already-erased row.

        The predicate goes on ``base`` so the total and the page agree; putting
        it only on the fetch would keep counting rows the caller never sees.
        """
        base = select(User).where(User.deleted_at.is_(None))
        if is_active is not None:
            base = base.where(User.is_active == is_active)

        # Count
        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch
        stmt = base.order_by(User.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        users = list(result.scalars().all())

        return users, total

    async def create(self, user: User) -> User:
        """Insert a new user."""
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_fields(self, user_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a user."""
        stmt = update(User).where(User.id == user_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        instance = self.session.identity_map.get(identity_key(User, user_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def email_exists(self, email: str) -> bool:
        """Check if an email is already registered."""
        stmt = select(User.id).where(User.email == email.lower())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def count(self) -> int:
        """Total number of users."""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(User)
        return (await self.session.execute(stmt)).scalar_one()

    async def has_admin(self) -> bool:
        """Return True if at least one *real* active admin user exists.

        One half of the registration bootstrap: the next person to register
        via the public API is promoted to admin only when this is False AND
        :meth:`has_real_user` is False (a genuinely fresh install). A missing
        admin alone is not enough - on an install whose last admin was
        deactivated, or whose operator never registered, that rule handed
        admin to whoever reached the public form first.

        The seeded demo account ``demo@openconstructionerp.com`` is intentionally
        excluded: a fresh ``pip install openconstructionerp`` ships with
        that admin already in the DB, and counting it would dead-lock the
        bootstrap path - every self-registered user would be created
        dormant in admin-approve mode with no real admin around to flip
        them active. Excluding it lets the first registrant claim admin
        like the bootstrap was always meant to.
        """
        stmt = (
            select(User.id)
            .where(User.role == "admin", User.is_active.is_(True))
            .where(~User.email.ilike("%@openconstructionerp.com"))
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def has_real_user(self) -> bool:
        """Return True if any *real* user row exists, active or not.

        Same population as :meth:`has_real_active_user` (seeded demo accounts
        and the desktop bootstrap owner are not real) but without the
        ``is_active`` filter. The registration bootstrap asks this question:
        an install is fresh only while no real account was ever created, so a
        deactivated or dormant account still means somebody got there first
        and the next public registrant must not be handed admin.
        """
        stmt = (
            select(User.id)
            .where(~User.email.ilike("%@openconstructionerp.com"))
            .where(User.email != LOCAL_DESKTOP_OWNER_EMAIL)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def has_real_active_user(self) -> bool:
        """Return True if a *real* active user exists (the inverse of fresh).

        "Real" deliberately excludes two populations:

        * the seeded demo accounts (``*@openconstructionerp.com``) shipped on a
          fresh ``pip install`` / hosted demo, and
        * the desktop bootstrap owner (``owner@openestimate.local``) that the
          first-run flow auto-provisions.

        So a brand-new install - whether empty or carrying only demo seeds and
        an auto-created local owner - reports no real user, which is what the
        ``first-run`` endpoint surfaces as ``fresh_install=True``. Once a human
        registers (the bootstrap admin) this returns True and the desktop
        auto-login guard refuses to silently mint a new owner.
        """
        stmt = (
            select(User.id)
            .where(User.is_active.is_(True))
            .where(~User.email.ilike("%@openconstructionerp.com"))
            .where(User.email != LOCAL_DESKTOP_OWNER_EMAIL)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def count_active_admins(self, *, exclude_id: uuid.UUID | None = None) -> int:
        """Count active admin users, optionally excluding one id.

        Used by the self-erasure guard so the workspace is never left without
        an administrator: the caller passes its own id as ``exclude_id`` and a
        result of 0 means it is the last admin and erasure must be refused.
        Rows already marked erased (``deleted_at`` set) are not counted - an
        anonymised admin row is not a real administrator.
        """
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True), User.deleted_at.is_(None))
        )
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        return (await self.session.execute(stmt)).scalar_one()

    async def get_local_desktop_owner(self) -> User | None:
        """Return the desktop bootstrap owner row, or None if it doesn't exist.

        Looks the row up by its fixed e-mail (``owner@openestimate.local``).
        The caller is responsible for verifying the ``local_desktop`` metadata
        flag before trusting it as a bootstrap owner - a row at this e-mail
        without the flag is treated as a non-owner so a manually created
        account at that address can never be auto-logged-in.
        """
        return await self.get_by_email(LOCAL_DESKTOP_OWNER_EMAIL)


class APIKeyRepository:
    """Data access for APIKey model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, key_id: uuid.UUID) -> APIKey | None:
        """Get API key by ID."""
        return await self.session.get(APIKey, key_id)

    async def get_by_hash(self, key_hash: str) -> APIKey | None:
        """Get API key by its hash (for authentication).

        Rejects keys that are inactive or past their ``expires_at``. A NULL
        ``expires_at`` means the key never expires.
        """
        from datetime import datetime

        now = datetime.now(UTC)
        stmt = select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.is_active.is_(True),
            (APIKey.expires_at.is_(None)) | (APIKey.expires_at > now),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[APIKey]:
        """List all API keys for a user."""
        stmt = select(APIKey).where(APIKey.user_id == user_id).order_by(APIKey.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, api_key: APIKey) -> APIKey:
        """Insert a new API key."""
        self.session.add(api_key)
        await self.session.flush()
        return api_key

    async def deactivate(self, key_id: uuid.UUID) -> None:
        """Soft-delete an API key."""
        stmt = update(APIKey).where(APIKey.id == key_id).values(is_active=False)
        await self.session.execute(stmt)

    async def deactivate_all_for_user(self, user_id: uuid.UUID) -> None:
        """Revoke (deactivate) every API key owned by a user.

        Used by account erasure so no programmatic session outlives the
        anonymised account. Idempotent - already-inactive keys stay inactive.
        """
        stmt = update(APIKey).where(APIKey.user_id == user_id).values(is_active=False)
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_last_used(self, key_id: uuid.UUID) -> None:
        """Update the last_used_at timestamp and persist it."""
        from datetime import datetime

        stmt = update(APIKey).where(APIKey.id == key_id).values(last_used_at=datetime.now(UTC))
        await self.session.execute(stmt)
        await self.session.commit()
