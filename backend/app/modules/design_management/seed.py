# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo design management for the demo estate, run by ``app.core.demo_enrichment``.

Each demo project gets what an owner's design manager would set up in the
first weeks: the numbering scheme its country resolves to, a small WBS (only
when the project has none), the design team as roles with originator codes,
approval points and a design schedule along the phases of the project's
pinned governance model (the governance seed runs first and is the only one
that pins; a project without a model is left alone). While the gate into construction is
undecided the seed describes that one moment: the phase the gate closes is done except a single
submitted report, nothing of the next phase has happened. Past that gate it tells a running
project. Drawings are numbered by the generator with
revisions at different suitability, a distribution matrix, the two approval
routes, a release a second person prepared and that waits for the demo user's
approval, a draft release, an internal review with comments, the expert reports the catalogue lists and
a permit package being assembled.

No names of real companies or people: roles are titled by function. Only
projects carrying the demo marker are touched; a project that already has a
design setup is skipped, so a re-run never duplicates.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DESIGN_SPINE = ("concept", "design", "approval", "detail")


_WBS_KINDS = ("location", "system")
_ROLE_KEYS = ("owner", "arch", "struct", "mep", "fire", "checker")
_REPORT_STATUSES = ("required", "commissioned", "in_progress", "submitted", "accepted")
# Where a story report sits: the first or the second design phase of the project (never the phase after the gate).
_REPORT_PHASES = ("early", "mid")


def default_plan() -> dict[str, Any]:
    """The built-in text of the demo: the wording the seed used before stories existed."""
    return {
        "wbs_top": ("1", "Building"),
        "wbs_children": (
            ("1.1", "Substructure", "system"),
            ("1.2", "Superstructure", "system"),
            ("1.3", "Envelope", "system"),
            ("1.4", "Building services", "system"),
        ),
        "wbs_extra": (("2", "External works", "location"),),
        "roles": {
            "owner": ("Owner's design manager", None),
            "arch": ("Lead architect", "ARC"),
            "struct": ("Structural engineer", "STR"),
            "mep": ("Building services engineer", "MEP"),
            "fire": ("Fire safety specialist", "FSE"),
            "checker": ("Independent structural checker", "CHK"),
        },
        "approval_points": {
            "AP-001": "Owner sign-off of the concept",
            "AP-002": "Cost check before the permit application",
            "AP-003": "User sign-off of room layouts",
        },
        "deliverables": {
            "DL-001": "Concept plans and sections",
            "DL-002": "Structural concept",
            "DL-003": "Permit drawings",
            "DL-004": "Building services layouts",
        },
        "drawings": (
            "Ground floor plan",
            "Section A-A",
            "Foundation layout",
            "Site plan for the permit",
            "Elevations for the permit",
            "Ventilation ground floor",
        ),
        "releases": {"REL-001": "Concept issue", "REL-002": "Permit drawings"},
        "review": {
            "title": "End of concept review",
            "comments": (
                "Plant room size does not match the ventilation concept",
                "Stair width to be checked against the escape route",
                "Foundation level differs from the ground report",
            ),
            "answer": "Plant room enlarged to match the ventilation concept.",
        },
        "reports": {},
        "report_status": {},
        "extra_reports": (),
        "permit": {"title": "Building permit application", "form": "Application form"},
        "route_names": {
            "design_approval_point": "Design approval point sign-off",
            "design_release": "Design release sign-off",
        },
        "first_issue": "first issue",
        "execution": None,
    }


def _txt(value: Any, locale: str, limit: int = 255) -> str | None:
    """A non-empty story text in the project's locale, else ``None`` (the default stays)."""
    from app.modules.project_governance.public import story_text

    if not isinstance(value, (str, dict)):
        return None
    text = story_text(value, locale)
    return text.strip()[:limit] if isinstance(text, str) and text.strip() else None


def _titles(default: dict[str, str], value: Any, locale: str) -> dict[str, str]:
    """``default`` with the titles of the story's entries for codes ``default`` already has."""
    out = dict(default)
    if isinstance(value, dict):
        for code in out:
            title = _txt(value.get(code), locale)
            if title:
                out[code] = title
    return out


def _wbs_rows(value: Any, locale: str) -> tuple[tuple[str, str, str], ...] | None:
    """``(code, name, kind)`` rows; ``None`` when the story gives none that are valid."""
    if not isinstance(value, list):
        return None
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        code, name, kind = _txt(item.get("code"), locale, 40), _txt(item.get("name"), locale), item.get("kind")
        if code and name and kind in _WBS_KINDS:
            rows.append((code, name, kind))
    return tuple(rows) or None


