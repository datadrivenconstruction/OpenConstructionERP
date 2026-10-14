# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo HSE frame for the German demo projects.

A project that is placed in Germany gets a frame on the catalogue its country
and Land resolve to, filled the way the owner's project team would have it
before construction starts: the facts that decide the duties (duration,
workers, employers, hazardous works), the register created from the catalogue
templates, roles, the permit conditions merged from the permits module and
links to the incidents, permits to work and audits the other seeders wrote.

Everything goes through the service, so the demo obeys the rules of user
input. Persons come from the project's own people (owner, demo cast, team
members); no name is invented, and where nobody is available a role stays
proposed.

Two stories, chosen by the project's Land and told as data below:

* Bavaria, a residential quarter: the frame is ready for the gate into
  execution, the coordinators are appointed and the notice went out.
* Baden-Wuerttemberg, a school: the frame is in progress, the execution
  coordinator is proposed, one clearance and the plan are still open.

A project is skipped when it is outside Germany or already has a frame, so a
customer's project is never written to and a re-run adds nothing. Dates count
from the day the seed runs.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hse_frame import schemas as s
from app.modules.hse_frame.models import HseItem
from app.modules.hse_frame.vocab import LATER_WORKS_STATUSES

logger = logging.getLogger(__name__)

# Days from the seed day to the start of construction, as in the other demo stories.
_START = 190


@dataclass(frozen=True)
class Story:
    duration_working_days: int
    peak_workers: int
    person_days: int
    employers: int
    hazardous: tuple[str, ...]
    notice_sent_days_ago: int | None
    plan_issued_days_ago: int | None
    later_works: str
    # Template codes that stay open (everything else mandatory is met).
    open_templates: frozenset[str] = frozenset()
    execution_coordinator_appointed: bool = True
    notes: str = ""
    # Template code -> (days until due, responsible party).
    due: dict[str, tuple[int, str]] = field(default_factory=dict)
    reference: str = "VA-2026-0417"
    evidence_note: str = "Nachweis liegt im Projektdokumentenordner."
    coordination_org: str = "SiGe-Koordination"
    owner_org: str = "Bauherr"
    qualification: str = "Qualifiziert nach RAB 30"
    parties: dict[str, str] = field(default_factory=lambda: dict(_PARTY))


_STORIES: dict[str, Story] = {
    # Four multi-family buildings with a shared underground garage, about 28 months of construction.
    "DE-BY": Story(
        duration_working_days=590,
        peak_workers=140,
        person_days=39000,
        employers=14,
        hazardous=("heavy_precast",),
        notice_sent_days_ago=9,
        plan_issued_days_ago=12,
        later_works="complete",
        notes="Die Balkone sind Fertigteile mit mehr als 10 t Stückgewicht; der Kranplan ist Teil des SiGe-Plans.",
    ),
    # A primary school with a sports hall, about 22 months of construction.
    "DE-BW": Story(
        duration_working_days=450,
        peak_workers=95,
        person_days=21000,
        employers=11,
        hazardous=("heavy_precast", "excavation_deep"),
        notice_sent_days_ago=None,
        plan_issued_days_ago=None,
        later_works="draft",
        open_templates=frozenset({"de_advance_notice", "de_sige_plan", "archaeology_clearance", "de_later_works_file"}),
        execution_coordinator_appointed=False,
        notes="Die Baugrube der Sporthalle ist tiefer als 5 m und liegt neben dem Bestandsgebäude der Schule.",
        due={
            "de_advance_notice": (_START - 28, "Projektsteuerung Bauherr"),
            "de_sige_plan": (_START - 21, "SiGe-Koordination"),
            "archaeology_clearance": (_START - 60, "Projektsteuerung Bauherr"),
            "de_later_works_file": (_START + 400, "SiGe-Koordination"),
        },
    ),
}
_DEFAULT_STORY = "DE-BW"
_PARTY = {
    "owner": "Projektsteuerung Bauherr",
    "designer": "Generalplaner",
    "contractor": "Generalunternehmer",
    "coordinator": "SiGe-Koordination",
    "operator": "Betreiber",
}
_TOTALS = ("projects", "items", "met", "roles", "linked_conditions", "links")


