# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The seed plan: a course spec turned into ordered steps per stage. Pure.

Nothing here touches the database. :func:`build_plan` reads a validated
:class:`~app.modules.trainer.spec.CourseSpec` (or the stored spec dict, which it
validates first) and returns a :class:`SeedPlan`: one :class:`SeedStep` per ERP
object group, each with the stage it runs at (decision 12: ``on_enrol`` or
``on_unlock(<task number>)``) and the ``seeded_refs`` key that marks it done.

Order inside a stage follows the dependencies between the objects: project,
main bill, its markups, bid package, contract (with the contract-sum-analysis
bill it links to), progress readings, variation requests. Readings run in
period order across the whole plan, because the claim populate picks the
reading with the highest ``seq`` and ``seq`` follows insertion order.

The plan also checks what the shape gate cannot see, the cross references
between seed blocks, and raises :class:`PlanError` with every problem at once:
a reading on a line that links to no bill position, a contract seeded before
the bill it links to, a markup before its bill, a stage naming a task that does
not exist.

Seeded refs (decision 10 and the ``seeded_refs`` column of
``oe_trainer_enrolment``). The keys the probes read hold one id as a string:
``project``, ``boq.main``, ``boq.csa``, ``bid_package.main``,
``contract.main``, ``progress.<n>`` (n-th entry of ``seed.progress_readings``,
1-based) and ``variation_request.<n>``. The groups each step creates are kept
beside them as ``{natural key: id}`` maps, see :data:`GROUP_REF_KEYS`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, Inexact, localcontext
from typing import Any, Literal

from app.modules.trainer.spec import (
    CONTRACT_REF,
    MAIN_BOQ_REF,
    PACKAGE_REF,
    BidPackageSeed,
    BidSeed,
    BoqSeed,
    ContractSeed,
    CourseSpec,
    SectionSeed,
    SovLineSeed,
    Stage,
    parse_stage,
)

StepKind = Literal[
    "project",
    "boq",
    "markups",
    "bid_package",
    "contract",
    "progress_readings",
    "variation_request",
]

#: Order of the step kinds inside one stage (dependencies first).
STEP_ORDER: tuple[StepKind, ...] = (
    "project",
    "boq",
    "markups",
    "bid_package",
    "contract",
    "progress_readings",
    "variation_request",
)

PROJECT_REF = "project"
CSA_BOQ_REF = "boq.csa"

#: The ``{natural key: id}`` maps a step records beside its main ref.
GROUP_REF_KEYS: dict[str, str] = {
    "boq.main.sections": "section ordinal -> position id of the section row",
    "boq.main.positions": "position ordinal -> position id",
    "boq.main.markups.<stage>": "markup name -> markup id, per stage",
    "bid_package.main.lines": "scope line code -> package line item id",
    "bid_package.main.bidders": "bidder name -> bidder id",
    "bid_package.main.invitations": "bidder name -> invitation id (the learner records its own bid on it)",
    "bid_package.main.submissions": "bidder name -> submission id, bids the seed records only",
    "boq.csa.positions": "SOV line code -> contract-sum-analysis position id",
    "contract.main.lines": "SOV line code -> contract line id",
    "contract.main.position_links": "SOV line code -> the bill position its progress is read from",
    "progress.<n>": "SOV line code -> progress entry id",
}

#: Ordinal of the one lump-sum position seeded for a section that states a
#: single priced ``line`` and its ``amount`` (US subcontract quotes). The
#: course names no ordinal for it and no probe reads it by ordinal.
SECTION_LINE_SUFFIX = ".1"

#: Default time of day of a seeded reading (decision 20).
READING_TIME = time(12, 0, tzinfo=UTC)


