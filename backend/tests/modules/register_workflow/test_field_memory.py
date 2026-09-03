# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Form defaults and this job's own history - and the one field that is
deliberately never remembered."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import field_memory, service
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, address: dict | None = None) -> uuid.UUID:
    user = User(
        email=f"fm-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="FM",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"FM {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="AUD",
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
        address=address,
    )
    session.add(proj)
    await session.flush()
    return proj.id


RFQ_FIELDS = {
    "Package": "Switchboards",
    "Delivery to": "12 Site Rd, Wetherill Park",
    "Site contact": "Alex Example 0400 000 000",
    "Delivery window / site hours": "Site hours 06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2099-01-01",
}


@pytest.mark.asyncio
async def test_delivery_to_defaults_to_the_projects_own_address(session: AsyncSession) -> None:
    pid = await _project(session, {"street": "1 Riverside Drive", "suburb": "Denver"})
    out = await field_memory.suggestions_for(session, project_id=pid, kind="rfq")
    assert out["fields"]["Delivery to"]["default"] == "1 Riverside Drive, Denver"


@pytest.mark.asyncio
async def test_this_jobs_answers_come_back_as_suggestions(session: AsyncSession) -> None:
    pid = await _project(session)
    await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    out = await field_memory.suggestions_for(session, project_id=pid, kind="rfq")
    assert "Site hours 06:30-14:30" in out["fields"]["Delivery window / site hours"]["recent"]
    # With no project address recorded, the address actually used leads.
    assert out["fields"]["Delivery to"]["default"] == "12 Site Rd, Wetherill Park"


@pytest.mark.asyncio
async def test_the_estimated_value_is_never_remembered(session: AsyncSession) -> None:
    """The one field that must be typed every time.

    It is what the quote gate tiers off: carry the last package's figure
    onto this one and a $40k job silently inherits a $2k package's
    one-quote rule.
    """
    pid = await _project(session)
    await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    out = await field_memory.suggestions_for(session, project_id=pid, kind="rfq")
    assert "Estimated value $" not in out["fields"]
    assert "9900" not in str(out)


@pytest.mark.asyncio
async def test_a_response_date_starts_a_week_out(session: AsyncSession) -> None:
    pid = await _project(session)
    out = await field_memory.suggestions_for(session, project_id=pid, kind="rfi")
    expected = (datetime.now(UTC).date() + timedelta(days=7)).isoformat()
    assert out["fields"]["Response required by"]["default"] == expected


@pytest.mark.asyncio
async def test_a_pasted_table_is_never_offered_as_a_one_click_suggestion(
    session: AsyncSession,
) -> None:
    """A materials table pasted into one RFQ must not appear in a
    pick-list under a site-contact box."""
    pid = await _project(session)
    fields = dict(RFQ_FIELDS, **{"Materials / scope required": "Item\tQty\nLadder\t24"})
    await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=fields)
    out = await field_memory.suggestions_for(session, project_id=pid, kind="rfq")
    assert "Materials / scope required" not in out["fields"]


@pytest.mark.asyncio
async def test_another_jobs_address_is_never_suggested(session: AsyncSession) -> None:
    """Project-scoped on purpose: a delivery address from another job is
    a way to send switchboards to the wrong site."""
    other = await _project(session)
    await service.raise_item(session, project_id=other, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    mine = await _project(session)
    out = await field_memory.suggestions_for(session, project_id=mine, kind="rfq")
    assert "12 Site Rd, Wetherill Park" not in str(out)
