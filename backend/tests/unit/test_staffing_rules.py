# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The staffing rules as pure functions (SPEC section 4), table-driven.

Every test names its rule and carries the case that would pass if the rule
were missing: a derived status that a stored one would contradict, a day on
which one person is booked 1.1 FTE, a requirement only the employment basis
adds, a retention floor counted from the start rather than the end.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.fsm import FSMError
from app.modules.staffing import rules
from app.modules.staffing.catalogue import STAFFING_MODEL_KIND, register_kinds
from app.modules.staffing.fsm import FILE_FSM, FILL_FSM, LEAVE_FSM, PLAN_FSM, POSITION_FSM, TRAVEL_FSM

D = date


def _catalogue(cid: str = "neutral"):
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    register_kinds()
    return next(c for c in get_catalogue_kind(STAFFING_MODEL_KIND).shipped() if c.id == cid)


def _pos(pid="p1", **kw):
    base = {
        "id": pid,
        "role_code": "project_manager",
        "phase": "execution",
        "key_role": False,
        "handover_role": False,
        "required_before": None,
        "entry_date": D(2027, 1, 1),
        "exit_date": None,
        "fte": Decimal("1"),
        "headcount": 1,
        "status": "open",
    }
    return {**base, **kw}


def _fill(fid, pid="p1", share="1", start=D(2027, 1, 1), end=None, status="confirmed", member="m1"):
    return {
        "id": fid,
        "position_id": pid,
        "roster_member_id": member,
        "fte_share": Decimal(share),
        "from_date": start,
        "to_date": end,
        "status": status,
    }


# ── rule 1 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fte", "headcount", "entry", "exit_", "expected"),
    [
        (Decimal("1"), 1, D(2027, 1, 1), D(2027, 6, 1), []),
        (Decimal("0.1"), 3, None, None, []),
        (Decimal("0"), 1, None, None, ["fte_out_of_range"]),
        (Decimal("1.01"), 1, None, None, ["fte_out_of_range"]),
        (0.5, 1, None, None, ["fte_out_of_range"]),
        ("0.5", 0, None, None, ["headcount_invalid"]),
        ("0.5", 1, D(2027, 6, 1), D(2027, 1, 1), ["exit_before_entry"]),
    ],
)
def test_rule1_position_values(fte, headcount, entry, exit_, expected) -> None:
    assert rules.position_errors(fte, headcount, entry, exit_) == expected


def test_rule1_decimal_only() -> None:
    with pytest.raises(ValueError, match="decimal_required"):
        rules.dec(0.5)
    with pytest.raises(ValueError, match="decimal_required"):
        rules.dec(True)
    assert rules.dec("0.25") == Decimal("0.25")


# ── rule 2 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("position", "fills", "expected"),
    [
        (_pos(), [], "open"),
        (_pos(status="recruiting"), [_fill("f1", status="proposed")], "recruiting"),
        (_pos(), [_fill("f1")], "filled"),
        # Job share: two halves fill one position.
        (_pos(), [_fill("f1", share="0.5"), _fill("f2", share="0.5", member="m2")], "filled"),
        # Half is not enough; a stored "filled" could not say so.
        (_pos(), [_fill("f1", share="0.5")], "open"),
        # Headcount 2 needs 2.0 FTE.
        (_pos(headcount=2), [_fill("f1")], "open"),
        # A fill starting after the entry date does not fill the position on its entry date.
        (_pos(), [_fill("f1", start=D(2027, 2, 1))], "open"),
        (_pos(status="on_hold"), [_fill("f1")], "on_hold"),
    ],
)
def test_rule2_filled_is_derived(position, fills, expected) -> None:
    assert rules.effective_position_status(position, fills) == expected


# ── rule 4 ─────────────────────────────────────────────────────────────────


def test_rule4_overallocation_found_on_the_overlapping_day() -> None:
    fills = [
        _fill("a", pid="p1", share="0.6", start=D(2027, 1, 1), end=D(2027, 3, 31)),
        _fill("b", pid="p2", share="0.5", start=D(2027, 3, 1)),
    ]
    day, total = rules.first_overallocated_day(fills)
    assert day == D(2027, 3, 1)
    assert total == Decimal("1.1")


def test_rule4_succession_and_proposed_are_not_overallocation() -> None:
    fills = [
        _fill("a", pid="p1", share="1", start=D(2027, 1, 1), end=D(2027, 2, 28)),
        _fill("b", pid="p2", share="1", start=D(2027, 3, 1)),
        _fill("c", pid="p3", share="1", start=D(2027, 1, 1), status="proposed"),
    ]
    assert rules.first_overallocated_day(fills) is None


# ── rule 5 ─────────────────────────────────────────────────────────────────


