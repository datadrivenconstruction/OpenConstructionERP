# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The showcase projects belong to the demo account, never to a deactivated one.

The seeders took the owner with ``WHERE role = 'admin' LIMIT 1``. On a live
installation that row is a real administrator, picked in whatever order the
database happened to read, and it could be one whose account had been
deactivated: the showcase then sat on a person who could not sign in to see
or remove it.

Every test works inside one transaction that is rolled back, so the users it
switches off or adds never reach the shared test database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.core.demo_accounts import SHOWCASE_OWNER_EMAIL
from app.core.demo_projects import _get_or_create_owner, find_showcase_owner


@pytest_asyncio.fixture(scope="module")
async def db_engine():
    from app.config import get_settings

    get_settings.cache_clear()
    import app.modules.users.models  # noqa: F401
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine


@pytest_asyncio.fixture
async def session(db_engine) -> AsyncIterator:
    from app.database import async_session_factory

    async with async_session_factory() as s:
        try:
            yield s
        finally:
            await s.rollback()


def _user(role: str, *, active: bool, created_at: datetime, email: str | None = None):
    from app.modules.users.models import User

    return User(
        email=email or f"owner-{uuid.uuid4().hex[:10]}@test.io",
        hashed_password="x",
        full_name="Owner Test",
        role=role,
        is_active=active,
        created_at=created_at,
    )


async def _demo_account(session, *, active: bool):
    """The demo row in this transaction, created if the database has none."""
    from app.modules.users.models import User

    demo = (await session.execute(select(User).where(User.email == SHOWCASE_OWNER_EMAIL))).scalar_one_or_none()
    if demo is None:
        demo = _user("viewer", active=active, created_at=datetime.now(UTC), email=SHOWCASE_OWNER_EMAIL)
        session.add(demo)
    demo.is_active = active
    await session.flush()
    return demo


async def _switch_everyone_off(session) -> None:
    from app.modules.users.models import User

    await session.execute(update(User).values(is_active=False))


@pytest.mark.asyncio
async def test_the_demo_account_owns_the_showcase_before_any_older_admin(session) -> None:
    session.add(_user("admin", active=True, created_at=datetime(2000, 1, 1, tzinfo=UTC)))
    demo = await _demo_account(session, active=True)

    owner = await find_showcase_owner(session)

    assert owner is not None
    assert owner.id == demo.id


@pytest.mark.asyncio
async def test_a_deactivated_admin_is_passed_over_for_an_active_one(session) -> None:
    await _switch_everyone_off(session)
    oldest = datetime(2000, 1, 1, tzinfo=UTC)
    session.add(_user("admin", active=False, created_at=oldest))
    active_admin = _user("admin", active=True, created_at=oldest + timedelta(days=1))
    session.add(active_admin)
    await session.flush()

    owner = await find_showcase_owner(session)

    assert owner is not None
    assert owner.id == active_admin.id
    assert owner.is_active


@pytest.mark.asyncio
async def test_a_deactivated_demo_account_does_not_own_the_showcase(session) -> None:
    await _switch_everyone_off(session)
    await _demo_account(session, active=False)
    editor = _user("editor", active=True, created_at=datetime(2000, 1, 1, tzinfo=UTC))
    session.add(editor)
    await session.flush()

    owner = await find_showcase_owner(session)

    assert owner is not None
    assert owner.id == editor.id


@pytest.mark.asyncio
async def test_with_no_active_account_the_seed_stops_rather_than_waking_the_demo(session) -> None:
    await _switch_everyone_off(session)
    await _demo_account(session, active=False)

    assert await find_showcase_owner(session) is None
    with pytest.raises(RuntimeError, match="deactivated"):
        await _get_or_create_owner(session)
