# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure proactive change-watch engine (runs on py3.11)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.change_intelligence.watch import (
    ALL_CLASSES,
    CLASS_INCOMPLETE,
    CLASS_LOST,
    CLASS_OK,
    CLASS_RANK,
    CLASS_STALLED,
    CLOSED_STATUSES,
    INCOMPLETE_THRESHOLD,
    LOST_IDLE_DAYS,
    REASON_INCOMPLETE,
    REASON_LOST,
    REASON_STALLED,
    STALE_IDLE_DAYS,
    WatchItem,
    WatchResult,
    WatchSummary,
    build_watch,
    classify,
    is_closed_status,
)

NOW = datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)


def _ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def _ahead(days: float) -> datetime:
    return NOW + timedelta(days=days)


def _item(
    *,
    change_id: str = "C1",
    kind: str = "change_order",
    status: str | None = "open",
    opened_days_ago: float = 30.0,
    last_movement_days_ago: float | None = 1.0,
    due_days_ago: float | None = None,
    due_days_ahead: float | None = None,
    completeness_score: float = 1.0,
    has_owner: bool = True,
) -> WatchItem:
    """Build a WatchItem; by default a healthy, owned, recently-moved change.

    ``due_days_ago`` puts the due date in the past (overdue); ``due_days_ahead``
    puts it in the future (not overdue). At most one should be given.
    """
    if due_days_ago is not None:
        due_at: datetime | None = _ago(due_days_ago)
    elif due_days_ahead is not None:
        due_at = _ahead(due_days_ahead)
    else:
        due_at = None
    return WatchItem(
        change_id=change_id,
        kind=kind,
        status=status,
        opened_at=_ago(opened_days_ago),
        last_movement_at=(None if last_movement_days_ago is None else _ago(last_movement_days_ago)),
        due_at=due_at,
        completeness_score=completeness_score,
        has_owner=has_owner,
    )


# --------------------------------------------------------------------------- #
# Healthy / ok baseline.
# --------------------------------------------------------------------------- #


def test_healthy_change_is_ok_with_no_reasons() -> None:
    result = classify(_item(), now=NOW)
    assert result.classification == CLASS_OK
    assert result.reasons == ()
    assert result.change_id == "C1"
    assert result.kind == "change_order"


