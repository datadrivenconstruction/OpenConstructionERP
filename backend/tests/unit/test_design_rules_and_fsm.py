# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design management rules and state machines, without a database.

WBS tree rules (SPEC rules 1-3), deliverable state (15), release content and
distribution (12-14), report acceptance (17, 18), permit completeness (19),
phase readiness (16), and every FSM table-driven: each legal move passes and
a sample of illegal ones is refused.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.design_management import fsm as dfsm
from app.modules.design_management import rules as r
from app.modules.design_management import wbs as w


def _n(code: str, parent: w.Node | None = None, closed: bool = False) -> w.Node:
    return w.Node(uuid.uuid4(), parent.id if parent else None, code, closed)


# ── WBS (rules 1-3) ──


def test_duplicate_codes_are_listed_case_insensitively() -> None:
    a, b, c = _n("1.1"), _n("1.1"), _n("1.2")
    d = _n("x.1")
    e = _n("X.1")
    assert w.duplicate_codes([a, b, c]) == {"1.1": [a.id, b.id]}
    assert list(w.duplicate_codes([d, e]).values()) == [[d.id, e.id]]
    assert w.duplicate_codes([a, c]) == {}


def test_new_code_must_be_unique() -> None:
    root = _n("1")
    with pytest.raises(w.WbsRuleError) as exc:
        w.check_code([root, _n("1.1", root)], code="1.1", parent_id=root.id)
    assert exc.value.code == "wbs_code_duplicate"
    w.check_code([root], code="1.1", parent_id=root.id)


def test_renaming_a_node_to_its_own_code_is_not_a_duplicate() -> None:
    root = _n("1")
    w.check_code([root], code="1", parent_id=None, node_id=root.id)


def test_hierarchical_codes_need_the_parent_prefix_and_can_be_switched_off() -> None:
    root = _n("1")
    with pytest.raises(w.WbsRuleError) as exc:
        w.check_code([root], code="2.1", parent_id=root.id)
    assert exc.value.code == "wbs_code_not_under_parent"
    with pytest.raises(w.WbsRuleError):
        w.check_code([root], code="1.", parent_id=root.id)
    w.check_code([root], code="2.1", parent_id=root.id, hierarchical=False)
    w.check_code([root], code="1-4", parent_id=root.id, separator="-")


def test_closed_parent_refuses_new_children() -> None:
    root = _n("1", closed=True)
    with pytest.raises(w.WbsRuleError) as exc:
        w.check_code([root], code="1.1", parent_id=root.id)
    assert exc.value.code == "wbs_node_closed"


def test_moving_under_own_descendant_is_a_cycle() -> None:
    root = _n("1")
    child = _n("1.1", root)
    grand = _n("1.1.1", child)
    with pytest.raises(w.WbsRuleError) as exc:
        w.check_code([root, child, grand], code="1.1", parent_id=grand.id, node_id=child.id, hierarchical=False)
    assert exc.value.code == "wbs_move_cycle"


def test_renumber_moves_the_whole_subtree() -> None:
    root = _n("1")
    child = _n("1.1", root)
    grand = _n("1.1.1", child)
    odd = _n("ZZ", child)
    other = _n("2")
    plan = w.renumber_plan([root, child, grand, odd, other], child.id, "1.5")
    assert plan == {child.id: "1.5", grand.id: "1.5.1"}


def test_renumber_onto_a_taken_code_applies_nothing() -> None:
    root = _n("1")
    child = _n("1.1", root)
    grand = _n("1.1.1", child)
    taken = _n("1.5.1", root)
    with pytest.raises(w.WbsRuleError) as exc:
        w.renumber_plan([root, child, grand, taken], child.id, "1.5")
    assert exc.value.code == "wbs_code_duplicate"


def test_a_node_whose_descendant_is_referenced_cannot_be_deleted() -> None:
    root = _n("1")
    child = _n("1.1", root)
    grand = _n("1.1.1", child)
    nodes = [root, child, grand]
    assert w.deletable(nodes, child.id, set())
    assert not w.deletable(nodes, child.id, {grand.id})
    assert not w.deletable(nodes, root.id, {grand.id})
    assert w.deletable(nodes, grand.id, {root.id})


