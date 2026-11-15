# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site prep demo seed - a mobilisation plan and its readiness register per project.

The module shipped complete and unseeded, so every screen it owns opened empty:
the readiness rollup had nothing to roll up, the commencement gate had no gates to
report on, and the category breakdown showed ten headings and no rows.

This writes what a project actually assembles before anyone starts work - access,
welfare, temporary power, hoarding, temporary works certificates, consents,
inductions - as one mobilisation plan per project with its readiness items hung
off it. Every item carries the ``plan_id`` of its own project's plan, which is
what makes the register a plan rather than a loose checklist: the plan's target
start date is the date the whole rollup counts down to.

Everything is written through :class:`SitePrepService` with a real
``SitePrepItemCreate`` payload, so each row passes the same Pydantic vocabulary
and the same in-project plan check as an item created from the API. A row this
seeder cannot write is a row the application would have refused.

Three things are derived rather than asserted, because a demo that states its own
conclusions stops being a demo of the engine:

  - Overdue is not a status. It falls out of a due date that has passed on an item
    that is not yet resolved, so the overdue list on the screen is computed by the
    readiness core from the dates seeded here.
  - The commencement gate is not a flag on the project. It is satisfied only when
    every gate item is ready or not applicable, so the projects that report a
    closed gate report it because their gate items really are closed.
  - Readiness percent counts ready items against applicable ones, so the items
    marked not applicable move the denominator the way they would on a real job.

Projects differ by the stage they are at, indexed by position in the seeding call
rather than drawn from the project id: a draw would hand two neighbouring demo
projects the same picture, and the stage is the first thing a reader sees. Within
a stage everything else comes from the project id, so re-seeding one project
reproduces it exactly.

Dates are anchored to the run date, never hardcoded, so a demo opened a year from
now still shows a site mobilising next month rather than one that mobilised in
2026.

Idempotent per project: a project that already carries a plan or an item is left
untouched, so a re-run never doubles the register.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import date, datetime, timedelta
from typing import Iterable, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_prep.models import SitePrepItem, SitePrepPlan
from app.modules.site_prep.schemas import (
    CategoryLiteral,
    ItemStatusLiteral,
    PlanStatusLiteral,
    SitePrepItemCreate,
    SitePrepPlanCreate,
)
from app.modules.site_prep.seed_text import site_prep_text
from app.modules.site_prep.service import SitePrepService

logger = logging.getLogger(__name__)

_SEED = 42


class _ChecklistEntry(TypedDict):
    """One line of the mobilisation checklist, before a project stages it.

    Typed rather than left as a loose dict so the entries stay plain dict
    literals - which is what lets the cross-module seed vocabulary gate read the
    category strings straight out of the source - while still being checkable.

    The vocabularies are the schema's own ``Literal`` aliases rather than ``str``,
    so a category this module does not offer is a type error where it is written
    instead of a 422 when the seeder runs.
    """

    category: CategoryLiteral
    title: str
    description: str
    is_gate: bool
    lead: int
    responsible_party: str


class _Stage(TypedDict):
    """How far through mobilisation a project is."""

    key: str
    plan_status: PlanStatusLiteral
    days_to_target: int
    progress: float
    blocked: int
    not_applicable: int


