# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free unit tests for the international robustness and validation
additions to the schedule_advanced CPM engine.

Covers:
    * ``DURATION_UNIT`` and ``dependency_type_label`` (explicit unit + plain
      dependency-type names).
    * ``offset_calendar_from_work_days`` (build a calendar from the model's
      stored fields, with clear errors on bad weekdays / non-ISO holidays and a
      worldwide Monday-Friday default).
    * ``OffsetCalendar.nth_working_day`` and ``to_calendar_dates`` (project CPM
      working-day indices onto ISO 8601 dates, skipping weekends and holidays).
    * ``validate_network`` (conservative, plain-language findings for the real
      edge cases: empty network, self / missing dependency, negative and zero
      duration, unknown link type, circular dependency, lead before start,
      duplicate id).

Everything here is pure: no DB, no FastAPI, no SQLAlchemy.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.schedule_advanced.cpm import (
    DEFAULT_WORK_WEEKDAYS,
    DURATION_UNIT,
    ISSUE_ERROR,
    ISSUE_INFO,
    ISSUE_WARNING,
    Activity,
    TaskNetwork,
    compute_cpm,
    dependency_type_label,
    offset_calendar_from_work_days,
    to_calendar_dates,
    validate_network,
)

# ── Explicit duration unit + dependency labels ──────────────────────────────


def test_duration_unit_is_working_day() -> None:
    assert DURATION_UNIT == "working_day"


def test_dependency_type_label_known_types_are_plain_language() -> None:
    assert dependency_type_label("FS").startswith("Finish-to-Start")
    assert dependency_type_label("SS").startswith("Start-to-Start")
    assert dependency_type_label("FF").startswith("Finish-to-Finish")
    assert dependency_type_label("SF").startswith("Start-to-Finish")


def test_dependency_type_label_unknown_type_is_explained() -> None:
    label = dependency_type_label("ZZ")
    assert "ZZ" in label
    assert "FS, SS, FF or SF" in label


def test_no_forbidden_typography_in_generated_messages() -> None:
    # No em-dashes or smart quotes anywhere in the user-facing strings we added.
    strings = [dependency_type_label(c) for c in ("FS", "SS", "FF", "SF", "ZZ")]
    acts = [Activity(id="A", duration=-1), Activity(id="A", duration=0)]
    strings += [i.message for i in validate_network(acts)]
    for s in strings:
        for bad in ("—", "–", "‘", "’", "“", "”"):
            assert bad not in s


# ── Calendar factory from stored model fields ───────────────────────────────


def test_calendar_factory_defaults_to_monday_to_friday() -> None:
    cal = offset_calendar_from_work_days(None, None)
    assert cal.work_weekdays == DEFAULT_WORK_WEEKDAYS
    assert cal.holidays == frozenset()


def test_calendar_factory_empty_work_days_defaults_to_monday_to_friday() -> None:
    cal = offset_calendar_from_work_days([], [])
    assert cal.work_weekdays == DEFAULT_WORK_WEEKDAYS


def test_calendar_factory_honours_custom_work_week() -> None:
    # A six-day work week (Mon-Sat) as used in many regions.
    cal = offset_calendar_from_work_days([0, 1, 2, 3, 4, 5], [])
    assert cal.work_weekdays == frozenset({0, 1, 2, 3, 4, 5})
    # Saturday 2026-01-03 is now a working day.
    assert cal._is_working_date(date(2026, 1, 3)) is True


def test_calendar_factory_supports_non_western_weekend() -> None:
    # Friday-Saturday weekend: work Sunday(6)-Thursday(3).
    cal = offset_calendar_from_work_days([6, 0, 1, 2, 3], [])
    assert cal._is_working_date(date(2026, 1, 2)) is False  # Friday off
    assert cal._is_working_date(date(2026, 1, 4)) is True  # Sunday works


def test_calendar_factory_rejects_bad_weekday_with_clear_message() -> None:
    with pytest.raises(ValueError, match="valid weekday"):
        offset_calendar_from_work_days([0, 1, 7], [])


def test_calendar_factory_rejects_non_iso_holiday_with_clear_message() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        offset_calendar_from_work_days([0, 1, 2, 3, 4], ["25/12/2026"])


def test_calendar_factory_accepts_iso_holidays() -> None:
    cal = offset_calendar_from_work_days([0, 1, 2, 3, 4], ["2026-12-25"])
    assert "2026-12-25" in cal.holidays
    assert cal._is_working_date(date(2026, 12, 25)) is False