# ── deliverables (rule 15) ──


def _d(state: str, code: str | None, rev: bool = True) -> r.DrawingState:
    return r.DrawingState(uuid.uuid4(), state, code, rev)


@pytest.mark.parametrize(
    ("drawings", "planned", "target", "expected"),
    [
        ([], 2, "S4", "not_started"),
        ([_d("wip", "S0", rev=False)], 1, "S4", "not_started"),
        ([_d("wip", "S0")], 1, "S4", "in_progress"),
        ([_d("shared", "S2"), _d("wip", "S0")], 2, "S4", "in_progress"),
        ([_d("shared", "S2"), _d("shared", "S3")], 2, "S4", "issued_for_review"),
        ([_d("shared", "S4"), _d("published", "A1")], 2, "S4", "accepted"),
        # count not met: never accepted even if every drawing is at target
        ([_d("published", "A1")], 2, "S4", "in_progress"),
        ([_d("shared", "S4")], 1, "A1", "issued_for_review"),
        ([_d("archived", "AR"), _d("published", "A1")], 1, "S4", "accepted"),
    ],
)
def test_deliverable_state_is_computed(drawings, planned, target, expected) -> None:
    assert r.deliverable_state(drawings, planned_count=planned, target_suitability=target) == expected


def test_waived_wins_and_is_the_only_typed_state() -> None:
    assert r.deliverable_state([], planned_count=3, target_suitability=None, waived=True) == "waived"


# ── releases and distribution (rules 12-14) ──


def _rev(code: str, disc: str = "A", form: str = "DR", phase: str = "lph5") -> r.RevisionView:
    return r.RevisionView(uuid.uuid4(), uuid.uuid4(), code, disc, form, phase)


def test_release_refuses_wip_and_construction_without_published() -> None:
    wip, shared, pub = _rev("S0"), _rev("S2"), _rev("A1")
    assert r.release_content_errors([wip, shared, pub], "for_information") == [
        (wip.revision_id, "release_contains_wip")
    ]
    errs = r.release_content_errors([shared, pub], "for_construction")
    assert errs == [(shared.revision_id, "release_needs_published")]


def test_one_plan_per_matching_recipient_with_exclusions_and_duplicates() -> None:
    a1, s2, struct = _rev("A1"), _rev("S2"), _rev("A1", disc="S")
    arch_rule = r.MatrixRule(uuid.uuid4(), "list:arch", discipline_codes=("A",), min_suitability="A1")
    all_rule = r.MatrixRule(uuid.uuid4(), "role:owner")
    struct_rule = r.MatrixRule(uuid.uuid4(), "list:arch", discipline_codes=("S",))
    plans = {
        p.recipient_key: p
        for p in r.distribution_plan(
            [arch_rule, all_rule, struct_rule],
            [a1, s2, struct],
            purpose="for_review",
            already_issued={("role:owner", a1.revision_id)},
        )
    }
    assert {p.purpose for p in plans.values()} == {"for_review"}
    assert set(plans) == {"list:arch", "role:owner"}
    assert plans["list:arch"].revision_ids == [a1.revision_id, struct.revision_id]
    assert plans["list:arch"].excluded == [(s2.revision_id, "below_min_suitability")]
    assert plans["role:owner"].revision_ids == [a1.revision_id, s2.revision_id, struct.revision_id]
    assert plans["role:owner"].duplicates == [a1.revision_id]


def test_a_recipient_with_nothing_matching_gets_no_transmittal() -> None:
    rule = r.MatrixRule(uuid.uuid4(), "list:mep", discipline_codes=("M",))
    assert r.distribution_plan([rule], [_rev("A1")], purpose="for_information") == []