class PlanError(ValueError):
    """A course whose seed blocks contradict each other.

    Attributes:
        problems: Every problem found, one sentence each.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True, slots=True)
class SeedStep:
    """One group of ERP objects the seeder writes.

    Attributes:
        kind: What the step writes.
        stage: When it runs.
        ref_key: The ``seeded_refs`` key that marks the step done; a step whose
            key is already set is skipped, which makes a stage idempotent.
        index: Position of the source entry in ``seed.progress_readings`` or
            ``seed.variations``; ``None`` for the single blocks.
    """

    kind: StepKind
    stage: Stage
    ref_key: str
    index: int | None = None


@dataclass(frozen=True, slots=True)
class SeedPlan:
    """The ordered steps of one course."""

    course: CourseSpec
    steps: tuple[SeedStep, ...] = field(default_factory=tuple)

    def for_stage(self, stage: Stage) -> list[SeedStep]:
        """The steps that run at ``stage``, in execution order."""
        return [s for s in self.steps if s.stage == stage]

    @property
    def stages(self) -> tuple[Stage, ...]:
        """Every stage that has at least one step, in execution order."""
        seen: list[Stage] = []
        for step in self.steps:
            if step.stage not in seen:
                seen.append(step.stage)
        return tuple(seen)


def stage_rank(stage: Stage) -> int:
    """Sort key of a stage: ``on_enrol`` is 0, ``on_unlock(n)`` is ``n``."""
    return 0 if stage.kind == "on_enrol" else int(stage.task_n or 0)


def stage_key(stage: Stage) -> str:
    """The spec spelling of a stage, e.g. ``on_unlock(3)``."""
    return "on_enrol" if stage.kind == "on_enrol" else f"on_unlock({stage.task_n})"


#: The stages that run when an enrolment starts: task 1 is unlocked at once.
ENROLMENT_STAGES: tuple[Stage, ...] = (Stage("on_enrol"), Stage("on_unlock", 1))


def reading_timestamp(period_from: date, period_to: date) -> datetime:
    """When a seeded reading is stamped (decision 20).

    ``period_to`` minus one day at 12:00 UTC; for a one-day period, that day at
    12:00 UTC. Always inside ``[period_from 00:00, period_to 23:59:59.999999]``
    UTC, the window the claim populate reads.
    """
    day = period_to - timedelta(days=1)
    if day < period_from:
        day = period_to
    return datetime.combine(day, READING_TIME)


def period_window(period_from: date, period_to: date) -> tuple[datetime, datetime]:
    """The UTC instants a reading of this period may carry, both inclusive."""
    return datetime.combine(period_from, time.min, tzinfo=UTC), datetime.combine(period_to, time.max, tzinfo=UTC)


def section_line_ordinal(section: SectionSeed) -> str:
    """Ordinal of the lump-sum position seeded for a section's single ``line``."""
    return f"{section.ordinal}{SECTION_LINE_SUFFIX}"


def seeded_position_ordinals(spec: CourseSpec) -> list[str]:
    """Every priced position ordinal the main bill gets, sections excluded."""
    boq = spec.seed.boq
    if boq is None:
        return []
    ordinals: list[str] = []
    for section in boq.sections:
        if section.lines:
            ordinals.extend(line.code for line in section.lines)
        elif section.line is not None and section.amount is not None:
            ordinals.append(section_line_ordinal(section))
    ordinals.extend(p.code for p in boq.positions)
    return ordinals


#: Scale of ``oe_contracts_contract_line.quantity`` and ``unit_rate``.
LINE_SCALE = Decimal("0.0001")


def sov_line_rate(line: SovLineSeed) -> Decimal | None:
    """The unit rate an SOV line is written with, or ``None`` when none fits.

    The quantity defaults to 1. The rate must be exact at the column's four
    decimals, so the line total the ERP computes equals the spec amount.
    """
    quantity = line.quantity if line.quantity is not None else Decimal(1)
    # A private context: the thread's default precision (28, or whatever a
    # library set) must not round the product back onto the amount.
    with localcontext() as exact:
        exact.prec = 60
        exact.traps[Inexact] = False
        if quantity <= 0 or quantity != quantity.quantize(LINE_SCALE):
            return None
        rate = (line.amount / quantity).quantize(LINE_SCALE)
        return rate if rate * quantity == line.amount else None


