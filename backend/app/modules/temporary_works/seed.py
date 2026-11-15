# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Temporary works demo seed - a governance register a coordinator would keep.

Fills every demo project's temporary-works register with the items a real job
carries at once: falsework and formwork still in design, propping and excavation
support bearing load under a live permit, a scaffold approved to strike, and the
hoarding that went up in week one and is still there. Each item names the design
load case it was checked against, the firm that designed it, the firm or engineer
that checked it independently, and the coordinator who holds the permits.

Every row is written through :class:`TemporaryWorksService` and the module's own
create schemas, so the seeded register passes the same ``Literal`` vocabularies,
the same per-project reference uniqueness and the same "a permit belongs to an
item in the same project" guard as an item typed in by hand. A row this seeder
cannot submit is a row the application would have rejected.

What a reader sees on the register screen afterwards:

* ten to nineteen items spread across the whole lifecycle, from ``identified``
  to ``removed``, with one paused on ``on_hold`` - so the screen teaches the
  gated workflow rather than showing one uniform status;
* design-check categories 0 to 3 that match the works, with the category 2 and 3
  items checked by a firm other than the one that designed them, which is what
  those categories mean;
* permits with real validity windows: draft permits on items whose inspection
  before use is still outstanding, live permits under every item bearing load,
  and closed permits behind everything already struck;
* two items under time pressure per project - one past its required load date
  and one past its required strike date - so the overdue lists are not empty;
* on one project only, and never the flagship, a single item whose permit to
  load has lapsed while the works are still in use. That is the register's one
  red flag, and it is the reason the module exists.

Dates are anchored to the run date, never hardcoded, so a demo opened a year
from now still shows a register that is being kept this month.

Self-gating twice over: only projects carrying the demo marker are touched, so a
customer's live project never receives invented safety records, and a project
that already holds a temporary-works item is left alone, so a re-run never
doubles the register.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.temporary_works.models import TemporaryWorksItem
from app.modules.temporary_works.schemas import (
    TemporaryWorksItemCreate,
    TemporaryWorksPermitCreate,
)
from app.modules.temporary_works.seed_text import temporary_works_text
from app.modules.temporary_works.service import TemporaryWorksService

logger = logging.getLogger(__name__)

_SEED = 4217

# Item statuses (mirrors the register core's own vocabulary).
_IDENTIFIED = "identified"
_DESIGN_BRIEF = "design_brief"
_DESIGN_SUBMITTED = "design_submitted"
_DESIGN_CHECKED = "design_checked"
_APPROVED_TO_LOAD = "approved_to_load"
_LOADED = "loaded"
_IN_USE = "in_use"
_APPROVED_TO_STRIKE = "approved_to_strike"
_STRUCK = "struck"
_REMOVED = "removed"
_ON_HOLD = "on_hold"

# Permit types and statuses (same source).
_PERMIT_TO_LOAD = "permit_to_load"
_PERMIT_TO_STRIKE = "permit_to_strike"
_PERMIT_TO_DISMANTLE = "permit_to_dismantle"
_DRAFT = "draft"
_ISSUED = "issued"
_ACTIVE = "active"
_EXPIRED = "expired"
_CLOSED = "closed"

# Works that are dismantled rather than struck. They never sit on ``struck``
# (a scaffold is not "struck"), and the closed record behind a removed one is a
# permit to dismantle rather than a permit to strike.
_DISMANTLE_FAMILY: frozenset[str] = frozenset(
    {"scaffold", "hoarding", "edge_protection", "facade_retention", "crane_base", "dewatering"},
)

# How many items a project's register carries, indexed by the project's position
# in the seeding call. Distinct counts keep two demo projects from rendering the
# same register, and the range sits inside what a live job actually runs at once.
_ITEM_COUNTS: tuple[int, ...] = (16, 11, 14, 19, 12, 17, 13, 18, 10, 15)

# Storey ceiling per project archetype, keyed by the leading word of the demo id.
# A single-storey warehouse with falsework on level six is the kind of row a site
# engineer spots immediately, so the level a location names is capped by what the
# building actually has.
_MAX_LEVEL_BY_ARCHETYPE: dict[str, int] = {
    "warehouse": 2,
    "school": 3,
    "retail": 2,
    "medical": 4,
    "govt": 4,
    "solar": 1,
    "modular": 3,
    "rc": 4,
}
_DEFAULT_MAX_LEVEL = 8

# Grid references a location can name. Plain structural grids, so they read the
# same on a warehouse and on a residential block.
_GRIDS: tuple[str, ...] = ("A-D / 1-4", "C-F / 3-6", "E-H / 5-9", "B-E / 2-5", "G-K / 6-10")

# Block / zone labels.
_BLOCKS: tuple[str, ...] = ("Block A", "Block B", "Block C", "Zone 1", "Zone 2", "Core")


