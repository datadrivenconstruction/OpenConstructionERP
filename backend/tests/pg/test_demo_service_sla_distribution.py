# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The seeded service desk must not report a 100% SLA breach.

Every ticket the demo shipped had breached, which reads as a broken feature
rather than as a struggling contractor. Two independent causes:

* historical tickets carried a flat four-hour ``sla_due_at`` against a
  one-to-twenty-four-hour resolution, so roughly five in six breached by
  construction;
* open tickets were aged zero to seventy-two hours against a response window
  of fifteen to four hundred and eighty minutes, so nearly all of them were
  already overdue the moment they were written.

The distribution is a property of rows in a database, not of the generator's
return value, so it is checked here rather than beside the seeder. A unit test
over the draw function would pass even after the seeder stopped calling it.
See :data:`_BREACH_FLOOR` for why the bands are tight rather than generous.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.modules.service.models import ServiceContract, ServiceTicket
from app.modules.service.seed import seed_service_demo
from app.modules.service.service import compute_sla_response_and_resolution

# Statuses ``ServiceService.scan_sla_breaches`` treats as still running.
_OPEN_STATUSES = ("new", "assigned", "in_progress")

# Breach rate both queues have to land in. ``_SLA_OUTCOME_MIX`` in the seeder
# declares a 10% breach weight; the seeded estate realises 6.7% on the open
# queue (2 of 30) and 9.5% on the history (19 of 200).
#
# The margin is deliberately narrow. The seeder runs on ``random.Random(42)``,
# so these rates are not a sample, they are a fixed property of the code, and a
# wide band would buy no robustness at all - it would only leave room for a
# regression to hide in. The first version of this test allowed up to 35% and
# 30%, which caught the original all-red estate but would have passed a silent
# tripling of the breach rate.
#
# The intended consequence: changing ``_SLA_OUTCOME_MIX`` fails here. That is
# not friction to route around, it is the point. Anyone retuning the mix has to
# say what the demo estate should now look like, in this file, on purpose.
_BREACH_FLOOR = 0.03
_BREACH_CEILING = 0.17


def _iso(value: str | None) -> datetime | None:
    """Parse a stored ISO timestamp, or ``None`` when the column is empty."""
    return datetime.fromisoformat(value) if value else None


@pytest.fixture
async def seeded(pg_session):
    """Run the service demo seeder once and hand back its tickets."""
    await seed_service_demo(pg_session)
    await pg_session.flush()
    tickets = list((await pg_session.execute(select(ServiceTicket))).scalars().all())
    assert tickets, "seeder produced no tickets"
    return tickets


async def test_the_open_queue_is_not_entirely_overdue(seeded) -> None:
    """Most open tickets are inside their response window, a few are not."""
    now = datetime.now(tz=_iso(seeded[0].reported_at).tzinfo)
    open_tickets = [t for t in seeded if t.status in _OPEN_STATUSES]
    assert len(open_tickets) >= 10, f"only {len(open_tickets)} open tickets to judge"

    breached = [t for t in open_tickets if (_iso(t.sla_due_at) or now) < now]
    rate = len(breached) / len(open_tickets)
    assert _BREACH_FLOOR <= rate <= _BREACH_CEILING, (
        f"{rate:.1%} of the open queue is overdue, outside "
        f"{_BREACH_FLOOR:.0%}-{_BREACH_CEILING:.0%} (seeds at 6.7%, 2 of 30)"
    )


async def test_the_history_shows_mostly_met_slas(seeded) -> None:
    """Closed tickets are judged on the resolution clock and mostly meet it."""
    closed = [t for t in seeded if t.status == "closed" and t.resolved_at]
    assert len(closed) >= 100, f"only {len(closed)} closed tickets to judge"

    late = [t for t in closed if (due := _iso(t.resolution_due_at)) is not None and _iso(t.resolved_at) > due]
    rate = len(late) / len(closed)
    assert _BREACH_FLOOR <= rate <= _BREACH_CEILING, (
        f"{rate:.1%} of closed tickets missed resolution, outside "
        f"{_BREACH_FLOOR:.0%}-{_BREACH_CEILING:.0%} (seeds at 9.5%, 19 of 200)"
    )


async def test_no_ticket_is_resolved_before_it_was_raised(seeded) -> None:
    """reported <= resolved <= closed, on every row that has the columns."""
    for t in seeded:
        reported = _iso(t.reported_at)
        assert reported is not None, f"{t.ticket_number} has no reported_at"
        resolved = _iso(t.resolved_at)
        if resolved is not None:
            assert resolved >= reported, f"{t.ticket_number} resolved before it was reported"
        closed = _iso(t.closed_at)
        if closed is not None and resolved is not None:
            assert closed >= resolved, f"{t.ticket_number} closed before it was resolved"


async def test_both_sla_clocks_are_stamped(seeded) -> None:
    """The two-clock view has something to read on every seeded ticket."""
    missing = [t.ticket_number for t in seeded if not t.response_due_at or not t.resolution_due_at]
    assert not missing, f"{len(missing)} tickets carry no SLA clocks, e.g. {missing[:3]}"


async def test_a_ticket_is_measured_against_its_own_contract_tier(pg_session, seeded) -> None:
    """A bronze contract's ticket is not judged by silver's promise.

    The seeder resolved the tier as "gold, or else silver", so every bronze
    contract was measured against a four-hour response instead of eight. The
    windows only differ per tier, so a wrong tier is a wrong deadline.
    """
    contracts = {c.id: c for c in (await pg_session.execute(select(ServiceContract))).scalars().all()}
    from app.modules.service.models import SLADefinition

    slas = {s.id: s for s in (await pg_session.execute(select(SLADefinition))).scalars().all()}

    checked = 0
    for ticket in seeded:
        contract = contracts.get(ticket.contract_id)
        sla = slas.get(contract.sla_definition_id) if contract else None
        if sla is None:
            continue
        expected_response, expected_resolution = compute_sla_response_and_resolution(
            _iso(ticket.reported_at), sla, priority=ticket.priority
        )
        assert _iso(ticket.response_due_at) == expected_response, (
            f"{ticket.ticket_number} on tier {sla.name} carries the wrong response deadline"
        )
        assert _iso(ticket.resolution_due_at) == expected_resolution, (
            f"{ticket.ticket_number} on tier {sla.name} carries the wrong resolution deadline"
        )
        checked += 1
    assert checked >= 100, f"only {checked} tickets had a tier to check"


async def test_every_tier_is_actually_represented(pg_session, seeded) -> None:
    """Guard the assertion above: it proves nothing if only one tier is used."""
    from app.modules.service.models import SLADefinition

    contracts = {c.id: c for c in (await pg_session.execute(select(ServiceContract))).scalars().all()}
    slas = {s.id: s for s in (await pg_session.execute(select(SLADefinition))).scalars().all()}
    tiers = {
        slas[contracts[t.contract_id].sla_definition_id].name
        for t in seeded
        if t.contract_id in contracts and contracts[t.contract_id].sla_definition_id in slas
    }
    assert tiers >= {"gold", "silver", "bronze"}, f"only {sorted(tiers)} appear on seeded tickets"
