# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the approval-route dry-run simulator.

Pure logic only - no database, no session. Covers the shared clearance rule
(``step_cleared``), the minimum-approvals helper, and the ``simulate_route``
happy path / what-if walks. A parity grid locks the flattened ``step_cleared``
against a faithful transcription of the original nested ``_maybe_advance``
branches so the refactor cannot silently change engine behaviour.
"""

from __future__ import annotations

import itertools
import uuid
from types import SimpleNamespace

import pytest

from app.modules.approval_routes.schemas import SimulateDecision
from app.modules.approval_routes.simulate import (
    min_approvals_to_clear,
    simulate_route,
    step_cleared,
)


def _step(
    ordinal: int,
    *,
    mode: str = "all",
    role: str | None = "pm",
    user_id: uuid.UUID | None = None,
    count: int | None = None,
) -> SimpleNamespace:
    """Duck-typed StepLike stand-in (no ORM / session needed)."""
    return SimpleNamespace(
        ordinal=ordinal,
        mode=mode,
        approver_role=None if user_id is not None else role,
        approver_user_id=user_id,
        required_approver_count=count,
    )


# ── step_cleared: mode-by-mode truth table ───────────────────────────


def test_any_clears_on_first_approval() -> None:
    common = dict(
        mode="any",
        user_pinned=False,
        pinned_user_approved=False,
        distinct_approvers=1,
        rejections=0,
        total_acted=1,
        quorum=None,
    )
    assert step_cleared(approvals=0, **{**common, "distinct_approvers": 0, "total_acted": 0}) is False
    assert step_cleared(approvals=1, **common) is True


def test_all_no_quorum_needs_two_distinct_and_no_rejection() -> None:
    base = dict(mode="all", user_pinned=False, pinned_user_approved=False, quorum=None)
    assert step_cleared(approvals=1, distinct_approvers=1, rejections=0, total_acted=1, **base) is False
    assert step_cleared(approvals=2, distinct_approvers=2, rejections=0, total_acted=2, **base) is True
    # A rejection blocks even with enough approvals.
    assert step_cleared(approvals=2, distinct_approvers=2, rejections=1, total_acted=3, **base) is False


def test_all_with_quorum_counts_distinct_approvers() -> None:
    base = dict(mode="all", user_pinned=False, pinned_user_approved=False, quorum=3)
    assert step_cleared(approvals=2, distinct_approvers=2, rejections=0, total_acted=2, **base) is False
    assert step_cleared(approvals=3, distinct_approvers=3, rejections=0, total_acted=3, **base) is True
    assert step_cleared(approvals=3, distinct_approvers=3, rejections=1, total_acted=4, **base) is False


def test_majority_with_quorum_needs_more_than_half() -> None:
    base = dict(mode="majority", user_pinned=False, pinned_user_approved=False, quorum=3)
    # 1 of 3 -> 2 > 3 is false
    assert step_cleared(approvals=1, distinct_approvers=1, rejections=0, total_acted=1, **base) is False
    # 2 of 3 -> 4 > 3 is true
    assert step_cleared(approvals=2, distinct_approvers=2, rejections=0, total_acted=2, **base) is True
    # quorum 4 needs 3 distinct (6 > 4), 2 is not enough (4 > 4 false)
    q4 = {**base, "quorum": 4}
    assert step_cleared(approvals=2, distinct_approvers=2, rejections=0, total_acted=2, **q4) is False
    assert step_cleared(approvals=3, distinct_approvers=3, rejections=0, total_acted=3, **q4) is True


def test_majority_no_quorum_uses_acted_population() -> None:
    base = dict(mode="majority", user_pinned=False, pinned_user_approved=False, quorum=None)
    # only one acted -> not enough
    assert step_cleared(approvals=1, distinct_approvers=1, rejections=0, total_acted=1, **base) is False
    # 2 approved of 3 acted -> 4 > 3 true
    assert step_cleared(approvals=2, distinct_approvers=2, rejections=1, total_acted=3, **base) is True
    # 1 of 2 acted -> 2 > 2 false
    assert step_cleared(approvals=1, distinct_approvers=1, rejections=1, total_acted=2, **base) is False


def test_user_pinned_ignores_mode_and_counts() -> None:
    # Pinned: only the pinned user's approval matters.
    assert (
        step_cleared(
            mode="all",
            user_pinned=True,
            pinned_user_approved=True,
            approvals=0,
            distinct_approvers=0,
            rejections=0,
            total_acted=0,
            quorum=99,
        )
        is True
    )
    assert (
        step_cleared(
            mode="any",
            user_pinned=True,
            pinned_user_approved=False,
            approvals=5,
            distinct_approvers=5,
            rejections=0,
            total_acted=5,
            quorum=None,
        )
        is False
    )


# ── Parity: flattened rule == original nested branches ───────────────


def _original_rule(
    *,
    mode: str,
    user_pinned: bool,
    pinned_user_approved: bool,
    approvals: int,
    distinct_approvers: int,
    rejections: int,
    total_acted: int,
    quorum: int | None,
) -> bool:
    """Faithful transcription of the pre-refactor ``_maybe_advance`` branch
    tree (approver_count -> distinct_approvers, len(approvals) -> approvals,
    len(rejections) -> rejections). If ``step_cleared`` ever diverges from this
    the parity test fails."""
    if user_pinned:
        return pinned_user_approved
    if mode == "any":
        cleared = approvals >= 1
    elif mode == "majority":
        if quorum is not None and quorum >= 1:
            cleared = distinct_approvers * 2 > quorum and rejections == 0
        else:
            cleared = total_acted >= 2 and approvals * 2 > total_acted
    else:  # "all"
        if quorum is not None and quorum >= 1:
            cleared = distinct_approvers >= quorum and rejections == 0
        else:
            cleared = distinct_approvers >= 2 and rejections == 0
    return cleared


def test_step_cleared_matches_original_over_grid() -> None:
    modes = ("all", "any", "majority")
    counts = (0, 1, 2, 3)
    quorums = (None, 1, 2, 3, 4)
    checked = 0
    for mode, approvals, rej, quorum, pinned in itertools.product(modes, counts, (0, 1), quorums, (False, True)):
        distinct = approvals  # each approval a distinct approver
        total_acted = approvals + rej
        kwargs = dict(
            mode=mode,
            user_pinned=pinned,
            pinned_user_approved=approvals >= 1,
            approvals=approvals,
            distinct_approvers=distinct,
            rejections=rej,
            total_acted=total_acted,
            quorum=quorum,
        )
        assert step_cleared(**kwargs) == _original_rule(**kwargs), kwargs
        checked += 1
    assert checked > 100  # the grid actually exercised many combinations


# ── min_approvals_to_clear ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (_step(1, user_id=uuid.uuid4()), 1),
        (_step(1, mode="any"), 1),
        (_step(1, mode="all", count=None), 2),
        (_step(1, mode="all", count=3), 3),
        (_step(1, mode="majority", count=None), 2),
        (_step(1, mode="majority", count=3), 2),
        (_step(1, mode="majority", count=4), 3),
        (_step(1, mode="majority", count=1), 1),
    ],
)
def test_min_approvals_to_clear(step: SimpleNamespace, expected: int) -> None:
    assert min_approvals_to_clear(step) == expected


# ── simulate_route: happy path, warnings, scenarios ──────────────────


def _simulate(steps: list[SimpleNamespace], decisions: list[SimulateDecision] | None = None):
    return simulate_route(
        route_id=uuid.uuid4(),
        target_kind="submittal",
        steps=steps,
        decisions=decisions or [],
    )


def test_happy_path_completes_and_reports_each_step() -> None:
    steps = [
        _step(1, mode="all", count=2),
        _step(2, user_id=uuid.uuid4()),
    ]
    res = _simulate(steps)
    assert res.step_count == 2
    assert res.happy_path.outcome == "completed"
    assert res.happy_path.stopped_at_ordinal is None
    assert res.steps[0].min_approvals_to_clear == 2
    assert res.steps[1].min_approvals_to_clear == 1
    assert res.scenario is None
    assert res.warnings == []


def test_role_all_without_count_warns_needs_multiple_approvers() -> None:
    res = _simulate([_step(1, mode="all", count=None)])
    assert res.steps[0].needs_multiple_approvers is True
    assert any("at least two different approvers" in w for w in res.warnings)
    # Happy path still completes because it supplies the two approvers.
    assert res.happy_path.outcome == "completed"


def test_scenario_rejection_short_circuits() -> None:
    steps = [_step(1, mode="all", count=2), _step(2, mode="any")]
    res = _simulate(steps, [SimulateDecision(ordinal=1, approvals=1, rejections=1)])
    assert res.scenario is not None
    assert res.scenario.outcome == "rejected"
    assert res.scenario.stopped_at_ordinal == 1


def test_scenario_too_few_approvals_gets_stuck() -> None:
    steps = [_step(1, mode="all", count=3)]
    res = _simulate(steps, [SimulateDecision(ordinal=1, approvals=1)])
    assert res.scenario is not None
    assert res.scenario.outcome == "stuck"
    assert res.scenario.stopped_at_ordinal == 1


def test_scenario_unmentioned_steps_default_to_happy_minimum() -> None:
    # Only step 2 is described (rejected); step 1 keeps its happy minimum and
    # clears, so the workflow reaches step 2 and is rejected there.
    steps = [_step(1, mode="all", count=2), _step(2, mode="any")]
    res = _simulate(steps, [SimulateDecision(ordinal=2, approvals=0, rejections=1)])
    assert res.scenario is not None
    assert res.scenario.outcome == "rejected"
    assert res.scenario.stopped_at_ordinal == 2


def test_steps_are_sorted_by_ordinal() -> None:
    # Feed out of order; the report and walk must be ordinal-ordered.
    steps = [_step(2, mode="any"), _step(1, mode="all", count=2)]
    res = _simulate(steps)
    assert [s.ordinal for s in res.steps] == [1, 2]
    assert res.happy_path.outcome == "completed"
