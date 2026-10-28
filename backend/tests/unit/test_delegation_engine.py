# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the approval delegation / out-of-office engine.

No DB, no FastAPI, no event bus - imports only the pure
``app.modules.approval_routes.delegation_engine`` so it runs on Python 3.11.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.approval_routes.delegation_engine import (
    DelegationView,
    eligible_deciders,
    is_active_at,
    resolve_delegate,
)

NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)

A = uuid.uuid4()
B = uuid.uuid4()
C = uuid.uuid4()
D = uuid.uuid4()
PROJ_1 = uuid.uuid4()
PROJ_2 = uuid.uuid4()


# ── is_active_at ─────────────────────────────────────────────────────────


def test_open_ended_delegation_is_active():
    d = DelegationView(delegator_id=A, delegate_id=B)
    assert is_active_at(d, NOW) is True


def test_inactive_flag_is_never_active():
    d = DelegationView(delegator_id=A, delegate_id=B, is_active=False)
    assert is_active_at(d, NOW) is False


def test_window_before_start_is_inactive():
    d = DelegationView(delegator_id=A, delegate_id=B, starts_at=NOW + timedelta(days=1))
    assert is_active_at(d, NOW) is False


def test_window_after_end_is_inactive():
    d = DelegationView(delegator_id=A, delegate_id=B, ends_at=NOW - timedelta(hours=1))
    assert is_active_at(d, NOW) is False


def test_within_window_is_active():
    d = DelegationView(
        delegator_id=A,
        delegate_id=B,
        starts_at=NOW - timedelta(days=1),
        ends_at=NOW + timedelta(days=1),
    )
    assert is_active_at(d, NOW) is True


def test_naive_window_is_normalised_to_utc():
    # A naive starts_at must be treated as UTC, not raise on compare.
    d = DelegationView(delegator_id=A, delegate_id=B, starts_at=datetime(2026, 6, 24, 11, 0, 0))
    assert is_active_at(d, NOW) is True


def test_project_scoped_matches_only_its_project():
    d = DelegationView(delegator_id=A, delegate_id=B, project_id=PROJ_1)
    assert is_active_at(d, NOW, project_id=PROJ_1) is True
    assert is_active_at(d, NOW, project_id=PROJ_2) is False


def test_project_scoped_not_applied_without_a_project_context():
    d = DelegationView(delegator_id=A, delegate_id=B, project_id=PROJ_1)
    assert is_active_at(d, NOW, project_id=None) is False


def test_blanket_delegation_applies_to_any_project():
    d = DelegationView(delegator_id=A, delegate_id=B, project_id=None)
    assert is_active_at(d, NOW, project_id=PROJ_1) is True
    assert is_active_at(d, NOW, project_id=None) is True


# ── resolve_delegate ─────────────────────────────────────────────────────


def test_no_delegation_resolves_to_self():
    assert resolve_delegate(A, [], now=NOW) == A


def test_single_hop():
    d = DelegationView(delegator_id=A, delegate_id=B)
    assert resolve_delegate(A, [d], now=NOW) == B


def test_two_hop_chain_resolves_to_terminal():
    chain = [
        DelegationView(delegator_id=A, delegate_id=B),
        DelegationView(delegator_id=B, delegate_id=C),
    ]
    assert resolve_delegate(A, chain, now=NOW) == C


def test_inactive_link_stops_the_chain():
    chain = [
        DelegationView(delegator_id=A, delegate_id=B),
        DelegationView(delegator_id=B, delegate_id=C, is_active=False),
    ]
    assert resolve_delegate(A, chain, now=NOW) == B


def test_cycle_is_broken_safely():
    chain = [
        DelegationView(delegator_id=A, delegate_id=B),
        DelegationView(delegator_id=B, delegate_id=A),
    ]
    # A -> B -> (A already visited) stops at B.
    assert resolve_delegate(A, chain, now=NOW) == B


def test_hop_cap_stops_long_chain():
    chain = [
        DelegationView(delegator_id=A, delegate_id=B),
        DelegationView(delegator_id=B, delegate_id=C),
        DelegationView(delegator_id=C, delegate_id=D),
    ]
    # With max_hops=1 we only follow A -> B.
    assert resolve_delegate(A, chain, now=NOW, max_hops=1) == B


def test_project_scoped_wins_over_blanket_for_same_delegator():
    delegations = [
        DelegationView(delegator_id=A, delegate_id=B, project_id=None),
        DelegationView(delegator_id=A, delegate_id=C, project_id=PROJ_1),
    ]
    # In PROJ_1 the specific delegation to C wins ...
    assert resolve_delegate(A, delegations, now=NOW, project_id=PROJ_1) == C
    # ... in PROJ_2 only the blanket one applies.
    assert resolve_delegate(A, delegations, now=NOW, project_id=PROJ_2) == B


def test_expired_delegation_resolves_to_self():
    d = DelegationView(delegator_id=A, delegate_id=B, ends_at=NOW - timedelta(hours=1))
    assert resolve_delegate(A, [d], now=NOW) == A


# ── eligible_deciders ────────────────────────────────────────────────────


def test_eligible_without_delegation_is_just_self():
    assert eligible_deciders(A, [], now=NOW) == {A}


def test_eligible_includes_self_and_terminal():
    chain = [
        DelegationView(delegator_id=A, delegate_id=B),
        DelegationView(delegator_id=B, delegate_id=C),
    ]
    # Intermediate B is "also out" and not eligible; A (if present) and C are.
    assert eligible_deciders(A, chain, now=NOW) == {A, C}


def test_eligible_single_hop():
    d = DelegationView(delegator_id=A, delegate_id=B)
    assert eligible_deciders(A, [d], now=NOW) == {A, B}
