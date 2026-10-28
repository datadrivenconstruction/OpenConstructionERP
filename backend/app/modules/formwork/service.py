# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Formwork business logic.

Centralises the reuse-aware rate build-up so every caller (router, import
wizard, BOQ rollup) shares one source of truth for what a formwork rate is:

    material unit cost = unit_rate * (1 + waste_pct/100) / reuse_count
    labour unit cost   = erect_strike_rate
    unit cost          = material + labour
    total              = area_m2 * unit cost

The two halves matter because only the first one amortises. Panels are bought
once and turned around ``reuse_count`` times; the labour and consumables to
set and strike them are paid on every one of those turnarounds.

``rate_basis`` decides whether the first line amortises at all: a purchase
rate is divided by the reuses, a per-use hire rate and an all-in subcontract
rate are already per-use and are not divided again.

Five things follow from that, and this module owns all five:

* choosing the system is the decision the module exists to support, so every
  candidate is priced against one set of assumptions by one function
  (:meth:`FormworkService.compare_systems`) rather than by whatever arithmetic
  a client happens to implement;
* a priced assignment can leave for the bill
  (:meth:`FormworkService.push_assignment_to_boq`), because a calculation that
  never reaches the tender is a calculator, not a module;
* a catalogue rate change re-prices every assignment that depends on it
  (:meth:`FormworkService.reprice_for_system`), because a stored total that no
  longer matches its own catalogue row is worse than no total at all;
* the pour schedule, not the estimator's memory, decides how many reuses the
  programme actually delivers (:meth:`FormworkService.analyse_cycle`);
* every assignment can be validated against the ``formwork`` rule set before
  its rate reaches the bill (:meth:`FormworkService.validate_assignment`).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.formwork.models import (
    FormworkAssignment,
    FormworkScheduleLine,
    FormworkSystem,
)
from app.modules.formwork.repository import (
    FormworkAssignmentRepository,
    FormworkScheduleLineRepository,
    FormworkSystemRepository,
)
from app.modules.formwork.schemas import (
    FormworkAssignmentCreate,
    FormworkAssignmentUpdate,
    FormworkBoqPushRequest,
    FormworkBoqPushResult,
    FormworkCompareCandidate,
    FormworkCompareRequest,
    FormworkCompareResult,
    FormworkCycleAnalysis,
    FormworkCycleConflict,
    FormworkProjectSummary,
    FormworkRepriceResult,
    FormworkScheduleLineCreate,
    FormworkScheduleLineUpdate,
    FormworkSystemCreate,
    FormworkSystemUpdate,
    FormworkSystemUsage,
    FormworkTypeBreakdown,
    FormworkValidationReport,
    default_seed_systems,
)
from app.modules.formwork.validators import evaluate_assignment, evaluate_project

_TWO_DP = Decimal("0.01")

# Rate bases whose ``unit_rate`` is quoted per use and therefore does NOT
# amortise over the reuse count. Everything not in here is treated as a
# purchase rate, which is the historical behaviour and the safe fallback.
_PER_USE_BASES = frozenset({"hire_per_use", "subcontract"})

# Fields on FormworkSystem that are nullable in the database. Anything else
# rejects an explicit ``null`` instead of writing one and failing at flush.
_NULLABLE_SYSTEM_FIELDS = frozenset({"supplier", "notes", "typical_reuses"})
_NULLABLE_ASSIGNMENT_FIELDS = frozenset({"boq_position_id", "notes"})
_NULLABLE_SCHEDULE_FIELDS = frozenset({"pour_date", "notes"})


class ReuseCountExceedsMaxError(ValueError):
    """Raised when an assignment's ``reuse_count`` exceeds the system cap.

    A formwork system carries a manufacturer reuse limit (``reuses_max``).
    Pricing an assignment with more reuses than the panels physically
    survive would understate the unit cost, so the service rejects it
    instead of silently producing a too-cheap figure.
    """

    def __init__(self, reuse_count: int, reuses_max: int) -> None:
        self.reuse_count = reuse_count
        self.reuses_max = reuses_max
        super().__init__(
            f"reuse_count {reuse_count} exceeds the system reuses_max {reuses_max}",
        )


class BoqProjectMismatchError(ValueError):
    """Raised when a push names a bill belonging to a different project.

    The caller supplies the target bill by id, so nothing but this check stops
    a formwork line priced on one project from landing in another project's
    tender. Refusing by name beats a foreign-key error the caller cannot act
    on, because there is deliberately no FK from the assignment to the bill.
    """

    def __init__(self, boq_id: uuid.UUID, project_id: uuid.UUID) -> None:
        self.boq_id = boq_id
        self.project_id = project_id
        super().__init__(f"BOQ {boq_id} does not belong to project {project_id}")


class OrdinalSpaceExhaustedError(RuntimeError):
    """Raised when no free ``FW.nn`` ordinal is left in the target bill.

    Only reachable with hundreds of formwork positions already in one bill, at
    which point the numbering scheme is the wrong shape and the estimator
    should be told so rather than served a thousand-iteration loop.
    """

    def __init__(self, boq_id: uuid.UUID) -> None:
        self.boq_id = boq_id
        super().__init__(f"no free formwork ordinal left in BOQ {boq_id}")


