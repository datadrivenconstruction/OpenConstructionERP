"""What counts as a milestone and as complete, for the milestone announcement.

The database half, where the transitions publish, lives in
tests/integration/test_schedule_milestone_events.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.schedule.milestone_events import is_completed, is_milestone


@pytest.mark.parametrize("activity_type", ["milestone", "start_milestone", "finish_milestone"])
def test_every_milestone_type_counts(activity_type: str) -> None:
    assert is_milestone(SimpleNamespace(activity_type=activity_type))


@pytest.mark.parametrize("activity_type", ["task", "summary", "", None])
def test_work_and_summaries_are_not_milestones(activity_type: str | None) -> None:
    """A zero-duration task is still a task: an undated activity has zero duration too."""
    assert not is_milestone(SimpleNamespace(activity_type=activity_type, duration_days=0))


@pytest.mark.parametrize(
    ("status", "progress", "expected"),
    [
        ("completed", "0", True),
        ("in_progress", "100", True),
        ("in_progress", "100.0", True),
        ("in_progress", 100.0, True),
        ("in_progress", "99.9", False),
        ("not_started", "0", False),
        ("not_started", "", False),
        ("not_started", None, False),
    ],
)
def test_complete_is_status_or_full_progress(status: str, progress: object, expected: bool) -> None:
    assert is_completed(status, progress) is expected
