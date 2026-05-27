"""Tests for the submittal FSM transition table.

The frontend's <SubmittalStatusPipeline> mirrors this table, so any
change here is a contract break with the UI stepper. Pin the allow-list
of transitions so a careless refactor trips before the visual review
regresses.

These are pure-data tests — no DB / no fixtures required.
"""

from __future__ import annotations

import pytest

from app.modules.submittals.service import (
    _PATCH_ALLOWED_STATUSES,
    _SUBMITTAL_STATUS_TRANSITIONS,
)

# Universe of statuses surfaced by both the API regex
# (schemas.SubmittalCreate.status) and the FSM in service.py.
ALL_STATUSES = {
    "draft",
    "submitted",
    "under_review",
    "approved",
    "approved_as_noted",
    "revise_and_resubmit",
    "rejected",
    "closed",
}


def test_fsm_keys_cover_all_known_statuses() -> None:
    """Every status the API can persist must have an entry in the FSM
    so transition checks never miss because of a typo / new value."""
    assert set(_SUBMITTAL_STATUS_TRANSITIONS.keys()) == ALL_STATUSES


def test_fsm_targets_are_known_statuses() -> None:
    """No transition may aim at a status the universe does not contain
    — guards against ghost states the UI would not know how to render."""
    for src, targets in _SUBMITTAL_STATUS_TRANSITIONS.items():
        unknown = targets - ALL_STATUSES
        assert not unknown, f"{src} → {unknown} contains unknown statuses"


def test_closed_is_terminal() -> None:
    """``closed`` is the only fully-terminal status — no resurrection
    via PATCH or any other endpoint."""
    assert _SUBMITTAL_STATUS_TRANSITIONS["closed"] == set()


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        # Happy path that the <SubmittalStatusPipeline> renders.
        ("draft", "submitted"),
        ("submitted", "under_review"),
        ("submitted", "approved"),
        ("under_review", "approved"),
        # Reviewer decisions on a live submittal.
        ("under_review", "approved_as_noted"),
        ("under_review", "revise_and_resubmit"),
        ("under_review", "rejected"),
        # Loop-back paths.
        ("revise_and_resubmit", "draft"),
        ("revise_and_resubmit", "submitted"),
        ("rejected", "draft"),
        # Closure paths.
        ("approved", "closed"),
        ("approved_as_noted", "closed"),
        ("rejected", "closed"),
    ],
)
def test_known_transitions_are_allowed(src: str, dst: str) -> None:
    """Pin the transitions the UI banks on."""
    assert dst in _SUBMITTAL_STATUS_TRANSITIONS[src], f"{src} → {dst} should be allowed"


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        # Cannot un-close.
        ("closed", "draft"),
        ("closed", "approved"),
        # Cannot skip review.
        ("draft", "approved"),
        ("draft", "under_review"),
        # Cannot bounce an already-approved submittal back to revise.
        ("approved", "revise_and_resubmit"),
        # Cannot reject after final approval.
        ("approved", "rejected"),
    ],
)
def test_forbidden_transitions_are_blocked(src: str, dst: str) -> None:
    """Negative cases — the FSM must not allow these jumps."""
    assert dst not in _SUBMITTAL_STATUS_TRANSITIONS[src], f"{src} → {dst} must be forbidden"


# ── Role-gate allow-list ────────────────────────────────────────────────


def test_patch_allowed_statuses_excludes_terminal_decisions() -> None:
    """``approved`` / ``approved_as_noted`` / ``rejected`` / ``closed``
    must NOT be reachable via a plain PATCH — they have to flow through
    the manager-gated /review or /approve endpoints. This is the auth
    bypass the SubmittalService.update_submittal check defends against,
    so a typo here would silently re-open the bypass."""
    forbidden = {"approved", "approved_as_noted", "rejected", "closed"}
    assert _PATCH_ALLOWED_STATUSES.isdisjoint(forbidden)


def test_patch_allowed_statuses_keeps_safe_in_flight_writes() -> None:
    """Editors still need to drive ``draft`` / ``submitted`` /
    ``under_review`` via PATCH (e.g. fix a typo on a draft, or mark
    something for under-review triage). Pin the safe set."""
    assert (
        frozenset(
            {"draft", "submitted", "under_review"},
        )
        == _PATCH_ALLOWED_STATUSES
    )
