# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the schedule real-time / field math (T3.4).

Stdlib and the pure module only, so they run on the local Python 3.11 runner
without the ORM or the database. Focus: the optimistic-concurrency revision
arithmetic (apply / stale / noop / invalid and the force escape hatch), the
field-submission validation and normalisation (clamp percent, floor remaining,
finish implies complete, require a mutating field, reject malformed ISO), and
the idempotent-replay predicate.
"""

from __future__ import annotations

from app.modules.schedule.realtime_math import (
    FieldProgressSubmission,
    MergeOutcome,
    bump_revision,
    check_revision,
    dedupe_decision,
    validate_field_submission,
)


def _sub(**kw) -> FieldProgressSubmission:
    base = {"activity_id": "a1", "client_op_id": "op1"}
    base.update(kw)
    return FieldProgressSubmission(**base)


# ----- revision arithmetic ----------------------------------------------------


def test_check_revision_apply_on_match() -> None:
    r = check_revision(client_base_revision=5, server_revision=5, has_changes=True)
    assert r.outcome is MergeOutcome.APPLY
    assert r.current_revision == 5
    assert r.next_revision == 6
    assert r.should_write is True


def test_check_revision_stale_when_client_behind() -> None:
    r = check_revision(client_base_revision=3, server_revision=5, has_changes=True)
    assert r.outcome is MergeOutcome.STALE
    assert r.current_revision == 5
    assert r.next_revision == 5  # no bump on a rejected stale write
    assert r.should_write is False


def test_check_revision_noop_when_equal_and_no_changes() -> None:
    r = check_revision(client_base_revision=5, server_revision=5, has_changes=False)
    assert r.outcome is MergeOutcome.NOOP
    assert r.next_revision == 5  # an unchanged double-submit must not bump
    assert r.should_write is False


def test_check_revision_invalid_on_negative_base() -> None:
    r = check_revision(client_base_revision=-1, server_revision=5, has_changes=True)
    assert r.outcome is MergeOutcome.INVALID
    assert r.next_revision == 5


def test_check_revision_invalid_on_future_base() -> None:
    r = check_revision(client_base_revision=9, server_revision=5, has_changes=True)
    assert r.outcome is MergeOutcome.INVALID


def test_check_revision_invalid_on_bool_base() -> None:
    # bool is a subclass of int; it must not be read as revision 0/1.
    r = check_revision(client_base_revision=True, server_revision=5, has_changes=True)
    assert r.outcome is MergeOutcome.INVALID


def test_check_revision_none_base_is_force_apply() -> None:
    for has_changes in (True, False):
        r = check_revision(client_base_revision=None, server_revision=5, has_changes=has_changes)
        assert r.outcome is MergeOutcome.APPLY
        assert r.next_revision == 6


def test_bump_revision_monotonic_and_floored() -> None:
    assert bump_revision(0) == 1
    assert bump_revision(7) == 8
    assert bump_revision(-5) == 1  # a stray negative floors at zero then increments


# ----- field submission validation / normalisation ----------------------------


def test_validate_clamps_percent() -> None:
    high = validate_field_submission(_sub(percent_complete=150.0))
    assert high.ok is True
    assert high.normalized is not None
    assert high.normalized.percent_complete == 100.0

    low = validate_field_submission(_sub(percent_complete=-10.0))
    assert low.ok is True
    assert low.normalized is not None
    assert low.normalized.percent_complete == 0.0


def test_validate_floors_remaining_duration() -> None:
    res = validate_field_submission(_sub(remaining_duration=-4))
    assert res.ok is True
    assert res.normalized is not None
    assert res.normalized.remaining_duration == 0


def test_validate_requires_one_mutating_field() -> None:
    res = validate_field_submission(_sub(captured_at_iso="2026-06-23"))
    assert res.ok is False
    assert any("mutating" in e for e in res.errors)


def test_validate_finish_implies_complete() -> None:
    ok = validate_field_submission(_sub(actual_finish_iso="2026-06-23"))
    assert ok.ok is True
    assert ok.normalized is not None
    assert ok.normalized.percent_complete == 100.0


def test_validate_rejects_finish_with_sub_100_percent() -> None:
    res = validate_field_submission(_sub(actual_finish_iso="2026-06-23", percent_complete=50.0))
    assert res.ok is False
    assert any("100" in e for e in res.errors)


def test_validate_rejects_bad_iso() -> None:
    res = validate_field_submission(_sub(percent_complete=10.0, actual_start_iso="not-a-date"))
    assert res.ok is False
    assert any("ISO" in e for e in res.errors)


def test_validate_accepts_iso_datetime_head() -> None:
    res = validate_field_submission(_sub(percent_complete=10.0, actual_start_iso="2026-06-23T08:30:00Z"))
    assert res.ok is True


# ----- idempotent replay ------------------------------------------------------


def test_dedupe_replay_short_circuits() -> None:
    assert (
        dedupe_decision(
            seen_result_id="r1",
            seen_result_type="schedule_activity_progress",
            expected_type="schedule_activity_progress",
        )
        is True
    )


def test_dedupe_type_mismatch_treated_as_new() -> None:
    assert (
        dedupe_decision(
            seen_result_id="r1",
            seen_result_type="punch_item",
            expected_type="schedule_activity_progress",
        )
        is False
    )


def test_dedupe_unseen_is_new() -> None:
    assert (
        dedupe_decision(
            seen_result_id=None,
            seen_result_type=None,
            expected_type="schedule_activity_progress",
        )
        is False
    )
