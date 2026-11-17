# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the revision-impact report: changed activities -> BOQ positions, variations, time and cost.

Worked example. Baseline B0 against the live plan:

* Foundations slips 5 days (finish 15.05 -> 20.05), its duration goes 5 -> 8 and
  its planned cost 20,000 -> 26,000. It carries positions 02.001 (15,000) and
  02.002 (5,000); 02.001 is in variation VR-003.
* Site office moves 1 day; it has no BOQ link.
* Fence (1,000, position 03.001) is gone from the live plan.
* Retaining wall is new, no planned cost yet, position 02.010 (4,800.50).
* Survey only reported progress: a progress update is not a revision.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.schedule.diff_engine import diff_snapshots
from app.modules.schedule.revision_impact import build_revision_impact

BASE = {
    "activities": [
        {"id": "a1", "name": "Excavation", "start_date": "2026-05-04", "end_date": "2026-05-08",
         "duration_days": 5, "cost_planned": "10000", "boq_position_ids": ["p1"]},
        {"id": "a2", "name": "Foundations", "start_date": "2026-05-11", "end_date": "2026-05-15",
         "duration_days": 5, "cost_planned": "20000", "boq_position_ids": ["p2", "p3"]},
        {"id": "a3", "name": "Fence", "start_date": "2026-05-04", "end_date": "2026-05-05",
         "duration_days": 2, "cost_planned": "1000", "boq_position_ids": ["p4"]},
        {"id": "a4", "name": "Survey", "start_date": "2026-05-04", "end_date": "2026-05-04",
         "duration_days": 1, "progress_pct": "0"},
        {"id": "a6", "name": "Site office", "start_date": "2026-05-04", "end_date": "2026-05-06",
         "duration_days": 3},
    ],
    "relationships": [],
    "calendars": {},
}  # fmt: skip

TARGET = {
    "activities": [
        {"id": "a1", "name": "Excavation", "start_date": "2026-05-04", "end_date": "2026-05-08",
         "duration_days": 5, "cost_planned": "10000", "boq_position_ids": ["p1"]},
        {"id": "a2", "name": "Foundations", "start_date": "2026-05-11", "end_date": "2026-05-20",
         "duration_days": 8, "cost_planned": "26000", "boq_position_ids": ["p2", "p3"]},
        {"id": "a4", "name": "Survey", "start_date": "2026-05-04", "end_date": "2026-05-04",
         "duration_days": 1, "progress_pct": "100"},
        {"id": "a5", "name": "Retaining wall", "start_date": "2026-05-21", "end_date": "2026-05-27",
         "duration_days": 5, "boq_position_ids": ["p5"]},
        {"id": "a6", "name": "Site office", "start_date": "2026-05-04", "end_date": "2026-05-07",
         "duration_days": 4},
    ],
    "relationships": [],
    "calendars": {},
}  # fmt: skip

POSITIONS = {
    "p1": {"ordinal": "01.001", "description": "Excavation", "unit": "m3", "quantity": "400", "total": "10000.00"},
    "p2": {"ordinal": "02.001", "description": "Concrete C30/37", "unit": "m3", "quantity": "100", "total": "15000"},
    "p3": {"ordinal": "02.002", "description": "Rebar", "unit": "t", "quantity": "5", "total": "5000"},
    "p4": {"ordinal": "03.001", "description": "Fence", "unit": "m", "quantity": "50", "total": "1000"},
    "p5": {"ordinal": "02.010", "description": "Retaining wall", "unit": "m2", "quantity": "30", "total": "4800.50"},
}
VARIATIONS = {
    "p2": [{"code": "VR-003", "title": "Deeper foundations", "status": "approved", "change_kind": "modified"}],
}


def _report():
    diff = diff_snapshots(BASE, TARGET)
    return build_revision_impact(diff, BASE, TARGET, positions=POSITIONS, variations=VARIATIONS)


def test_rows_are_the_revised_activities_largest_slip_first() -> None:
    rows = _report()["activities"]
    assert [r["name"] for r in rows] == ["Foundations", "Site office", "Fence", "Retaining wall"]


def test_slipped_activity_names_its_positions_variation_and_deltas() -> None:
    row = _report()["activities"][0]
    assert row["change_type"] == "modified"
    assert (row["finish_before"], row["finish_after"]) == ("2026-05-15", "2026-05-20")
    assert row["finish_movement_days"] == 5
    assert row["duration_delta_days"] == 3
    assert Decimal(row["cost_before"]) == 20000 and Decimal(row["cost_after"]) == 26000
    assert Decimal(row["cost_delta"]) == 6000
    assert [p["ordinal"] for p in row["positions"]] == ["02.001", "02.002"]
    assert Decimal(row["linked_value"]) == 20000
    assert row["positions"][0]["variations"][0]["code"] == "VR-003"
    assert row["positions"][1]["variations"] == []


def test_removed_activity_keeps_the_links_from_the_baseline() -> None:
    fence = next(r for r in _report()["activities"] if r["name"] == "Fence")
    assert fence["change_type"] == "removed"
    assert fence["finish_after"] is None
    assert Decimal(fence["cost_delta"]) == -1000
    assert [p["ordinal"] for p in fence["positions"]] == ["03.001"]


def test_added_activity_without_planned_cost_has_no_cost_delta() -> None:
    wall = next(r for r in _report()["activities"] if r["name"] == "Retaining wall")
    assert wall["change_type"] == "added"
    assert wall["cost_delta"] is None
    assert Decimal(wall["linked_value"]) == Decimal("4800.50")


def test_summary_totals() -> None:
    s = _report()["summary"]
    assert s["activities_revised"] == 4
    assert s["activities_linked"] == 3
    assert s["activities_unlinked"] == 1
    assert s["positions_linked"] == 4
    assert s["variations_linked"] == 1
    assert Decimal(s["cost_delta_total"]) == 5000
    assert Decimal(s["linked_value_total"]) == Decimal("25800.50")
    assert s["net_finish_movement_days"] == diff_snapshots(BASE, TARGET).summary.net_finish_movement_days


def test_position_deleted_from_the_bill_is_reported_missing() -> None:
    diff = diff_snapshots(BASE, TARGET)
    report = build_revision_impact(diff, BASE, TARGET, positions={}, variations={})
    row = report["activities"][0]
    assert all(p["missing"] for p in row["positions"])
    assert row["linked_value"] == "0"
