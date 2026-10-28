# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the takt / line-of-balance geometry engine.

Pure-Python, no DB — ``compute_line_of_balance_geometry`` is fully
decoupled from SQLAlchemy and FastAPI so the diagonal-bar math is
provable in isolation.

Coverage
--------
* test_empty_inputs_return_zero
* test_single_location_back_to_back_trades
* test_diagonal_stagger_across_locations
* test_critical_path_is_longest_trade
* test_rhythm_break_detected_above_tolerance
* test_rhythm_break_within_tolerance_clean
* test_buffer_shifts_start
* test_makespan_and_average_cycle
* test_takt_schedule_create_validation
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.schedule_advanced.schemas import TaktActivityCreate, TaktScheduleCreate
from app.modules.schedule_advanced.service import compute_line_of_balance_geometry


def _locs(n: int) -> list[dict]:
    return [{"id": f"L{i}", "name": f"Level {i}", "sequence_order": i} for i in range(1, n + 1)]


def test_empty_inputs_return_zero() -> None:
    out = compute_line_of_balance_geometry([], [])
    assert out["bars"] == []
    assert out["violations"] == []
    assert out["critical_path"] == []
    assert out["total_makespan_days"] == 0
    assert out["average_cycle_days"] == 0.0

    # Locations but no activities (and vice-versa) also short-circuit.
    assert compute_line_of_balance_geometry(_locs(3), [])["bars"] == []
    assert compute_line_of_balance_geometry([], [{"id": "A", "planned_cycle_duration_days": 3}])["bars"] == []


def test_single_location_back_to_back_trades() -> None:
    locs = _locs(1)
    acts = [
        {"id": "F", "name": "Formwork", "sequence_order": 1, "planned_cycle_duration_days": 5, "crew_size": 4},
        {"id": "C", "name": "Concrete", "sequence_order": 2, "planned_cycle_duration_days": 3, "crew_size": 3},
    ]
    out = compute_line_of_balance_geometry(locs, acts)
    bars = {b["activity_id"]: b for b in out["bars"]}
    # Formwork: day 0 → 5. Concrete picks up right after: 5 → 8.
    assert (bars["F"]["start_day"], bars["F"]["end_day"]) == (0, 5)
    assert (bars["C"]["start_day"], bars["C"]["end_day"]) == (5, 8)
    assert out["total_makespan_days"] == 8


def test_diagonal_stagger_across_locations() -> None:
    locs = _locs(3)
    acts = [
        {"id": "F", "name": "Formwork", "sequence_order": 1, "planned_cycle_duration_days": 5},
        {"id": "C", "name": "Concrete", "sequence_order": 2, "planned_cycle_duration_days": 3},
    ]
    out = compute_line_of_balance_geometry(locs, acts)
    # takt_time = max(5, 3) = 5; each location starts one takt later.
    by = {(b["activity_id"], b["location_id"]): b for b in out["bars"]}
    assert by[("F", "L1")]["start_day"] == 0
    assert by[("F", "L2")]["start_day"] == 5
    assert by[("F", "L3")]["start_day"] == 10
    # Within L1: Formwork 0→5, Concrete 5→8.
    assert by[("C", "L1")]["start_day"] == 5
    # 9 bars total? No — 3 locations × 2 activities = 6 bars.
    assert len(out["bars"]) == 6


def test_critical_path_is_longest_trade() -> None:
    locs = _locs(2)
    acts = [
        {"id": "F", "name": "Formwork", "sequence_order": 1, "planned_cycle_duration_days": 5},
        {"id": "C", "name": "Concrete", "sequence_order": 2, "planned_cycle_duration_days": 3},
        {"id": "X", "name": "Finishes", "sequence_order": 3, "planned_cycle_duration_days": 7},
    ]
    out = compute_line_of_balance_geometry(locs, acts)
    # Finishes (7d) is the longest trade → critical.
    assert out["critical_path"] == ["X"]
    crit_bars = [b for b in out["bars"] if b["is_critical"]]
    assert all(b["activity_id"] == "X" for b in crit_bars)
    assert len(crit_bars) == 2  # one per location