def bid_recorded_by_seed(bid: BidSeed) -> bool:
    """Whether the seeder records this bid, or leaves it to the learner.

    ``recorded_by`` is prose in the course files ("seed (API, while
    published)", "learner in T3 (Record bid)", "Lernende in T3 ..."). A value
    that starts with ``seed`` (any case), or no value, means the seeder records
    it; anything else names the learner, who records it in the task.
    """
    return bid.recorded_by is None or bid.recorded_by.strip().casefold().startswith("seed")


def _as_spec(spec: CourseSpec | Mapping[str, Any]) -> CourseSpec:
    if isinstance(spec, CourseSpec):
        return spec
    return CourseSpec.model_validate(dict(spec))


def build_plan(spec: CourseSpec | Mapping[str, Any]) -> SeedPlan:
    """Turn a course spec into its ordered seed steps.

    Args:
        spec: A validated course, or the stored spec dict
            (``CourseSpec.dump_for_storage()``), which is validated here.

    Returns:
        The plan.

    Raises:
        PlanError: the seed blocks contradict each other.
        pydantic.ValidationError: ``spec`` is a dict that fails the shape.
    """
    course = _as_spec(spec)
    seed = course.seed
    task_numbers = {t.n for t in course.tasks}
    problems: list[str] = []
    steps: list[SeedStep] = []

    def staged(stage_text: str, where: str) -> Stage:
        stage = parse_stage(stage_text)
        if stage.kind == "on_unlock" and stage.task_n not in task_numbers:
            problems.append(f"{where}: stage {stage_text} names task {stage.task_n}, which the course does not have")
        return stage

    # Project: everything else lives inside it, so it is seeded at enrolment.
    project_stage = staged(seed.project.stage, "seed.project")
    if project_stage.kind != "on_enrol":
        problems.append("seed.project: the project must be seeded on_enrol; every other object lives inside it")
    steps.append(SeedStep("project", project_stage, PROJECT_REF))

    # Main bill and its markups.
    boq_stage: Stage | None = None
    position_ordinals: set[str] = set()
    if seed.boq is not None:
        boq_stage = staged(seed.boq.stage, "seed.boq")
        steps.append(SeedStep("boq", boq_stage, MAIN_BOQ_REF))
        problems.extend(_boq_problems(course, seed.boq))
        position_ordinals = set(seeded_position_ordinals(course))
        markup_stages: list[Stage] = []
        for i, markup in enumerate(seed.boq.markups):
            m_stage = staged(markup.stage, f"seed.boq.markups[{i}]") if markup.stage else boq_stage
            if stage_rank(m_stage) < stage_rank(boq_stage):
                problems.append(
                    f"seed.boq.markups[{i}] ({markup.name}): stage {stage_key(m_stage)} runs before the bill "
                    f"it belongs to ({stage_key(boq_stage)})"
                )
            if m_stage not in markup_stages:
                markup_stages.append(m_stage)
        for m_stage in markup_stages:
            steps.append(SeedStep("markups", m_stage, f"{MAIN_BOQ_REF}.markups.{stage_key(m_stage)}"))

    # Bid package.
    if seed.bid_package is not None:
        pkg_stage = staged(seed.bid_package.stage, "seed.bid_package")
        steps.append(SeedStep("bid_package", pkg_stage, PACKAGE_REF))
        problems.extend(_bid_package_problems(seed.bid_package))
        for scope in seed.bid_package.scope_lines:
            if scope.boq_position is None:
                continue
            if boq_stage is None or scope.boq_position not in position_ordinals:
                problems.append(
                    f"seed.bid_package.scope_lines[{scope.code}]: boq_position {scope.boq_position} "
                    "names no seeded bill position"
                )
            elif stage_rank(boq_stage) > stage_rank(pkg_stage):
                problems.append(
                    f"seed.bid_package.scope_lines[{scope.code}]: the package is seeded before the bill it links to"
                )

    # Contract, and the bill positions its lines are read through.
    contract_stage: Stage | None = None
    line_links: dict[str, str | None] = {}
    if seed.contract is not None:
        contract_stage = staged(seed.contract.stage, "seed.contract")
        steps.append(SeedStep("contract", contract_stage, CONTRACT_REF))
        problems.extend(_contract_problems(seed.contract))
        for line in seed.contract.schedule_of_values:
            line_links[line.code] = line.progress_link
            link = line.progress_link or "none"
            if link.startswith("boq:"):
                ordinal = link.removeprefix("boq:")
                if seed.boq is None or boq_stage is None:
                    problems.append(f"SOV line {line.code}: progress_link {link} but the course seeds no main bill")
                    continue
                if ordinal not in position_ordinals:
                    problems.append(f"SOV line {line.code}: progress_link {link} names no seeded bill position")
                if stage_rank(boq_stage) > stage_rank(contract_stage):
                    problems.append(
                        f"SOV line {line.code}: the contract ({stage_key(contract_stage)}) is seeded before "
                        f"the bill it links to ({stage_key(boq_stage)})"
                    )

    # Progress readings: after the contract, in period order.
    readings_steps: list[tuple[int, date, SeedStep]] = []
    for i, entry in enumerate(seed.progress_readings):
        where = f"seed.progress_readings[{i}]"
        r_stage = staged(entry.stage, where)
        readings_steps.append((i, entry.period_to, SeedStep("progress_readings", r_stage, f"progress.{i + 1}", i)))
        if contract_stage is None:
            problems.append(f"{where}: readings are seeded but the course seeds no contract")
        elif stage_rank(r_stage) < stage_rank(contract_stage):
            problems.append(
                f"{where}: stage {stage_key(r_stage)} runs before the contract ({stage_key(contract_stage)})"
            )
        seen_lines: set[str] = set()
        for reading in entry.readings:
            code = reading.line_code
            if code in seen_lines:
                problems.append(f"{where}: line {code} is read twice in one period")
            seen_lines.add(code)
            if not Decimal(0) <= reading.percent_complete <= Decimal(100):
                problems.append(f"{where}: line {code} percent_complete {reading.percent_complete} is outside 0-100")
            if contract_stage is None:
                continue
            if code not in line_links:
                problems.append(f"{where}: line {code} is not a line of the schedule of values")
                continue
            link = line_links[code] or "none"
            if link == "none":
                problems.append(
                    f"{where}: line {code} has progress_link none, so the claim populate could never read "
                    "this reading; enter it by hand (by_hand) or link the line (csa or boq:<ordinal>)"
                )
    # Stable by stage, then by period end, then by file order: seq must follow time.
    readings_steps.sort(key=lambda item: (stage_rank(item[2].stage), item[1], item[0]))
    for (_, prev_to, prev), (_, next_to, nxt) in zip(readings_steps, readings_steps[1:], strict=False):
        if next_to < prev_to:
            problems.append(
                f"seed.progress_readings[{nxt.index}] (period to {next_to}) is seeded after "
                f"seed.progress_readings[{prev.index}] (period to {prev_to}); a later reading must cover "
                "a later period, because the populate takes the latest-inserted reading"
            )
    steps.extend(step for _, _, step in readings_steps)

    # Variation requests: only where the course asks the ERP for one.
    for i, variation in enumerate(seed.variations):
        v_stage = staged(variation.stage, f"seed.variations[{i}]")
        if variation.erp_request is not None:
            steps.append(SeedStep("variation_request", v_stage, f"variation_request.{i + 1}", i))

    if problems:
        raise PlanError(problems)

    order = {kind: n for n, kind in enumerate(STEP_ORDER)}
    # ``sorted`` is stable, so readings keep the period order set above.
    ordered = sorted(steps, key=lambda s: (stage_rank(s.stage), order[s.kind]))
    return SeedPlan(course=course, steps=tuple(ordered))