def test_ok_change_idle_within_threshold_and_not_overdue() -> None:
    # Idle just under the stall threshold, due date in the future, fully complete,
    # owned: nothing trips.
    result = classify(
        _item(
            last_movement_days_ago=STALE_IDLE_DAYS - 1.0,
            due_days_ahead=5.0,
            completeness_score=1.0,
            has_owner=True,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK
    assert result.reasons == ()


# --------------------------------------------------------------------------- #
# Incomplete - threshold boundary (inclusive-open at the threshold).
# --------------------------------------------------------------------------- #


def test_incomplete_below_threshold_is_flagged() -> None:
    result = classify(_item(completeness_score=INCOMPLETE_THRESHOLD - 0.01), now=NOW)
    assert result.classification == CLASS_INCOMPLETE
    assert result.reasons == (REASON_INCOMPLETE,)


def test_incomplete_exactly_at_threshold_is_ok() -> None:
    # Boundary: a score exactly at the threshold is "complete enough".
    result = classify(_item(completeness_score=INCOMPLETE_THRESHOLD), now=NOW)
    assert result.classification == CLASS_OK
    assert result.reasons == ()


def test_incomplete_just_above_threshold_is_ok() -> None:
    result = classify(_item(completeness_score=INCOMPLETE_THRESHOLD + 0.01), now=NOW)
    assert result.classification == CLASS_OK


def test_zero_completeness_is_incomplete() -> None:
    result = classify(_item(completeness_score=0.0), now=NOW)
    assert result.classification == CLASS_INCOMPLETE
    assert REASON_INCOMPLETE in result.reasons


# --------------------------------------------------------------------------- #
# Stalled - needs open + overdue + idle beyond STALE_IDLE_DAYS.
# --------------------------------------------------------------------------- #


def test_stalled_overdue_and_idle_beyond_threshold() -> None:
    result = classify(
        _item(
            due_days_ago=5.0,
            last_movement_days_ago=STALE_IDLE_DAYS + 1.0,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_STALLED
    assert result.reasons == (REASON_STALLED,)
    assert result.overdue_days == pytest.approx(5.0)


def test_stalled_idle_exactly_at_threshold_is_not_stalled() -> None:
    # Boundary: the rule is strictly greater than STALE_IDLE_DAYS, so idle
    # exactly at the threshold does not stall.
    result = classify(
        _item(
            due_days_ago=5.0,
            last_movement_days_ago=STALE_IDLE_DAYS,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK
    assert result.reasons == ()


def test_overdue_but_recently_touched_is_not_stalled() -> None:
    # Overdue, but moved yesterday: it is being worked, so not stalled.
    result = classify(
        _item(
            due_days_ago=10.0,
            last_movement_days_ago=1.0,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK
    assert result.overdue_days == pytest.approx(10.0)


def test_idle_but_not_overdue_is_not_stalled() -> None:
    # Long idle but the due date is still in the future: not stalled (no overdue).
    result = classify(
        _item(
            due_days_ahead=10.0,
            last_movement_days_ago=STALE_IDLE_DAYS + 30.0,
            has_owner=True,
            completeness_score=1.0,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK
    assert result.overdue_days == 0.0


def test_no_due_date_can_never_be_stalled() -> None:
    # No due date => never overdue => never stalled, however idle it is.
    result = classify(
        _item(
            due_days_ago=None,
            due_days_ahead=None,
            last_movement_days_ago=STALE_IDLE_DAYS + 100.0,
            has_owner=True,
            completeness_score=1.0,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK
    assert result.overdue_days == 0.0


def test_due_exactly_now_is_not_overdue() -> None:
    # Boundary: overdue requires now strictly after due_at.
    item = WatchItem(
        change_id="C1",
        kind="change_order",
        status="open",
        opened_at=_ago(30.0),
        last_movement_at=_ago(STALE_IDLE_DAYS + 5.0),
        due_at=NOW,
        completeness_score=1.0,
        has_owner=True,
    )
    result = classify(item, now=NOW)
    assert result.overdue_days == 0.0
    assert result.classification == CLASS_OK


# --------------------------------------------------------------------------- #
# Lost - needs open + idle beyond LOST_IDLE_DAYS + no owner.
# --------------------------------------------------------------------------- #


def test_lost_idle_beyond_threshold_and_unowned() -> None:
    result = classify(
        _item(
            last_movement_days_ago=LOST_IDLE_DAYS + 1.0,
            has_owner=False,
            completeness_score=1.0,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_LOST
    assert result.reasons == (REASON_LOST,)


def test_lost_idle_exactly_at_threshold_is_not_lost() -> None:
    # Boundary: strictly greater than LOST_IDLE_DAYS.
    result = classify(
        _item(
            last_movement_days_ago=LOST_IDLE_DAYS,
            has_owner=False,
            completeness_score=1.0,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK
    assert result.reasons == ()


def test_unowned_but_recently_moved_is_not_lost() -> None:
    result = classify(
        _item(
            last_movement_days_ago=2.0,
            has_owner=False,
            completeness_score=1.0,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK


def test_long_idle_but_owned_is_not_lost() -> None:
    # Idle well beyond the lost threshold but it has an owner: not lost.
    result = classify(
        _item(
            last_movement_days_ago=LOST_IDLE_DAYS + 30.0,
            has_owner=True,
            completeness_score=1.0,
            due_days_ahead=10.0,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK


# --------------------------------------------------------------------------- #
# Idle-day baseline: last_movement_at falls back to opened_at.
# --------------------------------------------------------------------------- #


def test_idle_days_measured_from_last_movement() -> None:
    result = classify(
        _item(opened_days_ago=40.0, last_movement_days_ago=3.0),
        now=NOW,
    )
    assert result.idle_days == pytest.approx(3.0)


def test_idle_days_falls_back_to_opened_at_when_no_movement() -> None:
    result = classify(
        _item(opened_days_ago=12.0, last_movement_days_ago=None),
        now=NOW,
    )
    assert result.idle_days == pytest.approx(12.0)


def test_lost_uses_opened_at_when_never_moved() -> None:
    # Never moved since opening, opened long ago, unowned => lost via opened-at
    # fallback for the idle baseline.
    result = classify(
        _item(
            opened_days_ago=LOST_IDLE_DAYS + 5.0,
            last_movement_days_ago=None,
            has_owner=False,
            completeness_score=1.0,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_LOST
    assert result.idle_days == pytest.approx(LOST_IDLE_DAYS + 5.0)


# --------------------------------------------------------------------------- #
# Day-math clamping and rounding.
# --------------------------------------------------------------------------- #


def test_idle_days_clamped_at_zero_for_future_movement() -> None:
    # A last-movement timestamp in the future (clock skew) clamps idle to zero.
    item = _item(last_movement_days_ago=-3.0)
    result = classify(item, now=NOW)
    assert result.idle_days == 0.0


def test_overdue_days_rounded_two_dp() -> None:
    # 2.5 days overdue should round-trip exactly to 2.5.
    result = classify(
        _item(due_days_ago=2.5, last_movement_days_ago=1.0),
        now=NOW,
    )
    assert result.overdue_days == pytest.approx(2.5)


def test_naive_datetimes_treated_as_utc() -> None:
    # Naive inputs are stamped UTC, not shifted, so the math matches the aware
    # case exactly.
    naive_now = datetime(2026, 6, 25, 12, 0, 0)
    item = WatchItem(
        change_id="C1",
        kind="change_order",
        status="open",
        opened_at=datetime(2026, 6, 15, 12, 0, 0),
        last_movement_at=datetime(2026, 6, 22, 12, 0, 0),
        due_at=None,
        completeness_score=1.0,
        has_owner=True,
    )
    result = classify(item, now=naive_now)
    assert result.idle_days == pytest.approx(3.0)


# --------------------------------------------------------------------------- #
# Multi-match: severity selection + every matched reason present, worst-first.
# --------------------------------------------------------------------------- #


def test_stalled_and_incomplete_classifies_stalled_keeps_both_reasons() -> None:
    result = classify(
        _item(
            due_days_ago=5.0,
            last_movement_days_ago=STALE_IDLE_DAYS + 2.0,
            completeness_score=0.0,
            has_owner=True,  # owned => not lost
        ),
        now=NOW,
    )
    # stalled outranks incomplete.
    assert result.classification == CLASS_STALLED
    # Both matched reasons present, worst-first (stalled before incomplete).
    assert result.reasons == (REASON_STALLED, REASON_INCOMPLETE)


def test_lost_and_stalled_and_incomplete_classifies_lost_all_reasons() -> None:
    # Unowned + long idle (lost), overdue (stalled), low completeness (incomplete):
    # all three match; classification is the most severe (lost); reasons list all
    # three worst-first.
    result = classify(
        _item(
            due_days_ago=10.0,
            last_movement_days_ago=LOST_IDLE_DAYS + 5.0,
            completeness_score=0.1,
            has_owner=False,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_LOST
    assert result.reasons == (REASON_LOST, REASON_STALLED, REASON_INCOMPLETE)


def test_lost_and_incomplete_without_stalled() -> None:
    # Unowned + long idle (lost) + low completeness (incomplete), but not overdue
    # (no due date) so not stalled.
    result = classify(
        _item(
            due_days_ago=None,
            last_movement_days_ago=LOST_IDLE_DAYS + 2.0,
            completeness_score=0.2,
            has_owner=False,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_LOST
    assert result.reasons == (REASON_LOST, REASON_INCOMPLETE)
    assert REASON_STALLED not in result.reasons


# --------------------------------------------------------------------------- #
# Closed statuses are never flagged.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", sorted(CLOSED_STATUSES))
def test_closed_statuses_never_flagged(status: str) -> None:
    # Every closed status: even with all three failure modes set up, the change
    # is ok with no reasons because it is resolved.
    result = classify(
        _item(
            status=status,
            due_days_ago=30.0,
            last_movement_days_ago=LOST_IDLE_DAYS + 30.0,
            completeness_score=0.0,
            has_owner=False,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK
    assert result.reasons == ()


def test_closed_status_is_case_insensitive_and_trimmed() -> None:
    result = classify(
        _item(
            status="  ClOsEd  ",
            due_days_ago=30.0,
            last_movement_days_ago=LOST_IDLE_DAYS + 30.0,
            completeness_score=0.0,
            has_owner=False,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK


def test_closed_change_still_reports_idle_and_overdue_math() -> None:
    # Math is reported for display even though no failure mode is flagged.
    result = classify(
        _item(
            status="closed",
            due_days_ago=4.0,
            last_movement_days_ago=9.0,
            completeness_score=0.0,
            has_owner=False,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_OK
    assert result.idle_days == pytest.approx(9.0)
    assert result.overdue_days == pytest.approx(4.0)


def test_none_status_is_treated_as_open_and_can_be_flagged() -> None:
    result = classify(
        _item(
            status=None,
            completeness_score=0.0,
        ),
        now=NOW,
    )
    assert result.classification == CLASS_INCOMPLETE


def test_empty_status_is_treated_as_open() -> None:
    assert is_closed_status("") is False
    assert is_closed_status(None) is False
    assert is_closed_status("open") is False
    assert is_closed_status("CLOSED") is True


# --------------------------------------------------------------------------- #
# build_watch: counts, worst-first ordering, empty input.
# --------------------------------------------------------------------------- #


def test_build_watch_empty_input() -> None:
    summary = build_watch([], now=NOW)
    assert isinstance(summary, WatchSummary)
    assert summary.item_count == 0
    assert summary.items == ()
    # Every class key present and zero.
    assert summary.counts == dict.fromkeys(ALL_CLASSES, 0)
    assert set(summary.counts) == set(ALL_CLASSES)


def test_build_watch_counts_every_class_key_present() -> None:
    items = [
        _item(change_id="ok1"),  # ok
        _item(change_id="inc1", completeness_score=0.0),  # incomplete
        _item(
            change_id="stl1",
            due_days_ago=5.0,
            last_movement_days_ago=STALE_IDLE_DAYS + 2.0,
        ),  # stalled
        _item(
            change_id="lost1",
            last_movement_days_ago=LOST_IDLE_DAYS + 5.0,
            has_owner=False,
        ),  # lost
    ]
    summary = build_watch(items, now=NOW)
    assert summary.item_count == 4
    assert summary.counts[CLASS_OK] == 1
    assert summary.counts[CLASS_INCOMPLETE] == 1
    assert summary.counts[CLASS_STALLED] == 1
    assert summary.counts[CLASS_LOST] == 1
    # All four classification keys always present.
    assert set(summary.counts) == set(ALL_CLASSES)


def test_build_watch_orders_worst_first() -> None:
    items = [
        _item(change_id="ok1"),  # ok
        _item(change_id="inc1", completeness_score=0.0),  # incomplete
        _item(
            change_id="stl1",
            due_days_ago=5.0,
            last_movement_days_ago=STALE_IDLE_DAYS + 2.0,
        ),  # stalled
        _item(
            change_id="lost1",
            last_movement_days_ago=LOST_IDLE_DAYS + 5.0,
            has_owner=False,
        ),  # lost
    ]
    summary = build_watch(items, now=NOW)
    assert all(isinstance(r, WatchResult) for r in summary.items)
    classes = [r.classification for r in summary.items]
    assert classes == [CLASS_LOST, CLASS_STALLED, CLASS_INCOMPLETE, CLASS_OK]


def test_build_watch_tie_break_by_idle_then_overdue_then_id() -> None:
    # Two incomplete items: the more idle one ranks first.
    less_idle = _item(
        change_id="b_inc",
        completeness_score=0.0,
        last_movement_days_ago=2.0,
        due_days_ahead=10.0,
    )
    more_idle = _item(
        change_id="a_inc",
        completeness_score=0.0,
        last_movement_days_ago=5.0,
        due_days_ahead=10.0,
    )
    summary = build_watch([less_idle, more_idle], now=NOW)
    assert [r.change_id for r in summary.items] == ["a_inc", "b_inc"]


def test_build_watch_tie_break_by_change_id_when_fully_equal() -> None:
    # Same classification, same idle, same overdue: deterministic by change_id.
    a = _item(change_id="zzz", completeness_score=0.0, last_movement_days_ago=2.0)
    b = _item(change_id="aaa", completeness_score=0.0, last_movement_days_ago=2.0)
    summary = build_watch([a, b], now=NOW)
    assert [r.change_id for r in summary.items] == ["aaa", "zzz"]


def test_build_watch_overdue_tiebreak_within_same_class_and_idle() -> None:
    # Both stalled with identical idle; the more overdue one ranks first.
    more_overdue = _item(
        change_id="b_stl",
        due_days_ago=20.0,
        last_movement_days_ago=STALE_IDLE_DAYS + 3.0,
    )
    less_overdue = _item(
        change_id="a_stl",
        due_days_ago=2.0,
        last_movement_days_ago=STALE_IDLE_DAYS + 3.0,
    )
    summary = build_watch([less_overdue, more_overdue], now=NOW)
    # idle equal, so overdue breaks the tie: more overdue (b_stl) first.
    assert [r.change_id for r in summary.items] == ["b_stl", "a_stl"]


# --------------------------------------------------------------------------- #
# Constants / contract sanity.
# --------------------------------------------------------------------------- #


def test_class_rank_orders_modes_correctly() -> None:
    assert CLASS_RANK[CLASS_LOST] > CLASS_RANK[CLASS_STALLED]
    assert CLASS_RANK[CLASS_STALLED] > CLASS_RANK[CLASS_INCOMPLETE]
    assert CLASS_RANK[CLASS_INCOMPLETE] > CLASS_RANK[CLASS_OK]


def test_all_classes_is_worst_first_and_complete() -> None:
    # ALL_CLASSES is ordered worst-first and covers exactly the ranked classes.
    ranks = [CLASS_RANK[c] for c in ALL_CLASSES]
    assert ranks == sorted(ranks, reverse=True)
    assert set(ALL_CLASSES) == set(CLASS_RANK)


def test_lost_threshold_is_longer_than_stale() -> None:
    # Losing a change entirely is a higher bar than it stalling.
    assert LOST_IDLE_DAYS > STALE_IDLE_DAYS


def test_watchresult_is_frozen() -> None:
    result = classify(_item(), now=NOW)
    with pytest.raises((AttributeError, TypeError)):
        result.classification = CLASS_LOST  # type: ignore[misc]


def test_classify_is_deterministic() -> None:
    item = _item(
        due_days_ago=5.0,
        last_movement_days_ago=STALE_IDLE_DAYS + 2.0,
        completeness_score=0.3,
        has_owner=False,
    )
    first = classify(item, now=NOW)
    second = classify(item, now=NOW)
    assert first == second