class _ItemSpec(NamedTuple):
    """One temporary-works item the register can carry.

    ``description`` names the design load case the item was checked against,
    because that is what an independent checker signs off and what a reader of
    the register is entitled to see. ``location`` is a format string taking
    ``block``, ``level`` and ``grid``.
    """

    tw_type: str
    category: str
    title: str
    description: str
    location: str


# The pool a project's register is drawn from. Every temporary-works family in
# the module's vocabulary appears at least once, and the design check category on
# each follows the rigour the works actually need: standard proprietary
# solutions at 0, simple bespoke design at 1, anything carrying a permanent-works
# load or retaining ground at 2, and the facade retention at 3.
_ITEM_SPECS: tuple[_ItemSpec, ...] = (
    _ItemSpec(
        "falsework",
        "2",
        "Falsework to the transfer slab soffit",
        (
            "Falsework to the transfer slab soffit. Design case: 24 kN/m2 wet concrete, 1.5 kN/m2 "
            "construction live load and a 10 percent dynamic allowance on placement. Props at 1.2 m "
            "centres on sole plates, bearing checked at 150 kN/m2."
        ),
        "{block}, level {level}, grid {grid}",
    ),
    _ItemSpec(
        "falsework",
        "2",
        "Falsework to the podium beam",
        (
            "Falsework to the podium beam soffit. Design case: 31 kN/m of wet concrete and "
            "reinforcement on a 9.0 m span, plus a 0.5 kN/m2 horizontal notional load on the "
            "bracing. Foundations on a compacted piling mat."
        ),
        "{block}, level {level}, grid {grid}",
    ),
    _ItemSpec(
        "formwork",
        "1",
        "Wall formwork to the lift core",
        (
            "Panel formwork to the lift core walls. Design case: 60 kN/m2 concrete pressure at a "
            "2.0 m/h placement rate and 15 degrees C, ties at 600 mm vertical centres. Working "
            "platform bracketed off the panels."
        ),
        "{block}, core walls, level {level}",
    ),
    _ItemSpec(
        "formwork",
        "1",
        "Column formwork, ground to first lift",
        (
            "Column formwork for the first lift. Design case: 80 kN/m2 concrete pressure on a full "
            "height pour, clamps at 450 mm centres over the bottom third. Plumbing props tied to "
            "cast-in anchors, not to the reinforcement."
        ),
        "{block}, grid {grid}",
    ),
    _ItemSpec(
        "formwork",
        "0",
        "Proprietary slab tables, typical floor",
        (
            "Proprietary table forms used within the supplier's published configuration. Design "
            "case: 10.5 kN/m2 total slab load at the standard leg spacing, no deviation from the "
            "standard arrangement permitted without a fresh design."
        ),
        "{block}, level {level}, grid {grid}",
    ),
    _ItemSpec(
        "propping",
        "1",
        "Back-propping to the two floors below the pour",
        (
            "Back-propping to the two floors below the slab being cast. Design case: the wet slab "
            "load redistributed 60 / 40 over the two supporting floors, checked against the "
            "strength gain curve at seven days. Props aligned floor to floor."
        ),
        "{block}, level {level}, grid {grid}",
    ),
    _ItemSpec(
        "propping",
        "2",
        "Propping to the ground slab under the crane track",
        (
            "Propping to the ground slab where the crawler crane tracks cross the basement. Design "
            "case: 45 kN wheel load with a 25 percent impact allowance, spread through a 2.4 m "
            "square mat onto the slab below."
        ),
        "{block}, grid {grid}",
    ),
    _ItemSpec(
        "propping",
        "2",
        "Needle propping to the party wall",
        (
            "Needle propping to the party wall while the underpinning is cast. Design case: 42 kN/m "
            "of wall and floor load carried on needles at 1.5 m centres, with settlement monitoring "
            "on the adjoining structure at each stage."
        ),
        "{block}, party wall, grid {grid}",
    ),
    _ItemSpec(
        "excavation_support",
        "2",
        "Sheet-piled support to the basement excavation",
        (
            "Sheet-piled support to the basement box. Design case: 6.5 m retained height with "
            "at-rest earth pressure, a 10 kPa surcharge from the site road and the water table at "
            "2.0 m below ground. Single walar frame at 1.5 m depth."
        ),
        "{block}, basement perimeter, grid {grid}",
    ),
    _ItemSpec(
        "excavation_support",
        "2",
        "Trench support to the incoming services run",
        (
            "Trench boxes to the incoming services run. Design case: 2.8 m deep trench in firm "
            "cohesive ground with a 5 kPa plant surcharge at the edge. No excavation outside the "
            "supported length, spoil kept 1.5 m back."
        ),
        "{block}, services corridor",
    ),
    _ItemSpec(
        "excavation_support",
        "3",
        "Piled wall with a single prop frame",
        (
            "Contiguous piled wall with a single propping frame. Design case: staged excavation to "
            "8.0 m with prop preloading, checked for the temporary condition before the base slab "
            "acts. Movement triggers set at 10 mm amber and 15 mm red."
        ),
        "{block}, deep basement, grid {grid}",
    ),
    _ItemSpec(
        "scaffold",
        "0",
        "Independent tied scaffold to the north elevation",
        (
            "Independent tied access scaffold within the standard configuration. Design case: "
            "loading class 3 at 2.0 kN/m2, ties on a 4 m by 4 m pattern, tie pull-out tested to "
            "6.1 kN. Sheeting not permitted without a fresh wind check."
        ),
        "{block}, north elevation",
    ),
    _ItemSpec(
        "scaffold",
        "1",
        "Birdcage scaffold to the atrium soffit",
        (
            "Birdcage scaffold giving access to the atrium soffit. Design case: 2.0 kN/m2 working "
            "platform with a single boarded lift in use at a time, standards at 1.8 m centres on "
            "sole boards spreading onto the finished slab."
        ),
        "{block}, atrium, level {level}",
    ),
    _ItemSpec(
        "scaffold",
        "1",
        "Loading bay on the elevation scaffold",
        (
            "Loading bay formed in the elevation scaffold. Design case: 5.0 kN/m2 over the bay with "
            "a single stillage landed at a time, additional ties either side of the opening and the "
            "posted load limit displayed at the gate."
        ),
        "{block}, level {level}, east elevation",
    ),
    _ItemSpec(
        "facade_retention",
        "3",
        "Facade retention to the retained elevation",
        (
            "Facade retention scheme holding the retained street elevation with the floors removed. "
            "Design case: wind load to a 50 year return period on the free-standing facade plus a "
            "5 kN/m notional horizontal restraint. Movement monitored weekly."
        ),
        "{block}, street elevation",
    ),
    _ItemSpec(
        "crane_base",
        "2",
        "Tower crane base and grillage",
        (
            "Tower crane base slab and grillage. Design case: in-service and out-of-service "
            "overturning moments taken from the crane foundation loading sheet, bearing pressure "
            "checked at 200 kPa. Base not to be loaded before 28 day strength."
        ),
        "{block}, crane position, grid {grid}",
    ),
    _ItemSpec(
        "crane_base",
        "1",
        "Mobile crane outrigger mats at the east gate",
        (
            "Outrigger mats for mobile crane lifts from the east gate standing. Design case: 320 kN "
            "outrigger reaction spread to 120 kPa on the mat footprint, with a 1.5 m stand-off kept "
            "from the basement wall and no set-up over the services trench."
        ),
        "{block}, east gate standing",
    ),
    _ItemSpec(
        "edge_protection",
        "0",
        "Class A edge protection to the slab perimeter",
        (
            "Proprietary class A edge protection to the slab perimeter. Design case: 0.3 kN point "
            "load and 0.3 kN/m line load at the top rail. Post sockets cast in with the slab, no "
            "clamped posts on the edge beam."
        ),
        "{block}, level {level}, slab perimeter",
    ),
    _ItemSpec(
        "edge_protection",
        "0",
        "Stair opening and riser guarding",
        (
            "Guarding to the stair openings and service risers. Design case: the same 0.3 kN point "
            "load as the perimeter, with covers rated for a 1.5 kN foot load and fixed down rather "
            "than laid loose."
        ),
        "{block}, level {level}, risers and stair cores",
    ),
    _ItemSpec(
        "dewatering",
        "2",
        "Well-point dewatering to the pile cap excavation",
        (
            "Well-point dewatering to the pile cap excavation. Design case: drawdown to 1.0 m below "
            "formation with a recharge allowance, settlement monitoring on the adjacent terrace and "
            "discharge consented before pumping starts."
        ),
        "{block}, pile caps, grid {grid}",
    ),
    _ItemSpec(
        "dewatering",
        "1",
        "Sump pumping to the basement slab pour",
        (
            "Sump pumping keeping the basement formation dry for the slab pour. Design case: "
            "12 l/s peak inflow after rain with a standby pump on site, sumps kept outside the pour "
            "sequence and backfilled as the slab advances."
        ),
        "{block}, basement, grid {grid}",
    ),
    _ItemSpec(
        "hoarding",
        "0",
        "Site perimeter hoarding to the highway boundary",
        (
            "Site perimeter hoarding, 2.4 m plywood on posts. Design case: wind on a solid "
            "free-standing wall to the site's exposure, posts in concrete-filled sockets at 3.0 m "
            "centres. No signage boards fixed without a fresh wind check."
        ),
        "{block}, highway boundary",
    ),
    _ItemSpec(
        "hoarding",
        "1",
        "Pavement gantry at the site entrance",
        (
            "Pavement gantry keeping the footway open past the site entrance. Design case: 5.0 "
            "kN/m2 on the deck for material storage plus a 50 kN vehicle impact case on the kerbside "
            "legs, headroom held at 2.6 m."
        ),
        "{block}, site entrance",
    ),
    _ItemSpec(
        "other",
        "1",
        "Temporary access ramp into the basement",
        (
            "Temporary access ramp into the basement. Design case: a 32 t dumper at 1 in 8 gradient "
            "on compacted fill, edge kerbs to both sides and the running surface inspected after "
            "heavy rain."
        ),
        "{block}, basement ramp",
    ),
)