# The mobilisation checklist, in the order a site assembles it.
#
# ``lead`` is the number of days before the target start date the item is due, so
# the register sequences itself: the boundary and the power supply come long
# before the induction pack, and a project that is three weeks out is genuinely
# late on anything whose lead has already passed.
#
# ``gate`` marks a hard prerequisite to breaking ground. Deliberately few: a gate
# that covers everything answers nothing, and the screen exists to say which of a
# handful of things is still holding the start.
#
# Written to be true of a site anywhere. Statutory instruments differ by country,
# so an item names the thing every regime requires (a notification to the safety
# regulator, a permit displayed on site) rather than one country's form number.
_CHECKLIST: tuple[_ChecklistEntry, ...] = (
    # -- Consents and notifications, which lead everything else --------------
    {
        "category": "permits_consents",
        "title": "Building permit issued and displayed on site",
        "description": "Permit received from the authority, copy posted at the site entrance.",
        "is_gate": True,
        "lead": 56,
        "responsible_party": "Project manager",
    },
    {
        "category": "permits_consents",
        "title": "Notification of the works submitted to the safety regulator",
        "description": "Statutory notification lodged before mobilisation, acknowledgement filed.",
        "is_gate": True,
        "lead": 42,
        "responsible_party": "Project manager",
    },
    {
        "category": "permits_consents",
        "title": "Highway and footway licences obtained",
        "description": "Licences for the crossing, scaffold over the footway and any lane closure.",
        "is_gate": False,
        "lead": 35,
        "responsible_party": "Project manager",
    },
    {
        "category": "permits_consents",
        "title": "Utility diversion consents received",
        "description": "Consents from each utility whose apparatus is affected by the enabling works.",
        "is_gate": False,
        "lead": 30,
        "responsible_party": "Project manager",
    },
    {
        "category": "permits_consents",
        "title": "Construction phase health and safety plan issued",
        "description": "Plan issued to the client and the trades, revision controlled.",
        "is_gate": True,
        "lead": 21,
        "responsible_party": "HSE manager",
    },
    # -- Access ---------------------------------------------------------------
    {
        "category": "access",
        "title": "Site access route agreed with the highway authority",
        "description": "Approved route for construction traffic, including approach and egress.",
        "is_gate": True,
        "lead": 38,
        "responsible_party": "Site manager",
    },
    {
        "category": "access",
        "title": "Gate positions and delivery turning circle set out",
        "description": "Entrance and exit gates positioned, swept path checked against the largest vehicle.",
        "is_gate": False,
        "lead": 24,
        "responsible_party": "Site manager",
    },
    {
        "category": "access",
        "title": "Wheel wash and road sweeping arrangements in place",
        "description": "Wheel wash sited at the exit, sweeper booked for the haul route.",
        "is_gate": False,
        "lead": 12,
        "responsible_party": "Site manager",
    },
    # -- Security and boundary ------------------------------------------------
    {
        "category": "security_hoarding",
        "title": "Perimeter hoarding erected and signed",
        "description": "Continuous boundary to the full site, warning and information signage fixed.",
        "is_gate": True,
        "lead": 28,
        "responsible_party": "Site manager",
    },
    {
        "category": "security_hoarding",
        "title": "CCTV and out-of-hours monitoring commissioned",
        "description": "Cameras covering the gates and the compound, monitoring contract live.",
        "is_gate": False,
        "lead": 18,
        "responsible_party": "Site manager",
    },
    {
        "category": "security_hoarding",
        "title": "Access control and visitor booking in place",
        "description": "Turnstile or signing-in point operating, visitor pre-booking published.",
        "is_gate": False,
        "lead": 10,
        "responsible_party": "Site supervisor",
    },
    # -- Temporary utilities --------------------------------------------------
    {
        "category": "temporary_utilities",
        "title": "Temporary power supply energised",
        "description": "Builder's supply connected, distribution boards installed and tested.",
        "is_gate": True,
        "lead": 26,
        "responsible_party": "MEP contractor",
    },
    {
        "category": "temporary_utilities",
        "title": "Temporary water supply connected and tested",
        "description": "Standpipe and site main in service, sample taken for potability.",
        "is_gate": False,
        "lead": 22,
        "responsible_party": "MEP contractor",
    },
    {
        "category": "temporary_utilities",
        "title": "Temporary lighting to access routes and stairs",
        "description": "Task and route lighting installed, emergency lighting to the escape routes.",
        "is_gate": False,
        "lead": 14,
        "responsible_party": "MEP contractor",
    },
    {
        "category": "temporary_utilities",
        "title": "Site data and telephony live",
        "description": "Connectivity to the offices and the gatehouse, coverage checked on the deck.",
        "is_gate": False,
        "lead": 9,
        "responsible_party": "MEP contractor",
    },
    # -- Accommodation and welfare -------------------------------------------
    {
        "category": "accommodation_welfare",
        "title": "Welfare units in service before any work starts",
        "description": "Toilets, washing, drying room and canteen connected and stocked.",
        "is_gate": True,
        "lead": 16,
        "responsible_party": "Site manager",
    },
    {
        "category": "accommodation_welfare",
        "title": "Site offices sited and connected",
        "description": "Offices and meeting room positioned clear of the crane radius.",
        "is_gate": False,
        "lead": 20,
        "responsible_party": "Site manager",
    },
    {
        "category": "accommodation_welfare",
        "title": "First aid room equipped and first aiders on the register",
        "description": "Equipped room, named first aiders per shift, emergency numbers posted.",
        "is_gate": False,
        "lead": 8,
        "responsible_party": "HSE manager",
    },
    # -- Temporary works ------------------------------------------------------
    {
        "category": "temporary_works",
        "title": "Temporary works register opened and coordinator appointed",
        "description": "Register live, coordinator named in writing, design brief issued.",
        "is_gate": False,
        "lead": 34,
        "responsible_party": "Temporary works coordinator",
    },
    {
        "category": "temporary_works",
        "title": "Crane base design certificate issued",
        "description": "Design check certificate for the base and its bearing pressure received.",
        "is_gate": True,
        "lead": 25,
        "responsible_party": "Temporary works coordinator",
    },
    {
        "category": "temporary_works",
        "title": "Piling mat design and validation certificate received",
        "description": "Working platform designed to the rig loads, validation certificate filed.",
        "is_gate": False,
        "lead": 19,
        "responsible_party": "Temporary works coordinator",
    },
    {
        "category": "temporary_works",
        "title": "Excavation support scheme approved",
        "description": "Support to the bulk dig checked and approved before the first excavation.",
        "is_gate": False,
        "lead": 11,
        "responsible_party": "Temporary works coordinator",
    },
    # -- Environmental controls ----------------------------------------------
    {
        "category": "environmental_controls",
        "title": "Ecology survey completed and protected species signed off",
        "description": "Survey carried out in season, mitigation agreed before any clearance.",
        "is_gate": True,
        "lead": 45,
        "responsible_party": "Environmental manager",
    },
    {
        "category": "environmental_controls",
        "title": "Surface water discharge consent and silt management in place",
        "description": "Consent held, settlement tanks sized and sited, discharge point agreed.",
        "is_gate": False,
        "lead": 23,
        "responsible_party": "Environmental manager",
    },
    {
        "category": "environmental_controls",
        "title": "Dust and noise monitoring stations installed",
        "description": "Boundary monitors installed with trigger levels agreed with the authority.",
        "is_gate": False,
        "lead": 13,
        "responsible_party": "Environmental manager",
    },
    {
        "category": "environmental_controls",
        "title": "Waste segregation compound set out",
        "description": "Skips and segregation bays positioned, carrier and consignee registered.",
        "is_gate": False,
        "lead": 7,
        "responsible_party": "Environmental manager",
    },
    # -- Logistics and laydown ------------------------------------------------
    {
        "category": "logistics_laydown",
        "title": "Crane oversail agreements signed with the adjoining owners",
        "description": "Written consent for the jib to oversail each affected boundary.",
        "is_gate": True,
        "lead": 32,
        "responsible_party": "Commercial manager",
    },
    {
        "category": "logistics_laydown",
        "title": "Laydown areas and material storage allocated",
        "description": "Storage zones allocated per trade, loading bays kept clear of the access route.",
        "is_gate": False,
        "lead": 17,
        "responsible_party": "Logistics manager",
    },
    {
        "category": "logistics_laydown",
        "title": "Delivery management system published to the supply chain",
        "description": "Booking slots open, delivery rules issued to every subcontractor.",
        "is_gate": False,
        "lead": 6,
        "responsible_party": "Logistics manager",
    },
    {
        "category": "logistics_laydown",
        "title": "Traffic management plan issued to hauliers",
        "description": "Routes, holding areas and banksman positions issued and acknowledged.",
        "is_gate": False,
        "lead": 5,
        "responsible_party": "Logistics manager",
    },
    # -- Inductions and training ----------------------------------------------
    {
        "category": "inductions_training",
        "title": "Site induction pack written and approved",
        "description": "Induction covering the hazards, the rules and the emergency arrangements.",
        "is_gate": False,
        "lead": 15,
        "responsible_party": "HSE manager",
    },
    {
        "category": "inductions_training",
        "title": "Emergency and evacuation procedure briefed",
        "description": "Muster points set, procedure briefed and the first drill scheduled.",
        "is_gate": True,
        "lead": 4,
        "responsible_party": "HSE manager",
    },
    {
        "category": "inductions_training",
        "title": "Competence and training records collected for the first trades",
        "description": "Cards and tickets checked for every operative mobilising in the first weeks.",
        "is_gate": False,
        "lead": 3,
        "responsible_party": "HSE manager",
    },
    {
        "category": "inductions_training",
        "title": "Toolbox talk schedule published",
        "description": "Rolling schedule of talks agreed with each trade for the opening month.",
        "is_gate": False,
        "lead": 2,
        "responsible_party": "Site supervisor",
    },
    # -- Everything else ------------------------------------------------------
    {
        "category": "other",
        "title": "Pre-condition survey of the adjoining properties recorded",
        "description": "Photographic and written record agreed with each neighbour before work starts.",
        "is_gate": False,
        "lead": 40,
        "responsible_party": "Project manager",
    },
    {
        "category": "other",
        "title": "Neighbour notification letters issued",
        "description": "Letters issued with the working hours, the contact number and the start date.",
        "is_gate": False,
        "lead": 27,
        "responsible_party": "Project manager",
    },
)

