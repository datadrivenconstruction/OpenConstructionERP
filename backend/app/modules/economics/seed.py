# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo economics for the demo estate, run by ``app.core.demo_enrichment``.

The story of a demo project (discount rate, business case lines, sources of finance with their tranches and
funding applications, securities, insurance, tax treatment and process set-up) is data: the active pack names
one file per project under ``module_files.economics`` and ``demo_module_story`` reads it. Texts are language
maps resolved by the project's own locale, and every date is a day offset from the day the demo is installed,
so the plan never goes stale. A project without such a story is left alone and the reason is logged.

Each demo project that has a priced bill gets a plan an owner would actually take to the gate: a cost frame cut
from the codes its bill uses (every group rounded up to the next 100 000 so the frame carries a little headroom
over the estimate, and the bill's markups rounded up the same way as the allowance), the business case of the
story, and a financing plan whose sources add up to the frame to the cent, the last source being the exact
remainder. Securities and insurance are set as a share of that frame. The figures are derived from the bill and
the frame, never typed in, so they follow the estimate when the demo bill changes.

The plan is proposed by a team member; the decision follows the story (``approve``): with gates the governance
gate approves, without them a second member does it by hand. Only projects carrying the demo marker are touched,
and a project that already has frame lines or sources is skipped, so a re-run never duplicates. Runs after the
governance and contracts seeders.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

D = Decimal
STEP = D("100000")
DEFAULT_NOTE = "Cost frame, business case and financing agreed with the client and the lenders."


class StoryError(ValueError):
    """The economics story of a demo project is malformed; the message says which key."""


@dataclass(frozen=True)
class Application:
    """The funding application behind a grant or subsidy source, and the programme it was made under."""

    code: str
    title: str
    programme_code: str
    programme_name: str
    authority: str
    region: str
    status: str  # submitted | approved
    submitted_on: str
    decided_on: str = ""
    expected_on: str = ""
    reference: str = ""


@dataclass(frozen=True)
class Source:
    kind: str
    name: str
    share: str | None  # share of the frame as a decimal, or None for the exact remainder
    due: tuple[str, ...]  # tranche dates, the amount split evenly, the last tranche taking the cent remainder
    rate: str | None = None
    condition: str = ""
    application: Application | None = None
    drawn: int = 0  # leading tranches already drawn, on their due date; they must lie in the past


@dataclass(frozen=True)
class SecuritySpec:
    kind: str
    description: str
    pct_of_frame: str
    issuer: str
    beneficiary: str
    reference: str
    valid_from: str | None
    valid_until: str | None
    status: str
    notes: str = ""


@dataclass(frozen=True)
class InsuranceSpec:
    kind: str
    insurer: str
    policy_number: str
    pct_of_frame: str | None  # the sum insured as a share of the frame, else ``sum_insured``
    sum_insured: str
    deductible: str
    period_from: str | None
    period_to: str | None
    status: str
    notes: str = ""


@dataclass(frozen=True)
class TaxSpec:
    vat_treatment: str
    input_tax_deduction: bool | None
    notes: str
    confirm: bool
    confirmed_on: str | None


@dataclass(frozen=True)
class ProcessSpec:
    area: str
    description: str
    owner: str
    status: str
    set_up_on: str | None
    notes: str = ""


@dataclass(frozen=True)
class Profile:
    discount_pct: str
    horizon: int
    build_years: int
    investment_label: str
    flows: tuple[tuple[str, str, str, int, int | None, str], ...]  # kind, label, amount, from, to, escalation
    sources: tuple[Source, ...]
    securities: tuple[SecuritySpec, ...] = field(default=())
    insurances: tuple[InsuranceSpec, ...] = field(default=())
    tax: TaxSpec | None = None
    process: tuple[ProcessSpec, ...] = field(default=())
    proposal_note: str = DEFAULT_NOTE
    approve: bool = False  # the story has reached the decision: the plan is approved, else it waits in review


def _need(cond: bool, key: str) -> None:
    if not cond:
        raise StoryError(key)


def _str(raw: Any, key: str, locale: str, *, required: bool = False) -> str:
    from app.modules.project_governance.public import story_text

    if raw is None:
        _need(not required, key)
        return ""
    out = story_text(raw, locale)
    _need(isinstance(out, str) and (bool(out.strip()) or not required), key)
    return out.strip()


def _dec(raw: Any, key: str, *, low: Decimal | None = None, high: Decimal | None = None) -> str:
    try:
        value = D(str(raw))
    except (InvalidOperation, ValueError):
        raise StoryError(key) from None
    _need(value.is_finite(), key)
    _need(low is None or value >= low, key)
    _need(high is None or value <= high, key)
    return str(raw)


def _int(raw: Any, key: str, *, low: int | None = None, high: int | None = None) -> int:
    _need(isinstance(raw, int) and not isinstance(raw, bool), key)
    _need(low is None or raw >= low, key)
    _need(high is None or raw <= high, key)
    return raw


def _day(today: date, raw: Any, key: str) -> str:
    return (today + timedelta(days=_int(raw, key))).isoformat()


def _opt_day(today: date, raw: dict[str, Any], name: str, key: str) -> str | None:
    return _day(today, raw[name], f"{key}.{name}") if raw.get(name) is not None else None


def _items(raw: Any, key: str, *, required: bool = False) -> list[dict[str, Any]]:
    if raw is None:
        _need(not required, key)
        return []
    _need(isinstance(raw, list) and all(isinstance(x, dict) for x in raw) and (bool(raw) or not required), key)
    return raw


def _parse_application(raw: dict[str, Any], today: date, key: str) -> Application:
    status = raw.get("status")
    _need(status in ("submitted", "approved"), f"{key}.status")
    return Application(
        code=_str(raw.get("code"), f"{key}.code", "en", required=True),
        title=_str(raw.get("title"), f"{key}.title", "en", required=True),
        programme_code=_str(raw.get("programme_code"), f"{key}.programme_code", "en", required=True),
        programme_name=_str(raw.get("programme_name"), f"{key}.programme_name", "en", required=True),
        authority=_str(raw.get("authority"), f"{key}.authority", "en", required=True),
        region=_str(raw.get("region"), f"{key}.region", "en", required=True),
        status=status,
        submitted_on=_day(today, raw.get("submitted_days"), f"{key}.submitted_days"),
        decided_on=_opt_day(today, raw, "decided_days", key) or "",
        expected_on=_opt_day(today, raw, "expected_days", key) or "",
        reference=_str(raw.get("reference"), f"{key}.reference", "en"),
    )


def _sources(story: dict[str, Any], locale: str, today: date) -> tuple[Source, ...]:
    out: list[Source] = []
    raw_sources = _items(story.get("sources"), "sources", required=True)
    for i, raw in enumerate(raw_sources):
        key = f"sources[{i}]"
        share = raw.get("share")
        # The last source is the exact remainder; every other one carries a share.
        _need((share is None) == (i == len(raw_sources) - 1), f"{key}.share")
        due = raw.get("due_days")
        _need(isinstance(due, list) and bool(due), f"{key}.due_days")
        app = raw.get("application")
        drawn = raw.get("drawn", 0)
        _need(isinstance(drawn, int) and not isinstance(drawn, bool) and 0 <= drawn <= len(due), f"{key}.drawn")
        _need(all(_int(v, f"{key}.due_days") < 0 for v in due[:drawn]), f"{key}.drawn")
        out.append(
            Source(
                kind=_str(raw.get("kind"), f"{key}.kind", "en", required=True),
                name=_str(raw.get("name"), f"{key}.name", locale, required=True),
                share=None if share is None else _dec(share, f"{key}.share", low=D(0), high=D(1)),
                due=tuple(_day(today, v, f"{key}.due_days") for v in due),
                rate=None if raw.get("rate") is None else _dec(raw["rate"], f"{key}.rate", low=D(0)),
                condition=_str(raw.get("condition"), f"{key}.condition", locale),
                application=_parse_application(app, today, f"{key}.application") if isinstance(app, dict) else None,
                drawn=drawn,
            )
        )
    return tuple(out)


def _securities(story: dict[str, Any], locale: str, today: date) -> tuple[SecuritySpec, ...]:
    out = []
    for i, raw in enumerate(_items(story.get("securities"), "securities")):
        key = f"securities[{i}]"
        out.append(
            SecuritySpec(
                kind=_str(raw.get("kind"), f"{key}.kind", "en", required=True),
                description=_str(raw.get("description"), f"{key}.description", locale, required=True),
                pct_of_frame=_dec(raw.get("pct_of_frame"), f"{key}.pct_of_frame", low=D(0), high=D(5)),
                issuer=_str(raw.get("issuer"), f"{key}.issuer", locale),
                beneficiary=_str(raw.get("beneficiary"), f"{key}.beneficiary", locale),
                reference=_str(raw.get("reference"), f"{key}.reference", locale),
                valid_from=_opt_day(today, raw, "valid_from_days", key),
                valid_until=_opt_day(today, raw, "valid_until_days", key),
                status=_str(raw.get("status"), f"{key}.status", "en", required=True),
                notes=_str(raw.get("notes"), f"{key}.notes", locale),
            )
        )
    return tuple(out)


def _insurances(story: dict[str, Any], locale: str, today: date) -> tuple[InsuranceSpec, ...]:
    out = []
    for i, raw in enumerate(_items(story.get("insurances"), "insurances")):
        key = f"insurances[{i}]"
        pct = raw.get("pct_of_frame")
        _need(pct is not None or raw.get("sum_insured") is not None, f"{key}.sum_insured")
        out.append(
            InsuranceSpec(
                kind=_str(raw.get("kind"), f"{key}.kind", "en", required=True),
                insurer=_str(raw.get("insurer"), f"{key}.insurer", locale, required=True),
                policy_number=_str(raw.get("policy_number"), f"{key}.policy_number", locale),
                pct_of_frame=None if pct is None else _dec(pct, f"{key}.pct_of_frame", low=D(0), high=D(5)),
                sum_insured=_dec(raw.get("sum_insured", "0"), f"{key}.sum_insured", low=D(0)),
                deductible=_dec(raw.get("deductible", "0"), f"{key}.deductible", low=D(0)),
                period_from=_opt_day(today, raw, "period_from_days", key),
                period_to=_opt_day(today, raw, "period_to_days", key),
                status=_str(raw.get("status"), f"{key}.status", "en", required=True),
                notes=_str(raw.get("notes"), f"{key}.notes", locale),
            )
        )
    return tuple(out)


def _tax(story: dict[str, Any], locale: str, today: date) -> TaxSpec | None:
    raw = story.get("tax")
    if raw is None:
        return None
    _need(isinstance(raw, dict), "tax")
    deduction = raw.get("input_tax_deduction")
    _need(deduction is None or isinstance(deduction, bool), "tax.input_tax_deduction")
    return TaxSpec(
        vat_treatment=_str(raw.get("vat_treatment"), "tax.vat_treatment", "en", required=True),
        input_tax_deduction=deduction,
        notes=_str(raw.get("notes"), "tax.notes", locale),
        confirm=bool(raw.get("confirm")),
        confirmed_on=_opt_day(today, raw, "confirmed_days", "tax"),
    )


def _process(story: dict[str, Any], locale: str, today: date) -> tuple[ProcessSpec, ...]:
    out = []
    for i, raw in enumerate(_items(story.get("process"), "process")):
        key = f"process[{i}]"
        out.append(
            ProcessSpec(
                area=_str(raw.get("area"), f"{key}.area", "en", required=True),
                description=_str(raw.get("description"), f"{key}.description", locale),
                owner=_str(raw.get("owner"), f"{key}.owner", locale),
                status=_str(raw.get("status"), f"{key}.status", "en", required=True),
                set_up_on=_opt_day(today, raw, "set_up_days", key),
                notes=_str(raw.get("notes"), f"{key}.notes", locale),
            )
        )
    return tuple(out)


def load_profile(story: dict[str, Any], locale: str, today: date) -> Profile:
    """The validated plan of a demo story. Raises :class:`StoryError` naming the first malformed key."""
    flows = []
    for i, raw in enumerate(_items(story.get("flows"), "flows", required=True)):
        key = f"flows[{i}]"
        flows.append(
            (
                _str(raw.get("kind"), f"{key}.kind", "en", required=True),
                _str(raw.get("label"), f"{key}.label", locale, required=True),
                _dec(raw.get("amount"), f"{key}.amount", low=D(0)),
                _int(raw.get("from"), f"{key}.from", low=0, high=100),
                None if raw.get("to") is None else _int(raw["to"], f"{key}.to", low=0, high=100),
                _dec(raw.get("escalation", "0"), f"{key}.escalation"),
            )
        )
    return Profile(
        discount_pct=_dec(story.get("discount_pct"), "discount_pct", low=D(0), high=D(100)),
        horizon=_int(story.get("horizon"), "horizon", low=1, high=100),
        build_years=_int(story.get("build_years"), "build_years", low=1, high=20),
        investment_label=_str(story.get("investment_label"), "investment_label", locale, required=True),
        flows=tuple(flows),
        sources=_sources(story, locale, today),
        securities=_securities(story, locale, today),
        insurances=_insurances(story, locale, today),
        tax=_tax(story, locale, today),
        process=_process(story, locale, today),
        proposal_note=_str(story.get("proposal_note"), "proposal_note", locale) or DEFAULT_NOTE,
        approve=bool(story.get("approve")),
    )


def round_up(value: Decimal) -> Decimal:
    """``value`` up to the next whole step of 100 000; a zero stays zero."""
    return (value / STEP).to_integral_value(rounding=ROUND_CEILING) * STEP


def thousands(value: Decimal) -> Decimal:
    """``value`` rounded to the nearest 1 000, the way a guarantee is written."""
    return (value / D(1000)).to_integral_value(rounding=ROUND_HALF_UP) * D(1000)


def split(total: Decimal, parts: int) -> list[Decimal]:
    """``total`` in ``parts`` equal amounts to the cent, the last one taking the remainder, so they add up exactly."""
    each = (total / parts).quantize(D("0.01"))
    amounts = [each] * (parts - 1)
    amounts.append(total - sum(amounts, D(0)))
    return amounts


async def seed_economics_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, Any]:
    """Seed the economics of every demo project in ``project_ids`` that has a story and a bill. The caller commits.

    Returns counts plus ``failed`` (projects whose seed raised and was rolled back), ``skipped`` (projects
    left alone, with the reason) and ``ok`` (no failure).
    """
    from app.core.demo_marker import demo_id_of
    from app.modules.economics.repository import EconomicsRepository
    from app.modules.project_governance.public import demo_module_story
    from app.modules.projects.models import Project

    totals: dict[str, Any] = {
        "projects": 0,
        "frame_lines": 0,
        "flow_lines": 0,
        "sources": 0,
        "tranches": 0,
        "applications": 0,
        "securities": 0,
        "insurances": 0,
        "process": 0,
        "proposed": 0,
        "approved": 0,
        "skipped": [],
        "failed": [],
        "ok": True,
    }
    ids = list(project_ids)
    if not ids:
        return totals
    rows = (
        await session.execute(
            select(Project.id, Project.owner_id, Project.metadata_, Project.locale).where(Project.id.in_(ids))
        )
    ).all()
    today = datetime.now(UTC).date()
    for pid, owner, meta, locale in rows:
        demo_id = demo_id_of(meta)
        if not demo_id:
            continue
        story = demo_module_story(demo_id, "economics")
        if not story:
            logger.info("economics demo seed: %s has no economics story in the active pack, left alone", demo_id)
            continue
        try:
            profile = load_profile(story, locale or "en", today)
        except StoryError as exc:
            logger.error("economics demo story of %s is malformed at %s, left alone", demo_id, exc)
            totals["skipped"].append({"project_id": str(pid), "reason": f"story_malformed:{exc}"})
            continue
        repo = EconomicsRepository(session)
        if await repo.frame_lines(pid) or await repo.sources(pid):
            continue
        try:
            async with session.begin_nested():
                counts = await _seed_project(session, pid, owner, profile)
        except _NoBill:
            totals["skipped"].append({"project_id": str(pid), "reason": "no_bill"})
            continue
        except Exception as exc:
            logger.error("economics demo seed failed for %s and was rolled back", pid, exc_info=True)
            totals["failed"].append({"project_id": str(pid), "reason": type(exc).__name__})
            continue
        totals["projects"] += 1
        for k, v in counts.items():
            totals[k] += v
    totals["ok"] = not totals["failed"]
    return totals


