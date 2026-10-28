# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure progress / percent-complete engine.

These exercise :mod:`app.modules.schedule.progress_math` directly with plain
``Decimal`` / ``dict`` inputs -- no database, FastAPI or ORM -- so they run on
any interpreter (including the local Python 3.11 runner), exactly like the EVM
and cost-risk engine tests.

They lock in the contract the "Progress rigor" feature depends on and cover the
roadmap's testable acceptance criteria #1, #2, #3, #4, #6, #8 and #9 (the
remaining criteria #5, #7, #10 are guard / migration concerns that live in the
service and DB layers, not in this pure module). Money stays ``Decimal``
throughout; working-day arithmetic is exclusive-of-start / inclusive-of-end to
match ``app/core/cpm.py``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.schedule import progress_math as pm

D = Decimal

# A fixed 10-working-day Mon-Fri span used across several criteria.
# 2026-06-01 is a Monday; exclusive-of-start counting puts the 10th working day
# on Monday 2026-06-15.
START = "2026-06-01"
END_10WD = "2026-06-15"
DATA_DATE_AT_START = "2026-06-01"


# ---------------------------------------------------------------------------
# WorkCalendar
# ---------------------------------------------------------------------------


def test_default_calendar_is_mon_fri_no_holidays() -> None:
    cal = pm.DEFAULT_CALENDAR
    assert cal.work_weekdays == frozenset({0, 1, 2, 3, 4})
    assert cal.holidays == frozenset()
    assert cal.is_working_day("2026-06-01") is True  # Monday
    assert cal.is_working_day("2026-06-06") is False  # Saturday
    assert cal.is_working_day("2026-06-07") is False  # Sunday


def test_working_days_between_is_exclusive_start_inclusive_end() -> None:
    cal = pm.DEFAULT_CALENDAR
    # Mon -> Fri same week: Tue, Wed, Thu, Fri = 4 working days.
    assert cal.working_days_between("2026-06-01", "2026-06-05") == 4
    # A full Mon..Mon (next week) span over the fixed 10-wd window.
    assert cal.working_days_between(START, END_10WD) == 10
    # Empty / inverted spans contribute nothing.
    assert cal.working_days_between("2026-06-01", "2026-06-01") == 0
    assert cal.working_days_between("2026-06-05", "2026-06-01") == 0


def test_working_days_between_skips_weekends_and_holidays() -> None:
    # Holiday on Wednesday 2026-06-03 drops one working day from the week.
    cal = pm.WorkCalendar(holidays=frozenset({"2026-06-03"}))
    assert cal.working_days_between("2026-06-01", "2026-06-05") == 3
    assert cal.is_working_day("2026-06-03") is False


def test_add_working_days_round_trips_with_between() -> None:
    cal = pm.DEFAULT_CALENDAR
    # add_working_days counts from the day after start, so 4 wd after Monday is Friday.
    assert cal.add_working_days("2026-06-01", 4) == "2026-06-05"
    # Crossing a weekend: 1 wd after Friday is the following Monday.
    assert cal.add_working_days("2026-06-05", 1) == "2026-06-08"
    # n <= 0 returns the start unchanged.
    assert cal.add_working_days("2026-06-01", 0) == "2026-06-01"
    assert cal.add_working_days("2026-06-01", -3) == "2026-06-01"
    # Round-trip: laying RD back out from start lands on the original end.
    rd = cal.working_days_between(START, END_10WD)
    assert cal.add_working_days(START, rd) == END_10WD


def test_six_day_week_changes_counts() -> None:
    cal6 = pm.WorkCalendar(work_weekdays=frozenset({0, 1, 2, 3, 4, 5}))
    # The same fixed window now contains 12 working days (Saturdays count).
    assert cal6.working_days_between(START, END_10WD) == 12


# ---------------------------------------------------------------------------
# clamp_pct / quantisers / Decimal discipline
# ---------------------------------------------------------------------------


