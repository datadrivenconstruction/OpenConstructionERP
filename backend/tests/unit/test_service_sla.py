"""‌⁠‍Unit tests for T10 — Service SLA timer + recurring schedules.

Covers:
    * compute_sla_due() priority lookup (urgent/critical/high/normal/med/low).
    * check_breaches() stamps sla_breached_at + emits service.sla.breached.
    * check_breaches() is idempotent — re-runs don't re-stamp.
    * create_recurring() persists + computes first next_run_at.
    * materialize_recurring() creates a ticket and advances next_run_at.
    * materialize_recurring() refuses to run a disabled schedule unless forced.

Uses an in-memory SQLite engine to exercise the real SQLAlchemy paths the
service relies on (``select(...).where(sla_breached_at.is_(None))``,
``recurring_repo.update_fields(...)``) — stubbing those out would test the
test, not the production code.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import AsyncIterator
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.service.models import (
    ServiceContract,
    ServiceRecurringSchedule,
    ServiceTicket,
)
from app.modules.service.schemas import (
    RecurringScheduleCreate,
)
from app.modules.service.service import (
    ServiceService,
    compute_sla_due,
    priority_sla_minutes,
)

# ── Async DB fixture ─────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test in-memory SQLite session.

    Uses ``StaticPool`` semantics implicitly via ``:memory:`` + a single
    connection lifecycle — each test gets a fresh DB so order can't leak.
    """
    # ``shared cache`` keeps the schema across coroutines on the same engine.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def contract(session: AsyncSession) -> ServiceContract:
    """A minimal active contract for tickets/schedules to hang off."""
    row = ServiceContract(
        customer_id=uuid.uuid4(),
        contract_number="SC-T10-0001",
        title="T10 fixture",
        period_start="2026-01-01",
        period_end="2026-12-31",
        sla_tier="standard",
        status="active",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


# ── compute_sla_due ──────────────────────────────────────────────────────


def test_priority_sla_minutes_matches_spec_table() -> None:
    """Priority lookup table: urgent=4h, high=8h, normal=24h, low=72h."""
    assert priority_sla_minutes("urgent") == 4 * 60
    # The existing schema vocab (critical) maps to the same 4h bucket as
    # urgent so the two vocabularies stay interchangeable.
    assert priority_sla_minutes("critical") == 4 * 60
    assert priority_sla_minutes("high") == 8 * 60
    assert priority_sla_minutes("normal") == 24 * 60
    assert priority_sla_minutes("med") == 24 * 60
    assert priority_sla_minutes("low") == 72 * 60
    # Unknown values fall back to ``normal`` rather than going SLA-immortal.
    assert priority_sla_minutes("bogus") == 24 * 60
    assert priority_sla_minutes(None) == 24 * 60


def test_compute_sla_due_priority_table() -> None:
    """compute_sla_due() == reported_at + priority window."""
    reported = datetime(2026, 5, 20, 9, 0, tzinfo=UTC)
    ticket = ServiceTicket(
        contract_id=uuid.uuid4(),
        ticket_number="T-001",
        priority="urgent",
        reported_at=reported.isoformat(),
        status="new",
    )
    assert compute_sla_due(ticket) == reported + timedelta(hours=4)

    ticket.priority = "high"
    assert compute_sla_due(ticket) == reported + timedelta(hours=8)

    ticket.priority = "low"
    assert compute_sla_due(ticket) == reported + timedelta(hours=72)


# ── check_breaches ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_breaches_stamps_overdue_tickets(
    session: AsyncSession,
    contract: ServiceContract,
) -> None:
    """Tickets past sla_due_at get sla_breached_at stamped and event emitted."""
    past_due = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    fresh_due = (datetime.now(UTC) + timedelta(hours=10)).isoformat()

    overdue = ServiceTicket(
        contract_id=contract.id,
        ticket_number="T-OVR-1",
        title="Overdue",
        priority="high",
        reported_at="2026-05-01T00:00:00+00:00",
        sla_due_at=past_due,
        status="in_progress",
    )
    fresh = ServiceTicket(
        contract_id=contract.id,
        ticket_number="T-OK-1",
        title="Fresh",
        priority="med",
        reported_at="2026-05-20T00:00:00+00:00",
        sla_due_at=fresh_due,
        status="new",
    )
    session.add_all([overdue, fresh])
    await session.commit()

    svc = ServiceService(session)

    with patch("app.modules.service.service.event_bus.publish_detached") as bus:
        result = await svc.check_breaches()

    assert result.newly_breached == 1
    assert result.total_breached == 1
    assert result.breached_ticket_ids == [overdue.id]

    # Verify DB state: the overdue ticket now carries sla_breached_at, the
    # fresh one is untouched.
    await session.refresh(overdue)
    await session.refresh(fresh)
    assert overdue.sla_breached_at is not None
    assert fresh.sla_breached_at is None

    # Event fan-out.
    event_names = [call.args[0] for call in bus.call_args_list]
    assert event_names == ["service.sla.breached"]


