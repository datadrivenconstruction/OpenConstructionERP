# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Quality concept state machines, table driven.

Every machine is checked against the full table below in both directions: each
listed transition is allowed, and every other ``(state, action)`` pair is
refused. A transition added or removed in ``fsm.py`` without the spec changing
fails here.
"""

from __future__ import annotations

import pytest

from app.modules.quality_concept import fsm

EXPECTED: dict[str, set[tuple[str, str, str]]] = {
    "concept": {
        ("draft", "submit", "in_review"),
        ("in_review", "return", "draft"),
        ("in_review", "approve", "approved"),
        ("approved", "bind", "binding"),
        ("approved", "revise", "revising"),
        ("binding", "reopen", "revising"),
        ("revising", "submit", "in_review"),
    },
    "stage": {
        ("blocked", "mark_ready", "ready"),
        ("blocked", "not_applicable", "not_applicable"),
        ("ready", "mark_blocked", "blocked"),
        ("ready", "open_test", "in_test"),
        ("ready", "not_applicable", "not_applicable"),
        ("in_test", "pass", "passed"),
        ("in_test", "fail", "failed"),
        ("in_test", "not_applicable", "not_applicable"),
        ("failed", "open_test", "in_test"),
        ("passed", "release", "released"),
        ("passed", "open_test", "in_test"),
        ("passed", "fail", "failed"),
        ("released", "open_test", "in_test"),
        ("released", "go_stale", "stale"),
        ("stale", "release", "released"),
        ("stale", "open_test", "in_test"),
        ("not_applicable", "reinstate", "blocked"),
    },
    "preservation": {
        ("planned", "invite", "invited"),
        ("planned", "record_survey", "surveyed"),
        ("planned", "refuse_access", "access_refused"),
        ("invited", "record_survey", "surveyed"),
        ("invited", "refuse_access", "access_refused"),
        ("surveyed", "issue_report", "report_issued"),
        ("report_issued", "close", "closed"),
        ("access_refused", "close", "closed"),
    },
}


def _all_actions(machine: str) -> set[str]:
    return {a for row in fsm.MACHINES[machine].values() for a in row}


@pytest.mark.parametrize("machine", sorted(EXPECTED))
def test_table_is_exactly_the_spec(machine: str) -> None:
    table = fsm.MACHINES[machine]
    actual = {(s, a, t) for s, row in table.items() for a, t in row.items()}
    assert actual == EXPECTED[machine]


@pytest.mark.parametrize("machine", sorted(fsm.MACHINES))
def test_every_unlisted_pair_is_refused(machine: str) -> None:
    table = fsm.MACHINES[machine]
    for state in table:
        for action in _all_actions(machine):
            if action in table[state]:
                continue
            with pytest.raises(fsm.TransitionError) as exc:
                fsm.next_state(machine, state, action, mirror=True, rationale="x")
            assert exc.value.code == "invalid_transition"


@pytest.mark.parametrize(
    ("machine", "state", "action"),
    [
        ("concept", "in_review", "approve"),
        ("concept", "approved", "bind"),
        ("stage", "passed", "release"),
        ("stage", "released", "go_stale"),
        ("acceptance", "requested", "accept"),
        ("acceptance", "inspection_scheduled", "accept_with_reservations"),
    ],
)
def test_states_owned_elsewhere_refuse_a_user_request(machine, state, action) -> None:
    with pytest.raises(fsm.TransitionError) as exc:
        fsm.next_state(machine, state, action, rationale="x")
    assert exc.value.code == "transition_owned_elsewhere"
    assert fsm.next_state(machine, state, action, mirror=True, rationale="x")


def test_no_direct_edit_after_binding() -> None:
    # No user action leaves a binding concept; only governance (a change request) reopens it.
    assert fsm.allowed_actions("concept", "binding") == []
    assert fsm.allowed_actions("concept", "binding", mirror=True) == ["reopen"]


@pytest.mark.parametrize(
    ("machine", "state", "action"),
    [
        ("certification", "planned", "abandon"),
        ("proof", "none", "waive"),
        ("stage", "ready", "not_applicable"),
        ("acceptance", "requested", "refuse"),
        ("preservation", "invited", "refuse_access"),
    ],
)
def test_rationale_actions_need_text(machine, state, action) -> None:
    with pytest.raises(fsm.TransitionError) as exc:
        fsm.next_state(machine, state, action, rationale="   ")
    assert exc.value.code == "rationale_required"
    assert fsm.next_state(machine, state, action, rationale="because")


def test_certification_path_and_terminals() -> None:
    s = "planned"
    for action in ("register", "assess_design", "assess_post_construction", "certify"):
        s = fsm.next_state("certification", s, action)
    assert s == "certified"
    assert fsm.next_state("certification", "registered", "assess_post_construction") == "post_construction_assessed"
    for terminal in ("certified", "level_missed", "abandoned"):
        assert fsm.allowed_actions("certification", terminal) == []


def test_user_actions_hide_mirror_ones() -> None:
    assert "release" not in fsm.allowed_actions("stage", "passed")
    assert "release" in fsm.allowed_actions("stage", "passed", mirror=True)
