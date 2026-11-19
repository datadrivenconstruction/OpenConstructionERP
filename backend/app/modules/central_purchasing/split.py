# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Award split arithmetic for a bundle. Pure Decimal, no database.

F1  share completeness: per line, the shares add up to the line quantity exactly.
F2  unit-price split: cell = round2(share x rate); project gross = sum of its cells;
    project net = round2(gross x (1 - d)); the sum of project nets must equal
    round2(bundle gross x (1 - d)) and a cent left over goes to the largest project.
F3  lump sum over priced lines: each cell x (lump / cells sum), round2, the
    remainder to the last cell in line order.
F4  budget: project net against its budget, with a tolerance in percent.
F5  call-off consumption per (line, project): headroom = share - used.

Rounding is ROUND_HALF_UP to the cent everywhere. Within a project the net is
spread back over its cells the same way (largest cell takes the cent), so the
document lines a project receives add up to exactly its net.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
RATE_PLACES = Decimal("0.0001")
ZERO = Decimal("0")
HUNDRED = Decimal("100")


def round2(value: Decimal) -> Decimal:
    """Round to the cent, half up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def round4(value: Decimal) -> Decimal:
    return value.quantize(RATE_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineIn:
    """A bundle line as the split sees it. ``shares`` maps project key -> quantity (None = blank)."""

    key: Hashable
    code: str
    unit: str
    quantity: Decimal
    rate: Decimal | None
    shares: dict[Hashable, Decimal | None]


@dataclass
class Cell:
    gross: Decimal = ZERO
    net: Decimal = ZERO


@dataclass
class ProjectSplit:
    gross: Decimal = ZERO
    net: Decimal = ZERO

    @property
    def discount(self) -> Decimal:
        return self.gross - self.net


@dataclass
class SplitResult:
    """Cells keyed ``(line_key, project_key)``; projects keyed by project key, in input order."""

    cells: dict[tuple[Hashable, Hashable], Cell] = field(default_factory=dict)
    projects: dict[Hashable, ProjectSplit] = field(default_factory=dict)
    gross: Decimal = ZERO
    net: Decimal = ZERO
    target: Decimal = ZERO
    #: Per line, the factor that turns an awarded rate into the rate each document carries.
    factor: Decimal = Decimal("1")

    @property
    def reconciles(self) -> bool:
        return sum((p.net for p in self.projects.values()), ZERO) == self.target


@dataclass(frozen=True)
class ShareGap:
    """A blank share (``missing``) or a line whose shares do not add up (``mismatch``)."""

    kind: str
    line_code: str
    project: Hashable | None = None
    total: Decimal | None = None
    quantity: Decimal | None = None


def share_gaps(lines: Sequence[LineIn], projects: Sequence[Hashable]) -> list[ShareGap]:
    """F1: every project has a share on every line, and the shares add up exactly."""
    out: list[ShareGap] = []
    for line in lines:
        total = ZERO
        for project in projects:
            qty = line.shares.get(project)
            if qty is None:
                out.append(ShareGap("missing", line.code, project=project))
            else:
                total += qty
        if total != line.quantity:
            out.append(ShareGap("mismatch", line.code, total=total, quantity=line.quantity))
    return out


def _largest(values: dict[Hashable, Decimal]) -> Hashable:
    """Key of the largest value; the first one in order on a tie."""
    best_key, best = None, None
    for key, value in values.items():
        if best is None or value > best:
            best_key, best = key, value
    return best_key


def _spread(total: Decimal, parts: dict[Hashable, Decimal], factor: Decimal) -> dict[Hashable, Decimal]:
    """round2(part x factor) each, the leftover cent on the largest part, so the parts sum to ``total``."""
    out = {k: round2(v * factor) for k, v in parts.items()}
    if out:
        diff = total - sum(out.values(), ZERO)
        if diff:
            key = _largest(parts)
            out[key] += diff
    return out


def split_award(
    lines: Sequence[LineIn],
    projects: Sequence[Hashable],
    *,
    discount_pct: Decimal | None = None,
    lump_sum: Decimal | None = None,
) -> SplitResult:
    """Split an award over the projects of a bundle (F2, or F3 when ``lump_sum`` is given).

    A line with no rate or a blank share contributes nothing; the share rules
    report those, the split never guesses.
    """
    result = SplitResult()
    order: list[tuple[Hashable, Hashable]] = []
    for line in lines:
        for project in projects:
            qty = line.shares.get(project)
            if qty is None or line.rate is None:
                continue
            key = (line.key, project)
            result.cells[key] = Cell(gross=round2(qty * line.rate))
            order.append(key)
    for project in projects:
        result.projects[project] = ProjectSplit(
            gross=sum((c.gross for (_, p), c in result.cells.items() if p == project), ZERO)
        )
    result.gross = sum((p.gross for p in result.projects.values()), ZERO)

    if lump_sum is not None:
        result.target = round2(lump_sum)
        if result.gross:
            factor = result.target / result.gross
            result.factor = factor
            running = ZERO
            for i, key in enumerate(order):
                cell = result.cells[key]
                if i == len(order) - 1:
                    cell.net = result.target - running
                else:
                    cell.net = round2(cell.gross * factor)
                    running += cell.net
        for project, split in result.projects.items():
            split.net = sum((c.net for (_, p), c in result.cells.items() if p == project), ZERO)
    else:
        keep = Decimal("1") - (discount_pct or ZERO) / HUNDRED
        result.factor = keep
        result.target = round2(result.gross * keep)
        nets = {p: round2(s.gross * keep) for p, s in result.projects.items()}
        diff = result.target - sum(nets.values(), ZERO)
        if diff and nets:
            nets[_largest(nets)] += diff
        for project, split in result.projects.items():
            split.net = nets[project]
            cells = {k: c.gross for k, c in result.cells.items() if k[1] == project}
            for key, net in _spread(split.net, cells, keep).items():
                result.cells[key].net = net
    result.net = sum((p.net for p in result.projects.values()), ZERO)
    return result


def document_rate(rate: Decimal, factor: Decimal) -> Decimal:
    """The unit rate a call-off or document line carries: the awarded rate after discount or lump factor."""
    return round4(rate * factor)


@dataclass(frozen=True)
class BudgetCheck:
    over: bool
    delta: Decimal


def budget_check(net: Decimal, budget: Decimal | None, tolerance_pct: Decimal = ZERO) -> BudgetCheck:
    """F4: the project's net against its budget; no budget means nothing to compare."""
    if budget is None or budget <= ZERO:
        return BudgetCheck(False, ZERO)
    delta = net - budget
    return BudgetCheck(net > budget * (Decimal("1") + tolerance_pct / HUNDRED), delta)


def headroom(share: Decimal, used: Decimal) -> Decimal:
    """F5: what a project may still call off on one line."""
    return share - used
