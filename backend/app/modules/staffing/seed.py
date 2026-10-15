# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo staffing plan for the demo estate, run by ``app.core.demo_enrichment``.

Each demo project gets the staffing catalogue its country resolves to and the
plan a project lead would be working on. Which plan that is follows from the
project's own state, read through the governance port: when the gate into the
phase that enables the start of construction exists and is not decided, the
project is before construction and nobody is on site yet (the site team is
named and enters at mobilisation, the plan is submitted for that gate). In
every other case, a project without a phase model included, it is the plan a
month into construction:

* development: the owner's lead team, on the project for eight months;
* execution: the site team that started a month ago, one person arriving in
  ten days, one position open and one being recruited through a resource
  request;
* operation: the operator's build-up before commissioning, still open, with
  the knowledge handovers into it already linked.

Nothing a submission would refuse is left in the plan. Every person on a
confirmed position has a personnel file with the documents their role asks
for, recorded through the service so each validity record carries its derived
status from the first day. Three documents run out inside 30, 60 and 90 days,
one required document is missing and one is waived, so the compliance matrix
and the upcoming view show every state. Travel (one trip done, one
mobilisation next week, one rotation) and leave (one approved, one requested)
fill the rest. Money is in the project's own currency; a project without one
gets its trips without a cost.

Approval goes through the governance gate, never through a seeder. Before
construction the plan is submitted, so the gate finds it in review; a month
into construction it is a draft somebody is working on. People come from the teams roster (seeded first
when the project has none), so no name is invented here. Only projects
carrying the demo marker are touched; a project that already has a plan is
skipped, so a re-run never duplicates.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# (role, phase, entry offset in days from today, exit offset or None, stored status)
POSITIONS: tuple[tuple[str, str, int, int | None, str], ...] = (
    ("project_director", "development", -240, None, "open"),
    ("project_manager", "development", -240, None, "open"),
    ("design_manager", "development", -240, None, "open"),
    ("cost_manager", "development", -210, None, "open"),
    ("contract_manager", "development", -180, None, "open"),
    ("site_manager", "execution", -30, None, "open"),
    ("hse_manager", "execution", -30, None, "open"),
    ("site_supervisor_civil", "execution", -30, None, "open"),
    ("document_controller", "execution", 10, None, "open"),
    ("quality_manager", "execution", 30, None, "open"),
    ("site_supervisor_mep", "execution", 45, 400, "recruiting"),
    ("commissioning_manager", "execution", 300, None, "open"),
    ("operator_plant_manager", "operation", 330, None, "open"),
    ("operator_shift_lead", "operation", 360, None, "open"),
)
# One roster member per role, the one whose site role names it or else in roster order; the roles
# further down stay vacant.
FILLED = (
    "project_director",
    "project_manager",
    "design_manager",
    "cost_manager",
    "contract_manager",
    "site_manager",
    "hse_manager",
    "site_supervisor_civil",
    "document_controller",
)
COMMISSIONING_IN_DAYS = 420
# Before construction. Offsets of the shared demo timeline: mobilisation of the site team 175 days after
# the seed day, start of construction 190, commissioning 560. Nobody of the site team is on site yet.
MOBILISATION_IN_DAYS = 175
POSITIONS_BEFORE_CONSTRUCTION: tuple[tuple[str, str, int, int | None, str], ...] = (
    *(row for row in POSITIONS if row[1] == "development"),
    ("site_manager", "execution", 175, None, "open"),
    ("hse_manager", "execution", 175, None, "open"),
    ("site_supervisor_civil", "execution", 175, None, "open"),
    ("document_controller", "execution", 175, None, "open"),
    ("quality_manager", "execution", 190, None, "open"),
    ("site_supervisor_mep", "execution", 190, 560, "recruiting"),
    ("commissioning_manager", "execution", 440, None, "open"),
    ("operator_plant_manager", "operation", 470, None, "open"),
    ("operator_shift_lead", "operation", 500, None, "open"),
)
COMMISSIONING_BEFORE_CONSTRUCTION_IN_DAYS = 560
MOBILISED = ("site_manager", "hse_manager", "site_supervisor_civil", "document_controller")
PERMIT_HOLDER = "site_supervisor_civil"
# (role, document kind) -> days until the document expires. The three windows of the upcoming view.
EXPIRING: dict[tuple[str, str], int] = {
    (PERMIT_HOLDER, "work_permit"): 20,
    ("hse_manager", "safety_training"): 45,
    ("site_manager", "occupational_health_certificate"): 80,
}
MISSING = ("hse_manager", "qualification")
WAIVED = ("site_manager", "professional_licence")
# Kinds without an end date: a contract runs until the assignment ends.
OPEN_ENDED = ("employment_contract",)
HANDOVERS = (
    ("project_manager", "operator_plant_manager", 30, "Open items, commissioning sequence, operator training plan."),
    ("design_manager", "commissioning_manager", 20, "Design intent, test and acceptance criteria, as-built status."),
)