class FieldNotNullableError(ValueError):
    """Raised when a patch sends an explicit ``null`` for a NOT NULL column.

    The update schemas type every patchable field as optional so an omitted
    field can be told apart from a supplied one. That makes ``{"name": null}``
    parseable, but the column is NOT NULL, so writing it would fail at flush
    with a database integrity error the caller cannot act on. Rejecting it here
    names the field instead.
    """

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"field '{field}' cannot be set to null")


def _q(v: Decimal) -> Decimal:
    """Round to 2 dp, half away from zero.

    ROUND_HALF_UP, matching the rest of the money paths in the platform. Not
    banker's rounding - that is ROUND_HALF_EVEN, which this deliberately is
    not, because a rate that rounds 0.125 to 0.12 half the time is harder to
    reconcile against a supplier quote than one that always rounds up.
    """
    return Decimal(v).quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _patch_fields(
    data: Any,
    *,
    nullable: frozenset[str],
) -> dict[str, Any]:
    """Turn a partial-update model into the fields to write.

    ``exclude_unset`` keeps the distinction the schema exists for: an omitted
    field is untouched, an explicitly supplied one is written - including an
    explicit ``null``, which is the only way to clear a nullable column. A
    ``null`` aimed at a NOT NULL column is refused by name rather than left to
    fail as an integrity error at flush.
    """
    fields = data.model_dump(exclude_unset=True)
    for name, value in fields.items():
        if value is None and name not in nullable:
            raise FieldNotNullableError(name)
    return fields


class FormworkCost:
    """The four figures that make up one assignment's priced formwork.

    A small value object rather than a bare tuple: the caller reads
    ``cost.material``, not ``cost[1]``, and adding the labour split did not
    silently re-index every existing unpack site.
    """

    __slots__ = ("labour", "material", "total", "unit_cost")

    def __init__(
        self,
        *,
        unit_cost: Decimal,
        material: Decimal,
        labour: Decimal,
        total: Decimal,
    ) -> None:
        self.unit_cost = unit_cost
        self.material = material
        self.labour = labour
        self.total = total

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FormworkCost):
            return NotImplemented
        return (
            self.unit_cost == other.unit_cost
            and self.material == other.material
            and self.labour == other.labour
            and self.total == other.total
        )

    def __repr__(self) -> str:
        return (
            f"FormworkCost(unit_cost={self.unit_cost}, material={self.material}, "
            f"labour={self.labour}, total={self.total})"
        )


def compute_cost(
    *,
    unit_rate: Decimal,
    area_m2: Decimal,
    waste_pct: Decimal,
    reuse_count: int,
    erect_strike_rate: Decimal = Decimal("0"),
    rate_basis: str = "purchase",
) -> FormworkCost:
    """Return the full rate build-up for one assignment.

    Formula, on the default ``purchase`` basis:

        material = unit_rate * (1 + waste_pct/100) / reuse_count
        labour   = erect_strike_rate
        unit     = material + labour
        total    = area_m2 * unit

    Waste applies to the panel cost only. Over-ordering covers offcuts and
    damaged panels; it does not buy extra erect-and-strike labour, which is
    driven by the area formed and is paid on every reuse. That is why the
    labour component is NOT divided by ``reuse_count``: forming 1000 m2 with a
    100 m2 set means ten sets of erect-and-strike, not one.

    ``rate_basis`` decides whether the panel component amortises at all, and
    it is the only input that changes the shape of the formula:

    * ``purchase`` - the rate buys the panels. Divide by ``reuse_count``.
    * ``hire_per_use`` / ``subcontract`` - the rate is quoted PER USE already,
      so the divisor is 1:

          material = unit_rate * (1 + waste_pct/100)

      Dividing a per-use price by the reuse count would amortise a number that
      was never a capital cost, and the answer would fall as the estimator
      claimed more reuses even though the invoice does not. That is the whole
      reason this argument exists rather than being a label on the catalogue
      row. A monthly hire rate is a third model - it needs a duration on site,
      not a reuse count - and is deliberately NOT accepted here.

    An unrecognised basis falls back to ``purchase`` rather than raising: the
    schema pattern already rejects unknown values on the way in, and a stored
    row from a future revision should keep pricing the way it always did
    instead of taking a re-pricing sweep down with it.

    Every component is persisted and shown, so each is rounded to 2 dp before
    the next one uses it, and ``total`` is derived from the **rounded**
    ``unit_cost``. Otherwise ``area_m2 * computed_unit_cost`` recomputed
    client-side would not match the stored ``computed_total`` whenever the
    quotient carried fractional cents (unit_rate 65.00, waste 5 percent,
    reuse 2 gives 34.125, where area 100 stored 3412.50 against a displayed
    3413.00).

    ``reuse_count`` is guaranteed >= 1 by the schema; the clamp defends the
    import paths that bypass Pydantic.
    """
    reuses = max(int(reuse_count), 1)
    # A per-use rate is already the cost of one use, so nothing is amortised.
    divisor = Decimal(reuses) if rate_basis not in _PER_USE_BASES else Decimal("1")
    waste_factor = Decimal("1") + (Decimal(waste_pct) / Decimal("100"))
    material = _q((Decimal(unit_rate) * waste_factor) / divisor)
    labour = _q(Decimal(erect_strike_rate))
    unit_cost = _q(material + labour)
    total = _q(Decimal(area_m2) * unit_cost)
    return FormworkCost(unit_cost=unit_cost, material=material, labour=labour, total=total)


