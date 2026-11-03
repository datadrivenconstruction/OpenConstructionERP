"""Planned progress, baseline choice, tolerance status and window checks (no database)."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.geo_hub import survey_logic as logic


@pytest.mark.parametrize(
    ("on", "expected"),
    [
        (date(2026, 2, 28), 0.0),  # before start
        (date(2026, 3, 1), 0.0),  # on start
        (date(2026, 3, 11), 50.0),  # halfway through a 20 day activity
        (date(2026, 3, 21), 100.0),  # on finish
        (date(2026, 6, 1), 100.0),  # after finish
    ],
)
def test_planned_pct_is_linear_between_start_and_end(on: date, expected: float) -> None:
    assert logic.planned_pct_on_date("2026-03-01", "2026-03-21", on) == expected


def test_milestone_and_missing_dates() -> None:
    assert logic.planned_pct_on_date("2026-03-01", "2026-03-01", date(2026, 2, 28)) == 0.0
    assert logic.planned_pct_on_date("2026-03-01", "2026-03-01", date(2026, 3, 1)) == 100.0
    assert logic.planned_pct_on_date(None, None, date(2026, 3, 1)) == 0.0
    assert logic.planned_pct_on_date(None, "2026-03-10", date(2026, 3, 11)) == 100.0
    assert logic.planned_pct_on_date("garbage", "2026-03-10", date(2026, 3, 11)) == 100.0
    assert logic.planned_pct_on_date("2026-03-01T08:00:00Z", "2026-03-21T17:00:00Z", date(2026, 3, 11)) == 50.0


def test_baseline_dates_read_both_snapshot_shapes() -> None:
    a = "11111111-1111-1111-1111-111111111111"
    wrapped = {"activities": [{"id": a, "start_date": "2026-03-01", "end_date": "2026-03-11"}]}
    bare = [{"activity_id": a, "start": "2026-03-01", "finish": "2026-03-11"}]
    assert logic.baseline_dates(wrapped) == {a: ("2026-03-01", "2026-03-11")}
    assert logic.baseline_dates(bare) == {a: ("2026-03-01", "2026-03-11")}
    assert logic.baseline_dates({"nothing": 1}) == {}
    assert logic.baseline_dates(None) == {}


def test_baseline_dates_change_the_planned_value_on_the_same_day() -> None:
    on = date(2026, 3, 11)
    current = logic.planned_pct_on_date("2026-03-01", "2026-03-31", on)  # slipped plan
    baseline = logic.planned_pct_on_date("2026-03-01", "2026-03-21", on)  # original plan
    assert (round(current), baseline) == (33, 50.0)


@pytest.mark.parametrize(
    ("variance", "expected"),
    [
        (None, "unobserved"),
        (0, "on_track"),
        (5, "on_track"),
        (-5, "on_track"),
        (5.01, "ahead"),
        (-5.01, "behind"),
        (40, "ahead"),
    ],
)
def test_status_uses_the_default_five_point_tolerance(variance, expected) -> None:
    assert logic.status_for(variance) == expected


def test_status_honours_a_custom_tolerance() -> None:
    assert logic.status_for(8, 10) == "on_track"
    assert logic.status_for(-8, 2) == "behind"


def test_tolerance_setting_is_read_from_project_metadata() -> None:
    assert logic.tolerance_from({}) == 5.0
    assert logic.tolerance_from(None) == 5.0
    assert logic.tolerance_from({"geo_hub.survey_tolerance_pct": 10}) == 10.0
    assert logic.tolerance_from({"geo_hub": {"survey_tolerance_pct": "7.5"}}) == 7.5
    assert logic.tolerance_from({"geo_hub.survey_tolerance_pct": 250}) == 5.0
    assert logic.tolerance_from({"geo_hub.survey_tolerance_pct": "x"}) == 5.0


def test_project_window_margin_is_thirty_days() -> None:
    assert logic.in_project_window(date(2025, 12, 2), "2026-01-01", "2026-12-31")
    assert not logic.in_project_window(date(2025, 12, 1), "2026-01-01", "2026-12-31")
    assert logic.in_project_window(date(2027, 1, 30), "2026-01-01", "2026-12-31")
    assert not logic.in_project_window(date(2027, 1, 31), "2026-01-01", "2026-12-31")
    assert logic.in_project_window(date(2030, 1, 1), None, None)


def test_bbox_distance() -> None:
    box = (13.40, 52.50, 13.41, 52.51)
    assert logic.bbox_distance_km(box, 52.505, 13.405) == 0.0
    assert logic.bbox_distance_km(box, 52.505, 13.50) == pytest.approx(6.1, abs=0.2)