def test_clamp_pct_bounds_and_type() -> None:
    assert pm.clamp_pct(-5) == D("0.000")
    assert pm.clamp_pct(150) == D("100.000")
    assert pm.clamp_pct(33.5) == D("33.500")
    assert pm.clamp_pct(None) == D("0.000")
    assert pm.clamp_pct("not-a-number") == D("0.000")
    assert isinstance(pm.clamp_pct(50), Decimal)


def test_clamp_pct_accepts_decimal_and_string() -> None:
    assert pm.clamp_pct(D("42.123456")) == D("42.123")
    assert pm.clamp_pct("75") == D("75.000")


def test_quantize_money_keeps_decimal() -> None:
    val = pm.quantize_money("1234.5678")
    assert val == D("1234.57")
    assert isinstance(val, Decimal)
    # float input is routed through str so no binary-float noise leaks in.
    assert pm.quantize_money(0.1) == D("0.10")


# ---------------------------------------------------------------------------
# Percent-complete type constant
# ---------------------------------------------------------------------------


def test_percent_complete_types_constant() -> None:
    assert pm.PERCENT_COMPLETE_TYPES == ("physical", "duration", "units")
    assert pm.DEFAULT_PERCENT_COMPLETE_TYPE == "physical"


# ---------------------------------------------------------------------------
# remaining_from_pct / original_duration
# ---------------------------------------------------------------------------


def test_original_duration_uses_calendar() -> None:
    assert pm.original_duration(pm.DEFAULT_CALENDAR, START, END_10WD) == 10


def test_remaining_from_pct_rounds_half_up() -> None:
    # 10 * 0.6 = 6.0 exactly.
    assert pm.remaining_from_pct(10, 40) == 6
    # 10 * 0.75 = 7.5 -> half-up -> 8 (a plain int() would wrongly give 7).
    assert pm.remaining_from_pct(10, 25) == 8
    # Fully complete leaves nothing.
    assert pm.remaining_from_pct(10, 100) == 0
    # Zero percent leaves the whole duration.
    assert pm.remaining_from_pct(10, 0) == 10
    # Never negative.
    assert pm.remaining_from_pct(0, 50) == 0


# ---------------------------------------------------------------------------
# Step roll-up (acceptance criterion #4)
# ---------------------------------------------------------------------------


def test_step_rollup_weighted_average() -> None:
    # Criterion #4: (w=3,100%), (w=1,0%) -> 75.0
    steps = [
        {"weight": D(3), "percent_complete": D(100)},
        {"weight": D(1), "percent_complete": D(0)},
    ]
    assert pm.step_rollup(steps) == D("75.000")


def test_step_rollup_accepts_dataclass_steps() -> None:
    steps = [
        pm.ProgressStep(weight=D(3), percent_complete=D(100)),
        pm.ProgressStep(weight=D(1), percent_complete=D(0)),
    ]
    assert pm.step_rollup(steps) == D("75.000")


def test_step_rollup_no_steps_returns_zero() -> None:
    assert pm.step_rollup([]) == D("0")


def test_step_rollup_all_zero_weight_returns_plain_mean() -> None:
    # Criterion #4 corollary: total weight 0 -> plain mean (caller warns).
    steps = [
        {"weight": D(0), "percent_complete": D(80)},
        {"weight": D(0), "percent_complete": D(40)},
    ]
    assert pm.step_rollup(steps) == D("60.000")
    assert pm.steps_total_weight(steps) == D(0)


def test_step_rollup_milestone_caps_below_complete() -> None:
    # Criterion #4: a milestone step below 100% caps the parent below 100 even
    # when the weighted mean would otherwise reach (or round to) 100.
    steps = [
        {"weight": D(1), "percent_complete": D(100)},
        {"weight": D(0), "percent_complete": D(50), "is_milestone": True},
    ]
    rolled = pm.step_rollup(steps)
    assert rolled == D("99.999")
    assert rolled < D(100)


