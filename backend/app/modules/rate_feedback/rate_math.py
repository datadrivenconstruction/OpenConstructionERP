# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure maths for estimate-vs-actual rate feedback.

Input is one observation per closed-project bill line that is linked to a cost
item. Output is one statistic per cost item. No I/O, so every number here can
be checked by hand.

The cost side is a ratio, not an absolute rate: actual labour plus material
money divided by the money the estimate allowed for the quantity actually
installed. A cost item's rate also carries plant, subcontract and overhead that
the site ledgers do not measure, so the measured part is scaled onto the whole
rate instead of being mistaken for it. The ratio is dimensionless, which keeps
projects in different currencies comparable.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import pstdev

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
DEFAULT_TOLERANCE = Decimal("0.05")
# Projects needed before the sample term of the confidence reaches 1.0.
FULL_CONFIDENCE_PROJECTS = 5
_Q4 = Decimal("0.0001")
_Q2 = Decimal("0.01")


@dataclass(frozen=True)
class LineObservation:
    """One closed-project bill line linked to a cost item."""

    project_id: str
    cost_item_id: str
    quantity: Decimal
    earned_cost: Decimal | None = None
    actual_cost: Decimal | None = None
    actual_hours: Decimal | None = None
    planned_hours_per_unit: Decimal | None = None


@dataclass
class RateStat:
    """What the closed projects say about one cost item."""

    cost_item_id: str
    project_count: int
    line_count: int
    total_quantity: Decimal
    cost_ratio: Decimal | None
    spread_pct: Decimal | None
    observed_hours_per_unit: Decimal | None
    planned_hours_per_unit: Decimal | None
    hours_variance_pct: Decimal | None
    confidence: Decimal
    project_ids: list[str] = field(default_factory=list)

    @property
    def cost_variance_pct(self) -> Decimal | None:
        """Rate change in percent (positive = the site cost more than estimated)."""
        if self.cost_ratio is None:
            return None
        return ((self.cost_ratio - ONE) * HUNDRED).quantize(_Q2)


def confidence_of(project_count: int, spread: Decimal | None) -> Decimal:
    """Sample size times consistency, in 0..1. One project is never high."""
    if project_count <= 0:
        return ZERO
    sample = min(ONE, Decimal(project_count) / Decimal(FULL_CONFIDENCE_PROJECTS))
    consistency = ONE if spread is None else ONE / (ONE + spread)
    return (sample * consistency).quantize(_Q4)


def _ratio(actual: Decimal, earned: Decimal) -> Decimal | None:
    return actual / earned if earned > 0 else None


def _costed(rows: Sequence[LineObservation]) -> list[LineObservation]:
    return [r for r in rows if r.actual_cost is not None and r.earned_cost is not None]


def aggregate(observations: Iterable[LineObservation]) -> list[RateStat]:
    """Pool observations per cost item across projects."""
    by_item: dict[str, list[LineObservation]] = defaultdict(list)
    for obs in observations:
        if obs.quantity > 0:
            by_item[obs.cost_item_id].append(obs)
    stats = [_stat_of(item_id, rows) for item_id, rows in by_item.items()]
    stats.sort(key=lambda s: s.cost_item_id)
    return stats


def _stat_of(item_id: str, rows: Sequence[LineObservation]) -> RateStat:
    projects: dict[str, list[LineObservation]] = defaultdict(list)
    for row in rows:
        projects[row.project_id].append(row)

    costed = _costed(rows)
    cost_ratio = _ratio(sum((r.actual_cost for r in costed), ZERO), sum((r.earned_cost for r in costed), ZERO))

    per_project: list[float] = []
    for group in projects.values():
        part = _costed(group)
        ratio = _ratio(sum((r.actual_cost for r in part), ZERO), sum((r.earned_cost for r in part), ZERO))
        if ratio is not None:
            per_project.append(float(ratio))
    spread: Decimal | None = None
    if len(per_project) >= 2:
        mean = sum(per_project) / len(per_project)
        if mean > 0:
            spread = Decimal(str(pstdev(per_project) / mean)).quantize(_Q4)

    timed = [r for r in rows if r.actual_hours is not None and r.planned_hours_per_unit is not None]
    timed_qty = sum((r.quantity for r in timed), ZERO)
    observed_hpu = planned_hpu = hours_var = None
    if timed_qty > 0:
        observed_hpu = (sum((r.actual_hours for r in timed), ZERO) / timed_qty).quantize(_Q4)
        planned_hpu = (sum((r.planned_hours_per_unit * r.quantity for r in timed), ZERO) / timed_qty).quantize(_Q4)
        if planned_hpu > 0:
            hours_var = ((observed_hpu / planned_hpu - ONE) * HUNDRED).quantize(_Q2)

    return RateStat(
        cost_item_id=item_id,
        project_count=len(projects),
        line_count=len(rows),
        total_quantity=sum((r.quantity for r in rows), ZERO),
        cost_ratio=cost_ratio.quantize(_Q4) if cost_ratio is not None else None,
        spread_pct=(spread * HUNDRED).quantize(_Q2) if spread is not None else None,
        observed_hours_per_unit=observed_hpu,
        planned_hours_per_unit=planned_hpu,
        hours_variance_pct=hours_var,
        confidence=confidence_of(len(projects), spread),
        project_ids=sorted(projects),
    )


def deviates(stat: RateStat, tolerance: Decimal = DEFAULT_TOLERANCE) -> bool:
    """True when cost or hours leave the on-plan band."""
    if stat.cost_ratio is not None and abs(stat.cost_ratio - ONE) >= tolerance:
        return True
    return stat.hours_variance_pct is not None and abs(stat.hours_variance_pct) >= tolerance * HUNDRED


def suggested_rate(current_rate: Decimal, stat: RateStat) -> Decimal:
    """The current rate scaled by the measured cost ratio (unchanged without one)."""
    if stat.cost_ratio is None:
        return current_rate.quantize(_Q4)
    return (current_rate * stat.cost_ratio).quantize(_Q4)
