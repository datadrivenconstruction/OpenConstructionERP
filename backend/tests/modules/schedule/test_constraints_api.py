"""Constraint vocabulary at the API edge, in the XER importer and through run_cpm."""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.schedule.router import _parse_xer_tables
from app.modules.schedule.schemas import ActivityCreate, ActivityUpdate
from app.modules.schedule.validators import ConstraintConflictsWithLogic, ConstraintDateMissing
from tests.modules.schedule.test_cpm_unified import _act, _api, _perms  # noqa: F401

XER = (
    "ERMHDR\t8.4\n"
    "%T\tTASK\n"
    "%F\ttask_id\ttask_code\ttask_name\tcstr_type\tcstr_date\n"
    "%R\t101\tA1010\tPour slab\tCS_MEOB\t2026-06-12 17:00\n"
    "%R\t102\tA1020\tCure slab\tCS_ALAP\t\n"
    "%R\t103\tA1030\tStrip forms\tCS_ASAP\t\n"
)


def test_xer_rows_normalise_to_neutral_names():
    from app.modules.schedule.constraints import normalize_constraint

    rows = _parse_xer_tables(XER)["TASK"]
    assert [normalize_constraint(r["cstr_type"]) for r in rows] == [
        "finish_no_later",
        "as_late_as_possible",
        None,
    ]


def test_schemas_reject_unknown_constraint_and_bad_date():
    base = {"schedule_id": uuid.uuid4(), "name": "A", "start_date": "2026-05-01", "end_date": "2026-05-02"}
    with pytest.raises(ValueError, match="unknown constraint"):
        ActivityCreate(**base, constraint_type="whenever")
    with pytest.raises(ValueError, match="ISO date"):
        ActivityCreate(**base, constraint_type="must_start_on", constraint_date="soon")
    assert ActivityCreate(**base, constraint_type="CS_MSOA", constraint_date="2026-05-01").constraint_type == (
        "start_no_earlier"
    )
    with pytest.raises(ValueError, match="unknown constraint"):
        ActivityUpdate(constraint_type="nope")


@pytest.mark.asyncio
async def test_api_answers_422_for_an_unknown_constraint():
    async with _api("editor") as (client, svc, sched):
        body = {
            "schedule_id": str(sched.id),
            "name": "A",
            "start_date": "2026-05-01",
            "end_date": "2026-05-02",
            "constraint_type": "whenever",
        }
        assert (await client.post(f"/schedule/schedules/{sched.id}/activities/", json=body)).status_code == 422
        a = await _act(svc, sched.id, "A", 3)
        patched = await client.patch(f"/schedule/activities/{a.id}", json={"constraint_type": "whenever"})
        assert patched.status_code == 422


@pytest.mark.asyncio
async def test_run_cpm_reports_deadline_as_negative_float_and_warns_on_bad_dates():
    seven_day = {"work_days": [0, 1, 2, 3, 4, 5, 6], "exceptions": []}
    async with _api("editor", calendar=seven_day) as (client, svc, sched):
        a = await _act(svc, sched.id, "Pour", 5)
        b = await _act(svc, sched.id, "Cure", 5, after=a.id)
        broken = await _act(svc, sched.id, "Broken", 2)
        svc.activity_repo.rows[b.id].constraint_type = "CS_MEOB"  # raw XER spelling stored before the migration
        svc.activity_repo.rows[b.id].constraint_date = "2026-05-05"
        svc.activity_repo.rows[broken.id].constraint_type = "start_no_earlier"
        svc.activity_repo.rows[broken.id].constraint_date = "not a date"

        body = (await client.post(f"/schedule/schedules/{sched.id}/calculate-cpm/")).json()

        rows = {r["name"]: r for r in body["all_activities"]}
        assert rows["Cure"]["total_float"] < 0
        assert rows["Cure"]["is_critical"] is True
        assert rows["Pour"]["total_float"] < 0
        assert len(body["constraint_warnings"]) == 1
        assert "Broken" in body["constraint_warnings"][0]


@pytest.mark.asyncio
async def test_validation_rules_flag_missing_dates_and_conflicts():
    rows = [
        {"id": "1", "name": "NoDate", "constraint_type": "start_no_earlier"},
        {"id": "2", "name": "Fine", "constraint_type": "as_late_as_possible"},
        {
            "id": "3",
            "name": "Late",
            "constraint_type": "must_start_on",
            "constraint_date": "2026-05-01",
            "early_start_date": "2026-05-06",
        },
        {
            "id": "4",
            "name": "Ok",
            "constraint_type": "must_finish_on",
            "constraint_date": "2026-05-09",
            "early_finish_date": "2026-05-09",
        },
    ]
    context = ValidationContext(data={"activities": rows})
    missing = [r for r in await ConstraintDateMissing().validate(context) if not r.passed]
    assert [r.element_ref for r in missing] == ["1"]
    assert missing[0].severity.value == "error"
    conflicts = await ConstraintConflictsWithLogic().validate(context)
    assert [(r.element_ref, r.passed) for r in conflicts] == [("3", False), ("4", True)]
    assert conflicts[0].severity.value == "warning"
    assert conflicts[0].details["late_by_days"] == 5