class _NoBill(Exception):
    """The project has no priced bill to cut a frame from."""


async def _seed_project(
    session: AsyncSession, pid: uuid.UUID, owner: uuid.UUID | None, profile: Profile
) -> dict[str, int]:
    from app.modules.economics import readings
    from app.modules.economics.service import EconomicsService

    service = EconomicsService(session)
    plan = await service.start(pid, owner)
    bill = await readings.read_bill(session, pid, plan.classification_standard, plan.boq_id)
    if bill is None or bill.direct_cost <= 0:
        raise _NoBill
    await service.patch_plan(
        pid,
        {
            "discount_rate_pct": D(profile.discount_pct),
            "horizon_years": profile.horizon,
            "markup_allowance": round_up(bill.markups_total),
            # The owner names the bill the plan reads, so a project with several bills has no open question.
            "boq_id": bill.boq_id,
        },
        owner,
    )
    # Commitments need cost lines to sit under; a project without them is built the way the plan advises.
    if not (await readings.read_commitments(session, pid)).available:
        from app.modules.costmodel.service import CostSpineService

        await CostSpineService(session).generate_from_boq(pid, bill.boq_id)
    frame = await service.generate_frame(pid, depth=1, amounts="estimate", replace=True, actor_id=owner)
    for line in frame:
        line.amount = round_up(line.amount)
    await session.flush()
    frame_total = sum((f.amount for f in frame), D(0)) + round_up(bill.markups_total)

    await service.add_flow_line(
        pid,
        {
            "kind": "investment",
            "label": profile.investment_label,
            "source": "cost_frame",
            "year_from": 0,
            "year_to": profile.build_years - 1,
        },
        owner,
    )
    for kind, label, amount, year_from, year_to, escalation in profile.flows:
        await service.add_flow_line(
            pid,
            {
                "kind": kind,
                "label": label,
                "amount": D(amount),
                "year_from": year_from,
                "year_to": year_to,
                "escalation_pct": D(escalation),
            },
            owner,
        )

    tranches = 0
    to_draw: list[tuple[uuid.UUID, str]] = []
    given = D(0)
    for source in profile.sources:
        amount = (frame_total - given) if source.share is None else (frame_total * D(source.share)).quantize(D("0.01"))
        given += amount
        application_id = None
        if source.application is not None:
            application_id = await _application(session, pid, source.application, amount, frame_total)
        row = await service.add_source(
            pid,
            {
                "kind": source.kind,
                "name": source.name,
                "amount": amount,
                "interest_rate_pct": D(source.rate) if source.rate is not None else None,
                "funding_application_id": application_id,
            },
            owner,
        )
        for n, (due, part) in enumerate(zip(source.due, split(amount, len(source.due)), strict=True)):
            tranche = await service.add_tranche(
                pid, row.id, {"due_on": due, "amount": part, "condition": source.condition}, owner
            )
            if n < source.drawn:
                to_draw.append((tranche.id, due))
            tranches += 1
    await _registers(service, pid, owner, profile, frame_total)
    status = await _settle(session, service, pid, owner, profile)
    # Drawing is a fact of the project and stays open on an approved plan.
    for tranche_id, due in to_draw:
        await service.patch_tranche(pid, tranche_id, {"status": "drawn", "drawn_on": due}, owner)
    return {
        "frame_lines": len(frame),
        "flow_lines": len(profile.flows) + 1,
        "sources": len(profile.sources),
        "tranches": tranches,
        "applications": sum(1 for x in profile.sources if x.application is not None),
        "securities": len(profile.securities),
        "insurances": len(profile.insurances),
        "process": len(profile.process),
        "proposed": int(status in ("proposed", "approved")),
        "approved": int(status == "approved"),
    }


