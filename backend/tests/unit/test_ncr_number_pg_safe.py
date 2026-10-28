"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression: ``next_ncr_number`` must survive non-canonical NCR numbers.

PostgreSQL casts an empty or non-numeric string to integer strictly
(``invalid input syntax for type integer: ""``), unlike SQLite which silently
yielded 0. A single legacy or cross-module-bridged row (e.g. ``"901"`` raised
by the clash bridge) whose suffix-from-position-5 is empty used to raise on
every subsequent NCR for that project. The repository now filters to the
canonical ``NCR-<digits>`` shape before the cast.

These tests run against a real, transaction-isolated PostgreSQL session so the
``cast(substr(...) AS integer)`` actually executes on the same engine the app
uses; a stubbed session would not reproduce the dialect behaviour.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown).

    FKs are disabled so we can seed NCR rows under a synthetic ``project_id``
    without materialising a full project graph; ``next_ncr_number`` only filters
    on ``project_id`` and the number suffix.
    """
    async with transactional_session(disable_fks=True) as s:
        yield s


def _ncr(project_id: uuid.UUID, number: str):
    from app.modules.ncr.models import NCR

    return NCR(
        project_id=project_id,
        ncr_number=number,
        title="t",
        description="d",
        ncr_type="documentation",
        severity="major",
        status="identified",
        metadata_={},
    )


@pytest.mark.asyncio
async def test_next_ncr_number_ignores_non_canonical_rows(session: AsyncSession) -> None:
    from app.modules.ncr.repository import NCRRepository

    pid = uuid.uuid4()
    # Canonical rows plus one malformed "901" (suffix-from-5 == "") that used
    # to raise InvalidTextRepresentationError on PostgreSQL.
    for number in ("NCR-001", "NCR-002", "NCR-006", "901"):
        session.add(_ncr(pid, number))
    await session.flush()

    repo = NCRRepository(session)
    nxt = await repo.next_ncr_number(pid)  # must not raise

    assert nxt == "NCR-007"


@pytest.mark.asyncio
async def test_next_ncr_number_only_malformed_starts_at_001(session: AsyncSession) -> None:
    from app.modules.ncr.repository import NCRRepository

    pid = uuid.uuid4()
    for number in ("901", "NCR-", "NCR-DRAFT"):
        session.add(_ncr(pid, number))
    await session.flush()

    repo = NCRRepository(session)
    nxt = await repo.next_ncr_number(pid)

    assert nxt == "NCR-001"


@pytest.mark.asyncio
async def test_next_ncr_number_empty_project_starts_at_001(session: AsyncSession) -> None:
    from app.modules.ncr.repository import NCRRepository

    pid = uuid.uuid4()
    repo = NCRRepository(session)
    nxt = await repo.next_ncr_number(pid)

    assert nxt == "NCR-001"


@pytest.mark.asyncio
async def test_next_ncr_number_scopes_to_project(session: AsyncSession) -> None:
    """Numbers from another project never bleed into this project's sequence."""
    from app.modules.ncr.repository import NCRRepository

    pid_a = uuid.uuid4()
    pid_b = uuid.uuid4()
    session.add(_ncr(pid_a, "NCR-050"))
    session.add(_ncr(pid_b, "NCR-003"))
    await session.flush()

    repo = NCRRepository(session)
    assert await repo.next_ncr_number(pid_b) == "NCR-004"
