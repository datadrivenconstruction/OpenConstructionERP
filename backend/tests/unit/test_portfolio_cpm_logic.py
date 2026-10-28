# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the portfolio CPM bridging (T3.3).

Exercises :func:`build_portfolio_inputs` end-to-end through the pure portfolio
engine, so they run on the local Python 3.11 runner without the ORM / DB. Focus:
id namespacing, start-offset anchoring, and in-scope-only cross-link inclusion.
"""

from __future__ import annotations

from app.modules.portfolio.cpm_logic import (
    ActivityInput,
    ScheduleInput,
    build_portfolio_inputs,
    nid,
    split_nid,
)
from app.modules.schedule_advanced.portfolio_cpm import compute_portfolio_cpm


def test_nid_roundtrip() -> None:
    n = nid("sched-1", "act-9")
    assert n == "sched-1:act-9"
    assert split_nid(n) == ("sched-1", "act-9")


def test_single_schedule_no_offset_no_links() -> None:
    sched = ScheduleInput(
        schedule_id="A",
        offset=0,
        activities=(
            ActivityInput("a1", 5, ()),
            ActivityInput("a2", 3, (("a1", "FS", 0),)),
        ),
    )
    activities, cross_edges, boundaries = build_portfolio_inputs([sched], [])
    assert {a.id for a in activities} == {"A:a1", "A:a2"}
    assert cross_edges == []
    assert boundaries == []  # offset 0 -> no floor
    results = compute_portfolio_cpm(activities, cross_edges=cross_edges, boundaries=boundaries)
    assert results["A:a1"].es == 0
    assert results["A:a1"].ef == 5
    assert results["A:a2"].es == 5
    assert results["A:a2"].ef == 8


def test_start_offset_floors_sources() -> None:
    sched = ScheduleInput(schedule_id="B", offset=10, activities=(ActivityInput("b1", 4, ()),))
    activities, _edges, boundaries = build_portfolio_inputs([sched], [])
    # The lone source picks up an FS boundary floor equal to the offset.
    assert len(boundaries) == 1
    assert boundaries[0].local_activity_id == "B:b1"
    assert boundaries[0].boundary_index == 10
    results = compute_portfolio_cpm(activities, boundaries=boundaries)
    assert results["B:b1"].es == 10
    assert results["B:b1"].ef == 14


def test_in_scope_cross_link_becomes_real_edge() -> None:
    a = ScheduleInput("A", 0, (ActivityInput("a1", 5, ()),))
    b = ScheduleInput("B", 0, (ActivityInput("b1", 3, ()),))
    links = [("A", "a1", "B", "b1", "FS", 0)]
    activities, cross_edges, boundaries = build_portfolio_inputs([a, b], links)
    assert len(cross_edges) == 1
    assert cross_edges[0].predecessor_id == "A:a1"
    assert cross_edges[0].successor_id == "B:b1"
    results = compute_portfolio_cpm(activities, cross_edges=cross_edges, boundaries=boundaries)
    # b1 now waits for a1 to finish (cross-schedule dependency).
    assert results["B:b1"].es == 5
    assert results["B:b1"].ef == 8


def test_out_of_scope_cross_link_dropped() -> None:
    a = ScheduleInput("A", 0, (ActivityInput("a1", 5, ()),))
    # Far side schedule "C" is not in scope -> the link must be dropped.
    links = [("A", "a1", "C", "c1", "FS", 0)]
    _activities, cross_edges, _boundaries = build_portfolio_inputs([a], links)
    assert cross_edges == []


def test_offset_plus_cross_link_combine() -> None:
    # A starts at the data date; B starts 7 days later. A:a1 -> B:b1 FS.
    a = ScheduleInput("A", 0, (ActivityInput("a1", 5, ()),))
    b = ScheduleInput("B", 7, (ActivityInput("b1", 2, ()),))
    links = [("A", "a1", "B", "b1", "FS", 0)]
    activities, cross_edges, boundaries = build_portfolio_inputs([a, b], links)
    results = compute_portfolio_cpm(activities, cross_edges=cross_edges, boundaries=boundaries)
    # b1 cannot start before max(its 7-day offset floor, a1's finish at day 5).
    assert results["B:b1"].es == 7
    assert results["B:b1"].ef == 9
