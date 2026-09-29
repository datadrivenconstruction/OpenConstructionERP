# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo roster for a project: the people a job of this kind actually carries.

A roster screen with nothing on it teaches nobody what a roster is for, so the
demo project ships with one. What is seeded is a small, deliberately ordinary
site team: the client side, the main contractor's staff, and two subcontractor
gangs with a foreman each. Enough that the trade filter, the "who is in charge"
question and the ticket-expiry warning all have something to say.

Seeded people are roster lines only. Not one of them is given a login or a team
membership, so the demo cannot hand anybody access to anything - which is also
the clearest possible illustration of what a roster line is.

Idempotent: the seeder returns immediately when the project already has roster
lines, so re-running boot enrichment never doubles the site team.

Names, firms and ticket kinds are invented. Any resemblance to a real firm is
accidental, and none of them is a product on the market.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.teams.models import RosterMember, Team


@dataclass(frozen=True)
class _Person:
    """One seeded roster line."""

    name: str
    company: str
    site_role: str
    trade: str = ""
    allocation: int | None = None
    #: ``(kind, days from today until it expires)``. A negative number seeds a
    #: ticket that has already run out, which is what makes the expiry warning
    #: visible on the demo instead of being a feature nobody ever sees fire.
    ticket: tuple[str, int] | None = None
    #: Days from today when this person leaves. ``None`` means open-ended.
    ends_in_days: int | None = None
    team_kind: str = "internal"


_DEMO_PEOPLE: tuple[_Person, ...] = (
    _Person(
        name="Helena Vogt",
        company="Owner side",
        site_role="client_representative",
        allocation=20,
        team_kind="client",
    ),
    _Person(
        name="Marcus Reiter",
        company="Main contractor",
        site_role="project_manager",
        allocation=60,
    ),
    _Person(
        name="Ana Lucia Ferreira",
        company="Main contractor",
        site_role="site_manager",
        allocation=100,
        ticket=("Site safety certificate", 180),
    ),
    _Person(
        name="Piotr Nowak",
        company="Main contractor",
        site_role="quantity_surveyor",
        allocation=50,
    ),
    _Person(
        name="Sofia Marchetti",
        company="Main contractor",
        site_role="safety_officer",
        allocation=40,
        ticket=("First aid at work", -21),
    ),
    _Person(
        name="Dieter Hoffmann",
        company="Concrete gang",
        site_role="foreman",
        trade="concrete",
        allocation=100,
        team_kind="subcontractor",
        ticket=("Mobile crane banksman", 90),
    ),
    _Person(
        name="Tomasz Zielinski",
        company="Concrete gang",
        site_role="operative",
        trade="concrete",
        allocation=100,
        team_kind="subcontractor",
        ends_in_days=45,
    ),
    _Person(
        name="Karel Novak",
        company="Electrical gang",
        site_role="foreman",
        trade="electrical",
        allocation=80,
        team_kind="subcontractor",
        ticket=("Electrical competence card", 400),
    ),
    _Person(
        name="Ingrid Larsen",
        company="Design office",
        site_role="bim_coordinator",
        trade="",
        allocation=30,
        team_kind="consultant",
    ),
)


async def seed_teams_roster(session: AsyncSession, *, project_id: uuid.UUID) -> dict[str, int]:
    """Give one project a demo roster. Returns what it wrote.

    Args:
        session: An open session. The caller commits.
        project_id: The project to give a roster to.

    Returns:
        A one-key count dict, empty when the project already had a roster.
    """
    existing = (
        await session.execute(select(RosterMember.id).where(RosterMember.project_id == project_id).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        return {}

    teams = list((await session.execute(select(Team).where(Team.project_id == project_id))).scalars().all())
    # Group people onto whichever teams the project already has, matched on the
    # team's declared kind. A project with only a default team gets everybody on
    # it, which is the honest picture of a project nobody has grouped yet.
    by_kind: dict[str, Team] = {}
    for team in teams:
        kind = str((team.metadata_ or {}).get("kind") or "internal")
        by_kind.setdefault(kind, team)
    fallback = next((t for t in teams if t.is_default), teams[0] if teams else None)

    today = datetime.now(UTC).date()
    rows: list[RosterMember] = []
    for person in _DEMO_PEOPLE:
        team = by_kind.get(person.team_kind) or fallback
        certifications = []
        if person.ticket is not None:
            kind, offset = person.ticket
            certifications.append(
                {
                    "kind": kind,
                    "number": "",
                    "issued_by": "",
                    "valid_until": (today + timedelta(days=offset)).isoformat(),
                }
            )
        rows.append(
            RosterMember(
                project_id=project_id,
                team_id=team.id if team is not None else None,
                display_name=person.name,
                company_name=person.company,
                trade=person.trade,
                site_role=person.site_role,
                allocation_percent=person.allocation,
                starts_on=today - timedelta(days=60),
                ends_on=(today + timedelta(days=person.ends_in_days)) if person.ends_in_days else None,
                certifications=certifications,
            )
        )

    session.add_all(rows)
    await session.flush()
    return {"roster_members": len(rows)}


async def seeded_row_ids(session: AsyncSession, project_ids: list[uuid.UUID]) -> list[tuple[type, list, str]]:
    """Roster lines in ``project_ids`` that are exactly one of ``_DEMO_PEOPLE``.

    A line matches only when name, firm, site role, trade and allocation all
    equal one seeded person and it is linked to no login and no contact, which
    the seed never sets. A real person who shares a demo name but works for a
    different firm or in a different role is not matched.

    Returns:
        ``(model, ids, label)`` groups; ``label`` names the group in reports.
    """
    if not project_ids:
        return []
    people = {(p.name, p.company, p.site_role, p.trade, p.allocation) for p in _DEMO_PEOPLE}
    rows = (
        await session.execute(
            select(
                RosterMember.id,
                RosterMember.display_name,
                RosterMember.company_name,
                RosterMember.site_role,
                RosterMember.trade,
                RosterMember.allocation_percent,
                RosterMember.user_id,
                RosterMember.contact_id,
            ).where(RosterMember.project_id.in_(project_ids))
        )
    ).all()
    ids = [
        r.id
        for r in rows
        if (r.display_name, r.company_name, r.site_role, r.trade, r.allocation_percent) in people
        and r.user_id is None
        and r.contact_id is None
    ]
    return [(RosterMember, ids, "teams_roster")]