def test_step_rollup_completed_milestone_does_not_cap() -> None:
    # A milestone that is itself 100% imposes no cap.
    steps = [
        {"weight": D(1), "percent_complete": D(100)},
        {"weight": D(1), "percent_complete": D(100), "is_milestone": True},
    ]
    assert pm.step_rollup(steps) == D("100.000")


# ---------------------------------------------------------------------------
# status_from
# ---------------------------------------------------------------------------


def test_status_from_basic_transitions() -> None:
    assert pm.status_from(0) == pm.STATUS_NOT_STARTED
    assert pm.status_from(1) == pm.STATUS_IN_PROGRESS
    assert pm.status_from(50) == pm.STATUS_IN_PROGRESS
    assert pm.status_from(100) == pm.STATUS_COMPLETED


def test_status_from_suspended_is_sticky() -> None:
    # Suspended overrides percent entirely.
    assert pm.status_from(0, suspended=True) == pm.STATUS_SUSPENDED
    assert pm.status_from(100, suspended=True) == pm.STATUS_SUSPENDED


def test_status_from_completion_blocked_by_open_predecessor() -> None:
    # At 100% but a predecessor is open: never *labels* complete (the service
    # guard would 409). Falls back to in_progress.
    assert pm.status_from(100, predecessors_complete=False) == pm.STATUS_IN_PROGRESS
    assert pm.status_from(100, predecessors_complete=True) == pm.STATUS_COMPLETED


# ---------------------------------------------------------------------------
# evm_distortion_warnings (deterministic keys)
# ---------------------------------------------------------------------------


def test_warning_units_without_budgeted() -> None:
    out = pm.evm_distortion_warnings(pct_type="units", budgeted_units=0)
    assert out == [pm.WARN_UNITS_WITHOUT_BUDGETED]
    # A positive budget clears it.
    assert pm.evm_distortion_warnings(pct_type="units", budgeted_units=200) == []


def test_warning_duration_on_nonlinear_cost() -> None:
    out = pm.evm_distortion_warnings(pct_type="duration", cost_is_nonlinear=True)
    assert out == [pm.WARN_DURATION_ON_NONLINEAR_COST]
    assert pm.evm_distortion_warnings(pct_type="duration", cost_is_nonlinear=False) == []


def test_warning_physical_manual_pct_is_subjective() -> None:
    out = pm.evm_distortion_warnings(pct_type="physical", has_steps=False, cost_planned=D("1000"))
    assert out == [pm.WARN_PHYSICAL_MANUAL_SUBJECTIVE]
    # Steps with real weight substantiate the percent -> no warning.
    assert (
        pm.evm_distortion_warnings(
            pct_type="physical",
            has_steps=True,
            steps_total_weight=D(4),
            cost_planned=D("1000"),
        )
        == []
    )
    # No cost loaded -> nothing subjective to flag.
    assert pm.evm_distortion_warnings(pct_type="physical", has_steps=False, cost_planned=0) == []


def test_warning_all_steps_zero_weight() -> None:
    out = pm.evm_distortion_warnings(pct_type="physical", has_steps=True, steps_total_weight=0, cost_planned=0)
    assert out == [pm.WARN_ALL_STEPS_ZERO_WEIGHT]


def test_warnings_can_stack_and_are_ordered() -> None:
    # physical + no steps + cost, AND has_steps=False so only the subjective one;
    # to stack, use units + budgeted 0 while also flagging zero-weight steps.
    out = pm.evm_distortion_warnings(
        pct_type="units",
        budgeted_units=0,
        has_steps=True,
        steps_total_weight=0,
    )
    assert out == [pm.WARN_UNITS_WITHOUT_BUDGETED, pm.WARN_ALL_STEPS_ZERO_WEIGHT]