# Where each project stands, indexed by its position in the seeding call.
#
# ``days_to_target`` is signed: positive counts down to a start that has not
# happened, negative is a site already running. ``progress`` is how far down the
# checklist the project has resolved, ``blocked`` how many of the rest are stuck,
# and ``not_applicable`` how many do not apply to this job at all.
#
# Overdue counts are absent on purpose. They emerge from ``days_to_target`` and
# the per-item lead times, which is the whole point of seeding dates instead of
# conclusions: a project nine days out with a third of the list open is late on
# everything with a longer lead, and the screen works that out for itself.
_STAGES: tuple[_Stage, ...] = (
    # Mid-mobilisation: the interesting one, so the flagship project gets it.
    {
        "key": "mobilising",
        "plan_status": "active",
        "days_to_target": 20,
        "progress": 0.55,
        "blocked": 1,
        "not_applicable": 2,
    },
    # Days from breaking ground and everything that gates the start is closed.
    {
        "key": "about_to_start",
        "plan_status": "active",
        "days_to_target": 4,
        "progress": 0.92,
        "blocked": 0,
        "not_applicable": 2,
    },
    # Pre-construction: the plan is a draft and most of the list is untouched.
    {
        "key": "planning",
        "plan_status": "draft",
        "days_to_target": 74,
        "progress": 0.14,
        "blocked": 0,
        "not_applicable": 1,
    },
    # Already on site; mobilisation closed out and the plan with it.
    {
        "key": "underway",
        "plan_status": "complete",
        "days_to_target": -38,
        "progress": 1.0,
        "blocked": 0,
        "not_applicable": 3,
    },
    # Start is close and three items are stuck, two of them gates: the case the
    # commencement-gate screen exists to answer.
    {
        "key": "at_risk",
        "plan_status": "active",
        "days_to_target": 9,
        "progress": 0.58,
        "blocked": 3,
        "not_applicable": 1,
    },
)