def test_rule5_key_role_not_filled_on_gate_date() -> None:
    key = _pos(key_role=True, required_before="t1", entry_date=D(2027, 1, 1))
    late = [_fill("f1", start=D(2027, 5, 1))]
    on_time = [_fill("f1", start=D(2027, 3, 1))]
    assert [f.code for f in rules.key_role_gate_findings([key], late, ["t1"], D(2027, 4, 1))] == [
        "key_role_not_filled_before_gate"
    ]
    assert rules.key_role_gate_findings([key], on_time, ["t1"], D(2027, 4, 1)) == []
    # A gate that enables something else does not ask for this role.
    assert rules.key_role_gate_findings([key], [], ["t2"], D(2027, 4, 1)) == []
    # No planned date on the gate: the role only has to be filled.
    assert rules.key_role_gate_findings([key], late, ["t1"], None) == []
    assert len(rules.key_role_gate_findings([key], [], ["t1"], None)) == 1


# ── rule 6 ─────────────────────────────────────────────────────────────────


def _full_plan(cat, commissioning: date):
    positions = []
    for r in cat.roles:
        if r.key_role:
            positions.append(
                _pos(
                    pid=r.code,
                    role_code=r.code,
                    key_role=True,
                    handover_role=r.handover_role,
                    entry_date=D(2027, 1, 1),
                )
            )
    return positions


def test_rule6_submission_needs_key_roles_operation_entry_and_handover() -> None:
    cat = _catalogue()
    positions = _full_plan(cat, D(2028, 1, 1))
    fills = [_fill(f"f-{p['id']}", pid=p["id"]) for p in positions]
    handovers = [
        {"id": f"h-{p['id']}", "from_fill_id": f"f-{p['id']}", "to_position_id": "later", "overlap_days": 10}
        for p in positions
        if p["handover_role"]
    ]
    assert rules.submission_findings(cat, positions, fills, handovers, D(2028, 1, 1)) == []

    without_pm = [p for p in positions if p["role_code"] != "project_manager"]
    codes = {f.code for f in rules.submission_findings(cat, without_pm, fills, handovers, D(2028, 1, 1))}
    assert "key_role_missing" in codes

    late = {f.code for f in rules.submission_findings(cat, positions, fills, handovers, D(2026, 1, 1))}
    assert "operation_role_late" in late
    assert "commissioning_date_missing" in {
        f.code for f in rules.submission_findings(cat, positions, fills, handovers, None)
    }

    zero = [{**h, "overlap_days": 0} for h in handovers]
    assert "handover_missing" in {f.code for f in rules.submission_findings(cat, positions, fills, zero, D(2028, 1, 1))}


# ── rule 8 ─────────────────────────────────────────────────────────────────


def test_rule8_requirement_union_and_country_kinds() -> None:
    cat = _catalogue()
    pm = set(rules.required_document_kinds(cat, ["project_manager"], "employee", False))
    site = set(rules.required_document_kinds(cat, ["project_manager", "site_manager"], "employee", False))
    assert pm == {"employment_contract"}
    assert {"site_induction", "occupational_health_certificate", "professional_licence"} <= site
    posted = rules.required_document_kinds(cat, ["project_manager"], "posted_worker", False)
    assert "a1_posting_certificate" in posted
    permit = rules.required_document_kinds(cat, ["project_manager"], "employee", True)
    assert "work_permit" in permit and "a1_posting_certificate" not in permit


@pytest.mark.parametrize(
    ("docs", "cleared", "missing", "expired"),
    [
        ({"work_permit": {"status_on_start": "active"}}, True, [], []),
        ({"work_permit": {"status_on_start": "expiring_soon"}}, True, [], []),
        ({"work_permit": {"status_on_start": "expired"}}, False, [], ["work_permit"]),
        ({}, False, ["work_permit"], []),
        ({"work_permit": {"status_on_start": None, "waived": True}}, True, [], []),
    ],
)
def test_rule8_cleared_to_work(docs, cleared, missing, expired) -> None:
    out = rules.clearance(["work_permit"], docs)
    assert (out["cleared"], out["missing"], out["expired"]) == (cleared, missing, expired)


# ── rule 12 ────────────────────────────────────────────────────────────────


def test_rule12_only_last_four_characters() -> None:
    assert rules.masked_number("A123", True) == "A123"
    assert rules.masked_number(None, False) is None
    with pytest.raises(ValueError, match="full_number_rejected"):
        rules.masked_number("C01X00T47", True)
    with pytest.raises(ValueError, match="number_not_stored"):
        rules.masked_number("1234", False)


# ── rules 14 and 15 ────────────────────────────────────────────────────────


def test_rule14_retention_due_is_the_latest_rule_end() -> None:
    cat = _catalogue()
    docs = [
        {"document_kind": "employment_contract", "valid_until": None},
        {"document_kind": "passport", "valid_until": D(2031, 5, 31)},
    ]
    due = rules.retention_due(cat, docs, assignment_start=D(2027, 1, 1), assignment_end=D(2028, 1, 31))
    # 24 months after the end (2030-01-31) vs 12 months after the passport expires (2032-05-31).
    assert due == D(2032, 5, 31)
    assert rules.retention_due(cat, [], assignment_start=None, assignment_end=D(2028, 1, 31)) == D(2030, 1, 31)
    assert rules.retention_due(cat, docs, assignment_start=None, assignment_end=None) == D(2032, 5, 31)