def _execution(value: Any, locale: str) -> dict[str, Any] | None:
    """The execution design (LP 5) of a site that runs: one deliverable, its drawings and the release waiting for approval.

    ``None`` unless the story gives codes, a deliverable title, at least one drawing title and a release title.
    """
    if not isinstance(value, dict):
        return None
    code, release = value.get("code"), value.get("release_code")
    title, release_title = _txt(value.get("title"), locale), _txt(value.get("release_title"), locale)
    raw = value.get("drawings")
    drawings = [t for t in (_txt(d, locale) for d in raw) if t] if isinstance(raw, list) else []
    if not (isinstance(code, str) and isinstance(release, str) and title and release_title and drawings):
        return None
    return {"code": code, "title": title, "drawings": drawings, "release_code": release, "release_title": release_title}


def _report_statuses(value: Any) -> dict[str, dict[str, str]]:
    """Where the story leaves a report, per report code: ``before_gate`` and ``after_gate`` (both optional).

    Applies to the five built-in reports and to extra reports. Before the gate the seed still decides which
    reports of the closing phase may be open, so a status the story gives there only stands when it is not
    ``accepted`` for more than one report; an unknown status is ignored.
    """
    out: dict[str, dict[str, str]] = {}
    if not isinstance(value, dict):
        return out
    items: list[tuple[Any, Any]] = []
    if isinstance(value.get("overrides"), dict):
        items += list(value["overrides"].items())
    items += [(i.get("code"), i) for i in value.get("extra") or [] if isinstance(i, dict)]
    for code, item in items:
        if not (isinstance(code, str) and isinstance(item, dict)):
            continue
        picked = {
            key: item[field]
            for key, field in (("before_gate", "status_before_gate"), ("after_gate", "status_after_gate"))
            if item.get(field) in _REPORT_STATUSES
        }
        if picked:
            out[code] = picked
    return out


def _merge_reports(
    value: Any, report_kinds: set[str], locale: str
) -> tuple[dict[str, tuple[str, str]], tuple[dict, ...]]:
    """Overrides of the five built-in reports, and the extra reports of the story.

    A report kind the catalogue does not list is ignored. An extra report is kept only with a code that is not
    already taken, a known kind, an author role, and a phase of the design part of the project.
    """
    overrides: dict[str, tuple[str, str]] = {}
    extras: list[dict] = []
    if not isinstance(value, dict):
        return overrides, ()
    if isinstance(value.get("overrides"), dict):
        for code, item in value["overrides"].items():
            if not (isinstance(item, dict) and code in ("RPT-001", "RPT-002", "RPT-003", "RPT-004", "RPT-005")):
                continue
            kind = item.get("kind") if item.get("kind") in report_kinds else ""
            overrides[code] = (kind, _txt(item.get("title"), locale) or "")
    taken = {"RPT-001", "RPT-002", "RPT-003", "RPT-004", "RPT-005"}
    for item in value.get("extra") if isinstance(value.get("extra"), list) else []:
        if not isinstance(item, dict):
            continue
        code, title = item.get("code"), _txt(item.get("title"), locale)
        author, checker = item.get("author"), item.get("checker")
        if not (
            isinstance(code, str)
            and code not in taken
            and item.get("kind") in report_kinds
            and title
            and author in _ROLE_KEYS
            and item.get("phase") in _REPORT_PHASES
            and (checker is None or checker in _ROLE_KEYS)
        ):
            logger.info("design_management demo story: extra report %r ignored", item.get("code"))
            continue
        taken.add(code)
        status = item.get("status")
        extras.append(
            {
                "code": code,
                "kind": item["kind"],
                "title": title,
                "phase": item["phase"],
                "author": author,
                "checker": checker,
                "status": status if status in _REPORT_STATUSES else "required",
            }
        )
    return overrides, tuple(extras)