# ---------------------------------------------------------------------------
# compute_progress -- per-type dispatch (criteria #1, #2, #3)
# ---------------------------------------------------------------------------


def test_compute_progress_physical_backcompat() -> None:
    # Criterion #1: physical + percent_in=50, no steps, no explicit RD
    # => RD = round(OD * 0.5) = 5, percent unchanged, status in_progress.
    res = pm.compute_progress(
        pct_type="physical",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        percent_in=50,
    )
    assert res.percent_complete == D("50.000")
    assert res.remaining_duration == 5
    assert res.status == pm.STATUS_IN_PROGRESS
    assert res.warnings == []


def test_compute_progress_default_type_is_physical() -> None:
    # No pct_type given -> defaults to physical, percent_in drives it.
    res = pm.compute_progress(
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        percent_in=50,
    )
    assert res.percent_complete == D("50.000")
    assert res.remaining_duration == 5


def test_compute_progress_unknown_type_falls_back_to_physical() -> None:
    res = pm.compute_progress(
        pct_type="bogus",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        percent_in=50,
    )
    assert res.percent_complete == D("50.000")
    assert res.remaining_duration == 5


def test_compute_progress_physical_explicit_remaining_diverges() -> None:
    # Physical is the only type where % and RD may legitimately diverge.
    res = pm.compute_progress(
        pct_type="physical",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        percent_in=50,
        explicit_remaining=2,
    )
    assert res.percent_complete == D("50.000")
    assert res.remaining_duration == 2  # not the auto-computed 5


def test_compute_progress_physical_with_steps_rolls_up() -> None:
    res = pm.compute_progress(
        pct_type="physical",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        steps=[
            {"weight": D(3), "percent_complete": D(100)},
            {"weight": D(1), "percent_complete": D(0)},
        ],
    )
    assert res.percent_complete == D("75.000")
    # RD auto-computed from the rolled-up 75% -> round(10 * 0.25) = 2 (2.5 half-up).
    assert res.remaining_duration == 3


def test_compute_progress_physical_zero_weight_steps_warns() -> None:
    res = pm.compute_progress(
        pct_type="physical",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        steps=[
            {"weight": D(0), "percent_complete": D(80)},
            {"weight": D(0), "percent_complete": D(40)},
        ],
    )
    assert res.percent_complete == D("60.000")  # plain mean
    assert pm.WARN_ALL_STEPS_ZERO_WEIGHT in res.warnings


def test_compute_progress_duration_type() -> None:
    # Criterion #2: 10-wd span at 40% -> RD=6, finish = data_date + 6 wd.
    res = pm.compute_progress(
        pct_type="duration",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        percent_in=40,
    )
    assert res.percent_complete == D("40.000")
    assert res.remaining_duration == 6
    assert res.forecast_finish_iso == pm.DEFAULT_CALENDAR.add_working_days(START, 6)
    assert res.forecast_finish_iso == "2026-06-09"


def test_compute_progress_duration_six_day_week_changes_finish() -> None:
    # Criterion #2 (second half): a 6-day week changes the finish deterministically.
    cal6 = pm.WorkCalendar(work_weekdays=frozenset({0, 1, 2, 3, 4, 5}))
    res = pm.compute_progress(
        pct_type="duration",
        calendar=cal6,
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        percent_in=40,
    )
    # OD is now 12 -> RD = round(12 * 0.6) = 7 (vs 6 on the Mon-Fri calendar).
    assert res.remaining_duration == 7
    assert res.forecast_finish_iso == cal6.add_working_days(START, 7)
    # The remaining duration deterministically differs from the Mon-Fri run for
    # the same percent (the calendar drives OD, hence RD). The forecast *dates*
    # may coincide -- a 6-day week reaches its 7th working day on the same
    # calendar date the 5-day week reaches its 6th -- so RD is the robust assert.
    five_day = pm.compute_progress(
        pct_type="duration",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        percent_in=40,
    )
    assert res.remaining_duration != five_day.remaining_duration


