# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure roadmap and condition logic of the permits module: rules 3, 6, 9, 10, 11, 12, 14, 15, 19."""

from __future__ import annotations

from datetime import date

from app.modules.permits.catalogue import Period, Validity
from app.modules.permits.conditions import (
    CondView,
    Item,
    NewCondition,
    OldCondition,
    PermitView,
    ReqView,
    blocked_activities,
    breach_risk,
    carry_forward,
    extended_until,
    handover_readiness,
    lapse_warning,
    register_readiness,
    roadmap_readiness,
    start_readiness,
    text_hash,
    valid_until,
)
from app.modules.permits.roadmap import (
    AttemptView,
    Edge,
    TimelineInput,
    derive_state,
    find_cycle,
    needed_by,
    timeline,
    unmet_dependencies,
)

# ── rule 3: dependencies ────────────────────────────────────────────────────


def test_cycle_is_found_and_acyclic_graph_passes() -> None:
    assert find_cycle([Edge("a", "b"), Edge("b", "c")]) is None
    cycle = find_cycle([Edge("a", "b"), Edge("b", "c"), Edge("c", "a")])
    assert cycle is not None and cycle[0] == cycle[-1]
    assert find_cycle([Edge("a", "a")]) == ["a", "a"]


def test_unmet_dependencies_by_edge_type() -> None:
    edges = [Edge("permit", "prelim", "granted"), Edge("early", "permit", "submitted")]
    states = {"prelim": "in_progress", "permit": "in_progress"}
    assert unmet_dependencies("permit", edges, states, {"prelim": True}) == ["prelim"]
    assert unmet_dependencies("early", edges, states, {"permit": True}) == []
    assert unmet_dependencies("early", edges, states, {"permit": False}) == ["permit"]
    assert unmet_dependencies("permit", edges, {"prelim": "granted"}, {}) == []
    assert unmet_dependencies("permit", edges, {"prelim": "not_applicable"}, {}) == []


def test_derived_requirement_state() -> None:
    assert derive_state(False, None, True) == "not_applicable"
    assert derive_state(True, None, False) == "blocked"
    assert derive_state(True, None, True) == "not_started"
    assert derive_state(True, AttemptView("under_review"), True) == "in_progress"
    assert derive_state(True, AttemptView("decided", "granted_with_conditions"), True) == "granted"
    assert derive_state(True, AttemptView("decided", "deemed_granted"), True) == "granted"
    assert derive_state(True, AttemptView("decided", "partially_granted"), True) == "partially_granted"
    assert derive_state(True, AttemptView("decided", "refused"), True) == "refused"
    assert derive_state(True, AttemptView("withdrawn"), True) == "not_started"


# ── rule 6: timeline ───────────────────────────────────────────────────────


def test_needed_by_fallbacks_and_basis() -> None:
    act = {"late_start": "2026-09-01", "early_start": "2026-08-01", "constraint_date": "2026-07-01"}
    assert needed_by(act, date(2026, 1, 1)) == (date(2026, 9, 1), "late_start")
    assert needed_by({**act, "late_start": None}, None) == (date(2026, 8, 1), "early_start")
    assert needed_by({"constraint_date": "2026-07-01"}, None) == (date(2026, 7, 1), "constraint_date")
    assert needed_by(None, date(2026, 1, 1)) == (date(2026, 1, 1), "fixed_date")
    assert needed_by({}, None) == (None, None)


def test_latest_submit_walks_the_dependency_chain_and_flags_conflicts() -> None:
    rows = [
        TimelineInput("permit", date(2026, 9, 1), "late_start", 210, buffer_days=14, forecast=date(2026, 9, 10)),
        TimelineInput("prelim", None, None, 90, buffer_days=0, planned_submit=date(2025, 10, 1)),
    ]
    out = {r.id: r for r in timeline(rows, [Edge("permit", "prelim", "granted")])}
    permit = out["permit"]
    assert permit.latest_decision == date(2026, 8, 18)
    assert permit.latest_submit == date(2026, 1, 20)
    assert permit.schedule_conflict and permit.conflict_days == 23
    prelim = out["prelim"]
    # The prerequisite must be decided by the time the permit has to be filed.
    assert prelim.needed_by == date(2026, 1, 20) and prelim.date_basis == "dependency"
    assert prelim.latest_submit == date(2025, 10, 22)
    assert prelim.forecast == date(2025, 12, 30) and not prelim.schedule_conflict


def test_no_conflict_without_a_forecast() -> None:
    (row,) = timeline([TimelineInput("x", date(2026, 9, 1), "fixed_date", None)], [])
    assert row.latest_submit is None and not row.schedule_conflict


# ── rules 10, 12, 19: readiness ────────────────────────────────────────────