async def _registers(
    service: Any, pid: uuid.UUID, owner: uuid.UUID | None, profile: Profile, frame_total: Decimal
) -> None:
    """Securities, insurance, tax treatment and process set-up of the story, the amounts as shares of the frame."""
    for sec in profile.securities:
        await service.add_security(
            pid,
            {
                "kind": sec.kind,
                "description": sec.description,
                "amount": thousands(frame_total * D(sec.pct_of_frame)),
                "issuer": sec.issuer,
                "beneficiary": sec.beneficiary,
                "reference": sec.reference,
                "valid_from": sec.valid_from,
                "valid_until": sec.valid_until,
                "status": sec.status,
                "notes": sec.notes,
            },
            owner,
        )
    for ins in profile.insurances:
        insured = thousands(frame_total * D(ins.pct_of_frame)) if ins.pct_of_frame is not None else D(ins.sum_insured)
        await service.add_insurance(
            pid,
            {
                "kind": ins.kind,
                "insurer": ins.insurer,
                "policy_number": ins.policy_number,
                "sum_insured": insured,
                "deductible": D(ins.deductible),
                "period_from": ins.period_from,
                "period_to": ins.period_to,
                "status": ins.status,
                "notes": ins.notes,
            },
            owner,
        )
    if profile.tax is not None:
        tax = await service.put_tax(
            pid,
            {
                "vat_treatment": profile.tax.vat_treatment,
                "input_tax_deduction": profile.tax.input_tax_deduction,
                "notes": profile.tax.notes,
                "confirm": profile.tax.confirm,
            },
            owner,
        )
        if profile.tax.confirm and profile.tax.confirmed_on:
            # The confirmation happened some time ago in the story, not at the moment of the install.
            tax.confirmed_at = datetime.fromisoformat(profile.tax.confirmed_on).replace(hour=10, tzinfo=UTC)
            await service.session.flush()
    for proc in profile.process:
        await service.put_process(
            pid,
            proc.area,
            {
                "description": proc.description,
                "owner": proc.owner,
                "status": proc.status,
                "set_up_on": proc.set_up_on,
                "notes": proc.notes,
            },
            owner,
        )


