# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Post-calculation (Nachkalkulation) compute + live data loader.

The top of this module is a pure, ``Decimal``-exact compute layer: a set of
functions that take plain dicts / lists and return the dataclasses from
:mod:`app.modules.postcalc.model`. They import nothing from the database, an ORM
or FastAPI, so the whole productivity calculation is unit-tested from plain values
on any interpreter - the same discipline as ``field_time.field_time_math`` and the
``price_breakdown`` library. Every repository / ORM import is deferred into the
async :class:`PostCalcService` methods below, so importing the compute functions
never touches the database.

Data model the compute expects, one dict per BoQ line (all numbers may be str /
int / float / Decimal / None and are coerced):

    {
        "ref": "01.02.0030",            # display code (reference_code or ordinal)
        "description": "RC wall C30/37",
        "unit": "m3",                   # position unit
        "currency": "EUR",
        "planned_quantity": "100",      # estimate quantity
        "planned_cost": "45000",        # full line total (estimate value, reference)
        "resources": [                  # per-position-unit split from metadata_["resources"]
            {"type": "labor", "unit": "h", "quantity": "2.5", "unit_rate": "45"},
            {"type": "material", "unit": "m3", "quantity": "1.02", "unit_rate": "110"},
        ],
        "actual_quantity": "100",       # installed qty (progress: planned_qty * pct/100)
        "actual_labour_hours": "300",   # booked labour hours matched to this line
        "actual_plant_hours": "40",     # booked plant hours matched to this line
        "actual_labour_cost": "13800",  # optional, from field-time rate rollup
        "actual_plant_cost": "3400",    # optional
        "actual_material_cost": "9900", # optional, from the site inventory ledger
    }

Labour ``quantity`` is hours per position unit (the platform prices labour per
hour), so a line's planned labour hours are ``sum(labour quantities) * planned_qty``
- the same invariant ``resource_summary`` relies on.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from app.modules.postcalc.model import (
    STATUS_NO_ACTUALS,
    STATUS_NO_BASELINE,
    STATUS_NO_PROGRESS,
    STATUS_ON_PLAN,
    STATUS_OVER_PRODUCTIVE,
    STATUS_UNDER_PRODUCTIVE,
    FeedbackFactor,
    LineProductivity,
    ProjectPostCalc,
    ResourceProductivity,
)
from app.modules.postcalc.norm_outturn import (
    NormBaseline,
    NormOutturnReport,
    group_by_norm,
)
from app.modules.price_breakdown import ResourceKind, coerce_kind

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# A line whose productivity factor sits within this fraction of 1.0 is "on plan".
# 0.05 = a 5% band, a pragmatic default that keeps normal site noise from being
# flagged as a real deviation. Callers may tighten or widen it.
DEFAULT_TOLERANCE = Decimal("0.05")

# A feedback factor is only suggested when at least this fraction of the line has
# actually been installed, so a single stray booking on a barely-started line does
# not propose a norm change. Confidence rises with installed coverage.
DEFAULT_MIN_CONFIDENCE = Decimal("0.10")

_HUNDRED = Decimal("100")
_ONE = Decimal("1")


# ── Coercion helpers ────────────────────────────────────────────────────────


def _dec(value: object, default: str = "0") -> Decimal:
    """Coerce an arbitrary value to a finite ``Decimal``, never raising."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else Decimal(default)
    if value is None or value == "":
        return Decimal(default)
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)
    return out if out.is_finite() else Decimal(default)


def _opt_dec(value: object) -> Decimal | None:
    """Coerce to ``Decimal`` when a value is present, else ``None`` (unknown)."""
    if value is None or value == "":
        return None
    return _dec(value)


def _resources_of(line: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the per-unit resource split of a line (empty when absent)."""
    meta = line.get("metadata_") or line.get("metadata")
    resources = line.get("resources")
    if resources is None and isinstance(meta, dict):
        resources = meta.get("resources")
    if not isinstance(resources, list):
        return []
    return [r for r in resources if isinstance(r, dict)]


def _res_kind(res: Mapping[str, Any]) -> ResourceKind:
    """Map a resource line's type token onto the shared :class:`ResourceKind`."""
    return coerce_kind(res.get("type") or res.get("resource_type") or res.get("kind"))


def _per_unit_cost(res: Mapping[str, Any]) -> Decimal:
    """Per-position-unit cost of one resource line (self-healing after an edit).

    Prefers ``quantity * unit_rate`` when both are present so the figure survives a
    factor edit that left a stale ``total`` behind; falls back to the stored
    ``total`` only when a factor is missing (same rule as the BoQ cost breakdown).
    """
    qty = res.get("quantity")
    rate = res.get("unit_rate")
    if qty is not None and rate is not None:
        return _dec(qty) * _dec(rate)
    return _dec(res.get("total"))


def _per_unit_hours(resources: Sequence[Mapping[str, Any]], kind: ResourceKind) -> Decimal:
    """Sum the per-position-unit hours of every resource line of one kind."""
    return sum((_dec(r.get("quantity")) for r in resources if _res_kind(r) is kind), Decimal("0"))


def _per_unit_cost_of_kind(resources: Sequence[Mapping[str, Any]], kind: ResourceKind) -> Decimal:
    """Sum the per-position-unit cost of every resource line of one kind."""
    return sum((_per_unit_cost(r) for r in resources if _res_kind(r) is kind), Decimal("0"))


def _classify(factor: Decimal, tolerance: Decimal) -> str:
    """Classify a productivity factor into on-plan / over / under against a band."""
    if factor > _ONE + tolerance:
        return STATUS_UNDER_PRODUCTIVE
    if factor < _ONE - tolerance:
        return STATUS_OVER_PRODUCTIVE
    return STATUS_ON_PLAN