# ── nth_working_day / ISO date projection ───────────────────────────────────


def test_nth_working_day_skips_weekend() -> None:
    cal = offset_calendar_from_work_days([0, 1, 2, 3, 4], [])
    start = date(2026, 1, 5)  # Monday
    assert cal.nth_working_day(start, 0) == date(2026, 1, 5)  # Mon
    assert cal.nth_working_day(start, 4) == date(2026, 1, 9)  # Fri
    assert cal.nth_working_day(start, 5) == date(2026, 1, 12)  # next Mon


def test_nth_working_day_skips_holiday() -> None:
    cal = offset_calendar_from_work_days([0, 1, 2, 3, 4], ["2026-01-07"])
    start = date(2026, 1, 5)  # Monday
    # index 2 would be Wed 2026-01-07 but that is a holiday, so it moves to Thu.
    assert cal.nth_working_day(start, 2) == date(2026, 1, 8)


def test_nth_working_day_advances_from_non_working_project_start() -> None:
    cal = offset_calendar_from_work_days([0, 1, 2, 3, 4], [])
    start = date(2026, 1, 3)  # Saturday -> first working day is Monday 5th
    assert cal.nth_working_day(start, 0) == date(2026, 1, 5)


def test_nth_working_day_negative_index_raises() -> None:
    cal = offset_calendar_from_work_days([0, 1, 2, 3, 4], [])
    with pytest.raises(ValueError, match="0 or greater"):
        cal.nth_working_day(date(2026, 1, 5), -1)


def test_to_calendar_dates_projects_iso_dates_over_a_weekend() -> None:
    # A -> B (FS), each 3 working days, Monday start. A occupies Mon-Wed,
    # finishing Wed; B starts Thu, occupies Thu, Fri, next Mon (weekend skipped).
    activities = [
        Activity(id="A", duration=3),
        Activity(id="B", duration=3, predecessors=[("A", "FS", 0)]),
    ]
    results = compute_cpm(TaskNetwork(activities))
    cal = offset_calendar_from_work_days([0, 1, 2, 3, 4], [])
    dates = to_calendar_dates(results, cal, date(2026, 1, 5))  # Monday
    assert dates["A"].early_start == "2026-01-05"  # Mon
    assert dates["A"].early_finish == "2026-01-07"  # Wed (last day worked)
    assert dates["B"].early_start == "2026-01-08"  # Thu
    assert dates["B"].early_finish == "2026-01-12"  # next Mon after weekend


def test_to_calendar_dates_milestone_has_equal_start_and_finish() -> None:
    activities = [Activity(id="M", duration=0)]
    results = compute_cpm(TaskNetwork(activities))
    cal = offset_calendar_from_work_days([0, 1, 2, 3, 4], [])
    dates = to_calendar_dates(results, cal, date(2026, 1, 5))
    assert dates["M"].early_start == dates["M"].early_finish == "2026-01-05"


def test_to_calendar_dates_all_days_calendar_matches_plain_offsets() -> None:
    # With every day a working day, dates advance one calendar day per index.
    activities = [Activity(id="A", duration=4)]
    results = compute_cpm(TaskNetwork(activities))
    cal = offset_calendar_from_work_days([0, 1, 2, 3, 4, 5, 6], [])
    dates = to_calendar_dates(results, cal, date(2026, 1, 5))
    assert dates["A"].early_start == "2026-01-05"
    assert dates["A"].early_finish == "2026-01-08"  # es=0, ef=4 -> last day index 3


# ── validate_network ────────────────────────────────────────────────────────


def _codes(activities: list[Activity]) -> set[str]:
    return {i.code for i in validate_network(activities)}


def test_validate_empty_network_is_info() -> None:
    issues = validate_network([])
    assert len(issues) == 1
    assert issues[0].code == "EMPTY_NETWORK"
    assert issues[0].severity == ISSUE_INFO


def test_validate_self_dependency_is_error() -> None:
    acts = [Activity(id="A", duration=2, predecessors=[("A", "FS", 0)])]
    issues = validate_network(acts)
    self_dep = [i for i in issues if i.code == "SELF_DEPENDENCY"]
    assert len(self_dep) == 1
    assert self_dep[0].severity == ISSUE_ERROR
    assert self_dep[0].activity_id == "A"


