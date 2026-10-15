# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo commitment matrix for the demo estate, run by ``app.core.demo_enrichment``.

Each demo project gets the authority schedule its catalogue data resolves to,
the project owner as holder of every tier and a second person (a member of the
project's team) who plans and requests, so that four eyes holds. Without such a
member the items are seeded and nothing is requested. The
four items are the ones an owner would plan:

* a works package, released in full and then linked to the first subcontractor
  contract of the project, so it reads committed against a release;
* a long-lead supply that is still planned and past its decision date, with a
  supplier cancellation schedule;
* a design appointment released in tranches: the first decided, the second
  waiting for its approver;
* a contingency drawdown, planned.

A demo project of the active pack may bring its own story (``demo_module_story``) for the
pre-construction items: per item (``works``, ``slot``, ``design``, ``enabling``, ``contingency``)
the title, the planned amount and the item's own figures, and for the slot item the release note,
the cancellation stages and the plant item it is the order of. A key that is absent or malformed
keeps its default, said at info.

Money is in the currency of the project; a project without one is skipped. The
abort terms use the ``custom`` basis with an entered charge: a statutory basis
is chosen by a person from the catalogue, never by this seeder. Requests and
decisions are dated a few days back so the history reads in order.

A project that stands before construction tells another story. It is known by
its own state, read through the governance port: the gate that opens the phase
enabling the construction start exists and is not decided. Nothing of the main
works is released there. Its works package is planned and due at the award;
the design appointment (first tranche decided, second pending) and the supply
order of the main power transformers are released before the gate, each with
what stopping would cost. That order is not placed yet: the manufacturer holds a
slot free of charge, and the release is the authority to sign before the slot
lapses. It is the one item that is a piece of equipment of the plant register,
so it is the one item :func:`link_demo_plant_items` links; one planned item is past its decision date; the
contingency drawdown is planned. All days are offsets from the seed day.

Only projects carrying the demo marker are touched; a project that already
has a matrix is skipped, so a re-run never duplicates. Runs after the
contracts and cost-model seeders, whose documents it links.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# The one demo item that is a piece of equipment of the plant register, in the story of a project
# before construction. The same code names another thing in the construction story (facade units),
# so the link is made by code AND title, never by code alone.
DEMO_SLOT_ITEM_CODE = "CR-002"
DEMO_SLOT_ITEM_TITLE = "Main power transformers: supply order on the held manufacturing slot"
DEMO_SLOT_RELEASE_NOTE = (
    "Authority to sign the supply order before the gate. The manufacturing slot is held free of charge "
    "and lapses if the order is not signed by its conversion date."
)


# What each story section may carry, key by key: "text", "money" (a decimal string above zero),
# "int" (a day count or a charge in days, zero or more), "pct" (a decimal string from 0 to 1).
_SECTIONS: dict[str, dict[str, str]] = {
    "works": {"title": "text", "amount": "money", "lead_time_days": "int", "award_days": "int"},
    "slot": {
        "title": "text",
        "amount": "money",
        "lead_time_days": "int",
        "release_note": "text",
        "salvage_value": "money",
        "source_note": "text",
        "order_signed_days": "int",
        "manufacturing_started_days": "int",
        "order_signed_pct": "pct",
        "manufacturing_started_pct": "pct",
        "release_days_ago": "int",
        "plant_item": "text",
    },
    "design": {
        "title": "text",
        "amount": "money",
        "decision_days": "int",
        "loss_estimate": "money",
        "brief_text": "text",
        "first_amount": "money",
        "first_note": "text",
        "first_condition": "text",
        "second_amount": "money",
        "second_note": "text",
    },
    "enabling": {"title": "text", "amount": "money"},
    "contingency": {"title": "text", "amount": "money"},
    # The story of a project whose site is running: the same four items, told after the gate.
    "running_works": {"title": "text", "source_note": "text", "release_note": "text"},
    "running_facade": {
        "title": "text",
        "amount": "money",
        "source_note": "text",
        "salvage_value": "money",
    },
    "running_design": {
        "title": "text",
        "amount": "money",
        "brief_text": "text",
        "evidence": "text",
        "first_amount": "money",
        "first_note": "text",
        "first_condition": "text",
        "second_amount": "money",
        "second_note": "text",
    },
    "running_contingency": {"title": "text", "amount": "money"},
    "labels": {"scenario": "text"},
}


def _valid_value(kind: str, value: Any) -> bool:
    if kind == "text":
        return isinstance(value, str) and bool(value.strip())
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if kind in ("money", "pct"):
        if not isinstance(value, str):
            return False
        try:
            number = Decimal(value)
        except InvalidOperation:
            return False
        if not number.is_finite():
            return False
        return number > 0 if kind == "money" else Decimal(0) <= number <= Decimal(1)
    return False


def resolve_story(story: dict[str, Any] | None, locale: str = "en") -> dict[str, dict[str, Any]]:
    """The validated overrides of a demo story, per section; a malformed key is left out.

    Texts may be a plain string or a language map. The result holds only the keys that passed, so
    ``result.get("slot", {}).get("title", DEFAULT)`` is the way to read a figure.
    """
    from app.modules.project_governance.public import story_text

    out: dict[str, dict[str, Any]] = {}
    for section, spec in _SECTIONS.items():
        raw = (story or {}).get(section)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            logger.info("commitment_release demo story: section %r is malformed, defaults are kept", section)
            continue
        clean: dict[str, Any] = {}
        for key, value in raw.items():
            kind = spec.get(key)
            candidate = story_text(value, locale) if kind == "text" else value
            if kind is not None and _valid_value(kind, candidate):
                clean[key] = candidate
            else:
                logger.info("commitment_release demo story: %s.%s is unknown or malformed, ignored", section, key)
        out[section] = clean
    return out


async def _story_schedule(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The id of the pack authority schedule the demo story names (``schedule``), ``None`` when it names none."""
    from app.core.demo_marker import demo_id_of
    from app.modules.project_governance.public import demo_module_story
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    if project is None:
        return None
    named = (demo_module_story(demo_id_of(project.metadata_), "commitment_release") or {}).get("schedule")
    return named if isinstance(named, str) and named.strip() else None


async def _story_of(session: AsyncSession, project_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """The validated story of this demo project in its own language, ``{}`` when it has none."""
    from app.core.demo_marker import demo_id_of
    from app.modules.project_governance.public import demo_module_story
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    if project is None:
        return {}
    story = demo_module_story(demo_id_of(project.metadata_), "commitment_release")
    return resolve_story(story, getattr(project, "locale", None) or "en")


async def seed_commitment_release_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seed the matrix of every demo project in ``project_ids`` that has none. The caller commits."""
    from app.core.demo_marker import demo_id_of
    from app.modules.commitment_release.models import CommitmentMatrix
    from app.modules.projects.models import Project

    totals = {
        "projects": 0,
        "items": 0,
        "links": 0,
        "releases": 0,
        "scenarios": 0,
        "releases_skipped_no_rate": 0,
        "cost_lines_linked": 0,
    }
    ids = list(project_ids)
    if not ids:
        return totals
    rows = (await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(ids)))).all()
    demo = [pid for pid, meta in rows if demo_id_of(meta)]
    for pid in demo:
        has = (
            await session.execute(select(CommitmentMatrix.id).where(CommitmentMatrix.project_id == pid))
        ).scalar_one_or_none()
        if has is not None:
            continue
        try:
            async with session.begin_nested():
                counts = await _seed_project(session, pid)
                counts["cost_lines_linked"] = await _link_cost_lines(session, pid)
        except Exception:
            logger.warning("commitment_release demo seed skipped for %s", pid, exc_info=True)
            continue
        totals["projects"] += 1
        for k, v in counts.items():
            # A count the story adds later must not undo a project that was seeded.
            totals[k] = totals.get(k, 0) + v
    return totals