# The lifecycle status each register position carries, oldest reference first.
# Deliberately mixed rather than sorted: a real register is numbered in the order
# items were raised, so the statuses interleave. The first ten positions already
# cover nine of the eleven statuses, so even the smallest project's register
# reads as a whole workflow.
_STATUS_PLAN: tuple[str, ...] = (
    _IN_USE,
    _DESIGN_SUBMITTED,
    _APPROVED_TO_LOAD,
    _STRUCK,
    _IDENTIFIED,
    _IN_USE,
    _DESIGN_CHECKED,
    _LOADED,
    _ON_HOLD,
    _APPROVED_TO_STRIKE,
    _DESIGN_BRIEF,
    _IN_USE,
    _REMOVED,
    _DESIGN_CHECKED,
    _IDENTIFIED,
    _STRUCK,
    _APPROVED_TO_LOAD,
    _IN_USE,
    _DESIGN_SUBMITTED,
    _LOADED,
    _DESIGN_BRIEF,
    _APPROVED_TO_STRIKE,
    _IN_USE,
    _REMOVED,
    _DESIGN_CHECKED,
)

# Day offsets from the run date for (design due, required load, required strike),
# per status. ``None`` means the date is not set yet at that stage. The ranges
# are inclusive and a deterministic RNG picks inside them, so no two items on a
# project share a timeline and no register looks generated.
_DATE_PLAN: dict[str, tuple[tuple[int, int] | None, tuple[int, int] | None, tuple[int, int] | None]] = {
    _IDENTIFIED: ((21, 45), (70, 120), (150, 260)),
    _DESIGN_BRIEF: ((14, 28), (45, 80), (110, 200)),
    _DESIGN_SUBMITTED: ((5, 14), (28, 50), (95, 160)),
    _DESIGN_CHECKED: ((-21, -7), (10, 25), (70, 130)),
    _APPROVED_TO_LOAD: ((-35, -21), (-2, 7), (55, 110)),
    _LOADED: ((-50, -35), (-14, -5), (30, 70)),
    _IN_USE: ((-80, -55), (-55, -20), (21, 60)),
    _APPROVED_TO_STRIKE: ((-120, -90), (-95, -70), (2, 10)),
    _STRUCK: ((-170, -140), (-140, -110), (-30, -12)),
    _REMOVED: ((-200, -170), (-170, -140), (-60, -35)),
    _ON_HOLD: ((-14, -5), (40, 70), (120, 190)),
}

