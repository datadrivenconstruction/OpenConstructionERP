"""Unit tests for the BOQ-to-schedule planner (:mod:`app.modules.schedule.boq_plan`).

The planner is pure: it turns the bill's tree into groups and work items, lays
the work items out in crews, and fits the layout into a window. These tests pin
the rules a site manager is told about:

* every priced position of the bill becomes exactly one task, at any depth;
* inside a section, up to ``crews`` items run at once, each item taken in bill
  order by the crew that frees up first, and a crew does its items one after
  the other;
* each next top-level section starts once half of the previous one's work is
  done, counted in crew-days, and never later than half its length;
* the fewest crews that fit the window are used, and a plan that cannot fit
  says so instead of quietly running past the window;
* a lump sum on its own at the top of the bill runs for the whole works.
"""

from __future__ import annotations

import random
import time

import pytest

from app.modules.schedule.boq_plan import (
    MAX_CREWS,
    MIN_COMPRESSION,
    BoqRow,
    Group,
    Task,
    build_plan_tree,
    fit_plan,
    iter_tasks,
    layout_plan,
)


def _row(
    row_id: str,
    parent: str | None = None,
    *,
    section: bool = False,
    placeholder: bool = False,
    has_work: bool = True,
    lump_sum: bool = False,
) -> BoqRow:
    return BoqRow(
        id=row_id,
        parent_id=parent,
        is_section=section,
        is_placeholder=placeholder,
        data={"id": row_id},
        has_work=has_work,
        lump_sum=lump_sum,
    )


def _task_ids(roots: list[Group | Task]) -> list[str]:
    return [t.row.id for t in iter_tasks(roots)]


# ── Tree ─────────────────────────────────────────────────────────────────────


def test_every_leaf_at_any_depth_is_one_task() -> None:
    # Italian bill: capitolo > categoria > voce, plus a voce straight under a
    # capitolo and a loose voce with no section at all.
    rows = [
        _row("cap1", section=True),
        _row("cat1", "cap1", section=True),
        _row("v1", "cat1"),
        _row("v2", "cat1"),
        _row("v3", "cap1"),
        _row("cap2", section=True),
        _row("cat2", "cap2", section=True),
        _row("sub2", "cat2", section=True),
        _row("v4", "sub2"),
        _row("loose"),
    ]
    tree = build_plan_tree(rows)
    ids = _task_ids(tree.roots)
    assert sorted(ids) == ["loose", "v1", "v2", "v3", "v4"]
    assert len(ids) == len(set(ids))
    cap2 = tree.roots[1]
    assert isinstance(cap2, Group)
    assert isinstance(cap2.items[0], Group) and cap2.items[0].row.id == "cat2"
    assert isinstance(cap2.items[0].items[0], Group) and cap2.items[0].items[0].row.id == "sub2"


def test_empty_sections_and_placeholders_are_dropped() -> None:
    rows = [
        _row("s1", section=True),
        _row("s1a", "s1", section=True),  # only holds an empty section
        _row("s1b", "s1a", section=True),
        _row("s2", section=True),
        _row("p", "s2"),
        _row("blank", "s2", placeholder=True),
    ]
    tree = build_plan_tree(rows)
    assert [r.row.id for r in tree.roots] == ["s2"]
    assert _task_ids(tree.roots) == ["p"]
    assert tree.skipped == 4
    assert sorted(reason for _, reason in tree.skipped_rows) == [
        "blank_row_dropped",
        "empty_section_dropped",
        "empty_section_dropped",
        "empty_section_dropped",
    ]


def test_a_position_with_no_quantity_is_skipped_but_its_rows_stay() -> None:
    # "Trasporto a discarica" with quantity 0 has nothing to build; a zero row
    # that carries rows under it still groups them.
    rows = [
        _row("s", section=True),
        _row("zero", "s", has_work=False),
        _row("p", "s"),
        _row("zero_parent", "s", has_work=False),
        _row("child", "zero_parent"),
    ]
    tree = build_plan_tree(rows)
    assert _task_ids(tree.roots) == ["p", "child"]
    assert [(r.id, reason) for r, reason in tree.skipped_rows] == [("zero", "skipped_zero_qty")]
    group = tree.roots[0]
    assert isinstance(group, Group) and isinstance(group.items[1], Group)
    assert group.items[1].row.id == "zero_parent"


