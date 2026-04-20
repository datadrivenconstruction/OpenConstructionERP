"""Test-only helpers for promoting a freshly registered user to admin.

The public `/auth/register` endpoint intentionally demotes new users to
``viewer`` (security hardening, BUG-327/386). Integration tests need admin
privileges, so they register a user and then promote them via a direct DB
write — bypassing the HTTP surface entirely.
"""

from sqlalchemy import update

from app.database import async_session_factory
from app.modules.users.models import User


async def promote_to_admin(email: str) -> None:
    """Set ``role = 'admin'`` on the user with the given email."""
    async with async_session_factory() as session:
        await session.execute(
            update(User).where(User.email == email.lower()).values(role="admin")
        )
        await session.commit()
