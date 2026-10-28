# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure approval-SLA engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the
local Python 3.11 test runner without app.* or SQLAlchemy on the path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.modules.approval_routes.sla_engine import (
    BreachStatus,
    Severity,
    breach_status,
    build_reminder_message,
    compute_due_at,
    current_step_baseline,
    next_escalation_target,
)

# ---------------------------------------------------------------------------
# compute_due_at
# ---------------------------------------------------------------------------


def test_compute_due_at_none_sla_returns_none() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert compute_due_at(started, None) is None


def test_compute_due_at_adds_hours() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    due = compute_due_at(started, 8)
    assert due == datetime(2026, 1, 1, 20, 0, tzinfo=UTC)


def test_compute_due_at_naive_input_treated_as_utc() -> None:
    started_naive = datetime(2026, 1, 1, 12, 0)  # no tzinfo
    due = compute_due_at(started_naive, 2.5)
    assert due is not None
    assert due.tzinfo is not None
    assert due == datetime(2026, 1, 1, 14, 30, tzinfo=UTC)


def test_compute_due_at_accepts_float_hours() -> None:
    started = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    due = compute_due_at(started, 1.5)
    assert due == datetime(2026, 1, 1, 1, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# breach_status
# ---------------------------------------------------------------------------


def test_no_sla_is_ok() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    now = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)  # far future, but no SLA
    st = breach_status(started, None, now)
    assert isinstance(st, BreachStatus)
    assert st.severity is Severity.OK
    assert st.is_breached is False
    assert st.due_at is None
    assert st.hours_remaining is None
    assert st.hours_overdue == 0.0


def test_not_yet_due_is_ok() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    # SLA 48h -> due 2026-01-03 12:00; now is only 1h in, well outside the
    # default 24h warning window.
    now = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
    st = breach_status(started, 48, now)
    assert st.severity is Severity.OK
    assert st.is_breached is False
    assert st.due_at == datetime(2026, 1, 3, 12, 0, tzinfo=UTC)
    assert st.hours_remaining is not None
    assert abs(st.hours_remaining - 47.0) < 1e-9


def test_due_soon_within_window() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    # SLA 10h -> due 22:00; now 20:00 -> 2h remaining, inside the 24h window.
    now = datetime(2026, 1, 1, 20, 0, tzinfo=UTC)
    st = breach_status(started, 10, now)
    assert st.severity is Severity.DUE_SOON
    assert st.is_breached is False
    assert st.hours_remaining is not None
    assert abs(st.hours_remaining - 2.0) < 1e-9
    assert st.hours_overdue == 0.0


def test_due_soon_boundary_exactly_at_window() -> None:
    started = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    # SLA 48h -> due 2026-01-03 00:00. now exactly 24h before due, with the
    # default due_soon_hours=24 -> remaining == window -> DUE_SOON (<=).
    now = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    st = breach_status(started, 48, now)
    assert st.severity is Severity.DUE_SOON
    assert st.hours_remaining is not None
    assert abs(st.hours_remaining - 24.0) < 1e-9


def test_just_outside_window_is_ok() -> None:
    started = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    # due 2026-01-03 00:00; now 23:59 on the 1st -> ~24.02h remaining,
    # just outside a 24h window -> OK.
    now = datetime(2026, 1, 1, 23, 59, tzinfo=UTC)
    st = breach_status(started, 48, now)
    assert st.severity is Severity.OK
    assert st.is_breached is False


def test_exactly_at_due_is_breached_with_zero_overdue() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    due = datetime(2026, 1, 1, 20, 0, tzinfo=UTC)
    st = breach_status(started, 8, due)  # now == due_at
    assert st.severity is Severity.BREACHED
    assert st.is_breached is True
    assert abs(st.hours_overdue) < 1e-9
    assert st.hours_remaining is None
    assert st.due_at == due


def test_overdue_reports_correct_hours() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    # due 20:00; now is 2026-01-02 01:00 -> 5h overdue.
    now = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)
    st = breach_status(started, 8, now)
    assert st.severity is Severity.BREACHED
    assert st.is_breached is True
    assert abs(st.hours_overdue - 5.0) < 1e-9
    assert st.hours_remaining is None


def test_custom_due_soon_window() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    # due 22:00; now 20:00 -> 2h remaining. With a 1h window this is OK,
    # with the default 24h window it would be DUE_SOON.
    now = datetime(2026, 1, 1, 20, 0, tzinfo=UTC)
    st_tight = breach_status(started, 10, now, due_soon_hours=1.0)
    assert st_tight.severity is Severity.OK
    st_wide = breach_status(started, 10, now, due_soon_hours=24.0)
    assert st_wide.severity is Severity.DUE_SOON


def test_naive_and_aware_mix_does_not_raise() -> None:
    started_aware = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    now_naive = datetime(2026, 1, 2, 1, 0)  # naive, treated as UTC
    st = breach_status(started_aware, 8, now_naive)
    assert st.severity is Severity.BREACHED
    assert abs(st.hours_overdue - 5.0) < 1e-9

    # And the reverse: naive start, aware now.
    started_naive = datetime(2026, 1, 1, 12, 0)
    now_aware = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
    st2 = breach_status(started_naive, 48, now_aware)
    assert st2.is_breached is False
    assert st2.due_at == datetime(2026, 1, 3, 12, 0, tzinfo=UTC)


def test_non_utc_aware_now_is_normalised() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)  # due 20:00 UTC
    plus5 = timezone(timedelta(hours=5))
    # 2026-01-02 06:00 +05:00 == 2026-01-02 01:00 UTC -> 5h overdue.
    now_plus5 = datetime(2026, 1, 2, 6, 0, tzinfo=plus5)
    st = breach_status(started, 8, now_plus5)
    assert st.severity is Severity.BREACHED
    assert abs(st.hours_overdue - 5.0) < 1e-9