async def _link_cost_lines(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Give every seeded item without one a cost line of the project's own cost spine.

    An item with no cost line trips ``item_has_cost_code`` once per item, so a demo project opens with a
    wall of identical findings. The cost lines come from the project's bill; they are handed out largest
    estimate first, one per item in code order, and a project without cost lines is left alone (the
    findings are then true). Returns how many items were linked.
    """
    from app.modules.commitment_release.models import CommitmentItem
    from app.modules.costmodel.models import CostLine

    items = (
        (
            await session.execute(
                select(CommitmentItem)
                .where(CommitmentItem.project_id == project_id, CommitmentItem.cost_line_id.is_(None))
                .order_by(CommitmentItem.code)
            )
        )
        .scalars()
        .all()
    )
    if not items:
        return 0
    lines = (await session.execute(select(CostLine).where(CostLine.project_id == project_id))).scalars().all()

    def _estimate(line: CostLine) -> Decimal:
        try:
            return Decimal(str(line.estimate_amount or "0"))
        except InvalidOperation:
            return Decimal(0)

    ranked = sorted(lines, key=lambda line: (-_estimate(line), line.code))
    for item, line in zip(items, ranked, strict=False):
        item.cost_line_id = line.id
    await session.flush()
    await _book_linked_contracts(session, project_id)
    return min(len(items), len(ranked))


async def _book_linked_contracts(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Put the schedule lines of each contract an item counts onto that item's cost line.

    The cost frame counts what is committed per cost line, from contract lines that carry one. The demo
    subcontracts come with a schedule of values and no cost line, so the frame read nothing committed
    while the matrix showed the works package bound. A line that already has a cost line keeps it.
    Returns how many contract lines were booked.
    """
    from app.modules.commitment_release.models import CommitmentItem, CommitmentLink
    from app.modules.contracts.models import ContractLine

    rows = (
        await session.execute(
            select(CommitmentLink.target_id, CommitmentItem.cost_line_id)
            .join(CommitmentItem, CommitmentItem.id == CommitmentLink.item_id)
            .where(
                CommitmentLink.project_id == project_id,
                CommitmentLink.kind == "contract",
                CommitmentItem.cost_line_id.is_not(None),
            )
        )
    ).all()
    booked = 0
    for contract_id, cost_line_id in rows:
        lines = (
            (
                await session.execute(
                    select(ContractLine).where(
                        ContractLine.contract_id == contract_id, ContractLine.cost_line_id.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        for line in lines:
            line.cost_line_id = cost_line_id
            booked += 1
    if booked:
        await session.flush()
    return booked


async def _team_member(session: AsyncSession, project_id: uuid.UUID, exclude: uuid.UUID | None) -> uuid.UUID | None:
    from app.modules.teams.models import Team, TeamMembership

    stmt = (
        select(TeamMembership.user_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.project_id == project_id)
        .order_by(TeamMembership.created_at)
    )
    for (uid,) in (await session.execute(stmt)).all():
        if uid and uid != exclude:
            return uid
    return None


async def _cast_cost_person(session: AsyncSession, project_id: uuid.UUID, owner: uuid.UUID) -> uuid.UUID | None:
    """The demo cast's cost person, when the install has a cast and that person is on this project's team.

    Asked by role so that the requester of the story does not depend on which of two memberships
    written in one transaction happens to sort first. ``None`` on an install without a demo cast.
    """
    import importlib

    from app.modules.teams.models import Team, TeamMembership

    try:
        demo_cast = importlib.import_module("app.core.demo_cast")
    except ImportError:
        return None
    cost = (await demo_cast.find_cast(session) or {}).get("cost")
    if cost is None or cost == owner:
        return None
    stmt = (
        select(TeamMembership.id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.project_id == project_id, TeamMembership.user_id == cost)
        .limit(1)
    )
    return cost if (await session.execute(stmt)).scalar_one_or_none() is not None else None


async def _second_person(session: AsyncSession, project_id: uuid.UUID, owner: uuid.UUID) -> uuid.UUID | None:
    """Who plans and requests while the owner approves: a member of this project's team, or nobody.

    Never an account that is not on the project: a project whose only person is its owner is a
    legal state (a pack install without the demo logins), and it is seeded without a release.
    """
    cost = await _cast_cost_person(session, project_id, owner)
    if cost is not None:
        return cost
    return await _team_member(session, project_id, owner)


async def _release(
    svc: Any,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    amount: str,
    currency: str,
    *,
    requester: uuid.UUID,
    approver: uuid.UUID | None,
    note: str,
    days_ago: int,
    conditions: str = "",
) -> bool:
    """Request a release and, with ``approver``, decide it. False (and a warning) when it is refused."""
    from app.modules.commitment_release.errors import CommitmentError

    today = datetime.now(UTC).date()
    try:
        async with svc.session.begin_nested():
            preview = svc.evaluation_out(await svc.preview_release(project_id, item_id, amount, currency, today=today))
            row = await svc.request_release(
                project_id,
                item_id,
                amount=amount,
                currency=currency,
                tranche_note=note,
                external_approval_ref="Owner board minute (demo)" if preview["escalate_outside"] else "",
                actor_id=requester,
                today=today,
            )
            row.created_at = datetime.now(UTC) - timedelta(days=days_ago)
            # A tier every assignee decides has one step each; the owner holds them all here.
            for _step in range(8):
                if approver is None or row.outcome != "pending":
                    break
                row = await svc.decide_release(
                    project_id,
                    item_id,
                    decision="approved",
                    comment="",
                    conditions=conditions,
                    valid_until=None,
                    actor_id=approver,
                    caller_role="admin",
                    today=today,
                )
            if row.decided_at is not None:
                row.decided_at = datetime.now(UTC) - timedelta(days=max(days_ago - 3, 0))
            await svc.session.flush()
    except CommitmentError as exc:
        logger.warning("commitment_release demo: release of %s on %s refused: %s", item_id, project_id, exc.code)
        return False
    return True


async def _readiness_fields(session: AsyncSession, project_id: uuid.UUID) -> dict[str, str]:
    """The gate and the management area a demo item is read at, from the project's own phase model.

    The gate is the one that opens the phase which enables procurement; the area is the one that
    hosts commitment release. Nothing is named when the project has no model or the model says
    neither, so no code of any catalogue is written here.
    """
    from app.modules.project_governance.public import host_for, phases_enabling, project_areas, project_gates

    host = await host_for(session, project_id, "commitment_release")
    phases = set(await phases_enabling(session, project_id, "procurement"))
    gate = next((g.code for g in await project_gates(session, project_id) if g.to_phase in phases), None)
    areas = {a.code for a in await project_areas(session, project_id)}
    if host is None or gate is None or host.area_code not in areas:
        return {}
    return {"gate_code": gate, "governance_area_code": host.area_code}


async def _undecided_start_gate(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The gate that opens the phase enabling the construction start, while it is not decided.

    ``None`` for a project without a phase model, without such a gate, or past it.
    """
    from app.modules.project_governance.public import phases_enabling, project_gates

    phases = set(await phases_enabling(session, project_id, "construction_start"))
    gate = next((g for g in await project_gates(session, project_id) if g.to_phase in phases), None)
    return gate.code if gate is not None and gate.status != "decided" else None


async def _seed_before_construction(
    svc: Any,
    project_id: uuid.UUID,
    *,
    gate: str,
    owner: uuid.UUID,
    planner: uuid.UUID | None,
    ccy: str,
    today: Any,
    counts: dict[str, int],
    story: dict[str, dict[str, Any]] | None = None,
) -> dict[str, int]:
    """The matrix of a project that has not started building (see the module docstring)."""
    from app.modules.project_governance.public import host_for, project_areas

    story = story or {}
    works_s, slot_s, design_s = (story.get(k, {}) for k in ("works", "slot", "design"))
    labels = story.get("labels", {})
    enabling_s, contingency_s = story.get("enabling", {}), story.get("contingency", {})
    author = planner or owner
    host = await host_for(svc.session, project_id, "commitment_release")
    areas = {a.code for a in await project_areas(svc.session, project_id)}
    # What has to be decided before this gate names it; the works package is awarded after it.
    before_gate = (
        {"gate_code": gate, "governance_area_code": host.area_code}
        if host is not None and host.area_code in areas
        else {}
    )

    async def add(code: str, title: str, ctype: str, amount: str, **extra: Any) -> Any:
        row = await svc.create_item(
            project_id,
            {
                "code": code,
                "title": title,
                "commitment_type": ctype,
                "planned_source": "manual",
                "planned_manual_amount": amount,
                "currency": ccy,
                **extra,
            },
            actor_id=author,
        )
        counts["items"] += 1
        return row

    async def loss_estimate(item: Any, charge: str, note: str) -> None:
        await svc.put_abort_terms(
            project_id,
            item.id,
            {"basis_code": "custom", "other_charge_estimate": charge, "source_note": note},
            actor_id=owner,
            manage=True,
        )

    # Planned, due at the award of the main works, waiting for the gate: nothing released, nothing linked.
    await add(
        "CR-001",
        works_s.get("title", "Main works package"),
        "works",
        works_s.get("amount", "1850000"),
        lead_time_days=works_s.get("lead_time_days", 45),
        latest_decision_date_fixed=(today + timedelta(days=works_s.get("award_days", 165))).isoformat(),
    )

    # The supply order that has to be signed before the gate, because the equipment takes longer
    # to make than the wait for it. Not ordered yet: the manufacturer holds a slot free of charge,
    # so the 420,000 is the order itself and no fee exists beside it. The 120 days are this row's
    # own figure for an install without the plant register; linked to its plant item, the
    # register's lead time and latest order date govern, and no need date is copied here.
    slot_amount = slot_s.get("amount", "420000")
    reservation = await add(
        DEMO_SLOT_ITEM_CODE,
        slot_s.get("title", DEMO_SLOT_ITEM_TITLE),
        "supplies",
        slot_amount,
        lead_time_days=slot_s.get("lead_time_days", 120),
        **before_gate,
    )
    await svc.put_abort_terms(
        project_id,
        reservation.id,
        {
            "basis_code": "supply_cancellation_schedule",
            "cancellation_schedule": [
                # Stages of an order that is still to be signed: nothing is charged before it exists.
                {
                    "milestone": "order_signed",
                    "from_date": (
                        today + timedelta(days=slot_s.get("order_signed_days", DEMO_ORDER_SIGNED_DAYS))
                    ).isoformat(),
                    "charge_pct": slot_s.get("order_signed_pct", "0.10"),
                },
                {
                    "milestone": "manufacturing_started",
                    "from_date": (
                        today
                        + timedelta(days=slot_s.get("manufacturing_started_days", DEMO_MANUFACTURING_STARTED_DAYS))
                    ).isoformat(),
                    "charge_pct": slot_s.get("manufacturing_started_pct", "0.50"),
                },
            ],
            "transferable": "resale",
            "salvage_value_estimate": slot_s.get("salvage_value", "60000"),
            "source_note": slot_s.get(
                "source_note", "Budget quotation: cancellation terms that apply once the order is signed"
            ),
        },
        actor_id=owner,
        manage=True,
    )
    if planner is not None and await _release(
        svc,
        project_id,
        reservation.id,
        slot_amount,
        ccy,
        requester=planner,
        approver=owner,
        note=slot_s.get("release_note", DEMO_SLOT_RELEASE_NOTE),
        days_ago=slot_s.get("release_days_ago", 33),
    ):
        counts["releases"] += 1

    design = await add(
        "CR-003",
        design_s.get("title", "Design appointment"),
        "design",
        design_s.get("amount", "260000"),
        latest_decision_date_fixed=(today + timedelta(days=design_s.get("decision_days", 45))).isoformat(),
    )
    await loss_estimate(design, design_s.get("loss_estimate", "25000"), "Demo estimate, not from a contract")
    brief = await svc.add_precondition(
        project_id,
        design.id,
        kind="manual",
        ref_id=None,
        text=design_s.get("brief_text", "Client brief signed off"),
        actor_id=author,
    )
    await svc.confirm_precondition(
        project_id, design.id, brief.id, met=True, evidence_ref="Brief rev. C, signed", actor_id=author
    )
    if planner is not None and await _release(
        svc,
        project_id,
        design.id,
        design_s.get("first_amount", "40000"),
        ccy,
        requester=planner,
        approver=owner,
        note=design_s.get("first_note", "First tranche: concept design"),
        days_ago=63,
        conditions=design_s.get("first_condition", "Design report before the next tranche"),
    ):
        counts["releases"] += 1
        if await _release(
            svc,
            project_id,
            design.id,
            design_s.get("second_amount", "60000"),
            ccy,
            requester=planner,
            approver=None,
            note=design_s.get("second_note", "Second tranche: developed design"),
            days_ago=2,
        ):
            counts["releases"] += 1

    # The one planned item past its decision date: it has to be decided before the gate and is not.
    await add(
        "CR-004",
        enabling_s.get("title", "Enabling works: service diversions"),
        "works",
        enabling_s.get("amount", "95000"),
        latest_decision_date_fixed=(today - timedelta(days=5)).isoformat(),
        **before_gate,
    )
    await add(
        "CR-005",
        contingency_s.get("title", "Contingency drawdown for ground conditions"),
        "contingency_drawdown",
        contingency_s.get("amount", "75000"),
    )
    await svc.save_scenario(project_id, as_of=today, label=labels.get("scenario", "Stop today"), actor_id=owner)
    counts["scenarios"] += 1
    return counts


async def _seed_project(session: AsyncSession, project_id: uuid.UUID) -> dict[str, int]:
    from app.modules.commitment_release.catalogue import DEFAULT_SCHEDULE_ID
    from app.modules.commitment_release.errors import CommitmentError
    from app.modules.commitment_release.fx import FxRateMissing
    from app.modules.commitment_release.service import CommitmentService
    from app.modules.contracts.models import Contract
    from app.modules.projects.models import Project

    counts = {"items": 0, "links": 0, "releases": 0, "scenarios": 0, "releases_skipped_no_rate": 0}
    project = await session.get(Project, project_id)
    owner = project.owner_id
    ccy = (project.currency or "").strip().upper()
    if owner is None or not ccy:
        # No owner to hold the tiers, or no currency to plan in: nothing honest can be seeded.
        logger.info("commitment_release demo: project %s has no owner or no currency, skipped", project_id)
        return counts
    planner = await _second_person(session, project_id, owner)
    if planner is None:
        # Four eyes: the owner holds the tiers and cannot approve a request of their own. A
        # one-person project is an ordinary install, so this is said quietly and nothing fails.
        logger.info(
            "commitment_release demo: project %s has nobody but its owner, items are seeded without a release",
            project_id,
        )
    author = planner or owner
    readiness = await _readiness_fields(session, project_id)
    today = datetime.now(UTC).date()
    svc = CommitmentService(session)
    matrix = await svc.set_matrix(project_id, actor_id=owner, tenant_id=None)
    named = await _story_schedule(session, project_id)
    if named:
        # The story names the schedule of its client: the country default is the one of a public owner,
        # and a private company decides through its own management and board.
        try:
            matrix = await svc.set_matrix(
                project_id, actor_id=owner, tenant_id=None, schedule_source="pack", schedule_id=named
            )
        except CommitmentError:
            logger.info("commitment_release demo story: schedule %r cannot be pinned, the default is kept", named)
    schedule = await svc.schedule_for(matrix)
    if schedule.currency and schedule.currency.strip().upper() != ccy:
        # A national schedule counts in its own currency. On a project in another one every figure
        # would need an exchange rate the demo does not have, so the neutral schedule (which counts
        # in the project's currency) is pinned instead. Nothing is released yet, so the pin is free.
        matrix = await svc.set_matrix(
            project_id, actor_id=owner, tenant_id=None, schedule_source="shipped", schedule_id=DEFAULT_SCHEDULE_ID
        )
        schedule = await svc.schedule_for(matrix)
    roles = [t.approver.ref for t in schedule.tiers if t.approver.kind == "project_role"]
    await svc.put_assignments(
        project_id,
        [{"project_role": r, "user_id": owner, "valid_from": today - timedelta(days=60)} for r in roles],
        actor_id=owner,
        today=today,
    )

    gate = await _undecided_start_gate(session, project_id)
    if gate is not None:
        return await _seed_before_construction(
            svc,
            project_id,
            gate=gate,
            owner=owner,
            planner=planner,
            ccy=ccy,
            today=today,
            counts=counts,
            story=await _story_of(session, project_id),
        )

    contract = (
        await session.execute(
            select(Contract)
            .where(Contract.project_id == project_id, Contract.counterparty_type == "subcontractor")
            .order_by(Contract.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    story = await _story_of(session, project_id)
    labels = story.get("labels", {})
    works_s, facade_s = story.get("running_works", {}), story.get("running_facade", {})
    design_s, contingency_s = story.get("running_design", {}), story.get("running_contingency", {})
    works_amount = str(contract.total_value) if contract is not None and contract.total_value else "1850000"
    works_ccy = (contract.currency if contract is not None and contract.currency else ccy).strip().upper()

    works = await svc.create_item(
        project_id,
        {
            "code": "CR-001",
            "title": works_s.get("title", "Structural works package"),
            "commitment_type": "works",
            "planned_source": "manual",
            "planned_manual_amount": works_amount,
            "currency": works_ccy,
            "lead_time_days": 45,
            "decision_buffer_days": 10,
            "latest_decision_date_fixed": (today - timedelta(days=14)).isoformat(),
            **readiness,
        },
        actor_id=author,
    )
    counts["items"] += 1
    await svc.put_abort_terms(
        project_id,
        works.id,
        {
            "basis_code": "custom",
            "other_charge_estimate": "40000",
            "source_note": works_s.get("source_note", "Demo estimate, not from a contract"),
        },
        actor_id=owner,
        manage=True,
    )
    # A seeder never sends a request it can know will be refused, and never invents a rate: a
    # subcontract in a currency the schedule cannot convert is left planned, and the result says so.
    convertible = True
    try:
        await svc.quote(matrix, project, works_ccy, svc.schedule_currency(schedule, project), today)
    except FxRateMissing:
        convertible = False
        if planner is not None:
            counts["releases_skipped_no_rate"] += 1
            logger.info(
                "commitment_release demo: project %s has no exchange rate for %s, the works release is not requested",
                project_id,
                works_ccy,
            )
    if (
        planner is not None
        and convertible
        and await _release(
            svc,
            project_id,
            works.id,
            works_amount,
            works_ccy,
            requester=planner,
            approver=owner,
            note=works_s.get("release_note", "Full package"),
            days_ago=21,
        )
    ):
        counts["releases"] += 1
        if contract is not None:
            # Linked only once released, so the contract never reads committed against nothing.
            await svc.add_link(project_id, works.id, "contract", contract.id, actor_id=author, manage=True)
            counts["links"] += 1

    facade = await svc.create_item(
        project_id,
        {
            "code": "CR-002",
            "title": facade_s.get("title", "Long-lead facade units"),
            "commitment_type": "supplies",
            "planned_source": "manual",
            "planned_manual_amount": facade_s.get("amount", "420000"),
            "currency": ccy,
            "lead_time_days": 120,
            "decision_buffer_days": 14,
            "latest_decision_date_fixed": (today - timedelta(days=5)).isoformat(),
            **readiness,
        },
        actor_id=author,
    )
    counts["items"] += 1
    await svc.put_abort_terms(
        project_id,
        facade.id,
        {
            "basis_code": "supply_cancellation_schedule",
            "cancellation_schedule": [
                {"milestone": "order", "from_date": today.isoformat(), "charge_pct": "0.10"},
                {
                    "milestone": "fabrication",
                    "from_date": (today + timedelta(days=60)).isoformat(),
                    "charge_pct": "0.50",
                },
                {"milestone": "shipped", "progress_pct": "0.9", "charge_pct": "0.95"},
            ],
            "transferable": "resale",
            "salvage_value_estimate": facade_s.get("salvage_value", "60000"),
            "source_note": facade_s.get("source_note", "Supplier quotation, cancellation terms"),
        },
        actor_id=owner,
        manage=True,
    )

    design = await svc.create_item(
        project_id,
        {
            "code": "CR-003",
            "title": design_s.get("title", "Design appointment to stage 3"),
            "commitment_type": "design",
            "planned_source": "manual",
            "planned_manual_amount": design_s.get("amount", "260000"),
            "currency": ccy,
            "latest_decision_date_fixed": (today + timedelta(days=45)).isoformat(),
        },
        actor_id=author,
    )
    counts["items"] += 1
    brief = await svc.add_precondition(
        project_id,
        design.id,
        kind="manual",
        ref_id=None,
        text=design_s.get("brief_text", "Client brief signed off"),
        actor_id=author,
    )
    await svc.confirm_precondition(
        project_id,
        design.id,
        brief.id,
        met=True,
        evidence_ref=design_s.get("evidence", "Brief rev. C, signed"),
        actor_id=author,
    )
    if planner is not None:
        if await _release(
            svc,
            project_id,
            design.id,
            design_s.get("first_amount", "40000"),
            ccy,
            requester=planner,
            approver=owner,
            note=design_s.get("first_note", "First tranche: concept design"),
            days_ago=12,
            conditions=design_s.get("first_condition", "Stage 2 report before the next tranche"),
        ):
            counts["releases"] += 1
            if await _release(
                svc,
                project_id,
                design.id,
                design_s.get("second_amount", "60000"),
                ccy,
                requester=planner,
                approver=None,
                note=design_s.get("second_note", "Second tranche: developed design"),
                days_ago=2,
            ):
                counts["releases"] += 1

    await svc.create_item(
        project_id,
        {
            "code": "CR-004",
            "title": contingency_s.get("title", "Contingency drawdown for ground conditions"),
            "commitment_type": "contingency_drawdown",
            "planned_source": "manual",
            "planned_manual_amount": contingency_s.get("amount", "75000"),
            "currency": ccy,
        },
        actor_id=author,
    )
    counts["items"] += 1
    await svc.save_scenario(project_id, as_of=today, label=labels.get("scenario", "Stop today"), actor_id=owner)
    counts["scenarios"] += 1
    return counts


# When the stages of that order's cancellation terms begin, in days from the seed day. These are
# this seed's own numbers and they are meant to agree with the plant register's demo seed
# (app/modules/plant_register/seed.py, ``_seed_slot``): ``DEMO_ORDER_SIGNED_DAYS`` is the slot's
# ``convert_by_date`` (the day the free slot lapses without an order) and
# ``DEMO_MANUFACTURING_STARTED_DAYS`` is its ``slot_from``. The register's read port serves no slot,
# so nothing checks the pair: whoever moves one of the two seeds moves the other.
DEMO_ORDER_SIGNED_DAYS = 45
DEMO_MANUFACTURING_STARTED_DAYS = 300

# Which demo item of this module is which demo item of the plant register (by their codes).
DEMO_PLANT_LINKS: dict[str, str] = {DEMO_SLOT_ITEM_CODE: "PL-001"}
# The title a commitment item must carry to be that equipment; a code missing here links on the code alone.
DEMO_PLANT_LINK_TITLES: dict[str, str] = {DEMO_SLOT_ITEM_CODE: DEMO_SLOT_ITEM_TITLE}


async def link_demo_plant_items(
    session: AsyncSession, project_id: uuid.UUID, *, links: dict[str, str] | None = None
) -> dict[str, str]:
    """Point demo commitment items at their demo plant items. The caller commits.

    Called by the integration seed after both seeders ran: neither seeder knows the other's ids.
    The plant item is looked up by its code through the plant register's read port. Answers, per
    commitment item code, ``linked``, ``already_linked``, ``no_commitment_item``, ``not_this_story``
    (the item of that code is another thing in this project's story, so there is nothing to link),
    ``no_plant_item`` or ``plant_register_unavailable``. Nothing is created and no link is overwritten.
    """
    from app.core.demo_marker import demo_id_of
    from app.modules.commitment_release.models import CommitmentItem
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    if project is None or not demo_id_of(project.metadata_):
        return {}
    slot_s = (await _story_of(session, project_id)).get("slot", {})
    wanted = dict(DEMO_PLANT_LINKS if links is None else links)
    if links is None and "plant_item" in slot_s:
        wanted[DEMO_SLOT_ITEM_CODE] = slot_s["plant_item"]
    titles = dict(DEMO_PLANT_LINK_TITLES)
    if "title" in slot_s:
        titles[DEMO_SLOT_ITEM_CODE] = slot_s["title"]
    from app.modules.commitment_release.figures import plant_register_reads

    by_code = getattr(plant_register_reads(), "plant_item_id_by_code", None)
    if by_code is None:
        return dict.fromkeys(wanted, "plant_register_unavailable")
    items = {
        i.code: i
        for i in (await session.execute(select(CommitmentItem).where(CommitmentItem.project_id == project_id)))
        .scalars()
        .all()
    }
    result: dict[str, str] = {}
    for item_code, plant_code in wanted.items():
        item = items.get(item_code)
        if item is None:
            result[item_code] = "no_commitment_item"
            continue
        expected = titles.get(item_code)
        if expected is not None and item.title != expected:
            # A link says the commitment IS that equipment. Here it is not.
            logger.info(
                "commitment_release demo: %s of %s is not the plant item's order, not linked", item_code, project_id
            )
            result[item_code] = "not_this_story"
            continue
        if item.plant_item_id is not None:
            result[item_code] = "already_linked"
            continue
        plant_id = await by_code(session, project_id, plant_code)
        if plant_id is None:
            result[item_code] = "no_plant_item"
            continue
        item.plant_item_id = plant_id
        result[item_code] = "linked"
    await session.flush()
    return result
