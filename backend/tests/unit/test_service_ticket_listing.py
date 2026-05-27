"""Regression tests for the Service & Maintenance ticket listing.

Pins the bug where ``GET /api/v1/service/tickets/`` with no ``contract_id``
and no ``project_id`` returned ``[]`` — which left the default ``/service``
Tickets tab (and the work-order create ticket picker) permanently empty.

Uses a per-test in-memory SQLite session with only the service tables
created (per ``feedback_test_isolation.md`` — production DB is never
touched). Mirrors the fixture style used by ``tests/unit/test_qms.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.projects.models import Project
from app.modules.service.models import (
    AssetInspectionChecklist,
    DebriefReport,
    ServiceAsset,
    ServiceContract,
    ServiceSchedule,
    ServiceTicket,
    ServiceWorkOrder,
    ServiceWorkOrderItem,
    SLADefinition,
)
from app.modules.service.repository import TicketRepository

# ServiceContract FKs oe_service_sla_definition; include the whole module's
# table set so create_all() resolves every intra-module FK.
_SERVICE_TABLES = [
    Project.__table__,
    SLADefinition.__table__,
    AssetInspectionChecklist.__table__,
    ServiceContract.__table__,
    ServiceAsset.__table__,
    ServiceTicket.__table__,
    ServiceWorkOrder.__table__,
    ServiceWorkOrderItem.__table__,
    DebriefReport.__table__,
    ServiceSchedule.__table__,
]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_SERVICE_TABLES)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()
    await engine.dispose()


async def _make_contract(session: AsyncSession) -> ServiceContract:
    contract = ServiceContract(
        customer_id=uuid.uuid4(),
        contract_number="SC-0001",
        title="Test",
        period_start="2026-01-01",
        period_end="2026-12-31",
    )
    session.add(contract)
    await session.flush()
    return contract


async def _make_ticket(
    session: AsyncSession,
    contract_id: uuid.UUID,
    *,
    number: str,
    status: str = "new",
    priority: str = "med",
    reported_at: str | None = None,
) -> ServiceTicket:
    ticket = ServiceTicket(
        contract_id=contract_id,
        ticket_number=number,
        title=f"Ticket {number}",
        priority=priority,
        reported_at=reported_at or datetime.now(UTC).isoformat(),
        status=status,
    )
    session.add(ticket)
    await session.flush()
    return ticket


@pytest.mark.asyncio
async def test_list_all_returns_tickets_across_contracts(
    session: AsyncSession,
) -> None:
    """The tenant-wide view returns every ticket regardless of contract."""
    c1 = await _make_contract(session)
    c2 = ServiceContract(
        customer_id=uuid.uuid4(),
        contract_number="SC-0002",
        title="Other",
        period_start="2026-01-01",
        period_end="2026-12-31",
    )
    session.add(c2)
    await session.flush()

    await _make_ticket(session, c1.id, number="T-00001")
    await _make_ticket(session, c2.id, number="T-00002")

    repo = TicketRepository(session)
    rows, total = await repo.list_all()

    assert total == 2
    assert {r.ticket_number for r in rows} == {"T-00001", "T-00002"}


@pytest.mark.asyncio
async def test_list_all_filters_by_status_and_priority(
    session: AsyncSession,
) -> None:
    c = await _make_contract(session)
    await _make_ticket(session, c.id, number="T-1", status="new", priority="low")
    await _make_ticket(
        session,
        c.id,
        number="T-2",
        status="in_progress",
        priority="high",
    )
    await _make_ticket(
        session,
        c.id,
        number="T-3",
        status="in_progress",
        priority="low",
    )

    repo = TicketRepository(session)

    rows, total = await repo.list_all(status="in_progress")
    assert total == 2
    assert {r.ticket_number for r in rows} == {"T-2", "T-3"}

    rows, total = await repo.list_all(priority="low")
    assert total == 2
    assert {r.ticket_number for r in rows} == {"T-1", "T-3"}

    rows, total = await repo.list_all(status="in_progress", priority="high")
    assert total == 1
    assert rows[0].ticket_number == "T-2"


@pytest.mark.asyncio
async def test_list_all_orders_by_reported_at_desc_and_paginates(
    session: AsyncSession,
) -> None:
    c = await _make_contract(session)
    base = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    # Oldest → newest.
    await _make_ticket(
        session,
        c.id,
        number="T-OLD",
        reported_at=base.isoformat(),
    )
    await _make_ticket(
        session,
        c.id,
        number="T-MID",
        reported_at=(base + timedelta(hours=1)).isoformat(),
    )
    await _make_ticket(
        session,
        c.id,
        number="T-NEW",
        reported_at=(base + timedelta(hours=2)).isoformat(),
    )

    repo = TicketRepository(session)

    rows, total = await repo.list_all(limit=2)
    assert total == 3
    # Newest first, page size honoured.
    assert [r.ticket_number for r in rows] == ["T-NEW", "T-MID"]

    rows, _ = await repo.list_all(offset=2, limit=2)
    assert [r.ticket_number for r in rows] == ["T-OLD"]


@pytest.mark.asyncio
async def test_list_all_empty_db_returns_empty(session: AsyncSession) -> None:
    repo = TicketRepository(session)
    rows, total = await repo.list_all()
    assert rows == []
    assert total == 0