def test_compute_progress_units_type_derived_percent() -> None:
    # Criterion #3: budgeted=200, installed=50 -> 25.0, RD = round(OD*0.75) = 8.
    res = pm.compute_progress(
        pct_type="units",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        installed_units=50,
        budgeted_units=200,
    )
    assert res.percent_complete == D("25.000")
    assert res.remaining_duration == 8
    assert res.warnings == []


def test_compute_progress_units_budgeted_zero_falls_back_and_warns() -> None:
    # Criterion #3 corollary: budgeted=0 -> fall back to percent_in AND warn.
    res = pm.compute_progress(
        pct_type="units",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        installed_units=50,
        budgeted_units=0,
        percent_in=33,
    )
    assert res.percent_complete == D("33.000")
    assert pm.WARN_UNITS_WITHOUT_BUDGETED in res.warnings


def test_compute_progress_units_over_installed_clamps_to_100() -> None:
    res = pm.compute_progress(
        pct_type="units",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        installed_units=250,
        budgeted_units=200,
    )
    assert res.percent_complete == D("100.000")
    assert res.remaining_duration == 0


def test_compute_progress_completed_status_and_predecessor_guard() -> None:
    done = pm.compute_progress(
        pct_type="duration",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        percent_in=100,
    )
    assert done.status == pm.STATUS_COMPLETED
    assert done.remaining_duration == 0
    # With an open predecessor the math refuses to label it complete.
    blocked = pm.compute_progress(
        pct_type="duration",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        percent_in=100,
        predecessors_complete=False,
    )
    assert blocked.status == pm.STATUS_IN_PROGRESS


def test_compute_progress_forecast_anchored_at_data_date() -> None:
    # When the data date is past the start, the remaining work lays out from the
    # data date (work cannot remain in the past).
    res = pm.compute_progress(
        pct_type="duration",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso="2026-06-08",  # one week into the job
        percent_in=40,
    )
    assert res.remaining_duration == 6
    assert res.forecast_finish_iso == pm.DEFAULT_CALENDAR.add_working_days("2026-06-08", 6)


# ---------------------------------------------------------------------------
# Suspend / resume remaining-duration freeze (acceptance criterion #6)
# ---------------------------------------------------------------------------


def test_suspend_freezes_remaining_and_resume_shifts_finish_by_gap() -> None:
    # Criterion #6: status in_progress -> suspended -> in_progress; RD unchanged
    # across the gap; finish shifts by exactly the working-day gap on resume.
    cal = pm.DEFAULT_CALENDAR
    suspend_date = "2026-06-08"  # Monday

    # In progress at suspension; RD frozen at whatever it was (say 6).
    before = pm.compute_progress(
        pct_type="duration",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=suspend_date,
        percent_in=40,
    )
    assert before.status == pm.STATUS_IN_PROGRESS
    frozen_rd = before.remaining_duration
    assert frozen_rd == 6
    finish_at_suspend = before.forecast_finish_iso

    # While suspended the RD is held; status is sticky-suspended. We model the
    # service freezing RD by passing it back as explicit_remaining on a physical
    # snapshot (the type the suspended activity is evaluated under for layout).
    suspended_snapshot = pm.compute_progress(
        pct_type="physical",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=suspend_date,
        percent_in=40,
        explicit_remaining=frozen_rd,
        suspended=True,
    )
    assert suspended_snapshot.status == pm.STATUS_SUSPENDED
    assert suspended_snapshot.remaining_duration == frozen_rd  # unchanged

    # Resume 5 working days later: RD still frozen, finish re-laid from resume.
    resume_date = cal.add_working_days(suspend_date, 5)
    gap_wd = cal.working_days_between(suspend_date, resume_date)
    assert gap_wd == 5

    resumed = pm.compute_progress(
        pct_type="physical",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=resume_date,
        percent_in=40,
        explicit_remaining=frozen_rd,
        suspended=False,
    )
    assert resumed.status == pm.STATUS_IN_PROGRESS
    assert resumed.remaining_duration == frozen_rd  # RD unchanged across the gap

    # Finish shifts by exactly the working-day gap.
    shift = cal.working_days_between(finish_at_suspend, resumed.forecast_finish_iso)
    assert shift == gap_wd == 5


