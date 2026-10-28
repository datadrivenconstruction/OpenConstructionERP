# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The recurring-schedule register fills, and fills the projects still empty.

The service module's recurring schedules tab is a real screen with a real
backend, and every demo project opened it on an empty table, so the feature read
as unbuilt. ``seed_service_recurring_schedules`` fills it.

What is worth asserting is less that rows appear than *when* they appear. The
module's other seeder returns early as soon as any service contract exists,
which on an install that has been seeded once is always. A register wired into
that function would therefore only ever show up on a database that started
empty, which is no running deployment. This seeder asks the question per project
instead, so the tests below check both halves of that: a project that already
has a schedule is left exactly as it was, and a project that is still empty is
filled on the same run.

``next_run_at`` is checked against the library rather than against a date typed
into the test, because a seeded row whose next run disagrees with its own rule
is a row the cron worker will materialise at the wrong time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.modules.projects.models import Project
from app.modules.service.models import ServiceContract, ServiceRecurringSchedule
from app.modules.service.seed import (
    _RECURRING_PER_PROJECT,
    _RECURRING_SPECS,
    seed_service_recurring_schedules,
)
from app.modules.users.models import User

_PRIORITIES = {"low", "med", "high", "critical"}


@pytest.fixture
async def owner(pg_session):
    """A user to own the projects; ``Project.owner_id`` is a real foreign key."""
    row = User(
        email=f"recurring-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Recurring schedule owner",
    )
    pg_session.add(row)
    await pg_session.flush()
    return row


