# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the approval-SLA escalation-depth engine.

Pure standard-library tests - no app.* imports, no DB, no FastAPI. Runs
on Python 3.11.
"""

from __future__ import annotations

import pytest

from app.modules.approval_routes.escalation import (
    REASON_CHAIN_EXHAUSTED,
    REASON_ESCALATE,
    REASON_WITHIN_WINDOW,
    SEVERITY_BREACHED,
    SEVERITY_CRITICAL,
    SEVERITY_LATE,
    SEVERITY_ON_TIME,
    EscalationDecision,
    EscalationPolicy,
    EscalationState,
    classify_severity,
    decide_escalation,
    hours_overdue,
)


def _policy(
    *,
    target_kind: str = "cost_approval",
    sla_hours: int = 24,
    escalate_after_hours: int = 48,
    chain: tuple[str, ...] = ("lead", "manager", "director"),
) -> EscalationPolicy:
    return EscalationPolicy(
        target_kind=target_kind,
        sla_hours=sla_hours,
        escalate_after_hours=escalate_after_hours,
        chain=chain,
    )


def _state(
    *,
    hours_since_assigned: float = 0.0,
    current_holder: str = "author",
    already_escalated_to: tuple[str, ...] = (),
) -> EscalationState:
    return EscalationState(
        hours_since_assigned=hours_since_assigned,
        current_holder=current_holder,
        already_escalated_to=already_escalated_to,
    )


# ---------------------------------------------------------------------------
# decide_escalation - the grace window
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hours, escalate_after",
    [
        (0.0, 48),
        (10.0, 48),
        (47.9, 48),
        (47.999999, 48),
    ],
)
def test_below_threshold_is_within_window(hours: float, escalate_after: int) -> None:
    decision = decide_escalation(
        _policy(escalate_after_hours=escalate_after),
        _state(hours_since_assigned=hours),
    )
    assert decision == EscalationDecision(
        should_escalate=False,
        next_target=None,
        level=0,
        reason=REASON_WITHIN_WINDOW,
    )


def test_exactly_at_threshold_escalates() -> None:
    # Boundary is inclusive of the threshold: at exactly escalate_after_hours
    # we are past the window and the chain is walked.
    decision = decide_escalation(
        _policy(escalate_after_hours=48),
        _state(hours_since_assigned=48.0),
    )
    assert decision.should_escalate is True
    assert decision.reason == REASON_ESCALATE
    assert decision.next_target == "lead"
    assert decision.level == 1


# ---------------------------------------------------------------------------
# decide_escalation - walking the chain
# ---------------------------------------------------------------------------


def test_first_escalation_picks_chain_head() -> None:
    decision = decide_escalation(
        _policy(chain=("lead", "manager", "director")),
        _state(hours_since_assigned=50.0, already_escalated_to=()),
    )
    assert decision.should_escalate is True
    assert decision.next_target == "lead"
    assert decision.level == 1
    assert decision.reason == REASON_ESCALATE


def test_second_escalation_picks_next_unused() -> None:
    decision = decide_escalation(
        _policy(chain=("lead", "manager", "director")),
        _state(hours_since_assigned=72.0, already_escalated_to=("lead",)),
    )
    assert decision.should_escalate is True
    assert decision.next_target == "manager"
    assert decision.level == 2
    assert decision.reason == REASON_ESCALATE


def test_third_escalation_picks_last_unused() -> None:
    decision = decide_escalation(
        _policy(chain=("lead", "manager", "director")),
        _state(hours_since_assigned=96.0, already_escalated_to=("lead", "manager")),
    )
    assert decision.should_escalate is True
    assert decision.next_target == "director"
    assert decision.level == 3
    assert decision.reason == REASON_ESCALATE


def test_used_entries_out_of_order_still_skipped() -> None:
    # already_escalated_to need not match chain order; any used entry is skipped.
    decision = decide_escalation(
        _policy(chain=("lead", "manager", "director")),
        _state(hours_since_assigned=80.0, already_escalated_to=("manager",)),
    )
    assert decision.should_escalate is True
    assert decision.next_target == "lead"
    # level counts how many escalations have happened, not chain position.
    assert decision.level == 2


# ---------------------------------------------------------------------------
# decide_escalation - skip the current holder
# ---------------------------------------------------------------------------


def test_skips_chain_entry_equal_to_current_holder() -> None:
    decision = decide_escalation(
        _policy(chain=("lead", "manager", "director")),
        _state(hours_since_assigned=50.0, current_holder="lead"),
    )
    # "lead" already holds it, so the next target is "manager".
    assert decision.should_escalate is True
    assert decision.next_target == "manager"
    assert decision.level == 1
    assert decision.reason == REASON_ESCALATE


def test_skips_holder_and_already_used_together() -> None:
    decision = decide_escalation(
        _policy(chain=("lead", "manager", "director")),
        _state(
            hours_since_assigned=90.0,
            current_holder="manager",
            already_escalated_to=("lead",),
        ),
    )
    # "lead" used, "manager" is the holder -> "director".
    assert decision.should_escalate is True
    assert decision.next_target == "director"
    assert decision.level == 2


def test_only_remaining_entry_is_current_holder_exhausts() -> None:
    decision = decide_escalation(
        _policy(chain=("lead", "manager")),
        _state(
            hours_since_assigned=90.0,
            current_holder="manager",
            already_escalated_to=("lead",),
        ),
    )
    # "lead" used and "manager" is the holder -> nobody left.
    assert decision == EscalationDecision(
        should_escalate=False,
        next_target=None,
        level=0,
        reason=REASON_CHAIN_EXHAUSTED,
    )


# ---------------------------------------------------------------------------
# decide_escalation - exhaustion
# ---------------------------------------------------------------------------


def test_chain_exhausted_when_all_used() -> None:
    decision = decide_escalation(
        _policy(chain=("lead", "manager", "director")),
        _state(
            hours_since_assigned=200.0,
            already_escalated_to=("lead", "manager", "director"),
        ),
    )
    assert decision == EscalationDecision(
        should_escalate=False,
        next_target=None,
        level=0,
        reason=REASON_CHAIN_EXHAUSTED,
    )


def test_empty_chain_exhausted() -> None:
    decision = decide_escalation(
        _policy(chain=()),
        _state(hours_since_assigned=100.0),
    )
    assert decision == EscalationDecision(
        should_escalate=False,
        next_target=None,
        level=0,
        reason=REASON_CHAIN_EXHAUSTED,
    )


def test_empty_chain_within_window_is_within_window() -> None:
    # Window check happens before the chain walk, so an empty chain still
    # reports within_window while inside the grace period.
    decision = decide_escalation(
        _policy(chain=()),
        _state(hours_since_assigned=1.0),
    )
    assert decision.reason == REASON_WITHIN_WINDOW
    assert decision.should_escalate is False


# ---------------------------------------------------------------------------
# decide_escalation - level increments with already_escalated_to
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "already, expected_target, expected_level",
    [
        ((), "lead", 1),
        (("lead",), "manager", 2),
        (("lead", "manager"), "director", 3),
    ],
)
def test_level_increments_with_already_escalated_to(
    already: tuple[str, ...], expected_target: str, expected_level: int
) -> None:
    decision = decide_escalation(
        _policy(chain=("lead", "manager", "director")),
        _state(hours_since_assigned=120.0, already_escalated_to=already),
    )
    assert decision.next_target == expected_target
    assert decision.level == expected_level
    assert decision.should_escalate is True


# ---------------------------------------------------------------------------
# hours_overdue
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sla_hours, hours_since, expected",
    [
        (24, 0.0, 0.0),  # nothing elapsed
        (24, 24.0, 0.0),  # exactly at SLA -> not yet overdue
        (24, 12.0, 0.0),  # within SLA -> clamped to 0
        (24, 30.0, 6.0),  # 6 h past
        (24, 48.0, 24.0),  # a full window past
        (24, 72.0, 48.0),  # two windows past
        (10, 25.0, 15.0),
    ],
)
def test_hours_overdue_math(sla_hours: int, hours_since: float, expected: float) -> None:
    result = hours_overdue(
        _policy(sla_hours=sla_hours),
        _state(hours_since_assigned=hours_since),
    )
    assert result == pytest.approx(expected)
    assert result >= 0.0


def test_hours_overdue_never_negative_for_fresh_step() -> None:
    result = hours_overdue(
        _policy(sla_hours=24),
        _state(hours_since_assigned=0.0),
    )
    assert result == 0.0


# ---------------------------------------------------------------------------
# classify_severity - band boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sla_hours, hours_since, expected",
    [
        # on_time: not past SLA at all (ratio == 0)
        (24, 0.0, SEVERITY_ON_TIME),
        (24, 12.0, SEVERITY_ON_TIME),
        (24, 24.0, SEVERITY_ON_TIME),  # exactly at SLA, overdue 0
        # late: 0 < ratio <= 0.5  (overdue up to half the window)
        (24, 24.0001, SEVERITY_LATE),  # just over
        (24, 30.0, SEVERITY_LATE),  # ratio 0.25
        (24, 36.0, SEVERITY_LATE),  # ratio 0.5 exactly -> top of late band
        # breached: 0.5 < ratio <= 1.0
        (24, 36.0001, SEVERITY_BREACHED),  # just over half
        (24, 42.0, SEVERITY_BREACHED),  # ratio 0.75
        (24, 48.0, SEVERITY_BREACHED),  # ratio 1.0 exactly -> top of breached
        # critical: ratio > 1.0
        (24, 48.0001, SEVERITY_CRITICAL),  # just over a full window
        (24, 72.0, SEVERITY_CRITICAL),  # ratio 2.0
    ],
)
def test_classify_severity_bands(sla_hours: int, hours_since: float, expected: str) -> None:
    result = classify_severity(
        _policy(sla_hours=sla_hours),
        _state(hours_since_assigned=hours_since),
    )
    assert result == expected


def test_classify_severity_zero_sla_on_time_when_not_overdue() -> None:
    # Degenerate SLA, no time elapsed -> nothing overdue -> on_time.
    result = classify_severity(
        _policy(sla_hours=0),
        _state(hours_since_assigned=0.0),
    )
    assert result == SEVERITY_ON_TIME


def test_classify_severity_zero_sla_any_overrun_is_critical() -> None:
    # Degenerate SLA cannot form a ratio; any overdue time is critical.
    result = classify_severity(
        _policy(sla_hours=0),
        _state(hours_since_assigned=0.5),
    )
    assert result == SEVERITY_CRITICAL


def test_classify_severity_negative_sla_any_overrun_is_critical() -> None:
    result = classify_severity(
        _policy(sla_hours=-5),
        _state(hours_since_assigned=1.0),
    )
    assert result == SEVERITY_CRITICAL


# ---------------------------------------------------------------------------
# dataclass shape / immutability
# ---------------------------------------------------------------------------


def test_policy_defaults_to_empty_chain() -> None:
    policy = EscalationPolicy(target_kind="x", sla_hours=1, escalate_after_hours=2)
    assert policy.chain == ()


def test_state_defaults_to_no_prior_escalations() -> None:
    state = EscalationState(hours_since_assigned=1.0, current_holder="a")
    assert state.already_escalated_to == ()


def test_decision_is_frozen() -> None:
    decision = decide_escalation(
        _policy(),
        _state(hours_since_assigned=0.0),
    )
    with pytest.raises(Exception):
        decision.should_escalate = True  # type: ignore[misc]


def test_policy_is_frozen() -> None:
    policy = _policy()
    with pytest.raises(Exception):
        policy.sla_hours = 99  # type: ignore[misc]