def test_a_priced_position_with_children_keeps_its_own_task() -> None:
    rows = [_row("pos"), _row("child", "pos")]
    tree = build_plan_tree(rows)
    group = tree.roots[0]
    assert isinstance(group, Group)
    assert _task_ids(tree.roots) == ["pos", "child"]


def test_orphans_and_cycles_do_not_lose_positions() -> None:
    rows = [
        _row("a", "missing-parent"),
        _row("b", "c"),
        _row("c", "b"),
    ]
    tree = build_plan_tree(rows)
    # A row whose parent is missing becomes a root; a parent loop is broken at
    # the row that would close it, so every row still becomes exactly one task.
    assert sorted(_task_ids(tree.roots)) == ["a", "b", "c"]
    assert tree.roots[0].row.id == "a"


# ── Layout ───────────────────────────────────────────────────────────────────


def _one_section(n: int) -> list[Group | Task]:
    rows = [_row("s", section=True)] + [_row(f"p{i}", "s") for i in range(n)]
    return build_plan_tree(rows).roots


def test_one_crew_runs_a_section_back_to_back() -> None:
    roots = _one_section(3)
    layout = layout_plan(roots, {"p0": 2, "p1": 3, "p2": 4}, crews=1)
    assert [(layout.slots[k].start, layout.slots[k].finish) for k in ("t:p0", "t:p1", "t:p2")] == [
        (0, 2),
        (2, 5),
        (5, 9),
    ]
    assert layout.span == 9
    assert layout.slots["t:p1"].predecessor == "t:p0"
    assert layout.slots["t:p0"].predecessor is None
    assert (layout.slots["g:s"].start, layout.slots["g:s"].finish) == (0, 9)


def test_crews_take_items_in_bill_order_from_whoever_is_free_first() -> None:
    roots = _one_section(6)
    durations = {f"p{i}": 5 for i in range(6)}
    layout = layout_plan(roots, durations, crews=3)
    assert layout.span == 10
    assert [layout.slots[f"t:p{i}"].start for i in range(6)] == [0, 0, 0, 5, 5, 5]
    assert layout.slots["t:p3"].predecessor == "t:p0"
    assert layout.slots["t:p5"].predecessor == "t:p2"


def test_next_top_level_section_starts_when_the_previous_is_half_done() -> None:
    rows = [
        _row("s1", section=True),
        _row("a", "s1"),
        _row("s2", section=True),
        _row("b", "s2"),
    ]
    roots = build_plan_tree(rows).roots
    layout = layout_plan(roots, {"a": 10, "b": 4}, crews=1)
    assert layout.slots["g:s2"].start == 5
    assert layout.root_links == [("g:s1", "g:s2", 5)]
    assert layout.span == 10


def test_a_long_item_beside_short_ones_no_longer_holds_the_next_section_back() -> None:
    # Measured shape of an Italian restoration bill: temporary works where the
    # scaffold hire runs 60 days beside an 8-day erection and a 2-day toe
    # board, then demolitions. On the calendar the section is 60 days long,
    # so "half done" used to mean day 30; half of its 70 crew-days of work is
    # done on day 25 (board 2 + erection 8 + hire 25 = 35), when demolitions
    # now start.
    rows = [
        _row("tw", section=True),
        _row("hire", "tw"),
        _row("erect", "tw"),
        _row("board", "tw"),
        _row("demo", section=True),
        _row("strip", "demo"),
    ]
    roots = build_plan_tree(rows).roots
    layout = layout_plan(roots, {"hire": 60, "erect": 8, "board": 2, "strip": 20}, crews=3)
    assert layout.slots["g:tw"].finish == 60
    assert layout.root_links == [("g:tw", "g:demo", 25)]


