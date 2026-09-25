"""Loading a user must not load their API keys.

Every authenticated request re-reads the caller with ``session.get(User, id)``
(``app.dependencies``). While ``User.api_keys`` was ``lazy="selectin"`` that one
lookup cost a second SELECT against ``oe_users_api_key`` on every request, for a
collection nothing reads. These tests pin the lookup to the user row alone, and
check that removing a user still removes the keys now that the ORM no longer
loads them to delete them one by one (the FK's ``ON DELETE CASCADE`` does it).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated PostgreSQL session - empty at t=0."""
    async with transactional_session() as s:
        yield s


async def _user_with_key(session: AsyncSession) -> uuid.UUID:
    from app.modules.users.models import APIKey, User

    user = User(
        id=uuid.uuid4(),
        email=f"keys-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Key Holder",
        role="editor",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(
        APIKey(
            user_id=user.id,
            name="ci",
            key_hash=uuid.uuid4().hex,
            key_prefix="oe_test_",
        )
    )
    await session.flush()
    session.expunge_all()
    return user.id


@pytest.mark.asyncio
async def test_loading_a_user_issues_no_api_key_query(session: AsyncSession) -> None:
    from app.modules.users.models import User

    uid = await _user_with_key(session)
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    engine = session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        user = await session.get(User, uid)
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert user is not None
    assert statements, "the listener saw nothing, so it proves nothing"
    assert not [s for s in statements if "oe_users_api_key" in s], statements


@pytest.mark.asyncio
async def test_deleting_a_user_removes_their_api_keys(session: AsyncSession) -> None:
    from app.modules.users.models import APIKey, User

    uid = await _user_with_key(session)
    assert await session.scalar(select(func.count()).select_from(APIKey).where(APIKey.user_id == uid)) == 1

    user = await session.get(User, uid)
    await session.delete(user)
    await session.flush()

    assert await session.scalar(select(func.count()).select_from(APIKey).where(APIKey.user_id == uid)) == 0