# The register note that goes with each status, so a reader who opens a row
# learns where it sits in the gated process rather than re-reading the status.
_STATUS_NOTES: dict[str, str] = {
    _IDENTIFIED: "Raised at the temporary works review. Design brief to follow.",
    _DESIGN_BRIEF: "Design brief issued to the temporary works designer.",
    _DESIGN_SUBMITTED: "Design received and with the checker.",
    _DESIGN_CHECKED: "Check certificate received. Permit to load follows the inspection before use.",
    _APPROVED_TO_LOAD: "Permit to load issued. Inspection before use passed.",
    _LOADED: "Loaded in accordance with the permit and the loading sequence.",
    _IN_USE: "In use. Inspected weekly by the coordinator and after any high wind.",
    _APPROVED_TO_STRIKE: "Permit to strike issued against the concrete strength result.",
    _STRUCK: "Struck in the sequence on the striking drawing. Permit closed out.",
    _REMOVED: "Removed from site and the register entry closed.",
    _ON_HOLD: "On hold pending a revised design after the change to the loading.",
}

# Permit conditions per permit type. Short, specific, and about this permit only.
_PERMIT_CONDITIONS: dict[str, str] = {
    _PERMIT_TO_LOAD: (
        "No loading beyond the design case. Props and ties not to be adjusted, removed or "
        "re-positioned under load. Any change of loading or sequence needs a fresh permit."
    ),
    _PERMIT_TO_STRIKE: (
        "Striking not to start before the cube result confirms the strength named in the design. "
        "Follow the striking sequence on the drawing. Back-props to remain until released "
        "separately."
    ),
    _PERMIT_TO_DISMANTLE: (
        "Dismantle top down in the reverse of the erection sequence. Exclusion zone at ground "
        "level throughout. No component to be dropped or thrown."
    ),
}