REQ = ReqView("r1", "baugenehmigung", "building", "full", ("site_start", "construction"), "granted", title="Permit")
PERMIT = PermitView("p1", "r1", "baugenehmigung", "building", "full", "in_force", ("site_start",))
REQUIRES = ("baugenehmigung",)
START = ("site_start", "construction")


def _cond(**kw) -> CondView:
    base = {"id": "c1", "number": "N 1", "permit_id": "p1", "kind": "suspensive", "trigger": "before_start"}
    return CondView(**{**base, "state": "open", "owner_user_id": "u1", **kw})


def test_open_suspensive_before_start_condition_blocks_start() -> None:
    r = start_readiness([REQ], [PERMIT], [_cond()])
    assert r.status == "not_ready"
    assert any(i.code == "suspensive_condition_open" and i.detail == "N 1" for i in r.items)
    assert start_readiness([REQ], [PERMIT], [_cond(state="discharged")]).status == "ready"


def test_obligation_does_not_suspend_but_open_before_start_obligation_blocks_unless_accepted_at_gate() -> None:
    ongoing = _cond(kind="obligation", trigger="ongoing")
    assert start_readiness([REQ], [PERMIT], [ongoing]).status == "ready"
    before = _cond(kind="obligation")
    assert start_readiness([REQ], [PERMIT], [before]).status == "not_ready"
    assert start_readiness([REQ], [PERMIT], [_cond(kind="obligation", gate_condition_id="g1")]).status == "at_risk"
    overdue = _cond(kind="obligation", trigger="ongoing", due_date=date(2026, 1, 1))
    assert breach_risk(overdue, date(2026, 2, 1)) and not breach_risk(
        _cond(due_date=date(2026, 1, 1)), date(2026, 2, 1)
    )


def test_unconfirmed_ai_proposals_never_count() -> None:
    assert start_readiness([REQ], [PERMIT], [_cond(confirmed=False)]).status == "ready"
    assert register_readiness([REQ], [_cond(confirmed=False, owner_user_id=None)]).status == "ready"


def test_early_start_is_start_at_risk_never_the_full_permit() -> None:
    pending = ReqView("r1", "baugenehmigung", "building", "full", ("site_start",), "in_progress")
    early = PermitView(
        "p2", "r2", "vorzeitiger_baubeginn", "early_start", "early_start", "in_force", ("site_start",), (), REQUIRES
    )
    assert start_readiness([pending], [], []).status == "not_ready"
    r = start_readiness([pending], [early], [])
    assert r.status == "at_risk" and r.items[0].code == "start_at_risk_early_start"
    revoked = PermitView("p2", "r2", "x", "early_start", "early_start", "revoked", ("site_start",), (), REQUIRES)
    assert start_readiness([pending], [revoked], []).status == "not_ready"


def test_handover_needs_occupancy_permit_and_no_open_before_occupation_condition() -> None:
    occ = ReqView("r9", "occ", "occupancy", "full", ("occupation",), "in_progress")
    assert handover_readiness([REQ, occ], [PERMIT], []).status == "not_ready"
    occ_ok = ReqView("r9", "occ", "occupancy", "full", ("occupation",), "granted")
    assert handover_readiness([REQ, occ_ok], [PERMIT], []).status == "ready"
    cond = _cond(trigger="before_occupation")
    assert handover_readiness([occ_ok], [PERMIT], [cond]).status == "not_ready"


def test_roadmap_and_register_checks() -> None:
    planned = ReqView("r1", "x", "building", "full", ("site_start",), "not_started")
    assert roadmap_readiness([planned], START).status == "not_ready"
    assert roadmap_readiness([planned], ("occupation",)).status == "ready"
    filed = ReqView("r1", "x", "building", "full", ("site_start",), "in_progress", True, True, submitted=True)
    assert roadmap_readiness([filed], START).status == "not_ready"
    accepted = ReqView("r1", "x", "building", "full", ("site_start",), "in_progress", True, True, True, submitted=True)
    assert roadmap_readiness([accepted], START).status == "ready"
    pending = ReqView("r1", "x", "building", "full", (), "granted", conditions_pending=True)
    assert register_readiness([pending], []).status == "not_ready"
    assert register_readiness([REQ], [_cond(owner_user_id=None)]).status == "not_ready"
    assert register_readiness([REQ], [_cond(trigger="")]).status == "not_ready"
    assert register_readiness([REQ], [_cond()]).status == "ready"


def test_partial_permit_blocks_activities_outside_its_scope() -> None:
    out = blocked_activities({"a1": "r1", "a2": "r1", "a3": "r2"}, {"r1": ["a1"]}, {"r1": "partially_granted"})
    assert out == {"a1": "permitted", "a2": "blocked_by_permit", "a3": "blocked_by_permit"}


# ── rule 9: validity ───────────────────────────────────────────────────────


