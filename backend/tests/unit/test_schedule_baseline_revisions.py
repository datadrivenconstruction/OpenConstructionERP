"""Programme baselines B0, B1, ...: labels, the one approved baseline, and its rule.

Worked example: a schedule captured as B0 and approved, then edited and
captured again as B1. Approving B1 must leave B0 untouched apart from its
approved flag, and exactly one baseline per schedule may be the approved one.
Pure: no database.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.schedule.baseline_revisions import effective_baseline, next_baseline_label
from app.modules.schedule.validators import SingleApprovedBaselinePerSchedule


@pytest.mark.parametrize(
    ("existing", "label"),
    [
        ([], "B0"),
        (["B0"], "B1"),
        (["B0", "B1"], "B2"),
        (["Original programme", "B0"], "B1"),
        (["Original programme"], "B0"),
        (["B3", "b1"], "B4"),
        (["B0 tender", "B1"], "B2"),
    ],
)
def test_the_next_label_counts_on_from_the_highest_b_number(existing: list[str], label: str) -> None:
    assert next_baseline_label(existing) == label


def _bl(name: str, *, active: bool, approved_at: str | None = None, created_at: str = "2026-01-01T00:00:00") -> dict:
    meta = {"approval": {"approved_at": approved_at}} if approved_at else {}
    return {"id": name, "name": name, "is_active": active, "metadata": meta, "created_at": created_at}


def test_the_effective_baseline_is_the_latest_approved_active_one() -> None:
    rows = [
        _bl("B0", active=True, approved_at="2026-01-10T09:00:00"),
        _bl("B1", active=True, approved_at="2026-02-10T09:00:00"),
        _bl("B2", active=False, created_at="2026-03-01T00:00:00"),
    ]
    assert effective_baseline(rows)["name"] == "B1"


def test_without_approval_stamps_the_newest_active_baseline_wins() -> None:
    rows = [
        _bl("Old", active=True, created_at="2026-01-01T00:00:00"),
        _bl("New", active=True, created_at="2026-02-01T00:00:00"),
    ]
    assert effective_baseline(rows)["name"] == "New"


def test_no_active_baseline_means_none() -> None:
    assert effective_baseline([_bl("B0", active=False)]) is None
    assert effective_baseline([]) is None


async def _run(baselines: list[dict]) -> list:
    rule = SingleApprovedBaselinePerSchedule()
    return await rule.validate(ValidationContext(data={"baselines": baselines}))


@pytest.mark.asyncio
async def test_two_approved_baselines_on_one_schedule_fail() -> None:
    results = await _run(
        [
            {"id": "b0", "name": "B0", "schedule_id": "s1", "is_active": True},
            {"id": "b1", "name": "B1", "schedule_id": "s1", "is_active": True},
            {"id": "x0", "name": "B0", "schedule_id": "s2", "is_active": True},
        ]
    )
    failed = [r for r in results if not r.passed]
    assert len(failed) == 1
    assert failed[0].element_ref == "s1"
    assert failed[0].details["baselines"] == ["B0", "B1"]
    assert "B0" in failed[0].message and "B1" in failed[0].message
    assert [r.element_ref for r in results if r.passed] == ["s2"]


@pytest.mark.asyncio
async def test_saved_versions_that_are_not_approved_do_not_count() -> None:
    results = await _run(
        [
            {"id": "b0", "name": "B0", "schedule_id": "s1", "is_active": True},
            {"id": "b1", "name": "B1", "schedule_id": "s1", "is_active": False},
        ]
    )
    assert all(r.passed for r in results)