async def _project(session, owner_row, name: str) -> uuid.UUID:
    project = Project(name=name, owner_id=owner_row.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project.id


async def _contract(session, pid: uuid.UUID, number: str) -> uuid.UUID:
    """The contract each occurrence stamps its ticket against."""
    contract = ServiceContract(
        customer_id=uuid.uuid4(),
        project_id=pid,
        contract_number=number,
        title="Service contract - reference",
        period_start="2026-01-01",
        period_end="2026-12-31",
        sla_tier="gold",
        status="active",
        currency="EUR",
    )
    session.add(contract)
    await session.flush()
    return contract.id


async def _schedules(session, pid: uuid.UUID) -> list[ServiceRecurringSchedule]:
    rows = await session.execute(select(ServiceRecurringSchedule).where(ServiceRecurringSchedule.project_id == pid))
    return list(rows.scalars().all())


# ── The register fills ──────────────────────────────────────────────────────


async def test_a_project_with_a_contract_gets_a_register(pg_session, owner) -> None:
    """Three rules, all bound to the project's contract, all ready to run."""
    pid = await _project(pg_session, owner, "Recurring register project")
    contract_id = await _contract(pg_session, pid, "SC-01")

    report = await seed_service_recurring_schedules(pg_session, [pid])
    assert report["recurring_schedules"] == _RECURRING_PER_PROJECT

    rows = await _schedules(pg_session, pid)
    assert len(rows) == _RECURRING_PER_PROJECT
    assert {r.contract_id for r in rows} == {contract_id}
    assert all(r.name for r in rows), "a rule with no name is a blank row on the tab"
    assert len({r.name for r in rows}) == _RECURRING_PER_PROJECT, "the same rule was seeded twice"

    for row in rows:
        template = row.template_ticket_data
        assert template.get("contract_id") == str(contract_id), (
            "the materialiser reads the contract from the template, so a rule without one cannot stamp a ticket"
        )
        assert template.get("priority") in _PRIORITIES
        assert template.get("title")


async def test_the_register_shows_both_enabled_states(pg_session, owner) -> None:
    """A column that reads the same all the way down teaches nothing.

    The tab has an enable toggle, and a register where every row is on never
    shows what a paused rule looks like.
    """
    pid = await _project(pg_session, owner, "Recurring both states project")
    await _contract(pg_session, pid, "SC-02")
    await seed_service_recurring_schedules(pg_session, [pid])

    states = {r.enabled for r in await _schedules(pg_session, pid)}
    assert states == {True, False}, f"expected both states in the register, found {states}"


async def test_next_run_agrees_with_the_rule(pg_session, owner) -> None:
    """A seeded next run must be the one the rule actually produces.

    Checked against dateutil rather than a date written into this test: a row
    whose ``next_run_at`` disagrees with its own RRULE is a row the cron worker
    materialises at the wrong time, and nothing else in the system would notice.
    """
    from dateutil.rrule import rrulestr

    pid = await _project(pg_session, owner, "Recurring next run project")
    await _contract(pg_session, pid, "SC-03")
    before = datetime.now(UTC)
    await seed_service_recurring_schedules(pg_session, [pid])
    after = datetime.now(UTC)

    for row in await _schedules(pg_session, pid):
        assert row.next_run_at, f"{row.name} has no next run, so it never fires"
        nxt = datetime.fromisoformat(row.next_run_at)
        assert nxt > before, "the next run is already in the past"
        # The rule is evaluated from the seed's own clock, so recomputing from
        # either end of the window it ran in must give the same answer.
        expected = {rrulestr(f"RRULE:{row.rrule}", dtstart=edge).after(edge).isoformat() for edge in (before, after)}
        assert row.next_run_at in expected, f"{row.name}: {row.next_run_at} is not what {row.rrule} produces"


# ── Twice-safe, and per project rather than on the first one ────────────────


async def test_a_second_run_changes_nothing(pg_session, owner) -> None:
    """Re-seeding leaves the register exactly as it was."""
    pid = await _project(pg_session, owner, "Recurring twice project")
    await _contract(pg_session, pid, "SC-04")
    await seed_service_recurring_schedules(pg_session, [pid])
    before = {(r.id, r.name, r.next_run_at, r.enabled) for r in await _schedules(pg_session, pid)}

    report = await seed_service_recurring_schedules(pg_session, [pid])

    assert report["recurring_schedules"] == 0
    assert report["projects_skipped"] == 1
    assert {(r.id, r.name, r.next_run_at, r.enabled) for r in await _schedules(pg_session, pid)} == before


async def test_a_full_project_does_not_block_an_empty_one(pg_session, owner) -> None:
    """The seeder asks per project, which is the whole reason it is separate.

    Guarding on the first project instead would mean that once the flagship has
    a register, no project seeded later ever gets one. That is the failure this
    module's other seeder has, and copying it here would leave the tab empty on
    every project added after the first run.
    """
    full = await _project(pg_session, owner, "Recurring already full project")
    await _contract(pg_session, full, "SC-05")
    await seed_service_recurring_schedules(pg_session, [full])
    full_before = {r.id for r in await _schedules(pg_session, full)}
    assert full_before

    empty = await _project(pg_session, owner, "Recurring still empty project")
    await _contract(pg_session, empty, "SC-06")

    report = await seed_service_recurring_schedules(pg_session, [full, empty])

    assert report["recurring_schedules"] == _RECURRING_PER_PROJECT
    assert report["projects_skipped"] == 1
    assert {r.id for r in await _schedules(pg_session, full)} == full_before, "the full project was rewritten"
    assert len(await _schedules(pg_session, empty)) == _RECURRING_PER_PROJECT


# ── Nothing that cannot work ────────────────────────────────────────────────


async def test_a_project_without_a_contract_is_left_alone(pg_session, owner) -> None:
    """Every occurrence stamps a ticket against a contract.

    Seeding rules for a project that has none would fill the tab with rows that
    fail the moment the cron worker reaches them, which is worse than the empty
    tab it replaces.
    """
    pid = await _project(pg_session, owner, "Recurring no contract project")

    report = await seed_service_recurring_schedules(pg_session, [pid])

    assert report["recurring_schedules"] == 0
    assert report["projects_skipped"] == 1
    assert await _schedules(pg_session, pid) == []


async def test_no_projects_is_not_an_error(pg_session) -> None:
    """A caller whose demo-project discovery failed hands over an empty list."""
    report = await seed_service_recurring_schedules(pg_session, [])
    assert report == {"recurring_schedules": 0, "projects_skipped": 0}


# ── The text is text a customer can read ────────────────────────────────────


def test_the_wordings_are_the_job_not_the_software() -> None:
    """The names go on a maintenance register, so they read like one.

    A stored name is data, but it is data a customer reads on a screen, and the
    estate's other registers were rewritten once already to stop saying "demo".
    """
    assert len(_RECURRING_SPECS) >= _RECURRING_PER_PROJECT, (
        "fewer rules than a project takes would repeat one inside a single register"
    )
    for name, rrule, priority, description in _RECURRING_SPECS:
        assert "demo" not in name.lower(), f"{name!r} names this product's demo estate"
        assert "demo" not in description.lower()
        assert len(name) <= 200, "the column is String(200)"
        assert len(rrule) <= 200
        assert rrule.startswith("FREQ="), f"{rrule!r} is not an RRULE body"
        assert priority in _PRIORITIES