def test_a_rule_purpose_only_narrows_and_never_changes_what_is_sent() -> None:
    """Finding 5: the plan carries the release's purpose; a rule naming another purpose does not apply."""
    rev = _rev("S2")
    build = r.MatrixRule(uuid.uuid4(), "role:site", purpose="for_construction")
    anyone = r.MatrixRule(uuid.uuid4(), "role:owner")
    info = r.distribution_plan([build, anyone], [rev], purpose="for_information")
    assert [(p.recipient_key, p.purpose) for p in info] == [("role:owner", "for_information")]
    construction = r.distribution_plan([build, anyone], [rev], purpose="for_construction")
    assert {(p.recipient_key, p.purpose) for p in construction} == {
        ("role:site", "for_construction"),
        ("role:owner", "for_construction"),
    }


# ── reports (rules 17, 18) ──


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"independent_check": "none", "checker_party": None}, None),
        ({"independent_check": "optional", "checker_party": None}, None),
        ({"independent_check": "required_by_rule", "checker_party": None}, "report_checker_required"),
        (
            {"independent_check": "required_by_rule", "checker_party": "contact:2", "author_party": None},
            "report_author_required",
        ),
        ({"independent_check": "required_by_rule", "checker_party": "contact:1"}, "report_checker_same_party"),
        (
            {"independent_check": "required_by_rule", "checker_party": "contact:2", "external": True},
            "report_external_check_not_approved",
        ),
        (
            {"independent_check": "required_by_rule", "checker_party": "contact:2", "cycle_state": "approved"},
            None,
        ),
        ({"independent_check": "required_by_rule", "checker_party": "contact:2"}, None),
    ],
)
def test_report_acceptance(kw, expected) -> None:
    base = {"author_party": "contact:1", "external": kw.pop("external", "cycle_state" in kw), "cycle_state": None}
    base.update(kw)
    assert r.report_acceptance_error(**base) == expected


def test_rationale_must_be_words() -> None:
    assert r.rationale_error("  ") == "rationale_required"
    assert r.rationale_error("Ground report from 2024 still valid") is None


def test_party_key_prefers_the_organisation() -> None:
    assert r.party_key(contact_id="c1", originator_code="abc", party_kind="specialist") == "contact:c1"
    assert r.party_key(contact_id=None, originator_code="abc", party_kind="x") == "originator:ABC"
    assert r.party_key(contact_id=None, originator_code=None, party_kind=None) is None


# ── permits (rule 19) and readiness (rule 16) ──


def test_permit_missing_lists_required_items_without_a_good_revision() -> None:
    ok = r.PermitItemView(uuid.uuid4(), "drawing", True, True, True)
    wip = r.PermitItemView(uuid.uuid4(), "drawing", True, True, False)
    absent = r.PermitItemView(uuid.uuid4(), "report", True, False, False)
    optional = r.PermitItemView(uuid.uuid4(), "form", False, False, False)
    assert r.permit_missing([ok, wip, absent, optional]) == [wip.id, absent.id]


def test_superseded_items_after_submission() -> None:
    c1, c2, c3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    r1, r2, r3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert r.superseded_items({c1: r1, c2: r2, c3: None}, {c1: r1, c2: r3, c3: r3}) == [c2]


def test_phase_blockers_for_the_whole_project() -> None:
    """No phase asked: every open required row counts, whatever word it carries as its phase."""
    b = r.phase_blockers(
        None,
        deliverables=[
            ("DL-1", None, "planned", True),
            ("DL-2", "own word", "accepted", True),
            ("DL-3", "x", "open", False),
        ],
        reports=[("RPT-1", "own word", "submitted", True), ("RPT-2", None, "accepted", True)],
        open_major_comments=[None, "own word"],
    )
    assert (b.deliverables, b.reports, b.major_comments, b.met) == (["DL-1"], ["RPT-1"], 2, False)
    assert r.phase_blockers(None, deliverables=[], reports=[], open_major_comments=[]).met