# Why an item is stuck. Attached as the item's note so the blocked list on the
# screen says something a reader can act on.
_BLOCKED_REASONS: tuple[str, ...] = (
    "Waiting on the authority; chased twice, no date given yet.",
    "Design information outstanding from the consultant.",
    "Adjoining owner has not returned the signed agreement.",
    "Utility provider cannot attend before the target start date.",
    "Survey could not be completed in season; revised window agreed.",
)

# Why an item does not apply here. A not-applicable item without a reason reads
# as an oversight rather than as a decision.
_NOT_APPLICABLE_REASONS: tuple[str, ...] = (
    "Not applicable: the site is served by the existing permanent supply.",
    "Not applicable: no adjoining boundary is oversailed on this site.",
    "Not applicable: works are wholly within the existing curtilage.",
    "Not applicable: no excavation below the founding level on this package.",
)

_READY: ItemStatusLiteral = "ready"
_IN_PROGRESS: ItemStatusLiteral = "in_progress"
_NOT_STARTED: ItemStatusLiteral = "not_started"
_BLOCKED: ItemStatusLiteral = "blocked"
_NOT_APPLICABLE: ItemStatusLiteral = "not_applicable"


def _rng_for(project_id: uuid.UUID) -> random.Random:
    """A deterministic RNG per project, so a re-seed reproduces the register."""
    return random.Random(f"{_SEED}:{project_id}")


