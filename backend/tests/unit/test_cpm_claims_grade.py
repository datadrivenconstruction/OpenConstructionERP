# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the claims-grade CPM extensions (T1.2).

Pure-Python, no DB - every function under test post-processes the output of
``compute_cpm`` (plus the network adjacency) and imports nothing beyond the
``cpm`` module and the standard library.

Coverage
--------
* parity: ``select_critical("total_float")`` == ``compute_cpm`` critical set,
  and ES/EF/LS/LF are untouched by the new code path.
* longest path picks the date-driving chain even when the float-based
  critical set is larger (disconnected islands).
* multiple float paths: strictly descending length, ``relative_float`` starts
  at 0 and is non-decreasing, path 1 == longest path.
* the three out-of-sequence modes on a fixed data date with an early-started
  finish-to-start successor: override finish <= actual-dates finish <=
  retained finish, and all three reduce to the planning result when there is
  no data date and no actuals.
* determinism: shuffled input activity order yields identical longest path,
  float-path ordering and QA-log ordering.
* scheduling QA log raises and sorts every finding type.
* generated explain strings never contradict the computed numbers.
"""

from __future__ import annotations

import random

from app.modules.schedule_advanced.cpm import (
    Activity,
    Progress,
    QAOptions,
    TaskNetwork,
    compute_cpm,
    detect_out_of_sequence,
    driving_predecessor,
    es_ef_durations,
    float_explanation,
    longest_path,
    multiple_float_paths,
    out_of_sequence_cpm,
    scheduling_qa_log,
    select_critical,
    why_critical,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _textbook_network() -> TaskNetwork:
    """Classic 6-activity AOA network; critical path A -> C -> F, finish 11."""
    return TaskNetwork(
        [
            Activity(id="A", duration=3, predecessors=[]),
            Activity(id="B", duration=4, predecessors=[]),
            Activity(id="C", duration=5, predecessors=[("A", "FS", 0)]),
            Activity(id="D", duration=2, predecessors=[("B", "FS", 0)]),
            Activity(id="E", duration=3, predecessors=[("B", "FS", 0)]),
            Activity(id="F", duration=3, predecessors=[("C", "FS", 0), ("D", "FS", 0)]),
        ],
    )


def _two_island_network() -> TaskNetwork:
    """Two disconnected chains where the float rule and longest path disagree.

    Island 1 (long):  A(3) -> B(4) -> C(5)   length 12  (controls the finish)
    Island 2 (short): X(2) -> Y(3)           length 5

    Every activity in BOTH chains has total float 0 (each island anchors to
    its own finish), so the ``total_float`` critical set is all five
    activities, while the Longest Path is only [A, B, C].
    """
    return TaskNetwork(
        [
            Activity(id="A", duration=3, predecessors=[]),
            Activity(id="B", duration=4, predecessors=[("A", "FS", 0)]),
            Activity(id="C", duration=5, predecessors=[("B", "FS", 0)]),
            Activity(id="X", duration=2, predecessors=[]),
            Activity(id="Y", duration=3, predecessors=[("X", "FS", 0)]),
        ],
    )


def _diamond_network() -> TaskNetwork:
    """Single island, three parallel chains of distinct length off START.

    START(1) -> A(6) -------------> END(1)   path length 8
    START(1) -> B(4) -> C(3) -----> END(1)   path length 9  (longest)
    START(1) -> D(2) -------------> END(1)   path length 4
    """
    return TaskNetwork(
        [
            Activity(id="START", duration=1, predecessors=[]),
            Activity(id="A", duration=6, predecessors=[("START", "FS", 0)]),
            Activity(id="B", duration=4, predecessors=[("START", "FS", 0)]),
            Activity(id="C", duration=3, predecessors=[("B", "FS", 0)]),
            Activity(id="D", duration=2, predecessors=[("START", "FS", 0)]),
            Activity(
                id="END",
                duration=1,
                predecessors=[("A", "FS", 0), ("C", "FS", 0), ("D", "FS", 0)],
            ),
        ],
    )


def _oos_network() -> TaskNetwork:
    """A(5) -FS-> B(4) -FS-> C(3); used for the out-of-sequence modes."""
    return TaskNetwork(
        [
            Activity(id="A", duration=5, predecessors=[]),
            Activity(id="B", duration=4, predecessors=[("A", "FS", 0)]),
            Activity(id="C", duration=3, predecessors=[("B", "FS", 0)]),
        ],
    )


# ── Parity with compute_cpm ──────────────────────────────────────────────────


def test_select_critical_total_float_matches_compute_cpm() -> None:
    """``select_critical("total_float")`` reproduces ``is_critical`` exactly."""
    for network in (_textbook_network(), _two_island_network(), _diamond_network()):
        results = compute_cpm(network)
        selected = select_critical(results, "total_float")
        expected = {aid for aid, r in results.items() if r.is_critical}
        assert selected == expected


def test_es_ef_durations_roundtrip_is_unchanged() -> None:
    """Projecting results back to es/ef/durations matches the raw CPM output.

    Confirms the new helper never perturbs the canonical ES/EF/LS/LF values.
    """
    network = _textbook_network()
    results = compute_cpm(network)
    es, ef, durations = es_ef_durations(network, results)
    for aid, r in results.items():
        assert es[aid] == r.es
        assert ef[aid] == r.ef
        # Durations come straight from the (clamped) network durations.
        a = network.get(aid)
        assert a is not None
        assert durations[aid] == max(0, int(a.duration))
    # Backward-pass values are still present and self-consistent on results.
    for r in results.values():
        assert r.total_float == max(0, r.ls - r.es)


# ── Longest path vs the float rule ───────────────────────────────────────────


def test_longest_path_picks_date_driving_chain() -> None:
    """On the diamond, the Longest Path is the date-driving B -> C chain."""
    network = _diamond_network()
    results = compute_cpm(network)
    es, ef, durations = es_ef_durations(network, results)
    lp = longest_path(network, results, durations, es, ef)
    assert lp == ["START", "B", "C", "END"]


def test_longest_path_differs_from_total_float_set() -> None:
    """Two islands: every node is float-critical but only one chain is longest.

    This is the case that separates a Longest Path analysis from a simple
    total-float scan: both island chains have zero float, yet only the longer
    island actually controls the project finish date.
    """
    network = _two_island_network()
    results = compute_cpm(network)
    es, ef, durations = es_ef_durations(network, results)

    total_float_set = select_critical(results, "total_float")
    assert total_float_set == {"A", "B", "C", "X", "Y"}

    lp = longest_path(network, results, durations, es, ef)
    assert lp == ["A", "B", "C"]

    lp_set = select_critical(results, "longest_path", longest_path_ids=lp)
    assert lp_set == {"A", "B", "C"}
    # The longest-path set is a STRICT subset of the float-critical set here.
    assert lp_set < total_float_set


def test_driving_predecessor_open_start_is_none() -> None:
    """An activity with no scheduled predecessor reports no driving edge."""
    network = _diamond_network()
    results = compute_cpm(network)
    es, ef, durations = es_ef_durations(network, results)
    assert driving_predecessor(network, es, ef, durations, "START") is None
    # END's early start is driven by C (the longest incoming chain).
    edge = driving_predecessor(network, es, ef, durations, "END")
    assert edge is not None
    assert edge[0] == "C"


def test_driving_predecessor_deterministic_tie_break() -> None:
    """When two predecessors tie on the forward bound, the lower topo-rank wins.

    P and Q both finish on day 5 and both feed R by FS lag 0, so each sets
    R.ES = 5. P precedes Q in the topological order (P has the earlier start
    here), so P is the driving predecessor.
    """
    network = TaskNetwork(
        [
            Activity(id="P", duration=5, predecessors=[]),
            Activity(id="Q", duration=5, predecessors=[]),
            Activity(id="R", duration=2, predecessors=[("Q", "FS", 0), ("P", "FS", 0)]),
        ],
    )
    results = compute_cpm(network)
    es, ef, durations = es_ef_durations(network, results)
    edge = driving_predecessor(network, es, ef, durations, "R")
    assert edge is not None
    assert edge[0] == "P"


# ── Multiple float paths ─────────────────────────────────────────────────────


def test_multiple_float_paths_ranking_and_relative_float() -> None:
    """Float paths are descending in length; relative float starts at 0."""
    network = _diamond_network()
    results = compute_cpm(network)
    es, ef, durations = es_ef_durations(network, results)

    paths = multiple_float_paths(network, results, durations, es, ef)
    assert len(paths) >= 2

    # Indexes are 0..n-1 in order.
    assert [p.index for p in paths] == list(range(len(paths)))

    # Lengths strictly descending.
    lengths = [p.length_days for p in paths]
    assert all(lengths[i] > lengths[i + 1] for i in range(len(lengths) - 1)), lengths

    # Relative float: path 1 is zero, then non-decreasing.
    rel = [p.relative_float for p in paths]
    assert rel[0] == 0
    assert all(rel[i] <= rel[i + 1] for i in range(len(rel) - 1)), rel

    # Path 1 == the Longest Path.
    lp = longest_path(network, results, durations, es, ef)
    assert set(paths[0].activity_ids) == set(lp)
    assert paths[0].activity_ids == lp


def test_multiple_float_paths_min_len_and_max_paths_caps() -> None:
    """``max_paths`` caps the count and ``min_len`` drops short chains."""
    network = _diamond_network()
    results = compute_cpm(network)
    es, ef, durations = es_ef_durations(network, results)

    capped = multiple_float_paths(network, results, durations, es, ef, max_paths=1)
    assert len(capped) == 1
    assert capped[0].index == 0

    # With min_len=2 the single-node secondary chains (A, D) are dropped, so
    # only the multi-activity Longest Path survives.
    long_only = multiple_float_paths(network, results, durations, es, ef, min_len=2)
    assert [p.activity_ids for p in long_only] == [["START", "B", "C", "END"]]


# ── Out-of-sequence modes ────────────────────────────────────────────────────


def test_out_of_sequence_mode_finish_ordering() -> None:
    """override finish <= actual-dates finish <= retained finish.

    B is started out of sequence (actual start day 1, 50% complete -> 2 days
    remaining) while predecessor A is unfinished, with the data date at day 3.
    """
    network = _oos_network()
    progress = {"B": Progress(actual_start=1, progress_pct=50.0)}
    data_date = 3

    override = out_of_sequence_cpm(network, mode="progress_override", data_date=data_date, progress=progress)
    actual = out_of_sequence_cpm(network, mode="actual_dates", data_date=data_date, progress=progress)
    retained = out_of_sequence_cpm(network, mode="retained_logic", data_date=data_date, progress=progress)

    override_finish = override["B"].ef
    actual_finish = actual["B"].ef
    retained_finish = retained["B"].ef

    assert override_finish <= actual_finish <= retained_finish
    # And the spread is real: progress override finishes strictly before
    # retained logic (remaining from the data date vs. from predecessor logic).
    assert override_finish < retained_finish

    # B is correctly flagged out of sequence (progressed ahead of A).
    assert detect_out_of_sequence(network, data_date, progress) == {"B"}


def test_out_of_sequence_successors_stay_logic_bound() -> None:
    """C (successor of B) keeps the same logic-driven dates in all three modes."""
    network = _oos_network()
    progress = {"B": Progress(actual_start=1, progress_pct=50.0)}
    data_date = 3

    finishes = {
        mode: out_of_sequence_cpm(network, mode=mode, data_date=data_date, progress=progress)["C"].ef
        for mode in ("progress_override", "actual_dates", "retained_logic")
    }
    # All identical: successors are bound by full predecessor logic regardless
    # of how B's own remaining work is scheduled.
    assert len(set(finishes.values())) == 1


def test_out_of_sequence_modes_reduce_to_planning() -> None:
    """With no data date and no actuals, every mode equals ``compute_cpm``."""
    network = _oos_network()
    base = compute_cpm(network)
    for mode in ("progress_override", "actual_dates", "retained_logic"):
        result = out_of_sequence_cpm(network, mode=mode, data_date=None, progress={})
        for aid in network.ids():
            r, b = result[aid], base[aid]
            assert (r.es, r.ef, r.ls, r.lf) == (b.es, b.ef, b.ls, b.lf), (mode, aid)
            assert r.total_float == b.total_float
            assert r.free_float == b.free_float
            assert r.is_critical == b.is_critical


def test_finished_activity_pins_to_actuals_in_every_mode() -> None:
    """A completed out-of-sequence activity reports its actual dates everywhere."""
    network = _oos_network()
    progress = {"B": Progress(actual_start=1, actual_finish=7, progress_pct=100.0)}
    for mode in ("progress_override", "actual_dates", "retained_logic"):
        result = out_of_sequence_cpm(network, mode=mode, data_date=3, progress=progress)
        assert (result["B"].es, result["B"].ef) == (1, 7)


# ── Scheduling QA log ────────────────────────────────────────────────────────


def _qa_network() -> TaskNetwork:
    return TaskNetwork(
        [
            Activity(id="A", duration=3, predecessors=[]),  # open start
            Activity(id="B", duration=4, predecessors=[("A", "FS", 15)]),  # large lag
            Activity(id="C", duration=2, predecessors=[("B", "FS", -3)]),  # neg lag, open finish
        ],
    )


def test_scheduling_qa_log_raises_and_sorts_every_finding() -> None:
    """Every finding type fires once and the log is sorted (severity, id, code)."""
    network = _qa_network()
    results = compute_cpm(network)
    options = QAOptions(
        hard_constrained={"A"},
        data_date=2,
        progress={"C": Progress(progress_pct=20.0)},  # progresses ahead of B
    )
    log = scheduling_qa_log(network, results, options)
    codes = {f.code for f in log}
    assert codes == {
        "OPEN_START",
        "OPEN_FINISH",
        "HARD_CONSTRAINT",
        "OUT_OF_SEQUENCE",
        "LARGE_LAG",
        "NEGATIVE_LAG",
    }

    # Highest-severity finding sorts first; the full sort key is monotone.
    keys = [(-f.severity, str(f.activity_id), f.code) for f in log]
    assert keys == sorted(keys)
    assert log[0].code == "OUT_OF_SEQUENCE"  # the only HIGH-severity finding


def test_scheduling_qa_log_respects_milestone_suppression() -> None:
    """Declaring start/finish milestones suppresses the open-end findings."""
    network = _qa_network()
    results = compute_cpm(network)
    options = QAOptions(start_milestones={"A"}, finish_milestones={"C"})
    codes = {f.code for f in scheduling_qa_log(network, results, options)}
    assert "OPEN_START" not in codes
    assert "OPEN_FINISH" not in codes


# ── Generated explain strings ────────────────────────────────────────────────


def test_explain_strings_track_the_numbers() -> None:
    """``why_critical`` / ``float_explanation`` never contradict the results."""
    network = _textbook_network()
    results = compute_cpm(network)
    es, ef, durations = es_ef_durations(network, results)

    for aid, r in results.items():
        why = why_critical(network, results, durations, es, ef, aid)
        fl = float_explanation(network, results, durations, es, ef, aid)
        if r.is_critical:
            assert "is critical" in why
            assert "not critical" not in why
        else:
            assert "not critical" in why
            # A non-critical activity's float is quoted verbatim.
            assert f"{r.total_float} day(s) of total float" in why
        # The float explanation always quotes the activity's own early start.
        assert f"day {r.es}" in fl

    # Critical activity F names its driving predecessor (C via FS).
    why_f = why_critical(network, results, durations, es, ef, "F")
    assert "C" in why_f and "FS" in why_f


# ── Determinism under input shuffling ────────────────────────────────────────


def test_determinism_under_shuffled_input() -> None:
    """Shuffling activity order leaves every derived artefact unchanged."""
    base_acts = _diamond_network().activities

    network = TaskNetwork(list(base_acts))
    results = compute_cpm(network)
    es, ef, durations = es_ef_durations(network, results)
    base_lp = longest_path(network, results, durations, es, ef)
    base_paths = [
        (p.index, tuple(p.activity_ids), p.length_days, p.relative_float)
        for p in multiple_float_paths(network, results, durations, es, ef)
    ]
    options = QAOptions(data_date=0)
    base_qa = [(f.code, str(f.activity_id)) for f in scheduling_qa_log(network, results, options)]

    for seed in range(25):
        shuffled = list(base_acts)
        random.Random(seed).shuffle(shuffled)
        n2 = TaskNetwork(shuffled)
        r2 = compute_cpm(n2)
        e2, f2, d2 = es_ef_durations(n2, r2)

        assert longest_path(n2, r2, d2, e2, f2) == base_lp, seed

        paths2 = [
            (p.index, tuple(p.activity_ids), p.length_days, p.relative_float)
            for p in multiple_float_paths(n2, r2, d2, e2, f2)
        ]
        assert paths2 == base_paths, seed

        qa2 = [(f.code, str(f.activity_id)) for f in scheduling_qa_log(n2, r2, options)]
        assert qa2 == base_qa, seed
