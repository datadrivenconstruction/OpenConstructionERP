# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan a schedule from a bill of quantities, without touching the database.

:meth:`ScheduleService.generate_from_boq` reads the bill, asks this module how
to lay it out, and writes what comes back. Keeping the planning pure lets the
rules be tested on their own and stated in a few sentences a site manager can
check against the Gantt chart:

1. Every section of the bill, at any depth, becomes a summary bar, and every
   priced position becomes exactly one task under it. Empty sections, blank
   rows nobody filled in and positions with no quantity are left out, each
   with its reason.
2. Inside a section, up to ``crews`` items (positions or sub-sections) run at
   the same time. Items are taken in bill order and each goes to the crew that
   becomes free first; a crew does its items one after the other. The crews
   are one budget for the section: a sub-section is worked by the share of
   them its lane holds, not by a full set of its own. Loose positions next to
   each other at the top are worked the same way, as if they were a section.
3. Each next top-level section starts once half of the previous one's work
   is done, counted in crew-days rather than read off the calendar: one long
   item running beside short ones (scaffolding standing for months) no
   longer holds the next trade back for half its length. In a section worked
   one item after another the two measures agree.
4. The fewest crews that fit the requested window are used, up to
   :data:`MAX_CREWS`. When even that is too long and the caller allows it, all
   durations are shortened by one common factor, never below
   :data:`MIN_COMPRESSION` of the estimate. When the plan still cannot fit,
   it is laid out at that floor and the caller reports the planned end, so
   asking for a day less never makes the plan longer.
5. A lump sum standing on its own at the top of the bill, outside every
   section (site costs, safety, insurance), is not a step in the sequence: it
   runs from the first day to the last and leaves the sections to overlap as
   rule 3 says. Only when the whole bill is such lump sums are they worked
   like any loose positions.

Durations here are working days; offsets count working days from the first
day of the plan, with ``finish`` exclusive.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

# Most crews one section is given at once. Four keeps a big section readable on
# the chart and is a number a site manager recognises as a real gang count.
MAX_CREWS = 4

# Shortest a duration may be squeezed to fit a window, as a share of its
# estimate. Below that the plan says it does not fit rather than turning forty
# days of work into two.
MIN_COMPRESSION = 0.5

# Steps of the search for the common shortening factor.
_COMPRESS_STEPS = 30


@dataclass(frozen=True)
class BoqRow:
    """One bill row as the planner needs it.

    Attributes:
        id: Position id.
        parent_id: Parent position id, or ``None`` at the top.
        is_section: True for a section header (no quantity, no rate).
        is_placeholder: True for a blank row nobody filled in yet.
        data: Whatever the caller wants back on the planned item.
        has_work: False for a position with no quantity: nothing to build, so
            no task, though rows under it still form a group.
        lump_sum: True for a position priced as a lump sum.
    """

    id: str
    parent_id: str | None
    is_section: bool
    is_placeholder: bool
    data: dict[str, Any]
    has_work: bool = True
    lump_sum: bool = False


@dataclass
class Task:
    """A unit of work: one priced position."""

    row: BoqRow

    @property
    def key(self) -> str:
        return f"t:{self.row.id}"


@dataclass
class Group:
    """A section (or a priced position with rows under it) holding items."""

    row: BoqRow
    items: list[Group | Task] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"g:{self.row.id}"


Item = Group | Task


# Why a row was left out of the plan.
SKIP_EMPTY_SECTION = "empty_section_dropped"
SKIP_BLANK_ROW = "blank_row_dropped"
SKIP_ZERO_QUANTITY = "skipped_zero_qty"


@dataclass
class PlanTree:
    """The bill as groups and tasks, plus the rows left out and why."""

    roots: list[Item]
    skipped_rows: list[tuple[BoqRow, str]] = field(default_factory=list)

    @property
    def skipped(self) -> int:
        return len(self.skipped_rows)


@dataclass
class Slot:
    """Where an item sits: working-day offsets and the item before it on its crew."""

    start: int
    finish: int
    predecessor: str | None = None


