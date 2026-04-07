"""Tests for ISO 19650 CDE state machine."""

import pytest

from app.core.cde_states import CDEState, CDEStateMachine


@pytest.fixture
def sm() -> CDEStateMachine:
    return CDEStateMachine()


# ── CDEState enum ─────────────────────────────────────────────────────────


class TestCDEState:
    def test_values(self) -> None:
        assert CDEState.WIP.value == "wip"
        assert CDEState.SHARED.value == "shared"
        assert CDEState.PUBLISHED.value == "published"
        assert CDEState.ARCHIVED.value == "archived"

    def test_string_comparison(self) -> None:
        assert CDEState.WIP == "wip"
        assert CDEState.ARCHIVED == "archived"

    def test_members_count(self) -> None:
        assert len(CDEState) == 4


# ── can_transition ────────────────────────────────────────────────────────


class TestCanTransition:
    def test_wip_to_shared(self, sm: CDEStateMachine) -> None:
        assert sm.can_transition("wip", "shared") is True

    def test_shared_to_published(self, sm: CDEStateMachine) -> None:
        assert sm.can_transition("shared", "published") is True

    def test_published_to_archived(self, sm: CDEStateMachine) -> None:
        assert sm.can_transition("published", "archived") is True

    def test_skip_step_not_allowed(self, sm: CDEStateMachine) -> None:
        assert sm.can_transition("wip", "published") is False
        assert sm.can_transition("wip", "archived") is False
        assert sm.can_transition("shared", "archived") is False

    def test_backward_not_allowed(self, sm: CDEStateMachine) -> None:
        assert sm.can_transition("shared", "wip") is False
        assert sm.can_transition("published", "shared") is False
        assert sm.can_transition("archived", "published") is False

    def test_same_state_not_allowed(self, sm: CDEStateMachine) -> None:
        assert sm.can_transition("wip", "wip") is False
        assert sm.can_transition("archived", "archived") is False

    def test_archived_is_terminal(self, sm: CDEStateMachine) -> None:
        for target in ["wip", "shared", "published", "archived"]:
            assert sm.can_transition("archived", target) is False

    def test_case_insensitive(self, sm: CDEStateMachine) -> None:
        assert sm.can_transition("WIP", "SHARED") is True
        assert sm.can_transition("Shared", "Published") is True

    def test_invalid_state(self, sm: CDEStateMachine) -> None:
        assert sm.can_transition("invalid", "wip") is False
        assert sm.can_transition("wip", "invalid") is False


# ── validate_transition ───────────────────────────────────────────────────


class TestValidateTransition:
    def test_valid_with_correct_role(self, sm: CDEStateMachine) -> None:
        ok, reason = sm.validate_transition("wip", "shared", user_role="task_team_manager")
        assert ok is True
        assert reason == "ok"

    def test_valid_with_higher_role(self, sm: CDEStateMachine) -> None:
        ok, reason = sm.validate_transition("wip", "shared", user_role="admin")
        assert ok is True

    def test_insufficient_role_gate_a(self, sm: CDEStateMachine) -> None:
        ok, reason = sm.validate_transition("wip", "shared", user_role="editor")
        assert ok is False
        assert "Insufficient role" in reason
        assert "task_team_manager" in reason

    def test_insufficient_role_gate_b(self, sm: CDEStateMachine) -> None:
        ok, reason = sm.validate_transition("shared", "published", user_role="task_team_manager")
        assert ok is False
        assert "lead_ap" in reason

    def test_gate_b_with_lead_ap(self, sm: CDEStateMachine) -> None:
        ok, _ = sm.validate_transition("shared", "published", user_role="lead_ap")
        assert ok is True

    def test_gate_c_admin_only(self, sm: CDEStateMachine) -> None:
        ok, _ = sm.validate_transition("published", "archived", user_role="admin")
        assert ok is True

        ok, reason = sm.validate_transition("published", "archived", user_role="lead_ap")
        assert ok is False
        assert "admin" in reason

    def test_invalid_transition_rejected(self, sm: CDEStateMachine) -> None:
        ok, reason = sm.validate_transition("wip", "published")
        assert ok is False
        assert "not allowed" in reason

    def test_invalid_state_value(self, sm: CDEStateMachine) -> None:
        ok, reason = sm.validate_transition("bogus", "shared")
        assert ok is False
        assert "Invalid state" in reason

    def test_default_role_is_editor(self, sm: CDEStateMachine) -> None:
        # editor has rank 1, gate A requires task_team_manager (rank 2)
        ok, _ = sm.validate_transition("wip", "shared")
        assert ok is False


# ── get_allowed_transitions ───────────────────────────────────────────────


class TestGetAllowedTransitions:
    def test_from_wip(self, sm: CDEStateMachine) -> None:
        assert sm.get_allowed_transitions("wip") == ["shared"]

    def test_from_shared(self, sm: CDEStateMachine) -> None:
        assert sm.get_allowed_transitions("shared") == ["published"]

    def test_from_published(self, sm: CDEStateMachine) -> None:
        assert sm.get_allowed_transitions("published") == ["archived"]

    def test_from_archived(self, sm: CDEStateMachine) -> None:
        assert sm.get_allowed_transitions("archived") == []

    def test_invalid_state(self, sm: CDEStateMachine) -> None:
        assert sm.get_allowed_transitions("invalid") == []


# ── get_gate_requirements ─────────────────────────────────────────────────


class TestGetGateRequirements:
    def test_gate_a(self, sm: CDEStateMachine) -> None:
        gate = sm.get_gate_requirements("wip", "shared")
        assert gate["gate"] == "A"
        assert gate["min_role"] == "task_team_manager"

    def test_gate_b(self, sm: CDEStateMachine) -> None:
        gate = sm.get_gate_requirements("shared", "published")
        assert gate["gate"] == "B"
        assert gate["min_role"] == "lead_ap"

    def test_gate_c(self, sm: CDEStateMachine) -> None:
        gate = sm.get_gate_requirements("published", "archived")
        assert gate["gate"] == "C"
        assert gate["min_role"] == "admin"

    def test_no_gate(self, sm: CDEStateMachine) -> None:
        assert sm.get_gate_requirements("wip", "published") == {}

    def test_invalid_state(self, sm: CDEStateMachine) -> None:
        assert sm.get_gate_requirements("bad", "shared") == {}


# ── repr ──────────────────────────────────────────────────────────────────


class TestRepr:
    def test_repr(self, sm: CDEStateMachine) -> None:
        assert "WIP" in repr(sm)
        assert "ARCHIVED" in repr(sm)
