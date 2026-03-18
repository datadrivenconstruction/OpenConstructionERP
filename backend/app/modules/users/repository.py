"""User data access layer.

All database queries for users and API keys live here.
No business logic — pure data access.
"""

import uuid
from datetime import UTC

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import APIKey, User


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
        """List users with pagination. Returns (users, total_count)."""
        base = select(User)
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


class APIKeyRepository:
    """Data access for APIKey model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, key_id: uuid.UUID) -> APIKey | None:
        """Get API key by ID."""
        return await self.session.get(APIKey, key_id)

    async def get_by_hash(self, key_hash: str) -> APIKey | None:
        """Get API key by its hash (for authentication)."""
        stmt = select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active.is_(True))
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

    async def update_last_used(self, key_id: uuid.UUID) -> None:
        """Update the last_used_at timestamp."""
        from datetime import datetime

        stmt = update(APIKey).where(APIKey.id == key_id).values(last_used_at=datetime.now(UTC))
        await self.session.execute(stmt)