_ROLE = "role"  # story key of a role code
_PHASES = ("development", "execution", "operation")
_Position = tuple[str, str, int, int | None, str]


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def story_positions(
    story: dict[str, Any], default: tuple[_Position, ...], key: str = "positions"
) -> tuple[_Position, ...]:
    """The pre-construction positions table of the story; rows of a bad shape are dropped, none left keeps ``default``.

    A row is ``{"role", "phase", "entry", "exit", "status"}`` with day offsets from the seed day. Role codes the
    catalogue does not know are skipped later, where the catalogue is at hand.
    """
    rows = story.get(key)
    out: list[_Position] = []
    for r in rows if isinstance(rows, list) else []:
        entry = _int(r.get("entry")) if isinstance(r, dict) else None
        leaving = r.get("exit") if isinstance(r, dict) else None
        if (
            entry is None
            or not isinstance(r.get(_ROLE), str)
            or r.get("phase") not in _PHASES
            or r.get("status", "open") not in ("open", "recruiting")
            or (leaving is not None and _int(leaving) is None)
        ):
            logger.info("staffing demo story: position row %r is not usable, dropped", r)
            continue
        out.append((r[_ROLE], r["phase"], entry, leaving, r.get("status", "open")))
    return tuple(out) or default


def story_pairs(story: dict[str, Any], key: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Rows ``{"role", "kind", ...}`` of a document list as ``(role, kind, row)``; malformed rows are dropped."""
    rows = story.get(key)
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and isinstance(r.get(_ROLE), str) and isinstance(r.get("kind"), str):
            out.append((r[_ROLE], r["kind"], r))
        else:
            logger.info("staffing demo story: %s row %r is not usable, dropped", key, r)
    return out


def story_roster(story: dict[str, Any], locale: str) -> list[dict[str, Any]]:
    """The invented people the story puts on the project roster, in the order they fill the roles.

    A row needs a ``name``; ``company`` and ``site_role`` are optional texts and ``allocation`` a
    percentage from 1 to 100. A row that is not usable is dropped with an info line.
    """
    from app.modules.project_governance.public import story_text

    rows = story.get("roster")
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        name = story_text(row.get("name"), locale) if isinstance(row, dict) else ""
        if not name:
            logger.info("staffing demo story: roster row %r is not usable, dropped", row)
            continue
        allocation = _int(row.get("allocation"))
        out.append(
            {
                "name": name,
                "company": story_text(row.get("company"), locale),
                "site_role": story_text(row.get("site_role"), locale),
                "allocation": allocation if allocation is not None and 0 < allocation <= 100 else 100,
            }
        )
    return out


def assign_roles(roles: Sequence[str], members: Sequence[Any]) -> list[tuple[str, Any]]:
    """Pair each role with the roster member who holds it, then the rest in roster order.

    A member whose ``site_role`` names a role takes that role, so the story cast lands where the story
    puts it however the roster rows happen to sort (rows written in one flush share ``created_at`` and
    then sort by a random id). Roles nobody names go to the members left over, in their order.
    """
    taken: set[int] = set()
    pairs: dict[str, Any] = {}
    for role in roles:
        for i, member in enumerate(members):
            if i not in taken and getattr(member, "site_role", None) == role:
                pairs[role] = member
                taken.add(i)
                break
    rest = iter(m for i, m in enumerate(members) if i not in taken)
    out: list[tuple[str, Any]] = []
    for role in roles:
        member = pairs.get(role) or next(rest, None)
        if member is not None:
            out.append((role, member))
    return out


def story_handovers(story: dict[str, Any], locale: str, default: tuple[tuple[str, str, int, str], ...]) -> tuple:
    """The handovers of the story as ``(giver, receiver, overlap days, scope)``, or ``default`` when none is usable."""
    from app.modules.project_governance.public import story_text

    rows = story.get("handovers")
    out = []
    for r in rows if isinstance(rows, list) else []:
        overlap = _int(r.get("overlap_days")) if isinstance(r, dict) else None
        scope = (
            story_text(r.get("scope"), locale)
            if isinstance(r, dict) and isinstance(r.get("scope"), (str, dict))
            else None
        )
        if (
            overlap is None
            or overlap <= 0
            or not scope
            or not isinstance(r.get("from"), str)
            or not isinstance(r.get("to"), str)
        ):
            logger.info("staffing demo story: handover row %r is not usable, dropped", r)
            continue
        out.append((r["from"], r["to"], overlap, scope))
    return tuple(out) or default


async def seed_staffing_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seed the staffing plan of every demo project in ``project_ids`` that has none. The caller commits."""
    from app.core.demo_marker import demo_id_of
    from app.modules.projects.models import Project
    from app.modules.staffing.models import StaffingPlan

    totals = {"projects": 0, "positions": 0, "fills": 0, "files": 0, "documents": 0, "submitted": 0}
    ids = list(project_ids)
    if not ids:
        return totals
    rows = (await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(ids)))).all()
    for pid in [pid for pid, meta in rows if demo_id_of(meta)]:
        has = (
            await session.execute(select(StaffingPlan.id).where(StaffingPlan.project_id == pid))
        ).scalar_one_or_none()
        if has is not None:
            continue
        try:
            async with session.begin_nested():
                counts = await _seed_project(session, pid)
        except Exception:
            # One project that cannot be seeded must not take the rest of the demo estate with it.
            logger.warning("staffing demo seed skipped for %s", pid, exc_info=True)
            continue
        totals["projects"] += 1
        for k, v in counts.items():
            totals[k] += v
    return totals


