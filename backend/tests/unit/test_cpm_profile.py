"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠CPM under scheduling options (app.core.cpm_profile).

2024-01-01 is a Monday, so on the default Monday-Friday calendar offset 0 is
Monday, 4 is Friday and 7 is the next Monday.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.core.cpm import calculate_cpm
from app.core.cpm_profile import (
    ActivityStatus,
    SchedulingOptions,
    calculate_cpm_with_options,
    remaining_working_days,
)

ORIGIN = date(2024, 1, 1)


def _run(acts, rels, **opts):
    status = opts.pop("status", {})
    options = SchedulingOptions(status=status, **opts)
    rows = calculate_cpm_with_options(acts, rels, calendar=None, project_start=ORIGIN, options=options)
    return {r["id"]: r for r in rows}


def _fs(pred, succ, lag=0, kind="FS"):
    return {"predecessor_id": pred, "successor_id": succ, "type": kind, "lag": lag}


CHAIN = [{"id": "A", "duration": 5}, {"id": "B", "duration": 3}]


def test_defaults_match_the_plain_pass_for_fs_and_ss() -> None:
    acts = [{"id": "A", "duration": 5}, {"id": "B", "duration": 3}, {"id": "C", "duration": 2}]
    rels = [_fs("A", "B", 2), _fs("A", "C", 1, "SS")]
    plain = {r["id"]: r for r in asyncio.run(calculate_cpm(acts, rels, project_start_date=ORIGIN.isoformat()))}
    profiled = _run(acts, rels)
    for aid in ("A", "B", "C"):
        assert profiled[aid]["early_start"] == plain[aid]["early_start"]
        assert profiled[aid]["early_finish"] == plain[aid]["early_finish"]


def test_calculate_cpm_delegates_when_options_are_given() -> None:
    rows = asyncio.run(
        calculate_cpm(CHAIN, [_fs("A", "B")], project_start_date=ORIGIN.isoformat(), options=SchedulingOptions())
    )
    assert {"on_longest_path", "out_of_sequence"} <= set(rows[0])


def test_lag_on_working_calendar_skips_the_weekend() -> None:
    # A finishes Friday; EF is next Monday (7). A 2-day lag in elapsed days
    # lands on Wednesday (9) either way, but a 6-day lag shows the difference.
    elapsed = _run(CHAIN, [_fs("A", "B", 6)])
    working = _run(CHAIN, [_fs("A", "B", 6)], lag_calendar="project")
    assert elapsed["B"]["early_start"] == 14  # Mon 7 + 6 calendar days = Sun 13, snapped to Mon 14
    assert working["B"]["early_start"] == 15  # six working days after Monday 7 = Tuesday 15


def test_lag_calendar_follows_the_chosen_side() -> None:
    acts = [
        {"id": "A", "duration": 5, "calendar": {"work_days": [0, 1, 2, 3, 4, 5, 6]}},
        {"id": "B", "duration": 1},
    ]
    pred_side = _run(acts, [_fs("A", "B", 2)], lag_calendar="predecessor")
    succ_side = _run(acts, [_fs("A", "B", 2)], lag_calendar="successor")
    # A works seven days a week and ends Friday night (EF = Sat 5).
    assert pred_side["B"]["early_start"] == 7  # Sat + 2 seven-day days = Mon
    assert succ_side["B"]["early_start"] == 9  # Sat snapped to Mon + 2 working days = Wed


def test_retained_logic_override_and_actual_dates_place_remaining_work_differently() -> None:
    acts = [{"id": "A", "duration": 10}, {"id": "B", "duration": 5}]
    rels = [_fs("A", "B")]
    status = {
        "A": ActivityStatus(actual_start=0, percent_complete=20.0),
        "B": ActivityStatus(actual_start=1, percent_complete=40.0),
    }
    retained = _run(acts, rels, data_date=2, status=status)
    override = _run(acts, rels, data_date=2, status=status, progress_mode="progress_override")
    actual = _run(acts, rels, data_date=2, status=status, progress_mode="actual_dates")

    assert retained["B"]["out_of_sequence"] is True
    # Retained logic: B's 3 remaining days wait for A (8 remaining from Wed 2).
    assert retained["B"]["early_finish"] > retained["A"]["early_finish"]
    # Progress override: B's 3 remaining days run from the data date (Wed 2 -> Mon 7).
    assert override["B"]["early_finish"] == 7
    # Actual dates: all 5 planned days from the actual start (Tue 1 -> Tue 8).
    assert actual["B"]["early_finish"] == 8
    assert override["B"]["early_finish"] < actual["B"]["early_finish"] < retained["B"]["early_finish"]
    for run in (retained, override, actual):
        assert run["B"]["early_start"] == 1


def test_finished_activity_is_pinned_to_actuals_and_never_critical() -> None:
    status = {"A": ActivityStatus(actual_start=0, actual_finish=2, percent_complete=100.0)}
    rows = _run(CHAIN, [_fs("A", "B")], data_date=3, status=status)
    assert rows["A"]["early_start"] == 0
    assert rows["A"]["early_finish"] == 3  # day after Wednesday 2
    assert rows["A"]["completed"] is True
    assert rows["A"]["is_critical"] is False
    assert rows["B"]["early_start"] == 3


def test_data_date_holds_unstarted_work_back() -> None:
    rows = _run(CHAIN, [_fs("A", "B")], data_date=7)
    assert rows["A"]["early_start"] == 7
    assert rows["B"]["early_start"] == 14


def test_open_ends_own_finish_makes_a_dangling_branch_critical() -> None:
    acts = [{"id": "A", "duration": 2}, {"id": "LONG", "duration": 10}, {"id": "SHORT", "duration": 1}]
    rels = [_fs("A", "LONG"), _fs("A", "SHORT")]
    bound = _run(acts, rels)
    own = _run(acts, rels, open_ends="own_finish")
    assert bound["SHORT"]["total_float"] > 0
    assert bound["SHORT"]["is_critical"] is False
    assert own["SHORT"]["total_float"] == 0
    assert own["SHORT"]["is_critical"] is True
    assert own["SHORT"]["open_finish"] is True


def test_float_threshold_and_longest_path_rules() -> None:
    acts = [
        {"id": "A", "duration": 5},
        {"id": "B", "duration": 5},
        {"id": "C", "duration": 3},
        {"id": "D", "duration": 1},
    ]
    rels = [_fs("A", "B"), _fs("A", "C"), _fs("B", "D"), _fs("C", "D")]
    zero = _run(acts, rels)
    loose = _run(acts, rels, critical_float_threshold=2)
    longest = _run(acts, rels, critical_rule="longest_path")
    assert zero["C"]["total_float"] == 2
    assert not zero["C"]["is_critical"]
    assert loose["C"]["is_critical"]
    assert {k for k, r in longest.items() if r["is_critical"]} == {"A", "B", "D"}
    assert longest["D"]["driving_predecessors"] == ["B"]


def test_invalid_option_is_rejected() -> None:
    with pytest.raises(ValueError, match="progress_mode"):
        SchedulingOptions(progress_mode="whatever")


def test_remaining_working_days_prefers_explicit_value() -> None:
    assert remaining_working_days(ActivityStatus(percent_complete=50.0), 10) == 5
    assert remaining_working_days(ActivityStatus(percent_complete=50.0, remaining_duration=7), 10) == 7
    assert remaining_working_days(ActivityStatus(remaining_duration=99), 10) == 10
    assert remaining_working_days(ActivityStatus(actual_finish=3), 10) == 0
    assert remaining_working_days(None, 4) == 4
