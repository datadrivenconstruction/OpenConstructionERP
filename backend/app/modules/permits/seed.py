# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo permit roadmap and condition register, run by ``app.core.demo_enrichment``.

Each demo project gets the permit catalogue its country resolves to and a
roadmap an owner would actually run: the preliminary decision (granted), the
main building permit (granted with conditions: one suspensive before-start
condition still open, a noise obligation in force, a before-occupation
condition), an early start at own risk under review, a road occupation permit
being prepared and the occupancy approval still to come. Permit types are
picked from the catalogue by category and scope, never by a national code, so
the same seeder serves every country. Everything goes through the service, so
the rows obey the same rules a user would meet.

A project that stands before the gate into construction (its governance model
has such a gate and the gate is not decided) gets the same roadmap at an
earlier moment: nothing of the execution has happened, so the early start is
still under review and exactly one before-start condition is open, with its
evidence submitted and waiting for the second pair of eyes. The moment is read
from the project's own state through the governance port, never from a
catalogue id or a name. Every other project keeps the story of a site that has
started.

Only projects carrying the demo marker are touched; a project that already
has a roadmap is skipped, so a re-run never duplicates.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Story:
    """When things happened, in days before the seed day (``*_in``: days after it)."""

    prelim_filed: int
    prelim_granted: int
    building_filed: int
    clock_stopped: int
    clock_resumed: int
    building_granted: int
    building_served: int
    early_filed: int
    # ``None``: the early start is still under review.
    early_granted: int | None
    discharge_filed: int
    discharge_decided: int
    start_in: int
    early_needed_in: int
    road_needed_in: int
    occupancy_needed_in: int
    fence_due_in: int
    # When the structural calculations of condition 1 fall due: before the start, so already past on a running site.
    calc_due_in: int
    # The special use of the road for crane, hoarding and site access: ``None`` while it is only being prepared.
    road_filed: int | None = None
    road_granted: int | None = None


# A site that has started: the early start was granted long before the building permit, and the
# road authority granted the special use of the road before the pit was opened.
_STARTED = _Story(
    330, 260, 190, 160, 141, 30, 27, 150, 128, 20, 8, 45, 20, 60, 540, -20, -35, road_filed=50, road_granted=28
)
# Before the gate into construction: the permit is three weeks old and nothing has been built.
_BEFORE_CONSTRUCTION = _Story(210, 150, 140, 110, 96, 20, 18, 10, None, 14, 6, 190, 175, 175, 600, 21, 21)


async def _story(session: AsyncSession, pid: uuid.UUID) -> _Story:
    """The pre-construction story where the project has an undecided gate into construction."""
    from app.modules.project_governance import public

    phases = await public.phases_enabling(session, pid, "construction_start")
    gates = [g for g in await public.project_gates(session, pid) if g.to_phase in phases]
    if gates and all(g.status != "decided" for g in gates):
        return _BEFORE_CONSTRUCTION
    return _STARTED