# ── Material actuals from the site material ledger ──────────────────────────


def consumed_material_cost(
    movements: Sequence[Any],
    items: Sequence[Any],
    *,
    project_currency: str = "",
) -> dict[str, Decimal]:
    """Priced material consumed per BoQ position, from site inventory movements.

    Pure: it takes the site-inventory module's own DB-free value objects
    (:class:`~app.modules.site_inventory.ledger.Movement` and
    :class:`~app.modules.site_inventory.ledger.StockItemRef`) and returns
    ``{position_id: consumed cost}``. The DB loader on
    :class:`PostCalcService` does nothing but read the rows and call this.

    Attribution and the consumption-only filter are the inventory module's own
    rule, so this figure and the one that module's material-variance screen
    reports can never disagree. What is added on top is honesty about what
    cannot be priced: a position is left out of the result entirely - unknown,
    never zero - when any of its consumption carries no unit cost, or when its
    money is labelled in more than one currency or in one the project does not
    report in. A position nothing was consumed against is absent for the same
    reason: an unmetered position is not a position that used no material.
    """
    from app.modules.site_inventory import ledger

    wanted = (project_currency or "").strip().upper()
    costs: dict[str, Decimal] = {}
    priced: dict[str, bool] = {}
    currencies: dict[str, set[str]] = {}
    for movement in ledger.resolve_positions(movements, items):
        if movement.movement_type != ledger.MovementType.CONSUMPTION.value:
            continue
        key = movement.boq_position_id
        if not key:
            continue
        costs[key] = costs.get(key, Decimal("0")) + movement.line_cost
        priced[key] = priced.get(key, True) and movement.unit_cost > 0
        code = (movement.currency or "").strip().upper()
        if code:
            currencies.setdefault(key, set()).add(code)

    out: dict[str, Decimal] = {}
    for key, cost in costs.items():
        if not priced.get(key, False):
            continue
        labels = currencies.get(key, set())
        if len(labels) > 1:
            continue
        if labels and wanted and next(iter(labels)) != wanted:
            continue
        out[key] = cost
    return out


# ── Per-line productivity ───────────────────────────────────────────────────