def _boq_problems(course: CourseSpec, boq: BoqSeed) -> list[str]:
    problems: list[str] = []
    section_ordinals = [s.ordinal for s in boq.sections]
    if len(set(section_ordinals)) != len(section_ordinals):
        problems.append("seed.boq.sections: two sections share an ordinal")
    for section in boq.sections:
        if not section.lines and section.line is not None and section.amount is not None and not section.unit:
            problems.append(f"seed.boq.sections[{section.ordinal}]: a priced line needs a unit")
    ordinals = seeded_position_ordinals(course)
    duplicates = sorted({o for o in ordinals if ordinals.count(o) > 1})
    if duplicates:
        problems.append(f"seed.boq: position ordinals {duplicates} are not unique")
    clash = sorted(set(ordinals) & set(section_ordinals))
    if clash:
        problems.append(f"seed.boq: ordinals {clash} name both a section and a position")
    for position in boq.positions:
        if position.section is not None and position.section not in section_ordinals:
            problems.append(f"seed.boq.positions[{position.code}]: section {position.section} is not declared")
        if position.qty < 0:
            problems.append(f"seed.boq.positions[{position.code}]: quantity is negative")
    return problems


def _bid_package_problems(pkg: BidPackageSeed) -> list[str]:
    problems: list[str] = []
    codes = [s.code for s in pkg.scope_lines]
    if len(set(codes)) != len(codes):
        problems.append("seed.bid_package.scope_lines: two lines share a code")
    names = [b.bidder for b in pkg.bids]
    if len(set(names)) != len(names):
        problems.append("seed.bid_package.bids: two bids name the same bidder")
    for bid in pkg.bids:
        for line in bid.lines:
            if line.code not in codes:
                problems.append(f"seed.bid_package.bids[{bid.bidder}]: line {line.code} is not a scope line")
            if line.rate is not None and line.rate < 0:
                problems.append(f"seed.bid_package.bids[{bid.bidder}]: line {line.code} has a negative rate")
    return problems