def test_rhythm_break_detected_above_tolerance() -> None:
    locs = _locs(1)
    acts = [
        {
            "id": "C",
            "name": "Concrete",
            "sequence_order": 1,
            "planned_cycle_duration_days": 3,
            "actual_cycle_duration_days": 5.5,
        },
    ]
    out = compute_line_of_balance_geometry(locs, acts, tolerance_days=1)
    assert len(out["violations"]) == 1
    v = out["violations"][0]
    assert v["violation_type"] == "rhythm_break"
    assert v["deviation_days"] == 2.5
    # 2.5 > 2 * tolerance(1) → escalated to error.
    assert v["severity"] == "error"
    assert any(b["has_rhythm_break"] for b in out["bars"])


def test_rhythm_break_within_tolerance_clean() -> None:
    locs = _locs(1)
    acts = [
        {
            "id": "C",
            "name": "Concrete",
            "sequence_order": 1,
            "planned_cycle_duration_days": 3,
            "actual_cycle_duration_days": 3.5,
        },
    ]
    out = compute_line_of_balance_geometry(locs, acts, tolerance_days=1)
    # 0.5 deviation is within the 1-day tolerance → no violation.
    assert out["violations"] == []
    assert all(not b["has_rhythm_break"] for b in out["bars"])


def test_buffer_shifts_start() -> None:
    locs = _locs(1)
    acts = [
        {"id": "F", "name": "Formwork", "sequence_order": 1, "planned_cycle_duration_days": 5},
        {
            "id": "C",
            "name": "Concrete",
            "sequence_order": 2,
            "planned_cycle_duration_days": 3,
            "buffer_days_before": 2,
        },
    ]
    out = compute_line_of_balance_geometry(locs, acts)
    by = {b["activity_id"]: b for b in out["bars"]}
    # Concrete waits 2 buffer days after Formwork finishes at 5 → starts 7.
    assert by["C"]["start_day"] == 7
    assert by["C"]["end_day"] == 10


def test_makespan_and_average_cycle() -> None:
    locs = _locs(2)
    acts = [
        {"id": "F", "name": "Formwork", "sequence_order": 1, "planned_cycle_duration_days": 4},
        {"id": "C", "name": "Concrete", "sequence_order": 2, "planned_cycle_duration_days": 2},
    ]
    out = compute_line_of_balance_geometry(locs, acts)
    # 4 bars, durations 4,2,4,2 → average 3.0.
    assert out["average_cycle_days"] == 3.0
    assert out["total_makespan_days"] > 0


def test_takt_schedule_create_validation() -> None:
    # Valid payload round-trips.
    ts = TaktScheduleCreate(
        master_schedule_id="00000000-0000-0000-0000-000000000001",
        name="Tower L1-L6 Formwork",
        target_cycle_days=5,
        locations=[{"sequence_order": 1, "name": "L1"}, {"sequence_order": 2, "name": "L2"}],
    )
    assert ts.target_cycle_days == 5
    assert len(ts.locations) == 2

    # sequence_order must be >= 1.
    with pytest.raises(ValidationError):
        TaktScheduleCreate(
            master_schedule_id="00000000-0000-0000-0000-000000000001",
            name="x",
            locations=[{"sequence_order": 0, "name": "bad"}],
        )

    # Activity cycle duration must be >= 1.
    with pytest.raises(ValidationError):
        TaktActivityCreate(name="Formwork", planned_cycle_duration_days=0)

    a = TaktActivityCreate(
        name="Formwork",
        activity_code="FORM-001",
        planned_cycle_duration_days=5,
        crew_size=4,
        crew_skill_codes=["carpenter", "laborer"],
    )
    assert a.crew_size == 4
    assert a.crew_skill_codes == ["carpenter", "laborer"]
    # actual is Decimal-typed in the update schema; sanity that Decimal works.
    assert Decimal("5.5") > Decimal("3")
