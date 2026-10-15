# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo quality concept for the demo estate.

Each demo project gets a draft concept on the neutral catalogue with every
register filled: applied standards and requirements, certification targets with
credits, the proof plan of two packages with evidence linked from records the
other seeders wrote, the catalogue commissioning stages with owners and a
system walked part of the way, acceptance units, expert reports and the
before-and-after survey of a neighbouring building.

Everything goes through the service, so the demo obeys the same rules as user
input: a stage is released by its hold gate, evidence is accepted by someone
other than the person who linked it, and where the estate has only one account
those steps are left open rather than faked.

The staged commissioning model is applied to the systems whose commissioning
has not finished its tests. A system the commissioning demo already shows as
tested or commissioned keeps working exactly as before.

A project is skipped when it is not a demo project or already has a concept,
so a customer's live project is never written to and a re-run adds nothing.
Dates are counted back from the day the seed runs: recorded facts lie in the
past, planned ones in the future.

A project whose gate into the phase that starts construction exists and is not
decided yet tells the story before construction: the same plan as a draft,
nothing delivered, nothing tested, every survey and expert report still ahead.
The project is recognised by that state, read through the governance port,
never by a catalogue, a name or a code.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality_concept import schemas as s
from app.modules.quality_concept import vocab
from app.modules.quality_concept.models import QualityConcept

logger = logging.getLogger(__name__)

_REGIME = "fidic_taking_over"
# Before construction the demo is told under the German standard form of the catalogue.
_REGIME_BEFORE_CONSTRUCTION = "de_vob_b"
# Days from the seed day to the start of construction in the story before construction.
_START = 190
# Due dates of the expert reports in that story, all after the start.
_REPORTS_AFTER_START = ((_START + 30,), (_START + 110, _START + 170), (_START + 290, _START + 330))
# Lifecycle states of a commissioning system whose tests are still open.
_OPEN_LIFECYCLES = ("not_started", "in_progress")
_PACKAGES = (
    ("PKG-STR", "Structure and envelope"),
    ("PKG-MEP", "Building services"),
)
_STANDARDS = (
    ("EN 206", "Concrete: specification, performance, production and conformity", "concrete", "structure", 0),
    ("EN 1090-2", "Execution of steel structures", "steel", "structure", 0),
    ("EN 12599", "Ventilation for buildings: test procedures for handing over", None, "mep", 1),
)
_REQUIREMENTS = (
    ("quality.material", "Structural concrete", "strength class", "C30/37", "", "Structural specification 3.2"),
    ("quality.availability", "Cooling plant", "availability", "99.5", "%", "Employer's requirements 7.1"),
    ("quality.acoustics", "Office floors", "airborne sound insulation", "52", "dB", "Employer's requirements 5.4"),
    ("quality.fm_data", "Maintainable assets", "asset data set", "complete at handover", "", "Information needs 2.3"),
)
_EXPERT_REPORTS = (
    ("Independent check of the structural analysis", "before_concreting", "once", (-240,), "completed"),
    (
        "Fire protection inspection of the services",
        "before_concealment",
        "per_floor",
        (-20, 25),
        "reporting",
    ),
    ("Acoustic measurement of the finished floors", "after_installation", "per_floor", (60, 110), "planned"),
)
_TOTALS = (
    "projects",
    "standards",
    "requirements",
    "certifications",
    "credits",
    "stages",
    "stage_rows",
    "units",
    "proofs",
    "links",
    "expert_reports",
    "surveys",
)


_REPORT_STATES = ("planned", "commissioned", "reporting", "completed", "cancelled")


def _text(value: Any, locale: str, *, limit: int = 500) -> str | None:
    """A non-empty story text in the project's locale, else ``None`` (the default stays)."""
    from app.modules.project_governance.public import story_text

    if not isinstance(value, (str, dict)):
        return None
    text = story_text(value, locale)
    return text.strip()[:limit] if isinstance(text, str) and text.strip() else None


def _days(value: Any, low: int = -720, high: int = 1500) -> int | None:
    """An integer day offset within ``[low, high]``; ``None`` for anything else (bool included)."""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        return None
    return value