async def _application(
    session: AsyncSession, pid: uuid.UUID, app: Application, amount: Decimal, frame_total: Decimal
) -> uuid.UUID:
    """The funding application of a grant source, filed under its programme (created once as reference data)."""
    from app.modules.funding.models import FundingApplication, FundingProgramme
    from app.modules.projects.models import Project

    country = app.region[:2]
    programme = (
        await session.execute(
            select(FundingProgramme).where(
                FundingProgramme.code == app.programme_code, FundingProgramme.country == country
            )
        )
    ).scalar_one_or_none()
    if programme is None:
        programme = FundingProgramme(
            code=app.programme_code,
            name=app.programme_name,
            authority_name=app.authority,
            authority_level="national" if app.region == country else "regional",
            country=country,
            region_code=app.region if app.region != country else "",
            instrument="grant",
            currency="EUR",
            status="open",
        )
        session.add(programme)
        await session.flush()
    project = await session.get(Project, pid)
    client = ((project.metadata_ or {}).get("client") if project is not None else "") or ""
    approved = app.status == "approved"
    row = FundingApplication(
        project_id=pid,
        programme_id=programme.id,
        code=app.code,
        title=app.title,
        applicant_name=str(client),
        applicant_type="company",
        status=app.status,
        eligible_cost_base=frame_total,
        requested_amount=amount,
        own_share_amount=frame_total - amount,
        currency="EUR",
        submitted_on=app.submitted_on,
        decision_expected_on=app.expected_on or app.decided_on,
        decided_on=app.decided_on,
        award_reference=app.reference,
        approved_amount=amount if approved else Decimal("0"),
    )
    session.add(row)
    await session.flush()
    return row.id