# Statuses that carry no permit yet: nothing has been designed and checked, so
# there is nothing a coordinator could authorise.
_PRE_PERMIT_STATUSES: frozenset[str] = frozenset({_IDENTIFIED, _DESIGN_BRIEF, _DESIGN_SUBMITTED})

# Contact types whose company is a plausible temporary-works designer or checker.
_FIRM_CONTACT_TYPES: frozenset[str] = frozenset({"consultant", "contractor", "subcontractor", "supplier"})


class _Parties(NamedTuple):
    """The people and firms a register names, read from the demo's own rows.

    Nothing here is invented. The firms are companies the demo already carries in
    its contact directory and the coordinator is one of the demo's own users, so
    the register never attaches a design responsibility or a check to a person
    this seeder made up.
    """

    firms: tuple[str, ...]
    engineers: tuple[str, ...]
    twc_name: str | None
    twc_user_id: uuid.UUID | None


def _rng_for(project_id: uuid.UUID) -> random.Random:
    """A deterministic RNG per project, so a re-seed reproduces the register."""
    return random.Random(f"{_SEED}:{project_id}")


def _offset(rng: random.Random, window: tuple[int, int] | None, *, anchor: date) -> date | None:
    """Pick a date inside ``window`` days of ``anchor``, or None when unset."""
    if window is None:
        return None
    return anchor + timedelta(days=rng.randint(window[0], window[1]))


def _max_level(demo_id: str) -> int:
    """Storey ceiling for the archetype behind a demo id."""
    head = str(demo_id or "").split("-", 1)[0].lower()
    return _MAX_LEVEL_BY_ARCHETYPE.get(head, _DEFAULT_MAX_LEVEL)


def _location(rng: random.Random, spec: _ItemSpec, max_level: int, locale: str | None = None) -> str:
    """Render a spec's location against this project's blocks, levels and grids."""
    return temporary_works_text(locale, spec.location).format(
        block=temporary_works_text(locale, rng.choice(_BLOCKS)),
        level=rng.randint(1, max_level),
        grid=rng.choice(_GRIDS),
    )[:500]


def _resolved_status(spec: _ItemSpec, planned: str) -> str:
    """Keep a scaffold from being 'struck'.

    Striking is what happens to falsework and formwork. Access scaffolds,
    hoarding, edge protection, facade retention, crane bases and dewatering are
    dismantled or removed, so a planned ``struck`` reads as ``removed`` on them.
    """
    if planned == _STRUCK and spec.tw_type in _DISMANTLE_FAMILY:
        return _REMOVED
    return planned


def _checker_for(
    rng: random.Random,
    parties: _Parties,
    category: str,
    designer: str | None,
) -> str | None:
    """Who checked the design, following what the category actually requires.

    Categories 2 and 3 are defined by the check being independent of the
    designer, so those name a different firm and never fall back to the same one.
    Categories 0 and 1 are checked inside the design team or by the site's own
    engineer, so those name a person.
    """
    if category in ("2", "3"):
        others = tuple(f for f in parties.firms if f != designer)
        return rng.choice(others) if others else None
    candidates = tuple(e for e in parties.engineers if e != parties.twc_name)
    if candidates:
        return rng.choice(candidates)
    return rng.choice(parties.engineers) if parties.engineers else None


def _permit_window(
    rng: random.Random,
    status: str,
    *,
    today: date,
    load_date: date | None,
    strike_date: date | None,
) -> tuple[date, date]:
    """Validity window for the permit to load that goes with ``status``.

    A permit under works that are bearing load has to contain today, or the
    register would report a compliance breach on data that is meant to be clean;
    a permit behind works already struck is closed and sits wholly in the past.
    """
    if status in (_APPROVED_TO_LOAD, _LOADED, _IN_USE, _APPROVED_TO_STRIKE):
        opened = min(load_date or today, today) - timedelta(days=rng.randint(2, 9))
        closes = max(
            (strike_date or today) + timedelta(days=7),
            today + timedelta(days=rng.randint(14, 45)),
        )
        return opened, closes
    if status in (_STRUCK, _REMOVED):
        end = strike_date or (today - timedelta(days=20))
        return (load_date or end - timedelta(days=60)) - timedelta(days=3), end + timedelta(days=3)
    # Draft permits (design checked, or the works paused) open when the item is
    # due to be loaded and have not been issued yet.
    opened = (load_date or today + timedelta(days=14)) - timedelta(days=2)
    return opened, opened + timedelta(days=rng.randint(45, 90))


def _load_permit_status(status: str) -> str:
    """Permit-to-load lifecycle status implied by the item's own status."""
    if status in (_DESIGN_CHECKED, _ON_HOLD):
        return _DRAFT
    if status == _APPROVED_TO_LOAD:
        return _ISSUED
    if status in (_LOADED, _IN_USE, _APPROVED_TO_STRIKE):
        return _ACTIVE
    return _CLOSED