def resolve_story(story: dict[str, Any], locale: str, *, report_kinds: set[str]) -> dict[str, Any]:
    """The wording of one project: the built-in text with ``story`` applied key by key.

    Args:
        story: The pack's story object for this module, or ``{}``.
        locale: Locale for ``{"en", "de"}`` texts.
        report_kinds: Report kind codes of the project's reports catalogue.

    Returns:
        The dict ``default_plan`` returns. Structure (phases, statuses of the built-in reports, four-eyes
        steps) stays in the seed; the story supplies names, titles and texts, and extra reports.
    """
    plan = default_plan()
    if not story:
        return plan
    wbs = story.get("wbs")
    if isinstance(wbs, dict):
        top = wbs.get("top")
        code, name = (
            (_txt(top.get("code"), locale, 40), _txt(top.get("name"), locale))
            if isinstance(top, dict)
            else (None, None)
        )
        children = _wbs_rows(wbs.get("children"), locale)
        # The children are numbered under the top node: a story that names one must name a matching set.
        if code and name and children and all(c[0].startswith(f"{code}.") for c in children):
            plan["wbs_top"], plan["wbs_children"] = (code, name), children
        extra = _wbs_rows(wbs.get("extra"), locale)
        if extra is not None:
            plan["wbs_extra"] = extra
    roles = story.get("roles")
    if isinstance(roles, dict):
        merged = {}
        for key, (title, orig) in plan["roles"].items():
            item = roles.get(key)
            item = item if isinstance(item, dict) else {}
            code = item.get("originator")
            merged[key] = (
                _txt(item.get("title"), locale) or title,
                code if orig is not None and isinstance(code, str) and re.fullmatch(r"[A-Z]{2,4}", code) else orig,
            )
        plan["roles"] = merged
    plan["approval_points"] = _titles(plan["approval_points"], story.get("approval_points"), locale)
    plan["deliverables"] = _titles(plan["deliverables"], story.get("deliverables"), locale)
    plan["releases"] = _titles(plan["releases"], story.get("releases"), locale)
    drawings = story.get("drawings")
    if isinstance(drawings, list) and len(drawings) == len(plan["drawings"]):
        titles = [_txt(d, locale) for d in drawings]
        if all(titles):
            plan["drawings"] = tuple(titles)
    review = story.get("review")
    if isinstance(review, dict):
        given = review.get("comments") if isinstance(review.get("comments"), list) else []
        plan["review"] = {
            "title": _txt(review.get("title"), locale) or plan["review"]["title"],
            "comments": tuple(
                (_txt(given[i], locale, 1000) if i < len(given) else None) or default
                for i, default in enumerate(plan["review"]["comments"])
            ),
            "answer": _txt(review.get("answer"), locale, 1000) or plan["review"]["answer"],
        }
    plan["reports"], plan["extra_reports"] = _merge_reports(story.get("reports"), report_kinds, locale)
    plan["report_status"] = _report_statuses(story.get("reports"))
    plan["route_names"] = _titles(plan["route_names"], story.get("route_names"), locale)
    plan["first_issue"] = _txt(story.get("first_issue"), locale) or plan["first_issue"]
    plan["execution"] = _execution(story.get("execution"), locale)
    permit = story.get("permit")
    if isinstance(permit, dict):
        plan["permit"] = {
            "title": _txt(permit.get("title"), locale) or plan["permit"]["title"],
            "form": _txt(permit.get("form"), locale) or plan["permit"]["form"],
        }
    return plan