def _ordered_checklist() -> list[_ChecklistEntry]:
    """The checklist in due-date order, longest lead first.

    Sorted here rather than kept sorted in the literal above so the source stays
    grouped by category, which is how it is read and edited, while the register
    is written in the order the site actually works through it.
    """
    return sorted(_CHECKLIST, key=lambda entry: (-entry["lead"], entry["title"]))


def _plan_statuses(
    rng: random.Random,
    stage: _Stage,
    total: int,
) -> list[ItemStatusLiteral]:
    """Decide each item's status, in checklist order.

    The resolved items are the ones with the longest lead, because that is the
    order a mobilisation is worked: the boundary and the power supply are closed
    out while the toolbox-talk schedule is still a draft. Blocked and
    not-applicable items are then drawn from the rest, so a stuck item is always
    one that is genuinely still open.
    """
    ready_through = round(total * stage["progress"])
    statuses: list[ItemStatusLiteral] = [_READY if i < ready_through else _NOT_STARTED for i in range(total)]

    open_indices = [i for i in range(total) if statuses[i] != _READY]

    # Not applicable is drawn from the whole list, not only the open tail: a job
    # decides an item does not apply to it early, and it stays that way.
    na_wanted = min(stage["not_applicable"], total)
    for index in rng.sample(range(total), k=na_wanted):
        statuses[index] = _NOT_APPLICABLE
        if index in open_indices:
            open_indices.remove(index)

    blocked_wanted = min(stage["blocked"], len(open_indices))
    for index in rng.sample(open_indices, k=blocked_wanted):
        statuses[index] = _BLOCKED
        open_indices.remove(index)

    # The two open items with the longest lead are the ones being worked on now.
    for index in open_indices[:2]:
        statuses[index] = _IN_PROGRESS
    return statuses


def _dates_for(
    rng: random.Random,
    *,
    status: ItemStatusLiteral,
    due: date,
    target: date,
) -> tuple[date | None, date | None]:
    """Return ``(due_date, completed_date)`` for one item.

    A resolved item is completed near its due date - usually a little before it,
    occasionally a little after, because a mobilisation that hit every date on
    the nose is not one anybody recognises. A completion is never dated in the
    future, so a project whose start is still weeks away cannot show work closed
    out on a day that has not happened.
    """
    if status == _NOT_APPLICABLE:
        # An item that does not apply carries no date to count down to; leaving a
        # due date on it would put it in the overdue list of a job it never
        # belonged to.
        return None, None
    if status != _READY:
        return due, None
    completed = (
        due - timedelta(days=rng.randint(0, 6)) if rng.random() < 0.75 else due + timedelta(days=rng.randint(1, 4))
    )
    today = datetime.now().date()
    if completed > today:
        completed = today
    # Never before the plan was conceivably opened.
    floor = target - timedelta(days=90)
    return due, max(completed, floor)