def single_use_cost(
    *,
    unit_rate: Decimal,
    area_m2: Decimal,
    waste_pct: Decimal,
    erect_strike_rate: Decimal = Decimal("0"),
    rate_basis: str = "purchase",
) -> Decimal:
    """What the same area costs if every pour needs brand-new panels.

    The counterfactual behind the reuse assumption. Subtracting the real total
    from this gives the money the reuse claim is worth, which is the figure a
    reviewer challenges first.

    On a per-use basis this equals the real total, and correctly so: nothing
    was amortised, so the reuse assumption was never worth anything. Reporting
    a saving there would credit the estimator with money the hire invoice does
    not give back.
    """
    return compute_cost(
        unit_rate=unit_rate,
        area_m2=area_m2,
        waste_pct=waste_pct,
        reuse_count=1,
        erect_strike_rate=erect_strike_rate,
        rate_basis=rate_basis,
    ).total


def derive_cycle(
    lines: list[FormworkScheduleLine],
    *,
    strip_time_days: int,
) -> dict[str, Any]:
    """Read the reuse economics out of a pour schedule.

    The panel set the contractor has to buy or hire is the LARGEST single
    pour, not the sum: every pour needs its own area formed at once, and the
    biggest one sizes the set. Forming ``total`` m2 with a ``peak`` m2 set
    turns that set around ``total / peak`` times.

    ``derived_reuse_count`` is the FLOOR of that ratio. Rounding up would
    divide the panel cost by a turnaround the programme does not deliver,
    which under-prices the job; rounding down is the conservative direction and
    the one an estimator can defend.

    Pours that carry dates are also checked against ``strip_time_days``: two
    consecutive pours closer together than the striking time cannot both be
    served by one set, because the panels are still holding the first pour.
    Undated pours are skipped rather than assumed - a cycle nobody has dated
    yet is not evidence of a clash.
    """
    # Tie-break on the id as a string: two lines can legitimately share a pour
    # number (that is what ``formwork.pour_numbers_unique`` reports), and a
    # not-yet-flushed line has ``id`` None, which is not orderable against
    # another None.
    ordered = sorted(lines, key=lambda line: (line.pour_no, str(line.id or "")))
    areas = [Decimal(line.area_m2 or 0) for line in ordered]
    total = sum(areas, Decimal("0"))
    peak = max(areas) if areas else Decimal("0")
    if peak > 0:
        ratio = total / peak
        derived = max(1, int(ratio))
    else:
        ratio = Decimal("0")
        derived = 0

    dated: list[tuple[int, date]] = [(line.pour_no, line.pour_date) for line in ordered if line.pour_date is not None]
    conflicts: list[FormworkCycleConflict] = []
    min_gap: int | None = None
    for (prev_no, prev_date), (next_no, next_date) in zip(dated, dated[1:], strict=False):
        gap = (next_date - prev_date).days
        min_gap = gap if min_gap is None else min(min_gap, gap)
        if gap < strip_time_days:
            conflicts.append(
                FormworkCycleConflict(
                    from_pour_no=prev_no,
                    to_pour_no=next_no,
                    gap_days=gap,
                    required_days=strip_time_days,
                ),
            )

    return {
        "pour_count": len(ordered),
        "total_pour_area_m2": _q(total),
        "peak_pour_area_m2": _q(peak),
        "reuse_ratio": _q(ratio),
        "derived_reuse_count": derived,
        "dated_pour_count": len(dated),
        "min_gap_days": min_gap,
        "conflicts": conflicts,
    }