@dataclass
class Layout:
    """A laid-out plan.

    Attributes:
        slots: Item key to its slot, for groups and tasks alike.
        root_links: ``(previous_root_key, root_key, lag)`` start-to-start links
            between consecutive top-level items.
        span: Working days from the first start to the last finish.
        spanning: Position ids of the loose lump sums that run for the whole
            works (rule 5).
    """

    slots: dict[str, Slot]
    root_links: list[tuple[str, str, int]]
    span: int
    spanning: frozenset[str] = frozenset()


@dataclass
class PlanFit:
    """The layout chosen for a window.

    Attributes:
        crews: Crews per section the layout uses.
        durations: Task durations the layout uses, keyed by position id.
        layout: The layout itself.
        fits: Whether ``layout.span`` is within the budget.
        compressed_pct: The common factor durations were shortened to, in
            percent, or ``None`` when they were not shortened.
    """

    crews: int
    durations: dict[str, int]
    layout: Layout
    fits: bool
    compressed_pct: int | None


def build_plan_tree(rows: list[BoqRow]) -> PlanTree:
    """Turn bill rows, in bill order, into groups and tasks.

    A row whose parent is missing becomes a top-level item; a parent loop is
    broken at the row that would close it. A section header or a blank row
    with nothing under it is left out (counted in ``skipped``); a priced
    position with rows under it becomes a group whose first item is its own
    task, so its work is not lost. A position with no quantity is left out
    when nothing hangs under it, and becomes a plain group when something
    does.

    Args:
        rows: The bill's rows in bill order.

    Returns:
        The tree and the rows left out, each with its reason.
    """
    by_id = {r.id: r for r in rows}
    parent_of: dict[str, str | None] = {}
    children: dict[str | None, list[str]] = {}

    for r in rows:
        parent = r.parent_id if r.parent_id in by_id and r.parent_id != r.id else None
        # Walk up from the parent; reaching this row means the link closes a loop.
        cursor, steps = parent, 0
        while cursor is not None and steps <= len(rows):
            if cursor == r.id:
                parent = None
                break
            cursor = parent_of.get(cursor)
            steps += 1
        parent_of[r.id] = parent
        children.setdefault(parent, []).append(r.id)

    skipped_rows: list[tuple[BoqRow, str]] = []

    def _build(row_id: str) -> Item | None:
        row = by_id[row_id]
        kids = [item for kid in children.get(row_id, []) if (item := _build(kid)) is not None]
        is_work = not row.is_section and not row.is_placeholder and row.has_work
        if kids:
            group = Group(row=row)
            if is_work:
                group.items.append(Task(row=row))
            group.items.extend(kids)
            return group
        if is_work:
            return Task(row=row)
        if row.is_section:
            reason = SKIP_EMPTY_SECTION
        elif row.is_placeholder:
            reason = SKIP_BLANK_ROW
        else:
            reason = SKIP_ZERO_QUANTITY
        skipped_rows.append((row, reason))
        return None

    # Iterative pre-check is unnecessary: bills nest a handful of levels deep
    # (the editor caps it at eight), far inside the recursion limit.
    roots = [item for rid in children.get(None, []) if (item := _build(rid)) is not None]
    return PlanTree(roots=roots, skipped_rows=skipped_rows)


def iter_tasks(items: list[Item]) -> Iterator[Task]:
    """Yield every task under ``items``, depth first, in bill order."""
    for item in items:
        if isinstance(item, Task):
            yield item
        else:
            yield from iter_tasks(item.items)


def iter_items(items: list[Item]) -> Iterator[tuple[Item, Group | None]]:
    """Yield every item with its enclosing group, parents before children."""
    stack: list[tuple[Item, Group | None]] = [(i, None) for i in reversed(items)]
    while stack:
        item, parent = stack.pop()
        yield item, parent
        if isinstance(item, Group):
            stack.extend((child, item) for child in reversed(item.items))


