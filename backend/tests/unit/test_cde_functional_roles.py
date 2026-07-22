"""Tests for the ISO 19650 CDE functional-roles catalog.

The catalog (Author / Reviewer / Approver / Viewer) must stay consistent with the
state machine it references: every role's ``cde_role`` has to be a real gate role,
every ``gate`` has to be a real gate, and the responsibility matrix has to cover
each state for each role. The endpoint response is built by validating each role
dict against the Pydantic schema, so a field drift would fail here.
"""

from app.core.cde_states import _GATES, _ROLE_RANK, CDEState
from app.modules.cde.roles import (
    CDE_STATE_ORDER,
    FUNCTIONAL_ROLES,
    RESPONSIBILITY_MATRIX,
    role_by_key,
    role_keys,
)
from app.modules.cde.schemas import FunctionalRoleEntry, FunctionalRolesResponse

_VALID_STATES = {s.value for s in CDEState}
_VALID_GATES = {gate["gate"] for gate in _GATES.values()}
_KNOWN_CDE_PERMISSIONS = {
    "cde.create",
    "cde.read",
    "cde.update",
    "cde.delete",
    "cde.transition",
}


class TestCatalogShape:
    def test_four_roles_in_workflow_order(self) -> None:
        assert role_keys() == ["author", "reviewer", "approver", "viewer"]

    def test_role_by_key_roundtrip(self) -> None:
        for key in role_keys():
            assert role_by_key(key)["key"] == key  # type: ignore[index]

    def test_role_by_key_unknown_is_none(self) -> None:
        assert role_by_key("nope") is None


class TestConsistencyWithStateMachine:
    def test_cde_role_is_a_real_gate_role(self) -> None:
        for role in FUNCTIONAL_ROLES:
            assert role["cde_role"] in _ROLE_RANK

    def test_gate_is_real_or_absent(self) -> None:
        for role in FUNCTIONAL_ROLES:
            if role["gate"] is not None:
                assert role["gate"] in _VALID_GATES

    def test_reviewer_owns_gate_a_approver_gate_b(self) -> None:
        assert role_by_key("reviewer")["gate"] == "A"  # type: ignore[index]
        assert role_by_key("approver")["gate"] == "B"  # type: ignore[index]

    def test_acts_on_states_are_valid(self) -> None:
        for role in FUNCTIONAL_ROLES:
            assert set(role["acts_on"]) <= _VALID_STATES

    def test_permissions_are_known(self) -> None:
        for role in FUNCTIONAL_ROLES:
            assert set(role["permissions"]) <= _KNOWN_CDE_PERMISSIONS


class TestResponsibilityMatrix:
    def test_covers_every_state(self) -> None:
        assert set(RESPONSIBILITY_MATRIX) == _VALID_STATES
        assert set(CDE_STATE_ORDER) == _VALID_STATES

    def test_every_state_covers_every_role(self) -> None:
        keys = set(role_keys())
        for state, cols in RESPONSIBILITY_MATRIX.items():
            assert set(cols) == keys, state


class TestSchemaConstruction:
    def test_role_entries_validate(self) -> None:
        entries = [FunctionalRoleEntry(**role) for role in FUNCTIONAL_ROLES]
        assert len(entries) == 4
        assert entries[0].name == "Author"

    def test_full_response_builds(self) -> None:
        resp = FunctionalRolesResponse(
            roles=[FunctionalRoleEntry(**r) for r in FUNCTIONAL_ROLES],
            states=list(CDE_STATE_ORDER),
            matrix={s: dict(c) for s, c in RESPONSIBILITY_MATRIX.items()},
        )
        assert [r.key for r in resp.roles] == role_keys()
        assert resp.matrix["shared"]["approver"] == "Authorise"
