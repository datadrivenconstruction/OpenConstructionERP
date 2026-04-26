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
    """Set ``role = 'admin'`` and ``is_active = True`` on the named user.

    Originally this only flipped ``role``, which sufficed in v2.5.x when
    ``open`` was the default registration mode and every newly-registered
    account was already active. v2.5.2 flipped the default mode to
    ``admin-approve`` (BUG-RBAC03), so non-bootstrap registrations now
    land with ``is_active=False`` and login returns the same generic
    "Invalid email or password" error as a wrong password — silently
    breaking every shared_auth fixture that promotes after register.
    Setting ``is_active=True`` here keeps test fixtures working in both
    legacy and current registration modes.
    """
    from sqlalchemy import select

    async with async_session_factory() as session:
        await session.execute(
            update(User)
            .where(User.email == email.lower())
            .values(role="admin", is_active=True)
        )
        await session.commit()
        # Defensive: confirm the row actually got updated. A miss here
        # (rowcount = 0) means the prior register call hit a different
        # session/engine — usually a test-isolation bug.
        result = await session.execute(
            select(User.is_active, User.role).where(User.email == email.lower())
        )
        row = result.first()
        if row is None:
            raise RuntimeError(
                f"promote_to_admin: user {email} not found after register; "
                "likely a DB-isolation issue (different DATABASE_URL between "
                "the HTTP client's app and async_session_factory)."
            )