def _lay_out_group(
    items: list[Item],
    origin: int,
    durations: Mapping[str, int],
    crews: int,
    slots: dict[str, Slot],
) -> int:
    """Place ``items`` from ``origin`` on up to ``crews`` crews; return the span.

    The crews are one budget for the whole group, sub-sections included: a
    sub-section placed on a lane is worked by that lane's share of the crews,
    so a deep bill never runs more items at once than a flat one.
    """
    if not items:
        return 0
    lanes = min(max(1, crews), len(items))
    share = [crews // lanes + (1 if lane < crews % lanes else 0) for lane in range(lanes)]
    free_at = [origin] * lanes
    last_on_lane: list[str | None] = [None] * lanes
    for item in items:
        lane = min(range(lanes), key=lambda i: free_at[i])
        start = free_at[lane]
        if isinstance(item, Task):
            finish = start + max(1, durations.get(item.row.id, 1))
        else:
            finish = start + _lay_out_group(item.items, start, durations, share[lane], slots)
        slots[item.key] = Slot(start=start, finish=finish, predecessor=last_on_lane[lane])
        last_on_lane[lane] = item.key
        free_at[lane] = finish
    return max(free_at) - origin


def _half_work_offset(item: Item, slots: Mapping[str, Slot]) -> int:
    """Working days from ``item``'s start until half of its task work is done.

    Work is counted in crew-days: each task adds one per working day it runs.
    Never later than half the item's length on the calendar, which is what it
    equals when the tasks run one after another. One sweep over the days on
    which tasks start or finish, so a section of ten thousand positions costs
    a sort, not ten thousand passes.
    """
    own = slots[item.key]
    half_span = max(1, math.ceil((own.finish - own.start) / 2))
    if isinstance(item, Task):
        return half_span
    change: dict[int, int] = {}
    total = 0
    for task in iter_tasks(item.items):
        slot = slots[task.key]
        start, finish = slot.start - own.start, slot.finish - own.start
        if finish <= start:
            continue
        change[start] = change.get(start, 0) + 1
        change[finish] = change.get(finish, 0) - 1
        total += finish - start
    if total <= 0:
        return half_span
    marks = sorted(change)
    done = 0
    running = 0
    for left, right in zip(marks, marks[1:], strict=False):
        running += change[left]
        if running and 2 * (done + running * (right - left)) >= total:
            needed = math.ceil((total / 2 - done) / running)
            return max(1, min(half_span, left + needed))
        done += running * (right - left)
    return half_span


def _sequence(roots: list[Item]) -> tuple[list[Item], list[Task], dict[str, Group]]:
    """Split the top level into the items worked in turn and the lump sums that span them.

    Loose positions next to each other at the top are worked like a section
    of their own, by the same crews: a bill with no sections is not a
    staircase of one position after another. Each such run stands in the
    sequence as a stand-in group whose key never leaves the layout.

    Returns:
        The sequence, the spanning lump sums, and each stand-in by its key.
    """
    spanning = [item for item in roots if isinstance(item, Task) and item.row.lump_sum]
    rest = [item for item in roots if not (isinstance(item, Task) and item.row.lump_sum)]
    if not rest:
        rest, spanning = list(roots), []
    sequence: list[Item] = []
    stand_ins: dict[str, Group] = {}
    run: list[Item] = []

    def _close_run() -> None:
        if len(run) > 1:
            stand_in = Group(
                row=BoqRow(
                    id=f"{_RUN_PREFIX}{len(stand_ins)}", parent_id=None, is_section=True, is_placeholder=False, data={}
                ),
                items=list(run),
            )
            stand_ins[stand_in.key] = stand_in
            sequence.append(stand_in)
        else:
            sequence.extend(run)
        run.clear()

    for item in rest:
        if isinstance(item, Task):
            run.append(item)
            continue
        _close_run()
        sequence.append(item)
    _close_run()
    return sequence, spanning, stand_ins


# Ids of the stand-in groups for runs of loose positions; never a position id.
_RUN_PREFIX = "\x00run:"


def layout_plan(roots: list[Item], durations: Mapping[str, int], crews: int) -> Layout:
    """Lay the plan out: crews inside sections, half-the-work overlap at the top.

    Args:
        roots: Top-level items.
        durations: Working days per task, keyed by position id.
        crews: Crews each section gets.

    Returns:
        The layout. Its slots and links name only items of ``roots``.
    """
    sequence, spanning, stand_ins = _sequence(roots)
    slots: dict[str, Slot] = {}
    chain: list[tuple[str, str, int]] = []
    start = 0
    span = 0
    previous: Item | None = None
    for item in sequence:
        if previous is not None:
            prev_slot = slots[previous.key]
            lag = _half_work_offset(previous, slots)
            start = prev_slot.start + lag
            chain.append((previous.key, item.key, lag))
        if isinstance(item, Task):
            finish = start + max(1, durations.get(item.row.id, 1))
        else:
            finish = start + _lay_out_group(item.items, start, durations, crews, slots)
        slots[item.key] = Slot(start=start, finish=finish)
        span = max(span, finish)
        previous = item

    # A stand-in is not an activity: a link into it goes to every first item
    # of its crews (they all start where it starts), a link out of it leaves
    # from its first position, which starts where it starts too.
    root_links: list[tuple[str, str, int]] = []
    for pred, succ, lag in chain:
        if pred in stand_ins:
            pred = stand_ins[pred].items[0].key
        if succ in stand_ins:
            root_links.extend(
                (pred, member.key, lag) for member in stand_ins[succ].items if slots[member.key].predecessor is None
            )
        else:
            root_links.append((pred, succ, lag))
    for key in stand_ins:
        del slots[key]

    for task in spanning:
        slots[task.key] = Slot(start=0, finish=max(1, span))
    return Layout(
        slots=slots,
        root_links=root_links,
        span=span,
        spanning=frozenset(task.row.id for task in spanning),
    )


def fit_plan(
    roots: list[Item],
    durations: Mapping[str, int],
    budget: int,
    *,
    allow_compress: bool,
) -> PlanFit:
    """Choose crews (and, if allowed, a shortening factor) to fit ``budget``.

    Args:
        roots: Top-level items.
        durations: Estimated working days per task, keyed by position id.
        budget: Working days the plan may span.
        allow_compress: Whether durations may be shortened to fit.

    Returns:
        The chosen layout. ``fits`` is False when no choice fits, and the
        layout then uses :data:`MAX_CREWS`. Durations are never shortened
        below :data:`MIN_COMPRESSION` of their estimate: a plan that needs
        more than that does not fit and is laid out at the floor (or at the
        estimates, when shortening is not allowed).
    """
    base = {k: max(1, int(v)) for k, v in durations.items()}
    layout = layout_plan(roots, base, 1)
    for crews in range(1, MAX_CREWS + 1):
        layout = layout_plan(roots, base, crews)
        if budget > 0 and layout.span <= budget:
            return PlanFit(crews=crews, durations=base, layout=layout, fits=True, compressed_pct=None)
    crews = MAX_CREWS
    if not allow_compress or budget <= 0:
        return PlanFit(crews=crews, durations=base, layout=layout, fits=False, compressed_pct=None)

    def _scaled(factor: float) -> dict[str, int]:
        return {k: max(1, math.floor(v * factor)) for k, v in base.items()}

    floor = _scaled(MIN_COMPRESSION)
    floor_layout = layout_plan(roots, floor, crews)
    if floor_layout.span > budget:
        # As close to the window as the floor allows. Falling back to the
        # estimates here would double the plan for a window one day shorter.
        return PlanFit(
            crews=crews,
            durations=floor,
            layout=floor_layout,
            fits=False,
            # One-day items cannot be halved; nothing was shortened then.
            compressed_pct=math.floor(MIN_COMPRESSION * 100) if floor != base else None,
        )

    low, high = MIN_COMPRESSION, 1.0  # ``low`` always fits, ``high`` never does
    for _ in range(_COMPRESS_STEPS):
        mid = (low + high) / 2
        if layout_plan(roots, _scaled(mid), crews).span <= budget:
            low = mid
        else:
            high = mid
    fitted = _scaled(low)
    return PlanFit(
        crews=crews,
        durations=fitted,
        layout=layout_plan(roots, fitted, crews),
        fits=True,
        compressed_pct=max(1, math.floor(low * 100)),
    )