async def before_construction(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """Whether the project stands before the gate into construction, by its own state and nothing else."""
    from app.modules.project_governance import public as governance

    enabling = await governance.phases_enabling(session, project_id, "construction_start")
    gates = await governance.project_gates(session, project_id)
    gate = next((g for g in gates if g.to_phase in enabling), None)
    return gate is not None and gate.status != "decided"


def _day(today: date, offset: int | None) -> date | None:
    return None if offset is None else today + timedelta(days=offset)


async def _seed_project(session: AsyncSession, project_id: uuid.UUID) -> dict[str, int]:
    from app.core.demo_marker import demo_id_of
    from app.modules.project_governance.public import demo_module_story, story_text
    from app.modules.projects.models import Project
    from app.modules.staffing import rules
    from app.modules.staffing.service import Actor, StaffingService
    from app.modules.teams.models import RosterMember
    from app.modules.teams.seed import seed_teams_roster

    project = await session.get(Project, project_id)
    story = demo_module_story(demo_id_of(project.metadata_), "staffing")
    locale = getattr(project, "locale", None) or "en"
    cast = story_roster(story, locale)
    if cast:
        # The story names its own people. They are written before the generic demo roster, which then
        # finds a roster and adds nobody, so the files are about people that belong to this project.
        today_ = datetime.now(UTC).date()
        for person in cast:
            session.add(
                RosterMember(
                    project_id=project_id,
                    display_name=person["name"],
                    company_name=person["company"],
                    site_role=person["site_role"],
                    allocation_percent=person["allocation"],
                    starts_on=today_ - timedelta(days=60),
                    certifications=[],
                )
            )
        await session.flush()
    else:
        await seed_teams_roster(session, project_id=project_id)
    members = list(
        (
            await session.execute(
                select(RosterMember)
                # Only the invented people of the demo roster. A roster row linked to an account or a
                # contact is a real person, and a personnel file is never seeded about one.
                .where(
                    RosterMember.project_id == project_id,
                    RosterMember.user_id.is_(None),
                    RosterMember.contact_id.is_(None),
                    # With a story cast only those people: other roster rows (the client organisation)
                    # are not staff of the project.
                    *([RosterMember.display_name.in_([p["name"] for p in cast])] if cast else []),
                )
                .order_by(RosterMember.created_at, RosterMember.id)
            )
        ).scalars()
    )
    owner = project.owner_id
    # The project owner plans the demo and is the line manager of every position, which is what lets
    # them open the files. The erase permission is not needed and not taken.
    actor = Actor(owner, personnel_read=True, personnel_edit=True, assign_owner=True, manage=True)
    currency = (getattr(project, "currency", "") or "").strip()
    priced = len(currency) == 3 and currency.isalpha()
    svc = StaffingService(session)
    today = datetime.now(UTC).date()
    early = await before_construction(session, project_id)
    # A story tells both moments: ``positions`` before the gate, ``running_positions`` once the site runs.
    planned = (
        story_positions(story, POSITIONS_BEFORE_CONSTRUCTION)
        if early
        else story_positions(story, POSITIONS, "running_positions")
    )
    commissioning = COMMISSIONING_BEFORE_CONSTRUCTION_IN_DAYS if early else COMMISSIONING_IN_DAYS
    commissioning_key = "commissioning_in_days" if early else "running_commissioning_in_days"
    if _int(story.get(commissioning_key)) is not None:
        commissioning = story[commissioning_key]
    mobilisation = _int(story.get("mobilisation_in_days")) if early else None
    mobilisation = MOBILISATION_IN_DAYS if mobilisation is None else mobilisation
    filled = [r for r in story.get("filled", ()) if isinstance(r, str)] if isinstance(story.get("filled"), list) else []
    filled = filled or list(FILLED)
    expiring = {
        **EXPIRING,
        **{(r, k): d for r, k, row in story_pairs(story, "expiring") if (d := _int(row.get("days")))},
    }
    missing = {(r, k) for r, k, _ in story_pairs(story, "missing")} or {MISSING}
    waived = {(r, k) for r, k, _ in story_pairs(story, "waived")} or {WAIVED}
    handovers = story_handovers(story, locale, HANDOVERS)
    # Words a story may give in the project's language: the note of a waived document and the trip endpoints.
    waiver_note = story_text(story.get("waiver_note"), locale) or (
        "Renewal filed with the registration body; confirmation of receipt is on file."
    )
    home_place = story_text(story.get("home_place"), locale) or "Home city"
    site_place = story_text(story.get("site_place"), locale) or "Site"

    await svc.set_plan(
        project_id,
        actor_id=owner,
        tenant_id=None,
        commissioning_date=today + timedelta(days=commissioning),
    )
    catalogue = await svc.catalogue_for(await svc.require_plan(project_id))
    counts = {"positions": 0, "fills": 0, "files": 0, "documents": 0, "submitted": 0}

    positions: dict[str, Any] = {}
    for role_code, phase, entry, leaving, status in planned:
        if catalogue.role(role_code) is None:
            continue
        row = await svc.create_position(
            project_id,
            {
                "role_code": role_code,
                "phase": phase,
                "entry_date": _day(today, entry),
                "exit_date": _day(today, leaving),
                "owner_user_id": owner,
                "recruiting_channel": "agency" if status == "recruiting" else None,
            },
            actor,
        )
        if status != "open":
            await svc.set_position_status(project_id, row.id, status, owner)
        if status == "recruiting":
            await svc.request_resource(project_id, row.id, owner)
        positions[role_code] = row
        counts["positions"] += 1

    fills: dict[str, Any] = {}
    files: dict[str, Any] = {}
    for role_code, member in assign_roles([r for r in filled if r in positions], members):
        position = positions[role_code]
        fill = await svc.create_fill(
            project_id,
            position.id,
            {"roster_member_id": member.id, "fte_share": str(position.fte), "from_date": position.entry_date},
            owner,
        )
        await svc.confirm_fill(project_id, fill.id, actor)
        fills[role_code] = fill
        counts["fills"] += 1

        needs_permit = role_code == PERMIT_HOLDER
        pfile = await svc.create_file(
            project_id,
            {
                "roster_member_id": member.id,
                "employer_organisation": member.company_name or "",
                "employment_basis": "employee",
                "nationality_required": needs_permit,
                "lawful_basis": "contract",
            },
            actor,
        )
        files[role_code] = pfile
        counts["files"] += 1
        # Signed a month before the first day, and never in the future.
        hired = min(position.entry_date, today) - timedelta(days=30)
        for kind_code in rules.required_document_kinds(catalogue, [role_code], "employee", needs_permit):
            kind = catalogue.document_kind(kind_code)
            if kind is None or (role_code, kind_code) in missing:
                continue
            if (role_code, kind_code) in waived:
                await svc.waive_document(
                    project_id,
                    pfile.id,
                    kind_code,
                    waiver_note,
                    actor,
                )
                continue
            if kind_code in OPEN_ENDED:
                valid_until = None
            else:
                valid_until = today + timedelta(days=expiring.get((role_code, kind_code), 400))
            await svc.record_document(
                project_id,
                pfile.id,
                {
                    "document_kind": kind_code,
                    "issued_at": hired,
                    "valid_until": valid_until,
                    "number_last4": "4821" if kind.store_number else None,
                    "fit_for_role": "yes" if kind_code == "occupational_health_certificate" else None,
                },
                actor,
            )
            counts["documents"] += 1

    def trip(kind: str, depart: int, back: int | None, amount: str) -> dict[str, Any]:
        priced_part = {"cost": amount, "currency": currency} if priced else {}
        return {
            "kind": kind,
            "from_place": home_place,
            "to_place": site_place,
            "depart_date": today + timedelta(days=depart),
            "return_date": _day(today, back),
            **priced_part,
        }

    if early:
        # Nobody has travelled to a site that does not exist yet: the site team arrives the day before it starts.
        for role_code, amount in zip(MOBILISED, ("420.00", "380.00", "360.00", "340.00"), strict=True):
            if role_code in files:
                await svc.create_travel(
                    project_id,
                    files[role_code].id,
                    trip("mobilisation", mobilisation - 1, None, amount),
                    actor,
                )
    elif "document_controller" in files:
        # Arrives one day before the first working day.
        await svc.create_travel(
            project_id, files["document_controller"].id, trip("mobilisation", 9, None, "380.00"), actor
        )
    if not early and "site_manager" in files:
        await svc.create_travel(project_id, files["site_manager"].id, trip("rotation", 20, 34, "240.00"), actor)
    if not early and "project_manager" in files:
        done = await svc.create_travel(
            project_id, files["project_manager"].id, trip("business", -20, -18, "510.00"), actor
        )
        for status in ("booked", "done"):
            await svc.update_travel(project_id, files["project_manager"].id, done.id, {"status": status}, actor)
    if "cost_manager" in files:
        leave, _warnings = await svc.create_leave(
            project_id,
            files["cost_manager"].id,
            {
                "leave_type": "annual",
                "from_date": today + timedelta(days=40),
                "to_date": today + timedelta(days=51),
            },
            actor,
        )
        await svc.set_leave_status(project_id, files["cost_manager"].id, leave.id, "approved", actor)
    if "design_manager" in files:
        await svc.create_leave(
            project_id,
            files["design_manager"].id,
            {
                "leave_type": "training",
                "from_date": today + timedelta(days=15),
                "to_date": today + timedelta(days=17),
            },
            actor,
        )

    # A handover needs somebody filling the giving role; a demo project with fewer people than roles has none.
    short_staffed = any(giver not in fills for giver, _, _, _ in handovers)
    for giver, receiver, overlap, scope in handovers:
        if giver in fills and receiver in positions:
            await svc.create_handover(
                project_id,
                {
                    "from_fill_id": fills[giver].id,
                    "to_position_id": positions[receiver].id,
                    "overlap_days": overlap,
                    "scope": scope,
                },
                owner,
            )
    if early:
        counts["submitted"] = int(await _submit_for_the_gate(svc, project_id, owner, short_staffed=short_staffed))
    return counts


async def _submit_for_the_gate(
    svc: Any, project_id: uuid.UUID, owner: uuid.UUID, *, short_staffed: bool = False
) -> bool:
    """Before the gate the plan is with the reviewer. Approval stays the gate's decision, never the seeder's.

    Asked first, never tried: a submission that would be refused is not sent.
    """
    from app.modules.staffing import hosting, rules

    frame = await svc._resolve_frame_document(project_id)
    refused = rules.plan_action_refusal(
        "submit",
        "draft",
        can_edit=True,
        has_frame_document=frame is not None,
        gates_in_use=await hosting.gates_in_use(svc.session, project_id),
    )
    if refused:
        # A legal state: the project's phase model carries no document for staffing. The plan stays a draft.
        logger.info("staffing demo seed: plan of %s stays a draft (%s)", project_id, refused)
        return False
    errors = sorted(f.code for f in await svc.submission_findings(project_id) if f.severity == rules.ERROR)
    if errors and short_staffed and set(errors) <= {"handover_missing"}:
        # Too few people on the team to hand anything over: the plan honestly waits for them. Legal, so info.
        logger.info("staffing demo seed: plan of %s stays a draft, nobody to hand over from (%s)", project_id, errors)
        return False
    if errors:
        # The seeded plan itself is incomplete: a seed defect worth reading, not a reason to lose the project.
        logger.warning("staffing demo seed: plan of %s stays a draft (%s)", project_id, errors)
        return False
    await svc.submit(project_id, owner)
    return True
