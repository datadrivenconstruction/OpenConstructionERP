# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure ownership hand-off chain engine (runs on py3.11)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.change_intelligence.ownership_chain import (
    REASON_CHAIN_INCONSISTENT,
    REASON_NO_HOLDER,
    REASON_UNCHANGED_ACROSS_TRANSITION,
    HandoffRow,
    OwnershipChain,
    build_ownership_chain,
)

NOW = datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)


def _ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def _handoff(
    *,
    days_ago: float,
    from_party: str | None,
    to_party: str | None,
    set_by: str | None = "pm",
    reason: str | None = None,
) -> HandoffRow:
    return HandoffRow(
        at=_ago(days_ago),
        from_party=from_party,
        to_party=to_party,
        set_by=set_by,
        reason=reason,
    )


def _dwell_map(chain: OwnershipChain) -> dict[str | None, float]:
    return {pd.party: pd.dwell_days for pd in chain.dwell_by_party}


# --- empty / degenerate ----------------------------------------------------


def test_empty_chain() -> None:
    chain = build_ownership_chain([], now=NOW)
    assert chain.segments == []
    assert chain.dwell_by_party == []
    assert chain.current_holder is None
    assert chain.total_handoffs == 0
    assert chain.as_of == NOW
    # No holder at all => ambiguous, with the no-holder reason.
    assert chain.ownership_ambiguous is True
    assert chain.has_current_holder is False
    assert chain.ambiguity_reasons == [REASON_NO_HOLDER]


def test_single_handoff_open_segment_dwells_to_now() -> None:
    chain = build_ownership_chain(
        [_handoff(days_ago=4, from_party=None, to_party="alice")],
        now=NOW,
    )
    assert len(chain.segments) == 1
    seg = chain.segments[0]
    assert seg.party == "alice"
    assert seg.is_open is True
    assert seg.to_ts is None
    assert seg.dwell_days == pytest.approx(4.0)
    assert chain.current_holder == "alice"
    assert chain.has_current_holder is True
    # from_party is None on the first hand-off => no unrecorded origin.
    assert chain.has_unrecorded_origin is False
    assert chain.ownership_ambiguous is False
    assert chain.ambiguity_reasons == []


def test_single_handoff_carries_metadata_onto_segment() -> None:
    chain = build_ownership_chain(
        [_handoff(days_ago=1, from_party=None, to_party="alice", set_by="boss", reason="kickoff")],
        now=NOW,
    )
    seg = chain.segments[0]
    assert seg.set_by == "boss"
    assert seg.reason == "kickoff"


# --- multi-segment + dwell math --------------------------------------------


def test_multi_handoff_segments_and_dwell() -> None:
    # alice held 10->6 (4d), bob 6->1 (5d), carol 1->now (1d, open).
    handoffs = [
        _handoff(days_ago=10, from_party=None, to_party="alice"),
        _handoff(days_ago=6, from_party="alice", to_party="bob"),
        _handoff(days_ago=1, from_party="bob", to_party="carol"),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)

    assert [s.party for s in chain.segments] == ["alice", "bob", "carol"]
    assert [s.dwell_days for s in chain.segments] == pytest.approx([4.0, 5.0, 1.0])
    # Only the last segment is open.
    assert [s.is_open for s in chain.segments] == [False, False, True]
    assert chain.segments[0].to_ts == _ago(6)
    assert chain.segments[1].to_ts == _ago(1)
    assert chain.segments[2].to_ts is None
    assert chain.current_holder == "carol"
    assert chain.ownership_ambiguous is False


