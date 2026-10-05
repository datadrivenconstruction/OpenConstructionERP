# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stage executors: write a course's seed into the learner's project.

Every object goes through the owning module's service, exactly as if the
learner had clicked it, so validation, events and derived fields (totals, the
frozen contract value, the retention schedule, the bid validity flag) behave as
they do in the ERP. The one exception is the progress reading: a reading has no
API path that accepts a past date, and the course needs it inside the claim
period, so it is written through the ORM with a backdated ``recorded_at``
(design §5.1, decision 20; the founder's call: "the seeder writes the readings
with a date").

Service calls per step (the report of stream C lists them too):

* ``project``: ``ProjectService.create_project(ProjectCreate, owner_id=learner)``.
  The learner is the owner, which is what ``verify_project_access`` admits, and
  ``create_project`` also puts the learner in the project's default team as
  ``lead``.
* ``boq``: ``BOQService.create_boq``, ``create_section`` per section,
  ``add_position`` per position. A position the learner prices is seeded at 0.
* ``markups``: ``BOQService.add_markup`` per pre-seeded markup.
* ``bid_package``: ``BidManagementService.create_package``, ``create_line`` per
  scope line, ``create_bidder`` and ``create_invitation`` per bid,
  ``publish_package``, then ``record_submission`` and
  ``create_submission_line`` per priced line of every bid the seed records.
  A bid whose ``recorded_by`` is not ``seed ...`` is left to the learner, who
  records it in the task; its bidder and invitation are seeded. Bids are recorded before the
  package is opened, so they stay valid; the learner opens, levels and awards.
  ``send_invitations`` and ``open_bids`` are never called.
* ``contract``: ``BOQService.create_boq`` and ``add_position`` for the
  contract-sum-analysis bill when a line links ``csa``;
  ``ContractsService.create_contract``, ``bulk_create_lines`` and
  ``transition_contract(id, "active")``, which runs the compliance gate,
  freezes ``original_contract_value`` and seeds the retention schedule.
* ``progress_readings``: ORM ``ProgressEntry`` rows, one flush each so ``seq``
  follows the file order.
* ``variation_request``: ``VariationsService.create_request`` in draft, no cost.

A stage runs inside a savepoint. When a step fails, the savepoint is rolled
back, so neither rows nor refs of that stage survive, and :class:`SeedError`
names the step. A step whose ``seeded_refs`` key is already set is skipped, so
running a stage twice creates nothing twice.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.trainer.seeder.plan import (
    CSA_BOQ_REF,
    ENROLMENT_STAGES,
    PROJECT_REF,
    SeedPlan,
    SeedStep,
    bid_recorded_by_seed,
    period_window,
    reading_timestamp,
    section_line_ordinal,
    sov_line_rate,
    stage_key,
)
from app.modules.trainer.spec import CONTRACT_REF, MAIN_BOQ_REF, PACKAGE_REF, CourseSpec, MarkupSeed, Stage, to_percent

logger = logging.getLogger(__name__)

#: Name of the contract-sum-analysis bill (design §5.3, risk R4) when the
#: caller passes none. User-visible: Wave 2 should pass a translated name.
DEFAULT_CSA_BOQ_NAME = "Contract sum analysis (for valuations)"

#: Domain of the invitation addresses of seeded bidders. ``.invalid`` is
#: reserved (RFC 2606): nothing can ever be delivered there.
BIDDER_EMAIL_DOMAIN = "academy.invalid"

_SEEDING: ContextVar[uuid.UUID | None] = ContextVar("trainer_seeding_enrolment", default=None)


def seeding_enrolment() -> uuid.UUID | None:
    """The enrolment whose seed is running in this context, or ``None``.

    Event handlers of the trainer read it to ignore the events the seed itself
    publishes (design §5.1). Tasks spawned during the seed (detached event
    handlers) copy the context, so they see it too.
    """
    return _SEEDING.get()


@contextlib.contextmanager
def seeding(enrolment_id: uuid.UUID) -> Iterator[None]:
    """Mark the current context as seeding ``enrolment_id``.

    :func:`execute_stage` holds it around its own writes. A caller that
    publishes after commit should hold it across the commit as well.
    """
    token = _SEEDING.set(enrolment_id)
    try:
        yield
    finally:
        _SEEDING.reset(token)


class SeedError(RuntimeError):
    """A seed step failed; nothing of its stage was kept.

    Attributes:
        step: The ``seeded_refs`` key of the failing step.
        stage: The stage, in spec spelling.
    """

    def __init__(self, step: str, stage: str, message: str) -> None:
        self.step = step
        self.stage = stage
        super().__init__(f"{stage} / {step}: {message}")


@dataclass(frozen=True, slots=True)
class SeedContext:
    """Who and what a seed is for.

    Attributes:
        enrolment_id: The enrolment; it suffixes the database-wide unique codes.
        learner_id: The learner; owner of the project and actor of every call.
        csa_boq_name: Name of the contract-sum-analysis bill, in the learner's
            language when the caller has it.
    """

    enrolment_id: uuid.UUID
    learner_id: uuid.UUID
    csa_boq_name: str = DEFAULT_CSA_BOQ_NAME

    @property
    def code_suffix(self) -> str:
        """Eight hex digits of the enrolment, upper case."""
        return self.enrolment_id.hex[:8].upper()

    @property
    def actor(self) -> str:
        """The learner id as the services take it."""
        return str(self.learner_id)


Refs = dict[str, Any]
_Executor = Callable[[AsyncSession, SeedStep, CourseSpec, SeedContext, Refs], Awaitable[None]]


async def execute_stage(
    session: AsyncSession,
    plan: SeedPlan,
    stage: Stage,
    ctx: SeedContext,
    seeded_refs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the steps of one stage that have not run yet.

    Args:
        session: The caller's session; nothing is committed here.
        plan: The course plan.
        stage: The stage to run.
        ctx: Enrolment and learner.
        seeded_refs: The enrolment's refs so far; not modified.

    Returns:
        A new mapping: ``seeded_refs`` plus the refs this stage created. The
        caller stores it on the enrolment.

    Raises:
        SeedError: a step failed; the stage's writes were rolled back.
    """
    refs: dict[str, Any] = dict(seeded_refs or {})
    pending = [step for step in plan.for_stage(stage) if step.ref_key not in refs]
    if not pending:
        return refs
    current = pending[0]
    with seeding(ctx.enrolment_id):
        try:
            async with session.begin_nested():
                for step in pending:
                    current = step
                    await _EXECUTORS[step.kind](session, step, plan.course, ctx, refs)
        except SeedError:
            raise
        except HTTPException as exc:
            raise SeedError(current.ref_key, stage_key(stage), f"HTTP {exc.status_code}: {exc.detail}") from exc
        except (ValidationError, ValueError, KeyError, SQLAlchemyError) as exc:
            raise SeedError(current.ref_key, stage_key(stage), f"{type(exc).__name__}: {exc}") from exc
    logger.info(
        "Trainer seed %s for enrolment %s: %s",
        stage_key(stage),
        ctx.enrolment_id,
        ", ".join(s.ref_key for s in pending),
    )
    return refs


async def execute_enrolment(
    session: AsyncSession,
    plan: SeedPlan,
    ctx: SeedContext,
    seeded_refs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run what an enrolment needs at once: ``on_enrol`` and task 1's unlock.

    Task 1 is unlocked when the enrolment starts, so its ``on_unlock(1)`` seed
    runs then too.
    """
    refs: dict[str, Any] = dict(seeded_refs or {})
    for stage in ENROLMENT_STAGES:
        refs = await execute_stage(session, plan, stage, ctx, refs)
    return refs


# ── Helpers ──────────────────────────────────────────────────────────────────


def _fail(step: SeedStep, message: str) -> SeedError:
    return SeedError(step.ref_key, stage_key(step.stage), message)


def _ref_id(refs: Refs, key: str, step: SeedStep) -> uuid.UUID:
    value = refs.get(key)
    if not isinstance(value, str):
        raise _fail(step, f"{key} has not been seeded yet")
    return uuid.UUID(value)


def _json_number(value: Decimal) -> int | float:
    """A Decimal as a JSON number: an int when whole, else a float."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)


# ── Step executors ───────────────────────────────────────────────────────────


async def _seed_project(
    session: AsyncSession, step: SeedStep, course: CourseSpec, ctx: SeedContext, refs: Refs
) -> None:
    from app.config import get_settings
    from app.modules.projects.models import Project
    from app.modules.projects.schemas import ProjectCreate
    from app.modules.projects.service import ProjectService

    p = course.seed.project
    data: dict[str, Any] = {
        "name": p.name,
        "description": p.description or "",
        "region": p.region or "",
        "classification_standard": p.classification_standard or "",
        "currency": p.currency,
        "locale": course.language,
        "country_code": (p.country_code or p.country).strip().upper(),
    }
    if p.validation_rule_sets:
        data["validation_rule_sets"] = list(p.validation_rule_sets)
    if p.address is not None:
        # ``address["state"]`` is what the contracts country defaults read the
        # state from (``contracts.country_defaults.subdivision_from_address``,
        # commit fd798fcb6 on its own branch, not merged here yet): it picks the
        # per-payment retention ceiling of the state pack, California's 5 % for
        # the US course. The seeder states the course's retention explicitly,
        # so the field feeds the defaults the learner sees, not the seeded rate.
        data["address"] = p.address.model_dump(exclude_none=True)
    # ``works`` (public | private, FR) has a project column only once the French
    # retention fix (commit 396a8e9e8, not merged here yet) lands. Written only
    # where the column exists, so this branch seeds the same project either way.
    works_column = p.works is not None and hasattr(Project, "works")
    if works_column and "works" in ProjectCreate.model_fields:
        data["works"] = p.works
    project = await ProjectService(session, get_settings()).create_project(ProjectCreate(**data), ctx.learner_id)
    if works_column and getattr(project, "works", None) != p.works:
        project.works = p.works  # type: ignore[attr-defined]
        await session.flush()
    refs[PROJECT_REF] = str(project.id)


async def _seed_boq(session: AsyncSession, step: SeedStep, course: CourseSpec, ctx: SeedContext, refs: Refs) -> None:
    from app.modules.boq.schemas import BOQCreate, PositionCreate, SectionCreate
    from app.modules.boq.service import BOQService

    spec_boq = course.seed.boq
    if spec_boq is None:
        raise _fail(step, "the course seeds no bill")
    project_id = _ref_id(refs, PROJECT_REF, step)
    svc = BOQService(session)
    boq = await svc.create_boq(BOQCreate(project_id=project_id, name=spec_boq.name))
    sections: dict[str, str] = {}
    positions: dict[str, str] = {}

    async def add(
        ordinal: str,
        description: str,
        unit: str,
        qty: Decimal,
        rate: Decimal | None,
        parent: str | None,
        classification: dict[str, str] | None = None,
    ) -> None:
        position = await svc.add_position(
            PositionCreate(
                boq_id=boq.id,
                parent_id=uuid.UUID(parent) if parent else None,
                ordinal=ordinal,
                description=description,
                unit=unit,
                quantity=float(qty),
                unit_rate=rate if rate is not None else Decimal(0),
                classification=dict(classification or {}),
            )
        )
        positions[ordinal] = str(position.id)

    by_section: dict[str | None, list[Any]] = {}
    for position in spec_boq.positions:
        by_section.setdefault(position.section, []).append(position)

    for section in spec_boq.sections:
        row = await svc.create_section(boq.id, SectionCreate(ordinal=section.ordinal, description=section.title or ""))
        sections[section.ordinal] = str(row.id)
        if section.lines:
            for line in section.lines:
                await add(
                    line.code,
                    line.description or "",
                    line.unit or "",
                    line.qty if line.qty is not None else Decimal(1),
                    line.rate,
                    sections[section.ordinal],
                )
        elif section.line is not None and section.amount is not None:
            await add(
                section_line_ordinal(section),
                section.line,
                section.unit or "",
                Decimal(1),
                section.amount,
                sections[section.ordinal],
            )
        for position in by_section.pop(section.ordinal, []):
            await add(
                position.code,
                position.description,
                position.unit,
                position.qty,
                position.rate,
                sections[section.ordinal],
                position.classification,
            )
    for position in by_section.pop(None, []):
        await add(
            position.code,
            position.description,
            position.unit,
            position.qty,
            position.rate,
            None,
            position.classification,
        )

    refs[MAIN_BOQ_REF] = str(boq.id)
    refs[f"{MAIN_BOQ_REF}.sections"] = sections
    refs[f"{MAIN_BOQ_REF}.positions"] = positions


def _markup_create(markup: MarkupSeed, sort_default: int) -> Any:
    from app.modules.boq.schemas import MarkupCreate

    data: dict[str, Any] = {
        "name": markup.name,
        "sort_order": markup.sort_order if markup.sort_order is not None else sort_default,
    }
    if markup.markup_type is not None:
        data["markup_type"] = markup.markup_type
    if markup.apply_to is not None:
        data["apply_to"] = markup.apply_to
    if markup.category is not None:
        data["category"] = markup.category
    if markup.percentage is not None:
        # The ERP column is a percent; a fraction in the spec is converted.
        data["percentage"] = float(to_percent(markup.percentage, markup.unit))
    if markup.fixed_amount is not None:
        data["fixed_amount"] = markup.fixed_amount
    if markup.metadata:
        data["metadata"] = dict(markup.metadata)
    return MarkupCreate(**data)


async def _seed_markups(
    session: AsyncSession, step: SeedStep, course: CourseSpec, ctx: SeedContext, refs: Refs
) -> None:
    from app.modules.boq.service import BOQService

    spec_boq = course.seed.boq
    if spec_boq is None:
        raise _fail(step, "the course seeds no bill")
    boq_id = _ref_id(refs, MAIN_BOQ_REF, step)
    boq_stage = spec_boq.parsed_stage
    svc = BOQService(session)
    created: dict[str, str] = {}
    for i, markup in enumerate(spec_boq.markups):
        own = markup.stage
        if (own is None and boq_stage != step.stage) or (own is not None and markup.parsed_stage != step.stage):
            continue
        row = await svc.add_markup(boq_id, _markup_create(markup, sort_default=(i + 1) * 10))
        created[markup.name] = str(row.id)
    refs[step.ref_key] = created


async def _seed_bid_package(
    session: AsyncSession, step: SeedStep, course: CourseSpec, ctx: SeedContext, refs: Refs
) -> None:
    from app.modules.bid_management.schemas import (
        BidderCreate,
        BidInvitationCreate,
        BidPackageCreate,
        BidPackageLineItemCreate,
        BidSubmissionCreate,
        BidSubmissionLineCreate,
    )
    from app.modules.bid_management.service import BidManagementService

    spec_pkg = course.seed.bid_package
    if spec_pkg is None:
        raise _fail(step, "the course seeds no bid package")
    project_id = _ref_id(refs, PROJECT_REF, step)
    svc = BidManagementService(session)
    budget = spec_pkg.budget.value if spec_pkg.budget is not None and spec_pkg.budget.value is not None else Decimal(0)
    package = await svc.create_package(
        BidPackageCreate(
            project_id=project_id,
            # Package codes are unique across the database (design §5.1).
            code=f"TRN-{ctx.code_suffix}",
            title=spec_pkg.title,
            currency=spec_pkg.currency,
            total_budget_estimate=budget,
        ),
        user_id=ctx.actor,
    )
    main_positions: dict[str, str] = refs.get(f"{MAIN_BOQ_REF}.positions", {})
    lines: dict[str, Any] = {}
    for i, scope in enumerate(spec_pkg.scope_lines):
        # A link only: award writes no bill rate (tendering.apply_winner does).
        linked = main_positions.get(scope.boq_position) if scope.boq_position else None
        lines[scope.code] = await svc.create_line(
            BidPackageLineItemCreate(
                package_id=package.id,
                code=scope.code,
                description=scope.description or "",
                unit=scope.unit,
                quantity=scope.qty,
                order_index=i,
                is_mandatory=scope.mandatory,
                boq_position_id=uuid.UUID(linked) if linked else None,
            )
        )
    bidders: dict[str, Any] = {}
    invitations: dict[str, Any] = {}
    for i, bid in enumerate(spec_pkg.bids):
        bidder = await svc.create_bidder(BidderCreate(package_id=package.id, company_name=bid.bidder))
        bidders[bid.bidder] = bidder
        invitations[bid.bidder] = await svc.create_invitation(
            BidInvitationCreate(
                package_id=package.id,
                bidder_ref_id=bidder.id,
                invitee_email=f"bidder{i + 1}.{ctx.code_suffix.lower()}@{BIDDER_EMAIL_DOMAIN}",
                invitee_company_name=bid.bidder,
            )
        )
    # Bids are recorded inside the tender window and before opening: a bid
    # entered after "Open bids" is stored with is_valid=False.
    await svc.publish_package(package.id, user_id=ctx.actor)
    submissions: dict[str, str] = {}
    scope_qty = {s.code: s.qty for s in spec_pkg.scope_lines}
    for bid in spec_pkg.bids:
        if not bid_recorded_by_seed(bid):
            continue  # the learner records this bid in the task, before opening
        submission = await svc.record_submission(
            BidSubmissionCreate(
                invitation_id=invitations[bid.bidder].id,
                bidder_id=bidders[bid.bidder].id,
                total_amount=bid.total,
                currency=spec_pkg.currency,
                exclusions=list(bid.exclusions or []),
            )
        )
        submissions[bid.bidder] = str(submission.id)
        for line in bid.lines:
            if line.rate is None:
                continue  # left blank by the bidder: the gap the learner levels
            payload: dict[str, Any] = {
                "submission_id": submission.id,
                "line_item_id": lines[line.code].id,
                "unit_price": line.rate,
                "quantity_priced": scope_qty[line.code],
                "comment": line.comment or "",
            }
            if line.inclusion_status is not None:
                payload["inclusion_status"] = line.inclusion_status
            await svc.create_submission_line(BidSubmissionLineCreate(**payload))
    refs[PACKAGE_REF] = str(package.id)
    refs[f"{PACKAGE_REF}.lines"] = {code: str(row.id) for code, row in lines.items()}
    refs[f"{PACKAGE_REF}.bidders"] = {name: str(row.id) for name, row in bidders.items()}
    refs[f"{PACKAGE_REF}.invitations"] = {name: str(row.id) for name, row in invitations.items()}
    refs[f"{PACKAGE_REF}.submissions"] = submissions


async def _seed_contract(
    session: AsyncSession, step: SeedStep, course: CourseSpec, ctx: SeedContext, refs: Refs
) -> None:
    from app.modules.boq.schemas import BOQCreate, PositionCreate
    from app.modules.boq.service import BOQService
    from app.modules.contracts.schemas import ContractCreate, ContractLineCreate
    from app.modules.contracts.service import BOQ_POSITION_META_KEY, ContractsService

    spec_contract = course.seed.contract
    if spec_contract is None:
        raise _fail(step, "the course seeds no contract")
    project_id = _ref_id(refs, PROJECT_REF, step)
    sov = spec_contract.schedule_of_values

    # The bill positions the lines read progress through (design §5.3): a
    # ``csa`` line gets a lump-sum position in the contract-sum-analysis bill,
    # a ``boq:<ordinal>`` line the main bill position, a ``none`` line nothing.
    position_links: dict[str, str] = {}
    csa_lines = [line for line in sov if line.progress_link == "csa"]
    if csa_lines and CSA_BOQ_REF not in refs:
        boq_svc = BOQService(session)
        csa = await boq_svc.create_boq(BOQCreate(project_id=project_id, name=ctx.csa_boq_name))
        csa_positions: dict[str, str] = {}
        for line in csa_lines:
            position = await boq_svc.add_position(
                PositionCreate(
                    boq_id=csa.id,
                    ordinal=line.code,
                    description=line.description,
                    unit=line.unit,
                    quantity=1.0,
                    unit_rate=line.amount,
                    classification=dict(line.metadata.classification),
                )
            )
            csa_positions[line.code] = str(position.id)
        refs[CSA_BOQ_REF] = str(csa.id)
        refs[f"{CSA_BOQ_REF}.positions"] = csa_positions
    csa_map: dict[str, str] = refs.get(f"{CSA_BOQ_REF}.positions", {})
    main_positions: dict[str, str] = refs.get(f"{MAIN_BOQ_REF}.positions", {})
    for line in sov:
        link = line.progress_link or "none"
        if link == "csa":
            position_links[line.code] = csa_map[line.code]
        elif link.startswith("boq:"):
            ordinal = link.removeprefix("boq:")
            if ordinal not in main_positions:
                raise _fail(step, f"SOV line {line.code} links {link}, which the main bill does not hold")
            position_links[line.code] = main_positions[ordinal]

    metadata: dict[str, Any] = {}
    if spec_contract.vat_rate_percent is not None:
        # Finance reads this as a PERCENT and reads an object as 0 without an
        # error, so it is written as a plain number (decisions 14 and 18).
        metadata["einvoice"] = {"vat_rate": _json_number(spec_contract.vat_rate_percent)}
    total = (
        spec_contract.value.value
        if spec_contract.value.value is not None
        else sum((line.amount for line in sov), Decimal(0))
    )
    svc = ContractsService(session)
    contract = await svc.create_contract(
        ContractCreate(
            # Contract codes are unique across the database.
            code=f"TRN-{ctx.code_suffix}",
            title=spec_contract.title,
            contract_type=spec_contract.contract_type or "lump_sum",
            counterparty_type="client",
            project_id=project_id,
            start_date=spec_contract.start_date,
            total_value=total,
            currency=spec_contract.currency or course.currency,
            retention_percent=spec_contract.retention_as_percent,
            metadata=metadata,
        ),
        user_id=ctx.actor,
    )
    items = []
    for i, line in enumerate(sov):
        quantity = line.quantity if line.quantity is not None else Decimal(1)
        rate = sov_line_rate(line)
        if rate is None:
            raise _fail(step, f"SOV line {line.code}: amount is not quantity x a rate the ERP stores")
        line_meta: dict[str, Any] = {"classification": dict(line.metadata.classification)}
        if line.code in position_links:
            line_meta[BOQ_POSITION_META_KEY] = position_links[line.code]
        items.append(
            ContractLineCreate(
                contract_id=contract.id,
                code=line.code,
                description=line.description,
                unit=line.unit,
                quantity=quantity,
                unit_rate=rate,
                order_index=i,
                metadata=line_meta,
            )
        )
    created = await svc.bulk_create_lines(contract.id, items)
    # Signing: compliance gate, frozen original_contract_value, retention
    # schedule, ``contracts.contract.signed``.
    await svc.transition_contract(contract.id, "active", actor_id=ctx.actor)
    refs[CONTRACT_REF] = str(contract.id)
    refs[f"{CONTRACT_REF}.lines"] = {row.code: str(row.id) for row in created}
    refs[f"{CONTRACT_REF}.position_links"] = position_links


async def _seed_progress_readings(
    session: AsyncSession, step: SeedStep, course: CourseSpec, ctx: SeedContext, refs: Refs
) -> None:
    from app.modules.progress.models import ProgressEntry

    if step.index is None:
        raise _fail(step, "a readings step needs its entry index")
    entry = course.seed.progress_readings[step.index]
    project_id = _ref_id(refs, PROJECT_REF, step)
    links = refs.get(f"{CONTRACT_REF}.position_links")
    if not isinstance(links, dict):
        raise _fail(step, f"{CONTRACT_REF} has not been seeded yet")
    recorded_at = reading_timestamp(entry.period_from, entry.period_to)
    earliest, latest = period_window(entry.period_from, entry.period_to)
    if not earliest <= recorded_at <= latest:  # R16: never outside the claim period
        raise _fail(step, f"recorded_at {recorded_at.isoformat()} falls outside the period")
    created: dict[str, str] = {}
    for reading in entry.readings:
        percent = reading.percent_complete
        if not Decimal(0) <= percent <= Decimal(100):  # R16: the ERP's 0-100 scale
            raise _fail(step, f"line {reading.line_code}: percent_complete {percent} is outside 0-100")
        position_id = links.get(reading.line_code)
        if position_id is None:
            raise _fail(step, f"line {reading.line_code} links to no bill position")
        row = ProgressEntry(
            project_id=project_id,
            boq_position_id=uuid.UUID(position_id),
            period_label=entry.period_to.strftime("%Y-%m"),
            percent_complete=percent,
            recorded_by=ctx.actor,
            recorded_at=recorded_at,
            metadata_={"trainer_seed": True},
        )
        session.add(row)
        # One flush per row: ``seq`` is assigned at INSERT, and the populate
        # reads the highest ``seq`` as the latest reading.
        await session.flush()
        created[reading.line_code] = str(row.id)
    refs[step.ref_key] = created


async def _seed_variation_request(
    session: AsyncSession, step: SeedStep, course: CourseSpec, ctx: SeedContext, refs: Refs
) -> None:
    from app.modules.variations.schemas import VariationRequestCreate
    from app.modules.variations.service import VariationsService

    if step.index is None:
        raise _fail(step, "a variation step needs its entry index")
    request = course.seed.variations[step.index].erp_request
    if request is None:
        raise _fail(step, "the variation carries no erp_request")
    project_id = _ref_id(refs, PROJECT_REF, step)
    row = await VariationsService(session).create_request(
        VariationRequestCreate(
            project_id=project_id,
            title=request.title,
            description=request.description or "",
            currency=course.currency,
            contract_clause_ref=request.contract_clause_ref or "",
            status="draft",
        ),
        user_id=ctx.actor,
    )
    refs[step.ref_key] = str(row.id)


_EXECUTORS: dict[str, _Executor] = {
    "project": _seed_project,
    "boq": _seed_boq,
    "markups": _seed_markups,
    "bid_package": _seed_bid_package,
    "contract": _seed_contract,
    "progress_readings": _seed_progress_readings,
    "variation_request": _seed_variation_request,
}


__all__ = [
    "BIDDER_EMAIL_DOMAIN",
    "DEFAULT_CSA_BOQ_NAME",
    "SeedContext",
    "SeedError",
    "execute_enrolment",
    "execute_stage",
    "seeding",
    "seeding_enrolment",
]
