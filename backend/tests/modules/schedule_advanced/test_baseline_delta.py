# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for ``compute_baseline_delta`` — variance computation.

These tests exercise the pure-Python helper directly (no DB / no HTTP)
so the variance math is provable in isolation. They also lock in the
2026-05-25 contract that the helper passes through the snapshot row's
``name`` field so the UI can render "Foundation +5d" instead of bare
UUIDs.

Coverage:
    * delay days → positive variance
    * acceleration → negative variance
    * task missing in current → no current dates, zero variance
    * snapshot ``{"tasks": [...]}`` wrapper shape tolerated
    * ``name`` carry-through from snapshot
    * ``name`` falls back to current row when snapshot lacks it
"""

from __future__ import annotations

from datetime import date

from app.modules.schedule_advanced.service import compute_baseline_delta


def test_delay_yields_positive_variance():
    baseline = [
        {
            "task_ref": "T1",
            "planned_start": "2026-06-01",
            "planned_finish": "2026-06-30",
            "name": "Foundation",
        }
    ]
    current = [
        {
            "task_ref": "T1",
            "planned_start": "2026-06-06",
            "planned_finish": "2026-07-05",
            "name": "Foundation",
        }
    ]
    out = compute_baseline_delta(baseline, current)
    assert len(out) == 1
    assert out[0]["schedule_variance_days"] == 5
    assert out[0]["planned_finish_baseline"] == date(2026, 6, 30)
    assert out[0]["planned_finish_current"] == date(2026, 7, 5)
    assert out[0]["name"] == "Foundation"


def test_acceleration_yields_negative_variance():
    baseline = [{"task_ref": "T1", "planned_finish": "2026-07-01", "name": "Roof"}]
    current = [{"task_ref": "T1", "planned_finish": "2026-06-25", "name": "Roof"}]
    out = compute_baseline_delta(baseline, current)
    assert out[0]["schedule_variance_days"] == -6


def test_missing_current_keeps_baseline_dates():
    baseline = [{"task_ref": "T1", "planned_finish": "2026-07-01", "name": "Gone"}]
    current: list[dict] = []
    out = compute_baseline_delta(baseline, current)
    assert out[0]["planned_finish_current"] is None
    assert out[0]["schedule_variance_days"] == 0
    # Even when current is missing, the snapshot's display name survives
    assert out[0]["name"] == "Gone"


def test_wrapper_tasks_shape_is_tolerated():
    baseline = {"tasks": [{"task_ref": "T1", "planned_finish": "2026-07-01"}]}
    current = [{"task_ref": "T1", "planned_finish": "2026-07-05"}]
    out = compute_baseline_delta(baseline, current)
    assert len(out) == 1
    assert out[0]["schedule_variance_days"] == 4


def test_name_falls_back_to_current_row():
    # Older snapshots (pre 2026-05-25) didn't include the name. The
    # helper must fall back to the current row's name so legacy
    # baselines still render readable rows in the UI.
    baseline = [{"task_ref": "T1", "planned_finish": "2026-07-01"}]
    current = [{"task_ref": "T1", "planned_finish": "2026-07-01", "name": "FallbackName"}]
    out = compute_baseline_delta(baseline, current)
    assert out[0]["name"] == "FallbackName"


def test_empty_inputs_return_empty_list():
    assert compute_baseline_delta([], []) == []
    assert compute_baseline_delta({}, []) == []