async def seed_design_management_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seed every demo project in ``project_ids`` that has no design setup. The caller commits."""
    from app.core.demo_marker import demo_id_of
    from app.modules.design_management.models import DesignSetup
    from app.modules.project_governance.public import project_catalogue
    from app.modules.projects.models import Project

    totals = {"projects": 0, "drawings": 0, "deliverables": 0, "reports": 0, "one_person_stories": 0}
    ids = list(project_ids)
    if not ids:
        return totals
    rows = (await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(ids)))).all()
    for pid in [pid for pid, meta in rows if demo_id_of(meta)]:
        has = (await session.execute(select(DesignSetup.id).where(DesignSetup.project_id == pid))).scalar_one_or_none()
        if has is not None:
            continue
        if await project_catalogue(session, pid) is None:
            # Design phases are the phases of the pinned model; without one there is nothing to schedule along.
            logger.info("design_management demo seed: project %s has no phase model, left alone", pid)
            continue
        # No blanket except: a seed that cannot finish is a defect to see, not a project to skip
        # quietly. The savepoint keeps a half-seeded project out; the caller logs and reports.
        async with session.begin_nested():
            counts = await _seed_project(session, pid)
        totals["projects"] += 1
        for k, v in counts.items():
            totals[k] += v
    return totals


async def align_demo_wbs_with_references(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Give the budget lines and schedule rows of a demo project the WBS nodes they point at.

    The demo budgets are keyed on the cost-plan group of the bill and the schedule
    rows on their outline or milestone code, while the design WBS is seeded from the
    pack story alone, so each of those values pointed at nothing and the rule
    ``wbs_reference_resolves`` warned once per row. This runs after the seeders that
    write those rows and adds the missing node, named after the row that carries the
    value. Only demo projects with a design setup are touched, only finance and
    schedule references are adopted, and a value that already resolves is left alone.
    The caller commits.
    """
    from sqlalchemy import text

    from app.core.demo_marker import demo_id_of
    from app.modules.design_management import wbs_refs
    from app.modules.design_management.models import DesignSetup
    from app.modules.design_management.service import DesignService
    from app.modules.projects.models import Project

    totals = {"projects": 0, "nodes": 0}
    ids = list(project_ids)
    if not ids:
        return totals
    names_sql = {
        "finance": "SELECT wbs_id, category FROM oe_finance_budget WHERE project_id = :pid AND wbs_id IS NOT NULL",
        "schedule": (
            "SELECT a.wbs_code, a.name FROM oe_schedule_activity a "
            "JOIN oe_schedule_schedule s ON s.id = a.schedule_id WHERE s.project_id = :pid"
        ),
    }
    rows = (await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(ids)))).all()
    for pid in [pid for pid, meta in rows if demo_id_of(meta)]:
        setup = (await session.execute(select(DesignSetup).where(DesignSetup.project_id == pid))).scalar_one_or_none()
        if setup is None:
            continue
        owner = (await session.get(Project, pid)).owner_id
        svc = DesignService(session)
        nodes = await svc.wbs_rows(pid)
        missing: dict[str, str] = {}
        for ref in await wbs_refs.unresolved_references(session, pid, nodes):
            if ref.module in names_sql and ref.value not in missing:
                missing[ref.value] = ""
        if not missing:
            continue
        for sql in names_sql.values():
            for value, name in (await session.execute(text(sql), {"pid": str(pid)})).all():
                key = str(value or "").strip()
                if key in missing and not missing[key] and name:
                    missing[key] = str(name).strip()
        created = 0
        for value in sorted(missing, key=lambda v: (len(v), v)):
            codes = {n.code: n for n in await svc.wbs_rows(pid)}
            parent = max(
                (c for c in codes if value.startswith(c + (setup.wbs_separator or "."))), key=len, default=None
            )
            data: dict[str, Any] = {"code": value, "name": missing[value] or value, "kind": "system"}
            if parent is not None:
                data["parent_id"] = str(codes[parent].id)
            await svc.create_wbs(pid, data, actor_id=owner)
            created += 1
        totals["projects"] += 1
        totals["nodes"] += created
    return totals


async def _pre_construction(session: AsyncSession, project_id: uuid.UUID) -> tuple[str, str] | None:
    """``(phase the gate closes, phase it opens)`` while the gate into construction is undecided, else ``None``.

    Read from the project's own state through module 1's port: the gate whose
    target phase enables the start of construction exists and carries no
    decision. Never from a catalogue id, a name or the source of the pin.
    """
    from app.modules.project_governance.public import phases_enabling, project_gates

    enabling = set(await phases_enabling(session, project_id, "construction_start"))
    gate = next((g for g in await project_gates(session, project_id) if g.to_phase in enabling), None)
    if gate is None or gate.status == "decided":
        return None
    return gate.from_phase, gate.to_phase