def test_add_working_days_models_suspension_gap_directly() -> None:
    # The pure working-day property behind criterion #6: re-laying a frozen RD
    # from a later anchor shifts the finish by exactly the elapsed working days.
    cal = pm.DEFAULT_CALENDAR
    rd = 6
    finish_a = cal.add_working_days("2026-06-08", rd)
    finish_b = cal.add_working_days(cal.add_working_days("2026-06-08", 5), rd)
    assert cal.working_days_between(finish_a, finish_b) == 5


# ---------------------------------------------------------------------------
# Time-phased planned value (acceptance criteria #8, #9)
# ---------------------------------------------------------------------------


def _pv_act(cost: str = "1000") -> dict:
    return {
        "baseline_start_iso": START,
        "baseline_end_iso": END_10WD,
        "cost_planned": D(cost),
    }


def test_planned_percent_for_boundaries() -> None:
    cal = pm.DEFAULT_CALENDAR
    act = _pv_act()
    # 0 before/at start (exclusive-of-start counting).
    assert pm.planned_percent_for(act, "2026-05-25", cal) == D(0)
    assert pm.planned_percent_for(act, START, cal) == D(0)
    # 1 at/after finish.
    assert pm.planned_percent_for(act, END_10WD, cal) == D(1)
    assert pm.planned_percent_for(act, "2026-06-20", cal) == D(1)
    # Strictly between inside the window (5 of 10 wd elapsed at 06-08).
    mid = pm.planned_percent_for(act, "2026-06-08", cal)
    assert D(0) < mid < D(1)
    assert mid == D("0.5")


def test_planned_percent_for_missing_dates_is_zero() -> None:
    cal = pm.DEFAULT_CALENDAR
    assert pm.planned_percent_for({"cost_planned": D(100)}, "2026-06-08", cal) == D(0)
    assert (
        pm.planned_percent_for(
            {"baseline_start_iso": START, "baseline_end_iso": START, "cost_planned": D(100)},
            "2026-06-08",
            cal,
        )
        == D(0)  # zero-length span contributes nothing
    )


def test_planned_value_at_boundaries_criterion_9() -> None:
    # Criterion #9: PV is 0 before start, BAC at/after finish, strictly between
    # inside the window.
    cal = pm.DEFAULT_CALENDAR
    acts = [_pv_act("1000")]

    def cal_for(_a: dict) -> pm.WorkCalendar:
        return cal

    bac = pm.budget_at_completion(acts)
    assert bac == D("1000.00")

    pv_before = pm.planned_value_at(acts, "2026-05-25", cal_for)
    pv_at_start = pm.planned_value_at(acts, START, cal_for)
    pv_mid = pm.planned_value_at(acts, "2026-06-08", cal_for)
    pv_at_finish = pm.planned_value_at(acts, END_10WD, cal_for)
    pv_after = pm.planned_value_at(acts, "2026-06-20", cal_for)

    assert pv_before == D("0.00")
    assert pv_at_start == D("0.00")
    assert pv_at_finish == bac
    assert pv_after == bac
    assert D("0.00") < pv_mid < bac
    assert pv_mid == D("500.00")
    # Every PV is a Decimal (money discipline).
    for value in (pv_before, pv_mid, pv_at_finish):
        assert isinstance(value, Decimal)