def test_phase_blockers() -> None:
    b = r.phase_blockers(
        "lph3",
        deliverables=[("D1", "lph3", "in_progress", True), ("D2", "lph3", "accepted", True), ("D3", "lph4", "x", True)],
        reports=[("fire", "lph3", "submitted", True), ("geo", "lph3", "not_required", True), ("x", "lph3", "x", False)],
        open_major_comments=["lph3", "lph2"],
    )
    assert (b.deliverables, b.reports, b.major_comments, b.met) == (["D1"], ["fire"], 1, False)
    assert r.phase_blockers("lph9", deliverables=[], reports=[], open_major_comments=[]).met


def test_a_required_report_without_a_phase_blocks_every_phase() -> None:
    """Finding 12: a report cannot be parked out of a gate's sight by leaving its phase empty."""
    reports = [("fire", None, "submitted", True), ("geo", "", "accepted", True), ("opt", None, "required", False)]
    for phase in ("lph2", "lph5"):
        assert r.phase_blockers(phase, deliverables=[], reports=reports, open_major_comments=[]).reports == ["fire"]


# ── FSMs, table driven ──

LEGAL = [
    (dfsm.ROLE_FSM, "planned", "appointed"),
    (dfsm.ROLE_FSM, "active", "released"),
    (dfsm.APPROVAL_POINT_FSM, "open", "in_review"),
    (dfsm.APPROVAL_POINT_FSM, "in_review", "approved"),
    (dfsm.APPROVAL_POINT_FSM, "rejected", "open"),
    (dfsm.RELEASE_FSM, "draft", "ready"),
    (dfsm.RELEASE_FSM, "ready", "issued"),
    (dfsm.REVIEW_FSM, "open", "comments_closed"),
    (dfsm.REVIEW_FSM, "comments_closed", "concluded"),
    (dfsm.COMMENT_FSM, "open", "answered"),
    (dfsm.COMMENT_FSM, "answered", "closed"),
    (dfsm.REPORT_FSM, "required", "not_required"),
    (dfsm.REPORT_FSM, "under_check", "accepted"),
    (dfsm.REPORT_FSM, "remarks", "in_progress"),
    (dfsm.PERMIT_FSM, "ready", "submitted"),
    (dfsm.PERMIT_FSM, "under_review", "partially_approved"),
]
ILLEGAL = [
    (dfsm.ROLE_FSM, "released", "active"),
    (dfsm.APPROVAL_POINT_FSM, "open", "approved"),
    (dfsm.APPROVAL_POINT_FSM, "approved", "open"),
    (dfsm.RELEASE_FSM, "draft", "issued"),
    (dfsm.RELEASE_FSM, "issued", "draft"),
    (dfsm.REVIEW_FSM, "open", "concluded"),
    (dfsm.COMMENT_FSM, "open", "closed"),
    (dfsm.REPORT_FSM, "required", "accepted"),
    (dfsm.REPORT_FSM, "accepted", "in_progress"),
    (dfsm.PERMIT_FSM, "assembling", "submitted"),
    (dfsm.PERMIT_FSM, "approved", "withdrawn"),
]


@pytest.mark.parametrize(("machine", "a", "b"), LEGAL, ids=lambda x: getattr(x, "name", x))
def test_legal_transitions(machine, a, b) -> None:
    assert machine.has_transition(a, b)


@pytest.mark.parametrize(("machine", "a", "b"), ILLEGAL, ids=lambda x: getattr(x, "name", x))
def test_illegal_transitions(machine, a, b) -> None:
    assert not machine.has_transition(a, b)


def test_fsm_names_are_prefixed_and_registered() -> None:
    from app.core.fsm import get_fsm

    for m in dfsm.ALL_FSMS:
        assert m.name.startswith("design_")
        assert get_fsm(m.name) is m


def test_cycle_states_map_onto_legal_permit_states() -> None:
    for target in dfsm.CYCLE_TO_PERMIT.values():
        assert target in dfsm.PERMIT_STATES
    assert dfsm.permit_path(dfsm.PERMIT_FSM, "submitted", "approved") == ["under_review", "approved"]
    assert dfsm.permit_path(dfsm.PERMIT_FSM, "approved", "remarks") == []
    for target in dfsm.CYCLE_TO_REPORT.values():
        assert target in dfsm.REPORT_STATES