def test_validity_lapse_and_warnings() -> None:
    v = Validity(
        lapse_if_not_started=Period(period=3, unit="years"),
        extension_per_request=Period(period=1, unit="years"),
        source_url="https://example.invalid/x",
        review_status="unconfirmed",
    )
    until = valid_until(date(2026, 3, 1), None, v)
    assert until == date(2029, 3, 1)
    assert valid_until(date(2026, 3, 1), date(2026, 6, 1), v) is None
    assert extended_until(until, v) == date(2030, 3, 1)
    assert lapse_warning(until, date(2028, 11, 1)) is None
    assert lapse_warning(until, date(2028, 12, 2))["level"] == "d90"
    assert lapse_warning(until, date(2029, 2, 1))["level"] == "d30"
    assert lapse_warning(until, date(2029, 2, 25))["level"] == "d7"
    assert lapse_warning(until, date(2029, 3, 2))["level"] == "lapsed"


# ── rule 14: variation carry-forward ───────────────────────────────────────


def test_variation_keeps_discharge_only_when_text_is_unchanged() -> None:
    old = [
        OldCondition("c1", "1", "Submit a noise plan.", "suspensive", "before_start", "discharged"),
        OldCondition("c2", "2", "Work hours 07:00 to 19:00.", "obligation", "ongoing", "in_compliance"),
        OldCondition("c3", "3", "Plant 12 trees.", "obligation", "before_occupation", "discharged"),
        OldCondition("c4", "4", "Old condition to drop.", "obligation", "ongoing", "open"),
    ]
    out = {
        c.number: c
        for c in carry_forward(
            old,
            [
                NewCondition("2", "Work hours 07:00 to 18:00.", "obligation", "ongoing"),
                NewCondition("3", "Plant  12 trees. ", "obligation", "before_occupation"),
                NewCondition("5", "New condition.", "obligation", "ongoing"),
            ],
            removed_numbers=["4"],
        )
    }
    assert out["1"].keep_state == "discharged" and out["1"].original_id == "c1"
    assert out["2"].keep_state is None  # text changed: reopens
    assert out["3"].keep_state == "discharged"  # whitespace only: same hash
    assert "4" not in out
    assert out["5"].original_id is None and out["5"].keep_state is None
    assert text_hash("a  b") == text_hash(" a b ")


# ── a permit the roadmap needs only after the gate date warns, it does not block ──

GATE_DAY = date(2026, 11, 2)


def _road(needed_by: date | None, state: str = "in_progress") -> ReqView:
    return ReqView(
        "r9", "road_occupation", "traffic_road", "full", ("site_start",), state, title="Road", needed_by=needed_by
    )


def test_a_permit_without_a_needed_by_date_blocks() -> None:
    r = start_readiness([REQ, _road(None)], [PERMIT], [], GATE_DAY)
    assert r.status == "not_ready"
    assert [(i.code, i.state) for i in r.items] == [("permit_granted", "met"), ("permit_missing", "not_met")]


def test_a_permit_needed_on_or_before_the_gate_date_blocks() -> None:
    for needed in (date(2026, 10, 1), GATE_DAY):
        r = start_readiness([REQ, _road(needed)], [PERMIT], [], GATE_DAY)
        assert r.status == "not_ready" and r.items[-1].code == "permit_missing", needed


def test_a_permit_needed_after_the_gate_date_is_a_warning_that_names_the_date() -> None:
    later = date(2027, 4, 5)
    r = start_readiness([REQ, _road(later)], [PERMIT], [], GATE_DAY)
    assert r.status == "ready"
    assert r.items[-1] == Item("permit_due_later", "warning", "Road 2027-04-05", "r9", "Road", later)
    # The title and the day are also served apart from the sentence, and only on this item.
    said = r.as_dict()["items"]
    assert (said[-1]["title"], said[-1]["needed_by"]) == ("Road", "2027-04-05")
    assert "needed_by" not in said[0] and "title" not in said[0]
    # Never silent: the warning is an item of the check, and a granted permit raises none.
    assert [i["state"] for i in r.as_dict()["items"]] == ["met", "warning"]
    granted = PermitView("p9", "r9", "road_occupation", "traffic_road", "full", "in_force", ("site_start",))
    done = start_readiness([REQ, _road(later, "granted")], [PERMIT, granted], [], GATE_DAY)
    assert [i.code for i in done.items] == ["permit_granted", "permit_granted"]
    # A warning does not hide a blocker next to it.
    mixed = start_readiness([REQ, _road(later)], [PERMIT], [_cond()], GATE_DAY)
    assert mixed.status == "not_ready"


def test_without_a_gate_date_every_missing_permit_blocks() -> None:
    """The site is to start now (site readiness, the readiness screen): nothing is needed later."""
    r = start_readiness([REQ, _road(date(2027, 4, 5))], [PERMIT], [])
    assert r.status == "not_ready" and r.items[-1].code == "permit_missing"