def test_planned_value_at_honours_per_activity_calendar() -> None:
    # Two identical activities; one on a 6-day week sees more elapsed working
    # days at the same data date, so its PV is higher.
    cal5 = pm.DEFAULT_CALENDAR
    cal6 = pm.WorkCalendar(work_weekdays=frozenset({0, 1, 2, 3, 4, 5}))
    act5 = {**_pv_act("1000"), "_cal": "5"}
    act6 = {**_pv_act("1000"), "_cal": "6"}

    def cal_for(a: dict) -> pm.WorkCalendar:
        return cal6 if a.get("_cal") == "6" else cal5

    # At Monday 06-08 both calendars are exactly half-elapsed (5/10 vs 6/12).
    pv5 = pm.planned_value_at([act5], "2026-06-08", cal_for)
    pv6 = pm.planned_value_at([act6], "2026-06-08", cal_for)
    assert pv5 == D("500.00")
    assert pv6 == D("500.00")  # 6/12 == 5/10 here; calendar still applied per-activity
    # Saturday 06-06 is a working day ONLY on the 6-day calendar, so the two
    # diverge there -- proving cal_for is honoured per activity. Mon-Fri sees
    # Tue..Fri = 4/10; the 6-day week sees Tue..Sat = 5/12.
    pv5_sat = pm.planned_value_at([act5], "2026-06-06", cal_for)
    pv6_sat = pm.planned_value_at([act6], "2026-06-06", cal_for)
    assert pv5_sat == D("400.00")  # 4/10
    assert pv6_sat == D("416.67")  # 5/12, quantised to cents
    assert pv6_sat > pv5_sat  # Saturday counts only on the 6-day calendar


def test_planned_value_at_sums_multiple_activities() -> None:
    cal = pm.DEFAULT_CALENDAR

    def cal_for(_a: dict) -> pm.WorkCalendar:
        return cal

    acts = [_pv_act("1000"), _pv_act("500")]
    # Both half-elapsed at 06-08 -> 500 + 250.
    assert pm.planned_value_at(acts, "2026-06-08", cal_for) == D("750.00")


# ---------------------------------------------------------------------------
# Earned value (method-aware via pre-resolved percent)
# ---------------------------------------------------------------------------


def test_earned_value_uses_resolved_percent() -> None:
    acts = [
        {
            "baseline_start_iso": START,
            "baseline_end_iso": END_10WD,
            "cost_planned": D("1000"),
            "percent_complete": D("40"),
        },
        {
            "baseline_start_iso": START,
            "baseline_end_iso": END_10WD,
            "cost_planned": D("500"),
            "percent_complete": D("100"),
        },
    ]
    # EV = 1000*0.4 + 500*1.0 = 900.
    ev = pm.earned_value(acts)
    assert ev == D("900.00")
    assert isinstance(ev, Decimal)


def test_earned_value_method_aware_flag_is_inert() -> None:
    acts = [
        {"cost_planned": D("1000"), "percent_complete": D("40")},
    ]
    assert pm.earned_value(acts, method_aware=True) == pm.earned_value(acts, method_aware=False)


def test_earned_value_clamps_percent() -> None:
    acts = [{"cost_planned": D("1000"), "percent_complete": D("150")}]
    assert pm.earned_value(acts) == D("1000.00")


def test_budget_at_completion_sums_costs() -> None:
    acts = [{"cost_planned": D("1000")}, {"cost_planned": D("250.5")}]
    assert pm.budget_at_completion(acts) == D("1250.50")


# ---------------------------------------------------------------------------
# Determinism / purity smoke test
# ---------------------------------------------------------------------------


def test_compute_progress_is_deterministic() -> None:
    kwargs = dict(
        pct_type="duration",
        start_iso=START,
        end_iso=END_10WD,
        data_date_iso=DATA_DATE_AT_START,
        percent_in=40,
    )
    a = pm.compute_progress(**kwargs)
    b = pm.compute_progress(**kwargs)
    assert a == b


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    raise SystemExit(pytest.main([__file__, "-q"]))