def test_breach_status_is_frozen() -> None:
    st = breach_status(datetime(2026, 1, 1, tzinfo=UTC), None, datetime(2026, 1, 1, tzinfo=UTC))
    try:
        st.is_breached = True  # type: ignore[misc]
    except Exception as exc:  # FrozenInstanceError subclasses Exception
        assert "cannot assign" in str(exc).lower() or "frozen" in str(type(exc)).lower()
    else:
        raise AssertionError("BreachStatus should be immutable (frozen dataclass)")


# ---------------------------------------------------------------------------
# next_escalation_target
# ---------------------------------------------------------------------------


def test_next_escalation_target_normal() -> None:
    chain = ["manager", "director", "vp"]
    # current ordinal 1 -> current element index 0 ("manager"), next is index 1.
    assert next_escalation_target(1, chain) == "director"
    assert next_escalation_target(2, chain) == "vp"


def test_next_escalation_target_at_end_returns_none() -> None:
    chain = ["manager", "director", "vp"]
    # ordinal 3 is the last element -> nothing after it.
    assert next_escalation_target(3, chain) is None
    # ordinal beyond the end.
    assert next_escalation_target(99, chain) is None


def test_next_escalation_target_empty_chain() -> None:
    assert next_escalation_target(1, []) is None


def test_next_escalation_target_low_ordinal_guarded() -> None:
    chain = ["manager", "director"]
    # ordinal 0 / negative are out of the 1-based convention -> None,
    # and crucially must not raise.
    assert next_escalation_target(0, chain) is None
    assert next_escalation_target(-1, chain) is None


def test_next_escalation_target_objects() -> None:
    a, b, c = object(), object(), object()
    chain = [a, b, c]
    assert next_escalation_target(1, chain) is b
    assert next_escalation_target(2, chain) is c
    assert next_escalation_target(3, chain) is None


# ---------------------------------------------------------------------------
# build_reminder_message
# ---------------------------------------------------------------------------


def test_reminder_message_overdue() -> None:
    started = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)  # due 12:00
    now = datetime(2026, 1, 1, 17, 0, tzinfo=UTC)  # 5h overdue
    st = breach_status(started, 8, now)
    msg = build_reminder_message("Cost review", st, now)
    assert msg == "Approval step 'Cost review' is overdue by 5.0 h (was due 2026-01-01 12:00 UTC)."
    assert "overdue" in msg
    assert "Cost review" in msg


def test_reminder_message_due_soon() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)  # due 22:00
    now = datetime(2026, 1, 1, 19, 0, tzinfo=UTC)  # 3h remaining
    st = breach_status(started, 10, now)
    msg = build_reminder_message("Budget sign-off", st, now)
    assert msg == "Approval step 'Budget sign-off' is due in 3.0 h (due 2026-01-01 22:00 UTC)."
    assert "due in" in msg


def test_reminder_message_no_sla() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    now = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
    st = breach_status(started, None, now)
    msg = build_reminder_message("Optional review", st, now)
    assert msg == "Approval step 'Optional review' has no SLA deadline."


def test_reminder_message_on_track() -> None:
    started = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)  # due 2026-01-03 12:00
    now = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)  # ~47h remaining -> OK
    st = breach_status(started, 48, now)
    msg = build_reminder_message("Early step", st, now)
    assert msg == "Approval step 'Early step' is on track (due 2026-01-03 12:00 UTC)."


def test_reminder_message_is_pure_ascii() -> None:
    started = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)
    now = datetime(2026, 1, 1, 17, 0, tzinfo=UTC)
    st = breach_status(started, 8, now)
    msg = build_reminder_message("Step", st, now)
    # Must encode cleanly as ASCII (no smart quotes / dashes leaked in).
    assert msg.encode("ascii")


# ---------------------------------------------------------------------------
# current_step_baseline
# ---------------------------------------------------------------------------


def test_baseline_first_step_uses_instance_start() -> None:
    started = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    # No prior decisions (step 1) -> the step started when the instance did.
    assert current_step_baseline(started, []) == started
    assert current_step_baseline(started, None) == started


def test_baseline_later_step_uses_latest_prior_decision() -> None:
    started = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    d1 = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
    d2 = datetime(2026, 1, 2, 14, 0, tzinfo=UTC)  # latest -> current step start
    assert current_step_baseline(started, [d1, d2]) == d2
    # Order must not matter.
    assert current_step_baseline(started, [d2, d1]) == d2


def test_baseline_ignores_none_decisions() -> None:
    started = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    d = datetime(2026, 1, 3, 8, 0, tzinfo=UTC)
    assert current_step_baseline(started, [None, d, None]) == d


def test_baseline_all_none_falls_back_to_instance_start() -> None:
    started = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    assert current_step_baseline(started, [None, None]) == started


def test_baseline_normalises_naive_to_utc() -> None:
    started_naive = datetime(2026, 1, 1, 9, 0)  # no tzinfo
    out = current_step_baseline(started_naive, [])
    assert out.tzinfo is not None
    assert out == datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    # A naive prior decision is also treated as UTC.
    d_naive = datetime(2026, 1, 2, 14, 0)
    out2 = current_step_baseline(started_naive, [d_naive])
    assert out2 == datetime(2026, 1, 2, 14, 0, tzinfo=UTC)


def test_baseline_feeds_breach_status() -> None:
    # End to end: a step that started 100h ago with a 1h SLA is breached.
    started = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    now = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)  # 100h after start
    baseline = current_step_baseline(started, [])
    st = breach_status(baseline, 1, now)
    assert st.is_breached is True
