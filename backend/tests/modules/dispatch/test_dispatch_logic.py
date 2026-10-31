# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board rules without a database: conflicts, unit status, moves, utilisation, prefill."""

from __future__ import annotations

from datetime import date

from app.modules.dispatch import logic

DAY = date(2026, 11, 3)


def _p(pid, kind, ref, loc, loc_kind="project", operator=None):
    return {
        "id": pid,
        "card_kind": kind,
        "card_ref": ref,
        "location_id": loc,
        "location_kind": loc_kind,
        "operator_ref": operator,
        "notes": "",
    }


def _kinds(facts):
    return [c.kind for c in logic.detect_conflicts(facts)]


def test_clean_board_has_no_conflicts():
    facts = logic.DayFacts(day=DAY, placements=[_p("1", "worker", "w1", "A"), _p("2", "equipment", "e1", "A")])
    assert logic.detect_conflicts(facts) == []


def test_worker_on_two_sites_is_double_booked_even_through_a_crew():
    facts = logic.DayFacts(
        day=DAY,
        placements=[_p("1", "worker", "w1", "A"), _p("2", "crew", "c1", "B")],
        crews={"c1": {"name": "Gang", "member_ids": ["w1", "w2"], "min_size": 0}},
    )
    conflicts = logic.detect_conflicts(facts)
    assert [c.kind for c in conflicts] == [logic.DOUBLE_BOOKED]
    assert conflicts[0].card_ref == "w1"
    assert conflicts[0].severity == "error"
    assert sorted(conflicts[0].placement_ids) == ["1", "2"]


def test_unit_and_its_rental_card_on_two_sites_is_double_booked():
    facts = logic.DayFacts(
        day=DAY,
        placements=[_p("1", "equipment", "e1", "A"), _p("2", "rental", "r1", "B")],
        rentals={"r1": "e1"},
    )
    assert _kinds(facts) == [logic.DOUBLE_BOOKED]


def test_scheduled_work_order_blocks_its_day_and_status_turns_maintenance():
    facts = logic.DayFacts(
        day=DAY,
        placements=[_p("1", "equipment", "e1", "A")],
        work_orders={"e1": [{"scheduled_for": DAY.isoformat(), "status": "scheduled"}]},
    )
    assert logic.MAINTENANCE_BLOCK in _kinds(facts)
    assert logic.unit_status("e1", facts) == "maintenance"


def test_in_progress_order_blocks_later_days_and_yard_is_fine():
    facts = logic.DayFacts(
        day=DAY,
        placements=[_p("1", "equipment", "e1", "Y", loc_kind="yard")],
        work_orders={"e1": [{"scheduled_for": "2026-11-01", "status": "in_progress"}]},
    )
    assert logic.unit_blocked("e1", DAY, facts)
    assert logic.MAINTENANCE_BLOCK not in _kinds(facts)


def test_overdue_maintenance_is_flagged():
    facts = logic.DayFacts(
        day=DAY,
        placements=[_p("1", "equipment", "e1", "A")],
        work_orders={"e1": [{"scheduled_for": "2026-10-20", "status": "scheduled"}]},
    )
    conflicts = logic.detect_conflicts(facts)
    assert [c.kind for c in conflicts] == [logic.MAINTENANCE_OVERDUE]
    assert conflicts[0].details["due"] == ["2026-10-20"]


def test_operator_without_required_certificate():
    facts = logic.DayFacts(
        day=DAY,
        placements=[_p("1", "equipment", "e1", "A", operator="w1")],
        required_certs={"e1": ["crane_operator", "first_aid"]},
        valid_certs={"w1": {"first_aid"}},
    )
    conflicts = logic.detect_conflicts(facts)
    assert [c.kind for c in conflicts] == [logic.MISSING_CERTIFICATE]
    assert conflicts[0].details["missing"] == ["crane_operator"]
    facts.valid_certs["w1"].add("crane_operator")
    assert logic.detect_conflicts(facts) == []


def test_absent_worker_and_crew_under_minimum():
    facts = logic.DayFacts(
        day=DAY,
        placements=[_p("1", "crew", "c1", "A")],
        crews={"c1": {"name": "Gang", "member_ids": ["w1", "w2", "w3"], "min_size": 3}},
        absences={"w2": "sick"},
    )
    assert _kinds(facts) == [logic.WORKER_ABSENT, logic.CREW_UNDER_MINIMUM]


def test_unit_status_assigned_available_in_transit():
    facts = logic.DayFacts(day=DAY, placements=[_p("1", "equipment", "e1", "A")])
    assert logic.unit_status("e1", facts) == "assigned"
    assert logic.unit_status("e2", facts) == "available"
    assert logic.unit_status("e1", facts, {"e1"}) == "in_transit"


def test_plan_move_is_idempotent():
    rows = [{"id": "1", "card_kind": "worker", "card_ref": "w1", "location_id": "A"}]
    assert logic.plan_move(rows, "worker", "w1", "B") == (["1"], True)
    after = [{"id": "2", "card_kind": "worker", "card_ref": "w1", "location_id": "B"}]
    assert logic.plan_move(after, "worker", "w1", "B") == ([], False)
    assert logic.plan_move([], "worker", "w1", "B") == ([], True)


def test_due_moves_only_pending_and_dated_today_or_earlier_oldest_first():
    moves = [
        {"id": 1, "status": "pending", "effective_date": date(2026, 11, 4)},
        {"id": 2, "status": "pending", "effective_date": date(2026, 11, 2)},
        {"id": 3, "status": "applied", "effective_date": date(2026, 11, 1)},
        {"id": 4, "status": "pending", "effective_date": DAY},
    ]
    assert [m["id"] for m in logic.due_moves(moves, DAY)] == [2, 4]


def test_utilisation_counts_working_days_on_projects_only():
    # 2026-11-02 is a Monday; the week has 5 working days.
    start, end = date(2026, 11, 2), date(2026, 11, 8)
    rows = [
        {"day": date(2026, 11, 2), "location_kind": "project", "unit_ref": "e1"},
        {"day": date(2026, 11, 3), "location_kind": "project", "unit_ref": "e1"},
        {"day": date(2026, 11, 4), "location_kind": "yard", "unit_ref": "e1"},
        {"day": date(2026, 11, 7), "location_kind": "project", "unit_ref": "e1"},
    ]
    out = {r["unit_ref"]: r for r in logic.utilisation(rows, ["e1", "e2"], start, end)}
    assert out["e1"]["days_assigned"] == 2
    assert out["e1"]["days_idle"] == 3
    assert out["e1"]["percent"] == 40
    assert out["e2"]["days_assigned"] == 0


def test_timesheet_lines_expand_crews_rentals_and_skip_existing():
    placements = [
        _p("1", "crew", "c1", "A"),
        _p("2", "worker", "w1", "A"),
        _p("3", "rental", "r1", "A", operator="w3"),
    ]
    crews = {"c1": {"member_ids": ["w1", "w2"]}}
    lines = logic.timesheet_lines(placements, crews, {"r1": "e9"}, hours=8, existing_resources={"w2"})
    assert [ln.get("resource_id") or ln.get("equipment_id") for ln in lines] == ["w1", "w3", "e9"]
    assert all(ln["hours"] == 8 for ln in lines)