def test_rule14_floor_from_start_wins_when_later() -> None:
    cat = _catalogue("us")
    rule = cat.retention_rule("us_i9")
    short = rules.retention_end(rule, assignment_start=D(2027, 1, 1), assignment_end=D(2027, 6, 30))
    long = rules.retention_end(rule, assignment_start=D(2027, 1, 1), assignment_end=D(2031, 6, 30))
    assert short == D(2030, 1, 1)  # 3 years after start beats 1 year after the end
    assert long == D(2032, 6, 30)


def test_rule15_legal_obligation_blocks_erasure_until_its_end() -> None:
    cat = _catalogue("uk")
    docs = [{"document_kind": "right_to_work_check", "valid_until": None}]
    running, until = rules.legal_obligation_running(
        cat, docs, assignment_start=D(2027, 1, 1), assignment_end=D(2027, 12, 31), today=D(2028, 6, 1)
    )
    assert running and until == D(2029, 12, 31)
    running, _ = rules.legal_obligation_running(
        cat, docs, assignment_start=D(2027, 1, 1), assignment_end=D(2027, 12, 31), today=D(2030, 1, 1)
    )
    assert not running
    # Neutral catalogue: no statutory duty, erasure proceeds.
    running, _ = rules.legal_obligation_running(
        _catalogue(), docs, assignment_start=None, assignment_end=None, today=D(2028, 1, 1)
    )
    assert not running


def test_add_months_clamps_to_month_end() -> None:
    assert rules.add_months(D(2027, 1, 31), 1) == D(2027, 2, 28)
    assert rules.add_months(D(2027, 11, 15), 3) == D(2028, 2, 15)


# ── rules 16, 17, 18 ───────────────────────────────────────────────────────


def test_rule16_leave_over_mobilisation_or_gate_warns() -> None:
    leave = {"id": "l1", "from_date": D(2027, 3, 1), "to_date": D(2027, 3, 10), "status": "requested"}
    mob = [{"kind": "mobilisation", "depart_date": D(2027, 3, 5), "status": "booked"}]
    assert [f.code for f in rules.leave_findings(leave, mob, [])] == ["leave_conflicts_gate"]
    assert [f.code for f in rules.leave_findings(leave, [], [D(2027, 3, 2)])] == ["leave_conflicts_gate"]
    assert rules.leave_findings(leave, [], [D(2027, 4, 1)]) == []
    assert rules.leave_findings({**leave, "status": "cancelled"}, mob, []) == []


def test_rule17_travel_after_assignment_and_missing_demobilisation() -> None:
    trips = [{"id": "t1", "kind": "rotation", "return_date": D(2027, 7, 2), "status": "booked"}]
    codes = {f.code for f in rules.travel_findings(trips, D(2027, 6, 30), "ended")}
    assert codes == {"travel_after_assignment", "demobilisation_missing"}
    trips.append({"id": "t2", "kind": "demobilisation", "return_date": None, "status": "planned"})
    assert {f.code for f in rules.travel_findings(trips, D(2027, 7, 31), "ended")} == set()


def test_rule18_remote_site_needs_a_bed_on_day_one() -> None:
    covering = [{"check_in": D(2027, 2, 28), "check_out": None, "status": "reserved"}]
    late = [{"check_in": D(2027, 3, 5), "check_out": None, "status": "reserved"}]
    assert rules.accommodation_finding(True, D(2027, 3, 1), covering, "m1") is None
    assert rules.accommodation_finding(True, D(2027, 3, 1), late, "m1").code == "no_accommodation"
    assert rules.accommodation_finding(False, D(2027, 3, 1), [], "m1") is None


# ── lifecycles ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fsm", "current", "target", "ok"),
    [
        (PLAN_FSM, "draft", "in_review", True),
        (PLAN_FSM, "draft", "approved", False),
        (PLAN_FSM, "in_review", "approved", True),
        (PLAN_FSM, "approved", "binding", True),
        (PLAN_FSM, "binding", "draft", False),
        (PLAN_FSM, "binding", "revising", True),
        (PLAN_FSM, "revising", "in_review", True),
        (POSITION_FSM, "open", "recruiting", True),
        (POSITION_FSM, "open", "filled", False),
        (POSITION_FSM, "cancelled", "open", False),
        (FILL_FSM, "proposed", "confirmed", True),
        (FILL_FSM, "ended", "confirmed", False),
        (FILE_FSM, "ended", "anonymised", True),
        (FILE_FSM, "retention_hold", "anonymised", False),
        (FILE_FSM, "anonymised", "active", False),
        (TRAVEL_FSM, "planned", "booked", True),
        (TRAVEL_FSM, "done", "planned", False),
        (LEAVE_FSM, "requested", "approved", True),
        (LEAVE_FSM, "taken", "requested", False),
    ],
)
def test_lifecycles(fsm, current, target, ok) -> None:
    if ok:
        fsm.validate(current, target)
    else:
        with pytest.raises(FSMError):
            fsm.validate(current, target)