async def _people(session: AsyncSession, pid: uuid.UUID, owner_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID | None]:
    """``(owner, a second person who can open the project)``; the second is ``None`` when nobody qualifies."""
    from app.core import demo_cast
    from app.modules.project_governance import public
    from app.modules.teams.models import Team, TeamMembership

    cast = await demo_cast.find_cast(session)
    team = list(
        (
            await session.execute(
                select(TeamMembership.user_id)
                .join(Team, Team.id == TeamMembership.team_id)
                .where(Team.project_id == pid)
                .order_by(TeamMembership.created_at)
            )
        ).scalars()
    )
    for uid in (cast.get("cost"), cast.get("decider"), *team):
        if uid is not None and uid != owner_id and await public.user_can_access_project(session, pid, uid):
            return owner_id, uid
    return owner_id, None


async def _name(session: AsyncSession, user_id: uuid.UUID | None) -> str:
    if user_id is None:
        return ""
    from app.modules.users.models import User

    return (await session.execute(select(User.full_name).where(User.id == user_id))).scalar_one_or_none() or ""


async def _link_first(
    session: AsyncSession, svc: Any, pid: uuid.UUID, item_id: uuid.UUID, kind: str, actor: uuid.UUID
) -> int:
    """Link the project's first record of ``kind`` to an item; 0 when the project has none."""
    from app.modules.hse_frame import links

    model = links._model(kind)
    if model is None:
        return 0
    row_id = (
        await session.execute(select(model.id).where(model.project_id == pid).order_by(model.created_at).limit(1))
    ).scalar_one_or_none()
    if row_id is None:
        return 0
    await svc.add_link(pid, item_id, s.LinkCreate(link_kind=kind, link_id=str(row_id)), actor)
    return 1


