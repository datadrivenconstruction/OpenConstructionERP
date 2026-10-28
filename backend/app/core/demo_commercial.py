# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠One commercial story for every demo seeder that deals in money.

The reconciliation register and the earned-value baseline are shown one after
another in the same walkthrough: a viewer reads the margin on one screen and
the forecast on the next, and takes them for two views of one job. If each
seeder invents its own progress curve and its own budget, the two screens
disagree by construction, and the disagreement is worse than either screen
being empty - an empty screen says "no data", two confident and different
answers say the product cannot add up.

So the shape of the job lives here, once: how its money is spent month by
month, which packages it is made of, what each package was supposed to earn
and what it has actually cost. A seeder decides what to write; it does not
decide what the job is doing.

Nothing here reads or writes the database except :func:`bill_total`, which
totals the project's own priced bill. That total is the anchor for everything
downstream, because it is the figure the cost-model screen shows and therefore
the one a viewer will cross-check against.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Positions read when totalling a bill. Far above any demo project's line
# count; it exists so a pathological bill cannot turn a seed into a scan.
_POSITION_CAP = 20000

# How the job's money is spent month by month, from eleven months back to six
# months ahead. The entries sum to exactly 1. Every other figure in the demo
# commercial world is a share of this curve, which is the whole point of the
# module: one curve, so two screens cannot tell different stories.
MONTH_WEIGHTS: tuple[Decimal, ...] = (
    Decimal("0.020"),
    Decimal("0.030"),
    Decimal("0.040"),
    Decimal("0.050"),
    Decimal("0.060"),
    Decimal("0.070"),
    Decimal("0.075"),
    Decimal("0.080"),
    Decimal("0.080"),
    Decimal("0.078"),
    Decimal("0.075"),
    Decimal("0.070"),
    Decimal("0.062"),
    Decimal("0.055"),
    Decimal("0.045"),
    Decimal("0.035"),
    Decimal("0.050"),
    Decimal("0.025"),
)

# Index of the current month within the curve above.
CURRENT_INDEX = 11

# How far the work has fallen behind the money. The plan spends and earns
# together; this job is spending on plan and earning less, which is what makes
# the schedule index worth showing at all. A demo where planned and actual
# progress coincide reports SPI = 1 for ever and teaches nobody what the
# number is for.
SCHEDULE_SLIP = Decimal("0.10")

# No package is ever shown as finished. A reconciliation or a measurement
# taken against a completed package is a final account, which is a different
# document under different rules.
MAX_COMPLETION = Decimal("0.98")


@dataclass(frozen=True)
class CostHead:
    """One package of the job: its share, its margin, its overrun, its window.

    ``weight`` is the package's share of the priced bill, so the weights sum
    to one. ``margin`` is what it was priced to earn, and ``drift`` is what
    its cost has actually done against that plan - above one is an overrun,
    and above ``1 / (1 - margin)`` the package is losing money.

    ``opens`` and ``closes`` are the package's own window, expressed as the
    share of the job's money spent by the time it starts and finishes. They
    are a window rather than a speed, and that distinction is load-bearing: a
    package whose progress is a fixed multiple of the job's progress keeps the
    same share of the total for ever, so every month reconciles to exactly the
    same margin and the register reports a figure that never moves. Packages
    that start and finish at different times change the mix, and the mix is
    what a reconciliation is read for.
    """

    code: str
    name_de: str
    name_en: str
    weight: Decimal
    margin: Decimal
    drift: Decimal
    opens: Decimal
    closes: Decimal

    def budget_share(self) -> Decimal:
        """This package's share of the job's budgeted cost."""
        return self.weight * (Decimal("1") - self.margin)

    def net_margin(self) -> Decimal:
        """What the package is now expected to earn, after the overrun."""
        return Decimal("1") - (Decimal("1") - self.margin) * self.drift


# German projects get the DIN 276 cost groups because that is how their bills
# are already structured; everywhere else the same six packages under the names
# an English-language bill uses. The split is a property of the data, not of
# the interface, so it lives here rather than in a locale file.
#
# The services package is deliberately the one in trouble: its cost has drifted
# far enough past its budget that the package is losing money. A job where
# every package is comfortably in profit is a job nobody would have bothered to
# reconcile, and both screens exist to answer "which package is eating the
# margin" - a question that needs an answer on them.
HEADS: tuple[CostHead, ...] = (
    CostHead(
        code="300",
        name_de="KG 300 Bauwerk - Baukonstruktionen",
        name_en="Building fabric and structure",
        weight=Decimal("0.42"),
        margin=Decimal("0.09"),
        drift=Decimal("1.02"),
        opens=Decimal("0.05"),
        closes=Decimal("0.75"),
    ),
    CostHead(
        code="400",
        name_de="KG 400 Bauwerk - Technische Anlagen",
        name_en="Building services",
        weight=Decimal("0.26"),
        margin=Decimal("0.07"),
        drift=Decimal("1.14"),
        opens=Decimal("0.30"),
        closes=Decimal("0.95"),
    ),
    CostHead(
        code="500",
        name_de="KG 500 Außenanlagen und Freiflächen",
        name_en="External works",
        weight=Decimal("0.08"),
        margin=Decimal("0.10"),
        drift=Decimal("0.99"),
        opens=Decimal("0.35"),
        closes=Decimal("1.00"),
    ),
    CostHead(
        code="200",
        name_de="KG 200 Herrichten und Erschließen",
        name_en="Enabling works and site setup",
        weight=Decimal("0.07"),
        margin=Decimal("0.06"),
        drift=Decimal("1.01"),
        opens=Decimal("0.00"),
        closes=Decimal("0.18"),
    ),
    CostHead(
        code="700",
        name_de="KG 700 Baunebenkosten",
        name_en="Preliminaries and overheads",
        weight=Decimal("0.12"),
        margin=Decimal("0.12"),
        drift=Decimal("1.00"),
        opens=Decimal("0.00"),
        closes=Decimal("1.00"),
    ),
    CostHead(
        code="NT",
        name_de="Nachträge (beauftragt)",
        name_en="Instructed variations",
        weight=Decimal("0.05"),
        margin=Decimal("0.15"),
        drift=Decimal("0.97"),
        opens=Decimal("0.35"),
        closes=Decimal("0.90"),
    ),
)