def test_closed_segments_have_explicit_end_timestamps() -> None:
    handoffs = [
        _handoff(days_ago=8, from_party=None, to_party="alice"),
        _handoff(days_ago=3, from_party="alice", to_party="bob"),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    assert chain.segments[0].from_ts == _ago(8)
    assert chain.segments[0].to_ts == _ago(3)
    assert chain.segments[1].from_ts == _ago(3)
    assert chain.segments[1].to_ts is None


def test_dwell_by_party_sums_non_contiguous_segments() -> None:
    # Ball ping-pongs back to alice: alice 9->7 (2d) + alice 4->1 (3d) = 5d.
    handoffs = [
        _handoff(days_ago=9, from_party=None, to_party="alice"),
        _handoff(days_ago=7, from_party="alice", to_party="bob"),
        _handoff(days_ago=4, from_party="bob", to_party="alice"),
        _handoff(days_ago=1, from_party="alice", to_party="bob"),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    dwell = _dwell_map(chain)
    # bob: 7->4 (3d) + 1->now (1d) = 4d.
    assert dwell["alice"] == pytest.approx(5.0)
    assert dwell["bob"] == pytest.approx(4.0)
    # Sorted most-dwell first.
    assert [pd.party for pd in chain.dwell_by_party] == ["alice", "bob"]
    alice = next(pd for pd in chain.dwell_by_party if pd.party == "alice")
    assert alice.segment_count == 2


def test_dwell_by_party_sorted_descending_with_stable_tiebreak() -> None:
    # alice and bob each hold exactly 2 days; alice appears first -> ranks first.
    handoffs = [
        _handoff(days_ago=6, from_party=None, to_party="alice"),
        _handoff(days_ago=4, from_party="alice", to_party="bob"),
        _handoff(days_ago=2, from_party="bob", to_party="carol"),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    dwell = _dwell_map(chain)
    assert dwell["alice"] == pytest.approx(2.0)
    assert dwell["bob"] == pytest.approx(2.0)
    assert dwell["carol"] == pytest.approx(2.0)
    # carol is open and also 2d; tie broken by appearance order.
    assert [pd.party for pd in chain.dwell_by_party] == ["alice", "bob", "carol"]


# --- ordering --------------------------------------------------------------


def test_out_of_order_input_is_sorted() -> None:
    handoffs = [
        _handoff(days_ago=1, from_party="bob", to_party="carol"),
        _handoff(days_ago=10, from_party=None, to_party="alice"),
        _handoff(days_ago=6, from_party="alice", to_party="bob"),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    assert [s.party for s in chain.segments] == ["alice", "bob", "carol"]
    assert [s.dwell_days for s in chain.segments] == pytest.approx([4.0, 5.0, 1.0])
    assert chain.current_holder == "carol"
    # A correctly-ordered, continuous chain is not inconsistent.
    assert chain.chain_inconsistent is False


def test_same_timestamp_handoffs_keep_input_order() -> None:
    # Two hand-offs at the same instant: stable sort preserves input order, so
    # the later-listed one becomes the current holder.
    t = _ago(2)
    handoffs = [
        HandoffRow(at=t, from_party=None, to_party="alice"),
        HandoffRow(at=t, from_party="alice", to_party="bob"),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    assert [s.party for s in chain.segments] == ["alice", "bob"]
    # alice's segment is zero-width (same instant), bob holds to now.
    assert chain.segments[0].dwell_days == pytest.approx(0.0)
    assert chain.segments[1].dwell_days == pytest.approx(2.0)
    assert chain.current_holder == "bob"


# --- timezone handling -----------------------------------------------------


def test_naive_timestamps_treated_as_utc() -> None:
    handoffs = [
        HandoffRow(at=datetime(2026, 6, 23, 12, 0, 0), from_party=None, to_party="alice"),  # naive
        HandoffRow(at=datetime(2026, 6, 24, 12, 0, 0), from_party="alice", to_party="bob"),  # naive
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    assert chain.segments[0].dwell_days == pytest.approx(1.0)
    assert chain.segments[1].dwell_days == pytest.approx(1.0)


def test_offset_timestamps_normalized_to_utc() -> None:
    from datetime import timezone

    handoffs = [
        HandoffRow(
            at=datetime(2026, 6, 25, 11, 0, 0, tzinfo=timezone(timedelta(hours=2))),  # == 09:00 UTC
            from_party=None,
            to_party="alice",
        ),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    assert chain.segments[0].from_ts == datetime(2026, 6, 25, 9, 0, 0, tzinfo=UTC)
    # 09:00 -> 12:00 UTC = 3 hours = 0.12 days.
    assert chain.segments[0].dwell_days == pytest.approx(0.12)


# --- current holder / dropped ball -----------------------------------------


def test_dropped_ball_no_current_holder_is_ambiguous() -> None:
    # Last hand-off explicitly un-assigns (to_party=None).
    handoffs = [
        _handoff(days_ago=5, from_party=None, to_party="alice"),
        _handoff(days_ago=2, from_party="alice", to_party=None),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    assert chain.current_holder is None
    assert chain.has_current_holder is False
    assert chain.ownership_ambiguous is True
    assert REASON_NO_HOLDER in chain.ambiguity_reasons
    # The open segment is the un-assigned bucket and still dwells to now.
    assert chain.segments[-1].party is None
    assert chain.segments[-1].dwell_days == pytest.approx(2.0)


# --- unrecorded origin -----------------------------------------------------


def test_unrecorded_origin_flagged_but_not_ambiguous() -> None:
    # First hand-off names a prior holder (designer) we have no received-ts for.
    handoffs = [
        _handoff(days_ago=3, from_party="designer", to_party="alice"),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    assert chain.has_unrecorded_origin is True
    # We never fabricate a segment for the unrecorded origin.
    assert [s.party for s in chain.segments] == ["alice"]
    # Unrecorded origin alone does NOT make ownership ambiguous.
    assert chain.ownership_ambiguous is False
    assert chain.ambiguity_reasons == []


# --- gap / overlap (chain inconsistency) -----------------------------------


def test_gap_in_custody_flagged_as_inconsistent() -> None:
    # bob hands off, but the next hand-off claims to come FROM carol (not bob):
    # a gap/overlap in the recorded custody chain.
    handoffs = [
        _handoff(days_ago=8, from_party=None, to_party="alice"),
        _handoff(days_ago=5, from_party="alice", to_party="bob"),
        _handoff(days_ago=2, from_party="carol", to_party="dave"),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    assert chain.chain_inconsistent is True
    assert chain.ownership_ambiguous is True
    assert REASON_CHAIN_INCONSISTENT in chain.ambiguity_reasons


def test_continuous_chain_is_not_inconsistent() -> None:
    handoffs = [
        _handoff(days_ago=8, from_party=None, to_party="alice"),
        _handoff(days_ago=5, from_party="alice", to_party="bob"),
        _handoff(days_ago=2, from_party="bob", to_party="carol"),
    ]
    chain = build_ownership_chain(handoffs, now=NOW)
    assert chain.chain_inconsistent is False
    assert REASON_CHAIN_INCONSISTENT not in chain.ambiguity_reasons


# --- ambiguity via status transition ---------------------------------------


def test_status_transition_inside_segment_is_ambiguous() -> None:
    # alice holds 10->now; a status transition at day 4 falls inside her segment
    # => the change advanced but the ball never moved.
    handoffs = [_handoff(days_ago=10, from_party=None, to_party="alice")]
    chain = build_ownership_chain(
        handoffs,
        now=NOW,
        status_transition_times=[_ago(4)],
    )
    assert chain.unchanged_across_transition is True
    assert chain.ownership_ambiguous is True
    assert REASON_UNCHANGED_ACROSS_TRANSITION in chain.ambiguity_reasons


def test_status_transition_on_handoff_boundary_is_not_ambiguous() -> None:
    # A status transition that lines up exactly with a hand-off (the ball moved
    # when the status moved) is healthy, not ambiguous.
    handoffs = [
        _handoff(days_ago=8, from_party=None, to_party="alice"),
        _handoff(days_ago=4, from_party="alice", to_party="bob"),
    ]
    chain = build_ownership_chain(
        handoffs,
        now=NOW,
        status_transition_times=[_ago(4)],  # exactly the hand-off instant
    )
    assert chain.unchanged_across_transition is False
    assert chain.ownership_ambiguous is False


def test_status_transition_with_matching_handoff_clears_ambiguity() -> None:
    # Two transitions, each matched by a hand-off => healthy.
    handoffs = [
        _handoff(days_ago=9, from_party=None, to_party="alice"),
        _handoff(days_ago=6, from_party="alice", to_party="bob"),
        _handoff(days_ago=3, from_party="bob", to_party="carol"),
    ]
    chain = build_ownership_chain(
        handoffs,
        now=NOW,
        status_transition_times=[_ago(6), _ago(3)],
    )
    assert chain.unchanged_across_transition is False
    assert chain.ownership_ambiguous is False


def test_no_transitions_supplied_is_not_unchanged() -> None:
    handoffs = [_handoff(days_ago=5, from_party=None, to_party="alice")]
    chain = build_ownership_chain(handoffs, now=NOW, status_transition_times=None)
    assert chain.unchanged_across_transition is False


def test_multiple_ambiguity_reasons_accumulate() -> None:
    # Inconsistent chain AND a dropped ball AND a transition inside a segment.
    handoffs = [
        _handoff(days_ago=10, from_party=None, to_party="alice"),
        _handoff(days_ago=6, from_party="carol", to_party="bob"),  # gap: not from alice
        _handoff(days_ago=2, from_party="bob", to_party=None),  # dropped
    ]
    chain = build_ownership_chain(
        handoffs,
        now=NOW,
        status_transition_times=[_ago(8)],  # inside alice's 10->6 segment
    )
    assert chain.ownership_ambiguous is True
    assert set(chain.ambiguity_reasons) == {
        REASON_NO_HOLDER,
        REASON_CHAIN_INCONSISTENT,
        REASON_UNCHANGED_ACROSS_TRANSITION,
    }
    # Stable reason ordering: no-holder, transition, inconsistent.
    assert chain.ambiguity_reasons == [
        REASON_NO_HOLDER,
        REASON_UNCHANGED_ACROSS_TRANSITION,
        REASON_CHAIN_INCONSISTENT,
    ]


# --- determinism -----------------------------------------------------------


def test_deterministic_across_input_orderings() -> None:
    base = [
        _handoff(days_ago=10, from_party=None, to_party="alice"),
        _handoff(days_ago=6, from_party="alice", to_party="bob"),
        _handoff(days_ago=1, from_party="bob", to_party="carol"),
    ]
    shuffled = [base[2], base[0], base[1]]
    a = build_ownership_chain(base, now=NOW)
    b = build_ownership_chain(shuffled, now=NOW)
    assert [s.party for s in a.segments] == [s.party for s in b.segments]
    assert [s.dwell_days for s in a.segments] == pytest.approx([s.dwell_days for s in b.segments])
    assert a.current_holder == b.current_holder
    assert a.dwell_by_party == b.dwell_by_party