@pytest.mark.asyncio
async def test_check_breaches_idempotent(
    session: AsyncSession,
    contract: ServiceContract,
) -> None:
    """Re-running check_breaches() does not re-stamp already-breached tickets."""
    past_due = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    ticket = ServiceTicket(
        contract_id=contract.id,
        ticket_number="T-IDEM-1",
        title="X",
        priority="high",
        reported_at="2026-05-01T00:00:00+00:00",
        sla_due_at=past_due,
        status="new",
    )
    session.add(ticket)
    await session.commit()

    svc = ServiceService(session)
    with patch("app.modules.service.service.event_bus.publish_detached"):
        first = await svc.check_breaches()
    assert first.newly_breached == 1

    await session.refresh(ticket)
    first_stamp = ticket.sla_breached_at
    assert first_stamp is not None

    # Second run: stamp is preserved, count is zero, event is NOT re-emitted.
    with patch("app.modules.service.service.event_bus.publish_detached") as bus:
        second = await svc.check_breaches()
    assert second.newly_breached == 0
    # total_breached still counts the existing breach so the dashboard
    # number stays accurate across polls.
    assert second.total_breached == 1
    assert bus.call_count == 0

    await session.refresh(ticket)
    assert ticket.sla_breached_at == first_stamp


# ── Recurring schedules ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_recurring_computes_next_run_at(
    session: AsyncSession,
    contract: ServiceContract,
) -> None:
    """Daily RRULE schedule gets a next_run_at within the next 24h."""
    svc = ServiceService(session)

    with patch("app.modules.service.service.event_bus.publish_detached"):
        sched = await svc.create_recurring(
            RecurringScheduleCreate(
                name="Daily AHU inspection",
                rrule="FREQ=DAILY;INTERVAL=1",
                contract_id=contract.id,
                template_ticket_data={
                    "contract_id": str(contract.id),
                    "title": "Daily AHU walk-around",
                    "priority": "normal",
                },
                enabled=True,
            ),
        )

    assert sched.name == "Daily AHU inspection"
    assert sched.next_run_at is not None
    first_due = datetime.fromisoformat(sched.next_run_at)
    now = datetime.now(UTC)
    # FREQ=DAILY anchored at "now" yields a candidate exactly one day later.
    delta = first_due - now
    assert timedelta(hours=23, minutes=50) <= delta <= timedelta(hours=24, minutes=5)


@pytest.mark.asyncio
async def test_materialize_recurring_advances_next_run_at(
    session: AsyncSession,
    contract: ServiceContract,
) -> None:
    """Materialise: ticket created, last_run_at set, next_run_at advanced by one period."""
    svc = ServiceService(session)

    # Seed an overdue schedule so materialise() runs without ``force=True``.
    overdue = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    sched_row = ServiceRecurringSchedule(
        contract_id=contract.id,
        name="Weekly elevator check",
        rrule="FREQ=WEEKLY",
        template_ticket_data={
            "contract_id": str(contract.id),
            "title": "Weekly elevator inspection",
            "priority": "med",
        },
        next_run_at=overdue,
        enabled=True,
    )
    session.add(sched_row)
    await session.commit()
    await session.refresh(sched_row)
    before_next_run = sched_row.next_run_at
    assert before_next_run is not None

    with patch("app.modules.service.service.event_bus.publish_detached"):
        result = await svc.materialize_recurring(sched_row.id, user_id="dispatcher")

    assert result.materialized is True
    assert result.ticket_id is not None
    assert result.next_run_at is not None
    # Next run is exactly one week after the previous next_run_at anchor.
    advanced = datetime.fromisoformat(result.next_run_at)
    anchor = datetime.fromisoformat(before_next_run)
    assert timedelta(days=6, hours=23) <= (advanced - anchor) <= timedelta(days=7, hours=1)

    # Schedule row mirrors the response.
    await session.refresh(sched_row)
    assert sched_row.last_run_at is not None
    assert sched_row.next_run_at == result.next_run_at

    # Ticket links back to the schedule + carries source=auto_ppm.
    ticket = await session.get(ServiceTicket, result.ticket_id)
    assert ticket is not None
    assert ticket.recurring_schedule_id == sched_row.id
    assert ticket.source == "auto_ppm"


@pytest.mark.asyncio
async def test_materialize_recurring_skips_disabled_unless_forced(
    session: AsyncSession,
    contract: ServiceContract,
) -> None:
    """Disabled schedules are skipped; force=True materialises anyway."""
    svc = ServiceService(session)
    overdue = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    sched_row = ServiceRecurringSchedule(
        contract_id=contract.id,
        name="Disabled quarterly",
        rrule="FREQ=MONTHLY;INTERVAL=3",
        template_ticket_data={
            "contract_id": str(contract.id),
            "title": "Quarterly review",
        },
        next_run_at=overdue,
        enabled=False,
    )
    session.add(sched_row)
    await session.commit()
    await session.refresh(sched_row)

    # Without force: short-circuit, no ticket.
    with patch("app.modules.service.service.event_bus.publish_detached"):
        skipped = await svc.materialize_recurring(sched_row.id)
    assert skipped.materialized is False
    assert skipped.ticket_id is None
    assert skipped.reason == "Schedule disabled"

    # With force=True: ticket created.
    with patch("app.modules.service.service.event_bus.publish_detached"):
        forced = await svc.materialize_recurring(sched_row.id, force=True)
    assert forced.materialized is True
    assert forced.ticket_id is not None
