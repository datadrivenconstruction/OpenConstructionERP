# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The two lifecycles of project governance, every move allowed and refused.

Both machines are tables, so the tests are tables too. Every pair of states is
asked once: the allowed set must answer yes and every other pair must answer no.
A transition that was quietly added or dropped turns exactly one row red.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from app.core.fsm import InvalidTransition
from app.modules.project_governance.fsm import (
    DOCUMENT_FSM,
    DOCUMENT_STATES,
    GATE_FSM,
    GATE_STATES,
)

GATE_ALLOWED: set[tuple[str, str]] = {
    ("not_started", "in_preparation"),
    ("in_preparation", "in_review"),
    # The route sent it back, the decider recycled it, or the submitter withdrew.
    ("in_review", "in_preparation"),
    ("in_review", "on_hold"),
    ("in_review", "decided"),
    # Resuming a hold opens a new attempt in preparation.
    ("on_hold", "in_preparation"),
    # Reopening keeps the decision and starts attempt n+1.
    ("decided", "in_preparation"),
}

DOCUMENT_ALLOWED: set[tuple[str, str]] = {
    ("draft", "in_review"),
    ("in_review", "draft"),
    ("in_review", "approved_at_gate"),
    ("approved_at_gate", "binding"),
    # The document type left the phase model on a model change, or came back with a later one.
    ("binding", "superseded"),
    ("superseded", "binding"),
}


@pytest.mark.parametrize(("src", "dst"), sorted(itertools.product(GATE_STATES, GATE_STATES)))
def test_gate_transition_table(src: str, dst: str) -> None:
    assert GATE_FSM.has_transition(src, dst) is ((src, dst) in GATE_ALLOWED)


@pytest.mark.parametrize(("src", "dst"), sorted(itertools.product(DOCUMENT_STATES, DOCUMENT_STATES)))
def test_document_transition_table(src: str, dst: str) -> None:
    assert DOCUMENT_FSM.has_transition(src, dst) is ((src, dst) in DOCUMENT_ALLOWED)


def test_state_sets_are_exactly_the_documented_ones() -> None:
    assert set(GATE_STATES) == {"not_started", "in_preparation", "in_review", "on_hold", "decided"}
    assert set(DOCUMENT_STATES) == {"draft", "in_review", "approved_at_gate", "binding", "superseded"}
    assert GATE_FSM.all_states == set(GATE_STATES)
    assert DOCUMENT_FSM.all_states == set(DOCUMENT_STATES)


def test_initial_states() -> None:
    assert GATE_FSM.initial == "not_started"
    assert DOCUMENT_FSM.initial == "draft"


def test_no_document_state_is_a_dead_end() -> None:
    """Superseded is not terminal: a model change that brings the type back reinstates the document."""
    assert not [s for s in DOCUMENT_STATES if DOCUMENT_FSM.is_terminal(s)]


def test_a_superseded_document_only_ever_goes_back_to_binding() -> None:
    assert {dst for dst in DOCUMENT_STATES if DOCUMENT_FSM.has_transition("superseded", dst)} == {"binding"}


def test_no_gate_state_is_a_dead_end() -> None:
    """A decided gate can still be reopened, so nothing in the gate machine is terminal."""
    assert not [s for s in GATE_STATES if GATE_FSM.is_terminal(s)]


@pytest.mark.asyncio
async def test_apply_refuses_a_forbidden_move_and_leaves_the_status_alone() -> None:
    gate = SimpleNamespace(id="g", status="not_started")
    with pytest.raises(InvalidTransition):
        await GATE_FSM.apply(None, gate, "decided")
    assert gate.status == "not_started"


@pytest.mark.asyncio
async def test_apply_moves_an_allowed_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.audit_log as audit_log

    async def _no_audit(*_a, **_k):
        return None

    monkeypatch.setattr(audit_log, "log_activity", _no_audit)
    doc = SimpleNamespace(id="d", status="draft")
    await DOCUMENT_FSM.apply(None, doc, "in_review")
    assert doc.status == "in_review"