async def _construction_released(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """Whether the gate into construction exists and is decided: the design phases are closed and the site runs."""
    from app.modules.project_governance.public import phases_enabling, project_gates

    enabling = set(await phases_enabling(session, project_id, "construction_start"))
    gate = next((g for g in await project_gates(session, project_id) if g.to_phase in enabling), None)
    return gate is not None and gate.status == "decided"


# A running site: the concept (LP 2) went out before the preliminary enquiry and the permit set
# shortly before the building application (the permits seed files them 330 and 190 days back).
_RUNNING_ISSUED_DAYS_AGO = {"REL-001": 340, "REL-002": 195}
# Days after the issue on which every recipient of a release transmittal confirmed receipt.
_ACK_AFTER_DAYS = 2


async def _date_issue(session: AsyncSession, release_id: uuid.UUID, days_ago: int) -> None:
    """Move an issued release and its transmittals to the day the story issued them, receipts included.

    ``issue_release`` stamps the moment of the call, so a seeded register would show every
    release of a project's history as sent on the install day under one subject.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.modules.design_management.models import DesignRelease
    from app.modules.transmittals.models import Transmittal, TransmittalRecipient

    release = await session.get(DesignRelease, release_id)
    if release is None or release.status != "issued":
        return
    now = datetime.now(UTC)
    issued_at = (now - timedelta(days=days_ago)).replace(hour=9, minute=0, second=0, microsecond=0)
    release.issued_at = issued_at
    ids = [uuid.UUID(str(t)) for t in release.transmittal_ids or []]
    if ids:
        await session.execute(
            update(Transmittal).where(Transmittal.id.in_(ids)).values(issued_date=issued_at.date().isoformat())
        )
        await session.execute(
            update(TransmittalRecipient)
            .where(TransmittalRecipient.transmittal_id.in_(ids))
            .values(acknowledged_at=min(issued_at + timedelta(days=_ACK_AFTER_DAYS, hours=1), now))
        )
    await session.flush()


async def _approve(session: AsyncSession, instance_id: uuid.UUID, approver: uuid.UUID) -> None:
    """Decide an approval instance through approval_routes, the way its own screen does."""
    from app.modules.approval_routes.models import Instance, Step
    from app.modules.approval_routes.schemas import DecisionSubmit
    from app.modules.approval_routes.service import ApprovalRouteService

    instance = await session.get(Instance, instance_id)
    step = (
        await session.execute(
            select(Step).where(Step.route_id == instance.route_id, Step.ordinal == instance.current_step_ordinal)
        )
    ).scalar_one()
    await ApprovalRouteService(session).submit_decision(
        instance_id, DecisionSubmit(step_id=step.id, decision="approved"), approver_id=approver
    )


def _example(scheme: Any, field: str, meaning: str) -> str | None:
    """The scheme's own illustrative value of a field; ``None`` when the scheme has no such field."""
    return scheme.examples.get(field, {}).get(meaning) if scheme.field(field) is not None else None


def _phase_value(scheme: Any, phase_code: str) -> str | None:
    """The scheme's code for a governance phase: the listed code of the same name, else its example."""
    field = scheme.field("phase")
    if field is None:
        return None
    by_name = {c.casefold(): c for c in field.codes() or ()}
    return by_name.get((phase_code or "").casefold()) or _example(scheme, "phase", "default")


async def _second_person(session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID | None:
    """The demo cast's second person of a four-eyes step, when the installation has one.

    Only the cast: any other account of the installation is somebody's real one, possibly another
    tenant's, and has no business on a seeded row.
    """
    from app.core.demo_cast import find_cast

    cost = (await find_cast(session)).get("cost")
    return cost if cost is not None and cost != owner_id else None


async def _routes(
    session: AsyncSession, project_id: uuid.UUID, owner: uuid.UUID, second: uuid.UUID, names: dict[str, str]
) -> None:
    """One approval route per design target kind, each decided by the person who did not prepare."""
    from app.modules.approval_routes.schemas import RouteCreate, StepCreate
    from app.modules.approval_routes.service import ApprovalRouteService

    for kind, name, approver in (
        # The demo user submits approval points, so the second person decides them.
        ("design_approval_point", names["design_approval_point"], second),
        # The second person prepares the release, so the demo user approves and issues it.
        ("design_release", names["design_release"], owner),
    ):
        await ApprovalRouteService(session).create_route(
            RouteCreate(
                project_id=project_id,
                name=name,
                target_kind=kind,
                steps=[StepCreate(ordinal=1, approver_user_id=approver, mode="any")],
            ),
            created_by=owner,
        )


async def _seed_project(session: AsyncSession, project_id: uuid.UUID) -> dict[str, int]:
    from app.core.demo_marker import demo_id_of
    from app.modules.cde.models import DocumentContainer
    from app.modules.cde.schemas import RevisionCreate
    from app.modules.cde.service import CDEService
    from app.modules.design_management.service import DesignService
    from app.modules.project_governance.public import demo_module_story
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    actor = project.owner_id
    svc = DesignService(session)
    setup = await svc.set_setup(project_id, actor_id=actor, tenant_id=None)
    scheme = await svc.scheme(setup)
    reports_cat = await svc.reports_catalogue(setup)
    plan = resolve_story(
        demo_module_story(demo_id_of(project.metadata_), "design_management"),
        getattr(project, "locale", None) or "en",
        report_kinds={k.code for k in reports_cat.report_kinds},
    )
    phases = await svc.phases(project_id)
    design_phases = [p for p in phases if p["spine_key"] in _DESIGN_SPINE] or phases
    p_early = design_phases[0]["code"]
    p_mid = design_phases[min(1, len(design_phases) - 1)]["code"]
    p_late = design_phases[-1]["code"]
    # Before construction is released the story is one moment: everything of the phase the gate
    # closes is done except a single report, and nothing of the phase it opens has happened.
    pre = await _pre_construction(session, project_id)
    # A decided gate is the other half of the same story: the design of the closing phase is issued and accepted,
    # and only the execution design is still under way.
    running = pre is None and await _construction_released(session, project_id)
    if pre is not None:
        p_mid, p_late = pre
        closes = next((p["order"] for p in phases if p["code"] == p_mid), None)
        earlier = [p for p in design_phases if closes is not None and p["order"] <= closes]
        p_early = earlier[0]["code"] if earlier else p_mid

    # WBS: only when the project has none (never touch a WBS someone built).
    wbs = await svc.wbs_rows(project_id)
    if not wbs:
        top_code, top_name = plan["wbs_top"]
        top = await svc.create_wbs(project_id, {"code": top_code, "name": top_name, "kind": "location"}, actor_id=actor)
        for code, name, kind in plan["wbs_children"]:
            await svc.create_wbs(
                project_id, {"code": code, "name": name, "kind": kind, "parent_id": top.id}, actor_id=actor
            )
        for code, name, kind in plan["wbs_extra"]:
            await svc.create_wbs(project_id, {"code": code, "name": name, "kind": kind}, actor_id=actor)
        wbs = await svc.wbs_rows(project_id)
    wbs_leaf = next((w for w in wbs if not (w.metadata_ or {}).get("closed")), None)

    disc = {
        "arch": _example(scheme, "discipline", "architecture"),
        "struct": _example(scheme, "discipline", "structure"),
        "mep": _example(scheme, "discipline", "building_services"),
    }
    roles = {}
    for key, kind in (
        ("owner", "owner"),
        ("arch", "discipline_designer"),
        ("struct", "discipline_designer"),
        ("mep", "discipline_designer"),
        ("fire", "specialist"),
        ("checker", "checker"),
    ):
        title, orig = plan["roles"][key]
        roles[key] = await svc.create_role(
            project_id,
            {
                "code": key.upper(),
                "title": title,
                "party_kind": kind,
                "discipline_code": disc.get(key),
                "originator_code": orig,
                "user_id": actor if key == "owner" else None,
            },
            actor_id=actor,
        )
        roles[key].status = "active"
    setup.lead_designer_role_id = roles["arch"].id

    for code, phase, kind in (
        ("AP-001", p_early, "owner_approval"),
        ("AP-002", p_mid, "cost_check"),
        ("AP-003", p_mid, "user_signoff"),
    ):
        title = plan["approval_points"][code]
        await svc.create_approval_point(
            project_id,
            {"code": code, "title": title, "phase_code": phase, "kind": kind, "approver_role_id": roles["owner"].id},
            actor_id=actor,
        )

    deliverables = {}
    for code, phase, role, count in (
        ("DL-001", p_early, "arch", 2),
        ("DL-002", p_early, "struct", 1),
        ("DL-003", p_mid, "arch", 2 if (pre or running) else 3),
        ("DL-004", p_late, "mep", 2),
    ):
        title = plan["deliverables"][code]
        deliverables[code] = await svc.create_deliverable(
            project_id,
            {
                "code": code,
                "title": title,
                "phase_code": phase,
                "role_id": roles[role].id,
                "discipline_code": disc[role],
                "planned_count": count,
                "wbs_node_id": wbs_leaf.id if wbs_leaf else None,
            },
            actor_id=actor,
        )

    execution = plan["execution"] if running else None
    if execution is not None:
        deliverables[execution["code"]] = await svc.create_deliverable(
            project_id,
            {
                "code": execution["code"],
                "title": execution["title"],
                "phase_code": p_late,
                "role_id": roles["struct"].id,
                "discipline_code": disc["struct"],
                "planned_count": len(execution["drawings"]),
                "wbs_node_id": wbs_leaf.id if wbs_leaf else None,
            },
            actor_id=actor,
        )

    cde = CDEService(session)
    drawing_rows = []
    # Before construction: the drawings of the closing phase are published, so their schedule lines
    # are accepted; the one drawing of the next phase is work in progress and counts for no line yet.
    done = "A4" if (pre or running) else None
    execution_specs = (
        tuple(("struct", execution["code"], p_late, "plan", "basement", "plan", "S2") for _ in execution["drawings"])
        if execution is not None
        else ()
    )
    for title, (role, dl, phase, form, spatial, sheet_type, suit) in zip(
        [*plan["drawings"], *(execution["drawings"] if execution is not None else [])],
        (
            ("arch", "DL-001", p_early, "plan", "ground", "plan", done or "S3"),
            ("arch", "DL-001", p_early, "section", "whole", "section", done or "S4"),
            ("struct", "DL-002", p_early, "plan", "basement", "plan", done or "S2"),
            ("arch", "DL-003", p_mid, "site_plan", "whole", "general", "A4"),
            ("arch", "DL-003", p_mid, "elevation", "whole", "elevation", done or "S0"),
            ("mep", None if pre else "DL-004", p_late, "plan", "ground", "plan", "S0"),
            *execution_specs,
        ),
        strict=True,
    ):
        project_code = re.sub(r"[^A-Z0-9]", "", (project.project_code or "").upper())[:6]
        values = {
            "project": project_code if len(project_code) >= 2 else "DEMO",
            "functional": _example(scheme, "functional", "whole"),
            "spatial": _example(scheme, "spatial", spatial),
            "form": _example(scheme, "form", form),
            "custom_sheet_type": _example(scheme, "custom_sheet_type", sheet_type),
            "phase": _phase_value(scheme, phase),
        }
        fields = {k: v for k, v in values.items() if v is not None}
        drawing, container = await svc.create_drawing(
            project_id,
            {
                "title": title,
                "role_id": roles[role].id,
                "deliverable_id": deliverables[dl].id if dl else None,
                "phase_code": phase,
                "fields": fields,
                "scale": "1:100",
                "sheet_size": "A1",
                "wbs_node_id": wbs_leaf.id if wbs_leaf else None,
            },
            actor_id=actor,
        )
        rev = await cde.create_revision(
            container.id,
            RevisionCreate(file_name=f"{container.container_code}.pdf", change_summary=plan["first_issue"]),
            user_id=str(actor),
        )
        c = await session.get(DocumentContainer, container.id)
        c.current_revision_id = rev.id
        c.suitability_code = suit
        c.cde_state = "published" if suit.startswith("A") else ("wip" if suit == "S0" else "shared")
        drawing_rows.append((drawing, c, rev))
    await session.flush()
    for d in deliverables.values():
        await svc.refresh_deliverable(d)

    await svc.create_dist_rule(
        project_id,
        {"recipient_role_id": roles["owner"].id, "min_suitability": "S2"},
        actor_id=actor,
    )
    await svc.create_dist_rule(
        project_id,
        {"recipient_role_id": roles["struct"].id, "discipline_codes": [disc["arch"]]},
        actor_id=actor,
    )
    await svc.create_dist_rule(
        project_id,
        {"recipient_role_id": roles["mep"].id, "discipline_codes": [disc["arch"], disc["struct"]], "format": "native"},
        actor_id=actor,
    )
    n_base = len(plan["drawings"])
    shared = [r.id for _d, c, r in drawing_rows[:n_base] if c.cde_state != "wip"]
    execution_revisions = [r.id for _d, c, r in drawing_rows[n_base:] if c.cde_state != "wip"]
    second = await _second_person(session, actor)
    if second is not None:
        # Prepared and marked ready by the second person: the demo user approves it and issues it.
        await _routes(session, project_id, actor, second, plan["route_names"])
        concept = await svc.create_release(
            project_id,
            {"code": "REL-001", "title": plan["releases"]["REL-001"], "revision_ids": shared[:3]},
            actor_id=second,
        )
        concept = await svc.release_transition(project_id, concept.id, "ready", actor_id=second)
    else:
        # Nobody plays the second part here: four-eyes off, so the release can still be issued.
        logger.info("design_management demo seed: project %s has no second person, one-person story", project_id)
        setup.four_eyes_release = False
        concept = await svc.create_release(
            project_id,
            {"code": "REL-001", "title": plan["releases"]["REL-001"], "revision_ids": shared[:3]},
            actor_id=actor,
        )
        concept = await svc.release_transition(project_id, concept.id, "ready", actor_id=actor)
    if running:
        # On a running site the concept was approved and issued long before the permit: only the
        # execution design below still waits. It goes out first, so the register numbers run in story order.
        if concept.approval_instance_id is not None:
            await _approve(session, concept.approval_instance_id, actor)
            await svc.catch_up_approvals(project_id)
        await svc.issue_release(project_id, concept.id, actor_id=actor)
    preparer = (second or actor) if (pre or running) else actor
    permit_set = await svc.create_release(
        project_id,
        {"code": "REL-002", "title": plan["releases"]["REL-002"], "revision_ids": shared[3:]},
        actor_id=preparer,
    )
    if pre is not None or running:
        # Released before the gate: prepared by one person, approved on the route and issued by the other.
        ready = await svc.release_transition(project_id, permit_set.id, "ready", actor_id=preparer)
        if ready.approval_instance_id is not None:
            await _approve(session, ready.approval_instance_id, actor)
            await svc.catch_up_approvals(project_id)
        await svc.issue_release(project_id, permit_set.id, actor_id=actor)
    if running:
        # Each issue is dated where the story puts it, not on the install day.
        await _date_issue(session, concept.id, _RUNNING_ISSUED_DAYS_AGO["REL-001"])
        await _date_issue(session, permit_set.id, _RUNNING_ISSUED_DAYS_AGO["REL-002"])

    if execution is not None and execution_revisions and second is not None:
        # The execution design waits for its approval: the release is ready and nobody has signed it yet.
        waiting = await svc.create_release(
            project_id,
            {
                "code": execution["release_code"],
                "title": execution["release_title"],
                "revision_ids": execution_revisions,
            },
            actor_id=second,
        )
        await svc.release_transition(project_id, waiting.id, "ready", actor_id=second)

    review = await svc.create_review(
        project_id,
        {
            "code": "REV-001",
            "title": plan["review"]["title"],
            "phase_code": p_early,
            "deliverable_ids": [deliverables["DL-001"].id, deliverables["DL-002"].id],
            "reviewer_role_ids": [roles["owner"].id, roles["mep"].id],
        },
        actor_id=actor,
    )
    for text, severity, idx in zip(plan["review"]["comments"], ("major", "minor", "minor"), range(3), strict=True):
        comment = await svc.add_comment(
            project_id,
            review.id,
            {"text": text, "severity": severity, "revision_id": drawing_rows[idx][2].id},
            actor_id=actor,
        )
        if (pre is not None or running) and severity != "minor":
            # An open major comment blocks the phase; before the gate it has been answered and closed.
            await svc.comment_transition(
                project_id,
                comment.id,
                "answered",
                actor_id=actor,
                answer=plan["review"]["answer"],
                role_id=roles["arch"].id,
            )
            await svc.comment_transition(project_id, comment.id, "closed", actor_id=actor)

    count_reports = 0
    if pre is not None:
        # Exactly one report of the closing phase is not accepted yet, and it stands one step before it.
        report_plan = (
            ("RPT-001", "geotechnical", p_early, "accepted", "struct", None),
            ("RPT-002", "fire_safety_concept", p_mid, "accepted", "fire", None),
            ("RPT-003", "structural_design", p_mid, "accepted", "struct", None),
            ("RPT-004", "structural_proof_check", p_late, "required", "struct", "checker"),
            ("RPT-005", "thermal_energy", p_mid, "submitted", "mep", None),
        )
    else:
        report_plan = (
            ("RPT-001", "geotechnical", p_early, "accepted", "struct", None),
            ("RPT-002", "fire_safety_concept", p_mid, "in_progress", "fire", None),
            ("RPT-003", "structural_design", p_mid, "commissioned", "struct", None),
            ("RPT-004", "structural_proof_check", p_mid, "required", "struct", "checker"),
            ("RPT-005", "thermal_energy", p_mid, "required", "mep", None),
        )
    extras = [
        (
            e["code"],
            e["kind"],
            {"early": p_early, "mid": p_mid}[e["phase"]],
            # Before the gate everything of the closing phase is done except the one report above.
            e["status"] if pre is None else "accepted",
            e["author"],
            e["checker"],
        )
        for e in plan["extra_reports"]
    ]
    titles = {e["code"]: e["title"] for e in plan["extra_reports"]}
    stated = plan.get("report_status") or {}
    for code, kind, phase, status, author, checker in [*report_plan, *extras]:
        status = stated.get(code, {}).get("before_gate" if pre is not None else "after_gate", status)
        kind_override, title_override = plan["reports"].get(code, ("", ""))
        kind = kind_override or kind
        report = await svc.create_report(
            project_id,
            {
                "code": code,
                "kind_code": kind,
                "title": titles.get(code) or title_override or kind.replace("_", " ").capitalize(),
                "phase_code": phase,
                "author_role_id": roles[author].id,
                "checker_role_id": roles[checker].id if checker else None,
                "from_catalogue": True,
            },
            actor_id=actor,
        )
        for step in {
            "accepted": ("commissioned", "in_progress", "submitted", "accepted"),
            "submitted": ("commissioned", "in_progress", "submitted"),
            "in_progress": ("commissioned", "in_progress"),
            "commissioned": ("commissioned",),
        }.get(status, ()):
            await svc.report_transition(project_id, report.id, step, actor_id=actor)
        count_reports += 1

    country = (project.country_code or "").upper()
    profile = next((p.code for p in reports_cat.permit_steps if country in p.jurisdiction_countries), "neutral")
    permit = await svc.create_permit(
        project_id, {"code": "PP-001", "title": plan["permit"]["title"], "profile_code": profile}, actor_id=actor
    )
    for drawing, c, _rev in drawing_rows[3:5]:
        await svc.add_permit_item(
            project_id, permit.id, {"kind": "drawing", "title": drawing.title, "container_id": c.id}, actor_id=actor
        )
    await svc.add_permit_item(project_id, permit.id, {"kind": "form", "title": plan["permit"]["form"]}, actor_id=actor)
    await session.flush()
    return {
        "drawings": len(drawing_rows),
        "deliverables": len(deliverables),
        "reports": count_reports,
        "one_person_stories": 0 if second is not None else 1,
    }