def _offsets(value: Any) -> tuple[int, ...] | None:
    """A non-empty list of day offsets, or ``None``."""
    if not isinstance(value, list) or not value:
        return None
    days = [_days(v) for v in value]
    return None if any(d is None for d in days) else tuple(d for d in days if d is not None)


_WAIVER_REASON = "Covered by the manufacturer's system warranty; a separate certificate is not issued for this package."


def default_plan() -> dict[str, Any]:
    """The built-in story as one dict: the constants above, in the shape ``resolve_story`` returns."""
    return {
        "start": _START,
        "regime": _REGIME,
        "regime_before": _REGIME_BEFORE_CONSTRUCTION,
        "packages": _PACKAGES,
        "standards": tuple((*row, "contract") for row in _STANDARDS),
        "requirements": _REQUIREMENTS,
        "expert_reports": tuple(
            (*row, _REPORTS_AFTER_START[i % len(_REPORTS_AFTER_START)]) for i, row in enumerate(_EXPERT_REPORTS)
        ),
        "units": (
            ("AU-01", "Structure, building section A", "partial_section", 45, (0,), "A"),
            ("AU-02", "Building services", "partial_package", 120, (1,), ""),
            ("AU-03", "Whole works", "total", 150, (), ""),
            ("AU-04", "Handover to operation", "handover_to_operation", 165, (), ""),
        ),
        "neighbour": {
            "ref": "NB-01",
            "address": "Adjacent building, north boundary",
            "triggers": ["excavation"],
            "methods": ["photo", "crack_mapping"],
        },
        "road": {"ref": "RD-01", "address": "Access road, east side", "triggers": ["excavation"], "methods": ["photo"]},
        "waiver_reason": _WAIVER_REASON,
        "stage_names": {},
    }


def _merge_standards(value: Any, families: set[str], locale: str) -> tuple[tuple, ...] | None:
    """Standard rows ``(code, title, family, discipline, package index, mandate)``; ``None`` keeps the default."""
    if not isinstance(value, list):
        return None
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        code = _text(item.get("code"), locale, limit=120)
        title = _text(item.get("title"), locale)
        family, package = item.get("family"), item.get("package", 0)
        mandate = item.get("mandate", "contract")
        if not code or not title or package not in (0, 1) or isinstance(package, bool):
            logger.info("quality_concept demo story: standard %r ignored", item.get("code"))
            continue
        if family is not None and family not in families:
            family = None
        discipline = _text(item.get("discipline"), locale, limit=40) or ""
        rows.append(
            (code, title, family, discipline, package, mandate if mandate in vocab.STANDARD_MANDATE else "contract")
        )
    return tuple(rows) or None


def _merge_requirements(value: Any, categories: set[str], locale: str) -> tuple[tuple, ...] | None:
    """Requirement rows ``(category, entity, attribute, value, unit, source)``; ``None`` keeps the default."""
    if not isinstance(value, list):
        return None
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        entity, attribute = (
            _text(item.get("entity"), locale, limit=255),
            _text(item.get("attribute"), locale, limit=255),
        )
        if not (isinstance(category, str) and category in categories and entity and attribute):
            logger.info("quality_concept demo story: requirement %r ignored", item.get("category"))
            continue
        rows.append(
            (
                category,
                entity,
                attribute,
                _text(item.get("value"), locale) or "",
                _text(item.get("unit"), locale, limit=50) or "",
                _text(item.get("source"), locale) or "",
            )
        )
    return tuple(rows) or None


def _merge_reports(value: Any, start: int, locale: str) -> tuple[tuple, ...] | None:
    """Expert report rows ``(subject, trigger, frequency, offsets, state, planned offsets)``.

    ``planned_offsets`` is where the report falls due in the story before construction; without it the report
    follows the start by 30 days plus 40 per row.
    """
    if not isinstance(value, list):
        return None
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        subject = _text(item.get("subject"), locale)
        offsets = _offsets(item.get("offsets"))
        if not subject or offsets is None:
            logger.info("quality_concept demo story: expert report %r ignored", item.get("subject"))
            continue
        trigger, frequency, state = item.get("trigger", ""), item.get("frequency", ""), item.get("state", "planned")
        planned = _offsets(item.get("planned_offsets")) or (start + 30 + 40 * len(rows),)
        rows.append(
            (
                subject,
                trigger if trigger in ("", *vocab.EXPERT_REPORT_TRIGGERS) else "",
                frequency if frequency in ("", *vocab.EXPERT_REPORT_FREQUENCIES) else "",
                offsets,
                state if state in _REPORT_STATES else "planned",
                planned,
            )
        )
    return tuple(rows) or None