def _contract_problems(contract: ContractSeed) -> list[str]:
    problems: list[str] = []
    codes = [line.code for line in contract.schedule_of_values]
    if len(set(codes)) != len(codes):
        problems.append("seed.contract.schedule_of_values: two lines share a code")
    total = sum((line.amount for line in contract.schedule_of_values), Decimal(0))
    if contract.value.value is not None and contract.value.value != total:
        problems.append(
            f"seed.contract: the schedule of values sums to {total}, the contract value is {contract.value.value}"
        )
    retention = contract.retention_as_percent
    if not Decimal(0) <= retention <= Decimal(100) or retention != retention.quantize(Decimal("0.01")):
        problems.append(
            f"seed.contract: retention {retention} percent does not fit the ERP column (0-100, two decimals)"
        )
    vat = contract.vat_rate_percent
    if vat is not None and not Decimal(0) <= vat <= Decimal(100):
        problems.append(f"seed.contract: vat_rate_percent {vat} is outside 0-100")
    links: dict[str, str] = {}
    for line in contract.schedule_of_values:
        if not line.unit.strip():
            problems.append(f"SOV line {line.code}: unit is empty; signing refuses it")
        if not line.metadata.classification:
            problems.append(f"SOV line {line.code}: metadata.classification is empty; signing refuses it")
        if sov_line_rate(line) is None:
            problems.append(
                f"SOV line {line.code}: amount {line.amount} is not a positive quantity times a rate "
                "the ERP stores (four decimals)"
            )
        link = line.progress_link or "none"
        if link.startswith("boq:"):
            other = links.get(link)
            if other is not None:
                problems.append(f"SOV lines {other} and {line.code} read progress from the same bill position ({link})")
            links[link] = line.code
    return problems


__all__ = [
    "CSA_BOQ_REF",
    "CONTRACT_REF",
    "ENROLMENT_STAGES",
    "GROUP_REF_KEYS",
    "MAIN_BOQ_REF",
    "PACKAGE_REF",
    "PROJECT_REF",
    "STEP_ORDER",
    "PlanError",
    "SeedPlan",
    "SeedStep",
    "StepKind",
    "bid_recorded_by_seed",
    "build_plan",
    "period_window",
    "reading_timestamp",
    "section_line_ordinal",
    "seeded_position_ordinals",
    "sov_line_rate",
    "stage_key",
    "stage_rank",
]