def test_a_trade_ordered_bill_keeps_its_half_done_overlap() -> None:
    # Structures then finishes, one crew: excavation 10, foundations 30,
    # frame 90. Work and calendar agree, so finishes start on day 65, not a
    # few days into the excavation.
    rows = [
        _row("str", section=True),
        _row("exc", "str"),
        _row("fdn", "str"),
        _row("frame", "str"),
        _row("fin", section=True),
        _row("plaster", "fin"),
    ]
    roots = build_plan_tree(rows).roots
    layout = layout_plan(roots, {"exc": 10, "fdn": 30, "frame": 90, "plaster": 40}, crews=1)
    assert layout.root_links == [("g:str", "g:fin", 65)]
    # Two crews: excavation and foundations start together, the frame follows
    # the excavation (days 10 to 100). Two crews work until day 30 (60
    # crew-days), the frame alone adds the last 5 of the 65: finishes start on
    # day 35 where the calendar half said 50. Parallel crews already overlap
    # the trades; the rule moves with how much work is really behind.
    two = layout_plan(roots, {"exc": 10, "fdn": 30, "frame": 90, "plaster": 40}, crews=2)
    assert two.slots["g:str"].finish == 100
    assert two.root_links == [("g:str", "g:fin", 35)]


def test_nested_group_is_one_item_of_its_parent() -> None:
    rows = [
        _row("s", section=True),
        _row("sub", "s", section=True),
        _row("x", "sub"),
        _row("y", "sub"),
        _row("z", "s"),
    ]
    roots = build_plan_tree(rows).roots
    layout = layout_plan(roots, {"x": 3, "y": 3, "z": 2}, crews=1)
    assert (layout.slots["g:sub"].start, layout.slots["g:sub"].finish) == (0, 6)
    assert layout.slots["t:z"].start == 6
    assert layout.slots["t:z"].predecessor == "g:sub"


# ── Fitting ──────────────────────────────────────────────────────────────────


def test_fewest_crews_that_fit_are_used() -> None:
    roots = _one_section(8)
    durations = {f"p{i}": 5 for i in range(8)}
    assert fit_plan(roots, durations, budget=40, allow_compress=True).crews == 1
    fit = fit_plan(roots, durations, budget=20, allow_compress=True)
    assert fit.crews == 2 and fit.fits and fit.compressed_pct is None
    assert fit.layout.span <= 20


def test_compression_only_after_the_crews_run_out() -> None:
    roots = _one_section(MAX_CREWS)
    durations = {f"p{i}": 100 for i in range(MAX_CREWS)}
    fit = fit_plan(roots, durations, budget=70, allow_compress=True)
    assert fit.crews == MAX_CREWS
    assert fit.fits
    assert fit.compressed_pct is not None and 50 <= fit.compressed_pct < 100
    assert fit.layout.span <= 70
    untouched = fit_plan(roots, durations, budget=70, allow_compress=False)
    assert not untouched.fits and untouched.compressed_pct is None
    assert untouched.durations == durations


def test_durations_are_never_squeezed_below_half() -> None:
    roots = _one_section(MAX_CREWS)
    durations = {f"p{i}": 40 for i in range(MAX_CREWS)}
    halved = {f"p{i}": 20 for i in range(MAX_CREWS)}
    # Fitting 40 days of work into 10 would need a quarter of every estimate:
    # the plan says it does not fit and stops at half.
    fit = fit_plan(roots, durations, budget=10, allow_compress=True)
    assert not fit.fits and fit.compressed_pct == 50
    assert fit.durations == halved
    assert MIN_COMPRESSION == 0.5
    half = fit_plan(roots, durations, budget=20, allow_compress=True)
    assert half.fits and half.durations == halved


def test_a_day_less_never_makes_the_plan_longer() -> None:
    roots = _one_section(MAX_CREWS)
    durations = {f"p{i}": 40 for i in range(MAX_CREWS)}
    fits_at_half = fit_plan(roots, durations, budget=20, allow_compress=True)
    one_day_short = fit_plan(roots, durations, budget=19, allow_compress=True)
    assert fits_at_half.fits and not one_day_short.fits
    # Past the floor the plan stays where the floor put it, not back at the
    # estimates (which would double it for asking a day less).
    assert one_day_short.layout.span == fits_at_half.layout.span == 20
    assert one_day_short.durations == fits_at_half.durations