def _merge_units(value: Any, locale: str) -> tuple[tuple, ...] | None:
    """Acceptance unit rows ``(code, title, kind, days, package indexes, section)``; ``None`` keeps the default."""
    if not isinstance(value, list):
        return None
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        code, title = _text(item.get("code"), locale, limit=40), _text(item.get("title"), locale)
        kind, days, packages = item.get("kind"), _days(item.get("days"), 0, 1500), item.get("packages", [])
        if not (code and title and kind in vocab.ACCEPTANCE_KINDS and days is not None):
            logger.info("quality_concept demo story: acceptance unit %r ignored", item.get("code"))
            continue
        indexes = (
            tuple(i for i in packages if i in (0, 1) and not isinstance(i, bool)) if isinstance(packages, list) else ()
        )
        section = _text(item.get("section"), locale, limit=255) or ("A" if kind == "partial_section" else "")
        rows.append((code, title, kind, days, indexes, section))
    return tuple(rows) or None


def _merge_subject(default: dict[str, Any], value: Any, locale: str) -> dict[str, Any]:
    """A survey subject (reference, address, influence triggers, methods) with the story on top."""
    out = dict(default)
    if not isinstance(value, dict):
        return out
    ref, address = _text(value.get("ref"), locale, limit=64), _text(value.get("address"), locale)
    if ref:
        out["ref"] = ref
    if address:
        out["address"] = address
    triggers, methods = value.get("triggers"), value.get("methods")
    if isinstance(triggers, list) and triggers and all(t in vocab.INFLUENCE_TRIGGERS for t in triggers):
        out["triggers"] = list(triggers)
    if isinstance(methods, list) and methods and all(m in vocab.SURVEY_METHODS for m in methods):
        out["methods"] = list(methods)
    return out


def _merge_stage_names(raw: Any, locale: str) -> dict[str, str]:
    """The names a story gives catalogue stages, by stage code; a code the project does not have is ignored later."""
    if not isinstance(raw, dict):
        return {}
    names: dict[str, str] = {}
    for code, value in raw.items():
        name = _text(value, locale, limit=255)
        if isinstance(code, str) and name:
            names[code] = name
        else:
            logger.info("quality_concept demo story: stage name for %r ignored", code)
    return names


def resolve_story(
    story: dict[str, Any], locale: str, *, families: set[str], categories: set[str], regimes: set[str]
) -> dict[str, Any]:
    """The plan of one project: the built-in story with ``story`` applied key by key.

    Args:
        story: The pack's story object for this module, or ``{}``.
        locale: Locale for ``{"en", "de"}`` texts.
        families: Standard family codes of the project's catalogue.
        categories: Requirement category codes of the catalogue.
        regimes: Acceptance regime codes of the catalogue.

    Returns:
        The dict ``default_plan`` returns. A value that is malformed or names a code the catalogue does not
        have keeps its default.
    """
    plan = default_plan()
    if not story:
        return plan
    plan["waiver_reason"] = _text(story.get("waiver_reason"), locale, limit=2000) or _WAIVER_REASON
    start = _days(story.get("start_days"), 30, 720)
    if start is not None:
        plan["start"] = start
        plan["expert_reports"] = tuple(
            (*row[:5], (start + 30 + 40 * i,)) for i, row in enumerate(plan["expert_reports"])
        )
    for key, field in (("regime", "regime"), ("regime_before_construction", "regime_before")):
        code = story.get(key)
        if code is None:
            continue
        if isinstance(code, str) and code in regimes:
            plan[field] = code
        else:
            logger.info("quality_concept demo story: acceptance regime %r ignored", code)
    packages = story.get("packages")
    if isinstance(packages, list) and len(packages) >= 2:
        rows = tuple(
            (str(pk["ref"])[:64], t)
            for pk in packages
            if isinstance(pk, dict) and pk.get("ref") and (t := _text(pk.get("title"), locale, limit=255))
        )
        if len(rows) >= 2:
            plan["packages"] = rows
    plan["standards"] = _merge_standards(story.get("standards"), families, locale) or plan["standards"]
    plan["requirements"] = _merge_requirements(story.get("requirements"), categories, locale) or plan["requirements"]
    plan["expert_reports"] = (
        _merge_reports(story.get("expert_reports"), plan["start"], locale) or plan["expert_reports"]
    )
    plan["units"] = _merge_units(story.get("units"), locale) or plan["units"]
    plan["neighbour"] = _merge_subject(plan["neighbour"], story.get("survey_neighbour"), locale)
    plan["road"] = _merge_subject(plan["road"], story.get("survey_road"), locale)
    plan["stage_names"] = _merge_stage_names(story.get("stage_names"), locale)
    return plan