def compute_line_productivity(
    line: Mapping[str, Any],
    *,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> LineProductivity:
    """Compute the labour productivity of one BoQ line from a plain dict.

    The productivity factor is ``actual_labour_hours / earned_hours`` where
    ``earned_hours = planned_hours_per_unit * actual_quantity`` - the hours the
    estimate budgeted for the quantity actually installed. Guards, in order:

    * no labour norm on the estimate (zero planned hours or quantity) -> no_baseline;
    * nothing booked and nothing installed -> no_actuals;
    * hours booked but nothing installed -> no_progress (a strong overrun signal);
    * installed but no hours booked -> no_actuals (a timesheet gap, not judged).

    Only a line with a baseline, installed quantity and booked hours yields a
    factor. Money is ``Decimal`` throughout.

    Material rides alongside on cost only. ``actual_material_cost`` comes from
    the site material ledger and stays ``None`` when the site recorded no priced
    consumption for the line, because an unmetered position and a position that
    used no material are two different statements and only one of them is worth
    a number.
    """
    resources = _resources_of(line)
    planned_quantity = _dec(line.get("planned_quantity"))
    actual_quantity = _dec(line.get("actual_quantity"))
    labour_per_unit = _per_unit_hours(resources, ResourceKind.LABOUR)
    planned_hours = labour_per_unit * planned_quantity
    actual_hours = _dec(line.get("actual_labour_hours"))
    labour_cost_per_unit = _per_unit_cost_of_kind(resources, ResourceKind.LABOUR)
    planned_labour_cost = labour_cost_per_unit * planned_quantity
    actual_labour_cost = _opt_dec(line.get("actual_labour_cost"))
    material_cost_per_unit = _per_unit_cost_of_kind(resources, ResourceKind.MATERIAL)
    planned_material_cost = material_cost_per_unit * planned_quantity
    actual_material_cost = _opt_dec(line.get("actual_material_cost"))

    has_baseline = planned_quantity > 0 and planned_hours > 0
    has_progress = actual_quantity > 0

    planned_hpu = planned_hours / planned_quantity if planned_quantity > 0 else None
    actual_hpu = actual_hours / actual_quantity if has_progress else None
    earned_hours = (planned_hpu * actual_quantity) if (has_baseline and has_progress) else None

    productivity_factor: Decimal | None = None
    variance_pct: Decimal | None = None
    hours_variance: Decimal | None = None

    if not has_baseline:
        status = STATUS_NO_BASELINE
    elif actual_hours <= 0 and not has_progress:
        status = STATUS_NO_ACTUALS
    elif not has_progress:
        status = STATUS_NO_PROGRESS
    elif actual_hours <= 0:
        # Installed quantity exists but no hours were booked against it: a
        # timesheet gap, not a productivity result. earned_hours stays available
        # as context but no factor is claimed.
        status = STATUS_NO_ACTUALS
    else:
        # Both guards passed, so planned_quantity > 0 and actual_quantity > 0;
        # recompute earned from the non-optional figures to keep the factor exact.
        earned = planned_hours / planned_quantity * actual_quantity
        hours_variance = actual_hours - earned
        productivity_factor = actual_hours / earned
        variance_pct = (productivity_factor - _ONE) * _HUNDRED
        status = _classify(productivity_factor, tolerance)

    labour_cost_variance = (actual_labour_cost - planned_labour_cost) if actual_labour_cost is not None else None
    material_cost_variance = (
        (actual_material_cost - planned_material_cost) if actual_material_cost is not None else None
    )

    # Money the estimate allowed for the quantity actually installed. Only
    # meaningful where the line was priced per unit at all, so a line with no
    # planned quantity earns nothing rather than earning its whole budget.
    earned_labour_cost = (labour_cost_per_unit * actual_quantity) if planned_quantity > 0 else None
    earned_material_cost = (material_cost_per_unit * actual_quantity) if planned_quantity > 0 else None

    return LineProductivity(
        ref=str(line.get("ref") or "").strip(),
        description=str(line.get("description") or "").strip(),
        unit=str(line.get("unit") or "").strip(),
        currency=str(line.get("currency") or "").strip(),
        planned_quantity=planned_quantity,
        actual_quantity=actual_quantity,
        planned_hours=planned_hours,
        actual_hours=actual_hours,
        planned_hours_per_unit=planned_hpu,
        actual_hours_per_unit=actual_hpu,
        earned_hours=earned_hours,
        hours_variance=hours_variance,
        productivity_factor=productivity_factor,
        variance_pct=variance_pct,
        planned_labour_cost=planned_labour_cost,
        actual_labour_cost=actual_labour_cost,
        labour_cost_variance=labour_cost_variance,
        status=status,
        earned_labour_cost=earned_labour_cost,
        planned_material_cost=planned_material_cost,
        earned_material_cost=earned_material_cost,
        actual_material_cost=actual_material_cost,
        material_cost_variance=material_cost_variance,
    )


# ── Per-resource-category rollup ────────────────────────────────────────────


def aggregate_resources(
    lines: Sequence[Mapping[str, Any]],
    *,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> list[ResourceProductivity]:
    """Roll every line's resource split up into one row per resource category.

    Labour and machinery are measured in hours, so they carry a real productivity
    factor (earned vs actual hours). Actual labour hours come from the line's
    ``actual_labour_hours`` and actual machinery hours from ``actual_plant_hours``.
    Material, equipment, subcontract and other are compared on cost only, and
    material's actual cost comes from the line's ``actual_material_cost`` (the
    site material ledger). Equipment, subcontract and other have no actuals
    source anywhere in the platform today, so they keep reporting ``None`` -
    unknown - rather than a zero that would read as money nobody spent.

    Only the categories that actually appear in the estimate, carry booked hours
    or carry a known actual cost are returned, ordered by
    :data:`app.modules.postcalc.model.KIND_ORDER`. That last condition is not
    decoration: material consumption can be booked against a position whose
    estimate carries no material line at all, and without it the category would
    be dropped and its spend would vanish from the report.
    """
    from app.modules.postcalc.model import KIND_ORDER

    acc: dict[ResourceKind, dict[str, Any]] = {}

    def _bucket(kind: ResourceKind) -> dict[str, Any]:
        slot = acc.get(kind)
        if slot is None:
            slot = {
                "planned_hours": Decimal("0"),
                "earned_hours": Decimal("0"),
                "actual_hours": Decimal("0"),
                "planned_cost": Decimal("0"),
                "earned_cost": Decimal("0"),
                "earned_cost_compared": Decimal("0"),
                "actual_cost": Decimal("0"),
                "actual_cost_known": False,
                "seen": False,
            }
            acc[kind] = slot
        return slot

    for line in lines:
        resources = _resources_of(line)
        planned_quantity = _dec(line.get("planned_quantity"))
        actual_quantity = _dec(line.get("actual_quantity"))

        # Actual hours + cost come from the field side, keyed by category. Read
        # before the estimate side because whether this line's actual is known
        # decides which earned bucket the estimate side may contribute to.
        labour = _bucket(ResourceKind.LABOUR)
        labour["actual_hours"] += _dec(line.get("actual_labour_hours"))
        labour_cost = _opt_dec(line.get("actual_labour_cost"))
        if labour_cost is not None:
            labour["actual_cost"] += labour_cost
            labour["actual_cost_known"] = True

        plant = _bucket(ResourceKind.MACHINERY)
        plant["actual_hours"] += _dec(line.get("actual_plant_hours"))
        plant_cost = _opt_dec(line.get("actual_plant_cost"))
        if plant_cost is not None:
            plant["actual_cost"] += plant_cost
            plant["actual_cost_known"] = True

        # Material actuals come from the site inventory ledger: the priced
        # consumption booked against this position. Absent, the category keeps
        # reporting unknown, which is the whole point of the flag.
        material_cost = _opt_dec(line.get("actual_material_cost"))
        if material_cost is not None:
            material = _bucket(ResourceKind.MATERIAL)
            material["actual_cost"] += material_cost
            material["actual_cost_known"] = True

        # Which categories this line can be compared on. A category missing here
        # still accrues planned and earned money, it just may not feed the
        # earned side of a subtraction whose other side does not cover it.
        priced_here = {
            ResourceKind.LABOUR: labour_cost is not None,
            ResourceKind.MACHINERY: plant_cost is not None,
            ResourceKind.MATERIAL: material_cost is not None,
        }

        kinds_here = {_res_kind(r) for r in resources}
        for kind in kinds_here:
            slot = _bucket(kind)
            slot["seen"] = True
            per_unit_hours = _per_unit_hours(resources, kind)
            per_unit_cost = _per_unit_cost_of_kind(resources, kind)
            slot["planned_hours"] += per_unit_hours * planned_quantity
            slot["planned_cost"] += per_unit_cost * planned_quantity
            if actual_quantity > 0:
                # What the estimate allowed for the quantity installed. Earned
                # money applies to every category, unlike earned hours, which
                # only the two hour-based ones can have.
                earned_here = per_unit_cost * actual_quantity
                slot["earned_cost"] += earned_here
                if priced_here.get(kind, False):
                    slot["earned_cost_compared"] += earned_here
                if kind in (ResourceKind.LABOUR, ResourceKind.MACHINERY):
                    slot["earned_hours"] += per_unit_hours * actual_quantity

    out: list[ResourceProductivity] = []
    for kind in KIND_ORDER:
        slot = acc.get(kind)
        if slot is None:
            continue
        # Skip a category we only touched to seed actual buckets but which
        # carries no estimate demand, no booked hours and no known spend (keeps
        # the table tidy). Money counts here as well as hours: material booked
        # against a position the estimate priced without a material line is real
        # spend, and dropping the row would hide it.
        if not slot["seen"] and slot["actual_hours"] <= 0 and not slot["actual_cost_known"]:
            continue

        planned_hours = slot["planned_hours"]
        earned_hours = slot["earned_hours"]
        actual_hours = slot["actual_hours"]
        planned_cost = slot["planned_cost"]
        earned_cost = slot["earned_cost"]
        actual_cost = slot["actual_cost"] if slot["actual_cost_known"] else None
        earned_cost_compared = slot["earned_cost_compared"] if slot["actual_cost_known"] else None

        factor: Decimal | None = None
        variance_pct: Decimal | None = None
        status = STATUS_NO_ACTUALS
        hour_based = kind in (ResourceKind.LABOUR, ResourceKind.MACHINERY)
        if not hour_based:
            status = STATUS_NO_BASELINE  # cost-only category, no hours productivity
        elif earned_hours <= 0:
            status = STATUS_NO_BASELINE if planned_hours <= 0 else STATUS_NO_PROGRESS
        elif actual_hours <= 0:
            status = STATUS_NO_ACTUALS
        else:
            factor = actual_hours / earned_hours
            variance_pct = (factor - _ONE) * _HUNDRED
            status = _classify(factor, tolerance)

        cost_variance = (actual_cost - planned_cost) if actual_cost is not None else None

        out.append(
            ResourceProductivity(
                kind=kind,
                planned_hours=planned_hours,
                earned_hours=earned_hours,
                actual_hours=actual_hours,
                productivity_factor=factor,
                variance_pct=variance_pct,
                planned_cost=planned_cost,
                actual_cost=actual_cost,
                cost_variance=cost_variance,
                status=status,
                earned_cost=earned_cost,
                earned_cost_compared=earned_cost_compared,
            )
        )
    return out


# ── Estimating feedback factors ─────────────────────────────────────────────


def _recommendation(line: LineProductivity, quant: Decimal) -> str:
    """Human-readable, no-jargon advice for one feedback factor."""
    from app.modules.postcalc.model import _q

    unit = line.unit or "unit"
    cur = _q(line.planned_hours_per_unit, quant) or "?"
    obs = _q(line.actual_hours_per_unit, quant) or "?"
    var = abs(line.variance_pct) if line.variance_pct is not None else Decimal("0")
    var_txt = _q(var, Decimal("0.1")) or "?"
    if line.is_under_productive:
        return (
            f"Site booked {var_txt}% more labour than the {cur} h/{unit} estimate norm. "
            f"Consider raising the norm toward {obs} h/{unit}."
        )
    return f"Site beat the {cur} h/{unit} estimate norm by {var_txt}%. The norm could tighten toward {obs} h/{unit}."


def build_feedback_factors(
    line_prods: Sequence[LineProductivity],
    *,
    min_confidence: Decimal = DEFAULT_MIN_CONFIDENCE,
) -> list[FeedbackFactor]:
    """Turn the deviating lines into a ranked list of estimating feedback factors.

    A factor is emitted for every line that is clearly over- or under-productive
    (its status already reflects the tolerance band) and whose installed coverage
    meets ``min_confidence``. Confidence is the installed fraction of the line
    (capped at 1.0): the more of the work that is done, the more the observed norm
    can be trusted. Factors are sorted by the absolute hour impact, biggest first,
    so the estimator sees where the money is. Nothing is auto-applied.
    """
    _q_factor = Decimal("0.0001")
    factors: list[FeedbackFactor] = []
    for line in line_prods:
        if line.status not in (STATUS_UNDER_PRODUCTIVE, STATUS_OVER_PRODUCTIVE):
            continue
        if (
            line.actual_hours_per_unit is None
            or line.planned_hours_per_unit is None
            or line.productivity_factor is None
            or line.variance_pct is None
        ):
            continue
        coverage = Decimal("0")
        if line.planned_quantity > 0:
            coverage = min(line.actual_quantity / line.planned_quantity, _ONE)
        if coverage < min_confidence:
            continue
        factors.append(
            FeedbackFactor(
                ref=line.ref,
                description=line.description,
                unit=line.unit,
                current_hours_per_unit=line.planned_hours_per_unit.quantize(_q_factor),
                observed_hours_per_unit=line.actual_hours_per_unit.quantize(_q_factor),
                suggested_hours_per_unit=line.actual_hours_per_unit.quantize(_q_factor),
                productivity_factor=line.productivity_factor,
                variance_pct=line.variance_pct,
                observed_quantity=line.actual_quantity,
                confidence=coverage,
                recommendation=_recommendation(line, _q_factor),
            )
        )
    factors.sort(
        key=lambda ff: abs((ff.observed_hours_per_unit - ff.current_hours_per_unit) * ff.observed_quantity),
        reverse=True,
    )
    return factors


# ── Project rollup ──────────────────────────────────────────────────────────


def compute_project_postcalc(
    lines: Sequence[Mapping[str, Any]],
    *,
    currency: str = "",
    tolerance: Decimal = DEFAULT_TOLERANCE,
    min_confidence: Decimal = DEFAULT_MIN_CONFIDENCE,
) -> ProjectPostCalc:
    """Compute the full post-calculation report from a list of plain line dicts.

    Builds a :class:`LineProductivity` per line, the per-category rollup, the
    project totals (the overall factor is actual/earned over the lines that have a
    baseline and progress, so unbaselined lines never skew it) and the estimating
    feedback list. Pure and ``Decimal``-exact.
    """
    line_prods = [compute_line_productivity(line, tolerance=tolerance) for line in lines]
    resources = aggregate_resources(lines, tolerance=tolerance)

    total_planned_hours = sum((lp.planned_hours for lp in line_prods), Decimal("0"))
    total_actual_hours = sum((lp.actual_hours for lp in line_prods), Decimal("0"))
    total_planned_labour_cost = sum((lp.planned_labour_cost for lp in line_prods), Decimal("0"))
    total_planned_value = sum((_dec(line.get("planned_cost")) for line in lines), Decimal("0"))

    # Overall factor is computed only over comparable lines (baseline + progress +
    # booked hours) so a line with no norm cannot distort it.
    total_earned_hours = Decimal("0")
    compared_actual_hours = Decimal("0")
    compared_line_count = 0
    for lp in line_prods:
        if lp.productivity_factor is not None and lp.earned_hours is not None:
            total_earned_hours += lp.earned_hours
            compared_actual_hours += lp.actual_hours
            compared_line_count += 1

    overall_factor: Decimal | None = None
    overall_variance_pct: Decimal | None = None
    if total_earned_hours > 0:
        overall_factor = compared_actual_hours / total_earned_hours
        overall_variance_pct = (overall_factor - _ONE) * _HUNDRED

    # Each category gets an earned total over every baselined line, which is the
    # figure the planned total may be read against, and a second one over the
    # lines the field could actually price, which is the only figure the actual
    # total may be subtracted from. An earned total covering forty lines against
    # an actual total covering three is a comparison of two different jobs, and
    # it reports the thirty-seven nobody measured as a saving.
    def _earned_over(lines_in: list[LineProductivity], pick: str) -> Decimal:
        return sum(
            (value for lp in lines_in if (value := getattr(lp, pick)) is not None),
            Decimal("0"),
        )

    labour_priced_lines = [lp for lp in line_prods if lp.actual_labour_cost is not None]
    total_actual_labour_cost = (
        sum((lp.actual_labour_cost for lp in labour_priced_lines), Decimal("0")) if labour_priced_lines else None
    )
    total_earned_labour_cost = _earned_over(line_prods, "earned_labour_cost")
    total_earned_labour_cost_compared = (
        _earned_over(labour_priced_lines, "earned_labour_cost") if labour_priced_lines else None
    )

    total_planned_material_cost = sum((lp.planned_material_cost for lp in line_prods), Decimal("0"))
    priced_lines = [lp for lp in line_prods if lp.actual_material_cost is not None]
    total_earned_material_cost = _earned_over(line_prods, "earned_material_cost")
    total_earned_material_cost_compared = _earned_over(priced_lines, "earned_material_cost") if priced_lines else None
    total_actual_material_cost = (
        sum((lp.actual_material_cost for lp in priced_lines), Decimal("0")) if priced_lines else None
    )

    status_counts: dict[str, int] = {}
    for lp in line_prods:
        status_counts[lp.status] = status_counts.get(lp.status, 0) + 1

    feedback = build_feedback_factors(line_prods, min_confidence=min_confidence)

    resolved_currency = (currency or "").strip()
    if not resolved_currency:
        for line in lines:
            code = str(line.get("currency") or "").strip()
            if code:
                resolved_currency = code
                break

    return ProjectPostCalc(
        currency=resolved_currency,
        total_planned_hours=total_planned_hours,
        total_earned_hours=total_earned_hours,
        total_actual_hours=total_actual_hours,
        overall_productivity_factor=overall_factor,
        overall_variance_pct=overall_variance_pct,
        total_planned_labour_cost=total_planned_labour_cost,
        total_actual_labour_cost=total_actual_labour_cost,
        total_planned_value=total_planned_value,
        line_count=len(line_prods),
        compared_line_count=compared_line_count,
        status_counts=status_counts,
        total_earned_labour_cost=total_earned_labour_cost,
        total_earned_labour_cost_compared=total_earned_labour_cost_compared,
        total_planned_material_cost=total_planned_material_cost,
        total_earned_material_cost=total_earned_material_cost,
        total_earned_material_cost_compared=total_earned_material_cost_compared,
        total_actual_material_cost=total_actual_material_cost,
        labour_priced_line_count=len(labour_priced_lines),
        material_priced_line_count=len(priced_lines),
        lines=line_prods,
        resources=resources,
        feedback_factors=feedback,
    )


# ── Live data loader (async, DB-backed) ─────────────────────────────────────

# Approved, non-reversal timesheets are the authoritative labour/plant actuals -
# the exact filter the field-time module's own summary uses (an approved sheet
# flips to "reversed" when undone, and its mirroring reversal carries reverses_id,
# so both drop out and net to zero).
_APPROVED = "approved"


class PostCalcService:
    """Assemble a live post-calculation report for a project.

    Reads the estimate side (BoQ positions and their stored resource split), the
    labour/plant actuals (approved field timesheets) and the installed quantities
    (latest progress percent per position), reconciles them per line, and hands the
    plain dicts to the pure compute above. It writes nothing back - it is a pure
    read/analyse layer, so it adds no table and no migration. Every cross-module
    read is best-effort: a project with no timesheets or no progress still returns
    a valid report (the estimate side alone), it just has no actuals to compare.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def generate(
        self,
        project_id: uuid.UUID,
        *,
        tolerance: Decimal = DEFAULT_TOLERANCE,
        min_confidence: Decimal = DEFAULT_MIN_CONFIDENCE,
    ) -> ProjectPostCalc:
        """Build the live report for a project by reconciling estimate vs actuals."""
        positions = await self._load_positions(project_id)
        currency = await self._project_currency(project_id)

        # Map every cost code a foreman might book against to its owning position.
        code_to_pid: dict[str, uuid.UUID] = {}
        wbs_to_pid: dict[str, uuid.UUID] = {}
        for pos in positions:
            pid = pos.id
            for code in (pos.reference_code, pos.ordinal, pos.cost_code_id):
                key = str(code).strip() if code else ""
                if key:
                    code_to_pid.setdefault(key, pid)
            wbs_key = str(pos.wbs_id).strip() if pos.wbs_id else ""
            if wbs_key:
                wbs_to_pid.setdefault(wbs_key, pid)

        actuals = await self._load_field_actuals(project_id, code_to_pid, wbs_to_pid)
        installed = await self._load_installed_quantities(project_id, positions)
        material = await self._load_material_actuals(project_id, positions, currency)

        lines: list[dict[str, Any]] = []
        for pos in positions:
            pid = pos.id
            act = actuals.get(pid)
            lines.append(
                {
                    "ref": str(pos.reference_code or pos.ordinal or "").strip(),
                    "description": pos.description or "",
                    "unit": pos.unit or "",
                    "currency": currency,
                    "planned_quantity": pos.quantity,
                    "planned_cost": pos.total,
                    "resources": (pos.metadata_ or {}).get("resources") if isinstance(pos.metadata_, dict) else None,
                    "actual_quantity": installed.get(pid, Decimal("0")),
                    "actual_labour_hours": act["labour_hours"] if act else Decimal("0"),
                    "actual_plant_hours": act["plant_hours"] if act else Decimal("0"),
                    "actual_labour_cost": act["labour_cost"] if act else None,
                    "actual_plant_cost": act["plant_cost"] if act else None,
                    "actual_material_cost": material.get(pid),
                }
            )

        return compute_project_postcalc(
            lines,
            currency=currency,
            tolerance=tolerance,
            min_confidence=min_confidence,
        )

    async def norm_outturn(
        self,
        project_id: uuid.UUID,
        *,
        tolerance: Decimal = DEFAULT_TOLERANCE,
    ) -> NormOutturnReport:
        """Per production norm: what the estimate allowed against what it cost.

        Issue #457. ``generate`` above answers this per bill line. This answers
        it per norm, by rolling up every position of the project that was priced
        from one, which is the grain the question is actually asked at: a norm is
        reused across a bill, so whether it held is a fact about all of its
        positions at once.

        The measured side is read through
        :func:`app.modules.costmodel.position_actuals.build_position_actuals`
        rather than through this module's own loaders, and that is a deliberate
        reuse rather than a shortcut. That function already crosses the two
        spines the platform keeps apart - money keyed by cost line, physical
        facts keyed by position - and already matches booked hours to positions
        through ``FieldTimesheetLine.boq_position_id``, which is the direct link
        and handles the reversal trap that the obvious ``status == 'approved'``
        filter gets exactly backwards. Reimplementing either here would mean
        reimplementing that trap.

        It is asked for the whole bill, unpaged. A rollup that took the paged
        default would report a subtotal in the shape of a total.

        The predicted side is read live from the norm library, and a norm that
        has been deleted since the bill was priced comes back with
        ``norm_row_present`` False rather than dropping out of the report: the
        identity was copied onto the position precisely so that deleting the
        library entry could not erase the fact that the work was estimated from
        it.

        Returns:
            A :class:`NormOutturnReport`. A project whose bill was never priced
            from a norm returns an empty ``norms`` list with every position
            counted under ``positions_without_norm``, which says "no norms here"
            where an empty response would say nothing at all.
        """
        from app.modules.costmodel.position_actuals import build_position_actuals

        # ``limit=None`` and not the paged default: this rolls the whole bill
        # up, and a page of it would report a subtotal in the shape of a total.
        report = await build_position_actuals(self.session, project_id, limit=None)

        # The bill baseline: labour hours per position unit, from the resource
        # split stored on the position when the assembly was applied. Read from
        # the positions rather than from the report, because the split is the
        # one thing a position-actuals row deliberately does not carry - it is
        # estimate composition, not an actual.
        #
        # Both sides of this are the same unpaged ``list_for_project``, which is
        # what makes the lookup below safe: every position of the project has an
        # entry, so a missing key is impossible and the zero default can only
        # mean "this position carries no labour split". Page either side and
        # that stops being true - the rows past the page would silently take the
        # zero and be reported as having no baseline rather than as unread.
        positions = await self._load_positions(project_id)
        bill_hours_per_unit = {
            pos.id: _per_unit_hours(_resources_of({"metadata": pos.metadata_}), ResourceKind.LABOUR)
            for pos in positions
        }

        norm_ids = {row.norm_id for row in report.rows if row.norm_id}
        baselines = await self._load_norm_baselines(norm_ids)

        return group_by_norm(
            list(report.rows),
            baselines=baselines,
            bill_labour_hours_per_unit=bill_hours_per_unit,
            currency=report.currency,
            tolerance=tolerance,
        )

    async def _load_norm_baselines(self, norm_ids: set[str]) -> dict[str, NormBaseline]:
        """Load the live library row for each norm id, skipping the ones that are gone.

        Best-effort, like every other cross-module read in this service: without
        the norm-expansion module the report still has its bill side and its
        outturn side, and every norm reads as deleted, which is the honest thing
        to say when the library cannot be consulted at all.

        An id that does not parse as a UUID is dropped before the query rather
        than passed to the driver: it can only have come from the metadata
        fallback, where the value is free-form JSON somebody else wrote.
        """
        if not norm_ids:
            return {}
        try:
            from sqlalchemy import select

            from app.modules.norm_expansion.models import ProductionNorm

            parsed: dict[uuid.UUID, str] = {}
            for raw in norm_ids:
                try:
                    parsed[uuid.UUID(str(raw))] = raw
                except (ValueError, AttributeError, TypeError):
                    continue
            if not parsed:
                return {}

            stmt = select(ProductionNorm).where(ProductionNorm.id.in_(sorted(parsed)))
            norms = (await self.session.execute(stmt)).scalars().all()
        except Exception:
            logger.debug("Norm library unavailable while building the norm outturn", exc_info=True)
            return {}

        return {
            parsed.get(norm.id, str(norm.id)): NormBaseline(
                work_key=norm.work_key or "",
                name=norm.name or "",
                unit=norm.unit or "",
                labour_hours_per_unit=_dec(norm.labor_hours_per_unit),
                machine_hours_per_unit=_dec(norm.machine_hours_per_unit),
            )
            for norm in norms
        }

    async def render_markdown(
        self,
        project_id: uuid.UUID,
        *,
        tolerance: Decimal = DEFAULT_TOLERANCE,
        min_confidence: Decimal = DEFAULT_MIN_CONFIDENCE,
    ) -> str:
        """Build the live report and render it as an auditable Markdown document."""
        from app.modules.postcalc.model import render_markdown

        report = await self.generate(project_id, tolerance=tolerance, min_confidence=min_confidence)
        return render_markdown(report)

    # ── Estimate side ────────────────────────────────────────────────────────

    async def _load_positions(self, project_id: uuid.UUID) -> list[Any]:
        """Return every BoQ position of a project (read-only)."""
        from app.modules.boq.repository import PositionRepository

        return await PositionRepository(self.session).list_for_project(project_id)

    async def _project_currency(self, project_id: uuid.UUID) -> str:
        """Best-effort project base currency (empty string when unknown)."""
        try:
            from sqlalchemy import select

            from app.modules.projects.models import Project

            row = (await self.session.execute(select(Project.currency).where(Project.id == project_id))).first()
        except Exception:
            logger.debug("Project currency lookup failed for %s", project_id, exc_info=True)
            return ""
        if not row or not row[0]:
            return ""
        return str(row[0]).strip()[:3].upper()

    # ── Actual side: field timesheets ────────────────────────────────────────

    async def _load_field_actuals(
        self,
        project_id: uuid.UUID,
        code_to_pid: dict[str, uuid.UUID],
        wbs_to_pid: dict[str, uuid.UUID],
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Bucket approved labour/plant hours (and cost where priced) per position.

        Best-effort: if the field-time module is unavailable the report simply has
        no labour actuals. Cost is only reported for a position when every one of
        its booked lines could be priced, so a partial rate lookup never understates
        actual cost silently - it reports ``None`` (unknown) instead.
        """
        try:
            from app.modules.field_time.repository import FieldTimeRepository

            timesheets, _total = await FieldTimeRepository(self.session).list_for_project(project_id, limit=100000)
        except Exception:
            logger.debug("Field-time actuals unavailable for %s", project_id, exc_info=True)
            return {}

        approved = [ts for ts in timesheets if ts.status == _APPROVED and ts.reverses_id is None]
        if not approved:
            return {}

        labour_rates, plant_rates = await self._resolve_rates(project_id, approved)

        actuals: dict[uuid.UUID, dict[str, Any]] = {}

        def _slot(pid: uuid.UUID) -> dict[str, Any]:
            slot = actuals.get(pid)
            if slot is None:
                slot = {
                    "labour_hours": Decimal("0"),
                    "plant_hours": Decimal("0"),
                    "labour_cost": Decimal("0"),
                    "plant_cost": Decimal("0"),
                    "labour_priced": True,
                    "plant_priced": True,
                }
                actuals[pid] = slot
            return slot

        for ts in approved:
            for tline in ts.lines:
                code = str(tline.cost_code or "").strip()
                pid = code_to_pid.get(code)
                if pid is None:
                    wbs = str(tline.wbs or "").strip()
                    pid = wbs_to_pid.get(wbs)
                if pid is None:
                    continue
                hours = _dec(tline.hours)
                slot = _slot(pid)
                if tline.resource_id is not None:
                    slot["labour_hours"] += hours
                    rate = labour_rates.get(str(tline.resource_id))
                    if rate is None:
                        slot["labour_priced"] = False
                    else:
                        slot["labour_cost"] += hours * rate
                elif tline.equipment_id is not None:
                    slot["plant_hours"] += hours
                    rate = plant_rates.get(str(tline.equipment_id))
                    if rate is None:
                        slot["plant_priced"] = False
                    else:
                        slot["plant_cost"] += hours * rate

        # Collapse the priced flags into a known cost or None.
        for slot in actuals.values():
            slot["labour_cost"] = slot["labour_cost"] if slot["labour_priced"] and slot["labour_hours"] > 0 else None
            slot["plant_cost"] = slot["plant_cost"] if slot["plant_priced"] and slot["plant_hours"] > 0 else None
        return actuals

    async def _resolve_rates(
        self,
        project_id: uuid.UUID,
        timesheets: Sequence[Any],
    ) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        """Resolve ``{resource_id: rate}`` and ``{equipment_id: rate}`` maps.

        Mirrors the field-time approval rollup: labour rates from the resources
        module's ``default_cost_rate`` and plant rates from the highest recorded
        project rental ``internal_rate_per_hour``. Any failure yields an empty map,
        so the report degrades to hours-only rather than raising.
        """
        resource_ids: set[uuid.UUID] = set()
        equipment_ids: set[uuid.UUID] = set()
        for ts in timesheets:
            for tline in ts.lines:
                if tline.resource_id is not None:
                    resource_ids.add(tline.resource_id)
                if tline.equipment_id is not None:
                    equipment_ids.add(tline.equipment_id)

        labour_rates: dict[str, Decimal] = {}
        if resource_ids:
            try:
                from sqlalchemy import select

                from app.modules.resources.models import Resource

                rows = (
                    await self.session.execute(
                        select(Resource.id, Resource.default_cost_rate).where(Resource.id.in_(resource_ids))
                    )
                ).all()
                labour_rates = {str(rid): _dec(rate) for rid, rate in rows}
            except Exception:
                logger.debug("Labour-rate lookup unavailable for %s", project_id, exc_info=True)

        plant_rates: dict[str, Decimal] = {}
        if equipment_ids:
            try:
                from sqlalchemy import select

                from app.modules.equipment.models import EquipmentRental

                rows = (
                    await self.session.execute(
                        select(EquipmentRental.equipment_id, EquipmentRental.internal_rate_per_hour).where(
                            EquipmentRental.equipment_id.in_(equipment_ids),
                            EquipmentRental.project_id == project_id,
                        )
                    )
                ).all()
                for equipment_id, rate in rows:
                    key = str(equipment_id)
                    value = _dec(rate)
                    if value > plant_rates.get(key, Decimal("0")):
                        plant_rates[key] = value
            except Exception:
                logger.debug("Plant-rate lookup unavailable for %s", project_id, exc_info=True)

        return labour_rates, plant_rates

    # ── Actual side: material consumed on site ───────────────────────────────

    async def _load_material_actuals(
        self,
        project_id: uuid.UUID,
        positions: Sequence[Any],
        currency: str,
    ) -> dict[uuid.UUID, Decimal]:
        """Priced material consumed per position, from the site inventory ledger.

        The estimate says what a position's material should cost; the store
        records what was actually drawn against it and what it was bought for.
        Reconciling the two is the half of a post-calculation that a labour
        factor cannot see, and until this existed the report said material cost
        was unknown on every project that had metered its yard.

        Attribution follows the inventory module's own rule
        (:func:`app.modules.site_inventory.ledger.resolve_positions`): a
        movement's own position wins, and otherwise it inherits the position of
        the item it moved. Only ``CONSUMPTION`` counts, exactly as
        :func:`~app.modules.site_inventory.ledger.material_cost_variance` does,
        so this report and the inventory module's own variance screen can never
        disagree about what a position's material cost.

        A position is left out of the result - unknown, never zero - when:

        * nothing was consumed against it (an unmetered position is not a
          position that used no material);
        * any of its consumption carries no unit cost, because a zero-priced
          issue makes the total an understatement rather than a figure;
        * its money is labelled in a currency the project does not report in, or
          in more than one, because two currencies have no common sum.

        Returns ``{position_id: consumed cost}`` for the positions that pass.
        """
        position_ids = {pos.id for pos in positions}
        if not position_ids:
            return {}
        try:
            from sqlalchemy import select

            from app.modules.site_inventory import ledger
            from app.modules.site_inventory.models import StockItem, StockMovement

            # Column selects, not entity selects: loading ``StockItem`` rows
            # would pull every movement a second time through the item's
            # selectin relationship.
            item_rows = (
                await self.session.execute(
                    select(StockItem.id, StockItem.boq_position_id).where(StockItem.project_id == project_id)
                )
            ).all()
            movement_rows = (
                await self.session.execute(
                    select(
                        StockMovement.item_id,
                        StockMovement.movement_type,
                        StockMovement.quantity,
                        StockMovement.unit_cost,
                        StockMovement.currency,
                        StockMovement.boq_position_id,
                    ).where(StockMovement.project_id == project_id)
                )
            ).all()
        except Exception:
            logger.debug("Site inventory actuals unavailable for %s", project_id, exc_info=True)
            return {}

        if not movement_rows:
            return {}

        items = [
            ledger.StockItemRef(
                item_id=str(item_id),
                boq_position_id=str(position_id) if position_id else None,
            )
            for item_id, position_id in item_rows
        ]
        movements = [
            ledger.Movement(
                movement_type=str(movement_type),
                quantity=_dec(quantity),
                unit_cost=_dec(unit_cost),
                currency=str(mv_currency or "").strip(),
                item_id=str(item_id),
                boq_position_id=str(position_id) if position_id else None,
            )
            for item_id, movement_type, quantity, unit_cost, mv_currency, position_id in movement_rows
        ]

        out: dict[uuid.UUID, Decimal] = {}
        for key, cost in consumed_material_cost(movements, items, project_currency=currency).items():
            try:
                position_id = uuid.UUID(key)
            except (ValueError, AttributeError, TypeError):
                continue
            if position_id in position_ids:
                out[position_id] = cost
        return out

    # ── Actual side: installed quantities ────────────────────────────────────

    async def _load_installed_quantities(
        self,
        project_id: uuid.UUID,
        positions: Sequence[Any],
    ) -> dict[uuid.UUID, Decimal]:
        """Installed quantity per position = planned quantity * latest percent / 100.

        Best-effort: without the progress module (or with no readings yet) every
        installed quantity is zero, and the compute treats such lines as having no
        progress to compare rather than failing.
        """
        position_ids = [pos.id for pos in positions]
        if not position_ids:
            return {}
        try:
            from app.modules.progress.repository import ProgressRepository

            pct_by_pid = await ProgressRepository(self.session).latest_pct_for_positions(project_id, position_ids)
        except Exception:
            logger.debug("Progress actuals unavailable for %s", project_id, exc_info=True)
            return {}

        installed: dict[uuid.UUID, Decimal] = {}
        planned_by_pid = {pos.id: _dec(pos.quantity) for pos in positions}
        for pid, pct in pct_by_pid.items():
            planned = planned_by_pid.get(pid, Decimal("0"))
            installed[pid] = planned * _dec(pct) / _HUNDRED
        return installed