async def _second_person(session: AsyncSession, pid: uuid.UUID, owner: uuid.UUID) -> uuid.UUID:
    """A team member other than the project owner, so the owner can be the second pair of eyes.

    A discharge is always four eyes: whoever owns the condition or handed in its evidence
    cannot verify it. Without a second member the owner holds both roles and the open
    condition waits for someone else.
    """
    from app.modules.teams.models import Team, TeamMembership

    stmt = (
        select(TeamMembership.user_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.project_id == pid, TeamMembership.user_id != owner)
        .order_by(TeamMembership.user_id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() or owner


async def seed_permits_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seed the roadmap of every demo project in ``project_ids`` that has none. The caller commits."""
    from app.core.demo_marker import demo_id_of
    from app.modules.permits.models import PermitRoadmap
    from app.modules.projects.models import Project

    totals = {"projects": 0, "requirements": 0, "conditions": 0}
    ids = list(project_ids)
    if not ids:
        return totals
    rows = (await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(ids)))).all()
    for pid in [pid for pid, meta in rows if demo_id_of(meta)]:
        has = (
            await session.execute(select(PermitRoadmap.id).where(PermitRoadmap.project_id == pid))
        ).scalar_one_or_none()
        if has is not None:
            continue
        try:
            async with session.begin_nested():
                counts = await _seed_project(session, pid)
        except Exception:
            logger.warning("permits demo seed skipped for %s", pid, exc_info=True)
            continue
        totals["projects"] += 1
        for k, v in counts.items():
            totals[k] += v
    return totals


def _early_start_conditions(owner: uuid.UUID, overrides: dict[str, dict[str, Any]] | None = None) -> list[dict]:
    """What every early start carries (rule 10): restore the site if the permit is refused, and give security."""
    conditions = [
        {
            "number": "1",
            "text": "If the building permit is refused, the site is restored to its previous condition.",
            "kind": "obligation",
            "trigger": "ongoing",
            "topic": "admin",
            "purpose": "restoration",
            "owner_user_id": owner,
        },
        {
            "number": "2",
            "text": "Security for the restoration is lodged with the authority before excavation starts.",
            "kind": "obligation",
            "trigger": "ongoing",
            "topic": "admin",
            "purpose": "security",
            "owner_user_id": owner,
        },
    ]
    return apply_condition_overrides(conditions, overrides or {})


def _pick(types: dict, *, category: str | None = None, scope: str | None = None, route: str | None = None):
    for t in types.values():
        if category and t.category != category:
            continue
        if scope and t.scope != scope:
            continue
        if route and route not in t.triggered_by_route:
            continue
        return t
    return None


# What a story may replace, key by key. A key a story leaves out, or gets wrong, keeps this.
_TEXT_DEFAULTS: dict[str, str] = {
    "preliminary_title": "Preliminary decision on use and building envelope",
    "building_title": "Main building permit",
    "early_title": "Early start of excavation at own risk",
    "road_title": "Road occupation for crane and site access",
    "occupancy_title": "Occupancy approval",
    "authority_name": "Local building authority",
    "preliminary_reference": "PRE-0418",
    "building_reference": "BP-0112",
    "early_reference": "ES-0031",
    "road_authority_name": "Local road authority",
    "road_reference": "SN-0207",
    "clock_stop_reason": "Authority asked for the revised drainage layout",
    "clock_resume_reason": "Revised drainage layout delivered",
    "evidence_note": "Tree protection fence along the northern boundary, photographed from the gate",
}
# Catalogue codes a story may name, with what the permit type has to be for the roadmap to work.
_CODE_KEYS = ("preliminary", "building", "early_start", "road", "occupancy")
_CONDITION_FIELDS = ("text", "topic", "evidence_required", "responsible_party")
# Day offset from the seed day (negative: past) a story may give a condition as its due date.
_DUE_IN_DAYS = "due_in_days"
_EARLY_NUMBERS = ("1", "2")
_CONDITION_NUMBERS = ("1", "2", "3", "4", "5")


def _overrides(raw: object, numbers: tuple[str, ...], locale: str) -> dict[str, dict[str, Any]]:
    """Per-number field overrides of a condition list that carry usable values; the rest is dropped."""
    from app.modules.permits.conditions import TOPICS
    from app.modules.project_governance.public import story_text

    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for number, fields in raw.items():
        if number not in numbers or not isinstance(fields, dict):
            logger.info("permits demo story: condition %r not usable, keeping the default", number)
            continue
        kept: dict[str, Any] = {}
        days = fields.get(_DUE_IN_DAYS)
        if isinstance(days, int) and not isinstance(days, bool) and -720 <= days <= 1500:
            kept[_DUE_IN_DAYS] = days
        elif _DUE_IN_DAYS in fields:
            logger.info(
                "permits demo story: condition %s field %s not usable, keeping the default", number, _DUE_IN_DAYS
            )
        for key in _CONDITION_FIELDS:
            if key not in fields:
                continue
            value = story_text(fields[key], locale)
            if value and (key != "topic" or value in TOPICS):
                kept[key] = value
            else:
                logger.info("permits demo story: condition %s field %s not usable, keeping the default", number, key)
        if kept:
            out[number] = kept
    return out


def resolve_permit_content(story: dict | None, locale: str) -> dict:
    """Texts, codes and condition overrides of a project: today's defaults with the story applied on top.

    Text keys are those of ``_TEXT_DEFAULTS``. ``codes`` names catalogue permit types by the keys
    in ``_CODE_KEYS``; ``conditions`` and ``early_conditions`` map a condition number to a subset of
    ``text``, ``topic``, ``evidence_required`` and ``responsible_party``, plus ``due_in_days`` (the due
    date as a day offset from the seed day). Kind, trigger and owner of
    a condition stay in code. An unusable value keeps the default for that key.
    """
    from app.modules.project_governance.public import story_text

    out: dict = {**_TEXT_DEFAULTS, "codes": {}, "conditions": {}, "early_conditions": {}}
    if not isinstance(story, dict) or not story:
        return out
    for key in _TEXT_DEFAULTS:
        if key in story:
            text = story_text(story[key], locale)
            if text:
                out[key] = text
            else:
                logger.info("permits demo story: %s not usable, keeping the default", key)
    codes = story.get("codes")
    if isinstance(codes, dict):
        out["codes"] = {k: v for k, v in codes.items() if k in _CODE_KEYS and isinstance(v, str) and v}
    out["conditions"] = _overrides(story.get("conditions"), _CONDITION_NUMBERS, locale)
    out["early_conditions"] = _overrides(story.get("early_conditions"), _EARLY_NUMBERS, locale)
    return out


def apply_condition_overrides(
    conditions: list[dict], overrides: dict[str, dict[str, Any]], today: date | None = None
) -> list[dict]:
    """The conditions with the story's text, topic, evidence, party and due date applied by condition number."""
    out = []
    for condition in conditions:
        merged = {**condition, **overrides.get(condition["number"], {})}
        days = merged.pop(_DUE_IN_DAYS, None)
        if days is not None:
            merged["due_date"] = (today or datetime.now(UTC).date()) + timedelta(days=days)
        # An information condition has no party to answer to and nothing to prove.
        if merged.get("kind") == "information":
            merged.pop("evidence_required", None)
            merged.pop("responsible_party", None)
        out.append(merged)
    return out


def pick_by_story(types: dict, codes: dict[str, str], key: str, found, *, ok):
    """The permit type the story names for ``key`` when the catalogue has it and ``ok`` accepts it, else ``found``."""
    code = codes.get(key)
    if code is None:
        return found
    chosen = types.get(code)
    if chosen is not None and ok(chosen):
        return chosen
    logger.info("permits demo story: permit type %r not usable as %s, keeping the default", code, key)
    return found


async def _seed_project(session: AsyncSession, pid: uuid.UUID) -> dict[str, int]:
    from app.modules.permits.service import PermitService
    from app.modules.projects.models import Project

    project = await session.get(Project, pid)
    owner = getattr(project, "owner_id", None)
    if owner is None:
        return {"requirements": 0, "conditions": 0}
    svc = PermitService(session)
    roadmap = await svc.set_roadmap(pid, tenant_id=None, actor_id=owner)
    types = await svc._types(roadmap)
    today = datetime.now(UTC).date()
    story = await _story(session, pid)
    from app.core.demo_marker import demo_id_of
    from app.modules.project_governance.public import demo_module_story

    content = resolve_permit_content(
        demo_module_story(demo_id_of(getattr(project, "metadata_", None)), "permits"),
        getattr(project, "locale", None) or "en",
    )
    codes = content["codes"]
    fence_owner = await _second_person(session, pid, owner)

    def ago(days: int) -> date:
        return today - timedelta(days=days)

    prelim = _pick(types, scope="preliminary")
    building = _pick(types, category="building", scope="full", route="full_permit") or _pick(
        types, scope="full", route="full_permit"
    )
    early = next(
        (
            t
            for t in types.values()
            if t.scope == "early_start" and building and building.code in {r.code for r in t.requires}
        ),
        None,
    )
    road = _pick(types, category="traffic_road")
    occupancy = _pick(types, category="occupancy")
    prelim = pick_by_story(types, codes, "preliminary", prelim, ok=lambda t: t.scope == "preliminary")
    building = pick_by_story(
        types, codes, "building", building, ok=lambda t: t.scope == "full" and "full_permit" in t.triggered_by_route
    )
    early = pick_by_story(
        types,
        codes,
        "early_start",
        early,
        ok=lambda t: (
            t.scope == "early_start" and building is not None and building.code in {r.code for r in t.requires}
        ),
    )
    road = pick_by_story(types, codes, "road", road, ok=lambda t: t.category == "traffic_road")
    occupancy = pick_by_story(types, codes, "occupancy", occupancy, ok=lambda t: t.category == "occupancy")
    if building is None:
        return {"requirements": 0, "conditions": 0}

    async def req(t, title: str, **kw) -> object:
        return await svc.create_requirement(
            pid, {"permit_type_code": t.code, "title": title, "responsible_user_id": owner, **kw}, actor_id=owner
        )

    made = []
    r_pre = await req(prelim, content["preliminary_title"]) if prelim else None
    r_bld = await req(
        building,
        content["building_title"],
        planned_submit_date=ago(story.building_filed + 10),
        needed_by_date=today + timedelta(days=story.start_in),
    )
    made += [r for r in (r_pre, r_bld) if r]
    if r_pre is not None:
        await svc.set_dependencies(pid, r_bld.id, [{"depends_on_id": r_pre.id, "on": "granted"}], actor_id=owner)
    r_early = (
        await req(early, content["early_title"], needed_by_date=today + timedelta(days=story.early_needed_in))
        if early
        else None
    )
    r_road = (
        await req(
            road,
            content["road_title"],
            needed_by_date=today + timedelta(days=story.road_needed_in),
        )
        if road
        else None
    )
    r_occ = (
        await req(
            occupancy, content["occupancy_title"], needed_by_date=today + timedelta(days=story.occupancy_needed_in)
        )
        if occupancy
        else None
    )
    made += [r for r in (r_early, r_road, r_occ) if r]
    if r_early is not None:
        await svc.set_dependencies(pid, r_early.id, [{"depends_on_id": r_bld.id, "on": "submitted"}], actor_id=owner)

    async def file(r, submitted: date, ref: str) -> object:
        app = await svc.create_application(
            pid,
            {"requirement_id": r.id, "authority_name": content["authority_name"], "authority_reference": ref},
            actor_id=owner,
        )
        await svc.transition_application(
            pid, app.id, "preparing", actor_id=owner, can_manage=True, on_date=None, today=submitted
        )
        await svc.transition_application(
            pid, app.id, "submitted", actor_id=owner, can_manage=True, on_date=submitted, today=submitted
        )
        return app

    if r_pre is not None:
        a = await file(r_pre, ago(story.prelim_filed), content["preliminary_reference"])
        await svc.record_decision(
            pid,
            a.id,
            {
                "outcome": "granted",
                "decision_date": ago(story.prelim_granted),
                "reference": content["preliminary_reference"],
            },
            actor_id=owner,
            today=today,
        )
    bp_ref = content["building_reference"]
    a_bld = await file(r_bld, ago(story.building_filed), bp_ref)
    for kind, days, reason in (
        ("stop", story.clock_stopped, content["clock_stop_reason"]),
        ("resume", story.clock_resumed, content["clock_resume_reason"]),
    ):
        await svc.add_clock_event(
            pid, a_bld.id, {"kind": kind, "at": today - timedelta(days=days), "reason": reason}, actor_id=owner
        )
    if r_early is not None and story.early_granted is not None:
        # Filed while the main application was pending and granted well before it: the site was
        # cleared and excavated at the owner's risk until the building permit arrived.
        a = await file(r_early, ago(story.early_filed), content["early_reference"])
        early_decision = await svc.record_decision(
            pid,
            a.id,
            {
                "outcome": "granted_with_conditions",
                "decision_date": ago(story.early_granted),
                "served_date": ago(story.early_granted - 2),
                "reference": content["early_reference"],
                "conditions": _early_start_conditions(owner, content["early_conditions"]),
            },
            actor_id=owner,
            today=today,
        )
        # The security is lodged and the restoration duty is observed since the pit was opened: both stand
        # complied with, so a due date in their past does not read as an overdue obligation.
        for early_condition in await svc.repo.conditions_of_permit(pid, early_decision["permit"].id):
            if early_condition.confirmed and early_condition.trigger == "ongoing":
                await svc.ongoing(pid, early_condition.id, "in_compliance", {}, actor_id=owner, can_manage=True)
    conditions = [
        {
            "number": "1",
            "text": "Before work starts, submit the verified structural calculations for the basement retaining walls.",
            "kind": "suspensive",
            "trigger": "before_start",
            "topic": "structural",
            "owner_user_id": owner,
            "due_date": today + timedelta(days=story.calc_due_in),
            "evidence_required": "Checked calculations with the checking engineer's report",
        },
        {
            "number": "2",
            "text": "Noisy works are permitted on working days between 07:00 and 19:00 only.",
            "kind": "obligation",
            "trigger": "ongoing",
            "topic": "noise",
            "owner_user_id": owner,
            "responsible_party": "Main contractor",
        },
        {
            "number": "3",
            "text": "A tree protection fence is installed before any excavation and kept until completion.",
            "kind": "obligation",
            "trigger": "before_start",
            "topic": "ecology",
            "owner_user_id": fence_owner,
            "due_date": today + timedelta(days=story.fence_due_in),
            "evidence_required": "Dated photograph of the fence in place",
        },
        {
            "number": "4",
            "text": "Before occupation, the fire alarm system is accepted by an approved inspector.",
            "kind": "suspensive",
            "trigger": "before_occupation",
            "topic": "fire",
            "owner_user_id": owner,
        },
        {
            "number": "5",
            "text": "The permit does not replace consents required under other legislation.",
            "kind": "information",
            "trigger": "",
            "topic": "admin",
        },
    ]
    conditions = apply_condition_overrides(conditions, content["conditions"], today)
    granted = await svc.record_decision(
        pid,
        a_bld.id,
        {
            "outcome": "granted_with_conditions",
            "decision_date": ago(story.building_granted),
            "served_date": ago(story.building_served),
            "reference": bp_ref,
            "conditions": conditions,
        },
        actor_id=owner,
        today=today,
    )
    permit = granted["permit"]
    by_number = {c.number: c for c in await svc.repo.conditions_of_permit(pid, permit.id)}
    # The fence is up and photographed; its owner submitted the evidence and a second person has
    # yet to verify it (four eyes), so the register shows one condition waiting for its verifier:
    # the one before-start condition still open, discharged with a single confirmation.
    fence_is_owners = fence_owner == owner
    await svc.add_evidence(
        pid,
        by_number["3"].id,
        {"kind": "photo", "note": content["evidence_note"]},
        actor_id=fence_owner,
        can_manage=fence_is_owners,
    )
    await svc.submit_evidence(pid, by_number["3"].id, actor_id=fence_owner, can_manage=fence_is_owners)
    if story is _STARTED and not fence_is_owners:
        # On a running site the fence went up before the pit was opened and the project owner has
        # verified it, so the before-start condition is closed instead of lingering past its date.
        await svc.discharge(
            pid,
            by_number["3"].id,
            {"mode": "self_certified", "on_date": ago(1 - story.fence_due_in)},
            actor_id=owner,
            today=today,
        )
    # The structural calculations went to the authority, which discharged the condition itself.
    dis = await svc.create_application(
        pid,
        {
            "requirement_id": r_bld.id,
            "kind": "discharge_of_conditions",
            "parent_permit_id": permit.id,
            "discharges_condition_ids": [by_number["1"].id],
            "authority_name": content["authority_name"],
            "authority_reference": f"{bp_ref}/D1",
        },
        actor_id=owner,
    )
    filed_on = ago(story.discharge_filed)
    await svc.transition_application(pid, dis.id, "preparing", actor_id=owner, can_manage=True, today=filed_on)
    await svc.transition_application(
        pid, dis.id, "submitted", actor_id=owner, can_manage=True, on_date=filed_on, today=filed_on
    )
    await svc.record_decision(
        pid,
        dis.id,
        {
            "outcome": "granted",
            "decision_date": ago(story.discharge_decided),
            "reference": f"{bp_ref}/D1",
            "discharged_condition_ids": [by_number["1"].id],
        },
        actor_id=owner,
        today=today,
    )
    if r_early is not None and story.early_granted is None:
        # Applied for so that excavation can begin while the last before-start condition is being
        # cleared; the authority has it under review.
        a = await file(r_early, ago(story.early_filed), content["early_reference"])
        await svc.transition_application(
            pid, a.id, "under_review", actor_id=owner, can_manage=True, today=ago(story.early_filed - 3)
        )
    if r_road is not None:
        # The road is the road authority's, not the building authority's; the file carries both so it never reads empty.
        a = await svc.create_application(
            pid,
            {
                "requirement_id": r_road.id,
                "authority_name": content["road_authority_name"],
                "authority_reference": content["road_reference"],
            },
            actor_id=owner,
        )
        if story.road_filed is None or story.road_granted is None:
            await svc.transition_application(pid, a.id, "preparing", actor_id=owner, can_manage=True, today=today)
        else:
            # On a running site the crane stands and the hoarding takes the pavement: without this permit
            # the start would not be ready, so the authority granted it before the pit was opened.
            filed = ago(story.road_filed)
            await svc.transition_application(pid, a.id, "preparing", actor_id=owner, can_manage=True, today=filed)
            await svc.transition_application(
                pid, a.id, "submitted", actor_id=owner, can_manage=True, on_date=filed, today=filed
            )
            await svc.record_decision(
                pid,
                a.id,
                {
                    "outcome": "granted",
                    "decision_date": ago(story.road_granted),
                    "reference": content["road_reference"],
                },
                actor_id=owner,
                today=today,
            )
    return {"requirements": len(made), "conditions": len(conditions)}