class FormworkService:
    """Orchestration over the three formwork repositories.

    Owns the invariant that a stored ``computed_*`` figure always matches the
    catalogue row it was derived from. Every write path that can invalidate a
    price - assignment edits, catalogue rate changes, schedule-driven reuse
    changes - runs back through :func:`compute_cost` here rather than leaving a
    stale total behind.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.system_repo = FormworkSystemRepository(session)
        self.assignment_repo = FormworkAssignmentRepository(session)
        self.schedule_repo = FormworkScheduleLineRepository(session)

    # ── Systems ────────────────────────────────────────────────────────

    async def create_system(self, data: FormworkSystemCreate) -> FormworkSystem:
        obj = FormworkSystem(**data.model_dump())
        return await self.system_repo.create(obj)

    async def update_system(
        self,
        system_id: uuid.UUID,
        data: FormworkSystemUpdate,
    ) -> tuple[FormworkSystem | None, FormworkRepriceResult]:
        """Patch a catalogue system and re-price everything that depends on it.

        A catalogue rate is not a label, it is the input every assignment's
        stored total was computed from. Editing ``unit_rate``,
        ``erect_strike_rate`` or ``reuses_max`` and leaving the assignments
        alone would leave every project quoting a number its own catalogue no
        longer produces, which is the failure mode nobody notices until a
        reviewer recomputes one rate by hand.

        Returns the updated system and the re-pricing outcome, so the caller
        can tell the user how many projects just moved.
        """
        fields = _patch_fields(data, nullable=_NULLABLE_SYSTEM_FIELDS)
        if fields:
            await self.system_repo.update_fields(system_id, **fields)
        system = await self.system_repo.get_by_id(system_id)
        if system is None:
            return None, FormworkRepriceResult(examined=0, repriced=0, unchanged=0)
        reprice = await self.reprice_for_system(system)
        return system, reprice

    async def system_usage(self, system_id: uuid.UUID) -> FormworkSystemUsage:
        """How many priced assignments depend on one catalogue system."""
        usage = await self.assignment_repo.usage_for_system(system_id)
        return FormworkSystemUsage(
            system_id=system_id,
            assignment_count=usage["assignment_count"],
            project_count=usage["project_count"],
            total_area_m2=_q(Decimal(usage["total_area_m2"])),
            total_cost=_q(Decimal(usage["total_cost"])),
        )

    async def seed_defaults(
        self,
        *,
        tenant_id: uuid.UUID | None,
    ) -> dict[str, int]:
        """Idempotently insert the starter formwork catalogue.

        ``total_after`` is counted from the table after the insert rather than
        added to the number of distinct names seen beforehand: a name present
        both globally and tenant-scoped collapses in a name set, and the
        derived figure under-reported the catalogue by every such duplicate.
        """
        already = await self.system_repo.list_names_for_tenant(tenant_id)
        inserted = 0
        skipped = 0
        for row in default_seed_systems():
            if row["name"] in already:
                skipped += 1
                continue
            obj = FormworkSystem(tenant_id=tenant_id, **row)
            self.session.add(obj)
            inserted += 1
        await self.session.flush()
        total = await self.system_repo.count_visible(tenant_id)
        return {"inserted": inserted, "skipped": skipped, "total_after": total}

    # ── Assignments ────────────────────────────────────────────────────

    def _apply_cost(
        self,
        assignment: FormworkAssignment,
        system: FormworkSystem,
    ) -> FormworkCost:
        """Recompute and write the four cost columns onto an assignment."""
        cost = compute_cost(
            unit_rate=system.unit_rate,
            area_m2=assignment.area_m2,
            waste_pct=assignment.waste_pct,
            reuse_count=assignment.reuse_count,
            erect_strike_rate=system.erect_strike_rate,
            rate_basis=system.rate_basis,
        )
        assignment.computed_unit_cost = cost.unit_cost
        assignment.material_unit_cost = cost.material
        assignment.labour_unit_cost = cost.labour
        assignment.computed_total = cost.total
        return cost

    async def _free_ordinal(self, boq_service: Any, boq_id: uuid.UUID) -> str:
        """Return an ordinal not already used in ``boq_id``.

        ``add_position`` raises 409 on a collision rather than resolving it,
        and ``bulk_add_positions`` rejects the whole batch, so the caller owns
        the allocation. The ``FW.nn`` prefix groups every formwork line the
        module contributes and stays readable in an exported bill.

        The probe is bounded: at a thousand formwork lines in one bill the
        assumption behind the prefix has broken down, and looping forever
        while holding a transaction open is the worse failure.
        """
        for n in range(1, 1000):
            candidate = f"FW.{n:02d}"
            if not await boq_service.position_repo.ordinal_exists(boq_id, candidate):
                return candidate
        raise OrdinalSpaceExhaustedError(boq_id)

    async def push_assignment_to_boq(
        self,
        assignment_id: uuid.UUID,
        data: FormworkBoqPushRequest,
        *,
        # ``CurrentUserId`` resolves to a ``str``, and the BOQ router hands its
        # own ``update_position`` the same string, so this is the established
        # shape rather than a missing conversion. Annotated honestly instead of
        # claiming a UUID nothing on this path actually produces.
        actor_id: uuid.UUID | str | None = None,
    ) -> FormworkBoqPushResult:
        """Write one priced assignment into a bill of quantities.

        A formwork calculation whose result never reaches the bill is a
        calculator, not a module. This is the exit: the assignment's contact
        area becomes the position quantity, its reuse-aware unit cost becomes
        the position rate, and ``source="formwork"`` records where the number
        came from so a reviewer can trace the rate back to the system, the
        reuse count and the waste allowance that produced it.

        Pushing twice does NOT bill the same formwork twice. The assignment
        remembers the position it created in ``boq_position_id``; a second
        push re-prices that position in place and reports ``created=False``.
        That matters because re-pricing is the normal case - the estimator
        changes the system or the reuse count and pushes again - and an
        endpoint that appended every time would quietly double a concrete
        frame's biggest single cost.

        The target bill is named explicitly. A project can carry several bills
        (there is no unique constraint on ``oe_boq_boq.project_id``), and the
        one the estimator meant is not derivable from the assignment.
        """
        from app.modules.boq.schemas import PositionCreate, PositionUpdate  # noqa: PLC0415
        from app.modules.boq.service import BOQService  # noqa: PLC0415

        assignment = await self.assignment_repo.get_with_system(assignment_id)
        if assignment is None:
            raise LookupError("assignment_not_found")
        system = assignment.system

        boq_service = BOQService(self.session)
        # Raises 404 when the bill does not exist. Checking that it belongs to
        # the assignment's project is the point: without it, a caller could
        # post a formwork line from project A into project B's tender.
        boq = await boq_service.get_boq(data.boq_id)
        if boq.project_id != assignment.project_id:
            raise BoqProjectMismatchError(data.boq_id, assignment.project_id)

        description = data.description or (
            f"Formwork to {system.system_type}, {system.name}, {assignment.reuse_count} use(s)"
        )
        quantity = Decimal(assignment.area_m2 or 0)
        unit_rate = Decimal(assignment.computed_unit_cost or 0)

        existing = None
        if assignment.boq_position_id is not None:
            existing = await boq_service.position_repo.get_by_id(assignment.boq_position_id)
            # A position deleted out from under the link is not an error: the
            # link is deliberately loose (no FK), so the honest response is to
            # write a fresh line rather than to fail.
            if existing is not None and existing.boq_id != data.boq_id:
                existing = None

        if existing is not None:
            updated = await boq_service.update_position(
                existing.id,
                PositionUpdate(
                    description=description,
                    quantity=float(quantity),
                    unit_rate=unit_rate,
                ),
                actor_id=actor_id,
            )
            return FormworkBoqPushResult(
                assignment_id=assignment.id,
                boq_id=data.boq_id,
                boq_position_id=updated.id,
                ordinal=updated.ordinal,
                quantity=quantity,
                unit_rate=unit_rate,
                total=_q(quantity * unit_rate),
                created=False,
            )

        ordinal = await self._free_ordinal(boq_service, data.boq_id)
        position = await boq_service.add_position(
            PositionCreate(
                boq_id=data.boq_id,
                parent_id=data.parent_id,
                ordinal=ordinal,
                description=description,
                # Formwork is priced per square metre of CONTACT AREA - the
                # face the concrete touches - which is what ``area_m2`` holds.
                unit="m2",
                quantity=float(quantity),
                unit_rate=unit_rate,
                source="formwork",
            )
        )
        await self.assignment_repo.update_fields(
            assignment.id,
            boq_position_id=position.id,
        )
        return FormworkBoqPushResult(
            assignment_id=assignment.id,
            boq_id=data.boq_id,
            boq_position_id=position.id,
            ordinal=position.ordinal,
            quantity=quantity,
            unit_rate=unit_rate,
            total=_q(quantity * unit_rate),
            created=True,
        )

    async def compare_systems(
        self,
        data: FormworkCompareRequest,
        *,
        tenant_id: uuid.UUID | None = None,
    ) -> FormworkCompareResult:
        """Price one area in every candidate system, on one set of assumptions.

        This is the method the whole module exists to serve. The same wall in a
        different system has a different rate and a different cycle, so
        "which system" is the estimator's actual decision - and a decision
        cannot be made against a list of names, only against numbers computed
        the same way for every option.

        Every candidate is priced at the SAME ``reuse_count``. Pricing each
        system at its own published figure and then calling the lowest total
        "cheapest" would just rank the catalogue by how boldly each row claims
        to be reusable, which is a claim rather than a measurement. Holding the
        assumption constant and reporting each system's own limit alongside
        turns that into the useful statement instead: this system is cheaper,
        and this one cannot actually deliver what you assumed.

        Two winners are named because they can differ, and the difference is
        the interesting part: ``cheapest_system_id`` is the lowest total of
        all, ``cheapest_buildable_system_id`` is the lowest total among the
        systems whose panels survive the assumed reuse count. A single-use
        column liner priced at forty reuses wins the first and is excluded
        from the second.
        """
        systems = await self.system_repo.list_filtered(
            tenant_id=tenant_id,
            system_type=data.system_type,
            # The catalogue is a product library, not per-project data, so the
            # whole of it is the comparison set. The cap is a guard against a
            # tenant with a pathological catalogue, not a pagination window:
            # a comparison that silently dropped candidates would recommend
            # the cheapest of an arbitrary subset.
            limit=500,
        )
        candidates: list[FormworkCompareCandidate] = []
        for system in systems:
            cost = compute_cost(
                unit_rate=system.unit_rate,
                area_m2=data.area_m2,
                waste_pct=data.waste_pct,
                reuse_count=data.reuse_count,
                erect_strike_rate=system.erect_strike_rate,
                rate_basis=system.rate_basis,
            )
            once = single_use_cost(
                unit_rate=system.unit_rate,
                area_m2=data.area_m2,
                waste_pct=data.waste_pct,
                erect_strike_rate=system.erect_strike_rate,
                rate_basis=system.rate_basis,
            )
            typical = system.typical_reuses
            candidates.append(
                FormworkCompareCandidate(
                    system_id=system.id,
                    name=system.name,
                    system_type=system.system_type,
                    material=system.material,
                    rate_basis=system.rate_basis,
                    currency=system.currency,
                    reuses_max=system.reuses_max,
                    typical_reuses=typical,
                    cycle_days=Decimal(system.cycle_days or 0),
                    strip_time_days=system.strip_time_days,
                    unit_cost=cost.unit_cost,
                    material_unit_cost=cost.material,
                    labour_unit_cost=cost.labour,
                    total=cost.total,
                    single_use_total=once,
                    reuse_saving=_q(once - cost.total),
                    exceeds_reuses_max=data.reuse_count > system.reuses_max,
                    above_typical_reuses=typical is not None and data.reuse_count > typical,
                )
            )

        # Cheapest total first, then by name so two systems that price
        # identically come back in a stable order rather than in whatever
        # order the database happened to return them.
        candidates.sort(key=lambda c: (c.total, c.name))
        buildable = [c for c in candidates if not c.exceeds_reuses_max]
        return FormworkCompareResult(
            area_m2=data.area_m2,
            reuse_count=data.reuse_count,
            waste_pct=data.waste_pct,
            system_type=data.system_type,
            candidates=candidates,
            cheapest_system_id=candidates[0].system_id if candidates else None,
            cheapest_buildable_system_id=buildable[0].system_id if buildable else None,
        )

    async def create_assignment(
        self,
        data: FormworkAssignmentCreate,
    ) -> FormworkAssignment:
        system = await self.system_repo.get_by_id(data.formwork_system_id)
        if system is None:
            raise LookupError("formwork_system_not_found")
        if data.reuse_count > system.reuses_max:
            raise ReuseCountExceedsMaxError(data.reuse_count, system.reuses_max)
        obj = FormworkAssignment(
            project_id=data.project_id,
            boq_position_id=data.boq_position_id,
            formwork_system_id=data.formwork_system_id,
            area_m2=data.area_m2,
            reuse_count=data.reuse_count,
            waste_pct=data.waste_pct,
            notes=data.notes,
            tenant_id=data.tenant_id,
        )
        self._apply_cost(obj, system)
        return await self.assignment_repo.create(obj)

    async def update_assignment(
        self,
        assignment_id: uuid.UUID,
        data: FormworkAssignmentUpdate,
    ) -> FormworkAssignment | None:
        """Patch an assignment and re-price it against the resolved system.

        Patches are applied in memory first so the recomputation runs against
        the merged state, not against half the old row. An explicit ``null``
        clears ``boq_position_id`` or ``notes``; aimed anywhere else it is
        refused by name.
        """
        obj = await self.assignment_repo.get_by_id(assignment_id)
        if obj is None:
            return None
        fields = _patch_fields(data, nullable=_NULLABLE_ASSIGNMENT_FIELDS)
        for name, value in fields.items():
            setattr(obj, name, value)
        # Recompute cost - resolve the (possibly swapped) system.
        system = await self.system_repo.get_by_id(obj.formwork_system_id)
        if system is None:
            raise LookupError("formwork_system_not_found")
        if obj.reuse_count > system.reuses_max:
            raise ReuseCountExceedsMaxError(obj.reuse_count, system.reuses_max)
        self._apply_cost(obj, system)
        await self.session.flush()
        return obj

    async def reprice_for_system(
        self,
        system: FormworkSystem,
    ) -> FormworkRepriceResult:
        """Recompute every assignment priced off one catalogue system.

        Assignments whose ``reuse_count`` now exceeds a lowered ``reuses_max``
        are clamped to the new cap rather than refused: the catalogue edit has
        already happened, and leaving a row priced over a limit the catalogue
        no longer allows would be a worse state than a conservative re-price.
        The clamp raises the unit cost, so it never quietly makes a job cheaper.
        """
        rows = await self.assignment_repo.list_for_system(system.id)
        repriced = 0
        unchanged = 0
        delta = Decimal("0")
        for row in rows:
            before = Decimal(row.computed_total or 0)
            if row.reuse_count > system.reuses_max:
                row.reuse_count = system.reuses_max
            cost = self._apply_cost(row, system)
            if cost.total == before:
                unchanged += 1
            else:
                repriced += 1
                delta += cost.total - before
        if rows:
            await self.session.flush()
        return FormworkRepriceResult(
            examined=len(rows),
            repriced=repriced,
            unchanged=unchanged,
            delta_total=_q(delta),
        )

    async def reprice_project(self, project_id: uuid.UUID) -> FormworkRepriceResult:
        """Recompute every formwork assignment on one project.

        The bulk refresh after a catalogue import, a currency correction or a
        restore: it re-derives every stored total from the catalogue rows as
        they stand now, and reports how much money moved.
        """
        rows = await self.assignment_repo.list_all_for_project(project_id)
        repriced = 0
        unchanged = 0
        delta = Decimal("0")
        for row in rows:
            system = row.system
            if system is None:
                continue
            before = Decimal(row.computed_total or 0)
            if row.reuse_count > system.reuses_max:
                row.reuse_count = system.reuses_max
            cost = self._apply_cost(row, system)
            if cost.total == before:
                unchanged += 1
            else:
                repriced += 1
                delta += cost.total - before
        if rows:
            await self.session.flush()
        return FormworkRepriceResult(
            examined=len(rows),
            repriced=repriced,
            unchanged=unchanged,
            delta_total=_q(delta),
        )

    # ── Pour cycle ─────────────────────────────────────────────────────

    async def analyse_cycle(
        self,
        assignment: FormworkAssignment,
        system: FormworkSystem,
    ) -> FormworkCycleAnalysis:
        """What the pour schedule says about this assignment's reuse economics."""
        lines = await self.schedule_repo.list_for_assignment(assignment.id)
        cycle = derive_cycle(lines, strip_time_days=system.strip_time_days)
        derived = int(cycle["derived_reuse_count"])
        total_area = cycle["total_pour_area_m2"]
        in_sync = (
            bool(lines)
            and derived > 0
            and assignment.reuse_count == derived
            and Decimal(assignment.area_m2) == total_area
        )
        return FormworkCycleAnalysis(
            assignment_id=assignment.id,
            pour_count=cycle["pour_count"],
            total_pour_area_m2=total_area,
            peak_pour_area_m2=cycle["peak_pour_area_m2"],
            reuse_ratio=cycle["reuse_ratio"],
            derived_reuse_count=derived,
            current_reuse_count=assignment.reuse_count,
            current_area_m2=_q(Decimal(assignment.area_m2)),
            reuses_max=system.reuses_max,
            strip_time_days=system.strip_time_days,
            min_gap_days=cycle["min_gap_days"],
            conflicts=cycle["conflicts"],
            dated_pour_count=cycle["dated_pour_count"],
            in_sync=in_sync,
        )

    async def derive_from_schedule(
        self,
        assignment: FormworkAssignment,
        system: FormworkSystem,
    ) -> tuple[FormworkCycleAnalysis, bool]:
        """Write the schedule-derived area and reuse count onto the assignment.

        This is the point of keeping a pour cycle at all: the estimator stops
        typing a reuse count from memory and takes the one the programme
        actually delivers. The derived count is clamped to the system's
        ``reuses_max`` because a schedule can describe more turnarounds than
        the panels survive - that is a real programme, just not one a single
        set of panels can serve, and the ``formwork.reuse_within_limit`` rule
        keeps reporting it.

        Returns the post-write analysis and whether anything actually changed.
        """
        analysis = await self.analyse_cycle(assignment, system)
        if analysis.pour_count == 0:
            raise LookupError("formwork_schedule_empty")
        target_reuse = min(max(analysis.derived_reuse_count, 1), system.reuses_max)
        target_area = analysis.total_pour_area_m2
        changed = assignment.reuse_count != target_reuse or Decimal(assignment.area_m2) != target_area
        if changed:
            assignment.reuse_count = target_reuse
            assignment.area_m2 = target_area
            self._apply_cost(assignment, system)
            await self.session.flush()
            analysis = await self.analyse_cycle(assignment, system)
        return analysis, changed

    # ── Schedule lines ─────────────────────────────────────────────────

    async def add_schedule_line(
        self,
        assignment: FormworkAssignment,
        data: FormworkScheduleLineCreate,
    ) -> FormworkScheduleLine:
        obj = FormworkScheduleLine(
            project_id=assignment.project_id,
            assignment_id=assignment.id,
            pour_no=data.pour_no,
            pour_date=data.pour_date,
            level_label=data.level_label,
            area_m2=data.area_m2,
            notes=data.notes,
        )
        return await self.schedule_repo.create(obj)

    async def update_schedule_line(
        self,
        line_id: uuid.UUID,
        data: FormworkScheduleLineUpdate,
    ) -> FormworkScheduleLine | None:
        """Patch a pour-cycle line in place.

        Only the fields the caller actually sent are touched, so the nullable
        ``pour_date`` / ``notes`` can be explicitly cleared by sending them as
        ``null`` while an omitted field is left untouched. A ``null`` aimed at
        ``level_label``, ``pour_no`` or ``area_m2`` is refused by name instead
        of failing as an integrity error at flush. ``project_id`` and
        ``assignment_id`` are never reparented.
        """
        obj = await self.schedule_repo.get_by_id(line_id)
        if obj is None:
            return None
        fields = _patch_fields(data, nullable=_NULLABLE_SCHEDULE_FIELDS)
        for name, value in fields.items():
            setattr(obj, name, value)
        await self.session.flush()
        return obj

    # ── Project rollup ─────────────────────────────────────────────────

    async def project_summary(self, project_id: uuid.UUID) -> FormworkProjectSummary:
        """The project's formwork totals, with the reuse saving made explicit.

        ``single_use_total`` re-prices every assignment at one use, so the
        difference against the real total is exactly the money the reuse
        assumption is claiming. That number, not the total, is what a reviewer
        challenges.

        When the assignments resolve to more than one catalogue currency the
        currency is reported blank and ``currency_mixed`` is set: the totals
        are still returned (a caller that only wants areas should not be
        blocked) but they are a sum of unlike units and the
        ``formwork.currency_consistent`` rule says so in the validation report.
        """
        rows = await self.assignment_repo.list_all_for_project(project_id)
        total_cost = Decimal("0")
        material_cost = Decimal("0")
        labour_cost = Decimal("0")
        total_area = Decimal("0")
        single_use = Decimal("0")
        unlinked = 0
        system_ids: set[uuid.UUID] = set()
        currencies: set[str] = set()
        by_type: dict[str, dict[str, Any]] = {}

        for row in rows:
            system = row.system
            area = Decimal(row.area_m2 or 0)
            total = Decimal(row.computed_total or 0)
            total_area += area
            total_cost += total
            material_cost += _q(area * Decimal(row.material_unit_cost or 0))
            labour_cost += _q(area * Decimal(row.labour_unit_cost or 0))
            system_ids.add(row.formwork_system_id)
            if row.boq_position_id is None:
                unlinked += 1
            if system is not None:
                if system.currency:
                    currencies.add(system.currency.strip().upper())
                single_use += single_use_cost(
                    unit_rate=system.unit_rate,
                    area_m2=area,
                    waste_pct=row.waste_pct,
                    erect_strike_rate=system.erect_strike_rate,
                    rate_basis=system.rate_basis,
                )
                bucket = by_type.setdefault(
                    system.system_type,
                    {"assignment_count": 0, "area_m2": Decimal("0"), "total": Decimal("0")},
                )
                bucket["assignment_count"] += 1
                bucket["area_m2"] += area
                bucket["total"] += total

        saving = single_use - total_cost
        saving_pct = (saving / single_use * Decimal("100")) if single_use > 0 else Decimal("0")
        average_unit = (total_cost / total_area) if total_area > 0 else Decimal("0")

        breakdown = [
            FormworkTypeBreakdown(
                system_type=system_type,
                assignment_count=bucket["assignment_count"],
                area_m2=_q(bucket["area_m2"]),
                total=_q(bucket["total"]),
                share_pct=_q(bucket["total"] / total_cost * Decimal("100")) if total_cost > 0 else Decimal("0"),
            )
            for system_type, bucket in sorted(
                by_type.items(),
                key=lambda item: item[1]["total"],
                reverse=True,
            )
        ]

        return FormworkProjectSummary(
            project_id=project_id,
            assignment_count=len(rows),
            system_count=len(system_ids),
            total_area_m2=_q(total_area),
            total_cost=_q(total_cost),
            material_cost=_q(material_cost),
            labour_cost=_q(labour_cost),
            average_unit_cost=_q(average_unit),
            single_use_total=_q(single_use),
            amortisation_saving=_q(saving),
            amortisation_saving_pct=_q(saving_pct),
            unlinked_to_boq=unlinked,
            currency=next(iter(currencies)) if len(currencies) == 1 else "",
            currency_mixed=len(currencies) > 1,
            by_system_type=breakdown,
        )

    # ── Validation ─────────────────────────────────────────────────────

    def _assignment_payload(
        self,
        assignment: FormworkAssignment,
        system: FormworkSystem | None,
        cycle: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Flatten one assignment into the dict shape the rules read.

        Money and quantity ride as decimal strings, never floats, so the rules
        compare the same values the API returned.
        """
        payload: dict[str, Any] = {
            "id": str(assignment.id),
            "project_id": str(assignment.project_id),
            "boq_position_id": str(assignment.boq_position_id) if assignment.boq_position_id else None,
            "formwork_system_id": str(assignment.formwork_system_id),
            "area_m2": str(assignment.area_m2 or 0),
            "reuse_count": assignment.reuse_count,
            "waste_pct": str(assignment.waste_pct or 0),
            "computed_unit_cost": str(assignment.computed_unit_cost or 0),
            "computed_total": str(assignment.computed_total or 0),
            "notes": assignment.notes or "",
            "system_name": system.name if system else "",
            "system_unit_rate": str(system.unit_rate) if system else "0",
            "erect_strike_rate": str(system.erect_strike_rate) if system else "0",
            "reuses_max": system.reuses_max if system else 0,
            "strip_time_days": system.strip_time_days if system else 0,
            "currency": system.currency if system else "",
        }
        if cycle is not None:
            payload["derived_reuse_count"] = cycle["derived_reuse_count"]
            payload["dated_pour_count"] = cycle["dated_pour_count"]
            payload["cycle_conflicts"] = [c.model_dump() for c in cycle["conflicts"]]
        return payload

    @staticmethod
    def _pour_payload(lines: list[FormworkScheduleLine]) -> list[dict[str, Any]]:
        """Flatten pour lines into the dict shape the rules read."""
        return [
            {
                "id": str(line.id),
                "pour_no": line.pour_no,
                "pour_date": line.pour_date.isoformat() if line.pour_date else None,
                "level_label": line.level_label or "",
                "area_m2": str(line.area_m2 or 0),
            }
            for line in lines
        ]

    async def validate_assignment(
        self,
        assignment: FormworkAssignment,
        system: FormworkSystem,
        *,
        locale: str = "",
    ) -> FormworkValidationReport:
        """Run the ``formwork`` rule set over one assignment and its cycle."""
        lines = await self.schedule_repo.list_for_assignment(assignment.id)
        cycle = derive_cycle(lines, strip_time_days=system.strip_time_days)
        payload = {
            "assignment": self._assignment_payload(assignment, system, cycle),
            "pours": self._pour_payload(lines),
        }
        return await evaluate_assignment(
            payload,
            project_id=str(assignment.project_id),
            locale=locale,
        )

    async def validate_project(
        self,
        project_id: uuid.UUID,
        *,
        locale: str = "",
    ) -> FormworkValidationReport:
        """Run the project-scope ``formwork`` rules over a whole project.

        The cross-assignment checks (one currency, one assignment per BOQ
        position) only exist at this scope - an assignment on its own cannot
        see that another one is charging the same bill line.
        """
        rows = await self.assignment_repo.list_all_for_project(project_id)
        payload = {
            "assignments": [self._assignment_payload(row, row.system, None) for row in rows],
        }
        return await evaluate_project(payload, project_id=str(project_id), locale=locale)
