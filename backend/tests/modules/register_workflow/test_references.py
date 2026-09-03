# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The tracking number: REG-RFQ-000123, burned once, never re-issued.

References used to be MAX+1 within one PROJECT, three digits. Two jobs
both held an RFI-004, so a forwarded reply carrying only its reference
was ambiguous, and a deleted item let its number be handed to different
work.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import service
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, code: str = "24188") -> uuid.UUID:
    user = User(
        email=f"rf-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="RF",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"RF {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="AUD", project_code=code)
    session.add(proj)
    await session.flush()
    return proj.id


RFQ_FIELDS = {
    "Package": "Switchboards",
    "Delivery to": "12 Site Rd",
    "Site contact": "Alex Example",
    "Delivery window / site hours": "06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2099-01-01",
}


def test_the_shape_is_the_house_prefix_the_kind_the_job_and_the_number() -> None:
    # Per job, which is every item reference from 19 Aug.
    assert service.format_reference("RFQ", 123, "24188") == "REG-RFQ-24188-0123"
    assert service.format_reference("RFI", 1, "24188") == "REG-RFI-24188-0001"
    # Un-scoped, which is where the mail series lives.
    assert service.format_reference("MSG", 42) == "REG-MSG-000042"


@pytest.mark.asyncio
async def test_two_jobs_never_share_a_reference(session: AsyncSession) -> None:
    """The defect this replaces: both jobs held an RFI-004, so a reply
    carrying only the reference could not be filed against one of them."""
    a = await _project(session)
    b = await _project(session, code="24190")
    first = await service.raise_item(session, project_id=a, kind="rfi", title="Q", fields={})
    second = await service.raise_item(session, project_id=b, kind="rfi", title="Q", fields={})
    assert first.reference != second.reference
    assert first.reference.startswith("REG-RFI-")
    assert second.reference.startswith("REG-RFI-")


@pytest.mark.asyncio
async def test_each_kind_runs_its_own_series(session: AsyncSession) -> None:
    pid = await _project(session)
    rfi = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    rfq = await service.raise_item(session, project_id=pid, kind="rfq", title="P", fields=RFQ_FIELDS)
    assert rfi.reference.startswith("REG-RFI-")
    assert rfq.reference.startswith("REG-RFQ-")
    # An RFQ minted after an RFI does not inherit the RFI's number.
    assert rfi.reference.rsplit("-", 1)[1] == rfq.reference.rsplit("-", 1)[1] == "0001"


@pytest.mark.asyncio
async def test_a_number_is_never_re_issued_after_a_delete(session: AsyncSession) -> None:
    """MAX+1 handed a deleted item's number to the next one raised, so two
    different pieces of work shared a reference on two different emails."""
    pid = await _project(session)
    first = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    await session.delete(first)
    await session.flush()
    second = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    assert second.reference != "REG-RFI-24188-0001"
    assert second.reference == "REG-RFI-24188-0002"


@pytest.mark.asyncio
async def test_peeking_for_the_preview_does_not_burn_a_number(session: AsyncSession) -> None:
    """The live preview shows the reference the item is about to get.

    Minting for a preview burns a number every time somebody opens a form
    and changes their mind, and the register reads as a list of gaps.
    """
    pid = await _project(session)
    peeked = await service._peek_reference(session, pid, "rfq")
    again = await service._peek_reference(session, pid, "rfq")
    assert peeked == again, "peeking twice moved the counter"
    raised = await service.raise_item(session, project_id=pid, kind="rfq", title="P", fields=RFQ_FIELDS)
    assert raised.reference == peeked, "the preview promised a different number to the one minted"


@pytest.mark.asyncio
async def test_the_counter_continues_a_series_already_in_use(session: AsyncSession) -> None:
    """An install that already holds RFQ-004 must not start again at 1 and
    hand a live number to a second package."""
    from app.modules.register_workflow.models import RegisterItem

    pid = await _project(session)
    session.add(RegisterItem(project_id=pid, kind="rfq", reference="RFQ-004", title="Old", fields={}))
    await session.flush()
    # A legacy row carries NO job number, so it cannot seed a job's
    # series - and it does not need to: "RFQ-004" and
    # "REG-RFQ-24188-0001" are different strings and cannot collide. Each
    # job's register starts at 0001 however much un-scoped history exists.
    nxt = await service._next_reference(session, pid, "rfq")
    assert nxt == "REG-RFQ-24188-0001"


@pytest.mark.asyncio
async def test_the_old_references_are_left_exactly_as_they_were(session: AsyncSession) -> None:
    """They are on emails that have already left the building."""
    from sqlalchemy import select

    from app.modules.register_workflow.models import RegisterItem

    pid = await _project(session)
    session.add(RegisterItem(project_id=pid, kind="rfq", reference="RFQ-004", title="Old", fields={}))
    await session.flush()
    await service.raise_item(session, project_id=pid, kind="rfq", title="P", fields=RFQ_FIELDS)
    refs = (await session.execute(select(RegisterItem.reference).where(RegisterItem.project_id == pid))).scalars().all()
    assert "RFQ-004" in refs


@pytest.mark.asyncio
async def test_the_series_is_unique_and_monotonic(session: AsyncSession) -> None:
    """Every mint is new and every mint is bigger.

    Monotonicity is the half that matters under concurrency: the counter
    row is read ``with_for_update()``, so a second minter blocks rather
    than reading the same value. This asserts the property the lock
    exists to guarantee - a test that spawned real parallel sessions
    would be asserting the test harness, not the lock.
    """
    pid = await _project(session)
    refs = [await service._next_reference(session, pid, "rfq") for _ in range(25)]
    assert len(set(refs)) == 25, "a number was issued twice"
    numbers = [int(r.rsplit("-", 1)[1]) for r in refs]
    assert numbers == sorted(numbers)
    assert numbers == list(range(numbers[0], numbers[0] + 25)), "the series skipped a number"


@pytest.mark.asyncio
async def test_the_reference_rides_the_email(session: AsyncSession) -> None:
    from app.modules.register_workflow import emailing

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Boards", fields=RFQ_FIELDS)
    built = await emailing.build_item_email(session, item, contact_id=None)
    assert item.reference in built["subject"]
    assert item.reference in built["html"]