def test_validate_missing_predecessor_is_error() -> None:
    acts = [Activity(id="B", duration=2, predecessors=[("A", "FS", 0)])]
    issues = validate_network(acts)
    missing = [i for i in issues if i.code == "MISSING_PREDECESSOR"]
    assert len(missing) == 1
    assert missing[0].severity == ISSUE_ERROR
    assert "'A'" in missing[0].message


def test_validate_negative_duration_is_warning() -> None:
    acts = [Activity(id="A", duration=-3)]
    issues = validate_network(acts)
    neg = [i for i in issues if i.code == "NEGATIVE_DURATION"]
    assert len(neg) == 1
    assert neg[0].severity == ISSUE_WARNING


def test_validate_zero_duration_is_info() -> None:
    acts = [Activity(id="M", duration=0)]
    codes = {i.code: i.severity for i in validate_network(acts)}
    assert codes.get("ZERO_DURATION") == ISSUE_INFO


def test_validate_unknown_dependency_type_is_error() -> None:
    acts = [
        Activity(id="A", duration=2),
        Activity(id="B", duration=2, predecessors=[("A", "ZZ", 0)]),  # type: ignore[list-item]
    ]
    issues = validate_network(acts)
    bad = [i for i in issues if i.code == "UNKNOWN_DEPENDENCY_TYPE"]
    assert len(bad) == 1
    assert bad[0].severity == ISSUE_ERROR


def test_validate_circular_dependency_is_error_and_spells_out_loop() -> None:
    acts = [
        Activity(id="A", duration=1, predecessors=[("C", "FS", 0)]),
        Activity(id="B", duration=1, predecessors=[("A", "FS", 0)]),
        Activity(id="C", duration=1, predecessors=[("B", "FS", 0)]),
    ]
    issues = validate_network(acts)
    loop = [i for i in issues if i.code == "CIRCULAR_DEPENDENCY"]
    assert len(loop) == 1
    assert loop[0].severity == ISSUE_ERROR
    # The loop text lists all three activities.
    for name in ("A", "B", "C"):
        assert name in loop[0].message


def test_validate_lead_before_project_start_is_warning() -> None:
    # A finishes at day 2; B has an FS link with a -5 lead, pulling B's ES to
    # day 2 + (-5) = -3, before the project start.
    acts = [
        Activity(id="A", duration=2),
        Activity(id="B", duration=2, predecessors=[("A", "FS", -5)]),
    ]
    issues = validate_network(acts)
    early = [i for i in issues if i.code == "STARTS_BEFORE_PROJECT_START"]
    assert len(early) == 1
    assert early[0].severity == ISSUE_WARNING
    assert early[0].activity_id == "B"


def test_validate_duplicate_activity_id_is_error() -> None:
    acts = [Activity(id="A", duration=1), Activity(id="A", duration=2)]
    codes = _codes(acts)
    assert "DUPLICATE_ACTIVITY_ID" in codes


def test_validate_clean_network_has_no_errors() -> None:
    acts = [
        Activity(id="A", duration=2),
        Activity(id="B", duration=3, predecessors=[("A", "FS", 0)]),
        Activity(id="C", duration=1, predecessors=[("B", "FS", 0)]),
    ]
    issues = validate_network(acts)
    assert [i for i in issues if i.severity == ISSUE_ERROR] == []


def test_validate_is_pure_does_not_mutate_input() -> None:
    acts = [
        Activity(id="A", duration=2),
        Activity(id="B", duration=3, predecessors=[("A", "FS", 0)]),
    ]
    before = [(a.id, a.duration, list(a.predecessors)) for a in acts]
    validate_network(acts)
    after = [(a.id, a.duration, list(a.predecessors)) for a in acts]
    assert before == after


def test_validate_sorts_errors_before_warnings_before_info() -> None:
    acts = [
        Activity(id="Z", duration=0),  # info (zero duration)
        Activity(id="A", duration=2, predecessors=[("A", "FS", 0)]),  # error (self)
        Activity(id="B", duration=-1),  # warning (negative)
    ]
    issues = validate_network(acts)
    severities = [i.severity for i in issues]
    # Errors first, then warnings, then info: non-increasing weight.
    weight = {ISSUE_ERROR: 3, ISSUE_WARNING: 2, ISSUE_INFO: 1}
    weights = [weight[s] for s in severities]
    assert weights == sorted(weights, reverse=True)