async def _read_parties(session: AsyncSession) -> _Parties:
    """Collect the firms, engineers and coordinator the demo already knows.

    Reads the contact directory and the user table rather than carrying a list of
    names of its own: the demo's parties are curated in one place, and a register
    that names anyone else would be naming somebody who does not exist anywhere
    else in the product.
    """
    firms: list[str] = []
    engineers: list[str] = []
    try:
        from app.modules.contacts.models import Contact

        rows = (
            await session.execute(
                select(Contact.contact_type, Contact.company_name, Contact.first_name, Contact.last_name)
                .where(Contact.is_active.is_(True))
                .order_by(Contact.company_name),
            )
        ).all()
    except Exception:
        logger.debug("Contact directory unavailable; temporary works rows carry no party names")
        rows = []

    seen_firms: set[str] = set()
    seen_people: set[str] = set()
    for contact_type, company_name, first_name, last_name in rows:
        company = str(company_name or "").strip()
        if company and str(contact_type or "") in _FIRM_CONTACT_TYPES and company not in seen_firms:
            seen_firms.add(company)
            firms.append(company)
        person = " ".join(part for part in (str(first_name or "").strip(), str(last_name or "").strip()) if part)
        if person and person not in seen_people:
            seen_people.add(person)
            engineers.append(person)

    twc_name: str | None = None
    twc_user_id: uuid.UUID | None = None
    try:
        from app.modules.users.models import User

        user_rows = (await session.execute(select(User.id, User.role, User.full_name).order_by(User.email))).all()
    except Exception:
        logger.debug("User table unavailable; temporary works rows carry no coordinator")
        user_rows = []
    by_role: dict[str, tuple[uuid.UUID, str]] = {}
    for user_id, role, full_name in user_rows:
        name = str(full_name or "").strip()
        if name:
            by_role.setdefault(str(role or ""), (user_id, name))
    for role in ("manager", "admin", "editor"):
        if role in by_role:
            twc_user_id, twc_name = by_role[role]
            break

    return _Parties(
        firms=tuple(firms),
        engineers=tuple(engineers),
        twc_name=twc_name,
        twc_user_id=twc_user_id,
    )


async def _demo_projects(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
) -> list[tuple[uuid.UUID, str]]:
    """Return ``(project_id, demo_id)`` for the demo projects among ``project_ids``.

    Temporary works are a safety register. A customer's live project must never
    be handed invented permits and design checks, so the marker the demo
    installer writes onto its own projects is what admits a project here. The
    filter runs in Python because a JSON ``contains`` compiles to a string LIKE
    on this stack rather than to real containment.

    The caller's order is preserved rather than the database's, because a
    project's position in this list decides how large a register it gets and
    which project carries the lapsed permit. An unordered ``IN`` would hand both
    of those to whatever order the rows happened to come back in.
    """
    from app.modules.projects.models import Project

    rows = (await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(list(project_ids))))).all()
    demo: dict[uuid.UUID, str] = {}
    for project_id, metadata in rows:
        meta = metadata if isinstance(metadata, dict) else {}
        # ``demo_id`` is the marker, not ``is_demo``. The ten template projects
        # stamp both, but the flagship reference project is installed from its
        # own baked fixture and carries only ``demo_id``, so a gate on
        # ``is_demo`` skips the one project users actually land on.
        demo_id = str(meta.get("demo_id") or "").strip()
        if demo_id:
            demo[project_id] = demo_id
    out: list[tuple[uuid.UUID, str]] = []
    seen: set[uuid.UUID] = set()
    for project_id in project_ids:
        if project_id in demo and project_id not in seen:
            seen.add(project_id)
            out.append((project_id, demo[project_id]))
    return out