def test_a_plan_that_cannot_fit_says_so() -> None:
    roots = _one_section(600)
    durations = {f"p{i}": 8 for i in range(600)}
    fit = fit_plan(roots, durations, budget=20, allow_compress=True)
    assert not fit.fits
    assert fit.crews == MAX_CREWS
    # Even at half of every estimate it does not fit: the plan stops there
    # and the caller reports the real planned end.
    assert fit.durations == {f"p{i}": 4 for i in range(600)} and fit.compressed_pct == 50
    assert fit.layout.span == (600 // MAX_CREWS) * 4


def test_one_day_items_past_the_floor_are_not_called_shortened() -> None:
    roots = _one_section(600)
    durations = {f"p{i}": 1 for i in range(600)}
    fit = fit_plan(roots, durations, budget=20, allow_compress=True)
    assert not fit.fits and fit.compressed_pct is None
    assert fit.durations == durations


# ── Loose lump sums ──────────────────────────────────────────────────────────


def _bill_with_site_costs() -> list[Group | Task]:
    # Site costs as a lump sum between two sections, outside both.
    return build_plan_tree(
        [
            _row("A", section=True),
            _row("a1", "A"),
            _row("site", lump_sum=True),
            _row("B", section=True),
            _row("b1", "B"),
        ]
    ).roots


def test_a_loose_lump_sum_runs_for_the_whole_works() -> None:
    layout = layout_plan(_bill_with_site_costs(), {"a1": 10, "site": 3, "b1": 10}, crews=1)
    # The sections overlap as if the lump sum were not there: B waits for
    # half of A, not for the site costs.
    assert layout.root_links == [("g:A", "g:B", 5)]
    assert (layout.slots["g:B"].start, layout.slots["g:B"].finish) == (5, 15)
    assert layout.span == 15
    site = layout.slots["t:site"]
    assert (site.start, site.finish) == (0, 15)
    assert site.predecessor is None
    assert layout.spanning == frozenset({"site"})


def test_a_loose_lump_sum_follows_a_compressed_plan() -> None:
    fit = fit_plan(_bill_with_site_costs(), {"a1": 40, "site": 500, "b1": 40}, budget=40, allow_compress=True)
    # Its own estimate neither stretches the plan nor gets compressed into it.
    assert fit.fits and fit.compressed_pct is not None
    site = fit.layout.slots["t:site"]
    assert (site.start, site.finish) == (0, fit.layout.span)
    assert fit.layout.span <= 40


def test_a_lump_sum_inside_a_section_is_an_ordinary_task() -> None:
    roots = build_plan_tree([_row("A", section=True), _row("a1", "A", lump_sum=True), _row("a2", "A")]).roots
    layout = layout_plan(roots, {"a1": 3, "a2": 4}, crews=1)
    assert layout.spanning == frozenset()
    assert (layout.slots["t:a1"].start, layout.slots["t:a1"].finish) == (0, 3)
    assert (layout.slots["t:a2"].start, layout.slots["t:a2"].finish) == (3, 7)


def test_a_bill_of_nothing_but_loose_lump_sums_is_worked_like_loose_positions() -> None:
    roots = build_plan_tree([_row("x", lump_sum=True), _row("y", lump_sum=True)]).roots
    layout = layout_plan(roots, {"x": 4, "y": 6}, crews=1)
    assert layout.spanning == frozenset()
    assert (layout.slots["t:y"].start, layout.slots["t:y"].predecessor) == (4, "t:x")
    assert layout.span == 10


# ── One crew budget, at any depth ────────────────────────────────────────────


def _peak(layout, roots) -> int:  # noqa: ANN001
    change: dict[int, int] = {}
    for task in iter_tasks(roots):
        slot = layout.slots[task.key]
        change[slot.start] = change.get(slot.start, 0) + 1
        change[slot.finish] = change.get(slot.finish, 0) - 1
    running = peak = 0
    for day in sorted(change):
        running += change[day]
        peak = max(peak, running)
    return peak


def test_loose_positions_are_worked_by_crews_not_one_after_another() -> None:
    roots = build_plan_tree([_row(f"p{i}") for i in range(8)]).roots
    layout = layout_plan(roots, {f"p{i}": 10 for i in range(8)}, crews=4)
    assert layout.span == 20
    assert _peak(layout, roots) == 4
    assert layout.slots["t:p4"].predecessor == "t:p0"
    # No stand-in for the run ever reaches the caller.
    keys = {f"t:p{i}" for i in range(8)}
    assert set(layout.slots) == keys
    assert layout.root_links == []


def test_a_run_of_loose_positions_overlaps_its_neighbours_like_a_section() -> None:
    rows = [_row("a"), _row("b"), _row("S", section=True), _row("s1", "S")]
    roots = build_plan_tree(rows).roots
    layout = layout_plan(roots, {"a": 10, "b": 10, "s1": 4}, crews=2)
    # a and b run side by side; the section follows half their work, linked
    # from the first of them, which starts where the run starts.
    assert layout.root_links == [("t:a", "g:S", 5)]
    after = layout_plan(build_plan_tree([*rows[2:], _row("a"), _row("b")]).roots, {"a": 10, "b": 10, "s1": 4}, 2)
    # Into a run: every first item of its crews is linked.
    assert sorted(after.root_links) == [("g:S", "t:a", 2), ("g:S", "t:b", 2)]


def test_a_sub_section_shares_its_sections_crews() -> None:
    rows = [_row("S", section=True)]
    for sub in ("A", "B"):
        rows.append(_row(sub, "S", section=True))
        rows.extend(_row(f"{sub}{i}", sub) for i in range(8))
    roots = build_plan_tree(rows).roots
    durations = {f"{sub}{i}": 10 for sub in ("A", "B") for i in range(8)}
    layout = layout_plan(roots, durations, crews=4)
    assert _peak(layout, roots) == 4
    assert layout.span == 40


def test_deep_and_flat_bills_of_the_same_work_take_comparable_time() -> None:
    random.seed(7)
    durations = {f"p{i}": random.randint(5, 30) for i in range(240)}
    flat = build_plan_tree([_row("S", section=True)] + [_row(f"p{i}", "S") for i in range(240)]).roots
    deep_rows = [_row("S", section=True)]
    for a in range(3):
        deep_rows.append(_row(f"S{a}", "S", section=True))
        for b in range(4):
            deep_rows.append(_row(f"S{a}{b}", f"S{a}", section=True))
            deep_rows.extend(_row(f"p{(a * 4 + b) * 20 + i}", f"S{a}{b}") for i in range(20))
    deep = build_plan_tree(deep_rows).roots
    flat_fit = fit_plan(flat, durations, budget=250, allow_compress=True)
    deep_fit = fit_plan(deep, durations, budget=250, allow_compress=True)
    assert _peak(flat_fit.layout, flat) <= MAX_CREWS
    assert _peak(deep_fit.layout, deep) <= MAX_CREWS
    assert flat_fit.layout.span <= deep_fit.layout.span <= 2 * flat_fit.layout.span


def _layout_seconds(positions: int, repeats: int) -> float:
    """Best of ``repeats`` wall-clock runs of one fit over a flat bill of ``positions`` items."""
    rows = [_row("S", section=True)] + [_row(f"p{i}", "S") for i in range(positions)] + [_row("T", section=True)]
    rows.append(_row("x", "T"))
    roots = build_plan_tree(rows).roots
    durations = {f"p{i}": 5 + i % 30 for i in range(positions)} | {"x": 5}
    best = float("inf")
    for _ in range(repeats):
        started = time.perf_counter()
        fit_plan(roots, durations, budget=365, allow_compress=True)
        best = min(best, time.perf_counter() - started)
    return best


def test_ten_thousand_positions_lay_out_in_near_linear_time() -> None:
    # The overlap sweep was quadratic: 26 to 62 s at 10 000 positions, paid on
    # every layout. A wall-clock ceiling flakes on a loaded runner, so the bill
    # is measured against a fifth of itself on the same machine: near-linear
    # work grows about 5x, the quadratic sweep grew 25x.
    small = _layout_seconds(2_000, repeats=3)
    large = _layout_seconds(10_000, repeats=2)
    assert large < 15 * max(small, 0.005), f"10 000 positions took {large:.2f}s, 2 000 took {small:.2f}s"


@pytest.mark.parametrize("budget", [0, -5])
def test_a_degenerate_budget_never_loops(budget: int) -> None:
    roots = _one_section(3)
    fit = fit_plan(roots, {"p0": 2, "p1": 2, "p2": 2}, budget=budget, allow_compress=True)
    assert not fit.fits
