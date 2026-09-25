"""A punch item written by any module is priced in its project's currency.

``PunchListService.create_item`` already stamped the project currency, but the
model default was ``USD`` and five other writers build ``PunchItem`` directly:
the punchlist event bridges (clash, inspection, NCR), the inspections router and
the field diary. On a euro project each of those rows said USD, and the amount
then fell out of every reader that folds only the project's currency. The
default now comes from the project at insert time, whoever does the insert.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, currency: str) -> uuid.UUID:
    user = User(email=f"pcur{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(name="Punch currency", owner_id=user.id, currency=currency)
    session.add(project)
    await session.flush()
    return project.id


async def test_a_directly_built_item_takes_the_project_currency(session: AsyncSession) -> None:
    pid = await _project(session, "EUR")
    item = PunchItem(project_id=pid, title="Scuffed skirting")
    session.add(item)
    await session.flush()
    assert item.rework_cost_currency == "EUR"


async def test_an_explicit_currency_is_kept(session: AsyncSession) -> None:
    pid = await _project(session, "EUR")
    item = PunchItem(project_id=pid, title="Imported fitting", rework_cost_currency="CHF")
    session.add(item)
    await session.flush()
    assert item.rework_cost_currency == "CHF"


async def test_a_project_without_a_currency_falls_back_like_the_service(session: AsyncSession) -> None:
    # Same fallback as PunchListService._rework_currency (pinned in
    # test_punch_rework_cost_edit): an undecided project currency is a
    # legitimate state, and the column is NOT NULL.
    pid = await _project(session, "")
    item = PunchItem(project_id=pid, title="Loose tile")
    session.add(item)
    await session.flush()
    assert item.rework_cost_currency == "USD"