async def _seed_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    demo_id: str,
    ordinal: int,
    parties: _Parties,
    *,
    with_lapsed_permit: bool,
) -> dict[str, int]:
    """Seed one project's register. Returns per-entity counts (zeros when skipped)."""
    empty = {"projects": 0, "items": 0, "permits": 0}

    already = (
        (
            await session.execute(
                select(TemporaryWorksItem.id).where(TemporaryWorksItem.project_id == project_id).limit(1),
            )
        )
        .scalars()
        .first()
    )
    if already is not None:
        return empty

    from app.modules.projects.models import Project

    locale = (await session.execute(select(Project.locale).where(Project.id == project_id))).scalars().first()
    rng = _rng_for(project_id)
    today = datetime.now(UTC).date()
    count = _ITEM_COUNTS[ordinal % len(_ITEM_COUNTS)]
    count = min(count, len(_ITEM_SPECS), len(_STATUS_PLAN))
    specs = rng.sample(_ITEM_SPECS, k=count)
    max_level = _max_level(demo_id)

    service = TemporaryWorksService(session)
    created_by = str(parties.twc_user_id) if parties.twc_user_id is not None else None
    counts = {"projects": 1, "items": 0, "permits": 0}

    # Two items per project are deliberately under time pressure, so the overdue
    # lists on the register screen are never empty: the first item still waiting
    # on its design is past the date the programme needs it loaded, and the
    # second one in use is past the date it was meant to come out.
    overdue_load_at = next((i for i, s in enumerate(_STATUS_PLAN[:count]) if s == _DESIGN_SUBMITTED), None)
    in_use_positions = [i for i, s in enumerate(_STATUS_PLAN[:count]) if s == _IN_USE]
    overdue_strike_at = in_use_positions[1] if len(in_use_positions) > 1 else None
    # The one lapsed permit, when this project is carrying it, sits on the first
    # item in use - not on the one already flagged as overdue to strike, so the
    # two signals stay legible as two separate things.
    lapsed_at = in_use_positions[0] if (with_lapsed_permit and in_use_positions) else None

    permit_serials = {_PERMIT_TO_LOAD: 0, _PERMIT_TO_STRIKE: 0, _PERMIT_TO_DISMANTLE: 0}

    def _permit_number(permit_type: str) -> str:
        permit_serials[permit_type] += 1
        prefix = {
            _PERMIT_TO_LOAD: "PTL",
            _PERMIT_TO_STRIKE: "PTS",
            _PERMIT_TO_DISMANTLE: "PTD",
        }[permit_type]
        return f"{prefix}-{permit_serials[permit_type]:03d}"

    for index in range(count):
        spec = specs[index]
        status = _resolved_status(spec, _STATUS_PLAN[index])
        design_window, load_window, strike_window = _DATE_PLAN[status]
        design_due = _offset(rng, design_window, anchor=today)
        load_date = _offset(rng, load_window, anchor=today)
        strike_date = _offset(rng, strike_window, anchor=today)

        if index == overdue_load_at:
            load_date = today - timedelta(days=rng.randint(4, 9))
        if index == overdue_strike_at:
            strike_date = today - timedelta(days=rng.randint(6, 15))
        if index == lapsed_at:
            # Live works whose authorisation has run out: the strike date is
            # still ahead, so this reads as a permit due for renewal rather
            # than as works everybody forgot about.
            strike_date = today + timedelta(days=rng.randint(9, 20))

        designer = rng.choice(parties.firms) if parties.firms else None
        checker = _checker_for(rng, parties, spec.category, designer)

        item = await service.create_item(
            project_id,
            TemporaryWorksItemCreate(
                reference=f"TW-{index + 1:03d}",
                title=temporary_works_text(locale, spec.title),
                description=temporary_works_text(locale, spec.description),
                tw_type=spec.tw_type,
                design_check_category=spec.category,
                designer_name=designer,
                checker_name=checker,
                twc_name=parties.twc_name,
                twc_user_id=parties.twc_user_id,
                status=status,
                required_load_date=load_date,
                required_strike_date=strike_date,
                design_due_date=design_due,
                location=_location(rng, spec, max_level, locale),
                sort_order=index,
                notes=temporary_works_text(locale, _STATUS_NOTES[status]),
            ),
            created_by,
        )
        counts["items"] += 1

        for payload in _permits_for(
            rng,
            status=status,
            spec=spec,
            today=today,
            load_date=load_date,
            strike_date=strike_date,
            parties=parties,
            lapsed=index == lapsed_at,
            next_number=_permit_number,
            locale=locale,
        ):
            await service.create_permit(project_id, item.id, payload, created_by)
            counts["permits"] += 1

    return counts


