# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Correcting a raised item - and the money rail that rides on it.

A typo'd quantity or due date used to be permanent: the update endpoint
existed and was fully typed, but nothing in the UI ever called it. Making
it reachable is only safe once the estimate cannot be walked downward,
because the quote gate tiers off that figure.
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


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"ed-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="ED",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"ED {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="AUD",
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj.id


RFQ_FIELDS = {
    "Package": "Switchboards",
    "Delivery to": "12 Site Rd, Wetherill Park",
    "Site contact": "Alex Example 0400 000 000",
    "Delivery window / site hours": "Site hours 06:30-14:30",
    "Estimated value $": "50000",
    "Quotes due": "2099-01-01",
}


@pytest.mark.asyncio
async def test_a_typo_can_be_corrected(session: AsyncSession) -> None:
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    await service.update_item(
        session,
        item,
        title="MSB-01 switchboard supply",
        fields=dict(RFQ_FIELDS, **{"Site contact": "Alex Example 0400 111 222"}),
    )
    assert item.title == "MSB-01 switchboard supply"
    assert item.fields["Site contact"] == "Alex Example 0400 111 222"


@pytest.mark.asyncio
async def test_a_corrected_deadline_moves_the_due_date(session: AsyncSession) -> None:
    """The due date is derived, so an edit that misses it leaves the
    register reporting against a date nobody agreed to."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    assert item.due_date == "2099-01-01"
    await service.update_item(session, item, fields=dict(RFQ_FIELDS, **{"Quotes due": "2026-09-15"}))
    assert item.due_date == "2026-09-15"


@pytest.mark.asyncio
async def test_an_edit_cannot_rewrite_the_send_log(session: AsyncSession) -> None:
    """The send log is what the quote rule counts "asked" from. An edit
    that could forge it could manufacture a passing gate."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    await service.update_item(
        session,
        item,
        fields=dict(RFQ_FIELDS, _send_log=[{"contact": "forged", "date": "2026-01-01"}]),
    )
    assert not (item.fields or {}).get("_send_log")


def _asked(fields: dict) -> dict:
    """Fields carrying a send log - i.e. an RFQ that has actually gone out.

    The native rail keys off the RFQ status, and this module creates its
    RFQs as "published" the moment the item is raised, before any email
    exists. The send log is what "out with suppliers" actually means here.
    """
    from app.modules.register_workflow.emailing import SEND_LOG_KEY

    return dict(
        fields,
        **{SEND_LOG_KEY: [{"contact_name": "Alpha Electrical", "date": "18/08/2026"}]},
    )


@pytest.mark.asyncio
async def test_the_estimate_cannot_be_walked_down_once_it_has_gone_out(
    session: AsyncSession,
) -> None:
    """The gate bypass this endpoint would otherwise have opened.

    The native RFQ screen has refused a downward correction since the
    stress pass. Editing the register item reached the same figure by a
    different door - and a rail enforced in one code path is not a rail.
    """
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    assert item.linked_entity_id, "the item should have a native RFQ behind it"
    # Send it to somebody: now the figure is on an email that has left.
    item.fields = _asked(dict(item.fields or {}))
    await session.flush()

    with pytest.raises(service.WorkflowError) as exc:
        await service.update_item(session, item, fields=_asked(dict(RFQ_FIELDS, **{"Estimated value $": "100"})))
    assert "reduced" in str(exc.value).lower()
    # And the register still holds the real figure.
    assert item.fields["Estimated value $"] == "50000"


@pytest.mark.asyncio
async def test_the_estimate_can_always_be_raised(session: AsyncSession) -> None:
    """Upward is safe: it can only ever ask for MORE quotes."""
    from app.modules.rfq_bidding.models import RFQ

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    item.fields = _asked(dict(item.fields or {}))
    await session.flush()

    await service.update_item(session, item, fields=_asked(dict(RFQ_FIELDS, **{"Estimated value $": "90000"})))
    assert item.fields["Estimated value $"] == "90000"
    # And the NATIVE record moved with it - the gate reads that, not the
    # register's copy, so leaving it behind would tier off a stale figure.
    rfq = await session.get(RFQ, uuid.UUID(item.linked_entity_id or ""))
    assert rfq is not None
    await session.refresh(rfq)
    assert (rfq.metadata_ or {}).get("estimated_value") == "90000"


@pytest.mark.asyncio
async def test_a_package_nobody_has_been_asked_about_is_freely_editable(
    session: AsyncSession,
) -> None:
    """Nothing has been sent, so the estimate is still a guess.

    This module marks its native RFQ "published" at raise time, before a
    single email exists. Applying the native rail on that flag alone
    locked the figure seconds after it was typed, with no way back but
    cancelling the package - the same "no legitimate exit" shape as a
    gate that cannot be taken off a workflow.
    """
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="MSB-01", fields=RFQ_FIELDS)
    await service.update_item(session, item, fields=dict(RFQ_FIELDS, **{"Estimated value $": "100"}))
    assert item.fields["Estimated value $"] == "100"