async def _already_seeded(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """True when the project already carries a plan or an item."""
    plan = (
        (await session.execute(select(SitePrepPlan.id).where(SitePrepPlan.project_id == project_id).limit(1)))
        .scalars()
        .first()
    )
    if plan is not None:
        return True
    item = (
        (await session.execute(select(SitePrepItem.id).where(SitePrepItem.project_id == project_id).limit(1)))
        .scalars()
        .first()
    )
    return item is not None


async def _seed_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    ordinal: int,
    locale: str | None = None,
) -> dict[str, int]:
    """Seed one project's mobilisation plan and readiness register."""
    empty = {"projects": 0, "plans": 0, "items": 0, "gates": 0}
    if await _already_seeded(session, project_id):
        return empty

    stage = _STAGES[ordinal % len(_STAGES)]
    rng = _rng_for(project_id)
    checklist = _ordered_checklist()
    statuses = _plan_statuses(rng, stage, len(checklist))

    today = datetime.now().date()
    target = today + timedelta(days=stage["days_to_target"])

    service = SitePrepService(session)
    created_by = str(owner_id)

    plan = await service.create_plan(
        project_id,
        SitePrepPlanCreate(
            target_start_date=target,
            status=stage["plan_status"],
            notes=site_prep_text(
                locale,
                "Mobilisation plan for the works. Readiness is measured against the "
                "target start date; the commencement gates must all be closed before "
                "anyone breaks ground.",
            ),
        ),
        created_by,
    )

    counts = {"projects": 1, "plans": 1, "items": 0, "gates": 0}
    blocked_seen = 0
    na_seen = 0

    for order, (entry, status) in enumerate(zip(checklist, statuses, strict=True)):
        due = target - timedelta(days=entry["lead"])
        due_date, completed_date = _dates_for(rng, status=status, due=due, target=target)

        note: str | None = None
        if status == _BLOCKED:
            note = site_prep_text(locale, _BLOCKED_REASONS[blocked_seen % len(_BLOCKED_REASONS)])
            blocked_seen += 1
        elif status == _NOT_APPLICABLE:
            note = site_prep_text(locale, _NOT_APPLICABLE_REASONS[na_seen % len(_NOT_APPLICABLE_REASONS)])
            na_seen += 1

        await service.create_item(
            project_id,
            SitePrepItemCreate(
                # The point of the register: every item hangs off this project's
                # own plan, so the rollup counts down to the plan's target date
                # rather than to nothing.
                plan_id=plan.id,
                category=entry["category"],
                title=site_prep_text(locale, entry["title"]),
                description=site_prep_text(locale, entry["description"]),
                status=status,
                responsible_party=site_prep_text(locale, entry["responsible_party"]),
                due_date=due_date,
                completed_date=completed_date,
                is_gate=entry["is_gate"],
                sort_order=order,
                notes=note,
            ),
            created_by,
        )
        counts["items"] += 1
        if entry["is_gate"]:
            counts["gates"] += 1

    return counts


async def seed_site_prep_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Populate the mobilisation plan and readiness register for demo projects.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Projects to seed, in the order they should be staged. Each
            is skipped when it already carries a plan or a readiness item.

    Returns:
        Dict with per-entity insert counts across every project seeded.
    """
    totals = {"projects": 0, "plans": 0, "items": 0, "gates": 0}
    ids = list(project_ids)
    if not ids:
        return totals

    from app.modules.projects.models import Project

    rows = (
        await session.execute(select(Project.id, Project.owner_id, Project.locale).where(Project.id.in_(ids)))
    ).all()
    owners = {pid: owner for pid, owner, _locale in rows}
    locales = {pid: locale for pid, _owner, locale in rows}

    for ordinal, project_id in enumerate(ids):
        owner_id = owners.get(project_id)
        if owner_id is None:
            continue
        try:
            # A SAVEPOINT per project, so one project that cannot be seeded costs
            # only its own rows. Catching the exception is not enough on
            # PostgreSQL: a failed statement aborts the whole transaction, and
            # every later project would then fail on a poisoned session rather
            # than on anything wrong with itself.
            async with session.begin_nested():
                counts = await _seed_project(session, project_id, owner_id, ordinal, locales.get(project_id))
        except Exception:
            logger.warning("Site prep demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
            continue
        for key, value in counts.items():
            totals[key] += value
    return totals
