# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project-scoped service listing must filter in the query, not after it.

The Service module is mounted twice: flat at ``/service``, which is the
tenant-wide dispatcher view, and under ``/projects/:projectId/service``. The
second mount used to be a lie - the page loaded the same tenant-wide lists
and printed them under a project's name.

Contracts and tickets could already be scoped server-side. Work orders could
not: they carry no ``project_id``, the project is two joins away through the
ticket and the contract. The tempting fix is to narrow the loaded page in the
browser, and that is the case pinned here: the listing is paginated, so a
client-side narrowing takes the newest N work orders across the whole tenant
and only then drops the foreign ones. A quiet project then shows an empty tab
while its own work orders sit just past the page boundary.

Against real PostgreSQL because the filter is a two-hop join and because the
ordering it pages by is the thing under test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

#: Anchor for the synthetic timeline, so "newest" is decided by the test.
_BASE = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)


async def _make_project(session, name: str) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "service-scope@reference.example"
    owner = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Reference owner")
        session.add(owner)
        await session.flush()

    project = Project(name=name, owner_id=owner.id, country_code="DE", currency="EUR")
    session.add(project)
    await session.flush()
    return uuid.UUID(str(project.id))


async def _make_contract(session, project_id: uuid.UUID | None, number: str) -> uuid.UUID:
    from app.modules.service.models import ServiceContract

    contract = ServiceContract(
        customer_id=uuid.uuid4(),
        project_id=project_id,
        contract_number=number,
        title=f"Maintenance {number}",
        period_start="2026-01-01",
        period_end="2026-12-31",
        status="active",
    )
    session.add(contract)
    await session.flush()
    return uuid.UUID(str(contract.id))


async def _make_ticket(
    session,
    contract_id: uuid.UUID,
    number: str,
    *,
    status: str = "new",
    age_days: int = 1,
) -> uuid.UUID:
    from app.modules.service.models import ServiceTicket

    ticket = ServiceTicket(
        contract_id=contract_id,
        ticket_number=number,
        title=f"Ticket {number}",
        priority="med",
        status=status,
        reported_at=(_BASE - timedelta(days=age_days)).isoformat(),
    )
    session.add(ticket)
    await session.flush()
    return uuid.UUID(str(ticket.id))


async def _make_work_order(
    session,
    ticket_id: uuid.UUID,
    number: str,
    *,
    age_days: int,
    status: str = "scheduled",
) -> uuid.UUID:
    """One work order, aged explicitly so ``created_at`` ordering is decided here."""
    from app.modules.service.models import ServiceWorkOrder

    work_order = ServiceWorkOrder(
        ticket_id=ticket_id,
        work_order_number=number,
        status=status,
        created_at=_BASE - timedelta(days=age_days),
        updated_at=_BASE - timedelta(days=age_days),
    )
    session.add(work_order)
    await session.flush()
    return uuid.UUID(str(work_order.id))


def _repos(session):
    from app.modules.service.repository import TicketRepository, WorkOrderRepository

    return TicketRepository(session), WorkOrderRepository(session)


async def test_work_orders_for_a_project_exclude_every_other_contract(pg_session) -> None:
    """The two-hop join reaches the project and stops at its own contracts."""
    ours = await _make_project(pg_session, "Service scope ours")
    theirs = await _make_project(pg_session, "Service scope theirs")

    our_contract = await _make_contract(pg_session, ours, "SC-SCOPE-1")
    their_contract = await _make_contract(pg_session, theirs, "SC-SCOPE-2")
    # Post-handover maintenance with no project at all - the third kind of row.
    loose_contract = await _make_contract(pg_session, None, "SC-SCOPE-3")

    our_ticket = await _make_ticket(pg_session, our_contract, "T-SCOPE-1")
    their_ticket = await _make_ticket(pg_session, their_contract, "T-SCOPE-2")
    loose_ticket = await _make_ticket(pg_session, loose_contract, "T-SCOPE-3")

    mine = await _make_work_order(pg_session, our_ticket, "WO-SCOPE-1", age_days=1)
    await _make_work_order(pg_session, their_ticket, "WO-SCOPE-2", age_days=1)
    await _make_work_order(pg_session, loose_ticket, "WO-SCOPE-3", age_days=1)

    _, work_orders = _repos(pg_session)
    rows, total = await work_orders.list_for_project(ours, limit=50)

    assert [uuid.UUID(str(r.id)) for r in rows] == [mine]
    assert total == 1


async def test_a_quiet_project_is_not_paged_out_by_a_busy_one(pg_session) -> None:
    """The filter runs before the page, so an older project still answers.

    This is the assertion a client-side narrowing fails: the loud project owns
    every one of the newest rows, so the first page taken tenant-wide contains
    nothing of the quiet project's.
    """
    quiet = await _make_project(pg_session, "Service scope quiet")
    loud = await _make_project(pg_session, "Service scope loud")

    quiet_ticket = await _make_ticket(pg_session, await _make_contract(pg_session, quiet, "SC-QUIET"), "T-QUIET")
    loud_ticket = await _make_ticket(pg_session, await _make_contract(pg_session, loud, "SC-LOUD"), "T-LOUD")

    # The quiet project's only work order is the oldest row on the estate.
    quiet_wo = await _make_work_order(pg_session, quiet_ticket, "WO-QUIET", age_days=90)
    for index in range(5):
        await _make_work_order(pg_session, loud_ticket, f"WO-LOUD-{index}", age_days=index)

    _, work_orders = _repos(pg_session)
    rows, total = await work_orders.list_for_project(quiet, limit=2)

    assert [uuid.UUID(str(r.id)) for r in rows] == [quiet_wo]
    assert total == 1

    # And the tenant-wide view still sees everything it saw before.
    all_rows, all_total = await work_orders.list_all(limit=50)
    assert all_total >= 6
    assert quiet_wo in {uuid.UUID(str(r.id)) for r in all_rows}


async def test_the_project_branch_keeps_the_status_filter(pg_session) -> None:
    """A filter the endpoint accepts must not be dropped by the scoped branch."""
    project = await _make_project(pg_session, "Service scope status")
    contract = await _make_contract(pg_session, project, "SC-STATUS")
    ticket = await _make_ticket(pg_session, contract, "T-STATUS")

    await _make_work_order(pg_session, ticket, "WO-STATUS-OPEN", age_days=2, status="scheduled")
    done = await _make_work_order(pg_session, ticket, "WO-STATUS-DONE", age_days=1, status="completed")

    _, work_orders = _repos(pg_session)
    rows, total = await work_orders.list_for_project(project, limit=50, status="completed")

    assert [uuid.UUID(str(r.id)) for r in rows] == [done]
    assert total == 1


async def test_the_ticket_project_branch_keeps_status_and_priority(pg_session) -> None:
    """The same silent-drop, on the branch that shipped first.

    ``/tickets/`` takes ``status`` and ``priority`` whatever the caller scoped
    by, and the project branch used to ignore both.
    """
    project = await _make_project(pg_session, "Service scope tickets")
    contract = await _make_contract(pg_session, project, "SC-TICKETS")

    await _make_ticket(pg_session, contract, "T-OPEN", status="new")
    closed = await _make_ticket(pg_session, contract, "T-CLOSED", status="closed")

    tickets, _ = _repos(pg_session)
    rows, total = await tickets.list_for_project(project, limit=50, status="closed")

    assert [uuid.UUID(str(r.id)) for r in rows] == [closed]
    assert total == 1
