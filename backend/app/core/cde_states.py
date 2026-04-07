"""ISO 19650 Common Data Environment state machine.

Four states: WIP -> SHARED -> PUBLISHED -> ARCHIVED.
Each transition has gate conditions (who can promote, what's required).

This module is stateless — it encodes only the *rules*.  Persistence of a
document's current state is the caller's responsibility.

Usage:
    from app.core.cde_states import CDEStateMachine, CDEState

    sm = CDEStateMachine()
    sm.can_transition("wip", "shared")        # True
    sm.can_transition("wip", "published")     # False (must go through shared)
    sm.validate_transition("shared", "published", user_role="lead_ap")
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CDEState(str, Enum):
    """ISO 19650 CDE document states."""

    WIP = "wip"
    SHARED = "shared"
    PUBLISHED = "published"
    ARCHIVED = "archived"


# ── Role hierarchy (higher index = more authority) ────────────────────────

_ROLE_RANK: dict[str, int] = {
    "viewer": 0,
    "editor": 1,
    "task_team_manager": 2,
    "lead_ap": 3,
    "admin": 4,
}

# ── Gate definitions ──────────────────────────────────────────────────────

# Each allowed transition maps to its gate metadata.
_GATES: dict[tuple[CDEState, CDEState], dict[str, Any]] = {
    # Gate A — WIP → SHARED
    (CDEState.WIP, CDEState.SHARED): {
        "gate": "A",
        "description": "Suitability check — task team manager promotes to shared area",
        "min_role": "task_team_manager",
    },
    # Gate B — SHARED → PUBLISHED
    (CDEState.SHARED, CDEState.PUBLISHED): {
        "gate": "B",
        "description": "Approval gate — lead appointed party or admin authorises publication",
        "min_role": "lead_ap",
    },
    # Gate C — PUBLISHED → ARCHIVED
    (CDEState.PUBLISHED, CDEState.ARCHIVED): {
        "gate": "C",
        "description": "Archive — document is superseded or project closes",
        "min_role": "admin",
    },
}


def _role_rank(role: str) -> int:
    """Return numeric rank for a role string (0 = least authority)."""
    return _ROLE_RANK.get(role, -1)


class CDEStateMachine:
    """ISO 19650 CDE state machine.

    Encodes the four-state lifecycle and gate conditions.  No backwards
    transitions are permitted.  ARCHIVED is terminal.
    """

    # ── Transition queries ────────────────────────────────────────────────

    def can_transition(self, from_state: str, to_state: str) -> bool:
        """Return ``True`` if the transition is structurally valid.

        This only checks whether the transition *exists* — it does **not**
        evaluate role-based authorisation.
        """
        key = self._gate_key(from_state, to_state)
        return key in _GATES

    def validate_transition(
        self,
        from_state: str,
        to_state: str,
        user_role: str = "editor",
    ) -> tuple[bool, str]:
        """Validate a state transition including role authorisation.

        Args:
            from_state: Current document state (case-insensitive).
            to_state: Desired target state.
            user_role: Role of the user requesting the transition.

        Returns:
            ``(True, "ok")`` when the transition is allowed, or
            ``(False, "<reason>")`` when it is not.
        """
        key = self._gate_key(from_state, to_state)

        if key is None:
            return False, f"Invalid state value: {from_state!r} or {to_state!r}"

        gate = _GATES.get(key)
        if gate is None:
            return False, (
                f"Transition {from_state!r} -> {to_state!r} is not allowed. "
                f"Allowed from {from_state!r}: "
                f"{self.get_allowed_transitions(from_state)}"
            )

        min_role = gate["min_role"]
        if _role_rank(user_role) < _role_rank(min_role):
            return False, (
                f"Insufficient role: {user_role!r} cannot pass gate {gate['gate']}. "
                f"Minimum required: {min_role!r}"
            )

        return True, "ok"

    def get_allowed_transitions(self, from_state: str) -> list[str]:
        """Return state values reachable in one step from *from_state*."""
        try:
            src = CDEState(from_state.lower())
        except ValueError:
            return []
        return [to.value for (frm, to) in _GATES if frm is src]

    def get_gate_requirements(self, from_state: str, to_state: str) -> dict[str, Any]:
        """Return gate metadata for a transition.

        Returns an empty dict if the transition does not exist.
        """
        key = self._gate_key(from_state, to_state)
        if key is None:
            return {}
        return dict(_GATES.get(key, {}))

    # ── Internals ─────────────────────────────────────────────────────────

    @staticmethod
    def _gate_key(
        from_state: str,
        to_state: str,
    ) -> tuple[CDEState, CDEState] | None:
        """Normalise string state values into a gate lookup key."""
        try:
            src = CDEState(from_state.lower())
            dst = CDEState(to_state.lower())
        except ValueError:
            return None
        return (src, dst)

    def __repr__(self) -> str:
        return "CDEStateMachine(WIP → SHARED → PUBLISHED → ARCHIVED)"
