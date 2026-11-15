"""The demo capture queue: three supplier quotes read by the rules extractor."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_projects import DEMO_TEMPLATES
from app.modules.projects.models import Project
from app.modules.quote_capture.models import CapturedQuote
from app.modules.quote_capture.seed import seed_quote_capture_demo
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio
OWNER = uuid.UUID("00000000-0000-4000-8000-00000000f14e")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def test_project_gets_three_read_quotes(session: AsyncSession) -> None:
    demo_id = next(k for k, t in DEMO_TEMPLATES.items() if len(t.tender_companies or []) >= 3)
    project = Project(
        id=uuid.uuid4(),
        name="Demo",
        currency="EUR",
        status="active",
        owner_id=OWNER,
        metadata_={"demo_id": demo_id},
    )
    session.add(project)
    await session.flush()

    assert (await seed_quote_capture_demo(session, [project.id]))["quotes"] == 3
    quotes = (
        (await session.execute(select(CapturedQuote).where(CapturedQuote.project_id == project.id))).scalars().all()
    )
    assert len({q.supplier_name for q in quotes}) == 3
    for quote in quotes:
        assert len(quote.lines) == 3
        assert Decimal(quote.quote_total) > 0

    assert (await seed_quote_capture_demo(session, [project.id]))["quotes"] == 0