def planned_progress(index: int) -> Decimal:
    """Share of the job's money the plan has spent by the end of month *index*."""
    return sum(MONTH_WEIGHTS[: index + 1], Decimal("0"))


def actual_progress(index: int) -> Decimal:
    """Where the work has actually got to by the end of month *index*.

    Behind the plan by a fixed amount, which is what gives the earned-value
    screen a schedule variance to report and the reconciliation a mix that
    keeps changing.
    """
    return max(Decimal("0"), planned_progress(index) - SCHEDULE_SLIP)


def completion(head: CostHead, overall: Decimal) -> Decimal:
    """How far *head* has got when the job as a whole has got to *overall*.

    Linear across the package's own window and clamped at both ends: nothing
    before it opens, and never quite finished.
    """
    elapsed = (overall - head.opens) / (head.closes - head.opens)
    return max(Decimal("0"), min(elapsed, MAX_COMPLETION))


def budget_margin() -> Decimal:
    """The margin the job was priced to earn, before anything overran."""
    return sum((head.weight * head.margin for head in HEADS), Decimal("0"))


def forecast_margin() -> Decimal:
    """The margin the job is now expected to earn, overruns included."""
    return sum((head.weight * head.net_margin() for head in HEADS), Decimal("0"))


def budget_share_total() -> Decimal:
    """Share of the bill that is budgeted cost rather than margin."""
    return sum((head.budget_share() for head in HEADS), Decimal("0"))


def shift_month(anchor: date, months: int) -> date:
    """The first day of the month *months* away from *anchor*."""
    total = anchor.year * 12 + (anchor.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def month_end(day: date) -> date:
    """The last day of the month *day* falls in."""
    following = shift_month(day, 1)
    return date.fromordinal(following.toordinal() - 1)


def is_demo_project(metadata: dict | None) -> bool:
    """Whether a project row belongs to the demo estate.

    The boot backfill hands every seeder every project on the installation and
    re-runs on each version upgrade, so on a customer installation a real
    project that has recorded no commercial reporting looks exactly like an
    unseeded demo one. A reconciliation or a baseline states what a job earned
    and what it cost; inventing one inside somebody's live project is a data
    incident rather than an untidy screen, which is why the gate is ownership
    and never emptiness.
    """
    if not isinstance(metadata, dict):
        return False
    return bool(str(metadata.get("demo_id") or "").strip())


def _to_decimal(value: object) -> Decimal | None:
    """Parse a bill money string, or ``None`` when the cell is not money.

    Bill money columns are strings by design, so a project can and does carry
    blanks and free text there. An unparseable cell contributes nothing to the
    total rather than taking the caller's savepoint down with it.
    """
    if value is None:
        return None
    try:
        parsed = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


async def bill_total(session: AsyncSession, project_id: uuid.UUID) -> Decimal:
    """Total the project's priced bill, or zero when it has none.

    Summed in Python rather than in SQL because the money column is text: an
    aggregate over it is an error on PostgreSQL, not a zero.
    """
    try:
        from app.modules.boq.models import BOQ, Position

        stmt = (
            select(Position.total)
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id, Position.unit != "")
            .limit(_POSITION_CAP)
        )
        rows = (await session.execute(stmt)).scalars().all()
    except Exception:
        logger.debug("Bill lookup unavailable for project=%s", project_id)
        return Decimal("0")
    total = Decimal("0")
    for raw in rows:
        parsed = _to_decimal(raw)
        if parsed is not None and parsed > 0:
            total += parsed
    return total


__all__ = [
    "CURRENT_INDEX",
    "HEADS",
    "MAX_COMPLETION",
    "MONTH_WEIGHTS",
    "SCHEDULE_SLIP",
    "CostHead",
    "actual_progress",
    "bill_total",
    "budget_margin",
    "budget_share_total",
    "completion",
    "forecast_margin",
    "is_demo_project",
    "month_end",
    "planned_progress",
    "shift_month",
]