async def _seed_project(
    session: AsyncSession, pid: uuid.UUID, totals: dict[str, int], today: date, overlay: dict[str, Any]
) -> None:
    from app.modules.hse_frame.service import HseFrameService
    from app.modules.projects.models import Project

    project = await session.get(Project, pid)
    if project is None or not str(getattr(project, "country_code", "") or "").upper().startswith("DE"):
        return
    svc = HseFrameService(session)
    if await svc.frame(pid) is not None:
        return
    story = told(
        _STORIES.get(str(getattr(project, "subdivision_code", "") or "").upper(), _STORIES[_DEFAULT_STORY]), overlay
    )
    owner, second = await _people(session, pid, project.owner_id)
    coordinator = second or owner

    await svc.ensure_frame(pid, owner)
    await svc.patch_frame(
        pid,
        s.FramePatch(
            planned_start=today + timedelta(days=_START),
            duration_working_days=story.duration_working_days,
            peak_workers=story.peak_workers,
            person_days=story.person_days,
            employers_count=story.employers,
            hazardous_work_codes=list(story.hazardous),
            hazardous_works_assessed=True,
            advance_notice_sent_on=None
            if story.notice_sent_days_ago is None
            else today - timedelta(days=story.notice_sent_days_ago),
            advance_notice_reference="" if story.notice_sent_days_ago is None else story.reference,
            plan_status="not_started" if story.plan_issued_days_ago is None else "issued",
            plan_issued_on=None
            if story.plan_issued_days_ago is None
            else today - timedelta(days=story.plan_issued_days_ago),
            later_works_status=story.later_works,
            notes=story.notes,
        ),
        owner,
    )
    await svc.apply_templates(pid, owner)

    # Register: mandatory rows are met unless the story keeps them open; recommended ones stay open.
    items: Iterable[HseItem] = await svc.repo.list(HseItem, pid, HseItem.topic, HseItem.created_at)
    for index, item in enumerate(items):
        totals["items"] += 1
        template = item.template_code or ""
        parties = [a for a in item.audience if a in story.parties]
        party = story.parties[parties[0]] if parties else story.parties.get("owner", "")
        due_in, party_override = story.due.get(template, (_START - 45 + index, party))
        item.responsible_party = party_override
        item.due_date = today + timedelta(days=due_in)
        if item.obligation != "mandatory" or template in story.open_templates:
            if template == "de_sige_plan":
                item.status = "in_progress"
            continue
        await svc.meet_item(
            pid,
            item.id,
            s.ItemMeet(
                met_on=today - timedelta(days=20 + 3 * index),
                evidence_note=story.evidence_note,
            ),
        )
        item.due_date = None
        totals["met"] += 1

    # Roles: persons are the project's own people.
    appointed = today - timedelta(days=210)
    role_plan = (
        ("safety_coordinator_design", coordinator, "appointed", appointed, True),
        (
            "safety_coordinator_execution",
            coordinator,
            "appointed" if story.execution_coordinator_appointed else "proposed",
            today - timedelta(days=20) if story.execution_coordinator_appointed else None,
            True,
        ),
        ("owner_hse_representative", owner, "appointed", today - timedelta(days=400), False),
        ("contractor_hse_manager", None, "proposed", None, False),
    )
    catalogue = await svc.project_catalogue(pid)
    for code, person, status, on, qualified in role_plan:
        if catalogue.entry("role_kinds", code) is None or (person is None and status != "proposed"):
            continue
        await svc.create_role(
            pid,
            s.RoleCreate(
                role_code=code,
                person_user_id=person,
                person_name=await _name(session, person) if person else "",
                organisation="" if person is None else story.coordination_org if qualified else story.owner_org,
                status=status,
                appointed_on=on if status == "appointed" else None,
                qualification=story.qualification if qualified and status == "appointed" else "",
                qualification_valid_until=today + timedelta(days=700) if qualified and status == "appointed" else None,
            ),
            owner,
        )
        totals["roles"] += 1

    # Permit conditions that concern health, safety or the environment become register rows.
    merged = await svc.consolidate_permit_conditions(pid, owner)
    totals["linked_conditions"] += merged["created"]

    # Link what the other seeders wrote: a risk assessment, a permit to work, an audit, an incident.
    by_template = {i.template_code: i for i in await svc.repo.list(HseItem, pid) if i.template_code}
    anchors = (
        ("de_hazard_assessment", "hse_jsa"),
        ("de_hazard_assessment", "hse_ptw"),
        ("de_planning_principles", "hse_audit"),
        ("contractor_safety_management", "safety_incident"),
    )
    for template, kind in anchors:
        item = by_template.get(template)
        if item is not None:
            totals["links"] += await _link_first(session, svc, pid, item.id, kind, owner)

    # The frame goes to review the way the story tells it: submitted by the owner when nothing blocks.
    if story.execution_coordinator_appointed and not story.open_templates:
        try:
            await svc.submit(pid, owner, today)
        except Exception:
            logger.info("hse_frame: demo frame of %s stays a draft", pid, exc_info=True)
    totals["projects"] += 1


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def told(base: Story, overlay: dict[str, Any]) -> Story:
    """``base`` with the keys of the pack's story laid over it; a key that is absent or malformed keeps the default."""
    changes: dict[str, Any] = {}
    for key in ("duration_working_days", "peak_workers", "person_days", "employers"):
        if (value := _int(overlay.get(key))) is not None:
            changes[key] = value
    for key in ("notice_sent_days_ago", "plan_issued_days_ago"):
        if key in overlay and (overlay[key] is None or _int(overlay[key]) is not None):
            changes[key] = overlay[key]
    for key in ("reference", "evidence_note", "coordination_org", "owner_org", "qualification", "notes"):
        if (value := _text(overlay.get(key))) is not None:
            changes[key] = value
    if overlay.get("later_works") in LATER_WORKS_STATUSES:
        changes["later_works"] = overlay["later_works"]
    if isinstance(overlay.get("execution_coordinator_appointed"), bool):
        changes["execution_coordinator_appointed"] = overlay["execution_coordinator_appointed"]
    for key in ("hazardous", "open_templates"):
        value = overlay.get(key)
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            changes[key] = tuple(value) if key == "hazardous" else frozenset(value)
    parties = overlay.get("parties")
    if isinstance(parties, dict):
        changes["parties"] = {**base.parties, **{k: v for k, v in parties.items() if isinstance(v, str)}}
    due = overlay.get("due")
    if isinstance(due, dict):
        rows = {
            code: (row["days"], row["party"])
            for code, row in due.items()
            if isinstance(row, dict) and isinstance(row.get("days"), int) and isinstance(row.get("party"), str)
        }
        changes["due"] = {**base.due, **rows}
    return replace(base, **changes)


async def _pack_story(session: AsyncSession, pid: uuid.UUID) -> dict[str, Any]:
    """What the active pack tells for this demo project, or nothing for a project that is not a demo."""
    from app.core.demo_marker import demo_id_of
    from app.modules.project_governance.public import demo_module_story
    from app.modules.projects.models import Project

    project = await session.get(Project, pid)
    demo_id = demo_id_of(getattr(project, "metadata_", None))
    return demo_module_story(demo_id, "hse_frame") if demo_id else {}


async def seed_hse_frame_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seed the demo frame of every German project in ``project_ids`` that has none yet."""
    totals = dict.fromkeys(_TOTALS, 0)
    today = datetime.now(UTC).date()
    for pid in project_ids:
        try:
            overlay = await _pack_story(session, pid)
            async with session.begin_nested():
                await _seed_project(session, pid, totals, today, overlay)
        except Exception:
            logger.warning("hse_frame: demo seed failed for project %s", pid, exc_info=True)
    return totals