async def _before_construction(session: AsyncSession, pid: uuid.UUID) -> bool:
    """Whether the gate into the phase that starts construction exists and is still undecided."""
    from app.modules.project_governance import public
    from app.modules.quality_concept.hosting import CONSTRUCTION_START

    starts = set(await public.phases_enabling(session, pid, CONSTRUCTION_START))
    if not starts:
        return False
    gates = [g for g in await public.project_gates(session, pid) if g.to_phase in starts]
    return bool(gates) and all(g.status != "decided" for g in gates)


async def _named(session: AsyncSession, pid: uuid.UUID, user_id: uuid.UUID, owner_id: uuid.UUID) -> uuid.UUID:
    """Who a record names as responsible: the user when they can open the project, else its owner."""
    from app.modules.project_governance import public

    return user_id if await public.user_can_access_project(session, pid, user_id) else owner_id


async def _team_members(session: AsyncSession, pid: uuid.UUID) -> list[uuid.UUID]:
    """The users on a team of this project, longest standing first."""
    from app.modules.teams.models import Team, TeamMembership

    stmt = (
        select(TeamMembership.user_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.project_id == pid)
        .order_by(TeamMembership.created_at)
    )
    return list((await session.execute(stmt)).scalars())


async def _actors(session: AsyncSession, pid: uuid.UUID, owner_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """``(recorder, second person)``: who records and who signs off.

    The recorder is the project's owner. The second person is the demo cast's cost owner, else
    its decider, else a member of one of the project's teams, and in every case somebody who can
    open this project. Nobody else is eligible: an account that merely exists in the installation
    may be a real person, of another tenant, and is never made the author of demo records. With
    nobody but the owner both sides are the owner and the two-person steps are left out.
    """
    from app.core import demo_cast
    from app.modules.project_governance import public

    cast = await demo_cast.find_cast(session)
    for uid in (cast.get("cost"), cast.get("decider"), *await _team_members(session, pid)):
        if uid is not None and uid != owner_id and await public.user_can_access_project(session, pid, uid):
            return owner_id, uid
    return owner_id, owner_id


def _credit_points(level: Any, count: int, available: Decimal) -> list[Decimal]:
    """Targeted points per credit: 18, 16, 14 ... and, where that falls short, enough to reach the target level.

    A target whose credits cannot reach the level's floor is flagged at risk on the readiness strip; the
    demo targets are meant to be reachable, so the shortfall goes onto the first credit.
    """
    from app.modules.quality_concept import evaluator as ev

    points = [Decimal(18 - 2 * n) for n in range(count)]
    floor = ev.to_decimal(level.min_score)
    if floor is None:
        return points
    if str(getattr(level, "score_unit", "points")) == "percent":
        floor = floor * available / Decimal("100")
    shortfall = floor - sum(points, Decimal("0"))
    if shortfall > 0:
        points[0] += shortfall
    return points


async def _seed_plan(
    svc: Any,
    pid: uuid.UUID,
    actor: uuid.UUID,
    named: uuid.UUID,
    today: date,
    totals: dict[str, int],
    before: bool,
    plan: dict[str, Any],
) -> list[str]:
    """Packages, standards, requirements, certification targets and expert reports. Returns the package refs."""
    await svc.patch_concept(
        pid,
        s.ConceptPatch(packages=[s.PackageScopeIn(ref=ref, code=ref, title=title) for ref, title in plan["packages"]]),
    )
    concept = await svc.require_concept(pid)
    refs = [p["ref"] for p in await svc.applicable_packages(concept)][:2]
    for code, title, family, discipline, package, mandate in plan["standards"]:
        await svc.create_standard(
            pid,
            s.StandardIn(
                code=code,
                title=title,
                family_code=family,
                discipline=discipline,
                package_refs=refs[package : package + 1],
                mandate=mandate,
            ),
        )
        totals["standards"] += 1
    for category, entity, attribute, value, unit, source in plan["requirements"]:
        await svc.add_requirement(
            pid,
            s.QualityRequirementIn(
                category=category,
                entity=entity,
                attribute=attribute,
                constraint_value=value,
                unit=unit,
                source_ref=source,
            ),
            actor,
        )
        totals["requirements"] += 1

    # One target per scope the catalogue offers a graded scheme for. The scheme is catalogue data.
    cat = await svc.catalogue_for(concept)
    seen: set[str] = set()
    for scheme in cat.certification_schemes:
        if scheme.scope in seen or len(scheme.levels) < 2 or not scheme.credit_categories:
            continue
        seen.add(scheme.scope)
        first = len(seen) == 1
        target = await svc.create_certification(
            pid,
            s.CertificationIn(
                scheme_code=scheme.code,
                scheme_version=scheme.versions[0] if scheme.versions else "",
                scope=scheme.scope,
                target_level=scheme.levels[-2].code,
                points_available=Decimal("100"),
            ),
        )
        totals["certifications"] += 1
        categories = scheme.credit_categories[: 5 if first else 3]
        points = _credit_points(scheme.levels[-2], len(categories), Decimal("100"))
        credits = await svc.add_credits(
            pid,
            target.id,
            [
                s.CreditIn(
                    credit_code=f"{category.upper()[:3]}-{n + 1:02d}",
                    category=category,
                    points_targeted=points[n],
                    owner_user_id=named,
                )
                for n, category in enumerate(categories)
            ],
        )
        totals["credits"] += len(credits)
        if first and not before:
            await svc.transition_certification(
                pid, target.id, s.CertificationTransition(action="register", on=today - timedelta(days=180))
            )
            await svc.patch_credit(pid, credits[0].id, s.CreditPatch(action="submit_evidence"))
            await svc.patch_credit(pid, credits[0].id, s.CreditPatch(action="achieve", points_achieved=Decimal("17")))
            await svc.patch_credit(pid, credits[1].id, s.CreditPatch(action="submit_evidence"))

    for subject, trigger, frequency, offsets, state, planned in plan["expert_reports"]:
        if before:
            # Nothing is built yet: every report is still planned and falls due after the start.
            offsets, state = planned, "planned"
        await svc.create_expert_report(
            pid,
            s.ExpertReportIn(
                subject=subject,
                trigger=trigger,
                frequency=frequency,
                due_dates=[today + timedelta(days=d) for d in offsets],
                state=state,
            ),
        )
        totals["expert_reports"] += 1
    return refs


async def _seed_stages(
    svc: Any,
    pid: uuid.UUID,
    engineer: uuid.UUID,
    authority: uuid.UUID,
    named: uuid.UUID,
    totals: dict[str, int],
    before: bool,
    stage_names: dict[str, str] | None = None,
) -> None:
    """The catalogue stages with owners, scoped to the systems still in testing, and one system under way.

    ``stage_names`` is what the project's story calls a stage, by code; the catalogue name stays for the rest.
    """
    from app.modules.commissioning.models import CxSystem
    from app.modules.construction_control.gating_service import GatingService
    from app.modules.construction_control.schemas import HoldGateReleaseIn

    session = svc.session
    systems = list(
        (await session.execute(select(CxSystem).where(CxSystem.project_id == pid).order_by(CxSystem.tag))).scalars()
    )
    staged = [x for x in systems if x.status in _OPEN_LIFECYCLES]
    scope: dict[str, Any] = {"mode": "all"}
    if len(staged) != len(systems):
        scope = {"mode": "systems", "values": [str(x.id) for x in staged]}
    stages = await svc.apply_catalogue_stages(pid)
    names = stage_names or {}
    for stage in stages:
        fields: dict[str, Any] = {"owner_user_id": named, "applies_to": scope}
        if stage.code in names:
            fields["name_override"] = names[stage.code]
        await svc.patch_stage(pid, stage.id, s.StageDefPatch(**fields))
    totals["stages"] += len(stages)
    rows = await svc.sync_progress(pid)
    totals["stage_rows"] += len(rows)
    if not staged or not stages or before:
        # Before construction the stage model stands with its owners and no system has been tested.
        return

    def row_of(system: Any, stage: Any) -> Any:
        return next(r for r in rows if r.system_id == system.id and r.stage_code == stage.code)

    first = stages[0]
    # System one: the first stage tested, passed and released by its hold gate; the next one in test.
    # System two: tested and passed, release requested and waiting for the releasing party.
    for index, system in enumerate(staged[:2]):
        row = row_of(system, first)
        if row.state != "ready":
            continue
        await svc.open_test(pid, row.id, engineer)
        await svc.record_result(pid, row.id, s.StageResultIn(result="pass"), engineer)
        gate = await svc.request_release(pid, row.id, engineer)
        if index:
            continue
        if authority == engineer:
            # Not a fault of the installation: a project with nobody but its owner shows the request only.
            logger.info("quality_concept demo seed: project %s has no second person to release a stage", pid)
            continue
        await GatingService(session).release_gate(
            gate.id, HoldGateReleaseIn(party_role=first.release_party_role), str(authority), signature_ip=None
        )
        await svc.apply_gate_released(gate.id)
        if len(stages) > 1:
            await svc.refresh_ready(pid)
            following = row_of(system, stages[1])
            if following.state == "ready":
                await svc.open_test(pid, following.id, engineer)


async def _seed_units(
    svc: Any, pid: uuid.UUID, refs: list[str], today: date, totals: dict[str, int], before: bool, plan: dict[str, Any]
) -> None:
    # Before construction the acceptances lie after commissioning, a year and a half ahead.
    shift = plan["start"] + 250 if before else 0
    for code, title, kind, days, indexes, section in plan["units"]:
        packages = [refs[i] for i in indexes if i < len(refs)]
        if kind.startswith("partial_") and not packages:
            continue
        await svc.create_unit(
            pid,
            s.AcceptanceUnitIn(
                code=code,
                title=title,
                kind=kind,
                regime_code=plan["regime_before"] if before else plan["regime"],
                package_refs=packages,
                section_ref=section,
                planned_date=today + timedelta(days=days + shift),
            ),
        )
        totals["units"] += 1


async def _seed_proofs(
    svc: Any,
    pid: uuid.UUID,
    refs: list[str],
    engineer: uuid.UUID,
    authority: uuid.UUID,
    totals: dict[str, int],
    before: bool,
    waiver_reason: str = _WAIVER_REASON,
) -> None:
    """The catalogue proof plan of each package, evidence from the project's own records, and decisions."""
    concept = await svc.require_concept(pid)
    cat = await svc.catalogue_for(concept)
    proofs: list[Any] = []
    for position, ref in enumerate(refs):
        preview = (await svc.generate_proofs(pid, s.ProofGenerateIn(package_ref=ref)))["preview"]
        wanted = [r["evidence_type"] for r in preview]
        # The second package carries the documentation proofs only, so the two columns differ.
        chosen = wanted if position == 0 else wanted[-3:]
        proofs += (await svc.generate_proofs(pid, s.ProofGenerateIn(package_ref=ref, confirm=chosen)))["created"]
    totals["proofs"] += len(proofs)
    if before:
        # The proof plan is the deliverable of this phase; no record of the works exists to prove anything.
        return

    passing: dict[str, list[str]] = {}
    delivered: list[Any] = []
    for proof in proofs:
        if proof.quantity_rule:
            # A counted proof needs the placed quantity to say how many tests are due.
            # One delivered test covers the quantity placed so far, so the proof reads as met rather
            # than as a test frequency that the single linked result cannot reach.
            per = Decimal(str(proof.quantity_rule.get("per_quantity") or "1"))
            minimum = int(proof.quantity_rule.get("min_count") or 1)
            rule = s.QuantityRuleIn(**{**proof.quantity_rule, "placed_quantity": per * minimum})
            await svc.patch_proof(pid, proof.id, s.ProofPatch(quantity_rule=rule))
        evidence_type = cat.evidence_type(proof.evidence_type)
        for kind in evidence_type.fulfilled_by if evidence_type else ():
            if kind not in passing:
                passing[kind] = [
                    c["id"] for c in await svc.candidates(pid, kind, limit=20) if c.get("outcome") == "pass"
                ]
            if not passing[kind]:
                continue
            await svc.add_link(
                pid,
                s.EvidenceLinkIn(owner_kind="proof", owner_id=proof.id, link_kind=kind, link_id=passing[kind][0]),
                engineer,
            )
            totals["links"] += 1
            if (await svc.proof_delivery(pid, [proof]))[proof.id].state == "delivered":
                delivered.append(proof)
            break
    # Four eyes: accepted by the authority, never by the engineer who linked the evidence.
    if authority != engineer:
        for proof in delivered[:2]:
            await svc.accept_proof(pid, proof.id, authority)
    elif delivered:
        logger.info("quality_concept demo seed: project %s has no second person to accept a proof", pid)
    open_proofs = [p for p in proofs if p not in delivered]
    if open_proofs:
        await svc.request_waiver(
            pid,
            open_proofs[-1].id,
            waiver_reason,
            engineer,
        )


async def _seed_surveys_ahead(
    svc: Any, pid: uuid.UUID, today: date, totals: dict[str, int], plan: dict[str, Any]
) -> None:
    """Before construction: the condition surveys are planned shortly before the start, none is carried out."""
    for kind, subject, days in (("neighbour_building", plan["neighbour"], 20), ("public_road", plan["road"], 10)):
        await svc.create_survey(
            pid,
            s.PreservationIn(
                subject_kind=kind,
                subject_ref=subject["ref"],
                address=subject["address"],
                influence_triggers=subject["triggers"],
                methods=subject["methods"],
                planned_date=today + timedelta(days=plan["start"] - days),
            ),
        )
        totals["surveys"] += 1


# How far ahead of its planned date a section may be reported complete. A unit planned further out
# is not finished yet, and a notice for it would make the works deemed accepted while they are being built.
NOTICE_WINDOW_DAYS = 60


def unit_due_for_notice(units: Iterable[Any], today: date, window: int = NOTICE_WINDOW_DAYS) -> Any | None:
    """The earliest acceptance unit when it is planned within ``window`` days of ``today``, else ``None``."""
    dated = [u for u in units if u.planned_date]
    if not dated:
        return None
    first = min(dated, key=lambda u: u.planned_date)
    return first if date.fromisoformat(str(first.planned_date)[:10]) <= today + timedelta(days=window) else None


async def _seed_course(svc: Any, pid: uuid.UUID, engineer: uuid.UUID, today: date) -> None:
    """Works under way: a documentation set chosen, one acceptance on its way, the concept in review.

    Each step is asked of the service first and left out when it would be refused, so a demo
    estate that lacks the records for it still gets its concept.
    """
    from app.modules.quality_concept import evaluator as ev
    from app.modules.quality_concept.models import AcceptanceUnit

    concept = await svc.require_concept(pid)
    cat = await svc.catalogue_for(concept)
    if cat.documentation_sets:
        await svc.patch_concept(pid, s.ConceptPatch(documentation_set_code=cat.documentation_sets[0].code))
    unit = unit_due_for_notice(await svc.repo.list(AcceptanceUnit, pid), today)
    if unit is not None:
        # The contractor gave notice of completion for the first section: the deemed date starts to count.
        await svc.record_dates(pid, unit.id, s.AcceptanceRecordIn(completion_notice_at=today - timedelta(days=4)))
        regime = cat.regime(unit.regime_code)
        unmet = await svc.unmet_preconditions(pid, unit)
        blocking, _reserved = ev.acceptance_request_check(
            unmet, reservable=regime.reservable if regime else (), with_reservations=True
        )
        if regime is not None and not blocking:
            await svc.request_acceptance(pid, unit.id, s.AcceptanceRequestIn(with_reservations=True), engineer)
    # Submitting freezes the first revision. It is the last step: a concept in review is closed to edits.
    concept = await svc.require_concept(pid)
    errors = [f for f in await svc.completeness(concept) if f.severity == ev.ERROR]
    if svc.submit_refusal(concept, errors) is None:
        await svc.submit(pid, engineer)


async def _seed_surveys(
    svc: Any, pid: uuid.UUID, actor: uuid.UUID, today: date, totals: dict[str, int], plan: dict[str, Any]
) -> None:
    nb, road = plan["neighbour"], plan["road"]
    before = await svc.create_survey(
        pid,
        s.PreservationIn(
            subject_kind="neighbour_building",
            subject_ref=nb["ref"],
            address=nb["address"],
            influence_triggers=nb["triggers"],
            methods=nb["methods"],
            planned_date=today - timedelta(days=300),
        ),
    )
    await svc.survey_action(
        pid, before.id, s.PreservationAction(action="invite", on=today - timedelta(days=320)), actor
    )
    await svc.survey_action(
        pid,
        before.id,
        s.PreservationAction(action="record_survey", on=today - timedelta(days=300), owner_acknowledged=True),
        actor,
    )
    await svc.survey_action(
        pid, before.id, s.PreservationAction(action="issue_report", on=today - timedelta(days=290)), actor
    )
    await svc.create_survey(
        pid,
        s.PreservationIn(
            subject_kind="neighbour_building",
            subject_ref=nb["ref"],
            address=nb["address"],
            influence_triggers=nb["triggers"],
            methods=nb["methods"],
            phase="after",
            paired_with_id=before.id,
            planned_date=today + timedelta(days=120),
        ),
    )
    await svc.create_survey(
        pid,
        s.PreservationIn(
            subject_kind="public_road",
            subject_ref=road["ref"],
            address=road["address"],
            influence_triggers=road["triggers"],
            methods=road["methods"],
            planned_date=today + timedelta(days=10),
        ),
    )
    totals["surveys"] += 3


async def seed_quality_concept_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seed a filled quality concept into every demo project that has none.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Projects to consider.

    Returns:
        Dict with per-entity insert counts.
    """
    from app.core.demo_marker import demo_id_of
    from app.modules.project_governance.public import demo_module_story
    from app.modules.projects.models import Project
    from app.modules.quality_concept.service import QualityConceptService

    totals = dict.fromkeys(_TOTALS, 0)
    ids = list(project_ids)
    if not ids:
        return totals
    rows = (
        await session.execute(
            select(Project.id, Project.owner_id, Project.metadata_, Project.locale).where(Project.id.in_(ids))
        )
    ).all()
    seeded = set(
        (await session.execute(select(QualityConcept.project_id).where(QualityConcept.project_id.in_(ids)))).scalars()
    )
    today = datetime.now(UTC).date()
    svc = QualityConceptService(session)
    for pid, owner, meta, locale in rows:
        if pid in seeded or not (isinstance(meta, dict) and str(meta.get("demo_id") or "").strip()):
            continue
        engineer, authority = await _actors(session, pid, owner)
        counts = dict.fromkeys(_TOTALS, 0)
        # One project is one unit of work. A refusal is not caught: it rolls this project back
        # and reaches the caller with its code, so a seed that no longer fits the rules is seen.
        # Steps that need a second person are left out above, with a warning, when there is none.
        async with session.begin_nested():
            before = await _before_construction(session, pid)
            named = await _named(session, pid, engineer, owner)
            await svc.ensure_concept(pid, engineer)
            cat = await svc.catalogue_for(await svc.require_concept(pid))
            plan = resolve_story(
                demo_module_story(demo_id_of(meta), "quality_concept"),
                locale or "en",
                families={f.code for f in cat.standard_families},
                categories={c.code for c in cat.requirement_categories},
                regimes={r.code for r in cat.acceptance_regimes},
            )
            refs = await _seed_plan(svc, pid, engineer, named, today, counts, before, plan)
            await _seed_stages(svc, pid, engineer, authority, named, counts, before, plan["stage_names"])
            await _seed_units(svc, pid, refs, today, counts, before, plan)
            await _seed_proofs(svc, pid, refs, engineer, authority, counts, before, plan["waiver_reason"])
            if before:
                await _seed_surveys_ahead(svc, pid, today, counts, plan)
            else:
                await _seed_surveys(svc, pid, engineer, today, counts, plan)
                await _seed_course(svc, pid, engineer, today)
        counts["projects"] = 1
        for key, value in counts.items():
            totals[key] += value
    logger.info("quality_concept demo seed: %s", totals)
    return totals
