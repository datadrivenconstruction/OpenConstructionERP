"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Fixtures for defects-liability module tests.

Uses the fast transactional-session primitive from ``tests/_pg.py`` against
the session PostgreSQL cluster. FK triggers are disabled so rows can be
created with a synthetic ``project_id`` without seeding a full project graph.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session with FK triggers disabled (synthetic project ids)."""
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()