def _permits_for(
    rng: random.Random,
    *,
    status: str,
    spec: _ItemSpec,
    today: date,
    load_date: date | None,
    strike_date: date | None,
    parties: _Parties,
    lapsed: bool,
    next_number: Callable[[str], str],
    locale: str | None = None,
) -> list[TemporaryWorksPermitCreate]:
    """Build the permits an item at ``status`` would actually have on file.

    Nothing is authorised before the design has been checked, so the first three
    statuses carry no permit at all. From ``design_checked`` on there is a permit
    to load - draft while the inspection before use is outstanding, live under
    anything bearing load, closed behind anything already struck - and the strike
    or dismantle authorisation appears only once the item has reached it.
    """
    if status in _PRE_PERMIT_STATUSES:
        return []

    permits: list[TemporaryWorksPermitCreate] = []
    load_status = _EXPIRED if lapsed else _load_permit_status(status)
    valid_from, valid_to = _permit_window(
        rng,
        status,
        today=today,
        load_date=load_date,
        strike_date=strike_date,
    )
    if lapsed:
        valid_from = today - timedelta(days=rng.randint(80, 140))
        valid_to = today - timedelta(days=rng.randint(8, 16))

    is_draft = load_status == _DRAFT
    # A draft permit has not been issued, so it carries neither an issue date nor
    # an issuer. The design-check prerequisite is already met at design_checked;
    # the inspection before use is what is still outstanding. A paused item has
    # neither.
    permits.append(
        TemporaryWorksPermitCreate(
            permit_number=next_number(_PERMIT_TO_LOAD),
            permit_type=_PERMIT_TO_LOAD,
            status=load_status,
            issued_by=None if is_draft else parties.twc_name,
            issued_at=None if is_draft else valid_from - timedelta(days=rng.randint(1, 4)),
            valid_from=valid_from,
            valid_to=valid_to,
            closed_at=strike_date if load_status == _CLOSED else None,
            closed_by=parties.twc_user_id if load_status == _CLOSED else None,
            prereq_design_check_accepted=status != _ON_HOLD,
            prereq_inspection_passed=not is_draft,
            conditions=temporary_works_text(locale, _PERMIT_CONDITIONS[_PERMIT_TO_LOAD]),
        ),
    )

    if status == _APPROVED_TO_STRIKE:
        opened = today - timedelta(days=rng.randint(1, 4))
        permits.append(
            TemporaryWorksPermitCreate(
                permit_number=next_number(_PERMIT_TO_STRIKE),
                permit_type=_PERMIT_TO_STRIKE,
                status=_ISSUED,
                issued_by=parties.twc_name,
                issued_at=opened,
                valid_from=opened,
                valid_to=(strike_date or today) + timedelta(days=rng.randint(7, 21)),
                prereq_design_check_accepted=True,
                prereq_inspection_passed=True,
                conditions=temporary_works_text(locale, _PERMIT_CONDITIONS[_PERMIT_TO_STRIKE]),
            ),
        )
    elif status in (_STRUCK, _REMOVED):
        # Removed access works were dismantled, not struck, so the closed record
        # behind them is the permit that actually authorised the operation.
        permit_type = (
            _PERMIT_TO_DISMANTLE if (status == _REMOVED and spec.tw_type in _DISMANTLE_FAMILY) else _PERMIT_TO_STRIKE
        )
        end = strike_date or (today - timedelta(days=20))
        permits.append(
            TemporaryWorksPermitCreate(
                permit_number=next_number(permit_type),
                permit_type=permit_type,
                status=_CLOSED,
                issued_by=parties.twc_name,
                issued_at=end - timedelta(days=rng.randint(3, 8)),
                valid_from=end - timedelta(days=rng.randint(1, 3)),
                valid_to=end + timedelta(days=rng.randint(3, 10)),
                closed_at=end,
                closed_by=parties.twc_user_id,
                prereq_design_check_accepted=True,
                prereq_inspection_passed=True,
                conditions=temporary_works_text(locale, _PERMIT_CONDITIONS[permit_type]),
            ),
        )
    return permits


async def seed_temporary_works_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Populate the temporary-works governance register for the demo projects.

    Afterwards the temporary-works screen on every demo project shows a register
    a coordinator could hand to an inspector: ten to nineteen items across the
    whole gated lifecycle, each naming the design load case it was checked
    against and the firms behind that check, with draft, live and closed permits
    underneath them, two items running late, and - on exactly one project, never
    the flagship - one item still in use on a permit that has lapsed.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Projects to consider. A project is skipped unless it carries
            the demo marker, and skipped again if it already holds a
            temporary-works item, so a re-run never doubles the register and a
            customer's live project is never given invented safety records.

    Returns:
        Dict with per-entity insert counts across every project seeded.
    """
    totals = {"projects": 0, "items": 0, "permits": 0}
    ids = list(project_ids)
    if not ids:
        return totals

    targets = await _demo_projects(session, ids)
    if not targets:
        return totals
    parties = await _read_parties(session)
    if not parties.firms:
        logger.debug("No contact firms found; temporary works items will name no designer")

    # The one lapsed permit goes on the third project seeded, so the flagship the
    # user lands on reads clean and the register still shows what it does when a
    # permit runs out. A one or two project install shows no breach at all.
    lapsed_project = targets[2][0] if len(targets) > 2 else None

    for ordinal, (project_id, demo_id) in enumerate(targets):
        try:
            # A SAVEPOINT per project, so one project that cannot be seeded costs
            # only its own rows. Catching the exception is not enough on
            # PostgreSQL: a failed statement aborts the whole transaction, and
            # every later project would then fail on a poisoned session rather
            # than on anything wrong with itself.
            async with session.begin_nested():
                counts = await _seed_project(
                    session,
                    project_id,
                    demo_id,
                    ordinal,
                    parties,
                    with_lapsed_permit=project_id == lapsed_project,
                )
        except Exception:
            logger.warning("Temporary works demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
            continue
        for key, value in counts.items():
            totals[key] += value
    return totals