async def _settle(
    session: AsyncSession, service: Any, pid: uuid.UUID, owner: uuid.UUID | None, profile: Profile
) -> str:
    """Propose the plan as a team member, and let the governance decision approve it when the story reached it.

    Under four-eyes the proposer is never the person who decides, so the proposal is made by a member other
    than the gate decider where the team has one. A plan whose gate has been decided is approved by the
    service's own binding rule: the proposal is dated just before that decision, as it would have been made.
    Without gates a different team member approves by hand. Where none of that is possible the plan stays
    proposed, which is the honest state.
    """
    from app.modules.economics import hosting
    from app.modules.teams.models import Team, TeamMembership

    members = list(
        (
            await session.execute(
                select(TeamMembership.user_id)
                .join(Team, Team.id == TeamMembership.team_id)
                .where(Team.project_id == pid)
            )
        )
        .scalars()
        .all()
    )
    gates = await hosting.gates_in_use(session, pid)
    doc = (await hosting.carrier_document(session, pid))[0] if gates else None
    decision = None
    if doc is not None and doc.status == "binding" and doc.approved_gate_id is not None:
        decision = await hosting.latest_gate_decision(session, pid, doc.approved_gate_id, ("go", "go_with_conditions"))
    decider = getattr(decision, "decided_by", None)
    proposer = next((m for m in members if m != decider), owner)
    try:
        await service.propose(pid, profile.proposal_note, proposer)
    except Exception:
        logger.warning("economics demo seed: the plan of %s could not be proposed", pid, exc_info=True)
        return "draft"
    plan = await service.require_plan(pid)
    if not profile.approve:
        return plan.status
    if gates:
        if decision is None or decider is None or decider == proposer:
            return plan.status
        approval = await service.repo.approval(pid, plan.current_approval_id)
        if decision.decided_at is not None and approval is not None:
            approval.proposed_at = decision.decided_at - timedelta(days=3)
            await session.flush()
        await service.sync_with_governance(pid)
    else:
        approver = next((m for m in members if m != proposer), None)
        if approver is not None:
            await service.approve_by_hand(pid, approver)
    return (await service.require_plan(pid)).status
